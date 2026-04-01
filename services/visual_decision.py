import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

VISUAL_TRIGGERS = {
    "histórico", "historico", "performance", "distribuição", "distribuicao",
    "rentabilidade", "comparativo", "evolução", "evolucao", "retorno",
    "dividendos", "rendimento", "dy", "yield", "vacância", "vacancia",
    "captação", "captacao", "cotação", "cotacao", "adtv", "cota",
    "patrimônio", "patrimonio", "nav", "gráfico", "grafico", "chart",
    "dividend yield", "p/vp", "pvp", "liquidez", "volume",
    "mostra", "mostrar", "ver", "visualizar",
    "desempenho", "resultado", "projeção", "projecao",
}

CONCEPTUAL_BLOCKERS = {
    "o que é", "o que e", "o que significa", "explique", "explica",
    "conceito", "definição", "definicao", "como funciona",
}

SEMANTIC_CATEGORIES = {
    "performance": {
        "query_terms": [
            "performance", "desempenho", "rentabilidade", "retorno",
            "rendimento", "resultado", "comparativo", "evolução",
            "evolucao", "benchmark", "ifix", "cdi", "ibov",
        ],
        "block_terms": [
            "desempenho", "performance", "rentabilidade", "retorno",
            "rendimento", "resultado", "benchmark", "ifix", "cdi",
            "ibov", "índice", "indice", "comparando", "acumulad",
        ],
        "weight": 3.0,
    },
    "dividendos": {
        "query_terms": [
            "dividendo", "distribuição", "distribuicao", "rendimento",
            "dy", "dividend yield", "yield", "proventos", "renda",
        ],
        "block_terms": [
            "dividendo", "distribuição", "distribuicao", "rendimento",
            "dy", "dividend", "yield", "provento", "renda", "por cota",
            "remuneração", "remuneracao",
        ],
        "weight": 3.0,
    },
    "vacancia": {
        "query_terms": [
            "vacância", "vacancia", "ocupação", "ocupacao", "vago",
        ],
        "block_terms": [
            "vacância", "vacancia", "ocupação", "ocupacao", "vago",
            "taxa de ocupação",
        ],
        "weight": 3.0,
    },
    "cotacao": {
        "query_terms": [
            "cotação", "cotacao", "cota", "preço", "preco", "p/vp",
            "pvp", "valor patrimonial",
        ],
        "block_terms": [
            "cotação", "cotacao", "cota", "preço", "preco", "p/vp",
            "pvp", "valor patrimonial", "ágio", "desconto",
        ],
        "weight": 2.5,
    },
    "liquidez": {
        "query_terms": [
            "liquidez", "volume", "adtv", "negociação", "negociacao",
            "cotista",
        ],
        "block_terms": [
            "liquidez", "volume", "adtv", "negociação", "negociacao",
            "cotista",
        ],
        "weight": 2.5,
    },
    "captacao": {
        "query_terms": [
            "captação", "captacao", "emissão", "emissao", "oferta",
        ],
        "block_terms": [
            "captação", "captacao", "emissão", "emissao", "oferta",
        ],
        "weight": 2.5,
    },
    "carteira": {
        "query_terms": [
            "carteira", "portfólio", "portfolio", "alocação", "alocacao",
            "composição", "composicao", "segmento", "setor",
        ],
        "block_terms": [
            "carteira", "portfólio", "portfolio", "alocação", "alocacao",
            "composição", "composicao", "segmento", "setor",
        ],
        "weight": 2.0,
    },
}

INSTITUTIONAL_PENALTY_TERMS = [
    "informações de contato", "redes sociais", "mídia", "midia", "imprensa",
    "equipe de gestão", "time de gestão", "estrutura da equipe",
    "sumário do material", "índice do material",
    "disclaimer", "avisos legais", "fatores de risco",
    "track record", "linha do tempo", "timeline",
    "processo de investimento", "comitê de investimento",
    "organograma", "estrutura organizacional",
    "quem somos", "sobre nós",
    "material publicitário",
    "oferta pública de distribuição",
]

MIN_RELEVANCE_THRESHOLD = 0.15


def should_send_visual(block_metadata: dict, query: str) -> bool:
    if not block_metadata:
        return False

    block_type = block_metadata.get("block_type", "")
    if block_type != "grafico":
        return False

    query_lower = query.lower().strip()

    for blocker in CONCEPTUAL_BLOCKERS:
        if blocker in query_lower:
            logger.debug(f"Visual blocked by conceptual blocker: '{blocker}'")
            return False

    for trigger in VISUAL_TRIGGERS:
        if trigger in query_lower:
            logger.info(f"Visual trigger matched in query: '{trigger}' for block {block_metadata.get('block_id')}")
            return True

    return False


def _is_institutional_block(visual_desc: str) -> bool:
    if not visual_desc:
        return False
    desc_lower = visual_desc.lower()
    penalty_count = sum(1 for term in INSTITUTIONAL_PENALTY_TERMS if term in desc_lower)
    return penalty_count >= 2


def _detect_query_category(query: str) -> Optional[str]:
    query_lower = query.lower()
    best_cat = None
    best_score = 0
    for cat_name, cat_data in SEMANTIC_CATEGORIES.items():
        score = sum(1 for term in cat_data["query_terms"] if term in query_lower)
        if score > best_score:
            best_score = score
            best_cat = cat_name
    return best_cat


def _category_match_score(visual_desc: str, category: str) -> float:
    if not visual_desc or not category:
        return 0.0
    cat_data = SEMANTIC_CATEGORIES.get(category)
    if not cat_data:
        return 0.0
    desc_lower = visual_desc.lower()
    matches = sum(1 for term in cat_data["block_terms"] if term in desc_lower)
    if matches == 0:
        return 0.0
    return (matches / len(cat_data["block_terms"])) * cat_data["weight"]


def _query_relevance_score(visual_desc: str, query: str) -> float:
    if not visual_desc:
        return 0.0
    query_lower = query.lower()
    desc_lower = visual_desc.lower()

    query_words = [w for w in query_lower.split() if len(w) > 2]
    if not query_words:
        return 0.0

    word_matches = sum(1 for w in query_words if w in desc_lower)
    word_score = word_matches / len(query_words)

    category = _detect_query_category(query)
    cat_score = _category_match_score(visual_desc, category) if category else 0.0

    institutional_penalty = -0.8 if _is_institutional_block(visual_desc) else 0.0

    total = word_score + cat_score + institutional_penalty
    return max(total, 0.0)


def select_best_visual_block(visual_blocks: list, query: str) -> Optional[dict]:
    if not visual_blocks:
        return None

    eligible = [b for b in visual_blocks if should_send_visual(b, query)]
    if not eligible:
        return None

    scored = []
    for b in eligible:
        desc = b.get("visual_description", "")
        relevance = _query_relevance_score(desc, query)
        search_score = b.get("score") or 0
        combined = relevance + (search_score * 0.3)
        b["_combined_score"] = combined
        scored.append(b)
        logger.debug(
            f"Visual block {b.get('block_id')} p.{b.get('source_page')}: "
            f"relevance={relevance:.3f} search={search_score:.3f} combined={combined:.3f} "
            f"desc={desc[:80]}"
        )

    scored.sort(key=lambda b: b.get("_combined_score", 0), reverse=True)
    selected = scored[0]

    if selected["_combined_score"] < MIN_RELEVANCE_THRESHOLD:
        logger.info(
            f"Best visual block {selected.get('block_id')} scored {selected['_combined_score']:.3f} "
            f"< threshold {MIN_RELEVANCE_THRESHOLD} — not sending any visual"
        )
        return None

    logger.info(
        f"Selected visual block {selected.get('block_id')} p.{selected.get('source_page')} "
        f"(combined={selected['_combined_score']:.3f}, desc={selected.get('visual_description', '')[:80]})"
    )
    return selected
