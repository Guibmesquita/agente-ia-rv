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
    retrieval_strategy: Optional[str] = None
    is_implicit_continuation: Optional[bool] = None
    emotional_tone: Optional[str] = None
    tool_calls: Optional[List[dict]] = None


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


def _normalize_doc_for_response(doc) -> dict:
    """Converte SearchResult ou dict em formato padronizado para resposta da API."""
    if hasattr(doc, 'metadata'):
        meta = doc.metadata
        content = doc.content or ""
        return {
            "title": meta.get("document_title", meta.get("source", "Documento")),
            "category": meta.get("category", ""),
            "content_preview": (content[:200] + "...") if len(content) > 200 else content,
            "composite_score": round(doc.composite_score, 3) if hasattr(doc, 'composite_score') else None,
            "block_type": meta.get("block_type", ""),
            "product": meta.get("product_name", ""),
        }
    elif isinstance(doc, dict):
        meta = doc.get("metadata", {})
        content = doc.get("content", "")
        return {
            "title": meta.get("document_title", "Documento"),
            "category": meta.get("category", ""),
            "content_preview": (content[:200] + "...") if len(content) > 200 else content,
            "composite_score": doc.get("composite_score"),
            "block_type": meta.get("block_type", ""),
            "product": meta.get("product_name", ""),
        }
    return {
        "title": "Documento",
        "category": "",
        "content_preview": "",
        "composite_score": None,
        "block_type": "",
        "product": "",
    }


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
    for msg in history[-20:]:
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

    from services.query_rewriter import rewrite_query
    rewrite_result = await rewrite_query(message, history_for_ai, openai_agent.client)

    if rewrite_result and rewrite_result.topic_switch and session.get("last_session_summary"):
        history_for_ai = [h for h in history_for_ai if h.get("role") != "system" or "[Contexto da sessão anterior]" not in h.get("content", "")]
        print(f"[AGENT_TEST] Topic switch detectado — removendo resumo de sessão anterior")

    search_query = rewrite_result.rewritten_query

    knowledge_context = ""
    search_results = []
    query_intent = None
    entities_detected = rewrite_result.entities.copy()
    retrieval_start = datetime.now()

    try:
        skip_search = rewrite_result.clarification_needed or rewrite_result.categoria in ("SAUDACAO", "ATENDIMENTO_HUMANO", "FORA_ESCOPO")
        enhanced = _get_enhanced_search()
        if enhanced and not skip_search:
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
                block_ids = [r.metadata.get("block_id") for r in search_results if r.metadata.get("block_id")]
                block_contents_map = {}
                if block_ids:
                    try:
                        from database.models import ContentBlock as CB
                        from services.content_formatter import get_rich_content
                        int_ids = []
                        for bid in block_ids:
                            try:
                                int_ids.append(int(str(bid).split("_")[-1]) if "_" in str(bid) else int(bid))
                            except (ValueError, TypeError):
                                pass
                        if int_ids:
                            blocks = db.query(CB.id, CB.content).filter(CB.id.in_(int_ids)).all()
                            block_contents_map = {b.id: b.content for b in blocks}
                    except Exception as e:
                        print(f"[AGENT_TEST] Erro ao buscar content_blocks originais: {e}")
                
                def _resolve_content(r):
                    block_id_raw = r.metadata.get("block_id")
                    if block_id_raw:
                        try:
                            int_bid = int(str(block_id_raw).split("_")[-1]) if "_" in str(block_id_raw) else int(block_id_raw)
                            original = block_contents_map.get(int_bid)
                            if original:
                                from services.content_formatter import get_rich_content
                                return get_rich_content(original, r.content, max_chars=800)
                        except (ValueError, TypeError):
                            pass
                    return r.content[:800]
                
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
                            content = _resolve_content(r)
                            mid = r.metadata.get("material_id")
                            mid_info = f" [material_id={mid}]" if mid else ""
                            knowledge_context += f"\n[{idx}] {title}{mid_info}"
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
                        mid = r.metadata.get("material_id")
                        score = r.composite_score
                        content = _resolve_content(r)
                        mid_info = f" [material_id={mid}]" if mid else ""
                        knowledge_context += f"\n[{i}] {title}{mid_info}"
                        if product_name:
                            knowledge_context += f" (Produto: {product_name})"
                        if block_type:
                            knowledge_context += f" [{block_type}]"
                        knowledge_context += f" [score:{score:.2f}]"
                        knowledge_context += f":\n{content}\n"
                print(f"[AGENT_TEST] EnhancedSearch: {len(search_results)} docs | intent={query_intent} | entities={entities_detected}")

                if search_results:
                    seen_product_ids = set()
                    for r in search_results:
                        pid = r.metadata.get("product_id")
                        mid = r.metadata.get("material_id")
                        if pid:
                            seen_product_ids.add(int(pid))
                        elif mid:
                            try:
                                from database.models import Material as Mat
                                mat_obj = db.query(Mat.product_id).filter(Mat.id == int(mid)).first()
                                if mat_obj:
                                    seen_product_ids.add(mat_obj.product_id)
                            except Exception:
                                pass
                    if seen_product_ids:
                        try:
                            from database.models import Material, Product, MaterialFile
                            materials_with_files = (
                                db.query(Material, Product.name, Product.ticker)
                                .join(Product, Product.id == Material.product_id)
                                .join(MaterialFile, MaterialFile.material_id == Material.id)
                                .filter(Material.product_id.in_(list(seen_product_ids)))
                                .filter(Material.publish_status != "arquivado")
                                .all()
                            )
                            if materials_with_files:
                                materials_by_product = {}
                                for mat, prod_name, prod_ticker in materials_with_files:
                                    key = prod_ticker or prod_name
                                    if key not in materials_by_product:
                                        materials_by_product[key] = []
                                    type_labels = {
                                        'one_page': 'One Pager', 'apresentacao': 'Apresentação',
                                        'comite': 'Material do Comitê', 'relatorio': 'Relatório',
                                        'lamina': 'Lâmina',
                                    }
                                    label = type_labels.get(mat.material_type, mat.material_type or mat.name or 'Documento')
                                    materials_by_product[key].append(f"[ID:{mat.id}] {mat.name or label}")
                                knowledge_context += "\n--- Materiais com PDF disponível para envio ---\n"
                                for prod_key, mat_list in materials_by_product.items():
                                    knowledge_context += f"{prod_key}: {', '.join(mat_list)}\n"
                                knowledge_context += "Para enviar um material, use a função send_document com o material_id correspondente.\n"
                        except Exception as e:
                            print(f"[AGENT_TEST] Erro ao listar materiais disponíveis: {e}")
            else:
                print(f"[AGENT_TEST] EnhancedSearch: nenhum resultado para '{message[:50]}'")
        elif skip_search:
            print(f"[AGENT_TEST] Busca RAG pulada — categoria={rewrite_result.categoria}")
        else:
            print("[AGENT_TEST] EnhancedSearch indisponível, seguindo sem contexto RAG")
    except Exception as e:
        print(f"[AGENT_TEST] Erro na busca EnhancedSearch: {e}")
        import traceback
        traceback.print_exc()

    retrieval_time = int((datetime.now() - retrieval_start).total_seconds() * 1000)

    from services.conversation_memory import build_context_dedup_instruction
    dedup_instruction = build_context_dedup_instruction(history_for_ai, message)
    full_context = knowledge_context
    if dedup_instruction:
        full_context = (full_context or "") + dedup_instruction

    try:
        response, should_create_ticket, context = await openai_agent.generate_response(
            message,
            history_for_ai,
            extra_context=full_context if full_context else None,
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

    session["last_response_at"] = datetime.now()
    test_session_data[user_id] = session

    try:
        import json as _json
        from database.models import RetrievalLog
        chunks_retrieved = []
        chunk_versions = {}
        min_distance = None
        max_distance = None
        log_query_type = None
        is_human_transfer = should_create_ticket or (context and context.get("human_transfer"))
        transfer_reason = context.get("transfer_reason") if context else None

        for r in search_results:
            if hasattr(r, 'metadata'):
                bid = r.metadata.get("block_id", "")
                if bid:
                    chunks_retrieved.append(bid)
                    chunk_versions[bid] = r.metadata.get("version", "1")
                dist = r.vector_distance if hasattr(r, 'vector_distance') else 0
                if min_distance is None or dist < min_distance:
                    min_distance = dist
                if max_distance is None or dist > max_distance:
                    max_distance = dist
                if not log_query_type:
                    extra = getattr(r, 'extra_meta', {}) if hasattr(r, 'extra_meta') else {}
                    log_query_type = extra.get('query_intent', query_intent or 'conceptual')

        retrieval_log = RetrievalLog(
            query=message,
            query_type=log_query_type or query_intent,
            chunks_retrieved=_json.dumps(chunks_retrieved) if chunks_retrieved else None,
            chunks_used=_json.dumps(chunks_retrieved[:3]) if chunks_retrieved else None,
            chunk_versions=_json.dumps(chunk_versions) if chunk_versions else None,
            result_count=len(search_results),
            min_distance=str(round(min_distance, 4)) if min_distance is not None else None,
            max_distance=str(round(max_distance, 4)) if max_distance is not None else None,
            threshold_applied="0.8",
            human_transfer=is_human_transfer,
            transfer_reason=transfer_reason,
            user_id=user_id,
            conversation_id=f"test_{user_id}",
            response_time_ms=retrieval_time
        )
        db.add(retrieval_log)
        db.commit()
    except Exception as log_err:
        print(f"[AGENT_TEST] Erro ao salvar RetrievalLog (não-bloqueante): {log_err}")

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
            _normalize_doc_for_response(d)
            for d in knowledge_documents_raw
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
        clarification_needed=rewrite_result.clarification_needed if rewrite_result.clarification_needed else None,
        retrieval_strategy=rewrite_result.retrieval_strategy if rewrite_result.retrieval_strategy != "rag" else None,
        is_implicit_continuation=rewrite_result.is_implicit_continuation if rewrite_result.is_implicit_continuation else None,
        emotional_tone=rewrite_result.emotional_tone if rewrite_result.emotional_tone != "neutral" else None,
        tool_calls=context.get("tool_calls") if context and context.get("tool_calls") else None
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
