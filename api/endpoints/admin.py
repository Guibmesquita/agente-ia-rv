"""
Endpoints de administração transversais (prefixo /api/admin).
Agrega diagnósticos e ferramentas de gestão interna restritas ao role admin.
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import Product, User
from api.endpoints.auth import get_current_user


# Status válidos para triagem de respostas evasivas (Task #190).
_VALID_RESOLUTION_STATUSES = {"resolved", "false_positive"}


router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")


@router.get("/committee-status")
async def committee_status_diagnostic(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Diagnóstico do sistema de comitê.

    Retorna três perspectivas para verificar consistência entre as fontes:
    - star_products: produtos com Product.is_committee=True (fonte de verdade)
    - active_rec_entries: RecommendationEntry ativas (enriquecimento — rating/preço-alvo)
    - effective_committee: o que o agente Stevan enxerga no system prompt

    Inclui divergências detectadas automaticamente:
    - entries_without_star: RecommendationEntry de produto sem estrela (não enriquece nada)
    - stars_without_entry: produto no comitê sem dados de enriquecimento estruturados
    """
    _require_admin(current_user)

    from datetime import datetime
    from sqlalchemy import or_
    from database.models import RecommendationEntry
    from services.vector_store import get_vector_store

    now = datetime.utcnow()

    # Produtos com estrela (fonte de verdade)
    star_products = db.query(Product).filter(Product.is_committee == True).all()
    star_ids = {p.id for p in star_products}

    # RecommendationEntry ativas
    active_entries = (
        db.query(RecommendationEntry)
        .filter(RecommendationEntry.is_active == True)
        .filter(
            or_(
                RecommendationEntry.valid_until == None,
                RecommendationEntry.valid_until >= now,
            )
        )
        .all()
    )
    entry_ids = {e.product_id for e in active_entries}

    # Carteira efetiva (injetada no system prompt do agente)
    vs = get_vector_store()
    effective = vs.get_committee_summary()
    effective_names = [e.get("product_name") for e in effective]

    # Divergências
    entries_without_star = list(entry_ids - star_ids)
    stars_without_entry = list(star_ids - entry_ids)

    return {
        "star_products": [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker or "",
                "manager": p.manager or "",
                "is_committee": bool(p.is_committee),
            }
            for p in star_products
        ],
        "active_rec_entries": [
            {
                "product_id": e.product_id,
                "rating": e.rating or "",
                "target_price": e.target_price,
                "rationale": e.rationale or "",
                "valid_until": e.valid_until.strftime("%d/%m/%Y") if e.valid_until else "",
                "has_star": e.product_id in star_ids,
            }
            for e in active_entries
        ],
        "effective_committee": [
            {
                "product_name": e.get("product_name"),
                "ticker": e.get("ticker"),
                "rating": e.get("rating"),
                "material_name": e.get("material_name", ""),
                "source": e.get("source"),
            }
            for e in effective
        ],
        "divergences": {
            "entries_without_star": entries_without_star,
            "stars_without_entry": stars_without_entry,
            "note": (
                "entries_without_star: RecommendationEntry de produtos sem estrela "
                "— não enriquecem o comitê (produto fora do comitê). "
                "stars_without_entry: produtos no comitê sem RecommendationEntry ativa "
                "— agente não terá rating/preço-alvo estruturados."
            ),
        },
        "summary": {
            "star_count": len(star_products),
            "rec_entry_count": len(active_entries),
            "effective_count": len(effective),
            "products_in_prompt": effective_names,
        },
    }


@router.get("/rag/evasive")
async def list_evasive_responses(
    limit: int = 50,
    offset: int = 0,
    evasive_pattern: Optional[str] = None,
    had_kb_results: Optional[bool] = None,
    completeness_mode: Optional[bool] = None,
    resolution_status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    RAG V3.6 — Lista as respostas detectadas como evasivas, com filtros.

    Padrões evasivos: o agente declara não ter encontrado o material
    ou que "o documento não detalha" mesmo após consultar a base.
    Útil para calibrar o reranker, ajustar prompts e priorizar
    re-extrações de PDFs.

    Filtros suportados (Task #190):
    - `evasive_pattern`: filtra pelo padrão exato detectado.
    - `had_kb_results`: True/False — só registros em que o RAG retornou
      (ou não retornou) resultados.
    - `completeness_mode`: True/False — só registros disparados (ou não)
      pelo modo de completude estendida.
    - `resolution_status`: 'open' (default), 'resolved', 'false_positive'
      ou 'all'. 'open' inclui apenas itens ainda não triados.

    Retorna até `limit` (máx 200) itens com `total` filtrado e a lista
    de padrões evasivos distintos para popular o seletor da UI.
    """
    _require_admin(current_user)

    from sqlalchemy import text as _sql_text

    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))

    where_clauses = []
    params: dict = {"lim": safe_limit, "off": safe_offset}

    if evasive_pattern:
        where_clauses.append("evasive_pattern = :pattern")
        params["pattern"] = evasive_pattern
    if had_kb_results is not None:
        where_clauses.append("had_kb_results = :had_kb")
        params["had_kb"] = bool(had_kb_results)
    if completeness_mode is not None:
        where_clauses.append("completeness_mode = :comp")
        params["comp"] = bool(completeness_mode)

    # 'open' é o default — agiliza a triagem mostrando só o que ainda
    # precisa de revisão. 'all' desliga o filtro.
    status = (resolution_status or "open").lower()
    if status == "open":
        where_clauses.append("resolution_status IS NULL")
    elif status in _VALID_RESOLUTION_STATUSES:
        where_clauses.append("resolution_status = :res_status")
        params["res_status"] = status
    elif status != "all":
        raise HTTPException(
            status_code=400,
            detail=(
                "resolution_status inválido. Use 'open', 'resolved', "
                "'false_positive' ou 'all'."
            ),
        )

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        total_row = db.execute(
            _sql_text(
                f"SELECT COUNT(*) FROM rag_evasive_responses {where_sql}"
            ),
            params,
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        rows = db.execute(
            _sql_text(
                f"""
                SELECT id, created_at, conversation_id, user_query,
                       ai_response, evasive_pattern, had_kb_results,
                       kb_results_count, completeness_mode, tools_used,
                       retrieved_material_ids, retrieved_material_names,
                       top_k, intent_label, resolution_status, resolved_at,
                       resolved_by_user_id, resolution_note
                FROM rag_evasive_responses
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
                """
            ),
            params,
        ).fetchall()

        # Lista distinta de padrões para popular o filtro da UI. Usa o
        # universo total da tabela (sem aplicar os filtros), para que o
        # usuário sempre veja todas as opções disponíveis.
        pattern_rows = db.execute(
            _sql_text(
                """
                SELECT evasive_pattern, COUNT(*) AS total
                FROM rag_evasive_responses
                WHERE evasive_pattern IS NOT NULL AND evasive_pattern <> ''
                GROUP BY evasive_pattern
                ORDER BY total DESC
                """
            )
        ).fetchall()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao consultar telemetria evasiva: {e}",
        )

    import json as _json

    def _parse_json_list(v):
        if not v:
            return []
        try:
            parsed = _json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    items = [
        {
            "id": r[0],
            "created_at": r[1].isoformat() if r[1] else None,
            "conversation_id": r[2],
            "user_query": r[3],
            "ai_response": r[4],
            "evasive_pattern": r[5],
            "had_kb_results": bool(r[6]) if r[6] is not None else None,
            "kb_results_count": r[7],
            "completeness_mode": bool(r[8]) if r[8] is not None else None,
            "tools_used": r[9],
            # RAG V3.6 — campos enriquecidos para diagnóstico segmentado.
            "retrieved_material_ids": _parse_json_list(r[10]),
            "retrieved_material_names": _parse_json_list(r[11]),
            "top_k": r[12],
            "intent_label": r[13],
            # Task #190 — triagem.
            "resolution_status": r[14],
            "resolved_at": r[15].isoformat() if r[15] else None,
            "resolved_by_user_id": r[16],
            "resolution_note": r[17],
        }
        for r in rows
    ]

    return {
        "count": len(items),
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "items": items,
        "patterns": [
            {"pattern": p[0], "total": int(p[1])}
            for p in pattern_rows
        ],
    }


@router.patch("/rag/evasive/{evasive_id}")
async def update_evasive_resolution(
    evasive_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Task #190 — Marca uma resposta evasiva como triada.

    Body:
    - `resolution_status`: 'resolved', 'false_positive' ou null (reabre).
    - `resolution_note`: string opcional explicando a decisão.

    Retorna o registro atualizado.
    """
    _require_admin(current_user)

    from datetime import datetime
    from sqlalchemy import text as _sql_text

    raw_status = payload.get("resolution_status")
    note = payload.get("resolution_note")

    if raw_status is not None and raw_status not in _VALID_RESOLUTION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                "resolution_status inválido. Use 'resolved', 'false_positive' "
                "ou null para reabrir."
            ),
        )

    # null reabre o item (limpa metadados de triagem).
    if raw_status is None:
        params = {
            "id": evasive_id,
            "status": None,
            "resolved_at": None,
            "resolved_by": None,
            "note": None,
        }
    else:
        params = {
            "id": evasive_id,
            "status": raw_status,
            "resolved_at": datetime.utcnow(),
            "resolved_by": current_user.id,
            "note": note if isinstance(note, str) and note.strip() else None,
        }

    try:
        result = db.execute(
            _sql_text(
                """
                UPDATE rag_evasive_responses
                SET resolution_status = :status,
                    resolved_at = :resolved_at,
                    resolved_by_user_id = :resolved_by,
                    resolution_note = :note
                WHERE id = :id
                RETURNING id, resolution_status, resolved_at,
                          resolved_by_user_id, resolution_note
                """
            ),
            params,
        ).fetchone()
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao atualizar telemetria evasiva: {e}",
        )

    if not result:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    return {
        "id": result[0],
        "resolution_status": result[1],
        "resolved_at": result[2].isoformat() if result[2] else None,
        "resolved_by_user_id": result[3],
        "resolution_note": result[4],
    }


@router.post("/portfolio-rows/backfill")
async def backfill_portfolio_rows(
    material_id: Optional[int] = Query(
        None,
        description="Limita o backfill a um único material. Se omitido, processa todos os elegíveis.",
    ),
    product_id: Optional[int] = Query(
        None,
        description="Limita o backfill aos materiais de um produto específico.",
    ),
    dry_run: bool = Query(
        False,
        description="Quando true, apenas detecta tabelas de carteira sem criar blocos nem reindexar.",
    ),
    skip_index: bool = Query(
        False,
        description="Cria os blocos portfolio_row mas pula a reindexação no vector store.",
    ),
    limit: Optional[int] = Query(
        None,
        ge=1,
        le=2000,
        description="Limita quantos materiais são processados nesta chamada (útil em produção).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    RAG V3.6 — Reprocessa materiais existentes para gerar blocos `portfolio_row`
    sem mexer nos blocos atuais.

    Para cada material elegível, varre os blocos do tipo `tabela`/`financial_table`
    e, para os que casam a heurística de carteira, cria um bloco sintético por
    linha (ticker → embedding dedicado). É idempotente — `_create_block` deduplica
    pelo `content_hash`, então rodar de novo não duplica nada.

    Se `dry_run=true`, apenas detecta as tabelas e relata o que seria criado
    (sem inserir blocos nem reindexar). Quando blocos novos são gerados, o
    material é reindexado no vector store (a menos que `skip_index=true`).
    """
    _require_admin(current_user)

    from database.models import ContentBlock, ContentBlockType, Material
    from services.product_ingestor import (
        _detect_portfolio_table,
        get_product_ingestor,
    )
    import json as _json

    elegible_q = (
        db.query(Material.id)
        .join(ContentBlock, ContentBlock.material_id == Material.id)
        .filter(
            ContentBlock.block_type.in_(
                [
                    ContentBlockType.TABLE.value,
                    ContentBlockType.FINANCIAL_TABLE.value,
                ]
            )
        )
        .distinct()
    )
    if material_id is not None:
        elegible_q = elegible_q.filter(Material.id == material_id)
    if product_id is not None:
        elegible_q = elegible_q.filter(Material.product_id == product_id)

    elegible_q = elegible_q.order_by(Material.id.asc())
    if limit is not None:
        elegible_q = elegible_q.limit(limit)

    material_ids = [row[0] for row in elegible_q.all()]

    summary = {
        "dry_run": dry_run,
        "skip_index": skip_index,
        "filters": {
            "material_id": material_id,
            "product_id": product_id,
            "limit": limit,
        },
        "materials_eligible": len(material_ids),
        "materials_with_portfolio_tables": 0,
        "materials_with_new_blocks": 0,
        "materials_reindexed": 0,
        "materials_failed": 0,
        "tables_scanned": 0,
        "portfolio_tables_detected": 0,
        "portfolio_rows_created": 0,
        "skipped_invalid_json": 0,
        "details": [],
    }

    if not material_ids:
        return summary

    if dry_run:
        for mid in material_ids:
            blocks = (
                db.query(ContentBlock)
                .filter(ContentBlock.material_id == mid)
                .filter(
                    ContentBlock.block_type.in_(
                        [
                            ContentBlockType.TABLE.value,
                            ContentBlockType.FINANCIAL_TABLE.value,
                        ]
                    )
                )
                .all()
            )
            mat_detected = 0
            mat_rows_estimate = 0
            mat_invalid = 0
            for b in blocks:
                summary["tables_scanned"] += 1
                try:
                    table_data = _json.loads(b.content)
                except (ValueError, TypeError):
                    mat_invalid += 1
                    summary["skipped_invalid_json"] += 1
                    continue
                if not isinstance(table_data, dict):
                    continue
                if _detect_portfolio_table(table_data):
                    mat_detected += 1
                    summary["portfolio_tables_detected"] += 1
                    rows = table_data.get("rows", []) or []
                    mat_rows_estimate += sum(
                        1
                        for r in rows
                        if isinstance(r, list) and any(c for c in r if c)
                    )
            if mat_detected > 0:
                summary["materials_with_portfolio_tables"] += 1
                summary["details"].append(
                    {
                        "material_id": mid,
                        "portfolio_tables_detected": mat_detected,
                        "estimated_rows": mat_rows_estimate,
                        "skipped_invalid_json": mat_invalid,
                    }
                )
        return summary

    ingestor = get_product_ingestor()
    user_id = getattr(current_user, "id", None)

    for mid in material_ids:
        try:
            res = ingestor.backfill_portfolio_row_blocks(
                material_id=mid,
                db=db,
                user_id=user_id,
                reindex=not skip_index,
            )
        except Exception as e:
            summary["materials_failed"] += 1
            summary["details"].append({"material_id": mid, "error": str(e)})
            continue

        summary["tables_scanned"] += res.get("tables_scanned", 0)
        summary["portfolio_tables_detected"] += res.get("portfolio_tables_detected", 0)
        summary["portfolio_rows_created"] += res.get("portfolio_rows_created", 0)
        summary["skipped_invalid_json"] += res.get("skipped_invalid_json", 0)

        if res.get("portfolio_tables_detected", 0) > 0:
            summary["materials_with_portfolio_tables"] += 1
        if res.get("portfolio_rows_created", 0) > 0:
            summary["materials_with_new_blocks"] += 1
            entry = {
                "material_id": mid,
                "portfolio_tables_detected": res.get("portfolio_tables_detected", 0),
                "portfolio_rows_created": res.get("portfolio_rows_created", 0),
                "reindexed": res.get("reindexed", False),
                "indexed_count": res.get("indexed_count", 0),
            }
            if res.get("reindex_error"):
                entry["reindex_error"] = res["reindex_error"]
            summary["details"].append(entry)
            if res.get("reindexed"):
                summary["materials_reindexed"] += 1

    return summary
