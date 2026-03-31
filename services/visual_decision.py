import logging
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
}

CONCEPTUAL_BLOCKERS = {
    "o que é", "o que e", "o que significa", "explique", "explica",
    "conceito", "definição", "definicao", "como funciona",
}


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


def _query_relevance_score(visual_desc: str, query: str) -> float:
    if not visual_desc:
        return 0.0
    query_words = set(query.lower().split())
    desc_lower = visual_desc.lower()
    matches = sum(1 for w in query_words if w in desc_lower and len(w) > 2)
    return matches / max(len(query_words), 1)


def select_best_visual_block(visual_blocks: list, query: str) -> Optional[dict]:
    if not visual_blocks:
        return None

    eligible = [b for b in visual_blocks if should_send_visual(b, query)]
    if not eligible:
        return None

    for b in eligible:
        search_score = b.get("score") or 0
        relevance = _query_relevance_score(b.get("visual_description", ""), query)
        b["_combined_score"] = search_score + relevance

    eligible.sort(key=lambda b: b.get("_combined_score", 0), reverse=True)
    selected = eligible[0]
    logger.info(f"Selected visual block {selected.get('block_id')} "
                f"(search_score={selected.get('score')}, combined={selected.get('_combined_score', 0):.3f})")
    return selected
