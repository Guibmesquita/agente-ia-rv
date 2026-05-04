"""
Task #204 (Frente D) — Reindexa materiais do tipo CARTEIRA para corrigir
metadata stale em `document_embeddings`.

Cenário corrigido:
  Após a Task #200, alguns materiais tiveram a redistribuição de blocos
  para tickers individuais REVERTIDA (blocos voltaram ao material principal),
  mas o `extra_metadata` JSON dos embeddings continuou apontando para os
  produtos antigos (produto FII individual em vez de produto-carteira).
  Resultado: a busca por "Carteira Seven FIIs" não consegue agrupar os
  blocos corretamente porque cada portfolio_row diz `product_id=35` em vez de
  `product_id=47`, e `products="TVRI11"` em vez de `products="CARTEIRA SEVEN..."`.

  O script `fix_phantom_portfolio_materials.py` só atualiza colunas de
  primeiro nível (`material_id`, `product_name`, `product_ticker`); o JSON
  `extra_metadata` fica intacto. Este script reindexa via
  `ProductIngestor().index_approved_blocks(...)`, que reescreve o
  `extra_metadata` inteiro através do `add_document` com `ON CONFLICT DO
  UPDATE`.

  CUSTO: gera novos embeddings (1 chamada à OpenAI por bloco). Para uma
  carteira de 12 FIIs (~20 blocos), são ~20 chamadas (~$0.001).

Uso:
    # Diagnóstico (default — não modifica nada)
    python scripts/reindex_portfolio_materials.py

    # Aplicar correções
    python scripts/reindex_portfolio_materials.py --apply

    # Limitar a um material específico
    python scripts/reindex_portfolio_materials.py --material-id 47 --apply

Idempotente: pode rodar múltiplas vezes sem efeito colateral. Compatível
com dev (DATABASE_URL local) e produção (Railway, mesma var).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import bindparam, text  # noqa: E402

from database.database import SessionLocal  # noqa: E402
from database.models import Material, Product  # noqa: E402
from services.product_ingestor import (  # noqa: E402
    ProductIngestor,
    _is_portfolio_material,
)


def _find_portfolio_materials(
    db, only_material_id: Optional[int] = None
) -> List[Material]:
    """Encontra materiais que são CARTEIRAS.

    Critérios (qualquer um basta):
      - Produto associado tem product_type='carteira'
      - Helper `_is_portfolio_material` retorna True (nome do material/produto
        contém keyword de carteira: "carteira", "portfólio", etc.)
    """
    if only_material_id is not None:
        m = db.query(Material).filter(Material.id == only_material_id).first()
        if not m:
            return []
        prod = (
            db.query(Product).filter(Product.id == m.product_id).first()
            if m.product_id else None
        )
        if _is_portfolio_material(m, prod, m.name):
            return [m]
        prod_type = (prod.product_type or "").lower() if prod else ""
        if prod_type == "carteira":
            return [m]
        print(f"[SKIP] mat#{only_material_id} não parece ser uma carteira "
              f"(name={m.name!r}, product_type={prod_type!r}). "
              "Re-execute sem --material-id para varrer todas.")
        return []

    candidates = (
        db.query(Material)
        .join(Product, Material.product_id == Product.id, isouter=True)
        .filter(
            Material.source_file_path.isnot(None),  # exclui placeholders
        )
        .all()
    )
    matches: List[Material] = []
    for m in candidates:
        prod = (
            db.query(Product).filter(Product.id == m.product_id).first()
            if m.product_id else None
        )
        prod_type = (prod.product_type or "").lower() if prod else ""
        if prod_type == "carteira" or _is_portfolio_material(m, prod, m.name):
            matches.append(m)
    return matches


def _show_baseline(db, material: Material) -> None:
    """Imprime amostra do extra_metadata atual antes da reindexação."""
    rows = db.execute(text("""
        SELECT doc_id, product_name, product_ticker,
               LEFT(extra_metadata, 240) AS extra
          FROM document_embeddings
         WHERE material_id = :mid
         ORDER BY doc_id
         LIMIT 3
    """), {"mid": str(material.id)}).fetchall()
    if not rows:
        print(f"  [BASELINE] mat#{material.id}: nenhum embedding existente.")
        return
    print(f"  [BASELINE] mat#{material.id} — amostra de embeddings ANTES:")
    for r in rows:
        print(f"    doc_id={r.doc_id} product_name={r.product_name!r} "
              f"product_ticker={r.product_ticker!r}")
        print(f"      extra={r.extra}")


def _reindex_one(db, material: Material, apply: bool) -> dict:
    """Apaga e regenera os embeddings de um material via index_approved_blocks."""
    product = (
        db.query(Product).filter(Product.id == material.product_id).first()
        if material.product_id else None
    )
    pname = product.name if product else (material.name or "")
    pticker = (product.ticker or None) if product else None

    n_existing = db.execute(
        text("SELECT COUNT(*) FROM document_embeddings WHERE material_id = :mid"),
        {"mid": str(material.id)},
    ).scalar() or 0

    print(
        f"\n  mat#{material.id} ({material.name!r}) prod#{material.product_id} "
        f"(name={pname!r}, ticker={pticker!r}, type="
        f"{(product.product_type if product else None)!r}): "
        f"{n_existing} embeddings existentes."
    )

    if not apply:
        return {"embeddings_before": n_existing, "embeddings_after": 0,
                "blocks_indexed": 0, "applied": False}

    # ESTRATÉGIA SAFE-FIRST (sugestão do code review):
    # 1) PRIMEIRO indexa (add_document faz UPSERT por doc_id, sobrescrevendo
    #    `extra_metadata` corretamente). Se a OpenAI ou o ingestor falhar,
    #    os embeddings antigos permanecem como fallback — o material nunca
    #    fica com zero embeddings.
    # 2) DEPOIS deleta apenas os ÓRFÃOS — embeddings cujos `doc_id` não
    #    estão no conjunto atual de blocos (resíduo de blocos removidos
    #    do `content_blocks`).
    from database.models import ContentBlock as _CBLite, ContentBlockStatus as _CBSLite
    current_block_ids = [
        b.id for b in (
            db.query(_CBLite.id)
            .filter(_CBLite.material_id == material.id)
            .filter(_CBLite.status.in_([
                _CBSLite.APPROVED.value, _CBSLite.AUTO_APPROVED.value,
            ]))
            .all()
        )
    ]
    expected_doc_ids = [f"product_block_{bid}" for bid in current_block_ids]

    # 1) Reindexa via pipeline padrão (regenera embeddings + extra_metadata).
    #    UPSERT por doc_id mantém o conjunto atual sempre íntegro.
    ingestor = ProductIngestor()
    result = ingestor.index_approved_blocks(
        material_id=material.id,
        product_name=pname,
        product_ticker=pticker,
        db=db,
    )

    # 2) Limpa órfãos (somente se o passo 1 terminou sem exceção). Quando
    #    `expected_doc_ids` está vazio (material sem blocos aprovados), pula
    #    o DELETE para evitar apagar embeddings legados sem reposição.
    if expected_doc_ids:
        db.execute(
            text(
                "DELETE FROM document_embeddings "
                "WHERE material_id = :mid AND doc_id NOT IN :keep"
            ).bindparams(bindparam("keep", expanding=True)),
            {"mid": str(material.id), "keep": expected_doc_ids},
        )
        db.commit()

    n_after = db.execute(
        text("SELECT COUNT(*) FROM document_embeddings WHERE material_id = :mid"),
        {"mid": str(material.id)},
    ).scalar() or 0

    indexed = (
        result.get("indexed_count", 0)
        if isinstance(result, dict) else 0
    )
    print(
        f"    reindexado: {indexed} blocos → {n_after} embeddings "
        f"(antes: {n_existing})."
    )
    return {
        "embeddings_before": n_existing,
        "embeddings_after": n_after,
        "blocks_indexed": indexed,
        "applied": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Executa de fato. Sem essa flag, apenas mostra o que faria.",
    )
    parser.add_argument(
        "--material-id", type=int, default=None,
        help="Limitar a reindexação a um material específico.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        materials = _find_portfolio_materials(db, only_material_id=args.material_id)
        print(f"[SCAN] {len(materials)} material(is) carteira encontrado(s).")
        if not materials:
            print("[OK] Nada a reindexar.")
            return 0

        totals = {
            "materials_processed": 0,
            "embeddings_before": 0,
            "embeddings_after": 0,
            "blocks_indexed": 0,
        }

        for m in materials:
            _show_baseline(db, m)
            try:
                stats = _reindex_one(db, m, args.apply)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(f"  [ERROR] mat#{m.id}: {e}")
                continue
            totals["materials_processed"] += 1
            totals["embeddings_before"] += stats["embeddings_before"]
            totals["embeddings_after"] += stats["embeddings_after"]
            totals["blocks_indexed"] += stats["blocks_indexed"]

        print("\n[SUMMARY]")
        for k, v in totals.items():
            print(f"  {k}: {v}")

        if not args.apply:
            print("\n[DRY-RUN] Nada foi alterado. Re-execute com --apply.")
        else:
            print("\n[DONE] Reindexação concluída.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
