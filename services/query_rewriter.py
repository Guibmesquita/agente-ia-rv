"""
Query Rewriter com Contexto Conversacional (V2 — GPT-4o + Análise Enriquecida).

Recebe a mensagem atual + histórico e produz:
- query reescrita autocontida (pronomes resolvidos, contexto incorporado)
- classificação de intenção (substitui _classify_message)
- entidades detectadas
- flags: is_comparative, topic_switch, clarification_needed
- campos enriquecidos: retrieval_strategy, is_implicit_continuation, resolved_context, emotional_tone
"""
import json
import re
import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from openai import OpenAI


@dataclass
class QueryRewriteResult:
    rewritten_query: str
    categoria: str
    entities: List[str] = field(default_factory=list)
    is_comparative: bool = False
    topic_switch: bool = False
    clarification_needed: bool = False
    clarification_text: str = ""
    original_message: str = ""
    used_fallback: bool = False
    retrieval_strategy: str = "rag"
    is_implicit_continuation: bool = False
    resolved_context: str = ""
    emotional_tone: str = "neutral"
    manager_query: str = ""


REWRITER_SYSTEM_PROMPT = """Você é um módulo interno de pré-processamento de mensagens. Seu papel é analisar a mensagem atual de um assessor financeiro, junto com o histórico recente da conversa, e produzir uma versão da mensagem que seja autocontida — ou seja, que faça sentido sozinha, sem precisar ler o histórico.

REGRAS DE REESCRITA:

1. SE a mensagem já é clara e autocontida (tem ativo/produto explícito + tipo de pergunta claro), retorne-a com MÍNIMAS alterações. Não adicione contexto desnecessário.

2. SE a mensagem tem pronomes ou referências vagas ("dele", "desse", "disso", "os dois", "ambos"), resolva-os usando o histórico. Exemplos:
   - "qual o DY dele?" (histórico falava de BTLG11) → "qual o DY do BTLG11?"
   - "os dois" / "ambos" → substituir pelos 2 últimos ativos distintos mencionados no histórico

3. SE a mensagem tem um marcador de troca de tópico ("ok", "beleza", "certo", "tá", "blz") seguido de novo ativo ou pergunta, trate como NOVA PERGUNTA — ignore o contexto do tópico anterior. Marque topic_switch=true.
   - "ok, e MANA11?" (histórico era sobre BTLG11) → "informações sobre o fundo MANA11" (NÃO comparar com BTLG11)

4. SE a mensagem é extremamente curta (≤3 palavras), sem verbo, sem palavra de pergunta, E sem histórico que dê contexto suficiente, marque clarification_needed=true e forneça uma pergunta de esclarecimento natural. Exemplos:
   - "BTLG11" (sem histórico) → clarification_needed=true, texto: "BTLG11 está na minha base! O que você gostaria de saber sobre esse fundo?"
   - "BTLG11" (com histórico sobre carteiras) → "carteira de ativos do BTLG11" (infere do padrão anterior, NÃO pede clarificação)

5. NUNCA adicione comparações que o assessor não pediu explicitamente. Se ele perguntou sobre UM ativo, a query deve ser sobre UM ativo.

6. A mensagem atual tem PRIORIDADE ABSOLUTA sobre o histórico. O histórico serve apenas para resolver ambiguidades.

7. CONTINUAÇÕES IMPLÍCITAS: quando o assessor responde algo curto que continua o tópico anterior (ex: "e a vacância?", "e o prazo?", "quanto tá rendendo?"), marque is_implicit_continuation=true e preencha resolved_context com o que foi inferido do histórico.

CLASSIFICAÇÃO DE INTENÇÃO (campo "categoria"):
- SAUDACAO: cumprimentos simples sem conteúdo ("oi", "bom dia", "tudo bem?")
- DOCUMENTAL: perguntas sobre produtos/fundos/ativos específicos que precisam da base de conhecimento
- ESCOPO: perguntas gerais sobre renda variável, estratégia SVN, comitê, recomendações atuais. Inclui perguntas sobre "produto do mês", "comitê", "o que a SVN recomenda"
- MERCADO: perguntas sobre cotações ATUAIS, notícias, eventos do dia, índices em TEMPO REAL (IFIX, IBOV, CDI, SELIC, dólar)
- PITCH: pedido para criar texto de venda, pitch comercial, argumento de vendas
- ATENDIMENTO_HUMANO: SOMENTE quando o assessor pede EXPLICITAMENTE para falar com uma PESSOA, HUMANO ou BROKER
- FORA_ESCOPO: piadas, assuntos pessoais, temas completamente não relacionados a finanças

Para "categoria", use os mesmos critérios do assessor financeiro: perguntas sobre comitê/produto do mês = ESCOPO com entidade "COMITE".

ESTRATÉGIA DE BUSCA (campo "retrieval_strategy"):
- "rag": buscar apenas na base de conhecimento interna (padrão para maioria das perguntas)
- "web": buscar apenas na web (cotações atuais, notícias do dia, eventos em tempo real)
- "hybrid": buscar tanto na base interna quanto na web (comparações entre ativo interno e mercado, perguntas que precisam de dados internos + contexto de mercado)
- "none": não precisa de busca (saudações, fora de escopo)

DETECÇÃO DE GESTORA (campo "manager_query"):
- Se o assessor está CLARAMENTE perguntando sobre uma gestora/asset manager específica (ex: "me fala sobre a Kinea", "quais fundos da XP vocês recomendam?", "o que a Hedge tem?"), preencha com o nome da gestora mencionada.
- NÃO preencha se "xp" aparece apenas dentro de outra palavra (ex: "explicar", "experiência") ou como parte de um nome de fundo/ativo (ex: "XP Log Prime", "XPAG11").
- NÃO preencha se o assessor está perguntando sobre um conceito, estrutura ou produto genérico (ex: "o que é uma booster?", "como funciona um put spread?").
- Exemplos:
  - "me fala sobre a Kinea" → manager_query: "Kinea"
  - "quais fundos da XP?" → manager_query: "XP Asset"
  - "o que é uma booster?" → manager_query: "" (é conceito, não gestora)
  - "consegue me explicar?" → manager_query: "" (a palavra "explicar" contém "xp" mas não é gestora)
  - "XP Log Prime II" → manager_query: "" (é nome de fundo, não menção à gestora)
  - "o que a Hedge Investments tem?" → manager_query: "Hedge Investments"

TOM EMOCIONAL (campo "emotional_tone"):
- "neutral": pergunta técnica normal
- "urgent": assessor com urgência ou pressão
- "frustrated": assessor demonstra frustração ou insatisfação
- "curious": assessor explorando ou aprendendo
- "friendly": conversa mais leve e próxima

FORMATO DE SAÍDA (JSON):
{
  "rewritten_query": "query reescrita autocontida",
  "categoria": "DOCUMENTAL",
  "entities": ["BTLG11"],
  "is_comparative": false,
  "topic_switch": false,
  "clarification_needed": false,
  "clarification_text": "",
  "retrieval_strategy": "rag",
  "is_implicit_continuation": false,
  "resolved_context": "",
  "emotional_tone": "neutral",
  "manager_query": ""
}

Retorne APENAS o JSON, sem explicação."""


def _build_rewriter_messages(message: str, history: Optional[List[dict]] = None) -> list:
    messages = [{"role": "system", "content": REWRITER_SYSTEM_PROMPT}]

    history_text = ""
    if history:
        recent = history[-20:]
        lines = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                label = "Assessor" if role == "user" else "Stevan"
                lines.append(f"{label}: {content}")
        if lines:
            history_text = "\n".join(lines)

    user_content = ""
    if history_text:
        user_content = f"HISTÓRICO RECENTE:\n{history_text}\n\nMENSAGEM ATUAL:\n{message}"
    else:
        user_content = f"MENSAGEM ATUAL (sem histórico):\n{message}"

    messages.append({"role": "user", "content": user_content})
    return messages


def _fallback_classify(message: str) -> QueryRewriteResult:
    msg_lower = message.lower().strip()

    greetings = ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite",
                 "e aí", "e ai", "tudo bem", "tudo bom", "hey", "fala"]
    if msg_lower in greetings or any(msg_lower.startswith(g) and len(msg_lower) < len(g) + 5 for g in greetings):
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="SAUDACAO",
            original_message=message,
            used_fallback=True,
            retrieval_strategy="none"
        )

    human_keywords = ["falar com alguém", "falar com humano", "chama o broker",
                      "atendimento humano", "falar com pessoa", "abre um chamado",
                      "abre um ticket"]
    if any(kw in msg_lower for kw in human_keywords):
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="ATENDIMENTO_HUMANO",
            original_message=message,
            used_fallback=True,
            retrieval_strategy="none"
        )

    market_keywords = ["cotação", "cotacao", "mercado hoje", "ifix", "ibov",
                       "selic", "cdi hoje", "dólar", "dolar"]
    if any(kw in msg_lower for kw in market_keywords):
        entities = []
        ticker_matches = re.findall(r'\b([A-Z]{4,5}(?:11|12|13)?)\b', message, re.IGNORECASE)
        entities = [t.upper() for t in ticker_matches]
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="MERCADO",
            entities=entities,
            original_message=message,
            used_fallback=True,
            retrieval_strategy="web"
        )

    pitch_keywords = ["pitch", "texto de venda", "argumento de vendas", "vender"]
    if any(kw in msg_lower for kw in pitch_keywords):
        entities = []
        ticker_matches = re.findall(r'\b([A-Z]{4,5}(?:11|12|13)?)\b', message, re.IGNORECASE)
        entities = [t.upper() for t in ticker_matches]
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="PITCH",
            entities=entities,
            original_message=message,
            used_fallback=True,
            retrieval_strategy="rag"
        )

    ticker_matches = re.findall(r'\b([A-Z]{4,5}(?:11|12|13)?)\b', message, re.IGNORECASE)
    entities = list(dict.fromkeys([t.upper() for t in ticker_matches]))

    comite_keywords = ["comitê", "comite", "produto do mês", "produto do mes",
                       "recomendações atuais", "recomendacoes atuais"]
    if any(kw in msg_lower for kw in comite_keywords):
        if "COMITE" not in entities:
            entities.append("COMITE")
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="ESCOPO",
            entities=entities,
            original_message=message,
            used_fallback=True,
            retrieval_strategy="rag"
        )

    if entities:
        return QueryRewriteResult(
            rewritten_query=message,
            categoria="DOCUMENTAL",
            entities=entities,
            is_comparative=len(entities) >= 2,
            original_message=message,
            used_fallback=True,
            retrieval_strategy="rag"
        )

    return QueryRewriteResult(
        rewritten_query=message,
        categoria="ESCOPO",
        entities=entities,
        original_message=message,
        used_fallback=True,
        retrieval_strategy="rag"
    )


def _parse_rewriter_response(raw: str, original_message: str) -> QueryRewriteResult:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    data = json.loads(cleaned)

    entities = data.get("entities", [])
    if isinstance(entities, list):
        entities = [str(e).upper() for e in entities if e]
    else:
        entities = []

    return QueryRewriteResult(
        rewritten_query=data.get("rewritten_query", original_message),
        categoria=data.get("categoria", "ESCOPO"),
        entities=entities,
        is_comparative=bool(data.get("is_comparative", False)),
        topic_switch=bool(data.get("topic_switch", False)),
        clarification_needed=bool(data.get("clarification_needed", False)),
        clarification_text=data.get("clarification_text", ""),
        original_message=original_message,
        used_fallback=False,
        retrieval_strategy=data.get("retrieval_strategy", "rag"),
        is_implicit_continuation=bool(data.get("is_implicit_continuation", False)),
        resolved_context=data.get("resolved_context", ""),
        emotional_tone=data.get("emotional_tone", "neutral"),
        manager_query=str(data.get("manager_query", "") or "").strip()[:100]
    )


async def rewrite_query(
    message: str,
    history: Optional[List[dict]] = None,
    client: Optional[OpenAI] = None,
    timeout_seconds: float = 5.0
) -> QueryRewriteResult:
    if not client:
        try:
            import os
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                print("[QueryRewriter] OPENAI_API_KEY não configurada, usando fallback")
                return _fallback_classify(message)
            client = OpenAI(api_key=api_key)
        except Exception as e:
            print(f"[QueryRewriter] Erro ao criar client OpenAI: {e}")
            return _fallback_classify(message)

    messages = _build_rewriter_messages(message, history)

    try:
        def _call_api():
            return client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.1,
                max_tokens=400,
                timeout=timeout_seconds
            )

        response = await asyncio.to_thread(_call_api)

        try:
            from services.cost_tracker import cost_tracker
            if response.usage:
                cost_tracker.track_openai_chat(
                    model="gpt-4o",
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    operation='query_rewriter'
                )
        except Exception:
            pass

        raw_content = response.choices[0].message.content.strip()

        result = _parse_rewriter_response(raw_content, message)
        print(
            f"[QueryRewriter] '{message[:60]}' → "
            f"query='{result.rewritten_query[:60]}' | "
            f"cat={result.categoria} | "
            f"entities={result.entities} | "
            f"comparative={result.is_comparative} | "
            f"topic_switch={result.topic_switch} | "
            f"clarification={result.clarification_needed} | "
            f"strategy={result.retrieval_strategy} | "
            f"implicit_cont={result.is_implicit_continuation} | "
            f"tone={result.emotional_tone}" +
            (f" | manager={result.manager_query}" if result.manager_query else "")
        )
        return result

    except json.JSONDecodeError as e:
        print(f"[QueryRewriter] Erro de parse JSON: {e} — usando fallback")
        return _fallback_classify(message)
    except asyncio.TimeoutError:
        print(f"[QueryRewriter] Timeout ({timeout_seconds}s) — usando fallback")
        return _fallback_classify(message)
    except Exception as e:
        print(f"[QueryRewriter] Erro inesperado: {e} — usando fallback")
        return _fallback_classify(message)
