"""
Pipeline V2: Definições de tools e executores para o loop agentic.
As tools são expostas ao GPT via OpenAI function calling.
Os executores reutilizam os serviços existentes (EnhancedSearch, web_search, fii_lookup).
"""
import json
import time
import asyncio
from typing import Dict, Any, List, Optional


TOOL_SEARCH_KNOWLEDGE_BASE = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "Busca na base de conhecimento interna da SVN sobre produtos financeiros "
            "(fundos, COEs, derivativos, FIIs, materiais de research). Use para dados ESTRATÉGICOS: "
            "preço-alvo, recomendação de compra/venda, racional de investimento, tese, análise "
            "fundamentalista, estratégias, diferenciais, riscos, campanhas. "
            "Ao citar dados desta tool, SEMPRE inclua o nome do documento como fonte. "
            "Para cotações e dados ao vivo, use search_web ou lookup_fii_public."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A consulta de busca. Seja específico: inclua ticker, nome do fundo, "
                        "ou termos-chave do que procura. Exemplos: 'BTLG11 rentabilidade histórica', "
                        "'Kinea Rendimentos estratégia', 'COE proteção capital estrutura'."
                    )
                }
            },
            "required": ["query"]
        }
    }
}

TOOL_SEARCH_WEB = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Busca na web por informações de mercado em tempo real: cotações atuais, preço, "
            "abertura, fechamento, variação, D/Y ao vivo, P/VP, volume, notícias recentes, "
            "eventos corporativos, resultados trimestrais, dados macroeconômicos "
            "(Selic, IPCA, IGPM, dólar, IFIX, IBOV). "
            "Use PROATIVAMENTE para qualquer pergunta sobre preços, cotações, indicadores ao vivo "
            "ou índices de mercado. NÃO peça permissão ao usuário — busque automaticamente. "
            "Para dados estratégicos (tese, racional, recomendação), use search_knowledge_base."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A consulta de busca para a web. Exemplos: 'cotação PETR4 hoje', "
                        "'Vale notícias recentes', 'Selic atual'."
                    )
                }
            },
            "required": ["query"]
        }
    }
}

TOOL_LOOKUP_FII = {
    "type": "function",
    "function": {
        "name": "lookup_fii_public",
        "description": (
            "Consulta dados públicos atuais de um FII (Fundo Imobiliário) no FundsExplorer: "
            "DY, P/VP, vacância, último rendimento, patrimônio, preço da cota. Use quando o "
            "assessor perguntar sobre indicadores quantitativos de mercado de um FII específico. "
            "Pode ser combinada com search_knowledge_base para dar análise qualitativa + dados atuais."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "O ticker do FII (ex: BTLG11, HGLG11, KNRI11)."
                }
            },
            "required": ["ticker"]
        }
    }
}

TOOL_SEND_DOCUMENT = {
    "type": "function",
    "function": {
        "name": "send_document",
        "description": (
            "Envia o PDF de um material cadastrado para o assessor via WhatsApp. "
            "Use APENAS quando o assessor pedir EXPLICITAMENTE para enviar, mandar ou "
            "compartilhar um material/PDF/documento/one-pager/lâmina. "
            "NUNCA use para gerar textos, pitches, resumos ou análises — isso é completamente diferente. "
            "Use apenas material_id da lista 'Materiais com PDF disponível' no system prompt."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": {
                    "type": "integer",
                    "description": "ID do material conforme lista no system prompt."
                },
                "product_name": {
                    "type": "string",
                    "description": "Nome do produto/fundo associado ao material."
                }
            },
            "required": ["material_id", "product_name"]
        }
    }
}

TOOL_REQUEST_HUMAN_HANDOFF = {
    "type": "function",
    "function": {
        "name": "request_human_handoff",
        "description": (
            "Solicita transferência para um broker/especialista humano. Use quando: "
            "o assessor pedir explicitamente para falar com alguém, quando a demanda "
            "exigir análise além do documentado, quando não houver informação suficiente "
            "após consultar as tools, ou quando o assessor demonstrar frustração clara."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Motivo da transferência. Ex: 'assessor pediu atendimento humano', "
                        "'demanda requer análise específica', 'informação não encontrada na base'."
                    )
                }
            },
            "required": ["reason"]
        }
    }
}

TOOL_SEND_PAYOFF_DIAGRAM = {
    "type": "function",
    "function": {
        "name": "send_payoff_diagram",
        "description": (
            "Envia o diagrama de payoff de uma estrutura de derivativos ao assessor. "
            "Use quando o assessor pedir explicitamente para ver/enviar/mostrar um diagrama, "
            "gráfico ou payoff de uma estrutura."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "structure_slug": {
                    "type": "string",
                    "description": (
                        "Slug da estrutura de derivativos. Slugs disponíveis: "
                        "booster, swap, collar-com-ativo, fence-com-ativo, step-up, "
                        "condor-strangle-com-hedge, condor-venda-strangle, venda-straddle, "
                        "compra-condor, compra-borboleta-fly, compra-straddle, compra-strangle, "
                        "compra-venda-opcoes, risk-reversal, compra-call-spread, seagull, "
                        "collar-sem-ativo, compra-put-spread, fence-sem-ativo, call-up-and-in, "
                        "call-up-and-out, put-down-and-in, put-down-and-out, ndf, financiamento, "
                        "venda-put-spread, venda-call-spread"
                    )
                },
                "structure_name": {
                    "type": "string",
                    "description": "Nome legível da estrutura."
                }
            },
            "required": ["structure_slug", "structure_name"]
        }
    }
}

ALL_TOOLS_V2 = [
    TOOL_SEARCH_KNOWLEDGE_BASE,
    TOOL_SEARCH_WEB,
    TOOL_LOOKUP_FII,
    TOOL_SEND_DOCUMENT,
    TOOL_SEND_PAYOFF_DIAGRAM,
    TOOL_REQUEST_HUMAN_HANDOFF,
]


async def execute_tool_call(tool_call, db=None, conversation_id=None) -> Dict[str, Any]:
    """
    Executa uma tool call solicitada pelo GPT.
    Reutiliza os serviços existentes — não reimplementa nada.
    
    Returns:
        Dict com o resultado da tool ou erro.
    """
    name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError):
        args = {}

    start_time = time.time()
    print(f"[V2 Tool Call] {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    try:
        if name == "search_knowledge_base":
            result = await _execute_search_knowledge_base(args, db, conversation_id)
        elif name == "search_web":
            result = await _execute_search_web(args, db)
        elif name == "lookup_fii_public":
            result = await _execute_lookup_fii(args)
        elif name == "send_document":
            result = await _validate_and_prepare_send_document(args, db)
        elif name == "send_payoff_diagram":
            result = {"action": "send_payoff_diagram", "structure_slug": args.get("structure_slug"), "structure_name": args.get("structure_name")}
        elif name == "request_human_handoff":
            result = {"action": "request_human_handoff", "reason": args.get("reason", "Solicitação de atendimento")}
        else:
            result = {"error": f"Tool desconhecida: {name}"}

        elapsed_ms = int((time.time() - start_time) * 1000)
        print(f"[V2 Tool Result] {name} — {elapsed_ms}ms — success")
        return result

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        print(f"[V2 Tool Error] {name} — {elapsed_ms}ms — {e}")
        return {"error": f"Erro ao executar {name}: {str(e)}"}


async def _execute_search_knowledge_base(args: dict, db=None, conversation_id=None) -> Dict[str, Any]:
    """Executa busca na base de conhecimento usando EnhancedSearch existente."""
    from services.semantic_search import EnhancedSearch
    from services.vector_store import get_vector_store, filter_expired_results

    query = args.get("query", "")
    if not query:
        return {"error": "Query vazia", "results": []}

    vector_store = get_vector_store()
    if not vector_store:
        return {"error": "Base de conhecimento indisponível", "results": []}

    enhanced = EnhancedSearch(vector_store)
    raw_results = enhanced.search(
        query=query,
        n_results=8,
        conversation_id=conversation_id,
        similarity_threshold=0.8,
        db=db
    )

    if not raw_results:
        return {"results": [], "message": "Nenhum resultado encontrado para a consulta."}

    if db:
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
        filtered = filter_expired_results(raw_dicts, db)[:6]
        filtered_ids = {d.get("metadata", {}).get("block_id") for d in filtered}
        if filtered_ids:
            raw_results = [
                r for r in raw_results
                if r.metadata.get("block_id") in filtered_ids
            ]
        else:
            raw_results = []
    else:
        raw_results = raw_results[:6]

    results = []
    materials_with_pdf = set()
    seen_product_ids = set()

    for r in raw_results:
        meta = r.metadata
        content = r.content

        if db:
            try:
                block_id_raw = meta.get("block_id")
                if block_id_raw:
                    from database.models import ContentBlock as CB
                    from services.content_formatter import get_rich_content
                    int_bid = int(str(block_id_raw).split("_")[-1]) if "_" in str(block_id_raw) else int(block_id_raw)
                    block = db.query(CB.content).filter(CB.id == int_bid).first()
                    if block:
                        content = get_rich_content(block.content, r.content, max_chars=800)
            except Exception:
                pass

        pid = meta.get("product_id")
        if pid:
            seen_product_ids.add(int(pid))

        material_name = meta.get("material_name", "") or meta.get("document_title", "Documento")
        results.append({
            "title": meta.get("document_title", "Documento"),
            "material_name": material_name,
            "product": meta.get("product_name", ""),
            "ticker": meta.get("products", ""),
            "content": content[:800],
            "score": round(r.composite_score, 3) if hasattr(r, 'composite_score') else None,
            "material_id": meta.get("material_id"),
            "block_type": meta.get("block_type", ""),
            "source_note": f"Ao citar dados deste resultado, inclua: (Fonte: {material_name})",
        })

    if db and seen_product_ids:
        try:
            from database.models import Material, Product, MaterialFile
            mats = (
                db.query(Material.id, Material.name, Product.name.label("pname"), Product.ticker)
                .join(Product, Product.id == Material.product_id)
                .join(MaterialFile, MaterialFile.material_id == Material.id)
                .filter(Material.product_id.in_(list(seen_product_ids)))
                .filter(Material.publish_status != "arquivado")
                .all()
            )
            for m in mats:
                materials_with_pdf.add(f"[ID:{m.id}] {m.pname} ({m.ticker}) - {m.name}")
        except Exception:
            pass

    response = {"results": results, "count": len(results)}
    if materials_with_pdf:
        response["materials_with_pdf"] = list(materials_with_pdf)

    return response


async def _execute_search_web(args: dict, db=None) -> Dict[str, Any]:
    """Executa busca na web usando o serviço Tavily existente."""
    from services.web_search import get_web_search_service

    query = args.get("query", "")
    if not query:
        return {"error": "Query vazia"}

    web_service = get_web_search_service()
    if not web_service.is_configured():
        return {"error": "Busca web não configurada (API key ausente)"}

    result = web_service.search_sync(query, db=db)
    if not result.get("success"):
        return {"error": f"Busca web falhou: {result.get('error', 'desconhecido')}"}

    if not result.get("results"):
        return {"results": [], "message": "Nenhum resultado encontrado na web."}

    if db:
        try:
            web_service.log_search(db=db, query=query, results=result, fallback_reason="GPT tool call")
        except Exception:
            pass

    formatted_results = []
    for r in result["results"][:5]:
        source_name = r.get("url", "")
        try:
            from urllib.parse import urlparse
            source_name = urlparse(r.get("url", "")).netloc or r.get("url", "")
        except Exception:
            pass
        formatted_results.append({
            "title": r.get("title", ""),
            "content": r.get("content", "")[:500],
            "url": r.get("url", ""),
            "published_date": r.get("published_date", ""),
            "source_note": f"Ao citar dados deste resultado, inclua: (Fonte: {source_name})",
        })

    return {"results": formatted_results, "count": len(formatted_results)}


async def _execute_lookup_fii(args: dict) -> Dict[str, Any]:
    """Consulta dados públicos de FII no FundsExplorer usando o serviço existente."""
    from services.fii_lookup import get_fii_lookup_service

    ticker = args.get("ticker", "").upper()
    if not ticker:
        return {"error": "Ticker não informado"}

    fii_service = get_fii_lookup_service()
    fii_result = fii_service.lookup(ticker)

    if not fii_result or not fii_result.get("data"):
        return {
            "error": f"Não encontrei dados públicos para {ticker} no FundsExplorer.",
            "ticker": ticker
        }

    fii_info = fii_service.format_complete_response(fii_result["data"])
    return {
        "ticker": ticker,
        "data": fii_info,
        "source": "FundsExplorer",
        "note": "Dados públicos — este fundo pode NÃO estar na base oficial de recomendações da SVN.",
        "source_note": "Ao citar dados deste resultado, inclua: (Fonte: FundsExplorer)",
    }


async def _validate_and_prepare_send_document(args: dict, db=None) -> Dict[str, Any]:
    material_id = args.get("material_id")
    product_name = args.get("product_name", "")

    if not material_id:
        return {"error": "material_id não informado"}

    if not db:
        return {"action": "send_document", "material_id": material_id, "product_name": product_name}

    try:
        from database.models import Material, MaterialFile
        material = db.query(Material).filter(Material.id == int(material_id)).first()
        if not material:
            return {"error": f"Material ID {material_id} não encontrado na base de dados."}

        if material.publish_status == "arquivado":
            return {"error": f"Material '{material.name}' está arquivado e não pode ser enviado."}

        has_file = db.query(MaterialFile).filter(MaterialFile.material_id == int(material_id)).first()
        if not has_file:
            return {"error": f"Material '{material.name}' não possui arquivo PDF disponível para envio."}

        return {"action": "send_document", "material_id": material_id, "product_name": product_name}

    except Exception as e:
        print(f"[V2 Tool] Erro ao validar send_document: {e}")
        return {"error": f"Erro ao validar material: {str(e)}"}
