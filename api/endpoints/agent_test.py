"""
API para testar o agente de IA sem usar WhatsApp.
Usa Pipeline V2 (agentic RAG) — mesmo pipeline do WhatsApp.
Histórico isolado por usuário.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
from datetime import datetime

from database.database import get_db
from database.models import User
from api.endpoints.auth import get_current_user
from services.openai_agent import openai_agent

router = APIRouter(prefix="/api/agent", tags=["Agent Test"])

test_conversations: Dict[int, List[dict]] = {}
test_session_data: Dict[int, Dict[str, Any]] = {}


class TestMessageRequest(BaseModel):
    message: str


class TestMessageResponse(BaseModel):
    response: str
    should_create_ticket: bool
    intent: Optional[str]
    query_type: Optional[str] = None
    entities_detected: Optional[List[str]] = None
    knowledge_documents: List[dict]
    conversation_length: int
    identified_assessor: Optional[Dict[str, Any]] = None
    rewritten_query: Optional[str] = None
    topic_switch: Optional[bool] = None
    is_comparative: Optional[bool] = None
    clarification_needed: Optional[bool] = None
    retrieval_strategy: Optional[str] = None
    is_implicit_continuation: Optional[bool] = None
    emotional_tone: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    pipeline: Optional[str] = None
    iterations: Optional[int] = None
    elapsed_ms: Optional[int] = None
    visual_image: Optional[str] = None
    visual_caption: Optional[str] = None


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: str
    knowledge_used: Optional[List[dict]] = None
    intent: Optional[str] = None


@router.post("/test", response_model=TestMessageResponse)
async def test_agent_message(
    request: TestMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Testa uma mensagem com o agente de IA.
    Usa EnhancedSearch (mesmo pipeline do WhatsApp) para garantir comportamento idêntico.
    Histórico é isolado por usuário.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    user_id = current_user.id
    from services.conversation_flow import normalize_message
    message = normalize_message(request.message)

    if not message:
        raise HTTPException(status_code=400, detail="Mensagem não pode estar vazia")

    if user_id not in test_conversations:
        test_conversations[user_id] = []

    if user_id not in test_session_data:
        test_session_data[user_id] = {"identified_assessor": None}

    history = test_conversations[user_id]
    session = test_session_data[user_id]

    try:
        SESSION_GAP_MINUTES = 120
        last_ts = session.get("last_response_at")
        if last_ts:
            from datetime import timedelta
            gap = datetime.now() - last_ts
            if gap > timedelta(minutes=SESSION_GAP_MINUTES) and len(history) >= 4:
                from services.conversation_memory import generate_session_summary
                history_for_summary = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in history[-10:]
                ]
                old_summary = await generate_session_summary(history_for_summary, openai_agent.client)
                if old_summary:
                    session["last_session_summary"] = old_summary
                    test_conversations[user_id] = []
                    history = test_conversations[user_id]
                    print(f"[AGENT_TEST] Gap de sessão detectado ({gap}), resumo gerado")
    except Exception as e:
        print(f"[AGENT_TEST] Erro na detecção de sessão (não-bloqueante): {e}")

    history_for_ai = []
    for msg in history[-30:]:
        entry = {
            "role": msg["role"],
            "content": msg["content"],
            "metadata": msg.get("metadata", {})
        }
        if msg.get("timestamp"):
            entry["timestamp"] = msg["timestamp"]
        history_for_ai.append(entry)

    if session.get("last_session_summary"):
        history_for_ai = [{"role": "system", "content": f"[Contexto da sessão anterior]: {session['last_session_summary']}"}] + history_for_ai

    from services.query_rewriter import rewrite_query as _test_rewrite_query
    _test_rewrite_result = None
    try:
        _test_rw_history = [m for m in history_for_ai if m.get("role") in ("user", "assistant")][-10:]
        _test_rewrite_result = await _test_rewrite_query(
            message=message,
            history=_test_rw_history,
            client=openai_agent.client,
            timeout_seconds=3.0,
        )
    except Exception as _rw_err:
        print(f"[AGENT_TEST] QueryRewriter falhou (não-bloqueante): {_rw_err}")

    try:
        response, should_create_ticket, context = await openai_agent.generate_response_v2(
            user_message=message,
            conversation_history=history_for_ai,
            sender_phone=None,
            identified_assessor=session.get("identified_assessor"),
            db=db,
            conversation_id=f"test_{user_id}",
            allow_tools=True,
            rewrite_result=_test_rewrite_result,
        )

        if context and context.get("identified_assessor"):
            session["identified_assessor"] = context["identified_assessor"]
            test_session_data[user_id] = session

    except Exception as e:
        print(f"[AGENT_TEST] Erro ao gerar resposta V2: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao gerar resposta: {str(e)}")

    session["last_response_at"] = datetime.now()
    test_session_data[user_id] = session

    # Task #196 — telemetria do playground precisa ser visível. Antes este
    # try/except absorvia silenciosamente qualquer falha (ex.: rollback de
    # transação anterior), apagando o rastro do playground inteiro. Agora:
    #  1. Logamos o tipo do erro + traceback completo no console.
    #  2. Forçamos rollback da sessão para não contaminar requisições
    #     subsequentes (sintoma observado em prod: nenhum RetrievalLog do
    #     playground por horas após uma única falha).
    #  3. Mantemos não-bloqueante para o usuário — a resposta do agente já
    #     foi gerada e nunca deve ser invalidada por falha de telemetria.
    try:
        import json as _json
        from database.models import RetrievalLog
        is_human_transfer = should_create_ticket or (context and context.get("human_transfer"))
        transfer_reason = context.get("transfer_reason") if context else None

        tool_calls_for_log = context.get("tool_calls", []) if context else []
        tools_used = [
            {"name": tc.get("name"), "iteration": tc.get("iteration")}
            for tc in (tool_calls_for_log or [])
        ]
        search_result_count = sum(
            1 for tc in (tool_calls_for_log or [])
            if tc.get("name") in ("search_knowledge_base", "search_web")
            and tc.get("result_preview", "").strip()
            and "erro" not in tc.get("result_preview", "").lower()[:50]
        )

        retrieval_log = RetrievalLog(
            query=message,
            query_type="v2_agentic",
            result_count=search_result_count,
            threshold_applied="v2_auto",
            human_transfer=is_human_transfer,
            transfer_reason=transfer_reason,
            user_id=user_id,
            conversation_id=f"test_{user_id}",
            response_time_ms=context.get("elapsed_ms") if context else None,
            chunks_retrieved=_json.dumps(tools_used, ensure_ascii=False) if tools_used else None,
        )
        db.add(retrieval_log)
        db.commit()
    except Exception as log_err:
        import traceback as _tb
        print(
            f"[AGENT_TEST][TELEMETRY] Falha ao gravar RetrievalLog (não-bloqueante) — "
            f"{type(log_err).__name__}: {log_err}"
        )
        print(_tb.format_exc())
        try:
            db.rollback()
        except Exception as _rb_err:
            print(f"[AGENT_TEST][TELEMETRY] Rollback também falhou: {_rb_err}")

    knowledge_documents = []
    if context and context.get("tool_calls"):
        for tc in context["tool_calls"]:
            if tc.get("name") == "search_knowledge_base":
                knowledge_documents.append({
                    "title": f"Tool: {tc['name']}",
                    "category": "",
                    "content_preview": tc.get("result_preview", "")[:200],
                    "composite_score": None,
                    "block_type": "tool_result",
                    "product": "",
                })

    history.append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now().isoformat()
    })

    history.append({
        "role": "assistant",
        "content": response,
        "timestamp": datetime.now().isoformat(),
        "metadata": context if context else {}
    })

    test_conversations[user_id] = history[-30:]

    identified = session.get("identified_assessor")
    intent_from_context = context.get("intent") if context else None

    visual_image_b64 = None
    visual_caption_str = None
    visual_blocks = context.get("visual_blocks") if context else None
    print(f"[AGENT_TEST] Visual blocks from context: {len(visual_blocks) if visual_blocks else 0}")
    if visual_blocks:
        try:
            from services.visual_decision import select_best_visual_block, should_send_visual
            from services.visual_extractor import get_visual_base64
            for vb in visual_blocks:
                trigger_match = should_send_visual(vb, message)
                print(f"[AGENT_TEST] Visual candidate block_id={vb.get('block_id')}, "
                      f"type={vb.get('block_type')}, trigger_match={trigger_match}")
            best_visual = select_best_visual_block(visual_blocks, message)
            if best_visual and best_visual.get("block_id"):
                print(f"[AGENT_TEST] Selected visual block_id={best_visual['block_id']}, extracting image...")
                visual_result = get_visual_base64(best_visual["block_id"], db)
                if visual_result:
                    visual_image_b64 = visual_result["base64"]
                    caption_parts = []
                    if best_visual.get("visual_description"):
                        caption_parts.append(best_visual["visual_description"][:200])
                    if best_visual.get("material_name"):
                        caption_parts.append(f"Fonte: {best_visual['material_name']}")
                    if best_visual.get("source_page"):
                        caption_parts.append(f"Página {best_visual['source_page']}")
                    visual_caption_str = " | ".join(caption_parts) if caption_parts else "Referência visual"
                    print(f"[AGENT_TEST] Visual reference sent: block_id={best_visual['block_id']}, "
                          f"fallback={visual_result['used_fallback']}, size={visual_result['size_bytes']}B")
                else:
                    print(f"[AGENT_TEST] Visual extraction returned None for block_id={best_visual['block_id']}")
            else:
                print(f"[AGENT_TEST] No visual block selected (triggers not matched or no eligible blocks)")
        except Exception as vis_err:
            import traceback
            print(f"[AGENT_TEST] Erro ao gerar referência visual: {vis_err}")
            traceback.print_exc()

    return TestMessageResponse(
        response=response,
        should_create_ticket=should_create_ticket,
        intent=intent_from_context,
        knowledge_documents=knowledge_documents,
        conversation_length=len(history),
        identified_assessor={
            "nome": identified.get("nome"),
            "broker": identified.get("broker"),
            "equipe": identified.get("equipe"),
            "unidade": identified.get("unidade")
        } if identified else None,
        tool_calls=context.get("tool_calls") if context and context.get("tool_calls") else None,
        pipeline=context.get("pipeline") if context else None,
        iterations=context.get("iterations") if context else None,
        elapsed_ms=context.get("elapsed_ms") if context else None,
        visual_image=visual_image_b64,
        visual_caption=visual_caption_str,
    )


@router.delete("/test/clear")
async def clear_test_conversation(
    current_user: User = Depends(get_current_user)
):
    """
    Limpa o histórico de conversa de teste do usuário atual.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    user_id = current_user.id

    if user_id in test_conversations:
        del test_conversations[user_id]

    if user_id in test_session_data:
        del test_session_data[user_id]

    return {"success": True, "message": "Conversa de teste limpa com sucesso"}


@router.get("/test/history")
async def get_test_history(
    current_user: User = Depends(get_current_user)
):
    """
    Retorna o histórico de conversa de teste do usuário atual.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    user_id = current_user.id
    history = test_conversations.get(user_id, [])

    return {
        "messages": history,
        "total": len(history)
    }
