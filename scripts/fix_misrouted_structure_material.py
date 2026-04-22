"""
Re-rota um material que ficou erradamente vinculado ao ATIVO SUBJACENTE
em vez do produto-ESTRUTURA correspondente (ex.: "POP RAPT4.pdf" caiu no
produto research RAPT4 (ação) em vez de criar/usar "POP sobre RAPT4").

Faz remediação completa:
  1. Detecta se o material é estrutura via filename/nome
  2. Procura produto-estrutura existente que cubra o mesmo underlying
     (busca por nome contendo a keyword + ticker do produto atual)
  3. Se não encontrar, cria um produto novo do tipo `estruturada`
  4. Re-aponta `material.product_id` e ajusta `MaterialProductLink`

Idempotente. Por padrão roda em --dry-run e só explica o que faria.
Use --apply para executar.

Uso:
    python scripts/fix_misrouted_structure_material.py --material-id 123
    python scripts/fix_misrouted_structure_material.py --material-id 123 --apply
    python scripts/fix_misrouted_structure_material.py --scan          # varre TODOS
    python scripts/fix_misrouted_structure_material.py --scan --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import or_  # noqa: E402

from database.models import Material, MaterialProductLink, Product, ProductStatus  # noqa: E402
from database.database import SessionLocal  # noqa: E402
from services.upload_queue import UploadQueue  # noqa: E402


STRUCTURE_TYPES = {"estruturada", "estrutura", "estruturado"}


def _find_or_create_structure_product(db, struct_kw: str, underlying_ticker: str | None,
                                      gestora: str | None, apply: bool) -> Product | None:
    """Procura produto-estrutura compatível (mesmo underlying + mesma keyword
    no nome). Se não achar, cria um novo do tipo `estruturada`."""
    query = db.query(Product).filter(
        Product.status == ProductStatus.ATIVO,
        Product.product_type == "estruturada",
    )
    name_filters = [Product.name.ilike(f"%{struct_kw}%")]
    if underlying_ticker:
        name_filters.append(Product.name.ilike(f"%{underlying_ticker}%"))
    candidate = query.filter(*name_filters).first()
    if candidate:
        print(f"  → produto-estrutura existente compatível: "
              f"#{candidate.id} {candidate.name!r}")
        return candidate

    new_name_parts = [struct_kw.upper()]
    if underlying_ticker:
        new_name_parts.append(f"sobre {underlying_ticker}")
    new_name = " ".join(new_name_parts)
    print(f"  → vai criar produto-estrutura novo: {new_name!r}")
    if not apply:
        return None
    new = Product(
        name=new_name,
        ticker=None,
        product_type="estruturada",
        category="estruturada",
        gestora=gestora,
        status=ProductStatus.ATIVO,
    )
    db.add(new)
    db.flush()
    print(f"     criado #{new.id}")
    return new


def _process_material(db, mat: Material, apply: bool) -> bool:
    filename_hint = (
        getattr(mat, "source_filename", None)
        or (Path(mat.source_file_path).name if mat.source_file_path else None)
        or mat.name
    )
    struct_kw = UploadQueue._detect_structure_in_name(
        filename_hint, mat.name, getattr(mat, "source_filename", None)
    )

    print(f"Material #{mat.id}: {mat.name!r}")
    print(f"  filename: {filename_hint!r}")
    print(f"  product_id atual: {mat.product_id}")
    print(f"  estrutura detectada: {struct_kw or 'NENHUMA'}")

    if not struct_kw:
        print("  Skip: não é estrutura.")
        return False
    if not mat.product_id:
        print("  Skip: sem produto vinculado.")
        return False

    linked = db.query(Product).filter(Product.id == mat.product_id).first()
    linked_type = (linked.product_type or "").lower() if linked else ""
    if linked and linked_type in STRUCTURE_TYPES:
        print(f"  Skip: vínculo já é estrutura ({linked.name}, {linked.product_type}).")
        return False

    print(f"  produto vinculado errado: {linked.name if linked else '?'} "
          f"(type={linked.product_type if linked else '?'})")

    target = _find_or_create_structure_product(
        db,
        struct_kw=struct_kw,
        underlying_ticker=(linked.ticker if linked else None),
        gestora=(linked.gestora if linked else None),
        apply=apply,
    )

    if not apply:
        print("  [DRY-RUN] (use --apply para executar)")
        return True

    if linked:
        db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == mat.id,
            MaterialProductLink.product_id == linked.id,
        ).delete()
    if target:
        existing_link = db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == mat.id,
            MaterialProductLink.product_id == target.id,
        ).first()
        if not existing_link:
            db.add(MaterialProductLink(material_id=mat.id, product_id=target.id))
        mat.product_id = target.id
        print(f"  [OK] re-apontado para estrutura #{target.id}")
    else:
        mat.product_id = None
        print(f"  [OK] desvinculado (produto-estrutura não criado em dry-run).")
    db.commit()
    return True


def _scan_all(db, apply: bool) -> int:
    """Encontra todos os materiais com vínculo errado a uma ação subjacente."""
    candidates = (
        db.query(Material)
        .filter(Material.product_id.isnot(None))
        .all()
    )
    affected = 0
    for mat in candidates:
        try:
            if _process_material(db, mat, apply):
                affected += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"  [ERROR] material #{mat.id}: {e}")
    print(f"\n[SUMMARY] {affected} materiais{' corrigidos' if apply else ' detectados'}.")
    return affected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--material-id", type=int)
    parser.add_argument("--scan", action="store_true",
                        help="Varre todos os materiais e remedia os errados.")
    parser.add_argument("--apply", action="store_true",
                        help="Executa de fato. Sem essa flag, apenas explica.")
    args = parser.parse_args()

    if not args.material_id and not args.scan:
        parser.error("informe --material-id <id> ou --scan")

    db = SessionLocal()
    try:
        if args.scan:
            _scan_all(db, args.apply)
            return 0

        mat = db.query(Material).filter(Material.id == args.material_id).first()
        if not mat:
            print(f"[ERROR] Material id={args.material_id} não encontrado.")
            return 2
        _process_material(db, mat, args.apply)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
