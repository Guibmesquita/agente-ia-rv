"""
One-shot orquestrado para rodar a normalização de `product_type` em produção.

Pensado para ser executado como Scheduled Deployment (one-shot) na Replit,
após o próximo deploy do app principal. Faz, em sequência e de forma
idempotente:

  1. Garante que as colunas novas (`product_type`, `key_info`,
     `is_committee`, `categories`) existam — caso o app ainda não tenha
     subido com o startup que aplica os ALTERs em `main.py`, o script
     mesmo se vira.
  2. Mostra um snapshot ANTES (totais por product_type, incluindo NULL).
  3. Roda `backfill_product_types.main(dry_run=True)` para preview.
  4. Roda `backfill_product_types.main(dry_run=False)` para gravar.
  5. Roda `audit_product_types.main(limit=500)` para listar o que sobrou
     em NULL ou marcado como 'outro' para revisão manual.
  6. Mostra um snapshot DEPOIS e faz uma checagem final: encerra com
     exit code != 0 se ainda houver `product_type` NULL/vazio.

Uso (local ou via Scheduled Deployment):
    python scripts/run_product_type_backfill_oneshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ensure_schema() -> None:
    """Aplica os ALTERs idempotentes que `main.py` normalmente faz no startup."""
    from sqlalchemy import text
    from database.database import engine

    statements = [
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS key_info TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_committee BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS categories TEXT DEFAULT '[]'",
    ]
    print("--- Garantindo schema (ALTER TABLE IF NOT EXISTS) ---")
    with engine.begin() as conn:
        for stmt in statements:
            print(f"  > {stmt}")
            conn.execute(text(stmt))
    print("[OK] Schema verificado.\n")


def _snapshot(label: str) -> int:
    """Imprime totais por product_type. Retorna a contagem de NULL/vazio."""
    from sqlalchemy import text
    from database.database import engine

    print(f"--- Snapshot {label} ---")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(product_type), ''), '<NULL/empty>') AS pt,
                       COUNT(*) AS c
                FROM products
                GROUP BY 1
                ORDER BY c DESC
                """
            )
        ).all()
        nulls = conn.execute(
            text(
                "SELECT COUNT(*) FROM products "
                "WHERE product_type IS NULL OR TRIM(product_type) = ''"
            )
        ).scalar_one()

    print(f"{'product_type':<20}  count")
    for pt, c in rows:
        print(f"{pt:<20}  {c}")
    print(f"(NULL/vazio: {nulls})\n")
    return int(nulls or 0)


def main() -> None:
    print("============================================================")
    print(" Backfill one-shot de product_type em produção")
    print("============================================================\n")

    _ensure_schema()
    _snapshot("ANTES")

    from scripts import backfill_product_types, audit_product_types

    print("--- DRY-RUN (preview) ---")
    backfill_product_types.main(dry_run=True)
    print()

    print("--- EXECUÇÃO REAL ---")
    backfill_product_types.main(dry_run=False)
    print()

    print("--- AUDITORIA ---")
    audit_product_types.main(limit=500)
    print()

    nulls_after = _snapshot("DEPOIS")

    if nulls_after > 0:
        print(
            f"[FALHA] Ainda restam {nulls_after} produtos com product_type "
            "NULL/vazio. Investigue manualmente."
        )
        sys.exit(2)

    print("[OK] 0 produtos com product_type NULL/vazio. Backfill concluído.")


if __name__ == "__main__":
    main()
