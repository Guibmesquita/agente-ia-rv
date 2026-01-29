"""
Endpoints do CMS de Produtos.
Gerencia produtos, materiais, blocos de conteúdo e scripts.
"""
import json
import hashlib
import os
import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from pydantic import BaseModel

from database.database import get_db
from database.models import (
    User, Product, Material, ContentBlock, BlockVersion, 
    WhatsAppScript, PendingReviewItem,
    ProductStatus, MaterialType, ContentBlockType, 
    ContentBlockStatus, ContentSourceType
)
from api.endpoints.auth import get_current_user

router = APIRouter(prefix="/api/products", tags=["products"])

UPLOAD_DIR = "uploads/materials"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== Schemas ====================

class ProductCreate(BaseModel):
    name: str
    ticker: Optional[str] = None
    manager: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    manager: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


class MaterialCreate(BaseModel):
    material_type: str
    name: Optional[str] = None
    description: Optional[str] = None


class BlockCreate(BaseModel):
    block_type: str = "texto"
    title: Optional[str] = None
    content: str
    order: Optional[int] = 0


class BlockUpdate(BaseModel):
    title: Optional[str] = None
    content: str
    change_reason: Optional[str] = None


class ScriptCreate(BaseModel):
    title: str
    content: str
    usage_type: Optional[str] = "whatsapp"


class ScriptUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    usage_type: Optional[str] = None
    is_active: Optional[bool] = None


# ==================== Helpers ====================

def compute_hash(content: str) -> str:
    """Computa hash SHA-256 do conteúdo."""
    return hashlib.sha256(content.encode()).hexdigest()


def detect_high_risk_content(content: str) -> tuple[bool, str]:
    """
    Detecta se o conteúdo contém informações de alto risco.
    Retorna (is_high_risk, reason)
    """
    high_risk_keywords = [
        ("taxa", "Contém taxas"),
        ("custo", "Contém custos"),
        ("rentabilidade", "Contém rentabilidade"),
        ("dy", "Contém dividend yield"),
        ("dividend", "Contém dividendos"),
        ("yield", "Contém yield"),
        ("preço", "Contém preços"),
        ("price", "Contém preços"),
        ("%", "Contém percentuais"),
        ("cdi", "Contém referência a CDI"),
        ("ipca", "Contém referência a IPCA"),
        ("selic", "Contém referência a Selic"),
        ("performance", "Contém performance"),
        ("retorno", "Contém retorno"),
    ]
    
    content_lower = content.lower()
    for keyword, reason in high_risk_keywords:
        if keyword in content_lower:
            return True, reason
    
    return False, ""


# ==================== Products Endpoints ====================

@router.get("")
async def list_products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os produtos com filtros opcionais."""
    query = db.query(Product)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Product.name.ilike(search_term),
                Product.ticker.ilike(search_term),
                Product.manager.ilike(search_term)
            )
        )
    
    if category:
        query = query.filter(Product.category == category)
    
    if status:
        query = query.filter(Product.status == status)
    
    products = query.order_by(Product.name).all()
    
    result = []
    for p in products:
        materials_count = db.query(Material).filter(Material.product_id == p.id).count()
        scripts_count = db.query(WhatsAppScript).filter(WhatsAppScript.product_id == p.id).count()
        
        result.append({
            "id": p.id,
            "name": p.name,
            "ticker": p.ticker,
            "manager": p.manager,
            "category": p.category,
            "status": p.status,
            "description": p.description,
            "materials_count": materials_count,
            "scripts_count": scripts_count,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None
        })
    
    return {"products": result}


@router.get("/categories")
async def list_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista categorias únicas de produtos."""
    categories = db.query(Product.category).distinct().filter(Product.category.isnot(None)).all()
    return {"categories": [c[0] for c in categories if c[0]]}


@router.get("/expiring")
async def get_expiring_materials(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna materiais que expiram nos próximos X dias."""
    from datetime import timedelta
    
    now = datetime.now()
    expiry_threshold = now + timedelta(days=days)
    
    expiring = db.query(Material).join(Product).filter(
        Material.valid_until.isnot(None),
        Material.valid_until <= expiry_threshold,
        Material.valid_until > now
    ).all()
    
    expired = db.query(Material).join(Product).filter(
        Material.valid_until.isnot(None),
        Material.valid_until <= now
    ).all()
    
    def material_to_dict(m):
        return {
            "id": m.id,
            "name": m.name,
            "material_type": m.material_type,
            "product_name": m.product.name if m.product else None,
            "product_id": m.product_id,
            "valid_until": m.valid_until.isoformat() if m.valid_until else None,
            "days_until_expiry": (m.valid_until - now).days if m.valid_until else None
        }
    
    return {
        "expiring": [material_to_dict(m) for m in expiring],
        "expired": [material_to_dict(m) for m in expired],
        "expiring_count": len(expiring),
        "expired_count": len(expired)
    }


@router.post("")
async def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo produto."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    product = Product(
        name=data.name,
        ticker=data.ticker,
        manager=data.manager,
        category=data.category,
        description=data.description,
        created_by=current_user.id
    )
    
    db.add(product)
    db.commit()
    db.refresh(product)
    
    return {"success": True, "product_id": product.id}


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna detalhes de um produto com materiais e scripts."""
    product = db.query(Product).options(
        joinedload(Product.materials).joinedload(Material.blocks),
        joinedload(Product.scripts)
    ).filter(Product.id == product_id).first()
    
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    materials = []
    for m in product.materials:
        blocks = []
        for b in m.blocks:
            blocks.append({
                "id": b.id,
                "block_type": b.block_type,
                "title": b.title,
                "content": b.content,
                "status": b.status,
                "is_high_risk": b.is_high_risk,
                "confidence_score": b.confidence_score,
                "order": b.order,
                "current_version": b.current_version,
                "updated_at": b.updated_at.isoformat() if b.updated_at else None
            })
        
        materials.append({
            "id": m.id,
            "material_type": m.material_type,
            "name": m.name,
            "description": m.description,
            "current_version": m.current_version,
            "is_indexed": m.is_indexed,
            "blocks_count": len(blocks),
            "blocks": sorted(blocks, key=lambda x: x["order"]),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None
        })
    
    scripts = []
    for s in product.scripts:
        scripts.append({
            "id": s.id,
            "title": s.title,
            "content": s.content,
            "usage_type": s.usage_type,
            "is_active": s.is_active,
            "current_version": s.current_version,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        })
    
    return {
        "id": product.id,
        "name": product.name,
        "ticker": product.ticker,
        "manager": product.manager,
        "category": product.category,
        "status": product.status,
        "description": product.description,
        "materials": materials,
        "scripts": scripts,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None
    }


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza um produto."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    if data.name is not None:
        product.name = data.name
    if data.ticker is not None:
        product.ticker = data.ticker
    if data.manager is not None:
        product.manager = data.manager
    if data.category is not None:
        product.category = data.category
    if data.status is not None:
        product.status = data.status
    if data.description is not None:
        product.description = data.description
    
    db.commit()
    return {"success": True}


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um produto e todos seus materiais."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    db.delete(product)
    db.commit()
    return {"success": True}


# ==================== Materials Endpoints ====================

@router.post("/{product_id}/materials")
async def create_material(
    product_id: int,
    data: MaterialCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo material para o produto."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    material = Material(
        product_id=product_id,
        material_type=data.material_type,
        name=data.name,
        description=data.description,
        created_by=current_user.id
    )
    
    db.add(material)
    db.commit()
    db.refresh(material)
    
    return {"success": True, "material_id": material.id}


@router.get("/{product_id}/materials/{material_id}")
async def get_material(
    product_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna detalhes de um material com seus blocos."""
    material = db.query(Material).options(
        joinedload(Material.blocks)
    ).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    blocks = []
    for b in sorted(material.blocks, key=lambda x: x.order):
        blocks.append({
            "id": b.id,
            "block_type": b.block_type,
            "title": b.title,
            "content": b.content,
            "status": b.status,
            "is_high_risk": b.is_high_risk,
            "confidence_score": b.confidence_score,
            "source_type": b.source_type,
            "source_page": b.source_page,
            "order": b.order,
            "current_version": b.current_version,
            "semantic_tags": json.loads(b.semantic_tags) if b.semantic_tags else [],
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None
        })
    
    return {
        "id": material.id,
        "product_id": material.product_id,
        "material_type": material.material_type,
        "name": material.name,
        "description": material.description,
        "current_version": material.current_version,
        "is_indexed": material.is_indexed,
        "source_filename": material.source_filename,
        "blocks": blocks,
        "created_at": material.created_at.isoformat() if material.created_at else None,
        "updated_at": material.updated_at.isoformat() if material.updated_at else None
    }


@router.delete("/{product_id}/materials/{material_id}")
async def delete_material(
    product_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um material e todos seus blocos."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    db.delete(material)
    db.commit()
    return {"success": True}


# ==================== Content Blocks Endpoints ====================

@router.post("/{product_id}/materials/{material_id}/blocks")
async def create_block(
    product_id: int,
    material_id: int,
    data: BlockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo bloco de conteúdo."""
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    content_hash = compute_hash(data.content)
    is_high_risk, risk_reason = detect_high_risk_content(data.content)
    
    block = ContentBlock(
        material_id=material_id,
        block_type=data.block_type,
        title=data.title,
        content=data.content,
        content_hash=content_hash,
        source_type=ContentSourceType.MANUAL_INPUT.value,
        status=ContentBlockStatus.AUTO_APPROVED.value,
        is_high_risk=is_high_risk,
        order=data.order
    )
    
    db.add(block)
    db.commit()
    db.refresh(block)
    
    version = BlockVersion(
        block_id=block.id,
        version=1,
        content=data.content,
        content_hash=content_hash,
        author_id=current_user.id,
        change_reason="Criação inicial"
    )
    db.add(version)
    db.commit()
    
    return {"success": True, "block_id": block.id}


@router.put("/{product_id}/materials/{material_id}/blocks/{block_id}")
async def update_block(
    product_id: int,
    material_id: int,
    block_id: int,
    data: BlockUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza um bloco de conteúdo (cria nova versão)."""
    block = db.query(ContentBlock).filter(
        ContentBlock.id == block_id,
        ContentBlock.material_id == material_id
    ).first()
    
    if not block:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")
    
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    new_hash = compute_hash(data.content)
    if new_hash == block.content_hash:
        return {"success": True, "message": "Conteúdo não alterado"}
    
    block.current_version += 1
    block.content = data.content
    block.content_hash = new_hash
    
    if data.title is not None:
        block.title = data.title
    
    is_high_risk, risk_reason = detect_high_risk_content(data.content)
    block.is_high_risk = is_high_risk
    block.status = ContentBlockStatus.AUTO_APPROVED.value
    
    version = BlockVersion(
        block_id=block.id,
        version=block.current_version,
        content=data.content,
        content_hash=new_hash,
        author_id=current_user.id,
        change_reason=data.change_reason or "Atualização"
    )
    db.add(version)
    db.commit()
    
    return {"success": True, "new_version": block.current_version}


@router.get("/{product_id}/materials/{material_id}/blocks/{block_id}/versions")
async def get_block_versions(
    product_id: int,
    material_id: int,
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista histórico de versões de um bloco."""
    block = db.query(ContentBlock).options(
        joinedload(ContentBlock.versions).joinedload(BlockVersion.author)
    ).filter(
        ContentBlock.id == block_id,
        ContentBlock.material_id == material_id
    ).first()
    
    if not block:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")
    
    versions = []
    for v in sorted(block.versions, key=lambda x: x.version, reverse=True):
        versions.append({
            "id": v.id,
            "version": v.version,
            "content": v.content,
            "author": v.author.username if v.author else None,
            "change_reason": v.change_reason,
            "created_at": v.created_at.isoformat() if v.created_at else None
        })
    
    return {"versions": versions}


@router.post("/{product_id}/materials/{material_id}/blocks/{block_id}/restore/{version}")
async def restore_block_version(
    product_id: int,
    material_id: int,
    block_id: int,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Restaura uma versão anterior do bloco."""
    block = db.query(ContentBlock).filter(
        ContentBlock.id == block_id,
        ContentBlock.material_id == material_id
    ).first()
    
    if not block:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")
    
    old_version = db.query(BlockVersion).filter(
        BlockVersion.block_id == block_id,
        BlockVersion.version == version
    ).first()
    
    if not old_version:
        raise HTTPException(status_code=404, detail="Versão não encontrada")
    
    block.current_version += 1
    block.content = old_version.content
    block.content_hash = old_version.content_hash
    
    new_version = BlockVersion(
        block_id=block.id,
        version=block.current_version,
        content=old_version.content,
        content_hash=old_version.content_hash,
        author_id=current_user.id,
        change_reason=f"Restaurado da versão {version}"
    )
    db.add(new_version)
    db.commit()
    
    return {"success": True, "new_version": block.current_version}


@router.delete("/{product_id}/materials/{material_id}/blocks/{block_id}")
async def delete_block(
    product_id: int,
    material_id: int,
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um bloco de conteúdo."""
    block = db.query(ContentBlock).filter(
        ContentBlock.id == block_id,
        ContentBlock.material_id == material_id
    ).first()
    
    if not block:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")
    
    db.delete(block)
    db.commit()
    return {"success": True}


@router.post("/blocks/{block_id}/approve")
async def approve_block(
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova manualmente um bloco pendente de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    block = db.query(ContentBlock).filter(ContentBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")
    
    if block.status != ContentBlockStatus.PENDING_REVIEW.value:
        raise HTTPException(status_code=400, detail="Bloco não está pendente de revisão")
    
    block.status = ContentBlockStatus.APPROVED.value
    
    review_item = db.query(PendingReviewItem).filter(
        PendingReviewItem.block_id == block_id,
        PendingReviewItem.reviewed_at.is_(None)
    ).first()
    
    if review_item:
        review_item.reviewed_by = current_user.id
        review_item.reviewed_at = datetime.utcnow()
        review_item.review_action = "approved"
    
    db.commit()
    
    material = db.query(Material).filter(Material.id == block.material_id).first()
    if material:
        product = db.query(Product).filter(Product.id == material.product_id).first()
        if product:
            from services.product_ingestor import get_product_ingestor
            ingestor = get_product_ingestor()
            ingestor.index_approved_blocks(
                material_id=material.id,
                product_name=product.name,
                product_ticker=product.ticker,
                db=db
            )
    
    return {"success": True, "status": block.status}


# ==================== Scripts Endpoints ====================

@router.post("/{product_id}/scripts")
async def create_script(
    product_id: int,
    data: ScriptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cria um novo script de WhatsApp."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    script = WhatsAppScript(
        product_id=product_id,
        title=data.title,
        content=data.content,
        usage_type=data.usage_type,
        created_by=current_user.id
    )
    
    db.add(script)
    db.commit()
    db.refresh(script)
    
    return {"success": True, "script_id": script.id}


@router.put("/{product_id}/scripts/{script_id}")
async def update_script(
    product_id: int,
    script_id: int,
    data: ScriptUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza um script de WhatsApp."""
    script = db.query(WhatsAppScript).filter(
        WhatsAppScript.id == script_id,
        WhatsAppScript.product_id == product_id
    ).first()
    
    if not script:
        raise HTTPException(status_code=404, detail="Script não encontrado")
    
    if data.title is not None:
        script.title = data.title
    if data.content is not None:
        script.content = data.content
        script.current_version += 1
    if data.usage_type is not None:
        script.usage_type = data.usage_type
    if data.is_active is not None:
        script.is_active = data.is_active
    
    db.commit()
    return {"success": True}


@router.delete("/{product_id}/scripts/{script_id}")
async def delete_script(
    product_id: int,
    script_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um script de WhatsApp."""
    script = db.query(WhatsAppScript).filter(
        WhatsAppScript.id == script_id,
        WhatsAppScript.product_id == product_id
    ).first()
    
    if not script:
        raise HTTPException(status_code=404, detail="Script não encontrado")
    
    db.delete(script)
    db.commit()
    return {"success": True}


# ==================== Pending Review Endpoints ====================

@router.get("/review/pending")
async def list_pending_reviews(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista itens pendentes de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    pending = db.query(PendingReviewItem).options(
        joinedload(PendingReviewItem.block).joinedload(ContentBlock.material).joinedload(Material.product)
    ).filter(
        PendingReviewItem.reviewed_at.is_(None)
    ).order_by(PendingReviewItem.created_at).all()
    
    items = []
    for p in pending:
        items.append({
            "id": p.id,
            "block_id": p.block_id,
            "product_name": p.block.material.product.name if p.block and p.block.material and p.block.material.product else None,
            "material_name": p.block.material.name if p.block and p.block.material else None,
            "block_title": p.block.title if p.block else None,
            "block_type": p.block.block_type if p.block else None,
            "original_content": p.original_content,
            "extracted_content": p.extracted_content,
            "confidence_score": p.confidence_score,
            "risk_reason": p.risk_reason,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    
    return {"pending_items": items, "total": len(items)}


@router.post("/review/{item_id}/approve")
async def approve_review_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova um item pendente de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    item.reviewed_by = current_user.id
    item.reviewed_at = datetime.utcnow()
    item.review_action = "approved"
    
    block = db.query(ContentBlock).filter(ContentBlock.id == item.block_id).first()
    if block:
        block.status = ContentBlockStatus.APPROVED.value
    
    db.commit()
    return {"success": True}


@router.post("/review/{item_id}/edit")
async def edit_review_item(
    item_id: int,
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Edita e aprova um item pendente de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    block = db.query(ContentBlock).filter(ContentBlock.id == item.block_id).first()
    if block:
        block.content = content
        block.content_hash = compute_hash(content)
        block.current_version += 1
        block.status = ContentBlockStatus.APPROVED.value
        
        version = BlockVersion(
            block_id=block.id,
            version=block.current_version,
            content=content,
            content_hash=block.content_hash,
            author_id=current_user.id,
            change_reason="Corrigido na revisão"
        )
        db.add(version)
    
    item.reviewed_by = current_user.id
    item.reviewed_at = datetime.utcnow()
    item.review_action = "edited"
    
    db.commit()
    return {"success": True}


@router.post("/review/{item_id}/reject")
async def reject_review_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Rejeita um item pendente de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    item.reviewed_by = current_user.id
    item.reviewed_at = datetime.utcnow()
    item.review_action = "rejected"
    
    block = db.query(ContentBlock).filter(ContentBlock.id == item.block_id).first()
    if block:
        block.status = ContentBlockStatus.REJECTED.value
    
    db.commit()
    return {"success": True}


# ==================== PDF Upload Endpoints ====================

async def process_pdf_background(
    material_id: int,
    product_id: int,
    file_path: str,
    document_title: str,
    user_id: int
):
    """Processa PDF em background e cria blocos de conteúdo."""
    from database.database import SessionLocal
    from services.product_ingestor import get_product_ingestor
    
    db = SessionLocal()
    try:
        ingestor = get_product_ingestor()
        
        result = ingestor.process_pdf_to_blocks(
            pdf_path=file_path,
            material_id=material_id,
            document_title=document_title,
            db=db,
            user_id=user_id
        )
        
        if result.get("success"):
            product = db.query(Product).filter(Product.id == product_id).first()
            if product:
                ingestor.index_approved_blocks(
                    material_id=material_id,
                    product_name=product.name,
                    product_ticker=product.ticker,
                    db=db
                )
        
        print(f"[PDF_UPLOAD] Processamento concluído: {result}")
        
    except Exception as e:
        print(f"[PDF_UPLOAD] Erro no processamento: {e}")
    finally:
        db.close()


@router.post("/{product_id}/materials/{material_id}/upload")
async def upload_pdf_to_material(
    product_id: int,
    material_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Faz upload de um PDF para um material.
    O PDF é processado com GPT-4 Vision e convertido em blocos de conteúdo.
    Implementa sistema de Lanes (Fast Lane / High-Risk Lane).
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são suportados")
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    document_title = f"{product.name} - {material.name or material.material_type}"
    
    background_tasks.add_task(
        process_pdf_background,
        material_id=material_id,
        product_id=product_id,
        file_path=file_path,
        document_title=document_title,
        user_id=current_user.id
    )
    
    return {
        "success": True,
        "message": "PDF enviado para processamento. Os blocos serão criados em alguns instantes."
    }


@router.post("/materials/{material_id}/publish")
async def publish_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Publica um material e indexa seus blocos aprovados no vector store."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    product = db.query(Product).filter(Product.id == material.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    from datetime import datetime
    material.publish_status = "publicado"
    material.published_at = datetime.now()
    db.commit()
    
    from services.product_ingestor import get_product_ingestor
    ingestor = get_product_ingestor()
    
    result = ingestor.index_approved_blocks(
        material_id=material_id,
        product_name=product.name,
        product_ticker=product.ticker,
        db=db
    )
    
    return {
        "success": True,
        "message": "Material publicado e indexado",
        "indexed_count": result.get("indexed_count", 0)
    }


@router.post("/{product_id}/materials/{material_id}/reindex")
async def reindex_material(
    product_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reindexa todos os blocos aprovados de um material no vector store."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()
    
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    from services.product_ingestor import get_product_ingestor
    ingestor = get_product_ingestor()
    
    result = ingestor.reindex_material(
        material_id=material_id,
        product_name=product.name,
        product_ticker=product.ticker,
        db=db
    )
    
    if result.get("success"):
        return {"success": True, "indexed_count": result.get("indexed_count", 0)}
    else:
        raise HTTPException(status_code=500, detail=result.get("error", "Erro ao reindexar"))
