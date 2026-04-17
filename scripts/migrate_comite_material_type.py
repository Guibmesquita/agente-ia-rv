"""
Migração de dados: atualiza material_type='comite' → 'outro' na tabela materials.

Contexto:
  - Com a Task #147, a consulta por material_type='comite' foi removida do
    pipeline de busca (search_comite_vigent).
  - Registros com material_type='comite' são agora dados mortos que não
    influenciam nenhum comportamento, mas poluem o banco de dados.
  - Este script atualiza esses registros para o valor neutro 'outro',
    que corresponde a MaterialType.OTHER no enum da aplicação.

Ações:
  1. Conta os registros afetados (Material.material_type = 'comite').
  2. Atualiza material_type para 'outro' em todos esses registros.
  3. Verifica que nenhum registro com material_type='comite' permanece.

Uso:
    python scripts/migrate_comite_material_type.py [--dry-run]
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(dry_run: bool = False):
    from database.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        print("=== Migração: material_type='comite' → 'outro' na tabela materials ===")
        print(f"Modo: {'DRY-RUN (nenhuma alteração será salva)' if dry_run else 'EXECUÇÃO REAL'}\n")

        count = db.execute(text(
            "SELECT COUNT(*) FROM materials WHERE material_type = 'comite'"
        )).scalar()

        print(f"Registros com material_type='comite': {count}")

        if count and count > 0:
            if not dry_run:
                db.execute(text(
                    "UPDATE materials SET material_type = 'outro' WHERE material_type = 'comite'"
                ))
                db.commit()
                print(f"[OK] {count} registro(s) atualizado(s): material_type='comite' → 'outro'")
            else:
                print(f"[DRY-RUN] {count} registro(s) seriam atualizados.")
        else:
            print("[OK] Nenhum registro com material_type='comite' encontrado. Nada a fazer.")

        if not dry_run:
            remaining = db.execute(text(
                "SELECT COUNT(*) FROM materials WHERE material_type = 'comite'"
            )).scalar()
            print(f"\n[Verificação] Registros ainda com material_type='comite': {remaining}")
            if remaining == 0:
                print("[OK] Migração concluída com sucesso — nenhum registro legado encontrado.")
            else:
                print("[ATENÇÃO] Ainda há registros com material_type='comite'. Verifique manualmente.")
                sys.exit(1)

    except Exception as e:
        db.rollback()
        print(f"[ERRO] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migra material_type='comite' para 'outro' na tabela materials."
    )
    parser.add_argument("--dry-run", action="store_true", help="Executa sem salvar alterações.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
