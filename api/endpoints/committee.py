"""
Endpoints para gestão do Comitê Ativo (Change 3c).

Isolamento por produto: um material pode estar ativo no comitê, mas produtos específicos
podem ser excluídos via MaterialProductLink.excluded_from_committee.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func as _sa_func

from database.database import get_db
from database.models import Material, MaterialProductLink, Product, User
from api.endpoints.auth import get_current_user


router = APIRouter(prefix="/api/committee", tags=["committee"])


def _require_role(current_user: User) -> None:
    if current_user.role not in ("admin", "gestao_rv", "broker"):
        raise HTTPException(status_code=403, detail="Acesso negado")


def _build_status(db: Session) -> dict:
    """Constrói o snapshot atual do Comitê Ativo."""
    active_materials = (
        db.query(Material)
          .filter(Material.is_committee_active == True)
          .all()
    )

    materials_payload = []
    products_map: dict = {}  # (product_id, material_id) -> info

    for mat in active_materials:
        links = (
            db.query(MaterialProductLink)
              .filter(MaterialProductLink.material_id == mat.id)
              .all()
        )

        linked_product_ids = set()
        product_count_active = 0
        for link in links:
            prod = db.query(Product).filter(Product.id == link.product_id).first()
            if not prod:
                continue
            linked_product_ids.add(prod.id)
            if not link.excluded_from_committee:
                product_count_active += 1

            key = (prod.id, mat.id)
            products_map[key] = {
                "id": prod.id,
                "name": prod.name,
                "ticker": prod.ticker,
                "source_material_id": mat.id,
                "source_material_name": mat.name,
                "excluded": bool(link.excluded_from_committee),
            }

        # Produto primário do material (Material.product_id): pode não ter MaterialProductLink.
        # Incluí-lo no status como não-excluído por padrão permite isolamento por produto
        # mesmo quando o material tem apenas um produto principal.
        primary_pid = getattr(mat, "product_id", None)
        if primary_pid and primary_pid not in linked_product_ids:
            prod = db.query(Product).filter(Product.id == primary_pid).first()
            if prod:
                product_count_active += 1
                products_map[(prod.id, mat.id)] = {
                    "id": prod.id,
                    "name": prod.name,
                    "ticker": prod.ticker,
                    "source_material_id": mat.id,
                    "source_material_name": mat.name,
                    "excluded": False,
                }

        materials_payload.append({
            "id": mat.id,
            "name": mat.name,
            "type": mat.material_type,
            "product_count": product_count_active,
            "is_active": True,
        })

    products_payload = list(products_map.values())
    return {
        "is_active": len(active_materials) > 0,
        "materials": materials_payload,
        "products": products_payload,
    }


@router.get("/status")
async def committee_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_role(current_user)
    return _build_status(db)


@router.get("/available-materials")
async def committee_available_materials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Materiais publicados e indexados disponíveis para seleção no comitê."""
    _require_role(current_user)
    rows = (
        db.query(Material)
          .filter(
              Material.publish_status == "publicado",
              Material.is_indexed == True,
          )
          .order_by(Material.published_at.desc().nullslast(), Material.id.desc())
          .all()
    )
    result = []
    for m in rows:
        link_count = db.query(_sa_func.count(MaterialProductLink.id)).filter(
            MaterialProductLink.material_id == m.id
        ).scalar() or 0
        result.append({
            "id": m.id,
            "name": m.name,
            "type": m.material_type,
            "product_count": int(link_count),
            "published_at": m.published_at.isoformat() if m.published_at else None,
            "is_committee_active": bool(m.is_committee_active),
        })
    return {"materials": result}


@router.post("/add-material")
async def committee_add_material(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_role(current_user)
    body = await request.json()
    material_id = body.get("material_id")
    if not material_id:
        raise HTTPException(status_code=400, detail="material_id é obrigatório")

    mat = db.query(Material).filter(Material.id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    mat.is_committee_active = True
    db.commit()
    return _build_status(db)


@router.post("/remove-material")
async def committee_remove_material(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_role(current_user)
    body = await request.json()
    material_id = body.get("material_id")
    if not material_id:
        raise HTTPException(status_code=400, detail="material_id é obrigatório")

    mat = db.query(Material).filter(Material.id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    mat.is_committee_active = False
    db.commit()
    return _build_status(db)


def _get_or_create_link(db: Session, material_id: int, product_id: int) -> MaterialProductLink:
    """Obtém o link material-produto; se não existir mas o produto for o primário do
    material (Material.product_id), cria o link. Caso contrário, levanta 404."""
    link = db.query(MaterialProductLink).filter(
        MaterialProductLink.material_id == material_id,
        MaterialProductLink.product_id == product_id,
    ).first()
    if link:
        return link

    mat = db.query(Material).filter(Material.id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Aceita criar link se for o produto primário do material (caso comum: material
    # com único produto gravado em Material.product_id e sem MaterialProductLink).
    if getattr(mat, "product_id", None) == product_id:
        link = MaterialProductLink(
            material_id=material_id,
            product_id=product_id,
            excluded_from_committee=False,
        )
        db.add(link)
        db.flush()
        return link

    raise HTTPException(status_code=404, detail="Vínculo material-produto não encontrado")


@router.post("/exclude-product")
async def committee_exclude_product(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_role(current_user)
    body = await request.json()
    material_id = body.get("material_id")
    product_id = body.get("product_id")
    if not material_id or not product_id:
        raise HTTPException(status_code=400, detail="material_id e product_id são obrigatórios")

    link = _get_or_create_link(db, int(material_id), int(product_id))
    link.excluded_from_committee = True
    db.commit()
    return _build_status(db)


@router.post("/include-product")
async def committee_include_product(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_role(current_user)
    body = await request.json()
    material_id = body.get("material_id")
    product_id = body.get("product_id")
    if not material_id or not product_id:
        raise HTTPException(status_code=400, detail="material_id e product_id são obrigatórios")

    link = _get_or_create_link(db, int(material_id), int(product_id))
    link.excluded_from_committee = False
    db.commit()
    return _build_status(db)


@router.post("/add-product-manually")
async def committee_add_product_manually(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Adiciona manualmente um produto ao Comitê, via material de referência.
    Cria MaterialProductLink se não existir e marca excluded_from_committee=False.
    O material de referência precisa estar com is_committee_active=True para o
    produto aparecer efetivamente no comitê.
    """
    _require_role(current_user)
    body = await request.json()
    product_id = body.get("product_id")
    reference_material_id = body.get("reference_material_id")
    if not product_id or not reference_material_id:
        raise HTTPException(
            status_code=400,
            detail="product_id e reference_material_id são obrigatórios",
        )

    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    mat = db.query(Material).filter(Material.id == reference_material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material de referência não encontrado")

    link = db.query(MaterialProductLink).filter(
        MaterialProductLink.material_id == reference_material_id,
        MaterialProductLink.product_id == product_id,
    ).first()
    if not link:
        link = MaterialProductLink(
            material_id=reference_material_id,
            product_id=product_id,
            excluded_from_committee=False,
        )
        db.add(link)
    else:
        link.excluded_from_committee = False
    db.commit()
    return _build_status(db)


@router.get("/admin/diagnostic")
async def committee_admin_diagnostic(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Diagnóstico do sistema de comitê.

    Retorna três perspectivas para verificar a consistência:
    - star_products: produtos com Product.is_committee=True (fonte de verdade)
    - active_rec_entries: RecommendationEntry ativas (enriquecimento)
    - effective_committee: o que o agente Stevan enxerga no system prompt

    Acesso restrito a admin.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")

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

    # Carteira efetiva (injetada no system prompt)
    vs = get_vector_store()
    effective = vs.get_committee_summary()
    effective_names = [e.get("product_name") for e in effective]

    # Divergências
    entries_without_star = entry_ids - star_ids
    stars_without_entry = star_ids - entry_ids

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
            "entries_without_star": list(entries_without_star),
            "stars_without_entry": list(stars_without_entry),
            "note": (
                "entries_without_star: RecommendationEntry não enriquecerão o comitê (produto sem estrela). "
                "stars_without_entry: produtos no comitê sem dados de enriquecimento (rating/preço-alvo ausentes)."
            ),
        },
        "summary": {
            "star_count": len(star_products),
            "rec_entry_count": len(active_entries),
            "effective_count": len(effective),
            "products_in_prompt": effective_names,
        },
    }
