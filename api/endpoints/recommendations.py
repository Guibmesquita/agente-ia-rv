"""
Endpoints para gerenciar a lista de recomendações formais do Comitê SVN.
A tabela recommendation_entries é a fonte de verdade para 'quais produtos
estão no comitê ativo hoje'.
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.database import get_db
from database.models import Product, RecommendationEntry
from api.endpoints.auth import get_current_user
from database.models import User

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])
page_router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory="frontend/templates")

VALID_RATINGS = ["Compra", "Manutenção", "Venda"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RecommendationCreate(BaseModel):
    product_id: int
    rating: Optional[str] = None
    target_price: Optional[float] = None
    rationale: Optional[str] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None


class RecommendationUpdate(BaseModel):
    rating: Optional[str] = None
    target_price: Optional[float] = None
    rationale: Optional[str] = None
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


# ── Helper ────────────────────────────────────────────────────────────────────

def _sync_product_categories(db: Session, product: Product):
    """Garante que 'Comitê' esteja (ou não) em Product.categories conforme recomendações ativas."""
    now = datetime.utcnow()
    has_active = db.query(RecommendationEntry).filter(
        RecommendationEntry.product_id == product.id,
        RecommendationEntry.is_active == True,
    ).filter(
        (RecommendationEntry.valid_until == None) |
        (RecommendationEntry.valid_until >= now)
    ).first()

    cats = product.get_categories()
    if has_active and "Comitê" not in cats:
        cats.append("Comitê")
        product.set_categories(cats)
    elif not has_active and "Comitê" in cats:
        cats = [c for c in cats if c != "Comitê"]
        product.set_categories(cats)


def _entry_to_dict(entry: RecommendationEntry) -> dict:
    product = entry.product
    now = datetime.utcnow()
    expired = (entry.valid_until is not None and entry.valid_until < now)
    status = "expirado" if expired else ("vigente" if entry.is_active else "inativo")
    return {
        "id": entry.id,
        "product_id": entry.product_id,
        "product_name": product.name if product else "",
        "product_ticker": product.ticker if product else "",
        "product_manager": product.manager if product else "",
        "rating": entry.rating,
        "target_price": entry.target_price,
        "rationale": entry.rationale,
        "notes": entry.notes,
        "added_by": entry.added_by,
        "added_at": entry.added_at.isoformat() if entry.added_at else None,
        "valid_from": entry.valid_from.isoformat() if entry.valid_from else None,
        "valid_until": entry.valid_until.isoformat() if entry.valid_until else None,
        "is_active": entry.is_active,
        "status": status,
    }


# ── API Endpoints ──────────────────────────────────────────────────────────────

@router.get("")
async def list_recommendations(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista recomendações do comitê. Restrito a admin e gestão RV."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")
    now = datetime.utcnow()
    q = db.query(RecommendationEntry)

    if not include_inactive:
        q = q.filter(
            RecommendationEntry.is_active == True,
        ).filter(
            (RecommendationEntry.valid_until == None) |
            (RecommendationEntry.valid_until >= now)
        )

    entries = q.order_by(RecommendationEntry.added_at.desc()).all()
    return [_entry_to_dict(e) for e in entries]


@router.get("/check/{product_id}")
async def check_recommendation(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verifica se um produto está atualmente no comitê. Restrito a admin e gestão RV."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")
    now = datetime.utcnow()
    entry = db.query(RecommendationEntry).filter(
        RecommendationEntry.product_id == product_id,
        RecommendationEntry.is_active == True,
    ).filter(
        (RecommendationEntry.valid_until == None) |
        (RecommendationEntry.valid_until >= now)
    ).first()
    return {"in_committee": entry is not None, "entry": _entry_to_dict(entry) if entry else None}


@router.post("", status_code=201)
async def create_recommendation(
    data: RecommendationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Adiciona um produto à lista de recomendações do Comitê."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Produto id={data.product_id} não encontrado")

    if data.rating and data.rating not in VALID_RATINGS:
        raise HTTPException(status_code=422, detail=f"Rating inválido. Use um de: {VALID_RATINGS}")

    # Desativar entradas anteriores ativas para o mesmo produto
    old_entries = db.query(RecommendationEntry).filter(
        RecommendationEntry.product_id == data.product_id,
        RecommendationEntry.is_active == True,
    ).all()
    for e in old_entries:
        e.is_active = False

    entry = RecommendationEntry(
        product_id=data.product_id,
        rating=data.rating,
        target_price=data.target_price,
        rationale=data.rationale,
        added_by=current_user.email or current_user.username,
        valid_from=datetime.utcnow(),
        valid_until=data.valid_until,
        notes=data.notes,
        is_active=True,
    )
    db.add(entry)
    db.flush()

    _sync_product_categories(db, product)
    db.commit()
    db.refresh(entry)

    print(f"[COMITÊ] Produto '{product.name}' adicionado ao comitê por {current_user.email}")
    return _entry_to_dict(entry)


@router.patch("/{entry_id}")
async def update_recommendation(
    entry_id: int,
    data: RecommendationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edita uma entrada de recomendação (rating, preço-alvo, vigência, notas)."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    entry = db.query(RecommendationEntry).filter(RecommendationEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada não encontrada")

    # Usar model_fields_set para distinguir "campo ausente" de "campo explicitamente nulo"
    explicitly_set = data.model_fields_set if hasattr(data, "model_fields_set") else set(data.dict(exclude_unset=True).keys())

    if "rating" in explicitly_set:
        if data.rating is not None and data.rating not in VALID_RATINGS:
            raise HTTPException(status_code=422, detail=f"Rating inválido. Use um de: {VALID_RATINGS}")
        entry.rating = data.rating
    if "target_price" in explicitly_set:
        entry.target_price = data.target_price
    if "rationale" in explicitly_set:
        entry.rationale = data.rationale
    if "valid_until" in explicitly_set:
        entry.valid_until = data.valid_until
    if "notes" in explicitly_set:
        entry.notes = data.notes
    if "is_active" in explicitly_set:
        entry.is_active = data.is_active

    product = db.query(Product).filter(Product.id == entry.product_id).first()
    if product:
        _sync_product_categories(db, product)

    db.commit()
    db.refresh(entry)
    return _entry_to_dict(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_recommendation(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove (desativa) uma entrada de recomendação do comitê."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    entry = db.query(RecommendationEntry).filter(RecommendationEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada não encontrada")

    entry.is_active = False

    product = db.query(Product).filter(Product.id == entry.product_id).first()
    if product:
        _sync_product_categories(db, product)

    db.commit()
    return None


# ── Página do painel ──────────────────────────────────────────────────────────

@page_router.get("/comite", response_class=HTMLResponse)
async def comite_panel_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Painel de gestão do Comitê Ativo SVN."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito")

    products = db.query(Product).filter(Product.status == "ativo").order_by(Product.name).all()
    products_list = [
        {"id": p.id, "name": p.name, "ticker": p.ticker or "", "manager": p.manager or ""}
        for p in products
    ]

    return templates.TemplateResponse(
        "comite_panel.html",
        {
            "request": request,
            "user_role": current_user.role,
            "current_user": current_user,
            "products_list": products_list,
        },
    )
