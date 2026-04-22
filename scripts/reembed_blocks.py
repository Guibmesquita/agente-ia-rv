"""
Reembedding idempotente dos blocos de conteúdo (Task #152).

Para blocos com `embedding_version < TARGET_VERSION` (default 2):
1. Recalcula `content_for_embedding` (markdown para tabelas) e persiste no bloco.
2. Reindexa o bloco via ProductIngestor.
3. Marca o bloco com `embedding_version = TARGET_VERSION`.

É seguro rodar múltiplas vezes — só reprocessa o que ainda está em versão antiga.
Pode ser executado sob load (processa em lotes pequenos com sleep entre lotes).

Uso:
    python -m scripts.reembed_blocks --batch 50 --sleep 1.5
    python -m scripts.reembed_blocks --product-id 42
    python -m scripts.reembed_blocks --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Optional

from sqlalchemy import and_, or_

TARGET_VERSION = 2


def _iter_blocks(db, product_id: Optional[int], batch: int):
    """
    Itera blocos elegíveis usando cursor por id (estável mesmo quando
    `embedding_version` é atualizado durante o processamento). NUNCA usa OFFSET,
    que pularia registros conforme o conjunto encolhe.
    """
    from database.models import ContentBlock, Material

    last_id = 0
    while True:
        q = db.query(ContentBlock).join(Material, ContentBlock.material_id == Material.id)
        q = q.filter(
            ContentBlock.id > last_id,
            or_(
                ContentBlock.embedding_version.is_(None),
                ContentBlock.embedding_version < TARGET_VERSION,
            ),
        )
        if product_id is not None:
            q = q.filter(Material.product_id == product_id)
        rows = q.order_by(ContentBlock.id.asc()).limit(batch).all()
        if not rows:
            break
        for r in rows:
            yield r
        last_id = rows[-1].id


def _markdown_for_block(ingestor, block, product_name: str, product_ticker: Optional[str]) -> Optional[str]:
    """Gera markdown para tabela; retorna None para blocos não-tabela."""
    from database.models import ContentBlockType

    if block.block_type not in (ContentBlockType.TABLE.value, ContentBlockType.FINANCIAL_TABLE.value):
        return None
    try:
        data = json.loads(block.content)
        data.pop("_financial_metrics_detected", None)
    except Exception:
        return None
    try:
        return ingestor._table_to_markdown(
            data,
            title=block.title,
            product_name=product_name,
            product_ticker=product_ticker,
        )
    except Exception as e:
        print(f"[REEMBED] Falha gerar markdown bloco {block.id}: {e}")
        return None


def run(batch: int, sleep: float, product_id: Optional[int], dry_run: bool) -> dict:
    from database.database import SessionLocal
    from database.models import Material, Product
    from services.product_ingestor import get_product_ingestor

    ingestor = get_product_ingestor()
    db = SessionLocal()
    processed = 0
    upgraded = 0
    reindex_failed = 0
    materials_to_reindex: set = set()

    try:
        for block in _iter_blocks(db, product_id, batch):
            processed += 1
            material = db.query(Material).filter(Material.id == block.material_id).first()
            if not material:
                continue
            product = db.query(Product).filter(Product.id == material.product_id).first()
            if not product:
                continue

            md = _markdown_for_block(ingestor, block, product.name, product.ticker)
            if md is not None:
                block.content_for_embedding = md

            block.embedding_version = TARGET_VERSION
            materials_to_reindex.add(material.id)
            upgraded += 1

            if processed % batch == 0:
                if not dry_run:
                    db.commit()
                print(f"[REEMBED] Lote: {processed} blocos processados ({upgraded} marcados v{TARGET_VERSION})")
                time.sleep(sleep)

        if not dry_run:
            db.commit()

        if not dry_run:
            for mid in materials_to_reindex:
                try:
                    ingestor.index_material(mid)
                except Exception as e:
                    reindex_failed += 1
                    print(f"[REEMBED] Reindex falhou material {mid}: {e}")
                time.sleep(sleep / 2)

        return {
            "processed": processed,
            "upgraded": upgraded,
            "materials_reindexed": len(materials_to_reindex) - reindex_failed,
            "reindex_failed": reindex_failed,
            "dry_run": dry_run,
            "target_version": TARGET_VERSION,
        }
    finally:
        db.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reembedding idempotente — Task #152")
    parser.add_argument("--batch", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=1.5, help="Segundos entre lotes (proteção rate-limit)")
    parser.add_argument("--product-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = run(
        batch=args.batch,
        sleep=args.sleep,
        product_id=args.product_id,
        dry_run=args.dry_run,
    )
    print("[REEMBED] Resumo:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
