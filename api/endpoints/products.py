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

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
import asyncio
import queue
import threading
from sqlalchemy import or_
from pydantic import BaseModel

from database.database import get_db
from database.models import (
    User, Product, Material, ContentBlock, BlockVersion, 
    WhatsAppScript, PendingReviewItem, DocumentProcessingJob,
    ProductStatus, MaterialType, ContentBlockType, 
    ContentBlockStatus, ContentSourceType, PersistentQueueItem
)
from api.endpoints.auth import get_current_user
from services.vector_store import VectorStore
from services.semantic_transformer import transform_content_for_display, transform_semantic_to_indexable, parse_table_to_semantic

router = APIRouter(prefix="/api/products", tags=["products"])

# Queue para rastrear progresso de uploads
upload_progress_queues = {}

def reindex_block(block: ContentBlock, db: Session):
    """
    Reindexa um bloco de conteúdo no vetor de busca.
    
    MELHORIA: Agora inclui contexto global completo em cada chunk para melhor RAG.
    """
    try:
        vector_store = VectorStore()
        chunk_id = f"product_block_{block.id}"
        
        vector_store.delete_document(chunk_id)
        
        material = block.material
        product = material.product if material else None
        
        content_for_indexing = block.content
        if block.block_type == ContentBlockType.TABLE.value:
            try:
                table_data = json.loads(block.content)
                semantic_model = parse_table_to_semantic(table_data)
                content_for_indexing = transform_semantic_to_indexable(
                    semantic_model, 
                    block.title or ""
                )
            except Exception:
                pass
        
        global_context = _build_global_context_for_block(material, product)
        content_with_context = f"{global_context}\n\n{content_for_indexing}"
        
        material_tags = []
        material_categories = []
        if material:
            try:
                material_tags = json.loads(material.tags or "[]")
            except:
                pass
            try:
                material_categories = json.loads(material.material_categories or "[]")
            except:
                pass
        
        valid_until_str = ""
        created_at_str = ""
        if material:
            if material.valid_until:
                valid_until_str = material.valid_until.isoformat()
            if material.created_at:
                created_at_str = material.created_at.isoformat()
        
        metadata = {
            "block_id": str(block.id),
            "material_id": str(material.id) if material else "",
            "material_name": material.name if material else "",
            "material_type": material.material_type if material else "",
            "product_id": str(product.id) if product else "",
            "product_name": product.name if product else "",
            "product_ticker": product.ticker if product else "",
            "gestora": product.manager if product else "",
            "category": product.category if product else "",
            "products": (product.ticker.upper() if product and product.ticker else (product.name.upper() if product else "")),
            "block_type": block.block_type,
            "title": block.title or "",
            "page": str(block.source_page or 0),
            "publish_status": material.publish_status if material else "rascunho",
            "valid_until": valid_until_str,
            "created_at": created_at_str,
            "tags": ",".join(material_tags),
            "categories": ",".join(material_categories),
            "source": "product_cms"
        }
        
        vector_store.add_document(
            doc_id=chunk_id,
            text=content_with_context,
            metadata=metadata
        )
        print(f"[REINDEX] Bloco {block.id} reindexado com sucesso")
        return True
    except Exception as e:
        print(f"[REINDEX] Erro ao reindexar bloco {block.id}: {e}")
        return False


def _build_global_context_for_block(material, product) -> str:
    """
    Constrói o contexto global que será prefixado em todos os chunks.
    Isso melhora significativamente a qualidade do RAG (+15-25%).
    """
    parts = ["[CONTEXTO GLOBAL]"]
    
    if product:
        ticker_info = f" ({product.ticker})" if product.ticker else ""
        parts.append(f"Produto: {product.name}{ticker_info}")
        
        if product.manager:
            parts.append(f"Gestora: {product.manager}")
        
        if product.category:
            parts.append(f"Categoria: {product.category}")
    
    if material:
        if material.name:
            parts.append(f"Documento: {material.name}")
        
        type_labels = {
            "one_page": "one page",
            "relatorio_gerencial": "relatório gerencial",
            "material_publicitario": "material publicitário",
            "atualizacao_taxas": "atualização de taxas",
            "argumentos_comerciais": "argumentos comerciais",
            "apresentacao": "apresentação",
            "prospecto": "prospecto",
            "regulamento": "regulamento",
            "fato_relevante": "fato relevante"
        }
        type_label = type_labels.get(material.material_type, material.material_type or "")
        if type_label:
            parts.append(f"Tipo: {type_label}")
        
        if material.created_at:
            parts.append(f"Data: {material.created_at.strftime('%Y-%m-%d')}")
        
        if material.ai_summary:
            parts.append(f"Resumo: {material.ai_summary}")
        
        all_themes = []
        try:
            ai_themes = json.loads(material.ai_themes or "[]")
            all_themes.extend(ai_themes)
        except:
            pass
        try:
            tags = json.loads(material.tags or "[]")
            all_themes.extend(tags)
        except:
            pass
        try:
            cats = json.loads(material.material_categories or "[]")
            all_themes.extend(cats)
        except:
            pass
        
        unique_themes = list(dict.fromkeys(all_themes))
        if unique_themes:
            parts.append(f"Temas: {', '.join(unique_themes)}")
    
    return "\n".join(parts)

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
    
    query = query.filter(Product.ticker != "__SYSTEM_UNASSIGNED__")
    
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
        blocks_count = db.query(ContentBlock).join(Material).filter(Material.product_id == p.id).count()
        
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
            "blocks_count": blocks_count,
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


class BulkApproveRequest(BaseModel):
    block_ids: List[int]


@router.post("/blocks/bulk-approve")
async def bulk_approve_blocks(
    request: BulkApproveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova múltiplos blocos pendentes de revisão em massa."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    if not request.block_ids:
        raise HTTPException(status_code=400, detail="Nenhum bloco selecionado")
    
    approved_count = 0
    errors = []
    indexed_materials = set()
    
    for block_id in request.block_ids:
        block = db.query(ContentBlock).filter(ContentBlock.id == block_id).first()
        if not block:
            errors.append(f"Bloco {block_id} não encontrado")
            continue
        
        if block.status != ContentBlockStatus.PENDING_REVIEW.value:
            errors.append(f"Bloco {block_id} não está pendente de revisão")
            continue
        
        block.status = ContentBlockStatus.APPROVED.value
        
        review_item = db.query(PendingReviewItem).filter(
            PendingReviewItem.block_id == block_id,
            PendingReviewItem.reviewed_at.is_(None)
        ).first()
        
        if review_item:
            review_item.reviewed_by = current_user.id
            review_item.reviewed_at = datetime.utcnow()
            review_item.review_action = "approved"
        
        indexed_materials.add(block.material_id)
        approved_count += 1
    
    db.commit()
    
    for material_id in indexed_materials:
        material = db.query(Material).filter(Material.id == material_id).first()
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
    
    return {
        "success": True,
        "approved_count": approved_count,
        "errors": errors if errors else None
    }


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
        material = p.block.material if p.block else None
        block_type = p.block.block_type if p.block else None
        
        display_content = p.extracted_content
        semantic_model = None
        
        if block_type == ContentBlockType.TABLE.value and p.extracted_content:
            try:
                display_content, semantic_model = transform_content_for_display(
                    p.extracted_content, block_type
                )
            except Exception:
                pass
        
        items.append({
            "id": p.id,
            "block_id": p.block_id,
            "product_name": material.product.name if material and material.product else None,
            "material_name": material.name if material else None,
            "material_id": material.id if material else None,
            "source_page": p.block.source_page if p.block else None,
            "block_title": p.block.title if p.block else None,
            "block_type": block_type,
            "original_content": p.original_content,
            "extracted_content": p.extracted_content,
            "display_content": display_content,
            "semantic_model": semantic_model,
            "confidence_score": p.confidence_score,
            "risk_reason": p.risk_reason,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })
    
    return {"pending_items": items, "total": len(items)}


@router.post("/review/{item_id}/approve")
async def approve_review_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova um item pendente de revisão e reindexa no vetor de busca."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).options(
        joinedload(PendingReviewItem.block).joinedload(ContentBlock.material).joinedload(Material.product)
    ).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    item.reviewed_by = current_user.id
    item.reviewed_at = datetime.utcnow()
    item.review_action = "approved"
    
    block = item.block
    if block:
        block.status = ContentBlockStatus.APPROVED.value
        db.commit()
        reindex_block(block, db)
    else:
        db.commit()
    
    return {"success": True}


class EditReviewContent(BaseModel):
    content: str


@router.post("/review/{item_id}/edit")
async def edit_review_item(
    item_id: int,
    data: EditReviewContent,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Edita o conteúdo de um item pendente de revisão."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    block = db.query(ContentBlock).filter(ContentBlock.id == item.block_id).first()
    if block:
        block.content = data.content
        block.content_hash = compute_hash(data.content)
        block.current_version += 1
        
        version = BlockVersion(
            block_id=block.id,
            version=block.current_version,
            content=data.content,
            content_hash=block.content_hash,
            author_id=current_user.id,
            change_reason="Corrigido na revisão"
        )
        db.add(version)
    
    item.extracted_content = data.content
    
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


@router.post("/review/{item_id}/reprocess")
async def reprocess_review_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reprocessa a extração de uma página específica.
    Útil quando a extração original não capturou todos os dados da tabela.
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    item = db.query(PendingReviewItem).filter(PendingReviewItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    
    block = db.query(ContentBlock).options(
        joinedload(ContentBlock.material)
    ).filter(ContentBlock.id == item.block_id).first()
    
    if not block or not block.material:
        raise HTTPException(status_code=404, detail="Bloco ou material não encontrado")
    
    material = block.material
    if not material.file_path:
        raise HTTPException(status_code=400, detail="Material não possui arquivo PDF associado")
    
    page_num = int(block.source_page) if block.source_page else 1
    
    background_tasks.add_task(
        reprocess_single_page,
        material_id=material.id,
        page_num=page_num,
        block_id=block.id,
        pending_item_id=item.id,
        file_path=material.file_path,
        user_id=current_user.id
    )
    
    return {
        "success": True,
        "message": f"Reprocessamento da página {page_num} iniciado em background"
    }


async def reprocess_single_page(
    material_id: int,
    page_num: int,
    block_id: int,
    pending_item_id: int,
    file_path: str,
    user_id: int
):
    """Reprocessa uma única página do PDF com o prompt melhorado."""
    from database.database import SessionLocal
    from services.document_processor import DocumentProcessor
    from pdf2image import convert_from_path
    import json
    
    db = SessionLocal()
    try:
        processor = DocumentProcessor()
        
        images = convert_from_path(file_path, dpi=150, first_page=page_num, last_page=page_num)
        if not images:
            print(f"[REPROCESS] Erro: não foi possível converter página {page_num}")
            return
        
        image = images[0]
        
        result = processor.analyze_page(image, f"Reprocessamento - Página {page_num}")
        
        tables = result.get("raw_data", {}).get("tables", [])
        if not tables:
            print(f"[REPROCESS] Nenhuma tabela encontrada na página {page_num}")
            return
        
        all_rows = []
        headers = tables[0].get("headers", [])
        for table in tables:
            table_headers = table.get("headers", [])
            if table_headers == headers:
                all_rows.extend(table.get("rows", []))
            else:
                all_rows.extend(table.get("rows", []))
        
        merged_table = {
            "headers": headers,
            "rows": all_rows
        }
        table_json = json.dumps(merged_table, ensure_ascii=False)
        
        block = db.query(ContentBlock).filter(ContentBlock.id == block_id).first()
        if block:
            old_rows = 0
            try:
                old_data = json.loads(block.content)
                old_rows = len(old_data.get("rows", []))
            except:
                pass
            
            new_rows = len(all_rows)
            
            block.content = table_json
            
            pending_item = db.query(PendingReviewItem).filter(PendingReviewItem.id == pending_item_id).first()
            if pending_item:
                pending_item.extracted_content = table_json
                pending_item.original_content = table_json
                pending_item.risk_reason = f"Reprocessado: {old_rows} → {new_rows} linhas"
            
            db.commit()
            
            try:
                reindex_block(block, db)
                print(f"[REPROCESS] Bloco reindexado no vetor de busca")
            except Exception as idx_err:
                print(f"[REPROCESS] Erro ao reindexar: {idx_err}")
            
            print(f"[REPROCESS] Página {page_num} reprocessada: {old_rows} → {new_rows} linhas")
        
    except Exception as e:
        print(f"[REPROCESS] Erro: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


# ==================== PDF Upload Endpoints ====================

async def process_pdf_with_auto_product_detection(
    material_id: int,
    file_path: str,
    document_title: str,
    user_id: int
):
    """
    Processa PDF em background com detecção automática de produtos.
    A IA identifica tickers e nomes de produtos em cada página e vincula automaticamente.
    """
    from database.database import SessionLocal
    from services.product_ingestor import get_product_ingestor
    
    db = SessionLocal()
    try:
        ingestor = get_product_ingestor()
        
        result = ingestor.process_pdf_with_product_detection(
            pdf_path=file_path,
            material_id=material_id,
            document_title=document_title,
            db=db,
            user_id=user_id
        )
        
        print(f"[SMART_UPLOAD] Processamento concluído: {result}")
        
    except Exception as e:
        print(f"[SMART_UPLOAD] Erro no processamento: {e}")
    finally:
        db.close()


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


@router.get("/materials/{material_id}/pdf")
async def get_material_pdf(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna o arquivo PDF de um material."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    if not material.source_file_path:
        raise HTTPException(status_code=404, detail="PDF não disponível")
    
    import os
    
    ALLOWED_UPLOAD_DIR = os.path.abspath("uploads/materials")
    file_path = os.path.abspath(material.source_file_path)
    
    if not file_path.startswith(ALLOWED_UPLOAD_DIR):
        raise HTTPException(status_code=403, detail="Acesso ao arquivo negado")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    
    from fastapi.responses import FileResponse
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=material.name + ".pdf",
        headers={"Content-Disposition": "inline"}
    )


@router.get("/materials/all")
async def list_all_materials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os materiais do sistema."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    materials = db.query(Material).options(
        joinedload(Material.product)
    ).order_by(Material.created_at.desc()).all()
    
    result = []
    for m in materials:
        blocks_count = db.query(ContentBlock).filter(ContentBlock.material_id == m.id).count()
        result.append({
            "id": m.id,
            "name": m.name,
            "material_type": m.material_type,
            "product_id": m.product_id,
            "product_name": m.product.name if m.product else None,
            "product_ticker": m.product.ticker if m.product else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "valid_from": m.valid_from.isoformat() if m.valid_from else None,
            "valid_until": m.valid_until.isoformat() if m.valid_until else None,
            "indexed": blocks_count > 0,
            "blocks_count": blocks_count
        })
    
    return {"materials": result, "total": len(result)}


@router.get("/materials/pending")
async def list_pending_materials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista materiais com processamento pendente, em andamento ou com erro."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    active_queue_material_ids = db.query(PersistentQueueItem.material_id).filter(
        PersistentQueueItem.status.in_(['queued', 'processing'])
    ).subquery()
    
    pending_materials = db.query(Material).filter(
        Material.processing_status.in_(['processing', 'pending', 'failed']),
        ~Material.id.in_(active_queue_material_ids)
    ).options(
        joinedload(Material.product)
    ).order_by(Material.created_at.desc()).all()
    
    result = []
    for m in pending_materials:
        blocks_count = db.query(ContentBlock).filter(ContentBlock.material_id == m.id).count()
        
        job = db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.material_id == m.id
        ).order_by(DocumentProcessingJob.created_at.desc()).first()
        
        result.append({
            "id": m.id,
            "name": m.name,
            "source_filename": m.source_filename,
            "product_id": m.product_id,
            "product_name": m.product.name if m.product else None,
            "product_ticker": m.product.ticker if m.product else None,
            "processing_status": m.processing_status,
            "processing_error": m.processing_error,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "blocks_count": blocks_count,
            "job_info": {
                "total_pages": job.total_pages if job else None,
                "processed_pages": job.processed_pages if job else None,
                "status": job.status if job else None
            } if job else None,
            "can_resume": m.processing_status in ['processing', 'failed'] and (
                (m.source_file_path and os.path.exists(m.source_file_path)) or
                (job and job.file_path and os.path.exists(job.file_path))
            )
        })
    
    return {"pending_materials": result, "total": len(result)}


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


@router.post("/smart-upload")
async def smart_upload_without_product(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    material_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(None),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload inteligente sem produto vinculado.
    A IA processará o PDF e identificará automaticamente os produtos mencionados em cada página.
    Os blocos serão criados e vinculados aos produtos identificados.
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são suportados")
    
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Nome do material é obrigatório")
    
    placeholder_product = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
    if not placeholder_product:
        raise HTTPException(
            status_code=500, 
            detail="Produto de sistema não encontrado. Execute o seed do banco de dados."
        )
    
    from datetime import datetime
    
    parsed_valid_from = None
    parsed_valid_until = None
    
    if valid_from:
        try:
            parsed_valid_from = datetime.fromisoformat(valid_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    if valid_until:
        try:
            parsed_valid_until = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    material = Material(
        product_id=placeholder_product.id,
        material_type=material_type,
        name=name,
        description=description,
        valid_from=parsed_valid_from,
        valid_until=parsed_valid_until,
        publish_status="rascunho"
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    document_title = name or file.filename.replace('.pdf', '')
    
    background_tasks.add_task(
        process_pdf_with_auto_product_detection,
        material_id=material.id,
        file_path=file_path,
        document_title=document_title,
        user_id=current_user.id
    )
    
    return {
        "success": True,
        "message": "PDF enviado para processamento inteligente. A IA identificará os produtos automaticamente.",
        "material": {
            "id": material.id,
            "name": material.name
        },
        "product_id": placeholder_product.id
    }


@router.post("/smart-upload-stream")
async def smart_upload_stream(
    request: Request,
    file: UploadFile = File(...),
    material_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(None),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
    material_categories: str = Form("[]"),
    tags: str = Form("[]"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload inteligente com SSE para acompanhamento em tempo real.
    Retorna um stream de eventos com o progresso do processamento.
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    # Extrair user_id antes de entrar em thread (evita erro de sessão desvinculada)
    user_id = current_user.id
    
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são suportados")
    
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Nome do material é obrigatório")
    
    placeholder_product = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
    if not placeholder_product:
        raise HTTPException(status_code=500, detail="Produto de sistema não encontrado")
    
    from datetime import datetime as dt
    
    parsed_valid_from = None
    parsed_valid_until = None
    
    if valid_from:
        try:
            parsed_valid_from = dt.fromisoformat(valid_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    if valid_until:
        try:
            parsed_valid_until = dt.fromisoformat(valid_until.replace('Z', '+00:00'))
        except ValueError:
            pass
    
    import json as json_lib
    
    parsed_tags = []
    parsed_categories = []
    try:
        parsed_tags = json_lib.loads(tags) if tags else []
    except:
        parsed_tags = []
    try:
        parsed_categories = json_lib.loads(material_categories) if material_categories else []
    except:
        parsed_categories = []
    
    material = Material(
        product_id=placeholder_product.id,
        material_type=material_type,
        name=name,
        description=description,
        valid_from=parsed_valid_from,
        valid_until=parsed_valid_until,
        tags=json_lib.dumps(parsed_tags),
        material_categories=json_lib.dumps(parsed_categories),
        publish_status="rascunho"
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    upload_id = str(uuid.uuid4())
    progress_queue = queue.Queue()
    upload_progress_queues[upload_id] = progress_queue
    
    def process_with_progress():
        from database.database import SessionLocal
        from services.product_ingestor import get_product_ingestor
        from services.document_metadata_extractor import get_metadata_extractor
        from database.models import (
            ProcessingStatus, DocumentProcessingJob, DocumentPageResult,
            ProcessingJobStatus, PageProcessingStatus
        )
        from services.document_processor import get_document_processor
        import json as json_module
        from datetime import datetime
        import hashlib
        
        db_local = SessionLocal()
        material_id_local = material.id
        processing_success = False
        processing_job = None
        
        try:
            progress_queue.put({
                "type": "start",
                "message": "Iniciando processamento do documento...",
                "material_id": material_id_local
            })
            
            mat = db_local.query(Material).filter(Material.id == material_id_local).first()
            if mat:
                mat.processing_status = ProcessingStatus.PROCESSING.value
                db_local.commit()
            
            with open(file_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            
            doc_processor = get_document_processor()
            total_pages = doc_processor.get_pdf_page_count(file_path)
            
            processing_job = DocumentProcessingJob(
                material_id=material_id_local,
                file_path=file_path,
                file_hash=file_hash,
                total_pages=total_pages,
                status=ProcessingJobStatus.PROCESSING.value,
                started_at=datetime.utcnow()
            )
            db_local.add(processing_job)
            db_local.commit()
            db_local.refresh(processing_job)
            
            for page_num in range(1, total_pages + 1):
                page_result = DocumentPageResult(
                    job_id=processing_job.id,
                    page_number=page_num,
                    status=PageProcessingStatus.PENDING.value
                )
                db_local.add(page_result)
            db_local.commit()
            
            progress_queue.put({
                "type": "log",
                "message": "Extraindo metadados do documento (analisando primeiras páginas)...",
                "log_type": "info"
            })
            
            try:
                extractor = get_metadata_extractor()
                existing_products = db_local.query(Product).filter(
                    (Product.ticker != "__SYSTEM_UNASSIGNED__") | (Product.ticker == None)
                ).all()
                existing_products_list = [{"id": p.id, "name": p.name, "ticker": p.ticker} for p in existing_products]
                
                metadata = extractor.extract_metadata(
                    pdf_path=file_path,
                    pages_to_analyze=[0, 1, 2],
                    existing_products=existing_products_list
                )
                
                if mat:
                    mat.extracted_metadata = json_module.dumps(metadata.to_dict(), ensure_ascii=False)
                    db_local.commit()
                
                progress_queue.put({
                    "type": "metadata",
                    "message": f"Metadados extraídos: {metadata.fund_name or 'N/A'} | Ticker: {metadata.ticker or 'N/A'} | Gestora: {metadata.gestora or 'N/A'}",
                    "log_type": "info",
                    "data": metadata.to_dict()
                })
                
                if metadata.confidence >= 0.5 and (metadata.ticker or metadata.fund_name):
                    matched_product = None
                    
                    if metadata.ticker:
                        matched_product = db_local.query(Product).filter(
                            Product.ticker == metadata.ticker
                        ).first()
                    
                    if not matched_product and metadata.fund_name:
                        from services.document_metadata_extractor import normalize_text
                        fund_normalized = normalize_text(metadata.fund_name)
                        for prod in existing_products:
                            if normalize_text(prod.name) in fund_normalized or fund_normalized in normalize_text(prod.name):
                                matched_product = prod
                                break
                    
                    if matched_product and matched_product.ticker != "__SYSTEM_UNASSIGNED__":
                        if mat:
                            mat.product_id = matched_product.id
                            db_local.commit()
                        progress_queue.put({
                            "type": "log",
                            "message": f"Produto identificado automaticamente: {matched_product.name} ({matched_product.ticker})",
                            "log_type": "success"
                        })
                    elif metadata.fund_name and metadata.confidence >= 0.8:
                        new_product = Product(
                            name=metadata.fund_name,
                            ticker=metadata.ticker,
                            category=metadata.gestora or "FII",
                            manager=metadata.gestora,
                            status="ativo"
                        )
                        db_local.add(new_product)
                        db_local.commit()
                        db_local.refresh(new_product)
                        
                        if mat:
                            mat.product_id = new_product.id
                            db_local.commit()
                        
                        ticker_info = f"({metadata.ticker})" if metadata.ticker else "(ticker a definir)"
                        progress_queue.put({
                            "type": "log",
                            "message": f"Novo produto criado: {new_product.name} {ticker_info}",
                            "log_type": "success"
                        })
                
            except Exception as meta_err:
                progress_queue.put({
                    "type": "log",
                    "message": f"Aviso: Extração de metadados falhou ({str(meta_err)[:100]}), continuando...",
                    "log_type": "warning"
                })
            
            ingestor = get_product_ingestor()
            
            def progress_callback(current, total):
                progress_queue.put({
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "percent": int((current / total) * 100) if total > 0 else 0,
                    "message": f"Processando página {current}/{total}"
                })
            
            result = ingestor.process_pdf_with_product_detection_streaming(
                pdf_path=file_path,
                material_id=material_id_local,
                document_title=name or file.filename.replace('.pdf', ''),
                db=db_local,
                user_id=user_id,
                progress_callback=progress_callback,
                log_callback=lambda msg, t: progress_queue.put({"type": "log", "message": msg, "log_type": t})
            )
            
            mat = db_local.query(Material).filter(Material.id == material_id_local).first()
            if mat:
                mat.processing_status = ProcessingStatus.SUCCESS.value
                db_local.commit()
                
                placeholder = db_local.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
                if mat.product_id == placeholder.id:
                    first_block = db_local.query(ContentBlock).filter(
                        ContentBlock.material_id == mat.id
                    ).first()
                    
                    if first_block:
                        existing_review = db_local.query(PendingReviewItem).filter(
                            PendingReviewItem.block_id == first_block.id
                        ).first()
                        
                        if not existing_review:
                            first_block.status = ContentBlockStatus.PENDING_REVIEW.value
                            first_block.is_high_risk = True
                            db_local.commit()
                            
                            review_item = PendingReviewItem(
                                block_id=first_block.id,
                                original_content=first_block.content[:500] if first_block.content else "",
                                extracted_content=first_block.content,
                                confidence_score=30,
                                risk_reason="Material não vinculado a produto - requer categorização manual"
                            )
                            db_local.add(review_item)
                            db_local.commit()
                            
                            progress_queue.put({
                                "type": "log",
                                "message": "Material enviado para revisão (produto não identificado)",
                                "log_type": "warning"
                            })
            
            processing_success = True
            
            if processing_job:
                processing_job.status = ProcessingJobStatus.COMPLETED.value
                processing_job.processed_pages = processing_job.total_pages
                processing_job.last_processed_page = processing_job.total_pages
                processing_job.completed_at = datetime.utcnow()
                
                for page_result in db_local.query(DocumentPageResult).filter(
                    DocumentPageResult.job_id == processing_job.id
                ).all():
                    page_result.status = PageProcessingStatus.SUCCESS.value
                    page_result.processed_at = datetime.utcnow()
                
                db_local.commit()
            
            progress_queue.put({
                "type": "complete",
                "success": True,
                "message": "Processamento concluído com sucesso!",
                "stats": {
                    "blocks_created": result.get("stats", {}).get("blocks_created", 0),
                    "products_matched": list(result.get("stats", {}).get("products_matched", [])),
                    "auto_approved": result.get("stats", {}).get("auto_approved", 0),
                    "pending_review": result.get("stats", {}).get("pending_review", 0)
                }
            })
            
        except Exception as e:
            if processing_job:
                processing_job.status = ProcessingJobStatus.PAUSED.value
                processing_job.error_message = str(e)[:500]
                db_local.commit()
            
            mat = db_local.query(Material).filter(Material.id == material_id_local).first()
            if mat:
                blocks_count = len(mat.blocks) if mat.blocks else 0
                if blocks_count == 0 and not processing_job:
                    db_local.delete(mat)
                    db_local.commit()
                    progress_queue.put({
                        "type": "log",
                        "message": "Material removido (processamento falhou sem criar blocos)",
                        "log_type": "warning"
                    })
                else:
                    mat.processing_status = ProcessingStatus.FAILED.value
                    mat.processing_error = str(e)[:500]
                    db_local.commit()
                    
                    if processing_job:
                        progress_queue.put({
                            "type": "log",
                            "message": "Processamento interrompido - pode ser retomado",
                            "log_type": "warning"
                        })
            
            progress_queue.put({
                "type": "error",
                "message": f"Erro no processamento: {str(e)}",
                "resumable": processing_job is not None,
                "job_id": processing_job.id if processing_job else None
            })
        finally:
            db_local.close()
            progress_queue.put(None)
    
    thread = threading.Thread(target=process_with_progress)
    thread.start()
    
    async def event_generator():
        try:
            while True:
                try:
                    event = progress_queue.get(timeout=0.5)
                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    
                if await request.is_disconnected():
                    break
        finally:
            if upload_id in upload_progress_queues:
                del upload_progress_queues[upload_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/materials/{material_id}/processing-status")
async def get_processing_status(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna o status do processamento de um material, incluindo info de retomada."""
    from database.models import DocumentProcessingJob, ProcessingJobStatus
    
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    job = db.query(DocumentProcessingJob).filter(
        DocumentProcessingJob.material_id == material_id
    ).order_by(DocumentProcessingJob.created_at.desc()).first()
    
    if not job:
        return {
            "has_job": False,
            "resumable": False
        }
    
    return {
        "has_job": True,
        "job_id": job.id,
        "status": job.status,
        "total_pages": job.total_pages,
        "processed_pages": job.processed_pages,
        "last_processed_page": job.last_processed_page,
        "resumable": job.status in [ProcessingJobStatus.PAUSED.value, ProcessingJobStatus.FAILED.value],
        "error_message": job.error_message,
        "file_path": job.file_path
    }


@router.post("/materials/{material_id}/queue-resume")
async def queue_resume_upload(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Adiciona um material pendente na fila de processamento em background.
    Retoma de onde parou usando o DocumentProcessingJob existente.
    """
    from database.models import DocumentProcessingJob, ProcessingJobStatus
    from services.upload_queue import UploadQueue, UploadQueueItem

    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    job = db.query(DocumentProcessingJob).filter(
        DocumentProcessingJob.material_id == material_id
    ).order_by(DocumentProcessingJob.created_at.desc()).first()

    file_path = None
    if job and job.file_path and os.path.exists(job.file_path):
        file_path = job.file_path
    elif material.source_file_path and os.path.exists(material.source_file_path):
        file_path = material.source_file_path
    elif material.file_path and os.path.exists(material.file_path):
        file_path = material.file_path

    if not file_path:
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado. Faça um novo upload.")

    if job and job.status == ProcessingJobStatus.COMPLETED.value:
        if job.last_processed_page and job.total_pages and job.last_processed_page >= job.total_pages:
            raise HTTPException(
                status_code=400,
                detail="Este material já foi processado completamente. Não é necessário retomar."
            )

    existing_job_id = job.id if job else None
    resume_from = job.last_processed_page if job and job.last_processed_page else 0

    upload_id = str(uuid.uuid4())
    queue_item = UploadQueueItem(
        upload_id=upload_id,
        file_path=file_path,
        filename=material.source_filename or material.name,
        material_id=material.id,
        name=material.name,
        user_id=current_user.id,
        material_type=material.material_type or "outro",
        is_resume=True,
        resume_from_page=resume_from,
        existing_job_id=existing_job_id,
    )

    material.processing_status = 'queued'
    db.commit()

    upload_queue = UploadQueue.get_instance()
    upload_queue.add(queue_item)

    return {
        "status": "queued",
        "upload_id": upload_id,
        "material_id": material.id,
        "resuming_from_page": resume_from,
        "total_pages": job.total_pages if job else None,
        "message": f"Retomando processamento da página {resume_from + 1}" if resume_from > 0 else "Processamento adicionado à fila"
    }


@router.post("/materials/{material_id}/resume-upload")
async def resume_upload(
    request: Request,
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retoma o processamento de um upload interrompido.
    Continua de onde parou usando o DocumentProcessingJob existente.
    """
    from database.models import (
        DocumentProcessingJob, DocumentPageResult,
        ProcessingJobStatus, PageProcessingStatus, ProcessingStatus
    )
    
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    job = db.query(DocumentProcessingJob).filter(
        DocumentProcessingJob.material_id == material_id
    ).order_by(DocumentProcessingJob.created_at.desc()).first()
    
    file_path_to_use = None
    start_from_zero = False
    
    if job:
        if job.status not in [ProcessingJobStatus.PAUSED.value, ProcessingJobStatus.FAILED.value]:
            raise HTTPException(status_code=400, detail=f"Job não pode ser retomado (status: {job.status})")
        
        if os.path.exists(job.file_path):
            file_path_to_use = job.file_path
        elif material.file_path and os.path.exists(material.file_path):
            file_path_to_use = material.file_path
            start_from_zero = True
    else:
        if material.file_path and os.path.exists(material.file_path):
            file_path_to_use = material.file_path
            start_from_zero = True
    
    if not file_path_to_use:
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado. Faça um novo upload do documento.")
    
    user_id = current_user.id
    
    upload_id = str(uuid.uuid4())
    progress_queue = queue.Queue()
    upload_progress_queues[upload_id] = progress_queue
    
    def resume_with_progress():
        from database.database import SessionLocal
        from services.product_ingestor import get_product_ingestor
        from datetime import datetime
        import json as json_module
        import fitz
        
        db_local = SessionLocal()
        processing_success = False
        job_local = None
        
        try:
            mat = db_local.query(Material).filter(Material.id == material_id).first()
            if mat:
                mat.processing_status = ProcessingStatus.PROCESSING.value
                db_local.commit()
            
            if start_from_zero or not job:
                try:
                    pdf_doc = fitz.open(file_path_to_use)
                    total_pages = len(pdf_doc)
                    pdf_doc.close()
                except Exception as e:
                    total_pages = 1
                
                job_local = DocumentProcessingJob(
                    material_id=material_id,
                    file_path=file_path_to_use,
                    total_pages=total_pages,
                    processed_pages=0,
                    last_processed_page=0,
                    status=ProcessingJobStatus.PROCESSING.value,
                    retry_count=1
                )
                db_local.add(job_local)
                db_local.commit()
                
                start_page = 0
                progress_queue.put({
                    "type": "start",
                    "message": f"Iniciando processamento do zero (0/{total_pages} páginas)...",
                    "material_id": material_id,
                    "resuming_from": 0
                })
            else:
                job_local = db_local.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.id == job.id
                ).first()
                
                job_local.status = ProcessingJobStatus.PROCESSING.value
                job_local.retry_count += 1
                db_local.commit()
                
                start_page = job_local.last_processed_page
                
                progress_queue.put({
                    "type": "start",
                    "message": f"Retomando processamento da página {start_page + 1}/{job_local.total_pages}...",
                    "material_id": material_id,
                    "resuming_from": start_page
                })
            
            ingestor = get_product_ingestor()
            
            def progress_callback(current, total):
                progress_queue.put({
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "percent": int((current / total) * 100) if total > 0 else 0,
                    "message": f"Processando página {current}/{total}"
                })
                
                job_local.processed_pages = current
                job_local.last_processed_page = current
                db_local.commit()
            
            result = ingestor.process_pdf_with_product_detection_streaming(
                pdf_path=job_local.file_path,
                material_id=material_id,
                document_title=mat.name if mat else "Documento",
                db=db_local,
                user_id=user_id,
                progress_callback=progress_callback,
                log_callback=lambda msg, t: progress_queue.put({"type": "log", "message": msg, "log_type": t}),
                start_page=start_page
            )
            
            job_local.status = ProcessingJobStatus.COMPLETED.value
            job_local.processed_pages = job_local.total_pages
            job_local.last_processed_page = job_local.total_pages
            job_local.completed_at = datetime.utcnow()
            
            for page_result in db_local.query(DocumentPageResult).filter(
                DocumentPageResult.job_id == job_local.id
            ).all():
                page_result.status = PageProcessingStatus.SUCCESS.value
                page_result.processed_at = datetime.utcnow()
            
            if mat:
                mat.processing_status = ProcessingStatus.SUCCESS.value
            
            db_local.commit()
            
            processing_success = True
            
            progress_queue.put({
                "type": "complete",
                "success": True,
                "message": "Processamento retomado e concluído com sucesso!",
                "stats": {
                    "blocks_created": result.get("stats", {}).get("blocks_created", 0),
                    "products_matched": list(result.get("stats", {}).get("products_matched", [])),
                    "auto_approved": result.get("stats", {}).get("auto_approved", 0),
                    "pending_review": result.get("stats", {}).get("pending_review", 0)
                }
            })
            
        except Exception as e:
            if job_local:
                job_local.status = ProcessingJobStatus.PAUSED.value
                job_local.error_message = str(e)[:500]
                db_local.commit()
            elif job:
                job_from_db = db_local.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.id == job.id
                ).first()
                if job_from_db:
                    job_from_db.status = ProcessingJobStatus.PAUSED.value
                    job_from_db.error_message = str(e)[:500]
                    db_local.commit()
            
            mat = db_local.query(Material).filter(Material.id == material_id).first()
            if mat:
                mat.processing_status = ProcessingStatus.FAILED.value
                mat.processing_error = str(e)[:500]
                db_local.commit()
            
            job_id_for_error = job_local.id if job_local else (job.id if job else None)
            progress_queue.put({
                "type": "error",
                "message": f"Erro ao processar: {str(e)}",
                "resumable": True,
                "job_id": job_id_for_error
            })
        finally:
            db_local.close()
            progress_queue.put(None)
    
    thread = threading.Thread(target=resume_with_progress)
    thread.start()
    
    async def event_generator():
        try:
            while True:
                try:
                    event = progress_queue.get(timeout=0.5)
                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
                    
                if await request.is_disconnected():
                    break
        finally:
            if upload_id in upload_progress_queues:
                del upload_progress_queues[upload_id]
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


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


@router.post("/admin/migrate-embeddings")
async def migrate_embeddings_model(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Migra todos os embeddings para o novo modelo text-embedding-3-large.
    
    ATENÇÃO: Esta operação:
    1. Deleta todos os vetores existentes
    2. Recria a collection com as novas dimensões (3072)
    3. Reindexa TODOS os materiais publicados
    
    Apenas admin pode executar.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar esta operação")
    
    from services.vector_store import VectorStore
    from services.product_ingestor import ProductIngestor
    
    vector_store = VectorStore()
    
    reset_result = vector_store.reset_collection_for_migration()
    
    if not reset_result.get("success"):
        raise HTTPException(status_code=500, detail=f"Erro ao resetar collection: {reset_result.get('error')}")
    
    materials = db.query(Material).filter(
        Material.publish_status == "publicado"
    ).all()
    
    ingestor = ProductIngestor()
    indexed_count = 0
    errors = []
    
    for material in materials:
        try:
            result = ingestor.reindex_material(
                material_id=material.id,
                db=db
            )
            if result.get("success"):
                indexed_count += result.get("indexed_count", 0)
            else:
                errors.append(f"Material {material.id}: {result.get('error', 'Erro desconhecido')}")
        except Exception as e:
            errors.append(f"Material {material.id}: {str(e)}")
    
    return {
        "success": True,
        "old_count": reset_result.get("old_count", 0),
        "materials_processed": len(materials),
        "chunks_indexed": indexed_count,
        "errors": errors[:10] if errors else []
    }


UPLOAD_DIR_QUEUE = "uploads/materials"
os.makedirs(UPLOAD_DIR_QUEUE, exist_ok=True)


@router.post("/batch-upload")
async def batch_upload(
    request: Request,
    files: list[UploadFile] = File(...),
    material_type: str = Form("outro"),
    material_categories: str = Form("[]"),
    tags: str = Form("[]"),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
    product_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from services.upload_queue import upload_queue, UploadQueueItem
    from database.models import ProcessingStatus
    import json as json_lib

    parsed_tags = []
    parsed_categories = []
    try:
        parsed_tags = json_lib.loads(tags) if tags else []
    except Exception:
        parsed_tags = []
    try:
        parsed_categories = json_lib.loads(material_categories) if material_categories else []
    except Exception:
        parsed_categories = []

    parsed_valid_from = None
    parsed_valid_until = None
    if valid_from:
        try:
            parsed_valid_from = datetime.fromisoformat(valid_from.replace('Z', '+00:00'))
        except ValueError:
            pass
    if valid_until:
        try:
            parsed_valid_until = datetime.fromisoformat(valid_until.replace('Z', '+00:00'))
        except ValueError:
            pass

    selected_product_id = None
    if product_id:
        try:
            selected_product_id = int(product_id)
            selected_product = db.query(Product).filter(Product.id == selected_product_id).first()
            if not selected_product:
                raise HTTPException(status_code=404, detail="Produto não encontrado")
        except ValueError:
            pass

    target_product_id = selected_product_id
    if not target_product_id:
        placeholder_product = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
        if not placeholder_product:
            raise HTTPException(status_code=500, detail="Produto de sistema não encontrado")
        target_product_id = placeholder_product.id

    queued_items = []

    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            queued_items.append({"filename": file.filename, "error": "Apenas PDFs são suportados", "queued": False})
            continue

        name = file.filename.replace('.pdf', '')

        material = Material(
            product_id=target_product_id,
            material_type=material_type,
            name=name,
            valid_from=parsed_valid_from,
            valid_until=parsed_valid_until,
            tags=json_lib.dumps(parsed_tags),
            material_categories=json_lib.dumps(parsed_categories),
            publish_status="rascunho",
            processing_status=ProcessingStatus.PENDING.value if hasattr(ProcessingStatus, 'PENDING') else "pending"
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        unique_filename = f"{uuid.uuid4()}.pdf"
        file_path = os.path.join(UPLOAD_DIR_QUEUE, unique_filename)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        upload_id = str(uuid.uuid4())
        queue_item = UploadQueueItem(
            upload_id=upload_id,
            file_path=file_path,
            filename=file.filename,
            material_id=material.id,
            name=name,
            user_id=current_user.id,
            material_type=material_type,
            categories=parsed_categories,
            tags=parsed_tags,
            valid_from=parsed_valid_from,
            valid_until=parsed_valid_until,
            selected_product_id=selected_product_id,
        )
        upload_queue.add(queue_item)
        queued_items.append({
            "filename": file.filename,
            "upload_id": upload_id,
            "material_id": material.id,
            "queued": True
        })

    return {
        "success": True,
        "total_queued": sum(1 for i in queued_items if i.get("queued")),
        "items": queued_items
    }


@router.get("/upload-queue/status")
async def get_upload_queue_status(
    current_user: User = Depends(get_current_user)
):
    from services.upload_queue import upload_queue
    return upload_queue.get_all_status()


@router.post("/upload-queue/reorder")
async def reorder_upload_queue(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    from services.upload_queue import upload_queue
    body = await request.json()
    upload_id = body.get("upload_id")
    direction = body.get("direction")

    if not upload_id or direction not in ("up", "down"):
        raise HTTPException(status_code=400, detail="upload_id e direction (up/down) são obrigatórios")

    success = upload_queue.reorder(upload_id, direction)
    if not success:
        raise HTTPException(status_code=400, detail="Não foi possível reordenar. O item pode estar sendo processado ou já está no limite.")

    return {"status": "ok", "message": "Ordem atualizada"}


@router.delete("/upload-queue/{upload_id}")
async def remove_from_upload_queue(
    upload_id: str,
    current_user: User = Depends(get_current_user)
):
    from services.upload_queue import upload_queue
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    success = upload_queue.remove_from_queue(upload_id)
    if not success:
        raise HTTPException(status_code=400, detail="Item não encontrado na fila ou já está sendo processado.")

    return {"status": "ok", "message": "Item removido da fila"}


@router.get("/upload-queue/stream")
async def stream_upload_queue(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from services.upload_queue import upload_queue
    import queue as queue_module

    listener_id = str(uuid.uuid4())
    event_queue = upload_queue.subscribe(listener_id)

    async def event_generator():
        try:
            status = upload_queue.get_all_status()
            yield f"data: {json.dumps({'type': 'init', 'data': status}, ensure_ascii=False)}\n\n"

            while True:
                try:
                    event = event_queue.get(timeout=1)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue_module.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"

                if await request.is_disconnected():
                    break
        finally:
            upload_queue.unsubscribe(listener_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
