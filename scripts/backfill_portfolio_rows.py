"""
Backfill RAG V3.6 — gera blocos `portfolio_row` para PDFs de carteira já ingeridos.

Para cada material com tabelas (TABLE/FINANCIAL_TABLE), inspeciona se a tabela
casa a heurística de carteira (coluna identificadora de ativo + coluna de
peso/participação) e, em caso afirmativo, emite um bloco sintético por linha
(ticker → embedding dedicado). Essa é a indexação que a V3.6 introduziu na
ingestão e que materiais antigos não tinham.

Idempotente: `_create_block` deduplica por `content_hash`. Pode ser rodado
quantas vezes for preciso — só cria o que ainda falta.

Uso:
    python -u -m scripts.backfill_portfolio_rows
    python -u -m scripts.backfill_portfolio_rows --dry-run
    python -u -m scripts.backfill_portfolio_rows --product-id 42
    python -u -m scripts.backfill_portfolio_rows --material-id 123
    python -u -m scripts.backfill_portfolio_rows --skip-index
    python -u -m scripts.backfill_portfolio_rows --limit 50 --sleep 1.0

Notas operacionais:
- Sempre rode com `python -u` (ou PYTHONUNBUFFERED=1) para não perder logs
  em redirecionamentos/arquivos.
- Reindex (vector store) é a parte mais lenta. Use `--skip-index` para um
  dry-run-like que só cria os blocos no banco.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import traceback
from typing import List, Optional


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _install_signal_handlers(state: dict) -> None:
    def _handler(signum, _frame):
        _log(
            f"[BACKFILL_PORTFOLIO] Recebido sinal {signum} — abortando. "
            f"Snapshot: {json.dumps(state, ensure_ascii=False)}"
        )
        sys.exit(130 if signum == signal.SIGINT else 143)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def _collect_eligible_material_ids(
    db, product_id: Optional[int], material_id: Optional[int], limit: Optional[int]
) -> List[int]:
    from database.models import ContentBlock, ContentBlockType, Material

    q = (
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
        q = q.filter(Material.id == material_id)
    if product_id is not None:
        q = q.filter(Material.product_id == product_id)
    q = q.order_by(Material.id.asc())
    if limit is not None:
        q = q.limit(limit)

    return [row[0] for row in q.all()]


def run(
    product_id: Optional[int],
    material_id: Optional[int],
    dry_run: bool,
    skip_index: bool,
    limit: Optional[int],
    sleep: float,
) -> dict:
    from database.database import SessionLocal
    from database.models import ContentBlock, ContentBlockType
    from services.product_ingestor import (
        _detect_portfolio_table,
        get_product_ingestor,
    )

    _log(
        f"[BACKFILL_PORTFOLIO] Iniciando — product_id={product_id} material_id={material_id} "
        f"dry_run={dry_run} skip_index={skip_index} limit={limit}"
    )

    ingestor = get_product_ingestor()
    db = SessionLocal()
    state = {
        "dry_run": dry_run,
        "skip_index": skip_index,
        "materials_eligible": 0,
        "materials_with_portfolio_tables": 0,
        "materials_with_new_blocks": 0,
        "materials_reindexed": 0,
        "materials_failed": 0,
        "tables_scanned": 0,
        "portfolio_tables_detected": 0,
        "portfolio_rows_created": 0,
        "skipped_invalid_json": 0,
    }
    _install_signal_handlers(state)

    try:
        material_ids = _collect_eligible_material_ids(db, product_id, material_id, limit)
        state["materials_eligible"] = len(material_ids)
        _log(f"[BACKFILL_PORTFOLIO] {len(material_ids)} material(is) elegível(is).")

        if not material_ids:
            return state

        total = len(material_ids)
        for idx, mid in enumerate(material_ids, start=1):
            if dry_run:
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
                detected = 0
                rows_estimate = 0
                invalid = 0
                for b in blocks:
                    state["tables_scanned"] += 1
                    try:
                        td = json.loads(b.content)
                    except (ValueError, TypeError):
                        invalid += 1
                        state["skipped_invalid_json"] += 1
                        continue
                    if not isinstance(td, dict):
                        continue
                    if _detect_portfolio_table(td):
                        detected += 1
                        state["portfolio_tables_detected"] += 1
                        rows_estimate += sum(
                            1
                            for r in (td.get("rows") or [])
                            if isinstance(r, list) and any(c for c in r if c)
                        )
                if detected > 0:
                    state["materials_with_portfolio_tables"] += 1
                    _log(
                        f"[BACKFILL_PORTFOLIO] [{idx}/{total}] dry-run material {mid} — "
                        f"{detected} tabela(s) carteira, ~{rows_estimate} linha(s)"
                    )
                continue

            t0 = time.time()
            try:
                res = ingestor.backfill_portfolio_row_blocks(
                    material_id=mid,
                    db=db,
                    user_id=None,
                    reindex=not skip_index,
                )
            except Exception as e:
                state["materials_failed"] += 1
                _log(
                    f"[BACKFILL_PORTFOLIO] [{idx}/{total}] ✗ material {mid} falhou: {e}"
                )
                _log(traceback.format_exc())
                if sleep > 0:
                    time.sleep(sleep)
                continue

            state["tables_scanned"] += res.get("tables_scanned", 0)
            state["portfolio_tables_detected"] += res.get("portfolio_tables_detected", 0)
            state["portfolio_rows_created"] += res.get("portfolio_rows_created", 0)
            state["skipped_invalid_json"] += res.get("skipped_invalid_json", 0)

            if res.get("portfolio_tables_detected", 0) > 0:
                state["materials_with_portfolio_tables"] += 1

            elapsed = time.time() - t0
            if res.get("portfolio_rows_created", 0) > 0:
                state["materials_with_new_blocks"] += 1
                if res.get("reindexed"):
                    state["materials_reindexed"] += 1
                _log(
                    f"[BACKFILL_PORTFOLIO] [{idx}/{total}] ✓ material {mid} — "
                    f"{res['portfolio_tables_detected']} tabela(s), "
                    f"{res['portfolio_rows_created']} bloco(s) novo(s), "
                    f"reindexed={res.get('reindexed', False)} "
                    f"indexed={res.get('indexed_count', 0)} ({elapsed:.1f}s)"
                )
            else:
                _log(
                    f"[BACKFILL_PORTFOLIO] [{idx}/{total}] · material {mid} — "
                    f"{res.get('portfolio_tables_detected', 0)} tabela(s) detectada(s), "
                    f"nenhum bloco novo (já existia) ({elapsed:.1f}s)"
                )

            if sleep > 0:
                time.sleep(sleep)

        return state
    finally:
        db.close()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass
    if not os.environ.get("PYTHONUNBUFFERED"):
        os.environ["PYTHONUNBUFFERED"] = "1"

    parser = argparse.ArgumentParser(
        description="Backfill RAG V3.6 — gera blocos portfolio_row para PDFs de carteira já ingeridos."
    )
    parser.add_argument("--product-id", type=int, default=None)
    parser.add_argument("--material-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Cria os blocos no banco mas pula a reindexação no vector store.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Segundos entre materiais (proteção rate-limit do embedding).",
    )

    args = parser.parse_args(argv)

    try:
        summary = run(
            product_id=args.product_id,
            material_id=args.material_id,
            dry_run=args.dry_run,
            skip_index=args.skip_index,
            limit=args.limit,
            sleep=max(0.0, args.sleep),
        )
    except Exception as e:
        _log(f"[BACKFILL_PORTFOLIO] ✗ Falha não tratada: {e}")
        _log(traceback.format_exc())
        return 1

    _log("[BACKFILL_PORTFOLIO] Resumo:")
    _log(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
