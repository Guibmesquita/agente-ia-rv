"""
API para testar o agente de IA sem usar WhatsApp.
Simula todas as funcionalidades do webhook mas não registra em whatsapp_messages.
Usa o mesmo pipeline EnhancedSearch do WhatsApp para garantir comportamento idêntico.
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


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: str
    knowledge_used: Optional[List[dict]] = None
    intent: Optional[str] = None


def _get_enhanced_search():
    """Retorna instância do EnhancedSearch com o mesmo vector_store do agente."""
    try:
        from services.semantic_search import EnhancedSearch
        from services.vector_store import get_vector_store
        vs = get_vector_store()
        if vs:
            return EnhancedSearch(vs)
    except Exception as e:
        print(f"[AGENT_TEST] Erro ao criar EnhancedSearch: {e}")
    return None


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
    message = request.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Mensagem não pode estar vazia")

    if user_id not in test_conversations:
        test_conversations[user_id] = []

    if user_id not in test_session_data:
        test_session_data[user_id] = {"identified_assessor": None}

    history = test_conversations[user_id]
    session = test_session_data[user_id]

    history_for_ai = [
        {
            "role": msg["role"],
            "content": msg["content"],
            "metadata": msg.get("metadata", {})
        }
        for msg in history[-10:]
    ]

    from services.query_rewriter import rewrite_query
    rewrite_result = await rewrite_query(message, history_for_ai, openai_agent.client)

    search_query = rewrite_result.rewritten_query

    knowledge_context = ""
    search_results = []
    query_intent = None
    entities_detected = rewrite_result.entities.copy()

    try:
        enhanced = _get_enhanced_search()
        if enhanced and not rewrite_result.clarification_needed:
            from services.vector_store import filter_expired_results
            raw_results = enhanced.search(
                query=search_query,
                n_results=6,
                conversation_id=f"test_{user_id}",
                similarity_threshold=0.8,
                db=db
            )
            # Filtrar expirados e converter para dict para compatibilidade
            raw_dicts = [
                {
                    "content": r.content,
                    "metadata": r.metadata,
                    "distance": r.vector_distance,
                    "composite_score": r.composite_score,
                    "confidence_level": r.confidence_level,
                }
                for r in raw_results
            ]
            search_results_filtered = filter_expired_results(raw_dicts, db)[:5]

            # Enriquecer de volta com composite_score
            filtered_ids = {d.get("metadata", {}).get("block_id") for d in search_results_filtered}
            search_results = [
                r for r in raw_results
                if r.metadata.get("block_id") in filtered_ids
            ] if filtered_ids else []

            # Extrair query_intent e entities do primeiro resultado (todos têm o mesmo)
            if raw_results:
                extra = getattr(raw_results[0], 'extra_meta', {})
                query_intent = extra.get('query_intent')
                is_comparative = extra.get('is_comparative', False)

            # Extrair entidades detectadas dos metadados dos resultados
            seen_tickers = set()
            for r in search_results:
                ticker = r.metadata.get('product_ticker', '')
                if ticker and ticker not in seen_tickers:
                    seen_tickers.add(ticker)
                    entities_detected.append(ticker)

            if search_results:
                if is_comparative and len(entities_detected) >= 2:
                    tickers_str = " e ".join(entities_detected[:3])
                    knowledge_context = (
                        f"\n\nINSTRUÇÃO DE RESPOSTA: Esta é uma consulta COMPARATIVA entre {tickers_str}. "
                        f"Você DEVE comparar os fundos diretamente. NÃO continue o tópico anterior da conversa. "
                        f"Organize a resposta em seções separadas por fundo.\n"
                    )
                    results_by_product = {}
                    for r in search_results:
                        pname = r.metadata.get("product_name", "Outros")
                        if pname not in results_by_product:
                            results_by_product[pname] = []
                        results_by_product[pname].append(r)

                    idx = 1
                    for pname, prod_results in results_by_product.items():
                        knowledge_context += f"\n--- {pname} ---\n"
                        for r in prod_results:
                            title = r.metadata.get("document_title", r.metadata.get("source", "Documento"))
                            block_type = r.metadata.get("block_type", "")
                            score = r.composite_score
                            content = r.content[:500]
                            knowledge_context += f"\n[{idx}] {title}"
                            if block_type:
                                knowledge_context += f" [{block_type}]"
                            knowledge_context += f" [score:{score:.2f}]"
                            knowledge_context += f":\n{content}\n"
                            idx += 1
                else:
                    knowledge_context = "\n\n--- Informações da Base de Conhecimento ---\n"
                    for i, r in enumerate(search_results, 1):
                        title = r.metadata.get("document_title", r.metadata.get("source", "Documento"))
                        product_name = r.metadata.get("product_name", "")
                        block_type = r.metadata.get("block_type", "")
                        score = r.composite_score
                        content = r.content[:500]
                        knowledge_context += f"\n[{i}] {title}"
                        if product_name:
                            knowledge_context += f" (Produto: {product_name})"
                        if block_type:
                            knowledge_context += f" [{block_type}]"
                        knowledge_context += f" [score:{score:.2f}]"
                        knowledge_context += f":\n{content}\n"
                print(f"[AGENT_TEST] EnhancedSearch: {len(search_results)} docs | intent={query_intent} | entities={entities_detected}")
            else:
                print(f"[AGENT_TEST] EnhancedSearch: nenhum resultado para '{message[:50]}'")
        else:
            print("[AGENT_TEST] EnhancedSearch indisponível, seguindo sem contexto RAG")
    except Exception as e:
        print(f"[AGENT_TEST] Erro na busca EnhancedSearch: {e}")
        import traceback
        traceback.print_exc()

    try:
        response, should_create_ticket, context = await openai_agent.generate_response(
            message,
            history_for_ai,
            extra_context=knowledge_context if knowledge_context else None,
            sender_phone=None,
            identified_assessor=session.get("identified_assessor"),
            rewrite_result=rewrite_result
        )

        if context and context.get("identified_assessor"):
            session["identified_assessor"] = context["identified_assessor"]
            test_session_data[user_id] = session

    except Exception as e:
        print(f"[AGENT_TEST] Erro ao gerar resposta: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao gerar resposta: {str(e)}")

    # Montar lista de documentos para o frontend (com composite_score)
    knowledge_documents_raw = search_results if search_results else (
        context.get("documents", []) if context else []
    )

    history.append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now().isoformat()
    })

    history.append({
        "role": "assistant",
        "content": response,
        "timestamp": datetime.now().isoformat(),
        "knowledge_used": [
            {
                "title": r.metadata.get("document_title", r.metadata.get("source", "Documento")),
                "composite_score": round(r.composite_score, 3),
                "block_type": r.metadata.get("block_type", ""),
                "product": r.metadata.get("product_name", ""),
            }
            for r in knowledge_documents_raw
            if hasattr(r, 'metadata')
        ] if knowledge_documents_raw and hasattr(knowledge_documents_raw[0], 'metadata') else [],
        "metadata": context if context else {}
    })

    test_conversations[user_id] = history[-20:]

    identified = session.get("identified_assessor")
    intent_from_context = context.get("intent") if context else None

    return TestMessageResponse(
        response=response,
        should_create_ticket=should_create_ticket,
        intent=intent_from_context,
        query_type=query_intent,
        entities_detected=entities_detected if entities_detected else None,
        knowledge_documents=[
            {
                "title": (
                    r.metadata.get("document_title", r.metadata.get("source", "Documento"))
                    if hasattr(r, 'metadata')
                    else doc.get("metadata", {}).get("document_title", "Documento")
                    if isinstance(doc, dict) else "Documento"
                ),
                "category": (
                    r.metadata.get("category", "")
                    if hasattr(r, 'metadata')
                    else doc.get("metadata", {}).get("category", "")
                    if isinstance(doc, dict) else ""
                ),
                "content_preview": (
                    (r.content[:200] + "..." if len(r.content) > 200 else r.content)
                    if hasattr(r, 'content')
                    else (doc.get("content", "")[:200] + "..." if len(doc.get("content", "")) > 200 else doc.get("content", ""))
                    if isinstance(doc, dict) else ""
                ),
                "composite_score": round(r.composite_score, 3) if hasattr(r, 'composite_score') else None,
                "block_type": r.metadata.get("block_type", "") if hasattr(r, 'metadata') else "",
                "product": r.metadata.get("product_name", "") if hasattr(r, 'metadata') else "",
            }
            for doc, r in [
                (d, d) if hasattr(d, 'metadata') else (d, type('_', (), {'metadata': d.get('metadata', {}), 'content': d.get('content', ''), 'composite_score': d.get('composite_score', 0)})())
                for d in knowledge_documents_raw
            ]
        ],
        conversation_length=len(history),
        identified_assessor={
            "nome": identified.get("nome"),
            "broker": identified.get("broker"),
            "equipe": identified.get("equipe"),
            "unidade": identified.get("unidade")
        } if identified else None,
        rewritten_query=rewrite_result.rewritten_query if rewrite_result.rewritten_query != message else None,
        topic_switch=rewrite_result.topic_switch if rewrite_result.topic_switch else None,
        is_comparative=rewrite_result.is_comparative if rewrite_result.is_comparative else None,
        clarification_needed=rewrite_result.clarification_needed if rewrite_result.clarification_needed else None
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
