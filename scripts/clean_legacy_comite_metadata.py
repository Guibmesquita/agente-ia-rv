"""
Script de limpeza: remove metadados obsoletos 'is_comite' e normaliza
'material_type=comite' nos chunks já indexados em document_embeddings.

Contexto:
  - Com a Task #146/147, os campos 'is_comite' e 'material_type=comite'
    deixaram de ser usados para determinar a tag [COMITÊ] no RAG.
  - Este script remove esses campos dos registros já existentes na tabela
    document_embeddings para evitar confusão e dados obsoletos.

Ações:
  1. Remove a chave 'is_comite' do JSON armazenado em extra_metadata.
  2. Define material_type=NULL nas linhas onde material_type='comite'
     (o valor era um marcador legado, não reflete o tipo real do material).

Uso:
    python scripts/clean_legacy_comite_metadata.py [--dry-run]
"""

import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(dry_run: bool = False):
    from database.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        print("=== Limpeza de metadados legados 'is_comite' / 'material_type=comite' ===")
        print(f"Modo: {'DRY-RUN (nenhuma alteração será salva)' if dry_run else 'EXECUÇÃO REAL'}\n")

        # ── 1. Limpar 'is_comite' do extra_metadata JSON ──────────────────────
        rows = db.execute(text(
            "SELECT id, extra_metadata FROM document_embeddings "
            "WHERE extra_metadata IS NOT NULL AND extra_metadata LIKE '%is_comite%'"
        )).fetchall()

        print(f"[is_comite] Chunks com 'is_comite' em extra_metadata: {len(rows)}")

        updated_extra = 0
        for row in rows:
            try:
                extra = json.loads(row.extra_metadata)
            except Exception:
                continue

            if "is_comite" not in extra:
                continue

            del extra["is_comite"]
            new_extra = json.dumps(extra) if extra else None

            if not dry_run:
                db.execute(
                    text("UPDATE document_embeddings SET extra_metadata = :val WHERE id = :id"),
                    {"val": new_extra, "id": row.id},
                )
            updated_extra += 1

        print(f"[is_comite] Chunks atualizados (extra_metadata): {updated_extra}")

        # ── 2. Normalizar material_type='comite' → NULL ───────────────────────
        count_row = db.execute(text(
            "SELECT COUNT(*) FROM document_embeddings WHERE material_type = 'comite'"
        )).scalar()

        print(f"\n[material_type] Chunks com material_type='comite': {count_row}")

        if count_row and count_row > 0:
            if not dry_run:
                db.execute(text(
                    "UPDATE document_embeddings SET material_type = NULL "
                    "WHERE material_type = 'comite'"
                ))
            print(f"[material_type] Chunks atualizados (material_type → NULL): {count_row}")
        else:
            print("[material_type] Nenhum chunk a atualizar.")

        # ── Commit ────────────────────────────────────────────────────────────
        if not dry_run:
            db.commit()
            print("\n[OK] Alterações salvas no banco de dados.")
        else:
            print("\n[DRY-RUN] Nenhuma alteração foi persistida.")

        # ── Verificação pós-limpeza ───────────────────────────────────────────
        if not dry_run:
            remaining_extra = db.execute(text(
                "SELECT COUNT(*) FROM document_embeddings "
                "WHERE extra_metadata LIKE '%is_comite%'"
            )).scalar()
            remaining_type = db.execute(text(
                "SELECT COUNT(*) FROM document_embeddings WHERE material_type = 'comite'"
            )).scalar()
            print(f"\n[Verificação] Chunks ainda com 'is_comite' em extra_metadata: {remaining_extra}")
            print(f"[Verificação] Chunks ainda com material_type='comite': {remaining_type}")
            if remaining_extra == 0 and remaining_type == 0:
                print("[OK] Limpeza concluída com sucesso — nenhum metadado legado encontrado.")
            else:
                print("[ATENÇÃO] Ainda há registros com metadados legados. Verifique manualmente.")

    except Exception as e:
        db.rollback()
        print(f"[ERRO] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Limpa metadados legados de is_comite/material_type=comite.")
    parser.add_argument("--dry-run", action="store_true", help="Executa sem salvar alterações.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
