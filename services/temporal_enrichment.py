import re
from typing import Optional, Dict, Tuple, Set
from sqlalchemy.orm import Session

TEMPORAL_PATTERN = re.compile(
    r'(202[0-9]|'
    r'janeiro|fevereiro|março|abril|maio|junho|'
    r'julho|agosto|setembro|outubro|novembro|dezembro|'
    r'jan/|fev/|mar/|abr/|mai/|jun/|jul/|ago/|set/|out/|nov/|dez/|'
    r'[1-4]T\d{0,4}|'
    r'[1-4][ºo°]\s*trimestre|'
    r'[1-2][ºo°]\s*semestre)',
    re.IGNORECASE
)

QUANTITATIVE_PATTERN = re.compile(
    r'(\d+[,\.]\d+\s*%|'
    r'rentabilidade|dividend|dy\b|p/vp|pvp|'
    r'valoriza[çc][aã]o|rendimento|retorno|'
    r'R\$\s*\d|cota.*R\$|'
    r'CDI\s*\+|IPCA\s*\+|'
    r'a\.a\.|a\.m\.)',
    re.IGNORECASE
)

ENRICHMENT_MARKER = "[Ref.Temporal:"


def _needs_temporal_enrichment(content: str) -> bool:
    if ENRICHMENT_MARKER in content:
        return False
    has_quantitative = bool(QUANTITATIVE_PATTERN.search(content))
    has_temporal = bool(TEMPORAL_PATTERN.search(content))
    return has_quantitative and not has_temporal


def _extract_temporal_ref(content: str) -> Optional[str]:
    matches = TEMPORAL_PATTERN.findall(content)
    if not matches:
        return None

    year_matches = [m for m in matches if re.match(r'202\d', m)]
    month_matches = [m for m in matches if re.match(
        r'(?i)(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|jan/|fev/|mar/|abr/|mai/|jun/|jul/|ago/|set/|out/|nov/|dez/)',
        m
    )]
    quarter_matches = [m for m in matches if re.match(r'[1-4]T', m, re.IGNORECASE)]
    semester_matches = [m for m in matches if re.match(r'[1-2][ºo°]\s*semestre', m, re.IGNORECASE)]

    parts = []
    if month_matches:
        parts.append(month_matches[0].strip().rstrip('/'))
    elif quarter_matches:
        parts.append(quarter_matches[0].strip())
    elif semester_matches:
        parts.append(semester_matches[0].strip())
    if year_matches:
        parts.append(year_matches[0])

    return " ".join(parts) if parts else matches[0]


def enrich_results_with_temporal_refs(
    results: list,
    db: Session
) -> list:
    try:
        from database.models import ContentBlock
    except ImportError:
        print("[TemporalEnrichment] ContentBlock model não disponível, pulando enriquecimento")
        return results

    candidates = []
    for i, result in enumerate(results):
        content = ""
        metadata = {}
        if hasattr(result, 'content'):
            content = result.content
            metadata = result.metadata if hasattr(result, 'metadata') else {}
        elif isinstance(result, dict):
            content = result.get('content', '')
            metadata = result.get('metadata', {})
        else:
            continue

        if not _needs_temporal_enrichment(content):
            continue

        block_id = metadata.get('block_id')
        material_id = metadata.get('material_id')

        if not block_id or not material_id:
            continue

        try:
            block_id_int = int(block_id)
            material_id_int = int(material_id)
        except (ValueError, TypeError):
            continue

        candidates.append({
            'index': i,
            'block_id': block_id_int,
            'material_id': material_id_int,
        })

    if not candidates:
        return results

    candidate_block_ids = {c['block_id'] for c in candidates}
    candidate_material_ids = {c['material_id'] for c in candidates}

    try:
        all_blocks_in_materials = db.query(
            ContentBlock.id,
            ContentBlock.material_id,
            ContentBlock.order,
            ContentBlock.content
        ).filter(
            ContentBlock.material_id.in_(list(candidate_material_ids))
        ).order_by(
            ContentBlock.material_id,
            ContentBlock.order
        ).all()
    except Exception as e:
        print(f"[TemporalEnrichment] Erro ao buscar blocos por material: {e}")
        return results

    blocks_by_material: Dict[int, list] = {}
    block_index_map: Dict[int, Tuple[int, int]] = {}
    for b in all_blocks_in_materials:
        mid = b.material_id
        if mid not in blocks_by_material:
            blocks_by_material[mid] = []
        idx_in_list = len(blocks_by_material[mid])
        blocks_by_material[mid].append(b)
        block_index_map[b.id] = (mid, idx_in_list)

    enriched_count = 0
    for c in candidates:
        bid = c['block_id']
        mid = c['material_id']

        if bid not in block_index_map:
            continue

        _, idx_in_list = block_index_map[bid]
        material_blocks = blocks_by_material[mid]

        temporal_ref = None
        for offset in [-1, 1, -2, 2]:
            neighbor_idx = idx_in_list + offset
            if 0 <= neighbor_idx < len(material_blocks):
                nb_content = material_blocks[neighbor_idx].content or ""
                temporal_ref = _extract_temporal_ref(nb_content)
                if temporal_ref:
                    break

        if not temporal_ref:
            continue

        result_idx = c['index']
        prefix = f"{ENRICHMENT_MARKER} {temporal_ref}]\n"

        result = results[result_idx]
        if hasattr(result, 'content'):
            result.content = prefix + result.content
        elif isinstance(result, dict):
            result['content'] = prefix + result.get('content', '')

        enriched_count += 1

    if enriched_count > 0:
        print(f"[TemporalEnrichment] {enriched_count}/{len(candidates)} blocos enriquecidos com referência temporal de vizinhos")

    return results
