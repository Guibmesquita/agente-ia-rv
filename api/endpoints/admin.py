"""
Endpoints de administração transversais (prefixo /api/admin).
Agrega diagnósticos e ferramentas de gestão interna restritas ao role admin.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.database import get_db
from database.models import Product, User
from api.endpoints.auth import get_current_user


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
