"""
Gerenciamento de memória conversacional persistente com debounce.

Camada 1 — Sessão ativa: mensagens recentes carregadas do banco (com cache em memória).
Camada 2 — Resumo de sessão anterior: resumo GPT da sessão anterior (armazenado em conversations).
Camada 3 — Histórico completo: permanece no banco, acessível via "Carregar mais".

Debounce: acumula mensagens rápidas (6s) antes de processar.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import desc


SESSION_GAP_HOURS = 2
HISTORY_WINDOW = 20
INCREMENTAL_SUMMARY_THRESHOLD = 20
DEBOUNCE_SECONDS = 12

_history_cache: Dict[str, list] = {}

_pending: Dict[str, dict] = {}
_locks: Dict[str, asyncio.Lock] = {}
_processing_locks: Dict[str, asyncio.Lock] = {}
_active_tasks: set = set()


def _get_lock(phone: str, lock_dict: dict = None) -> asyncio.Lock:
    target = lock_dict if lock_dict is not None else _locks
    if phone not in target:
        target[phone] = asyncio.Lock()
    return target[phone]


def load_history_from_db(phone: str, db: Session, limit: int = HISTORY_WINDOW, after_timestamp=None) -> list:
    from database.models import WhatsAppMessage, MessageDirection

    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.phone == phone,
        WhatsAppMessage.message_type == "text",
        WhatsAppMessage.body.isnot(None),
        WhatsAppMessage.body != "",
    )

    if after_timestamp:
        query = query.filter(WhatsAppMessage.created_at > after_timestamp)

    messages = (
        query
        .order_by(desc(WhatsAppMessage.created_at))
        .limit(limit * 2)
        .all()
    )

    messages.reverse()

    history = []
    for msg in messages:
        ts = msg.created_at.isoformat() if msg.created_at else None
        if msg.direction == MessageDirection.INBOUND.value or not msg.from_me:
            if msg.body:
                entry = {"role": "user", "content": msg.body}
                if ts:
                    entry["timestamp"] = ts
                history.append(entry)
        elif msg.direction == MessageDirection.OUTBOUND.value or msg.from_me:
            content = msg.ai_response or msg.body
            if content:
                entry = {"role": "assistant", "content": content}
                if ts:
                    entry["timestamp"] = ts
                if msg.ai_intent:
                    entry["metadata"] = {"intent": msg.ai_intent}
                history.append(entry)

    return history[-limit:]


def get_history(phone: str, db: Session) -> list:
    if phone in _history_cache and _history_cache[phone]:
        return _history_cache[phone]

    history = load_history_from_db(phone, db)
    _history_cache[phone] = history
    print(f"[MEMORY] Histórico carregado do banco para {phone}: {len(history)} mensagens")
    return history


def update_history(phone: str, history: list):
    _history_cache[phone] = history[-HISTORY_WINDOW:]


def append_to_history(phone: str, role: str, content: str, metadata: dict = None):
    if phone not in _history_cache:
        _history_cache[phone] = []
    entry = {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
    if metadata:
        entry["metadata"] = metadata
    _history_cache[phone].append(entry)
    _history_cache[phone] = _history_cache[phone][-HISTORY_WINDOW:]


def build_context_dedup_instruction(history: list, current_message: str, recency_seconds: int = 60) -> Optional[str]:
    """
    Analisa o histórico recente de conversa para detectar respostas do bot
    que já cobriram tópicos similares à pergunta atual. Retorna instrução
    para a IA focar em questões novas, ou None se não há deduplicação necessária.

    Condições para ativar dedup:
    1. Deve haver pelo menos uma resposta recente do bot no histórico
    2. A resposta deve ter timestamp e ser recente (dentro de recency_seconds, default 60s)
       Mensagens sem timestamp são ignoradas (não elegíveis para dedup)
    3. Deve haver sobreposição de palavras-chave entre a pergunta atual
       e as perguntas/respostas anteriores (indicando mesmo tópico)
    """
    if not history or len(history) < 2:
        return None

    now = datetime.now()
    recent_pairs = []
    i = len(history) - 1
    while i >= max(0, len(history) - 8):
        msg = history[i]
        if msg.get("role") == "assistant" and msg.get("content"):
            ts_str = msg.get("timestamp")
            if not ts_str:
                i -= 1
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "").replace("+00:00", ""))
                if (now - ts).total_seconds() > recency_seconds:
                    i -= 1
                    continue
            except (ValueError, TypeError):
                i -= 1
                continue

            user_q = None
            if i > 0 and history[i - 1].get("role") == "user":
                user_q = history[i - 1].get("content", "")
            recent_pairs.append({
                "user_question": user_q or "",
                "bot_response": msg["content"][:300],
            })
        i -= 1

    if not recent_pairs:
        return None

    def _extract_keywords(text: str) -> set:
        import re as _re
        words = set(_re.findall(r'[a-záàâãéêíóôõúüç]{3,}', text.lower()))
        stopwords = {
            'que', 'qual', 'como', 'para', 'com', 'por', 'uma', 'dos', 'das',
            'nos', 'nas', 'esse', 'essa', 'sobre', 'mais', 'pode', 'tem',
            'não', 'sim', 'são', 'foi', 'está', 'ser', 'ter', 'fala', 'isso',
            'aqui', 'ali', 'dele', 'dela', 'meu', 'sua', 'nos', 'nós', 'eles',
        }
        return words - stopwords

    current_kw = _extract_keywords(current_message)
    if not current_kw:
        return None

    overlapping_responses = []
    for pair in recent_pairs:
        prev_kw = _extract_keywords(pair["user_question"] + " " + pair["bot_response"])
        overlap = current_kw & prev_kw
        if len(overlap) >= 2 or (len(overlap) >= 1 and len(current_kw) <= 3):
            overlapping_responses.append(pair["bot_response"])

    if not overlapping_responses:
        print(f"[CONTEXT_DEDUP] Sem sobreposição de tópicos detectada — dedup não necessário")
        return None

    bot_summary = " | ".join(overlapping_responses[:2])

    instruction = (
        f"\n\n⚠️ ATENÇÃO — CONTEXTO DE MENSAGENS ANTERIORES:\n"
        f"Você JÁ respondeu recentemente sobre tópicos relacionados nesta conversa:\n"
        f'"{bot_summary[:500]}"\n\n'
        f"REGRAS OBRIGATÓRIAS:\n"
        f"1. NÃO repita informações que você já forneceu nas respostas acima.\n"
        f"2. Foque EXCLUSIVAMENTE na nova pergunta do usuário: \"{current_message[:200]}\"\n"
        f"3. Se a nova pergunta pede algo diferente do que você já respondeu, "
        f"responda APENAS sobre o novo assunto.\n"
        f"4. Se a nova pergunta é uma continuação, complemente com informações NOVAS, "
        f"sem repetir os dados já enviados."
    )

    print(f"[CONTEXT_DEDUP] Sobreposição detectada com {len(overlapping_responses)} resposta(s) recente(s) — instrução de dedup gerada")
    return instruction


def detect_session_gap(phone: str, db: Session) -> bool:
    from database.models import WhatsAppMessage, MessageDirection

    last_msg = (
        db.query(WhatsAppMessage.created_at)
        .filter(
            WhatsAppMessage.phone == phone,
            WhatsAppMessage.direction == MessageDirection.OUTBOUND.value,
        )
        .order_by(desc(WhatsAppMessage.created_at))
        .first()
    )

    if not last_msg or not last_msg.created_at:
        return False

    last_time = last_msg.created_at
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return (now - last_time) > timedelta(hours=SESSION_GAP_HOURS)


async def generate_session_summary(history: list, client) -> str:
    if not history or not client:
        return ""

    recent_msgs = history[-HISTORY_WINDOW:]
    if len(recent_msgs) < 2:
        return ""

    lines = []
    for msg in recent_msgs:
        content = msg.get("content", "")
        if content:
            label = "Assessor" if msg.get("role") == "user" else "Stevan"
            lines.append(f"{label}: {content[:200]}")

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Resuma a conversa abaixo em 2-3 frases concisas. "
                            "Foque nos ativos/produtos discutidos, decisões tomadas, "
                            "e qualquer pedido pendente. Formato: texto corrido, sem bullets."
                        )
                    },
                    {"role": "user", "content": "\n".join(lines)}
                ],
                max_tokens=150,
                temperature=0.3
            )
        )
        summary = response.choices[0].message.content.strip()
        print(f"[MEMORY] Resumo de sessão gerado: {summary[:100]}...")
        return summary
    except Exception as e:
        print(f"[MEMORY] Erro ao gerar resumo de sessão: {e}")
        return ""


async def handle_session_transition(phone: str, db: Session, conversation):
    if not detect_session_gap(phone, db):
        return

    print(f"[MEMORY] Gap de sessão detectado para {phone}")

    old_history = _history_cache.get(phone, [])
    if not old_history:
        old_history = load_history_from_db(phone, db)

    if old_history and len(old_history) >= 2:
        try:
            from services.openai_agent import openai_agent
            if openai_agent.client:
                summary = await generate_session_summary(old_history, openai_agent.client)
                if summary and conversation:
                    conversation.last_session_summary = summary
                    conversation.last_session_ended_at = datetime.now(timezone.utc)
                    db.commit()
                    print(f"[MEMORY] Resumo salvo na conversa {conversation.id}")
        except Exception as e:
            print(f"[MEMORY] Erro ao salvar resumo de sessão: {e}")

    _history_cache[phone] = []

    if conversation and getattr(conversation, 'last_session_ended_at', None):
        fresh_history = load_history_from_db(phone, db, after_timestamp=conversation.last_session_ended_at)
        if fresh_history:
            _history_cache[phone] = fresh_history
            print(f"[MEMORY] Histórico pós-gap carregado: {len(fresh_history)} msgs da sessão atual")


async def maybe_incremental_summary(phone: str, db: Session, conversation) -> Optional[str]:
    if not conversation:
        return None

    history = _history_cache.get(phone, [])
    if len(history) < INCREMENTAL_SUMMARY_THRESHOLD:
        return None

    try:
        from services.openai_agent import openai_agent
        if not openai_agent.client:
            return None

        older_msgs = history[:INCREMENTAL_SUMMARY_THRESHOLD // 2]
        summary = await generate_session_summary(older_msgs, openai_agent.client)

        if summary:
            _history_cache[phone] = history[INCREMENTAL_SUMMARY_THRESHOLD // 2:]

            prev_summary = getattr(conversation, 'last_session_summary', '') or ''
            if prev_summary:
                combined_summary = f"{prev_summary} | {summary}"
            else:
                combined_summary = summary

            if len(combined_summary) > 500:
                combined_summary = combined_summary[-500:]

            conversation.last_session_summary = combined_summary
            db.commit()
            print(f"[MEMORY] Resumo incremental gerado para {phone}: {summary[:80]}... (histórico reduzido para {len(_history_cache[phone])} msgs)")
            return summary
    except Exception as e:
        print(f"[MEMORY] Erro no resumo incremental: {e}")

    return None


def build_context_with_summary(history: list, conversation, rewrite_result=None) -> list:
    if not conversation:
        return history

    summary = getattr(conversation, 'last_session_summary', None)
    if not summary:
        return history

    if rewrite_result and rewrite_result.topic_switch:
        print(f"[MEMORY] Topic switch detectado — ignorando resumo de sessão anterior")
        return history

    return [{"role": "system", "content": f"[Contexto da sessão anterior]: {summary}"}] + history


def schedule_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task


async def enqueue_message(
    phone: str,
    body: str,
    message_record_id: Optional[int],
    conversation_id: Optional[int],
    db_factory,
    process_fn
):
    lock = _get_lock(phone)
    async with lock:
        if phone not in _pending:
            _pending[phone] = {"messages": [], "timer": None, "db_factory": db_factory, "process_fn": process_fn}

        _pending[phone]["messages"].append({
            "body": body,
            "message_record_id": message_record_id,
            "conversation_id": conversation_id,
        })

        old_timer = _pending[phone].get("timer")
        if old_timer and not old_timer.done():
            old_timer.cancel()
            print(f"[DEBOUNCE] Timer resetado para {phone} — {len(_pending[phone]['messages'])} msgs acumuladas")

        timer = asyncio.create_task(_flush_after_delay(phone))
        _active_tasks.add(timer)
        timer.add_done_callback(_active_tasks.discard)
        _pending[phone]["timer"] = timer

        if len(_pending[phone]["messages"]) == 1:
            print(f"[DEBOUNCE] Timer de {DEBOUNCE_SECONDS}s iniciado para {phone}")


async def _flush_after_delay(phone: str):
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return

    lock = _get_lock(phone)
    async with lock:
        data = _pending.get(phone)
        if not data or not data["messages"]:
            return
        messages = list(data["messages"])
        db_factory = data["db_factory"]
        process_fn = data["process_fn"]

    proc_lock = _get_lock(phone, _processing_locks)
    async with proc_lock:
        try:
            db = db_factory()
        except Exception as e:
            print(f"[DEBOUNCE] Erro ao criar sessão DB para {phone}: {e}")
            return

        try:
            from database.models import WhatsAppMessage, Conversation

            async with lock:
                _pending.pop(phone, None)

            first = messages[0]
            conversation = db.query(Conversation).filter(
                Conversation.id == first["conversation_id"]
            ).first() if first["conversation_id"] else None

            message_record = db.query(WhatsAppMessage).filter(
                WhatsAppMessage.id == first["message_record_id"]
            ).first() if first["message_record_id"] else None

            if len(messages) == 1:
                combined_body = first["body"]
                print(f"[DEBOUNCE] Processando 1 mensagem de {phone}")
            else:
                combined_body = "\n".join(m["body"] for m in messages if m["body"])
                print(f"[DEBOUNCE] Processando {len(messages)} msgs acumuladas de {phone}: {combined_body[:100]}...")

                for extra in messages[1:]:
                    if extra["message_record_id"]:
                        extra_rec = db.query(WhatsAppMessage).filter(
                            WhatsAppMessage.id == extra["message_record_id"]
                        ).first()
                        if extra_rec:
                            extra_rec.ai_intent = "debounced_merged"
                            db.commit()

            await process_fn(phone, combined_body, db, message_record, conversation)

        except Exception as e:
            print(f"[DEBOUNCE] Erro ao processar msgs de {phone}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            db.close()
