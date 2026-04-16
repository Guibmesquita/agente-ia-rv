"""
Endpoints para gerenciar a lista de recomendações formais do Comitê SVN.
A tabela recommendation_entries é a fonte de verdade para 'quais produtos
estão no comitê ativo hoje'.
"""
import json
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database.database import get_db
from database.models import Product, RecommendationEntry, Material, MaterialProductLink
from api.endpoints.auth import get_current_user
from database.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])
materials_router = APIRouter(prefix="/api/materials", tags=["materials"])
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

def _is_product_in_committee(db: Session, product: Product) -> bool:
    """Verifica se um produto pertence ao comitê ativo por qualquer das fontes.
    
    Respeita `excluded_from_committee` em MaterialProductLink — um produto
    explicitamente excluído não conta como membro do comitê via materiais.
    """
    now = datetime.utcnow()
    has_entry = db.query(RecommendationEntry).filter(
        RecommendationEntry.product_id == product.id,
        RecommendationEntry.is_active == True,
    ).filter(
        (RecommendationEntry.valid_until == None) |
        (RecommendationEntry.valid_until >= now)
    ).first()
    if has_entry:
        return True

    from sqlalchemy import or_
    from datetime import datetime as _dt
    _now = _dt.utcnow()
    active_mats = db.query(Material).filter(
        Material.is_committee_active == True,
        Material.publish_status == 'publicado',
        or_(
            Material.valid_until.is_(None),
            Material.valid_until >= _now,
        ),
        or_(
            Material.product_id == product.id,
            Material.id.in_(
                db.query(MaterialProductLink.material_id).filter(
                    MaterialProductLink.product_id == product.id
                )
            )
        )
    ).all()

    for mat in active_mats:
        # Verificar se o produto está explicitamente excluído neste material
        exclusion_link = db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == mat.id,
            MaterialProductLink.product_id == product.id,
            MaterialProductLink.excluded_from_committee == True,
        ).first()
        if exclusion_link is None:
            # Produto não excluído neste material → está no comitê
            return True
    return False


def _sync_product_categories(db: Session, product: Product):
    """Garante que 'Comitê' esteja (ou não) em Product.categories conforme fontes ativas."""
    in_committee = _is_product_in_committee(db, product)
    cats = product.get_categories()
    if in_committee and "Comitê" not in cats:
        cats.append("Comitê")
        product.set_categories(cats)
    elif not in_committee and "Comitê" in cats:
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
    product_id: Optional[int] = None
    rating: Optional[str] = None
    target_price: Optional[float] = None
    rationale: Optional[str] = None
    valid_until: Optional[datetime] = None
    ticker: Optional[str] = None
    nome_produto: Optional[str] = None
    auto_create: bool = False


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
    products_created = []
    errors = []
    added_by = current_user.email or current_user.username

    for item in data.items:
        savepoint = db.begin_nested()
        try:
            product = None

            if item.product_id:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if not product:
                    savepoint.rollback()
                    errors.append({"product_id": item.product_id, "error": "Produto não encontrado"})
                    continue

            elif item.auto_create and item.ticker:
                ticker_clean = item.ticker.strip().upper()

                existing = db.query(Product).filter(
                    Product.ticker.ilike(ticker_clean)
                ).first()

                if existing:
                    product = existing
                    logger.info(f"[bulk-import] Ticker {ticker_clean} já cadastrado (id={existing.id}), usando produto existente")
                else:
                    inferred_type = "FII" if ticker_clean.endswith("11") else "Ação"
                    product_name = (item.nome_produto or "").strip() or ticker_clean
                    new_product = Product(
                        name=product_name,
                        ticker=ticker_clean,
                        status="ativo",
                        category=inferred_type,
                        categories=json.dumps(["Comitê", inferred_type]),
                        created_by=current_user.id,
                    )
                    db.add(new_product)
                    db.flush()
                    product = new_product
                    products_created.append(ticker_clean)
                    logger.info(f"[bulk-import] Produto novo '{product_name}' ({ticker_clean}) criado por {added_by}")

            if not product:
                savepoint.rollback()
                errors.append({"ticker": item.ticker, "error": "Produto não encontrado e auto_create não habilitado ou ticker ausente"})
                continue

            if item.rating and item.rating not in VALID_RATINGS:
                savepoint.rollback()
                errors.append({"product_id": product.id, "error": f"Rating inválido: {item.rating}"})
                continue

            old_entries = db.query(RecommendationEntry).filter(
                RecommendationEntry.product_id == product.id,
                RecommendationEntry.is_active == True,
            ).all()
            for e in old_entries:
                e.is_active = False

            entry = RecommendationEntry(
                product_id=product.id,
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
            savepoint.commit()
            created_entries.append(_entry_to_dict(entry))
            logger.info(f"[bulk-import] Produto '{product.name}' adicionado ao comitê por {added_by}")

        except Exception as e:
            savepoint.rollback()
            pid = item.product_id or item.ticker or "?"
            logger.error(f"[bulk-import] Erro ao processar produto {pid}: {e}")
            errors.append({"product_id": item.product_id, "ticker": item.ticker, "error": str(e)})
            continue

    db.commit()

    msg_parts = []
    if created_entries:
        msg_parts.append(f"{len(created_entries)} produto(s) adicionado(s) ao Comitê com sucesso.")
    else:
        msg_parts.append("Nenhum produto pôde ser adicionado.")
    if products_created:
        msg_parts.append(f"{len(products_created)} novo(s) produto(s) criado(s) no cadastro ({', '.join(products_created)}).")

    return {
        "created": len(created_entries),
        "products_created": len(products_created),
        "products_created_tickers": products_created,
        "errors": errors,
        "entries": created_entries,
        "message": " ".join(msg_parts),
    }


# ── Materiais do Comitê Ativo ─────────────────────────────────────────────────

def _get_material_derived_products(db: Session, material: Material) -> list:
    """Retorna todos os produtos vinculados a um material (primário + junction)."""
    products = []
    seen = set()
    if material.product_id:
        p = db.query(Product).filter(Product.id == material.product_id).first()
        if p and p.id not in seen:
            products.append(p)
            seen.add(p.id)
    links = db.query(MaterialProductLink).filter(MaterialProductLink.material_id == material.id).all()
    for link in links:
        p = db.query(Product).filter(Product.id == link.product_id).first()
        if p and p.id not in seen:
            products.append(p)
            seen.add(p.id)
    return products


def _material_committee_dict(material: Material, db: Session) -> dict:
    derived = _get_material_derived_products(db, material)
    now = datetime.utcnow()
    expired = material.valid_until is not None and material.valid_until.replace(tzinfo=None) < now

    def _product_exclusion(p: Product) -> bool:
        """Retorna True se o produto está excluído do comitê neste material."""
        link = db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == material.id,
            MaterialProductLink.product_id == p.id,
            MaterialProductLink.excluded_from_committee == True,
        ).first()
        return link is not None

    return {
        "id": material.id,
        "name": material.name or "",
        "material_type": material.material_type or "",
        "publish_status": material.publish_status,
        "is_committee_active": material.is_committee_active,
        "available_for_whatsapp": material.available_for_whatsapp if material.available_for_whatsapp is not None else True,
        "valid_until": material.valid_until.isoformat() if material.valid_until else None,
        "is_expired": expired,
        "created_at": material.created_at.isoformat() if material.created_at else None,
        "updated_at": material.updated_at.isoformat() if material.updated_at else None,
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker or "",
                "manager": p.manager or "",
                "excluded_from_committee": _product_exclusion(p),
            }
            for p in derived
        ],
    }


@router.get("/committee-materials")
async def list_committee_materials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista materiais marcados como Comitê Ativo com seus produtos derivados."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    materials = db.query(Material).filter(
        Material.is_committee_active == True
    ).order_by(Material.updated_at.desc()).all()

    return [_material_committee_dict(m, db) for m in materials]


@router.get("/available-materials")
async def list_available_materials(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista materiais publicados disponíveis para ativação como Comitê."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    from database.models import ContentBlock, MaterialStatus
    from sqlalchemy import or_, case

    mats_with_content = db.query(Material.id).join(
        ContentBlock, ContentBlock.material_id == Material.id
    ).filter(ContentBlock.status.in_(['approved', 'auto_approved'])).subquery()

    query = db.query(Material).filter(
        Material.publish_status == MaterialStatus.PUBLISHED.value,
        Material.id.in_(mats_with_content),
    )

    if q:
        query = query.filter(
            or_(
                Material.name.ilike(f"%{q}%"),
            )
        )

    materials = query.order_by(
        case((Material.is_committee_active == True, 0), else_=1),
        Material.updated_at.desc()
    ).limit(50).all()

    return [_material_committee_dict(m, db) for m in materials]


async def _analyze_products_for_material(db: Session, material: Material) -> list:
    """
    Analisa os produtos de um material usando ContentBlocks indexados ou PDF como fallback.
    Retorna lista no formato do _match_products_to_db (com product_id, exists_in_db etc.).
    Faz cache do resultado em material.ai_product_analysis.
    """
    import json as _json
    import os as _os

    if material.ai_product_analysis:
        try:
            cached = _json.loads(material.ai_product_analysis)
            if isinstance(cached, list) and cached:
                logger.info(f"[COMITÊ] Usando cache ai_product_analysis para material {material.id}")
                return cached
        except Exception:
            pass

    from database.models import ContentBlock, Product, MaterialProductLink
    from api.endpoints.products import _identify_products_with_ai, _match_products_to_db

    text = ""
    blocks = db.query(ContentBlock).filter(
        ContentBlock.material_id == material.id
    ).order_by(ContentBlock.order, ContentBlock.id).all()

    if blocks:
        from services.committee_importer import _extract_text_from_blocks
        text = _extract_text_from_blocks(blocks)
        logger.info(f"[COMITÊ] Extraindo produtos de {len(blocks)} ContentBlocks ({len(text)} chars)")

    if not text.strip():
        from database.models import MaterialFile
        mat_file = db.query(MaterialFile).filter(
            MaterialFile.material_id == material.id
        ).first()
        if mat_file and mat_file.content:
            from api.endpoints.products import _extract_pdf_text_for_analysis
            text = _extract_pdf_text_for_analysis(bytes(mat_file.content))
            logger.info(f"[COMITÊ] Extraindo produtos do PDF ({len(text)} chars)")

    if not text.strip():
        logger.warning(f"[COMITÊ] Material {material.id} sem conteúdo para análise de produtos")
        return []

    ai_products = await _identify_products_with_ai(text, material.name or "")
    identified = _match_products_to_db(db, ai_products)

    material.ai_product_analysis = _json.dumps(identified, ensure_ascii=False)

    return identified


@router.post("/committee-materials/{material_id}/activate", status_code=200)
async def activate_committee_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ativa um material como Comitê Ativo e sincroniza categorias dos produtos derivados.
    Se o material não tiver vínculos de produto além do primário, analisa automaticamente
    os produtos do documento e retorna suggested_products para confirmação.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    if material.publish_status != 'publicado':
        raise HTTPException(status_code=400, detail="Somente materiais publicados podem ser ativados no Comitê")

    material.is_committee_active = True
    db.flush()

    derived = _get_material_derived_products(db, material)
    for product in derived:
        _sync_product_categories(db, product)

    db.commit()

    junction_links = db.query(MaterialProductLink).filter(
        MaterialProductLink.material_id == material_id
    ).count()
    has_links = junction_links > 0 or bool(material.product_id)

    suggested_products = []
    if not has_links:
        try:
            suggested_products = await _analyze_products_for_material(db, material)
            db.commit()
            logger.info(
                f"[COMITÊ] {len(suggested_products)} produto(s) sugerido(s) para material {material_id}"
            )
        except Exception as e:
            logger.warning(f"[COMITÊ] Falha na análise automática de produtos: {e}")

    logger.info(
        f"[COMITÊ] Material '{material.name}' (id={material.id}) ativado como Comitê Ativo "
        f"por {current_user.email} — {len(derived)} produto(s) derivado(s)"
    )
    return {
        "success": True,
        "message": f"Material ativado no Comitê com {len(derived)} produto(s) derivado(s)",
        "material": _material_committee_dict(material, db),
        "suggested_products": suggested_products,
        "has_product_links": has_links,
    }


@router.post("/committee-materials/{material_id}/link-products", status_code=200)
async def link_committee_products(
    material_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Vincula produtos confirmados a um material do Comitê Ativo.
    Body: { confirmed_products: [{product_id, name, ticker, product_type, gestora}] }
    Cria produtos novos quando necessário e gera MaterialProductLink.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    body = await request.json()
    confirmed_products = body.get("confirmed_products", [])

    import json as _json_links

    linked_ids = set()
    for cp in confirmed_products:
        pid = cp.get("product_id")

        if not pid:
            ticker = (cp.get("ticker") or "").strip().upper() or None
            name = (cp.get("name") or "").strip() or None
            if not ticker and not name:
                continue

            existing = None
            if ticker:
                existing = db.query(Product).filter(
                    Product.ticker == ticker,
                    Product.status == "ativo",
                ).first()
            if not existing and name:
                existing = db.query(Product).filter(
                    Product.name.ilike(f"%{name}%"),
                    Product.status == "ativo",
                ).first()

            if existing:
                pid = existing.id
            else:
                product_type = (cp.get("product_type") or "").strip() or None
                gestora = (cp.get("gestora") or "").strip() or None
                category_map = {
                    "FII": "fii", "FIA": "fundo_acoes", "ETF": "etf",
                    "BDR": "bdr", "Ação": "acao", "Acao": "acao",
                    "CRI": "renda_fixa", "CRA": "renda_fixa",
                    "Debênture": "renda_fixa", "Debenture": "renda_fixa",
                    "Fundo Multimercado": "multimercado",
                    "Fundo de Renda Fixa": "renda_fixa",
                }
                category = category_map.get(product_type, "") if product_type else ""
                new_p = Product(
                    name=name or ticker,
                    ticker=ticker,
                    manager=gestora,
                    categories=_json_links.dumps([category] if category else []),
                    description=f"Criado automaticamente via Comitê. Tipo: {product_type or 'não identificado'}.",
                    status="ativo",
                )
                db.add(new_p)
                db.flush()
                pid = new_p.id
                logger.info(f"[COMITÊ] Produto criado: {name or ticker} (ticker={ticker})")

        if pid:
            linked_ids.add(pid)

    if not material.product_id and linked_ids:
        material.product_id = next(iter(linked_ids))

    for pid in linked_ids:
        if pid == material.product_id:
            continue
        existing_link = db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == material_id,
            MaterialProductLink.product_id == pid,
        ).first()
        if not existing_link:
            db.add(MaterialProductLink(
                material_id=material_id,
                product_id=pid,
                excluded_from_committee=False,
            ))

    db.flush()

    all_derived = _get_material_derived_products(db, material)
    for product in all_derived:
        _sync_product_categories(db, product)

    db.commit()

    logger.info(
        f"[COMITÊ] {len(linked_ids)} produto(s) vinculado(s) ao material '{material.name}' "
        f"(id={material_id}) por {current_user.email}"
    )
    return {
        "success": True,
        "message": f"{len(linked_ids)} produto(s) vinculado(s) ao material",
        "material": _material_committee_dict(material, db),
    }


@router.post("/committee-materials/{material_id}/deactivate", status_code=200)
async def deactivate_committee_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Desativa um material do Comitê Ativo e atualiza categorias dos produtos derivados."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    material.is_committee_active = False
    db.flush()

    derived = _get_material_derived_products(db, material)
    for product in derived:
        _sync_product_categories(db, product)

    db.commit()

    logger.info(
        f"[COMITÊ] Material '{material.name}' (id={material.id}) desativado do Comitê "
        f"por {current_user.email}"
    )
    return {
        "success": True,
        "message": "Material removido do Comitê Ativo",
        "material": _material_committee_dict(material, db),
    }


@router.post("/committee-materials/{material_id}/products/{product_id}/toggle-exclusion", status_code=200)
async def toggle_product_exclusion(
    material_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Inclui ou exclui um produto específico do Comitê Ativo para o material dado.

    Se não existir um registro em material_product_links para (material_id, product_id),
    ele é criado automaticamente com excluded_from_committee=True (exclusão imediata).
    Produtos excluídos não aparecem na carteira do agente nem no summary do Comitê.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso restrito a admin e gestão RV")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verificar se o produto pertence a este material (primário ou junction)
    is_primary = material.product_id == product_id
    link = db.query(MaterialProductLink).filter(
        MaterialProductLink.material_id == material_id,
        MaterialProductLink.product_id == product_id,
    ).first()

    if not is_primary and link is None:
        raise HTTPException(status_code=400, detail="Produto não vinculado a este material")

    if link is None:
        # Produto primário sem entrada no junction — cria entrada para controle de exclusão
        from sqlalchemy.exc import IntegrityError
        link = MaterialProductLink(
            material_id=material_id,
            product_id=product_id,
            excluded_from_committee=True,
        )
        try:
            db.add(link)
            db.flush()
        except IntegrityError:
            db.rollback()
            link = db.query(MaterialProductLink).filter(
                MaterialProductLink.material_id == material_id,
                MaterialProductLink.product_id == product_id,
            ).first()
            link.excluded_from_committee = not link.excluded_from_committee
    else:
        link.excluded_from_committee = not link.excluded_from_committee

    db.flush()
    _sync_product_categories(db, product)
    db.commit()

    action = "excluído" if link.excluded_from_committee else "incluído"
    logger.info(
        f"[COMITÊ] Produto '{product.name}' (id={product_id}) {action} do Comitê "
        f"no material '{material.name}' (id={material_id}) por {current_user.email}"
    )
    return {
        "success": True,
        "excluded_from_committee": link.excluded_from_committee,
        "message": f"Produto {action} do Comitê Ativo neste material",
        "material": _material_committee_dict(material, db),
    }


@router.post("/committee-materials/{material_id}/toggle-whatsapp", status_code=200)
async def toggle_material_whatsapp(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ativa ou desativa disponibilidade do material para envio via WhatsApp pelo agente."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    current_val = material.available_for_whatsapp if material.available_for_whatsapp is not None else True
    material.available_for_whatsapp = not current_val
    db.commit()

    state = "ativado" if material.available_for_whatsapp else "desativado"
    logger.info(
        f"[WHATSAPP] Material '{material.name}' (id={material_id}) {state} para WhatsApp "
        f"por {current_user.email}"
    )
    return {
        "success": True,
        "available_for_whatsapp": material.available_for_whatsapp,
        "message": f"Material {state} para envio via WhatsApp",
    }


# ── Aliases /api/materials/... (compatibilidade de contrato) ──────────────────

@materials_router.get("/committee")
async def list_committee_materials_alias(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias para GET /api/recommendations/committee-materials."""
    return await list_committee_materials(db=db, current_user=current_user)


@materials_router.get("/committee/available")
async def list_available_materials_alias(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias para GET /api/recommendations/available-materials."""
    return await list_available_materials(q=q, db=db, current_user=current_user)


@materials_router.post("/{material_id}/committee/activate", status_code=200)
async def activate_committee_material_alias(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias para POST /api/recommendations/committee-materials/{id}/activate."""
    return await activate_committee_material(material_id=material_id, db=db, current_user=current_user)


@materials_router.post("/{material_id}/committee/deactivate", status_code=200)
async def deactivate_committee_material_alias(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias para POST /api/recommendations/committee-materials/{id}/deactivate."""
    return await deactivate_committee_material(material_id=material_id, db=db, current_user=current_user)


@materials_router.post("/{material_id}/committee/link-products", status_code=200)
async def link_committee_products_alias(
    material_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alias para POST /api/recommendations/committee-materials/{id}/link-products."""
    return await link_committee_products(material_id=material_id, request=request, db=db, current_user=current_user)


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
