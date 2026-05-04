"""
Pipeline V2: Definições de tools e executores para o loop agentic.
As tools são expostas ao GPT via OpenAI function calling.
Os executores reutilizam os serviços existentes (EnhancedSearch, web_search, fii_lookup).
"""
import json
import os
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
            "preço-alvo, racional de investimento, tese, análise fundamentalista, estratégias, "
            "diferenciais, riscos, campanhas. "
            "IMPORTANTE: cada resultado retornado inclui o campo 'comite_tag' que pode ser "
            "'[COMITÊ]' (recomendação formal aprovada pelo Comitê de Investimentos da SVN) ou "
            "'[NÃO-COMITÊ]' (material informativo — research, análise, apresentação, campanha). "
            "Use linguagem de recomendação formal SOMENTE para resultados '[COMITÊ]'. "
            "Para '[NÃO-COMITÊ]', você PODE informar, analisar e explicar o ativo, mas deve "
            "deixar claro que não é uma recomendação formal da SVN. "
            "Ao citar dados desta tool, SEMPRE inclua o nome do documento como fonte. "
            "Para cotações e dados ao vivo, use search_web ou lookup_fii_public. "
            "PAGINAÇÃO DE TABELAS GRANDES: a resposta inclui o campo 'has_more' e "
            "'next_offset' quando o conteúdo (ex.: tabela com 12+ linhas) foi truncado. "
            "Para ver as linhas restantes, refaça a busca com a MESMA query e o "
            "parâmetro 'offset' igual ao 'next_offset' retornado. NUNCA invente linhas "
            "que não vieram no resultado: se 'has_more' = true e o usuário pediu lista "
            "completa, faça nova chamada com offset."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A consulta de busca. Seja específico: inclua ticker, nome do fundo, "
                        "ou termos-chave do que procura. Exemplos: 'BTLG11 rentabilidade histórica', "
                        "'Kinea Rendimentos estratégia', 'COE proteção capital estrutura'. "
                        "Para listas exaustivas use termos como 'composição completa', "
                        "'todos os ativos', 'lista completa da carteira X'. "
                        "OBRIGATÓRIO no fluxo de busca; OPCIONAL apenas quando você está "
                        "continuando a leitura de um bloco específico via 'block_id' (nesse "
                        "caso pode ser omitido ou enviado como string vazia)."
                    )
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "Deslocamento de paginação (default 0). Use APENAS quando uma "
                        "chamada anterior retornou 'has_more: true' — informe o valor de "
                        "'next_offset' para receber os blocos seguintes da mesma sequência "
                        "de resultados. Útil para carteiras com muitas linhas (10+ FIIs, "
                        "20+ ações). Se a janela atual contém 'content_truncated_in_window: "
                        "true', paginar NÃO recupera mais conteúdo do mesmo bloco — refine "
                        "a query (ex.: peça um ticker específico)."
                    )
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Tamanho da janela retornada (default 6, máximo 20). Aumente para "
                        "10-20 quando o assessor pediu listagem exaustiva ('todos', "
                        "'completa', 'liste os N') para receber mais blocos de uma vez "
                        "em vez de paginar várias chamadas."
                    )
                },
                "block_id": {
                    "type": "integer",
                    "description": (
                        "Continuação intra-bloco. Use quando uma chamada anterior "
                        "retornou um resultado com 'content_truncated: true' — informe "
                        "o 'block_id' do bloco truncado E 'content_offset' = "
                        "'next_content_offset' para receber a continuação do MESMO "
                        "bloco (típico de tabelas grandes >4000 chars). Quando "
                        "'block_id' é fornecido, a busca semântica é IGNORADA e o "
                        "retorno traz apenas o bloco solicitado. Se omitido, executa "
                        "busca normal."
                    )
                },
                "content_offset": {
                    "type": "integer",
                    "description": (
                        "Posição (em caracteres) do conteúdo formatado do bloco a "
                        "partir da qual continuar a leitura. Use junto com 'block_id'. "
                        "Default 0. Use 'next_content_offset' devolvido pela chamada "
                        "anterior."
                    )
                }
            },
            # `query` é obrigatório no fluxo de busca. Para o fluxo de
            # continuação intra-bloco (`block_id` + `content_offset`), o
            # backend dispensa a validação. Mantemos o campo formalmente
            # como NÃO obrigatório no schema para permitir o fluxo de
            # continuação sem inflar a query com placeholder.
            "required": []
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


async def execute_tool_call_direct(name: str, args: dict, db=None, conversation_id=None) -> Dict[str, Any]:
    if name == "search_knowledge_base":
        return await _execute_search_knowledge_base(args, db, conversation_id)
    elif name == "search_web":
        return await _execute_search_web(args, db)
    elif name == "lookup_fii_public":
        return await _execute_lookup_fii(args)
    else:
        return {"error": f"Tool desconhecida: {name}"}


async def _execute_search_knowledge_base(args: dict, db=None, conversation_id=None) -> Dict[str, Any]:
    """Executa busca na base de conhecimento usando EnhancedSearch existente.

    RAG V3.6 — Mudanças nesta função:
      1. Detecta intenção de COMPLETUDE (carteira, lista exaustiva, "todos os...").
         Quando True:
           - Expande n_results de 12 → 20 para cobrir todas as linhas/blocos
             de uma carteira espalhada em múltiplos chunks.
           - Em vez de cortar para os 4 melhores blocos (top-4), AGRUPA por
             material_id e devolve TODOS os blocos do(s) material(is) com
             melhor pontuação acumulada. Isso garante que uma carteira de 12
             FIIs distribuída em 5 blocos sequenciais não seja cortada para 4.
           - Aumenta o `max_chars` do `get_rich_content` para 4000 (já era o
             default para tabelas, mas força mesmo se o `block_type` vier
             vazio em embeddings legados).
      2. Aceita parâmetro `offset` (default 0) — quando o agente recebe um
         resultado com `has_more: true` (tabela truncada), pode chamar de
         novo com `offset = next_offset` para receber a continuação.
    """
    from services.semantic_search import EnhancedSearch, TokenExtractor
    from services.vector_store import get_vector_store, filter_expired_results

    query = args.get("query", "")
    # RAG V3.6 — `query` é dispensável quando o agente está apenas continuando
    # a leitura de um bloco específico via `block_id`/`content_offset`. A
    # validação só dispara se NÃO houver block_id (fluxo de busca semântica).
    if not query and args.get("block_id") is None:
        return {"error": "Query vazia", "results": []}

    try:
        offset = int(args.get("offset", 0) or 0)
        if offset < 0:
            offset = 0
    except (TypeError, ValueError):
        offset = 0

    # Task #204 — Detecção de intenção movida para CIMA da definição de
    # `page_size` para que carteiras (que precisam caber inteiras na primeira
    # janela) ganhem default maior. `is_portfolio_intent` é mais estrito que
    # `is_completeness` e também dispara `search_by_portfolio` (lookup
    # relacional) dentro de EnhancedSearch, mais abaixo.
    is_completeness = TokenExtractor.detect_completeness_intent(query)
    is_portfolio_intent = TokenExtractor.detect_portfolio_intent(query)

    # RAG V3.6 — limit (tamanho da janela) define o page_size para a paginação
    # monotônica. Default 6 (cobre o caso comum de 1-2 carteiras + alguns
    # extras), máximo 20 (mesmo cap de n_results em modo completude).
    #
    # Task #204 — para queries de PORTFÓLIO o default sobe para 20: uma
    # carteira de 12-15 FIIs precisa caber inteira na primeira janela. Sem
    # isso o agente recebe 6 linhas + has_more=true e tem que paginar 2-3x
    # para ler a carteira completa, frequentemente respondendo "documento
    # incompleto" antes de paginar.
    _portfolio_default = 20 if is_portfolio_intent else 6
    try:
        page_size = int(args.get("limit", _portfolio_default) or _portfolio_default)
    except (TypeError, ValueError):
        page_size = _portfolio_default
    page_size = max(1, min(page_size, 20))

    # RAG V3.6 — Continuação intra-bloco. Quando o agente recebe um bloco
    # com `content_truncated: true`, pode chamar de novo com `block_id` e
    # `content_offset` para receber a continuação (próximos ~4000 chars do
    # MESMO bloco). Isso resolve o caso de uma tabela única que estoura o
    # cap de formatador (ex.: carteira de 30 FIIs num único bloco).
    raw_block_id = args.get("block_id")
    if raw_block_id is not None:
        try:
            req_block_id = int(raw_block_id)
        except (TypeError, ValueError):
            req_block_id = None
        try:
            content_offset = int(args.get("content_offset", 0) or 0)
            if content_offset < 0:
                content_offset = 0
        except (TypeError, ValueError):
            content_offset = 0
        if req_block_id is not None and db is not None:
            return await _continue_block_content(
                block_id=req_block_id,
                content_offset=content_offset,
                page_size_chars=4000,
                db=db,
            )

    vector_store = get_vector_store()
    if not vector_store:
        return {"error": "Base de conhecimento indisponível", "results": []}

    # Task #204 — `is_completeness` e `is_portfolio_intent` foram detectados
    # mais acima (antes do `page_size`) para parametrizar a janela. Aqui só
    # decidimos quantos resultados pedir do EnhancedSearch (n_results).
    n_results = 30 if is_portfolio_intent else (20 if is_completeness else 12)

    enhanced = EnhancedSearch(vector_store)
    raw_results = enhanced.search(
        query=query,
        n_results=n_results,
        conversation_id=conversation_id,
        similarity_threshold=0.4,
        db=db
    )

    if not raw_results:
        # Task #196 — sinal explícito para o LLM de que NADA foi recuperado.
        # `no_results: true` é referenciado pela REGRA 4 do prompt
        # (`_get_table_completeness_rules`), que proíbe inventar dados nesse
        # caso. A mensagem é deliberadamente directiva.
        return {
            "results": [],
            "no_results": True,
            "count": 0,
            "total_results": 0,
            "message": (
                "Nenhum resultado encontrado na base interna para a consulta. "
                "Material não indexado ou nome não corresponde a nenhum "
                "documento. NÃO INVENTE composição, tickers ou percentuais — "
                "siga a REGRA 4 do prompt e responda com transparência."
            ),
            "completeness_mode": is_completeness,
        }

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
        # RAG V3.6 — em modo completude, expandimos a janela pós-filtro de
        # expirados para 20 (n_results) em vez de cortar para 4. Os blocos
        # serão depois agrupados por material_id.
        post_filter_cap = n_results if is_completeness else 4
        filtered = filter_expired_results(raw_dicts, db)[:post_filter_cap]
        filtered_ids = {d.get("metadata", {}).get("block_id") for d in filtered}
        if filtered_ids:
            raw_results = [
                r for r in raw_results
                if r.metadata.get("block_id") in filtered_ids
            ]
        else:
            raw_results = []
    else:
        raw_results = raw_results[:n_results if is_completeness else 4]

    # Task #196 — se o pós-filtro de expirados esvaziou tudo, devolva o
    # mesmo sinal `no_results: true` que o caminho do bloco anterior, para
    # que o LLM aplique a REGRA 4 e não fabrique conteúdo. Sem este guard,
    # o for-loop adiante geraria `results: []` sem o sinal explícito.
    if not raw_results:
        return {
            "results": [],
            "no_results": True,
            "count": 0,
            "total_results": 0,
            "message": (
                "Nenhum resultado válido após filtro de expirados. "
                "Material possivelmente desatualizado ou inexistente. "
                "NÃO INVENTE composição — siga a REGRA 4 do prompt."
            ),
            "completeness_mode": is_completeness,
        }

    # Task #196 — terceiro guard: resultados existem mas TODOS com score
    # muito baixo significa "match fraco" (provavelmente o material pedido
    # não está na base, e o RAG devolveu blocos pouco relacionados). Tratar
    # como no_results para evitar que o agente tente "preencher" com
    # conteúdo de outra carteira/produto. Threshold conservador (0.30)
    # ajustável via env var `RAG_LOW_CONFIDENCE_THRESHOLD`.
    try:
        LOW_CONFIDENCE_THRESHOLD = float(
            os.environ.get("RAG_LOW_CONFIDENCE_THRESHOLD", "0.30")
        )
    except (TypeError, ValueError):
        LOW_CONFIDENCE_THRESHOLD = 0.30
    try:
        max_score = max(
            (getattr(r, "composite_score", 0.0) or 0.0) for r in raw_results
        )
    except Exception:
        max_score = 1.0  # Em caso de schema inesperado, não ative o guard.

    # Task #204 — Portfolio intent BYPASS do guard de baixa confiança.
    # Quando a query é portfolio E pelo menos 1 bloco veio do lookup
    # relacional (`portfolio_row` com source `portfolio_lookup` ou block_type
    # `portfolio_row`), o match é por NOME, não por similaridade vetorial.
    # O `composite_score` natural fica baixo porque o embedding "liste FIIs
    # da Seven" é distante semanticamente de cada linha "BTLG11: Peso=6%...",
    # mas o resultado é AUTORITATIVO (vem do banco relacional). Aplicar o
    # guard aqui esconderia a carteira inteira.
    has_portfolio_rows = any(
        (getattr(r, "metadata", None) or {}).get("block_type", "").lower() == "portfolio_row"
        for r in raw_results
    )
    portfolio_bypass = is_portfolio_intent and has_portfolio_rows
    if portfolio_bypass:
        print(
            f"[search_kb] Portfolio intent + portfolio_row blocks "
            f"(max_score={max_score:.2f}) → bypass do guard de baixa confiança."
        )

    if max_score < LOW_CONFIDENCE_THRESHOLD and not portfolio_bypass:
        return {
            "results": [],
            "no_results": True,
            "count": 0,
            "total_results": 0,
            "message": (
                f"Resultados encontrados mas com baixa relevância "
                f"(score máximo {max_score:.2f} < {LOW_CONFIDENCE_THRESHOLD:.2f}). "
                "Provavelmente o material exato não está na base. "
                "NÃO INVENTE composição nem reaproveite blocos de outro "
                "material como se fossem do solicitado — siga a REGRA 4 "
                "do prompt."
            ),
            "completeness_mode": is_completeness,
            "low_confidence_max_score": round(max_score, 3),
        }

    # RAG V3.6 — em modo completude, ao invés do top-4 padrão, devolvemos
    # TODOS os blocos do(s) material(is) com maior contagem de blocos
    # entre os top n. Isso preserva a integridade de tabelas/listas que
    # foram chunkificadas e garante que carteiras grandes não sejam
    # cortadas pela metade.
    if is_completeness and raw_results:
        from collections import OrderedDict
        material_buckets: "OrderedDict[Any, list]" = OrderedDict()
        for r in raw_results:
            mid = r.metadata.get("material_id") or r.metadata.get("doc_id") or "_no_material"
            material_buckets.setdefault(mid, []).append(r)
        # Materiais ordenados pelo MAIOR `composite_score` entre seus blocos
        # (relevância semântica do EnhancedSearch), não pela quantidade de
        # blocos — material mais relevante vence material mais fragmentado.
        # Fallback para `score` legado, depois 0. Empate mantém ordem
        # original (estabilidade). Mantemos os 2 melhores materiais para
        # evitar misturar carteiras distintas no mesmo retorno.
        def _block_score(b):
            cs = getattr(b, "composite_score", None)
            if cs is not None:
                try:
                    return float(cs)
                except (TypeError, ValueError):
                    pass
            try:
                return float(getattr(b, "score", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        def _bucket_score(kv):
            blocks = kv[1]
            if not blocks:
                return 0.0
            return max(_block_score(b) for b in blocks)
        ranked_materials = sorted(
            material_buckets.items(),
            key=lambda kv: -_bucket_score(kv),
        )
        kept = []
        for _mid, blocks in ranked_materials[:2]:
            kept.extend(blocks)
        raw_results = kept

    results = []
    materials_with_pdf = set()
    seen_product_ids = set()

    # Carregar product_ids do comitê ativo (recommendation_entries) para marcação universal
    _committee_product_ids: set = set()
    try:
        from services.vector_store import get_vector_store as _get_vs_tools
        _vs_tools = _get_vs_tools()
        _committee_product_ids = set(_vs_tools.get_active_committee_product_ids())
    except Exception as _e_com:
        pass

    # Task #153 — fallback de product_type por product_id, para embeddings antigos
    # que ainda não foram reindexados com o novo metadata. Sem isso, blocos
    # legados teriam tag genérica [COMITÊ] em vez de [COMITÊ-ESTRUTURADA] etc.
    #
    # Após o reembedding em massa (Task #153), o caminho quente NÃO precisa mais
    # exercitar este fallback: pulamos a consulta extra quando todos os resultados
    # já carregam `product_type` no metadata. A consulta JOIN permanece como safety
    # net para resultados de embeddings legados (ex.: doc_ids antigos sem product_id
    # ou sem product_type) que possam reaparecer no futuro.
    _product_type_by_id: dict = {}
    _needs_ptype_lookup_ids = set()
    try:
        for r in raw_results:
            _meta_pt = (r.metadata.get("product_type") or "").strip()
            _meta_pid = r.metadata.get("product_id")
            if not _meta_pt and _meta_pid and str(_meta_pid).isdigit():
                _needs_ptype_lookup_ids.add(int(_meta_pid))
        if db and _needs_ptype_lookup_ids:
            from database.models import Product as _Prod
            _rows = db.query(_Prod.id, _Prod.product_type).filter(
                _Prod.id.in_(_needs_ptype_lookup_ids)
            ).all()
            _product_type_by_id = {
                int(rid): (pt or "").lower() for rid, pt in _rows
            }
    except Exception as _e_pt:
        pass

    for r in raw_results:
        meta = r.metadata
        content = r.content

        # RAG V3.6 — guarda o block_type efetivo (do banco se disponível, do
        # metadata caso contrário) para decidir o cap final de `content` no
        # result_entry mais abaixo. Tabelas merecem 4000 chars; texto, 600.
        effective_block_type = (meta.get("block_type") or "").lower().strip()

        if db:
            try:
                block_id_raw = meta.get("block_id")
                if block_id_raw:
                    from database.models import ContentBlock as CB
                    from services.content_formatter import get_rich_content, TABLE_BLOCK_TYPES
                    int_bid = int(str(block_id_raw).split("_")[-1]) if "_" in str(block_id_raw) else int(block_id_raw)
                    # RAG V3.5/V3.6 — Recuperação rica de tabelas: buscamos o
                    # block_type do banco (mais confiável que o metadata, que
                    # pode estar vazio em embeddings legados) para que o
                    # formatter ative o path rico (Markdown + Fatos por linha +
                    # truncamento por linha, cap 4000) em vez do path de texto
                    # (cap 600). Sem isso, tabelas grandes (ex.: carteira
                    # "Seven FIIs" com 12 FIIs) eram cortadas pela metade.
                    block = db.query(CB.content, CB.block_type).filter(CB.id == int_bid).first()
                    if block:
                        if (block.block_type or "").lower().strip():
                            effective_block_type = (block.block_type or "").lower().strip()
                        content = get_rich_content(
                            block.content,
                            r.content,
                            max_chars=600,
                            block_type=block.block_type,
                        )
            except Exception:
                pass

        pid = meta.get("product_id")
        if pid:
            seen_product_ids.add(int(pid))

        material_name = meta.get("material_name", "") or meta.get("document_title", "Documento")

        block_id_raw = meta.get("block_id")
        int_block_id = None
        visual_desc = None
        source_page = None
        if block_id_raw and db:
            try:
                int_bid = int(str(block_id_raw).split("_")[-1]) if "_" in str(block_id_raw) else int(block_id_raw)
                int_block_id = int_bid
                from database.models import ContentBlock as CB2
                cb_row = db.query(CB2.source_page, CB2.visual_description).filter(CB2.id == int_bid).first()
                if cb_row:
                    source_page = cb_row.source_page
                    visual_desc = cb_row.visual_description
            except Exception:
                pass

        material_type = meta.get("material_type", "")
        block_type_meta = meta.get("block_type", "")
        # Marcação exclusiva pela estrela: apenas produto com Product.is_committee=True (via _committee_product_ids)
        _doc_pid = meta.get("product_id")
        _in_committee_entries = bool(_doc_pid and int(_doc_pid) in _committee_product_ids)
        is_comite_doc = _in_committee_entries
        # Task #153 — tag inclui o tipo do produto para o agente diferenciar
        # ação de estrutura sobre essa ação. Ex.: [COMITÊ-ESTRUTURADA] vs [COMITÊ-AÇÃO].
        # Lookup encadeado: 1) metadata do embedding (novos), 2) join por product_id (legados).
        product_type_meta = (meta.get("product_type") or "").lower().strip()
        if not product_type_meta and _doc_pid and _product_type_by_id:
            try:
                product_type_meta = _product_type_by_id.get(int(_doc_pid), "") or ""
            except (TypeError, ValueError):
                product_type_meta = ""
        # Task #153 — whitelist ESTRITA: valores fora do dicionário conhecido
        # caem para "OUTRO" para evitar injeção via metadado adulterado no banco.
        # Mapeamento: chave = product_type lowercased tal como sai do banco/vector
        # store → rótulo de exibição para o agente.
        _PT_WHITELIST = {
            # Renda Variável — ativos básicos
            "acao": "AÇÃO",
            "etf": "ETF",
            "bdr": "BDR",
            "fii": "FII",
            # Fundos
            "fundo": "FUNDO",
            "fundo multimercado": "FUNDO MULTIMERCADO",
            "fundo de renda fixa": "FUNDO DE RENDA FIXA",
            "fia": "FIA",
            "fic-fia": "FIC-FIA",
            "fidc": "FIDC",
            # Renda Fixa / Crédito
            "debenture": "DEBÊNTURE",
            "debênture": "DEBÊNTURE",
            "cri": "CRI",
            "cra": "CRA",
            "lci": "LCI",
            "lca": "LCA",
            # Estruturadas / derivativos
            "estruturada": "ESTRUTURADA",
            "estrutura": "ESTRUTURADA",
            "pop": "POP",
            "collar": "COLLAR",
            "coe": "COE",
            # Operações táticas
            "swap": "SWAP",
            "long & short": "LONG & SHORT",
            "long&short": "LONG & SHORT",
            "long short": "LONG & SHORT",
            # Derivativos de balcão / bolsa
            "mercado futuro": "MERCADO FUTURO",
            "futuro": "MERCADO FUTURO",
            "mercado a termo": "MERCADO A TERMO",
            "a termo": "MERCADO A TERMO",
            "termo": "MERCADO A TERMO",
            # Outros veículos
            "joint venture": "JOINT VENTURE",
            "join venture": "JOINT VENTURE",
        }
        _PT_TAG = _PT_WHITELIST.get(product_type_meta, "OUTRO")
        # Normaliza product_type_meta para downstream: só valores reconhecidos passam.
        if product_type_meta and product_type_meta not in _PT_WHITELIST:
            product_type_meta = ""
        if is_comite_doc:
            comite_tag = f"[COMITÊ-{_PT_TAG}]"
        else:
            comite_tag = f"[NÃO-COMITÊ-{_PT_TAG}]" if product_type_meta else "[NÃO-COMITÊ]"

        _doc_id_meta = str(meta.get("doc_id") or "")
        is_product_key_info = (
            block_type_meta == "product_key_info"
            or material_type == "ficha_produto"
            or _doc_id_meta.startswith("product_keyinfo_")
        )
        product_link = None
        if is_product_key_info:
            ticker_label = (meta.get("product_ticker") or meta.get("products") or "").upper()
            product_name_label = meta.get("product_name", "")
            label_id = ticker_label or product_name_label or "Produto"
            material_name = f"Ficha do Produto – {label_id}"
            if _doc_pid:
                try:
                    product_link = f"/base-conhecimento/product/{int(_doc_pid)}"
                except (TypeError, ValueError):
                    product_link = None
            link_hint = f" (link: {product_link})" if product_link else ""
            source_note = (
                f"TAG: [{comite_tag.strip('[]')}] | Esta é a FICHA DO PRODUTO mantida internamente pela SVN. "
                f"Ao citar, use: (Fonte: {material_name}){link_hint}. "
                f"NÃO existe PDF para esta fonte — NUNCA chame send_document com este resultado. "
                f"Se o assessor quiser ver mais, oriente que pode acessar a tela do produto na Base de Conhecimento."
            )
        else:
            _page_suffix = ""
            if source_page:
                try:
                    _page_int = int(source_page)
                    if _page_int > 0:
                        _page_suffix = f", pág. {_page_int}"
                except (TypeError, ValueError):
                    pass

            # Task #153 — instrução explícita sobre tipo do produto evita
            # que o agente confunda estrutura com ativo subjacente.
            _type_clause = ""
            if product_type_meta in ("estruturada", "estrutura"):
                _type_clause = (
                    " ATENÇÃO: este material descreve uma ESTRUTURA/DERIVATIVO — "
                    "ao recomendar, deixe explícito que a recomendação é a estrutura, "
                    "NÃO o ativo subjacente puro (ação/índice)."
                )
            elif product_type_meta == "acao":
                _type_clause = " Tipo do produto: AÇÃO (ativo subjacente nu)."
            elif product_type_meta:
                _type_clause = f" Tipo do produto: {_PT_TAG}."

            if is_comite_doc:
                source_note = (
                    f"TAG: {comite_tag} | Ao citar, inclua: (Fonte: {material_name}{_page_suffix}). "
                    f"Este material é uma recomendação formal do Comitê de Investimentos da SVN — "
                    f"use framing de recomendação oficial na resposta.{_type_clause}"
                )
            else:
                source_note = (
                    f"TAG: {comite_tag} | Ao citar, inclua: (Fonte: {material_name}{_page_suffix}). "
                    f"Este material é INFORMATIVO — NÃO é uma recomendação formal da SVN. "
                    f"Você pode informar e analisar o ativo, mas se perguntado sobre recomendação, "
                    f"esclareça que este ativo não está no Comitê ativo da SVN e sugira consultar o broker."
                    f"{_type_clause}"
                )

        # RAG V3.6 — cap dinâmico por tipo de bloco. Tabela/financial_table
        # ganham 4000 chars (carteira de 12 FIIs precisa); o resto fica em 600.
        # Sem isso, o `get_rich_content` retornava 4000 chars de tabela rica e
        # nós destruíamos tudo aqui com `content[:600]`. Bug silencioso da V3.5.
        from services.content_formatter import TABLE_BLOCK_TYPES as _TBT
        _is_table_block = (effective_block_type or block_type_meta or "").lower() in _TBT
        _content_cap = 4000 if _is_table_block else 600
        _final_content = content[:_content_cap]
        # Marcador de truncamento para o agente saber pedir paginação.
        _content_was_truncated = len(content) > _content_cap

        result_entry = {
            "title": meta.get("document_title", "Documento"),
            "material_name": material_name,
            "material_type": material_type,
            "comite_tag": comite_tag,
            # Task #153 — campo dedicado para diferenciação acao x estruturada x fii
            "product_type": product_type_meta or "outro",
            "product": meta.get("product_name", ""),
            "ticker": meta.get("products", ""),
            "content": _final_content,
            "content_truncated": _content_was_truncated,
            "score": round(r.composite_score, 3) if hasattr(r, 'composite_score') else None,
            "material_id": None if is_product_key_info else meta.get("material_id"),
            "block_id": int_block_id,
            "block_type": block_type_meta,
            "source_page": source_page,
            "visual_description": visual_desc,
            "source_note": source_note,
        }
        if is_product_key_info:
            result_entry["is_product_key_info"] = True
            if product_link:
                result_entry["product_link"] = product_link
        results.append(result_entry)

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

    visual_candidates = []
    if db:
        try:
            seen_material_ids = {r.get("material_id") for r in results if r.get("material_id")}
            seen_block_ids = {r.get("block_id") for r in results if r.get("block_id")}
            if seen_material_ids:
                from database.models import ContentBlock as CB3, Material as Mat3, Product as Prod3
                graphic_blocks = (
                    db.query(
                        CB3.id, CB3.source_page, CB3.visual_description, CB3.material_id,
                        Mat3.name.label("mat_name"), Prod3.ticker.label("prod_ticker")
                    )
                    .join(Mat3, Mat3.id == CB3.material_id)
                    .outerjoin(Prod3, Prod3.id == Mat3.product_id)
                    .filter(CB3.material_id.in_([int(mid) for mid in seen_material_ids if mid]))
                    .filter(CB3.block_type == "grafico")
                    .filter(CB3.id.notin_(list(seen_block_ids) if seen_block_ids else [0]))
                    .all()
                )
                for gb in graphic_blocks:
                    visual_candidates.append({
                        "block_id": gb.id,
                        "block_type": "grafico",
                        "source_page": gb.source_page,
                        "visual_description": gb.visual_description,
                        "material_name": gb.mat_name,
                        "material_id": gb.material_id,
                        "ticker": gb.prod_ticker or "",
                        "score": 0,
                    })
                if visual_candidates:
                    print(f"[VISUAL_ENRICH] Found {len(visual_candidates)} graphic blocks from materials {list(seen_material_ids)}")
        except Exception as ve:
            print(f"[VISUAL_ENRICH] Error enriching visual candidates: {ve}")

    # RAG V3.6 — paginação monotônica por offset+page_size. `total_results`
    # reflete o tamanho real do conjunto antes da janela. A janela é
    # `results[offset:offset+page_size]` e `has_more` é true quando ainda há
    # blocos não enviados (`offset + page_size < total_results`) — cursor
    # progride sempre, sem risco de loop.
    #
    # Truncamento intra-bloco (uma única tabela cujo conteúdo passou do cap
    # de 4000 chars) é exposto separadamente em `content_truncated_in_window`
    # — neste caso, paginar não recuperaria mais conteúdo do mesmo bloco;
    # o agente deve refinar a query (ex.: pedir um ticker específico).
    total_results = len(results)

    window_end = offset + page_size
    results_window = results[offset:window_end]
    # Truncamento intra-bloco se aplica APENAS aos blocos que estão de fato
    # na janela retornada — calcular sobre `results` inteiro produziria
    # falsos positivos e induziria o agente a paginar/refinar à toa.
    has_truncated_block = any(r.get("content_truncated") for r in results_window)

    next_offset = offset + len(results_window)
    has_more = next_offset < total_results

    response = {
        "results": results_window,
        "count": len(results_window),
        "total_results": total_results,
        "offset": offset,
        "page_size": page_size,
        "completeness_mode": is_completeness,
        "content_truncated_in_window": has_truncated_block,
    }

    if has_more:
        response["has_more"] = True
        response["next_offset"] = next_offset
    else:
        response["has_more"] = False

    if materials_with_pdf:
        response["materials_with_pdf"] = list(materials_with_pdf)
    if visual_candidates:
        response["visual_candidates"] = visual_candidates

    return response


async def _continue_block_content(
    *,
    block_id: int,
    content_offset: int,
    page_size_chars: int,
    db,
) -> Dict[str, Any]:
    """RAG V3.6 — devolve a continuação do conteúdo formatado de UM bloco.

    Quando uma chamada anterior a `search_knowledge_base` devolveu um
    resultado com `content_truncated: true`, o agente pode chamar com
    `block_id` + `content_offset` para receber o trecho seguinte do MESMO
    bloco — útil para tabelas únicas que estouram o cap de 4000 chars do
    formatador (ex.: carteira com 30+ FIIs em uma única tabela).

    Comportamento:
      - Carrega o bloco do banco; aplica `get_rich_content` com cap muito
        alto (na prática, sem corte) para obter o conteúdo formatado
        completo.
      - Recorta `[content_offset:content_offset + page_size_chars]` em
        boundary de linha para preservar integridade de cada linha.
      - Devolve `next_content_offset` quando ainda há conteúdo restante,
        permitindo várias chamadas sequenciais sem reformular a query.
    """
    try:
        from database.models import ContentBlock as CB
        from services.content_formatter import (
            get_rich_content,
            truncate_at_line_boundary,
        )
    except Exception as _e:
        return {
            "error": f"Falha ao carregar dependências: {_e}",
            "results": [],
        }

    try:
        row = db.query(
            CB.id,
            CB.content,
            CB.block_type,
            CB.material_id,
            CB.source_page,
            CB.visual_description,
        ).filter(CB.id == block_id).first()
    except Exception as _e:
        return {
            "error": f"Falha ao consultar bloco {block_id}: {_e}",
            "results": [],
        }

    if not row:
        return {
            "results": [],
            "message": f"Bloco {block_id} não encontrado.",
            "block_id": block_id,
            "content_offset": content_offset,
            "has_more": False,
        }

    # Cap virtualmente infinito (10 MB) — queremos o formato completo para
    # poder fatiar com precisão.
    full_formatted = get_rich_content(
        row.content or "",
        row.content or "",
        max_chars=10_000_000,
        block_type=row.block_type,
    )
    total_chars = len(full_formatted)

    if content_offset >= total_chars:
        return {
            "results": [],
            "message": (
                f"content_offset {content_offset} além do fim do bloco "
                f"({total_chars} chars). Bloco esgotado."
            ),
            "block_id": block_id,
            "content_offset": content_offset,
            "total_chars": total_chars,
            "has_more": False,
        }

    remaining = full_formatted[content_offset:]
    chunk = truncate_at_line_boundary(remaining, page_size_chars)
    # `truncate_at_line_boundary` adiciona um marcador "[…conteúdo
    # truncado…]" ao chunk quando trunca; precisamos do tamanho REAL
    # consumido do `remaining` original para calcular o offset seguinte.
    if len(remaining) <= page_size_chars:
        chars_consumed = len(remaining)
        more = False
    else:
        head = remaining[:page_size_chars]
        last_nl = head.rfind("\n")
        chars_consumed = last_nl if last_nl > 0 else page_size_chars
        more = chars_consumed < len(remaining)

    next_offset = content_offset + chars_consumed

    # Buscar nome do material para citação consistente.
    material_name = "Documento"
    try:
        from database.models import Material as _Mat
        mat = db.query(_Mat.name).filter(_Mat.id == row.material_id).first()
        if mat and mat.name:
            material_name = mat.name
    except Exception:
        pass

    result_entry = {
        "block_id": block_id,
        "material_id": row.material_id,
        "material_name": material_name,
        "block_type": row.block_type,
        "source_page": row.source_page,
        "visual_description": row.visual_description,
        "content": chunk,
        "content_offset": content_offset,
        "content_chars_returned": chars_consumed,
        "content_truncated": more,
    }

    response = {
        "results": [result_entry],
        "count": 1,
        "block_id": block_id,
        "content_offset": content_offset,
        "total_chars": total_chars,
        "content_truncated_in_window": more,
        "is_block_continuation": True,
        "completeness_mode": False,
    }
    if more:
        response["has_more"] = True
        response["next_content_offset"] = next_offset
    else:
        response["has_more"] = False
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

    print(f"[AgentTools] search_web chamada com query='{query}'")
    result = web_service.search_sync(query, db=db)
    if not result.get("success"):
        error_msg = result.get('error', 'desconhecido')
        print(f"[AgentTools] search_web FALHOU: {error_msg}")
        return {"error": f"Busca web falhou: {error_msg}"}

    if not result.get("results"):
        return {"results": [], "message": "Nenhum resultado encontrado na web."}

    if db:
        try:
            web_service.log_search(db=db, query=query, results=result, fallback_reason="GPT tool call")
        except Exception:
            pass

    formatted_results = []
    for r in result["results"][:5]:
        full_url = r.get("url", "")
        source_domain = full_url
        try:
            from urllib.parse import urlparse
            source_domain = urlparse(full_url).netloc or full_url
        except Exception:
            pass
        if full_url:
            citation = f"Ao citar dados deste resultado, inclua a URL completa: (Fonte: {source_domain} — {full_url})"
        else:
            citation = f"Ao citar dados deste resultado, inclua: (Fonte: {source_domain})"
        formatted_results.append({
            "title": r.get("title", ""),
            "content": r.get("content", "")[:500],
            "url": full_url,
            "published_date": r.get("published_date", ""),
            "source_note": citation,
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
