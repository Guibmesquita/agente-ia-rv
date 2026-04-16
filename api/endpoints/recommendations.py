"""
Endpoints para gerenciar a lista de recomendações formais do Comitê SVN.
A tabela recommendation_entries é a fonte de verdade para 'quais produtos
estão no comitê ativo hoje'.
"""
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.database import get_db
from database.models import Product, RecommendationEntry, Material
from api.endpoints.auth import get_current_user
from database.models import User

logger = logging.getLogger(__name__)

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


# ── Importação via Material ────────────────────────────────────────────────────

class BulkImportItem(BaseModel):
    product_id: int
    rating: Optional[str] = None
    target_price: Optional[float] = None
    rationale: Optional[str] = None
    valid_until: Optional[datetime] = None


class BulkImportRequest(BaseModel):
    items: List[BulkImportItem]


@router.get("/materials-for-import")
async def list_materials_for_import(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lista materiais disponíveis para importação de recomendações do Comitê.
    Prioriza materiais do tipo 'comite', depois exibe os demais.
    Restrito a admin e gestão RV.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    from sqlalchemy import case
    from database.models import ContentBlock

    materials_with_blocks = db.query(Material.id).join(
        ContentBlock, ContentBlock.material_id == Material.id
    ).subquery()

    materials = (
        db.query(Material)
        .filter(Material.id.in_(materials_with_blocks))
        .order_by(
            case(
                (Material.material_type == "comite", 0),
                else_=1
            ),
            Material.created_at.desc()
        )
        .limit(200)
        .all()
    )

    result = []
    for m in materials:
        product = m.product
        result.append({
            "id": m.id,
            "name": m.name or m.source_filename or f"Material #{m.id}",
            "material_type": m.material_type,
            "product_id": m.product_id,
            "product_name": product.name if product else None,
            "product_ticker": product.ticker if product else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "ai_summary": (m.ai_summary or "")[:150] if m.ai_summary else None,
        })

    return result


@router.post("/preview-import/{material_id}")
async def preview_import_from_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Analisa um material e retorna um preview das recomendações identificadas.
    Usa GPT-4o-mini para extrair produtos, ratings, preços-alvo e racionais do conteúdo.
    Cada item retornado inclui flags `unresolved` e `already_in_committee`.
    Restrito a admin e gestão RV.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail=f"Material id={material_id} não encontrado")

    try:
        from services.committee_importer import extract_committee_from_material
        items = extract_committee_from_material(db, material_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"[preview-import] Erro inesperado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao analisar material: {str(e)}")

    return {
        "material_id": material_id,
        "material_name": material.name or material.source_filename or f"Material #{material_id}",
        "items": items,
        "total": len(items),
        "resolved": sum(1 for i in items if not i["unresolved"]),
        "unresolved": sum(1 for i in items if i["unresolved"]),
    }


@router.post("/bulk-import", status_code=201)
async def bulk_import_recommendations(
    data: BulkImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Cria RecommendationEntry para cada produto na lista confirmada.
    Desativa entradas anteriores ativas para os mesmos produtos (mesmo comportamento do POST individual).
    Retorna contagem de criados e lista de erros se houver.
    Restrito a admin e gestão RV.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    if not data.items:
        raise HTTPException(status_code=422, detail="Lista de itens está vazia")

    created_entries = []
    errors = []
    added_by = current_user.email or current_user.username

    for item in data.items:
        try:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                errors.append({"product_id": item.product_id, "error": "Produto não encontrado"})
                continue

            if item.rating and item.rating not in VALID_RATINGS:
                errors.append({"product_id": item.product_id, "error": f"Rating inválido: {item.rating}"})
                continue

            old_entries = db.query(RecommendationEntry).filter(
                RecommendationEntry.product_id == item.product_id,
                RecommendationEntry.is_active == True,
            ).all()
            for e in old_entries:
                e.is_active = False

            entry = RecommendationEntry(
                product_id=item.product_id,
                rating=item.rating,
                target_price=item.target_price,
                rationale=item.rationale,
                added_by=added_by,
                valid_from=datetime.utcnow(),
                valid_until=item.valid_until,
                is_active=True,
            )
            db.add(entry)
            db.flush()
            _sync_product_categories(db, product)
            created_entries.append(_entry_to_dict(entry))
            logger.info(f"[bulk-import] Produto '{product.name}' adicionado ao comitê por {added_by}")

        except Exception as e:
            logger.error(f"[bulk-import] Erro ao processar product_id={item.product_id}: {e}")
            errors.append({"product_id": item.product_id, "error": str(e)})
            continue

    db.commit()

    return {
        "created": len(created_entries),
        "errors": errors,
        "entries": created_entries,
        "message": (
            f"{len(created_entries)} produto(s) adicionado(s) ao Comitê com sucesso."
            if created_entries else "Nenhum produto pôde ser adicionado."
        ),
    }


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
