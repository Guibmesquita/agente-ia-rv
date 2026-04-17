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
    DocumentPageResult, ProductStatus, MaterialType, ContentBlockType, 
    ContentBlockStatus, ContentSourceType, PersistentQueueItem,
    IngestionLog, MaterialFile
)
from api.endpoints.auth import get_current_user
from services.vector_store import VectorStore
from services.semantic_transformer import transform_content_for_display, transform_semantic_to_indexable, parse_table_to_semantic

router = APIRouter(prefix="/api/products", tags=["products"])

upload_progress_queues = {}


def _save_file_to_db(db: Session, material_id: int, filename: str, file_content: bytes, content_type: str = "application/pdf"):
    existing = db.query(MaterialFile).filter(MaterialFile.material_id == material_id).first()
    if existing:
        existing.filename = filename
        existing.content_type = content_type
        existing.file_data = file_content
        existing.file_size = len(file_content)
    else:
        new_file = MaterialFile(
            material_id=material_id,
            filename=filename,
            content_type=content_type,
            file_data=file_content,
            file_size=len(file_content),
        )
        db.add(new_file)
    try:
        db.commit()
        print(f"[FILE_STORAGE] PDF salvo no banco para material_id={material_id} ({len(file_content)} bytes)")
    except Exception as e:
        db.rollback()
        print(f"[FILE_STORAGE] Erro ao salvar PDF no banco para material_id={material_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao armazenar arquivo no banco: {str(e)}")



def find_or_create_product_from_name(db: Session, material_name: str, gestora: str = None, document_type: str = None):
    import re as _re
    from services.document_metadata_extractor import TICKER_PATTERN, normalize_text
    from services.product_resolver import ProductResolver

    ticker_match = TICKER_PATTERN.search(material_name.upper())
    ticker = f"{ticker_match.group(1)}{ticker_match.group(2)}" if ticker_match else None

    fund_name = material_name
    for pfx in ["Relatório gerencial ", "Relatório Gerencial ", "MP ", "Material Publicitário "]:
        if fund_name.startswith(pfx):
            fund_name = fund_name[len(pfx):]
            break
    fund_name = _re.sub(r'\s*\(\d+\)\s*$', '', fund_name).strip()
    fund_name = _re.sub(r'\s*\(vf\)\s*', ' ', fund_name, flags=_re.IGNORECASE).strip()

    resolver = ProductResolver(db)
    result = resolver.resolve(fund_name=fund_name, ticker=ticker, gestora=gestora)
    if result.matched_product_id:
        matched = db.query(Product).filter(Product.id == result.matched_product_id).first()
        if matched:
            return matched

    if ticker:
        existing = db.query(Product).filter(Product.ticker == ticker).first()
        if existing:
            return existing

    if fund_name:
        norm = normalize_text(fund_name)
        for p in db.query(Product).all():
            if normalize_text(p.name) == norm:
                return p

    product_name = fund_name or ticker or material_name
    if ticker and ticker not in (product_name or ""):
        product_name = f"{product_name} ({ticker})"

    try:
        new_product = Product(
            name=product_name,
            ticker=ticker,
            manager=gestora,
            status="ativo",
            description=f"Produto criado automaticamente a partir de upload de documento ({document_type or 'N/A'})",
        )
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
        return new_product
    except Exception:
        db.rollback()
        if ticker:
            existing = db.query(Product).filter(Product.ticker == ticker).first()
            if existing:
                return existing
        return None


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

def auto_publish_if_ready(material, db: Session):
    pending_count = db.query(ContentBlock).filter(
        ContentBlock.material_id == material.id,
        ContentBlock.status == ContentBlockStatus.PENDING_REVIEW.value
    ).count()
    if pending_count == 0 and material.publish_status in (None, "rascunho"):
        material.publish_status = "publicado"
        db.commit()
        product = db.query(Product).filter(Product.id == material.product_id).first()
        if product:
            from services.product_ingestor import get_product_ingestor
            ingestor = get_product_ingestor()
            result = ingestor.index_approved_blocks(
                material_id=material.id,
                product_name=product.name,
                product_ticker=product.ticker,
                db=db
            )
            indexed = result.get("indexed_count", 0)
        else:
            indexed = 0
        print(f"[AUTO_PUBLISH] Material {material.id} '{material.name}' auto-publicado ({indexed} blocos indexados)")
        return True
    return False


UPLOAD_DIR = "uploads/materials"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== Schemas ====================

PREDEFINED_PRODUCT_CATEGORIES = [
    "FII",
    "FII de Papel",
    "FII de CRI",
    "Ação",
    "COE",
    "Derivativo",
    "Fundo Multimercado",
    "Renda Fixa",
    "Comitê",
]


class ProductCreate(BaseModel):
    name: str
    ticker: Optional[str] = None
    manager: Optional[str] = None
    category: Optional[str] = None
    categories: Optional[List[str]] = None
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    manager: Optional[str] = None
    category: Optional[str] = None
    categories: Optional[List[str]] = None
    status: Optional[str] = None
    description: Optional[str] = None
    product_type: Optional[str] = None  # acao | estruturada | fundo | fii | etf | debenture | outro
    key_info: Optional[str] = None      # JSON com campos extraídos relevantes


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
        query = query.filter(
            or_(
                Product.category == category,
                Product.categories.like(f'%"{category}"%')
            )
        )
    
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
            "categories": p.get_categories(),
            "status": p.status,
            "description": p.description,
            "is_committee": bool(getattr(p, "is_committee", False)),
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
    """Lista categorias únicas de produtos (pré-definidas + valores existentes no banco)."""
    import json as json_lib
    db_cat_set = set()
    all_products = db.query(Product.category, Product.categories).all()
    for row in all_products:
        if row.category:
            db_cat_set.add(row.category)
        if row.categories:
            try:
                for c in json_lib.loads(row.categories):
                    if c:
                        db_cat_set.add(c)
            except Exception:
                pass
    all_cats = list(PREDEFINED_PRODUCT_CATEGORIES)
    for c in sorted(db_cat_set):
        if c not in all_cats:
            all_cats.append(c)
    return {"categories": all_cats}


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
    cats = data.categories if data.categories is not None else ([data.category] if data.category else [])
    product.set_categories(cats)

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
    
    from database.models import MaterialProductLink

    seen_material_ids = set()
    all_materials = list(product.materials)

    linked = db.query(Material).join(
        MaterialProductLink, MaterialProductLink.material_id == Material.id
    ).filter(MaterialProductLink.product_id == product_id).all()
    for lm in linked:
        if lm.id not in {m.id for m in all_materials}:
            all_materials.append(lm)

    materials = []
    for m in all_materials:
        if m.id in seen_material_ids:
            continue
        seen_material_ids.add(m.id)

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

        is_linked = m.product_id != product_id
        materials.append({
            "id": m.id,
            "material_type": m.material_type,
            "name": m.name,
            "description": m.description,
            "current_version": m.current_version,
            "is_indexed": m.is_indexed,
            "blocks_count": len(blocks),
            "blocks": sorted(blocks, key=lambda x: x["order"]),
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            "is_multi_product_link": is_linked,
            "primary_product_id": m.product_id,
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
        "categories": product.get_categories(),
        "status": product.status,
        "description": product.description,
        "product_type": product.product_type,
        "key_info": product.key_info,
        "is_committee": bool(getattr(product, "is_committee", False)),
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
    if data.categories is not None:
        product.set_categories(data.categories)
    elif data.category is not None:
        product.set_categories([data.category])
    if data.status is not None:
        product.status = data.status
    if data.description is not None:
        product.description = data.description
    if data.product_type is not None:
        product.product_type = data.product_type
    if data.key_info is not None:
        product.key_info = data.key_info

    db.commit()
    return {"success": True}


@router.post("/{product_id}/reindex")
async def reindex_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reindexar todos os materiais de um produto no vector store."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    materials = db.query(Material).filter(Material.product_id == product_id).all()
    if not materials:
        return {"success": True, "reindexed_blocks": 0, "materials": 0, "message": "Nenhum material encontrado"}

    from services.product_ingestor import get_product_ingestor
    ingestor = get_product_ingestor()

    product_name = product.name
    product_ticker = product.ticker
    material_ids = [m.id for m in materials]
    n_materials = len(materials)

    def _do_reindex():
        from datetime import datetime
        total = 0
        for mid in material_ids:
            mat = db.query(Material).filter(Material.id == mid).first()
            if mat:
                mat.publish_status = "publicado"
                mat.published_at = datetime.now()
                db.commit()
            result = ingestor.index_approved_blocks(
                material_id=mid,
                product_name=product_name,
                product_ticker=product_ticker,
                db=db
            )
            total += result.get("indexed_count", 0)
        return total

    total_blocks = await asyncio.to_thread(_do_reindex)

    return {
        "success": True,
        "reindexed_blocks": total_blocks,
        "materials": n_materials,
        "message": f"Produto reindexado: {total_blocks} blocos em {n_materials} material(is)"
    }


@router.delete("/{product_id}")
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove um produto e todos seus materiais."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    product = db.query(Product).filter(Product.id == product_id).options(
        joinedload(Product.materials).joinedload(Material.blocks)
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    product_name = product.name

    block_ids = [block.id for mat in product.materials for block in mat.blocks]
    material_ids = [mat.id for mat in product.materials]

    print(f"[DELETE PRODUCT] Iniciando exclusão de '{product_name}' (id={product_id}) por {current_user.username} — {len(material_ids)} materiais, {len(block_ids)} blocos")

    if block_ids:
        n = db.query(PendingReviewItem).filter(
            PendingReviewItem.block_id.in_(block_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE PRODUCT] {n} pending_reviews removidos")

    if material_ids:
        n = db.query(PersistentQueueItem).filter(
            PersistentQueueItem.material_id.in_(material_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE PRODUCT] {n} queue_items removidos")

        n = db.query(IngestionLog).filter(
            IngestionLog.material_id.in_(material_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE PRODUCT] {n} ingestion_logs removidos")

        job_ids = [
            j.id for j in db.query(DocumentProcessingJob.id).filter(
                DocumentProcessingJob.material_id.in_(material_ids)
            ).all()
        ]
        if job_ids:
            n = db.query(DocumentPageResult).filter(
                DocumentPageResult.job_id.in_(job_ids)
            ).delete(synchronize_session=False)
            print(f"[DELETE PRODUCT] {n} page_results removidos")

        n = db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.material_id.in_(material_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE PRODUCT] {n} processing_jobs removidos")

    db.delete(product)
    db.commit()
    print(f"[DELETE PRODUCT] Produto '{product_name}' deletado do banco")

    vector_store = VectorStore()
    removed = 0
    for bid in block_ids:
        if vector_store.delete_document(f"product_block_{bid}"):
            removed += 1
    print(f"[DELETE PRODUCT] {removed}/{len(block_ids)} embeddings removidos do vector store")

    return {"success": True}


@router.post("/{product_id}/toggle-committee")
async def toggle_product_committee(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Alterna a flag is_committee (estrela) de um produto.

    Produtos estrelados são tratados como recomendação formal do Comitê SVN
    pelo agente; produtos não estrelados são informativos (não-recomendação).
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    product.is_committee = not bool(getattr(product, "is_committee", False))
    db.commit()
    db.refresh(product)

    print(
        f"[TOGGLE COMMITTEE] '{product.name}' (id={product_id}) -> "
        f"is_committee={product.is_committee} por {current_user.username}"
    )

    return {
        "success": True,
        "id": product.id,
        "is_committee": bool(product.is_committee),
    }


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
    
    material = db.query(Material).options(
        joinedload(Material.blocks)
    ).filter(
        Material.id == material_id,
        Material.product_id == product_id
    ).first()

    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    print(f"[DELETE MATERIAL] Iniciando exclusão de '{material.name}' (id={material_id}, product_id={product_id}) por {current_user.username} — {len(material.blocks)} blocos")

    vector_store = VectorStore()
    for block in material.blocks:
        vector_store.delete_document(f"product_block_{block.id}")
    print(f"[DELETE MATERIAL] {len(material.blocks)} embeddings removidos do vector store")

    n = db.query(PersistentQueueItem).filter(
        PersistentQueueItem.material_id == material_id
    ).delete()
    print(f"[DELETE MATERIAL] {n} queue_items removidos")

    job_ids = [
        j.id for j in db.query(DocumentProcessingJob.id).filter(
            DocumentProcessingJob.material_id == material_id
        ).all()
    ]
    if job_ids:
        n = db.query(DocumentPageResult).filter(
            DocumentPageResult.job_id.in_(job_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE MATERIAL] {n} page_results removidos")

    n = db.query(DocumentProcessingJob).filter(
        DocumentProcessingJob.material_id == material_id
    ).delete()
    print(f"[DELETE MATERIAL] {n} processing_jobs removidos")

    # FK sem CASCADE — limpeza manual obrigatória antes de db.delete(material).
    block_ids = [b.id for b in material.blocks]
    if block_ids:
        n = db.query(PendingReviewItem).filter(
            PendingReviewItem.block_id.in_(block_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE MATERIAL] {n} pending_review_items removidos")
        n = db.query(BlockVersion).filter(
            BlockVersion.block_id.in_(block_ids)
        ).delete(synchronize_session=False)
        print(f"[DELETE MATERIAL] {n} block_versions removidos")

    n = db.query(IngestionLog).filter(
        IngestionLog.material_id == material_id
    ).delete(synchronize_session=False)
    print(f"[DELETE MATERIAL] {n} ingestion_logs removidos")

    db.delete(material)
    db.commit()
    print(f"[DELETE MATERIAL] Material '{material.name}' deletado do banco")
    return {"success": True}


class MaterialTypeUpdate(BaseModel):
    material_type: str


@router.patch("/materials/{material_id}/type")
async def update_material_type(
    material_id: int,
    data: MaterialTypeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza o tipo (categoria) de um material sem reprocessar embeddings."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    valid_types = [t.value for t in MaterialType]
    if data.material_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo de material inválido: '{data.material_type}'. Valores aceitos: {', '.join(valid_types)}"
        )

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    old_type = material.material_type
    material.material_type = data.material_type
    db.commit()
    db.refresh(material)

    print(f"[MATERIAL_TYPE] material_id={material_id} '{old_type}' → '{data.material_type}' por {current_user.username}")
    return {
        "success": True,
        "material_id": material_id,
        "material_type": material.material_type,
        "name": material.name,
    }


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
        auto_publish_if_ready(material, db)
    
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
            auto_publish_if_ready(material, db)
    
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
    
    pending_products_count = db.query(Material).filter(
        Material.processing_status == "pending_product_match"
    ).count()
    
    return {
        "pending_items": items,
        "total": len(items),
        "pending_products_count": pending_products_count,
        "pending_content_count": len(items),
    }


@router.get("/review/pending-products")
async def list_pending_product_matches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista materiais com matching de produto pendente de confirmação."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    materials = db.query(Material).options(
        joinedload(Material.product)
    ).filter(
        Material.processing_status == "pending_product_match"
    ).order_by(Material.created_at.desc()).all()
    
    items = []
    for mat in materials:
        extracted = {}
        candidates = []
        if mat.extracted_metadata:
            try:
                meta = json.loads(mat.extracted_metadata)
                extracted = meta.get("product_resolver", {}).get("extracted_metadata", meta)
                resolver_data = meta.get("product_resolver", {}).get("resolver_result", {})
                candidates = resolver_data.get("candidates", [])
            except (json.JSONDecodeError, TypeError):
                pass
        
        items.append({
            "material_id": mat.id,
            "material_name": mat.name,
            "source_filename": mat.source_filename,
            "current_product_name": mat.product.name if mat.product else None,
            "current_product_id": mat.product_id,
            "extracted_fund_name": extracted.get("fund_name"),
            "extracted_ticker": extracted.get("ticker"),
            "extracted_gestora": extracted.get("gestora"),
            "extracted_confidence": extracted.get("confidence", 0),
            "candidates": candidates,
            "created_at": mat.created_at.isoformat() if mat.created_at else None,
        })
    
    return {"pending_items": items, "total": len(items)}


@router.post("/review/resolve-product")
async def resolve_product_match(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Resolve o matching de produto para um material.
    Ações: 'link' (vincular a existente) ou 'create' (criar novo).
    """
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    material_id = data.get("material_id")
    action = data.get("action")
    
    if not material_id or action not in ("link", "create"):
        raise HTTPException(status_code=400, detail="material_id e action (link/create) são obrigatórios")
    
    mat = db.query(Material).filter(Material.id == material_id).first()
    if not mat:
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    if action == "link":
        product_id = data.get("product_id")
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id é obrigatório para action=link")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        
        mat.product_id = product.id
        mat.processing_status = "success"
        
        extracted_name = None
        if mat.extracted_metadata:
            try:
                meta = json.loads(mat.extracted_metadata)
                extracted_name = meta.get("fund_name") or meta.get("product_resolver", {}).get("extracted_metadata", {}).get("fund_name")
            except (json.JSONDecodeError, TypeError):
                pass
        
        if extracted_name:
            product.add_alias(extracted_name)
        
        db.commit()
        
        return {
            "success": True,
            "action": "linked",
            "product_name": product.name,
            "product_ticker": product.ticker,
            "alias_saved": extracted_name if extracted_name else None,
        }
    
    elif action == "create":
        product_name = data.get("product_name")
        product_ticker = data.get("product_ticker")
        product_manager = data.get("product_manager")
        product_category = data.get("product_category", "FII")
        
        if not product_name:
            raise HTTPException(status_code=400, detail="product_name é obrigatório para action=create")
        
        if product_ticker:
            existing = db.query(Product).filter(Product.ticker == product_ticker).first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Já existe um produto com ticker {product_ticker}: {existing.name}"
                )
        
        new_product = Product(
            name=product_name,
            ticker=product_ticker,
            manager=product_manager,
            category=product_category,
            status="ativo",
            created_by=current_user.id,
        )
        db.add(new_product)
        db.commit()
        db.refresh(new_product)
        
        mat.product_id = new_product.id
        mat.processing_status = "success"
        db.commit()
        
        return {
            "success": True,
            "action": "created",
            "product_id": new_product.id,
            "product_name": new_product.name,
            "product_ticker": new_product.ticker,
        }


@router.post("/merge-products")
async def merge_products(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Merge produto A (source) em produto B (target).
    Move materiais, blocos, vetores e scripts de A para B.
    Salva nome de A como alias de B. Deleta A.
    """
    if current_user.role not in ["admin"]:
        raise HTTPException(status_code=403, detail="Apenas admin pode fazer merge")
    
    source_id = data.get("source_id")
    target_id = data.get("target_id")
    
    if not source_id or not target_id:
        raise HTTPException(status_code=400, detail="source_id e target_id são obrigatórios")
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="source e target não podem ser o mesmo produto")
    
    source = db.query(Product).filter(Product.id == source_id).first()
    target = db.query(Product).filter(Product.id == target_id).first()
    
    if not source or not target:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    materials_moved = db.query(Material).filter(Material.product_id == source_id).update(
        {Material.product_id: target_id}, synchronize_session=False
    )
    
    from database.models import WhatsAppScript
    scripts_moved = db.query(WhatsAppScript).filter(WhatsAppScript.product_id == source_id).update(
        {WhatsAppScript.product_id: target_id}, synchronize_session=False
    )
    
    target.add_alias(source.name)
    for alias in source.get_aliases():
        target.add_alias(alias)
    
    try:
        vector_store = get_vector_store()
        if vector_store and hasattr(vector_store, 'collection'):
            results = vector_store.collection.get(
                where={"product_id": str(source_id)}
            )
            if results and results.get("ids"):
                for doc_id in results["ids"]:
                    vector_store.collection.update(
                        ids=[doc_id],
                        metadatas=[{"product_id": str(target_id)}]
                    )
    except Exception as e:
        print(f"[MERGE] Aviso: erro ao migrar vetores: {e}")
    
    db.delete(source)
    db.commit()
    
    return {
        "success": True,
        "source_name": source.name,
        "target_name": target.name,
        "materials_moved": materials_moved,
        "scripts_moved": scripts_moved,
    }


@router.get("/{product_id}/aliases")
async def get_product_aliases(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna aliases de um produto."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    return {"aliases": product.get_aliases(), "product_name": product.name}


@router.post("/{product_id}/aliases")
async def manage_product_aliases(
    product_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Adiciona ou remove aliases de um produto."""
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    action = data.get("action", "add")
    alias = data.get("alias", "").strip()
    
    if not alias:
        raise HTTPException(status_code=400, detail="alias é obrigatório")
    
    if action == "add":
        added = product.add_alias(alias)
        db.commit()
        return {"success": True, "added": added, "aliases": product.get_aliases()}
    elif action == "remove":
        aliases = product.get_aliases()
        if alias in aliases:
            aliases.remove(alias)
            product.name_aliases = json.dumps(aliases, ensure_ascii=False)
            db.commit()
            return {"success": True, "removed": True, "aliases": product.get_aliases()}
        return {"success": True, "removed": False, "aliases": aliases}
    else:
        raise HTTPException(status_code=400, detail="action deve ser 'add' ou 'remove'")


@router.post("/review/{item_id}/approve")
async def approve_review_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova um item pendente de revisão e republica no vetor de busca (se material já publicado)."""
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
        if block.material and block.material.publish_status == "publicado":
            from services.product_ingestor import get_product_ingestor
            _product = block.material.product
            ingestor = get_product_ingestor()
            ingestor.index_approved_blocks(
                material_id=block.material_id,
                product_name=_product.name if _product else "",
                product_ticker=_product.ticker if _product else None,
                db=db
            )
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
    if not material.source_file_path:
        raise HTTPException(status_code=400, detail="Material não possui arquivo PDF associado")
    
    page_num = int(block.source_page) if block.source_page else 1
    
    background_tasks.add_task(
        reprocess_single_page,
        material_id=material.id,
        page_num=page_num,
        block_id=block.id,
        pending_item_id=item.id,
        file_path=material.source_file_path,
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
    import json
    
    db = SessionLocal()
    try:
        processor = DocumentProcessor()
        
        image = processor._pdf_page_to_image(file_path, page_num, dpi=150)
        if not image:
            print(f"[REPROCESS] Erro: não foi possível converter página {page_num}")
            return
        
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
                if block.material and block.material.publish_status == "publicado":
                    from services.product_ingestor import get_product_ingestor
                    _material = db.query(Material).filter(Material.id == block.material_id).first()
                    _product = db.query(Product).filter(Product.id == _material.product_id).first() if _material else None
                    get_product_ingestor().index_approved_blocks(
                        material_id=block.material_id,
                        product_name=_product.name if _product else "",
                        product_ticker=_product.ticker if _product else None,
                        db=db
                    )
                    print(f"[REPROCESS] Bloco indexado no vetor de busca")
            except Exception as idx_err:
                print(f"[REPROCESS] Erro ao indexar bloco: {idx_err}")
            
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
    
    import os
    from fastapi.responses import FileResponse
    
    ALLOWED_UPLOAD_DIR = os.path.realpath("uploads/materials")
    file_path = None
    
    if material.source_file_path:
        candidate = os.path.realpath(material.source_file_path)
        if os.path.commonpath([candidate, ALLOWED_UPLOAD_DIR]) == ALLOWED_UPLOAD_DIR and os.path.isfile(candidate):
            file_path = candidate
    
    if not file_path:
        restored = _restore_pdf_from_db(db, material_id)
        if restored:
            candidate = os.path.realpath(restored)
            if os.path.commonpath([candidate, ALLOWED_UPLOAD_DIR]) == ALLOWED_UPLOAD_DIR and os.path.isfile(candidate):
                file_path = candidate
    
    if not file_path:
        raise HTTPException(status_code=404, detail="PDF não encontrado no disco nem no banco de dados")
    
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=(material.source_filename or material.name or "documento") + ".pdf",
        headers={"Content-Disposition": "inline"}
    )


@router.get("/materials/all")
async def list_all_materials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os materiais do sistema com status de processamento da fila."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from sqlalchemy import func as sqlfunc

    materials = db.query(Material).options(
        joinedload(Material.product)
    ).order_by(Material.created_at.desc()).all()

    material_ids = [m.id for m in materials]

    active_queue_items = db.query(PersistentQueueItem).filter(
        PersistentQueueItem.material_id.in_(material_ids),
        PersistentQueueItem.status.in_(["queued", "processing"])
    ).all() if material_ids else []

    queue_by_material = {}
    for qi in sorted(active_queue_items, key=lambda x: x.created_at or datetime.min):
        queue_by_material[qi.material_id] = qi

    block_counts = dict(
        db.query(ContentBlock.material_id, sqlfunc.count(ContentBlock.id))
        .filter(ContentBlock.material_id.in_(material_ids))
        .group_by(ContentBlock.material_id)
        .all()
    ) if material_ids else {}

    result = []
    for m in materials:
        blocks_count = block_counts.get(m.id, 0)
        qi = queue_by_material.get(m.id)

        if qi:
            effective_status = qi.status
            queue_current_page = qi.current_page or 0
            queue_total_pages = qi.total_pages or 0
            queue_progress = qi.progress or 0
        else:
            effective_status = m.processing_status or "pending"
            queue_current_page = 0
            queue_total_pages = 0
            queue_progress = 0

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
            "blocks_count": blocks_count,
            "processing_status": effective_status,
            "processing_error": m.processing_error,
            "queue_current_page": queue_current_page,
            "queue_total_pages": queue_total_pages,
            "queue_progress": queue_progress,
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
    
    pending_materials = [
        m for m in pending_materials
        if not (m.processing_error and 'duplicado bloqueado' in m.processing_error.lower())
    ]
    
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
                (job and job.file_path and os.path.exists(job.file_path)) or
                db.query(MaterialFile).filter(MaterialFile.material_id == m.id).first() is not None
            )
        })
    
    return {"pending_materials": result, "total": len(result)}


@router.get("/materials/pending-unified")
async def list_pending_unified(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista unificada de materiais que precisam de ação: sem PDF ou com processamento falho."""
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from sqlalchemy import func

    materials_with_file = {
        mf.material_id
        for mf in db.query(MaterialFile.material_id).all()
    }

    blocks_count_map = dict(
        db.query(ContentBlock.material_id, func.count(ContentBlock.id))
        .group_by(ContentBlock.material_id)
        .all()
    )

    active_queue_ids = {
        row.material_id for row in
        db.query(PersistentQueueItem.material_id).filter(
            PersistentQueueItem.status.in_(['queued', 'processing'])
        ).all()
    }

    all_materials = db.query(Material).options(
        joinedload(Material.product)
    ).order_by(Material.created_at.desc()).all()

    success_names = {}
    for m in all_materials:
        if m.processing_status == "success" and blocks_count_map.get(m.id, 0) > 0:
            key = (m.name or "").strip().lower()
            if key and (key not in success_names or blocks_count_map.get(m.id, 0) > blocks_count_map.get(success_names[key], 0)):
                success_names[key] = m.id

    missing_pdf = []
    failed_processing = []

    for m in all_materials:
        if m.processing_error and 'duplicado bloqueado' in (m.processing_error or '').lower():
            continue
        if m.id in active_queue_ids:
            continue

        bc = blocks_count_map.get(m.id, 0)
        product = m.product

        base = {
            "id": m.id,
            "name": m.name,
            "source_filename": m.source_filename,
            "product_id": m.product_id,
            "product_name": product.name if product else None,
            "product_ticker": product.ticker if product else None,
            "material_type": m.material_type,
            "blocks_count": bc,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "processing_status": m.processing_status,
        }

        if m.processing_status == "success" and bc > 0 and m.id not in materials_with_file:
            if m.pdf_whatsapp_dismissed:
                continue
            base["pending_type"] = "missing_pdf"
            missing_pdf.append(base)

        elif m.processing_status in ["failed", "pending", "processing"]:
            key = (m.name or "").strip().lower()
            dup_id = success_names.get(key)
            has_dup = dup_id is not None and dup_id != m.id
            base["pending_type"] = "failed_processing"
            base["processing_error"] = m.processing_error
            base["has_success_duplicate"] = has_dup
            if has_dup:
                base["success_duplicate_id"] = dup_id
                base["success_duplicate_blocks"] = blocks_count_map.get(dup_id, 0)

            job = db.query(DocumentProcessingJob).filter(
                DocumentProcessingJob.material_id == m.id
            ).order_by(DocumentProcessingJob.created_at.desc()).first()
            base["job_info"] = {
                "total_pages": job.total_pages if job else None,
                "processed_pages": job.processed_pages if job else None,
            } if job else None
            base["can_resume"] = m.processing_status in ['processing', 'failed'] and (
                (m.source_file_path and os.path.exists(m.source_file_path)) or
                (job and job.file_path and os.path.exists(job.file_path)) or
                m.id in materials_with_file
            )
            failed_processing.append(base)

    missing_pdf.sort(key=lambda x: (x.get("product_ticker") or "", x.get("name") or ""))

    return {
        "missing_pdf": missing_pdf,
        "failed_processing": failed_processing,
        "total_missing_pdf": len(missing_pdf),
        "total_failed": len(failed_processing),
        "total": len(missing_pdf) + len(failed_processing),
    }


@router.post("/materials/{material_id}/dismiss-pdf")
async def dismiss_pdf_pending(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marca um material como dispensado da pendência 'Sem PDF para WhatsApp'.
    O material continua indexado e disponível para o agente; apenas deixa de aparecer na lista de pendências.
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    material.pdf_whatsapp_dismissed = True
    db.commit()

    return {"ok": True}


@router.post("/materials/{material_id}/toggle-whatsapp")
async def toggle_material_whatsapp(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ativa ou desativa o envio do material via WhatsApp pelo agente.
    Quando desativado, o material não aparece na lista de materiais disponíveis para envio.
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    current_val = material.available_for_whatsapp if material.available_for_whatsapp is not None else True
    material.available_for_whatsapp = not current_val
    db.commit()

    state = "ativado" if material.available_for_whatsapp else "desativado"
    return {
        "ok": True,
        "available_for_whatsapp": material.available_for_whatsapp,
        "message": f"Material {state} para envio via WhatsApp"
    }


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
    
    from core.upload_validator import validate_upload
    from core.security_middleware import record_security_event
    
    content, file_hash = await validate_upload(file)
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as f:
        f.write(content)
    
    record_security_event(
        "file_upload",
        user_id=current_user.id,
        username=current_user.username,
        filename=file.filename,
        file_hash=file_hash,
        size_bytes=len(content),
        product_id=product_id,
        material_id=material_id,
    )

    _save_file_to_db(db, material_id, file.filename or "documento.pdf", content)
    
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
        "message": "PDF enviado para processamento. Os blocos serão criados em alguns instantes.",
        "file_hash": file_hash
    }


@router.post("/smart-upload")
async def smart_upload_without_product(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    material_type: str = Form("one_page"),
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
    
    from datetime import datetime

    content_bytes = await file.read()

    import hashlib as _hashlib
    file_hash = _hashlib.sha256(content_bytes).hexdigest()
    existing_dup = db.query(Material).filter(
        Material.file_hash == file_hash,
        Material.file_hash != None,
        Material.processing_status == "success"
    ).first()
    if existing_dup:
        dup_date = existing_dup.created_at.strftime('%d/%m/%Y') if existing_dup.created_at else 'data desconhecida'
        raise HTTPException(
            status_code=409,
            detail=f"Arquivo idêntico já processado como '{existing_dup.name}' em {dup_date}. Upload duplicado bloqueado."
        )

    material_name = name or file.filename.replace('.pdf', '')
    temp_product = find_or_create_product_from_name(db, material_name)
    if not temp_product:
        raise HTTPException(status_code=500, detail="Não foi possível criar ou encontrar produto para o material")

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
        product_id=temp_product.id,
        material_type=material_type,
        name=name,
        description=description,
        valid_from=parsed_valid_from,
        valid_until=parsed_valid_until,
        publish_status="rascunho",
        file_hash=file_hash
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    _save_file_to_db(db, material.id, file.filename or "documento.pdf", content_bytes)
    
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
        "product_id": temp_product.id
    }


@router.post("/smart-upload-stream")
async def smart_upload_stream(
    request: Request,
    file: UploadFile = File(...),
    material_type: str = Form("one_page"),
    name: str = Form(...),
    description: str = Form(None),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
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
    
    from datetime import datetime as dt

    content_bytes = await file.read()
    await file.seek(0)

    import hashlib as _hashlib
    file_hash = _hashlib.sha256(content_bytes).hexdigest()
    existing_dup = db.query(Material).filter(
        Material.file_hash == file_hash,
        Material.file_hash != None,
        Material.processing_status == "success"
    ).first()
    if existing_dup:
        dup_date = existing_dup.created_at.strftime('%d/%m/%Y') if existing_dup.created_at else 'data desconhecida'
        raise HTTPException(
            status_code=409,
            detail=f"Arquivo idêntico já processado como '{existing_dup.name}' em {dup_date}. Upload duplicado bloqueado."
        )

    material_name2 = name or file.filename.replace('.pdf', '')
    temp_product2 = find_or_create_product_from_name(db, material_name2)
    if not temp_product2:
        raise HTTPException(status_code=500, detail="Não foi possível criar ou encontrar produto para o material")

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
    try:
        parsed_tags = json_lib.loads(tags) if tags else []
    except:
        parsed_tags = []
    
    material = Material(
        product_id=temp_product2.id,
        material_type=material_type,
        name=name,
        description=description,
        valid_from=parsed_valid_from,
        valid_until=parsed_valid_until,
        tags=json_lib.dumps(parsed_tags),
        publish_status="rascunho",
        file_hash=file_hash
    )
    db.add(material)
    db.commit()
    db.refresh(material)
    
    unique_filename = f"{uuid.uuid4()}.pdf"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as f:
        f.write(content_bytes)

    _save_file_to_db(db, material.id, file.filename or "documento.pdf", content_bytes)
    
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
                existing_products = db_local.query(Product).all()
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
                    
                    if matched_product:
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
                
                pass
            
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


def _restore_pdf_from_db(db, material_id: int) -> str:
    """
    Restaura o PDF do banco de dados (material_files) para o filesystem.
    Retorna o caminho do arquivo restaurado ou None se não encontrado no banco.
    """
    from database.models import MaterialFile
    import re as _re
    mf = db.query(MaterialFile).filter(MaterialFile.material_id == material_id).first()
    if not mf or not mf.file_data:
        return None

    restore_dir = os.path.join("uploads", "materials")
    os.makedirs(restore_dir, exist_ok=True)
    safe_filename = _re.sub(r'[^\w\-.]', '_', os.path.basename(mf.filename or f"material_{material_id}.pdf"))
    restored_path = os.path.join(restore_dir, f"restored_{material_id}_{safe_filename}")
    with open(restored_path, "wb") as f:
        f.write(mf.file_data)
    print(f"[RESTORE] PDF restaurado do banco para {restored_path} (material_id={material_id}, {mf.file_size} bytes)")
    return restored_path


class BatchQueueResumeRequest(BaseModel):
    material_ids: List[int]


@router.post("/materials/batch-queue-resume")
async def batch_queue_resume(
    payload: BatchQueueResumeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Enfileira múltiplos materiais pendentes para processamento em background.
    Retorna imediatamente. Materiais já na fila são ignorados silenciosamente.
    """
    from database.models import DocumentProcessingJob, ProcessingJobStatus
    from services.upload_queue import UploadQueue, UploadQueueItem

    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not payload.material_ids:
        raise HTTPException(status_code=400, detail="Nenhum material_id fornecido")

    if len(payload.material_ids) > 100:
        raise HTTPException(status_code=400, detail="Máximo de 100 materiais por lote")

    already_queued_ids = set(
        row[0] for row in db.query(PersistentQueueItem.material_id).filter(
            PersistentQueueItem.material_id.in_(payload.material_ids),
            PersistentQueueItem.status.in_(["queued", "processing"])
        ).all()
    )

    materials = db.query(Material).filter(
        Material.id.in_(payload.material_ids)
    ).options(joinedload(Material.product)).all()
    materials_by_id = {m.id: m for m in materials}

    upload_queue = UploadQueue.get_instance()
    queued = []
    skipped = []
    errors = []

    for material_id in payload.material_ids:
        material = materials_by_id.get(material_id)
        if not material:
            errors.append({"material_id": material_id, "reason": "Material não encontrado"})
            continue

        if material_id in already_queued_ids:
            skipped.append({"material_id": material_id, "reason": "Já está na fila"})
            continue

        job = db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.material_id == material_id
        ).order_by(DocumentProcessingJob.created_at.desc()).first()

        file_path = None
        if job and job.file_path and os.path.exists(job.file_path):
            file_path = job.file_path
        elif material.source_file_path and os.path.exists(material.source_file_path):
            file_path = material.source_file_path

        if not file_path:
            restored = _restore_pdf_from_db(db, material_id)
            if restored:
                file_path = restored
            else:
                errors.append({"material_id": material_id, "reason": "Arquivo PDF não encontrado"})
                continue

        has_blocks = db.query(ContentBlock).filter(ContentBlock.material_id == material_id).count() > 0

        if job and job.status == ProcessingJobStatus.COMPLETED.value:
            if has_blocks and job.last_processed_page and job.total_pages and job.last_processed_page >= job.total_pages:
                skipped.append({"material_id": material_id, "reason": "Já processado completamente"})
                continue

        existing_job_id = job.id if job else None
        resume_from = 0
        if job and job.last_processed_page and has_blocks:
            resume_from = job.last_processed_page
        elif job and not has_blocks:
            job.last_processed_page = 0
            job.processed_pages = 0
            db.commit()

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

        try:
            material.processing_status = "queued"
            db.commit()
            upload_queue.add(queue_item)
            queued.append({"material_id": material_id, "upload_id": upload_id})
        except Exception as enqueue_err:
            db.rollback()
            try:
                db.refresh(material)
                material.processing_status = "pending"
                db.commit()
            except Exception:
                db.rollback()
            errors.append({"material_id": material_id, "reason": f"Erro ao enfileirar: {str(enqueue_err)[:80]}"})

    return {
        "queued": queued,
        "skipped": skipped,
        "errors": errors,
        "total_queued": len(queued),
        "message": f"{len(queued)} documento(s) adicionado(s) à fila de processamento",
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

    if not file_path:
        restored = _restore_pdf_from_db(db, material_id)
        if restored:
            file_path = restored
        else:
            raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado. Faça um novo upload.")

    has_blocks = db.query(ContentBlock).filter(ContentBlock.material_id == material_id).count() > 0

    if job and job.status == ProcessingJobStatus.COMPLETED.value:
        if has_blocks and job.last_processed_page and job.total_pages and job.last_processed_page >= job.total_pages:
            raise HTTPException(
                status_code=400,
                detail="Este material já foi processado completamente. Não é necessário retomar."
            )

    existing_job_id = job.id if job else None
    resume_from = 0
    if job and job.last_processed_page and has_blocks:
        resume_from = job.last_processed_page
    elif job and not has_blocks:
        job.last_processed_page = 0
        job.processed_pages = 0
        db.commit()

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
        if job.status == ProcessingJobStatus.PROCESSING.value:
            from datetime import timedelta
            stale_threshold = datetime.utcnow() - timedelta(minutes=30)
            last_activity = (job.updated_at or job.created_at)
            if last_activity:
                last_activity_naive = last_activity.replace(tzinfo=None) if last_activity.tzinfo else last_activity
                if last_activity_naive > stale_threshold:
                    raise HTTPException(status_code=400, detail="Este documento está sendo processado no momento. Aguarde a conclusão.")
            job.status = ProcessingJobStatus.FAILED.value
            job.error_message = "Processamento interrompido (travado em processing)"
            db.commit()
            print(f"[RESUME] Job {job.id} (material {material_id}) transicionado de 'processing' para 'failed' (travado)")
        elif job.status not in [ProcessingJobStatus.PAUSED.value, ProcessingJobStatus.FAILED.value]:
            raise HTTPException(status_code=400, detail=f"Job não pode ser retomado (status: {job.status})")
        
        if job.file_path and os.path.exists(job.file_path):
            file_path_to_use = job.file_path
        elif material.source_file_path and os.path.exists(material.source_file_path):
            file_path_to_use = material.source_file_path
            start_from_zero = True
    else:
        if material.source_file_path and os.path.exists(material.source_file_path):
            file_path_to_use = material.source_file_path
            start_from_zero = True
    
    if not file_path_to_use:
        restored = _restore_pdf_from_db(db, material_id)
        if restored:
            file_path_to_use = restored
            if job:
                job.file_path = restored
                db.commit()
                has_content = db.query(ContentBlock).filter(ContentBlock.material_id == material_id).count() > 0
                if not has_content:
                    start_from_zero = True
                    print(f"[RESUME] Material {material_id}: 0 content blocks — forçando reprocessamento do zero")
                else:
                    start_from_zero = not (job.last_processed_page and job.last_processed_page > 0)
            else:
                start_from_zero = True
        else:
            raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado no servidor nem no banco de dados.")
    
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


@router.post("/materials/{material_id}/reindex")
async def reindex_material(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reindexar um material: atualiza publish_status para publicado e indexa blocos aprovados."""
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
        "message": "Material reindexado",
        "indexed_count": result.get("indexed_count", 0)
    }


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
            product = db.query(Product).filter(Product.id == material.product_id).first()
            result = ingestor.index_approved_blocks(
                material_id=material.id,
                product_name=product.name if product else "",
                product_ticker=product.ticker if product else None,
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


@router.get("/admin/vector-stats")
async def vector_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna estatísticas do vector store: totais, agrupamentos e embeddings órfãos."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar")

    from sqlalchemy import text

    total = db.execute(text("SELECT COUNT(*) FROM document_embeddings")).scalar()

    breakdown_rows = db.execute(text(
        "SELECT product_ticker, product_name, publish_status, COUNT(*) as total "
        "FROM document_embeddings "
        "GROUP BY product_ticker, product_name, publish_status "
        "ORDER BY total DESC"
    )).fetchall()
    breakdown = [
        {
            "product_ticker": r[0],
            "product_name": r[1],
            "publish_status": r[2],
            "total": r[3]
        }
        for r in breakdown_rows
    ]

    orphan_rows = db.execute(text(
        "SELECT doc_id, product_ticker, product_name, publish_status "
        "FROM document_embeddings "
        "WHERE doc_id LIKE 'product_block_%' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM content_blocks cb "
        "  WHERE cb.id = CAST(REPLACE(doc_id, 'product_block_', '') AS INTEGER)"
        ") "
        "ORDER BY product_name, doc_id"
    )).fetchall()
    orphans = [
        {"doc_id": r[0], "product_ticker": r[1], "product_name": r[2], "publish_status": r[3]}
        for r in orphan_rows
    ]

    return {
        "total_embeddings": total,
        "by_product": breakdown,
        "orphan_embeddings": orphans,
        "orphan_count": len(orphans)
    }


@router.post("/admin/cleanup-orphan-embeddings")
async def cleanup_orphan_embeddings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Remove embeddings órfãos — cujo content_block correspondente não existe mais no banco."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar")

    from sqlalchemy import text

    orphan_rows = db.execute(text(
        "SELECT doc_id FROM document_embeddings "
        "WHERE doc_id LIKE 'product_block_%' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM content_blocks cb "
        "  WHERE cb.id = CAST(REPLACE(doc_id, 'product_block_', '') AS INTEGER)"
        ")"
    )).fetchall()

    orphan_ids = [r[0] for r in orphan_rows]

    if orphan_ids:
        vector_store = VectorStore()
        for doc_id in orphan_ids:
            vector_store.delete_document(doc_id)

    print(f"[CLEANUP] {len(orphan_ids)} embeddings órfãos removidos: {orphan_ids[:10]}")

    return {
        "success": True,
        "removed_count": len(orphan_ids),
        "removed_ids": orphan_ids
    }


@router.post("/admin/fix-publish-status")
async def fix_publish_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Corrige embeddings gravados com publish_status='rascunho', tornando-os visíveis na busca."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar")

    from sqlalchemy import text

    result = db.execute(text(
        "UPDATE document_embeddings "
        "SET publish_status = 'publicado' "
        "WHERE doc_id LIKE 'product_block_%' "
        "AND publish_status = 'rascunho'"
    ))
    db.commit()

    updated = result.rowcount
    print(f"[FIX-PUBLISH] {updated} embeddings atualizados para 'publicado'")

    return {
        "success": True,
        "updated_count": updated
    }


@router.post("/admin/fix-stuck-blocks")
async def fix_stuck_blocks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Aprova blocos travados em pending_review sem entrada na fila de revisão (TVRI11 e VGHF11)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar")

    from sqlalchemy import text

    result = db.execute(text(
        "UPDATE content_blocks "
        "SET status = 'auto_approved', "
        "    updated_at = NOW() "
        "WHERE status = 'pending_review' "
        "AND material_id IN ("
        "  SELECT m.id FROM materials m "
        "  JOIN products p ON p.id = m.product_id "
        "  WHERE p.name IN ('TVRI11', 'VGHF11')"
        ")"
    ))
    db.commit()

    approved = result.rowcount
    print(f"[FIX-STUCK] {approved} blocos aprovados (TVRI11/VGHF11)")

    return {
        "success": True,
        "approved_count": approved
    }


@router.get("/admin/materials-without-files")
async def materials_without_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista materiais que não possuem arquivo PDF disponível (nem no banco nem em disco)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar")

    from database.models import Material, MaterialFile, Product
    from sqlalchemy import and_

    all_materials = db.query(Material).filter(
        Material.source_file_path.isnot(None),
        Material.source_file_path != ""
    ).all()

    materials_with_db_file = {
        mf.material_id
        for mf in db.query(MaterialFile.material_id).all()
    }

    missing = []
    available = []
    for m in all_materials:
        has_db = m.id in materials_with_db_file
        has_disk = m.source_file_path and os.path.exists(m.source_file_path)
        product = m.product
        product_name = product.name if product else m.name
        info = {
            "material_id": m.id,
            "material_name": m.name,
            "product_name": product_name,
            "material_type": m.material_type,
            "has_db_file": has_db,
            "has_disk_file": has_disk,
        }
        if has_db or has_disk:
            available.append(info)
        else:
            missing.append(info)

    return {
        "total_materials": len(all_materials),
        "with_file": len(available),
        "without_file": len(missing),
        "missing": missing,
    }


@router.post("/admin/reupload-pdf/{material_id}")
async def reupload_pdf(
    material_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from database.models import Material

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail=f"Material {material_id} não encontrado")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos")

    file_content = await file.read()
    if len(file_content) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")

    _save_file_to_db(db, material_id, file.filename, file_content, "application/pdf")

    material.source_filename = file.filename
    db.commit()

    product = material.product
    print(f"[REUPLOAD] PDF re-uploaded para material_id={material_id} ({material.name}) - {len(file_content)} bytes")

    return {
        "success": True,
        "material_id": material_id,
        "material_name": material.name,
        "product_name": product.name if product else "—",
        "filename": file.filename,
        "file_size": len(file_content),
    }


UPLOAD_DIR_QUEUE = "uploads/materials"
os.makedirs(UPLOAD_DIR_QUEUE, exist_ok=True)


@router.post("/batch-upload")
async def batch_upload(
    request: Request,
    files: list[UploadFile] = File(...),
    material_type: str = Form("outro"),
    tags: str = Form("[]"),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
    product_id: str = Form(None),
    campaign_slug: str = Form(None),
    campaign_structure_type: str = Form(None),
    campaign_key_data: str = Form(None),
    campaign_diagram: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from services.upload_queue import upload_queue, UploadQueueItem
    from database.models import ProcessingStatus
    import json as json_lib
    import re as re_lib

    if campaign_slug:
        if not re_lib.match(r'^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$', campaign_slug):
            raise HTTPException(status_code=400, detail="campaign_slug inválido. Use apenas letras minúsculas, números e hífens (3-64 caracteres).")
        if campaign_key_data:
            try:
                kd_parsed = json_lib.loads(campaign_key_data)
                if not isinstance(kd_parsed, dict):
                    raise ValueError()
            except (json_lib.JSONDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="campaign_key_data deve ser um JSON object válido.")
        if campaign_diagram and campaign_diagram.filename:
            allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
            ext_check = os.path.splitext(campaign_diagram.filename)[1].lower()
            if ext_check not in allowed_ext:
                raise HTTPException(status_code=400, detail=f"Tipo de arquivo do diagrama não suportado. Permitidos: {', '.join(allowed_ext)}")

    parsed_tags = []
    try:
        parsed_tags = json_lib.loads(tags) if tags else []
    except Exception:
        parsed_tags = []

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

    queued_items = []

    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            queued_items.append({"filename": file.filename, "error": "Apenas PDFs são suportados", "queued": False})
            continue

        name = file.filename.replace('.pdf', '')

        content = await file.read()

        import hashlib as hl
        file_hash = hl.sha256(content).hexdigest()
        existing_success = db.query(Material).filter(
            Material.file_hash == file_hash,
            Material.file_hash != None,
            Material.processing_status == "success"
        ).first()
        if existing_success:
            dup_name = existing_success.name
            queued_items.append({
                "filename": file.filename,
                "error": f"Arquivo idêntico já processado como '{dup_name}'. Upload duplicado bloqueado.",
                "queued": False,
                "existing_material_id": existing_success.id
            })
            continue

        file_product_id = selected_product_id
        if not file_product_id:
            auto_product = find_or_create_product_from_name(db, name)
            if auto_product:
                file_product_id = auto_product.id
            else:
                queued_items.append({"filename": file.filename, "error": "Não foi possível criar produto automaticamente", "queued": False})
                continue

        material = Material(
            product_id=file_product_id,
            material_type=material_type,
            name=name,
            valid_from=parsed_valid_from,
            valid_until=parsed_valid_until,
            tags=json_lib.dumps(parsed_tags),
            publish_status="rascunho",
            processing_status=ProcessingStatus.PENDING.value if hasattr(ProcessingStatus, 'PENDING') else "pending",
            file_hash=file_hash
        )
        db.add(material)
        db.commit()
        db.refresh(material)

        unique_filename = f"{uuid.uuid4()}.pdf"
        file_path = os.path.join(UPLOAD_DIR_QUEUE, unique_filename)
        with open(file_path, "wb") as f:
            f.write(content)

        _save_file_to_db(db, material.id, file.filename or "documento.pdf", content)

        upload_id = str(uuid.uuid4())
        queue_item = UploadQueueItem(
            upload_id=upload_id,
            file_path=file_path,
            filename=file.filename,
            material_id=material.id,
            name=name,
            user_id=current_user.id,
            material_type=material_type,
            categories=[],
            tags=parsed_tags,
            valid_from=parsed_valid_from,
            valid_until=parsed_valid_until,
            selected_product_id=selected_product_id,
        )
        upload_queue.add(queue_item)

        campaign_structure_id = None
        campaign_error = None
        is_campaign = campaign_slug and material_type == "campanha"
        if is_campaign:
            from database.models import CampaignStructure
            existing_cs = db.query(CampaignStructure).filter(
                CampaignStructure.campaign_slug == campaign_slug
            ).first()
            if existing_cs:
                existing_cs.material_id = material.id
                if parsed_valid_from:
                    existing_cs.valid_from = parsed_valid_from
                if parsed_valid_until:
                    existing_cs.valid_until = parsed_valid_until
                db.commit()
                campaign_structure_id = existing_cs.id
                print(f"[CAMPAIGN] Estrutura existente relinked: {campaign_slug} (id={existing_cs.id}) → material {material.id}")
            else:
                try:
                    product = db.query(Product).filter(Product.id == file_product_id).first()
                    ticker = product.ticker if product else None

                    cs = CampaignStructure(
                        name=name,
                        ticker=ticker,
                        structure_type=campaign_structure_type or "outro",
                        campaign_slug=campaign_slug,
                        key_data=campaign_key_data if campaign_key_data else "{}",
                        material_id=material.id,
                        valid_from=parsed_valid_from,
                        valid_until=parsed_valid_until,
                        is_active=1,
                        created_by=int(current_user.id),
                    )

                    if campaign_diagram and campaign_diagram.filename:
                        allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
                        ext = os.path.splitext(campaign_diagram.filename)[1].lower()
                        if ext not in allowed_ext:
                            ext = ".png"
                        diagram_name = f"{campaign_slug}{ext}"
                        diagram_dir = os.path.join("static", "derivatives_diagrams")
                        os.makedirs(diagram_dir, exist_ok=True)
                        diagram_content = await campaign_diagram.read()
                        max_diagram_size = 10 * 1024 * 1024
                        if len(diagram_content) > max_diagram_size:
                            campaign_error = "Diagrama excede 10MB"
                        else:
                            with open(os.path.join(diagram_dir, diagram_name), "wb") as df:
                                df.write(diagram_content)
                            cs.diagram_filename = diagram_name

                    db.add(cs)
                    db.commit()
                    db.refresh(cs)
                    campaign_structure_id = cs.id
                    print(f"[CAMPAIGN] Estrutura de campanha criada: {campaign_slug} (id={cs.id})")
                except Exception as e:
                    db.rollback()
                    campaign_error = f"Erro ao criar estrutura: {str(e)}"
                    print(f"[CAMPAIGN] {campaign_error}")

        queued_items.append({
            "filename": file.filename,
            "upload_id": upload_id,
            "material_id": material.id,
            "queued": True,
            "campaign_structure_id": campaign_structure_id,
            "campaign_error": campaign_error,
        })

    return {
        "success": True,
        "total_queued": sum(1 for i in queued_items if i.get("queued")),
        "items": queued_items
    }


def _extract_pdf_text_for_analysis(file_content: bytes, max_pages: int = None) -> str:
    """
    Extrai texto de um PDF para análise de produtos.
    Estratégia em camadas:
    - Lê TODAS as páginas com get_text('dict') para capturar texto e tabelas
    - Aplica sampling inteligente (30% início / 40% meio / 30% fim) para PDFs longos
    - Limite de ~20.000 chars para respeitar janela do GPT
    """
    MAX_CHARS = 20_000
    try:
        import fitz
        doc = fitz.open(stream=file_content, filetype="pdf")
        total = len(doc)
        if total == 0:
            doc.close()
            return ""

        def _page_to_text(page) -> str:
            page_dict = page.get_text("dict")
            blocks = page_dict.get("blocks", [])

            # Coleta todas as linhas de texto com suas coordenadas Y
            raw_lines = []
            for b in blocks:
                if b.get("type", 0) != 0:
                    continue
                for line in b.get("lines", []):
                    span_text = " ".join(s.get("text", "") for s in line.get("spans", []))
                    if not span_text.strip():
                        continue
                    y0 = line.get("bbox", [0, 0, 0, 0])[1]
                    raw_lines.append((round(y0, 1), span_text.strip()))

            if not raw_lines:
                return ""

            # Agrupa linhas com Y próximo (tolerância de 2pt) como células de tabela
            raw_lines.sort(key=lambda x: x[0])
            groups = []
            current_y = None
            current_group = []
            for y, text in raw_lines:
                if current_y is None or abs(y - current_y) <= 2:
                    current_group.append(text)
                    if current_y is None:
                        current_y = y
                else:
                    groups.append(current_group)
                    current_group = [text]
                    current_y = y
            if current_group:
                groups.append(current_group)

            result_lines = []
            for group in groups:
                if len(group) > 1:
                    result_lines.append(" | ".join(group))
                else:
                    result_lines.append(group[0])
            return "\n".join(result_lines)

        if total <= 20:
            texts = [_page_to_text(doc[i]) for i in range(total)]
            doc.close()
            return "\n\n".join(t for t in texts if t.strip())[:MAX_CHARS]

        # Sampler estratificado: 3 segmentos com budget de chars independente
        # Garante cobertura real de início/meio/fim mesmo em PDFs de 200+ páginas
        n_end_pages = max(1, round(total * 0.30))
        n_start_pages = max(1, round(total * 0.30))
        n_mid_start = n_start_pages
        n_mid_end = total - n_end_pages

        segments = [
            (list(range(0, n_start_pages)),          int(MAX_CHARS * 0.30)),
            (list(range(n_mid_start, n_mid_end)),    int(MAX_CHARS * 0.40)),
            (list(range(n_mid_end, total)),          int(MAX_CHARS * 0.30)),
        ]

        parts = []
        for page_indices, budget in segments:
            seg_chars = 0
            for i in page_indices:
                if seg_chars >= budget:
                    break
                text = _page_to_text(doc[i])
                if not text.strip():
                    continue
                remaining = budget - seg_chars
                parts.append(text[:remaining])
                seg_chars += min(len(text), remaining)

        doc.close()
        return "\n\n".join(p for p in parts if p.strip())[:MAX_CHARS]
    except Exception as e:
        print(f"[PRE_ANALYZE] Erro ao extrair texto do PDF: {e}")
        return ""


async def _identify_products_with_ai(text: str, filename: str) -> list:
    """
    Usa GPT-4o para identificar produtos/tickers em texto de documento financeiro brasileiro.
    Retorna lista com ticker, name, product_type, gestora, cnpj para cada produto.
    """
    if not text.strip():
        return []
    try:
        from openai import OpenAI
        import os as _os
        client = OpenAI(api_key=_os.environ.get("OPENAI_API_KEY"))
        system_prompt = (
            "Você é um analista sênior especializado em identificar produtos financeiros brasileiros em documentos.\n\n"
            "PADRÕES DE TICKER NO BRASIL:\n"
            "- Ações ON/PN: 4 letras + 1 dígito (ex: PETR3, VALE5, ITSA4)\n"
            "- Ações UNIT: 4 letras + 11 (ex: SANB11, CSAN11)\n"
            "- FIIs: 4 letras + 11 (ex: MXRF11, HGLG11, XPML11, VISC11)\n"
            "- ETFs: 4 letras + 11 (ex: BOVA11, IVVB11, SMAL11)\n"
            "- BDRs: 4 letras + 34 ou 35 (ex: AAPL34, MSFT34)\n\n"
            "TIPOS DE INSTRUMENTO VÁLIDOS (use exatamente um destes em product_type):\n"
            "FII, FIA, FIC-FIA, FIDC, CRI, CRA, Debênture, ETF, BDR, Ação, "
            "Fundo Multimercado, Fundo de Renda Fixa, POP, Collar, COE, LCI, LCA, Estruturada\n\n"
            "REGRA FUNDAMENTAL — PRODUTOS ESTRUTURADOS (CRÍTICO):\n"
            "Quando o documento descreve uma OPERAÇÃO ESTRUTURADA (POP, Collar, COE, Fence, "
            "Reverse Convertible, Knock-out, etc.) sobre um ativo-base, o PRODUTO em si é a "
            "ESTRUTURA, NÃO o ativo subjacente. Sinais inequívocos de operação estruturada no texto:\n"
            "  • Termos: 'POP', 'Collar', 'Fence', 'COE', 'estrutura', 'estrutura sobre', 'operação estruturada'\n"
            "  • Termos de opções: 'Compra Put', 'Vende Call', 'strike', 'vencimento', 'protected option'\n"
            "  • Padrões de payoff: 'capital protegido', 'piso de retorno', 'teto de retorno',\n"
            "    'ganho mínimo X% / ganho máximo Y%', 'parâmetro de ganho'\n"
            "Quando QUALQUER um desses sinais estiver presente:\n"
            "  - product_type DEVE ser 'POP', 'Collar', 'COE' ou 'Estruturada' (NUNCA 'Ação'/'ETF'/'FII')\n"
            "  - ticker DEVE refletir a estrutura (ex: 'POP_BEEF3_DEZ28', 'COLLAR_WEGE3_SET29');\n"
            "    se não houver ticker oficial da estrutura, gere um identificador no padrão\n"
            "    '<TIPO>_<UNDERLYING>_<MMMAA>' usando o vencimento se disponível\n"
            "  - name DEVE descrever a estrutura (ex: 'POP sobre BEEF3', 'Collar sobre WEGE3')\n"
            "  - underlying_ticker DEVE conter o ticker do ativo-base (ex: 'BEEF3', 'WEGE3')\n"
            "  - NUNCA emita uma entrada separada só para o ativo-base quando ele aparecer\n"
            "    apenas como subjacente de uma estrutura — a estrutura É o produto identificado\n\n"
            "REGRAS GERAIS:\n"
            "1. NÃO omita produtos que aparecem apenas em tabelas, notas de rodapé ou listas compactas.\n"
            "2. Inclua TODOS os produtos visíveis, mesmo que apareçam uma única vez.\n"
            "3. Se o mesmo produto aparecer com ticker e nome, unifique em uma entrada.\n"
            "4. Para fundos sem ticker explícito, use null em ticker — mas inclua o nome.\n"
            "5. Para ações/ETFs/FIIs/BDRs SEM contexto de estrutura, infira o tipo pelo padrão do ticker.\n"
            "6. Se a gestora ou CNPJ estiver mencionado próximo ao produto, capture-os.\n"
            "7. underlying_ticker só é preenchido para estruturas; deixe null para outros tipos.\n\n"
            "Responda APENAS com JSON válido, sem texto adicional.\n"
            'Formato: {"products": [{"ticker": "MXRF11", "name": "Maxi Renda FII", '
            '"product_type": "FII", "gestora": "XP Asset", "cnpj": null, "underlying_ticker": null}, '
            '{"ticker": "POP_BEEF3_DEZ28", "name": "POP sobre BEEF3", "product_type": "POP", '
            '"gestora": null, "cnpj": null, "underlying_ticker": "BEEF3"}, ...]}'
        )
        user_msg = f"Documento: {filename}\n\nTexto do documento:\n{text}"
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        for key in parsed:
            if isinstance(parsed[key], list):
                return parsed[key]
        return []
    except Exception as e:
        print(f"[PRE_ANALYZE] Erro na análise IA: {e}")
        return []


def _match_products_to_db(db: Session, ai_products: list) -> list:
    """
    Tenta encontrar cada produto identificado pela IA na base de dados.
    Estratégia em cascata:
    1. Ticker exato (maiúsculas)
    2. Ticker ILIKE (case-insensitive, cobre variações de OCR)
    3. Ticker sem sufixo numérico (prefixo de 4 letras, ILIKE)
    4. Nome ILIKE (%nome%)
    Retorna match_confidence: 'exact' | 'ilike' | 'prefix' | 'name' | None
    """
    result = []
    seen_pairs = set()

    for ap in ai_products:
        ticker = (ap.get("ticker") or "").strip().upper() or None
        name = (ap.get("name") or "").strip() or None
        product_type = (ap.get("product_type") or "").strip() or None
        gestora = (ap.get("gestora") or "").strip() or None
        cnpj = (ap.get("cnpj") or "").strip() or None
        underlying_ticker = (ap.get("underlying_ticker") or "").strip().upper() or None

        if not ticker and not name:
            continue

        pair_key = (ticker, (name or "").lower())
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        matched_product = None
        match_confidence = None

        if ticker:
            p = db.query(Product).filter(
                Product.ticker == ticker,
                Product.status == "ativo",
            ).first()
            if p:
                matched_product = p
                match_confidence = "exact"

            if not matched_product:
                p = db.query(Product).filter(
                    Product.ticker.ilike(ticker),
                    Product.status == "ativo",
                ).first()
                if p:
                    matched_product = p
                    match_confidence = "ilike"

            if not matched_product and len(ticker) >= 4:
                ticker_prefix = ticker[:4]
                p = db.query(Product).filter(
                    Product.ticker.ilike(f"{ticker_prefix}%"),
                    Product.status == "ativo",
                ).first()
                if p:
                    matched_product = p
                    match_confidence = "prefix"

        if not matched_product and name and len(name.strip()) >= 3:
            p = db.query(Product).filter(
                Product.name.ilike(f"%{name.strip()}%"),
                Product.status == "ativo",
            ).first()
            if p:
                matched_product = p
                match_confidence = "name"

        if not matched_product and name and len(name.strip()) >= 3:
            import json as _json_alias
            nome_lower = name.strip().lower()
            alias_candidates = db.query(Product).filter(
                Product.name_aliases.isnot(None),
                Product.name_aliases != "[]",
                Product.status == "ativo",
            ).all()
            for prod in alias_candidates:
                try:
                    aliases = _json_alias.loads(prod.name_aliases or "[]")
                except (ValueError, TypeError):
                    aliases = []
                for alias in aliases:
                    if nome_lower in alias.lower() or alias.lower() in nome_lower:
                        matched_product = prod
                        match_confidence = "alias"
                        break
                if matched_product:
                    break

        result.append({
            "ticker": ticker,
            "name": name or (matched_product.name if matched_product else ticker),
            "product_type": product_type,
            "gestora": gestora,
            "cnpj": cnpj,
            "underlying_ticker": underlying_ticker,
            "product_id": matched_product.id if matched_product else None,
            "exists_in_db": matched_product is not None,
            "match_confidence": match_confidence,
            "selected": True,
        })
    return result


def _extract_pdf_text_per_page(file_content: bytes, max_pages: int = 40) -> list:
    """
    Retorna uma lista de (page_index, text_extracted) para até max_pages páginas.
    Usado para detectar páginas com pouco texto extraído (candidatas a Vision pass).
    """
    try:
        import fitz
        doc = fitz.open(stream=file_content, filetype="pdf")
        pages = []
        total = min(len(doc), max_pages)
        for i in range(total):
            try:
                txt = doc[i].get_text("text") or ""
            except Exception:
                txt = ""
            pages.append((i, txt.strip()))
        doc.close()
        return pages
    except Exception as e:
        print(f"[PRE_ANALYZE] Erro ao extrair texto por página: {e}")
        return []


async def _vision_pass_low_confidence_pages(
    file_content: bytes,
    low_conf_page_indices: list,
    max_pages: int = 3,
) -> dict:
    """
    Para páginas com pouco texto extraído, renderiza em 200 DPI e envia para GPT-4o Vision
    solicitando produtos financeiros e dados-chave visíveis em tabelas/gráficos.
    Retorna {"products_found": [...], "key_data_text": "..."}.
    """
    selected = low_conf_page_indices[:max_pages]
    if not selected:
        return {"products_found": [], "key_data_text": ""}

    try:
        import fitz
        import base64 as _b64
        import io as _io
        from openai import OpenAI
        import os as _os
        import json as _json

        client = OpenAI(api_key=_os.environ.get("OPENAI_API_KEY"))
        doc = fitz.open(stream=file_content, filetype="pdf")
        all_products = []
        all_key_data = []

        prompt = (
            "This is a page from a Brazilian financial document. List ALL financial products "
            "mentioned: tickers, fund names, structured product names. Also extract any key "
            "data visible in tables or charts (returns, ratings, terms, prices, CNPJ). "
            'Return ONLY valid JSON: {"products_found": [{"ticker": "XXXX11", "name": "...", '
            '"type": "FII|Ação|ETF|Estruturada|Debênture|Fundo|Outro"}], "key_data_found": "texto livre"}.'
        )

        for page_idx in selected:
            if page_idx >= len(doc):
                continue
            try:
                page = doc[page_idx]
                matrix = fitz.Matrix(200 / 72, 200 / 72)
                pix = page.get_pixmap(matrix=matrix)
                img_bytes = pix.tobytes("png")
                b64 = _b64.b64encode(img_bytes).decode("utf-8")

                resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    temperature=0,
                    max_tokens=1200,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content or "{}"
                parsed = _json.loads(raw)
                found = parsed.get("products_found") or []
                if isinstance(found, list):
                    for p in found:
                        if not isinstance(p, dict):
                            continue
                        all_products.append({
                            "ticker": (p.get("ticker") or "").strip().upper() or None,
                            "name": (p.get("name") or "").strip() or None,
                            "product_type": (p.get("type") or "").strip() or None,
                            "gestora": None,
                            "cnpj": None,
                        })
                kd = parsed.get("key_data_found")
                if isinstance(kd, str) and kd.strip():
                    all_key_data.append(kd.strip())
            except Exception as page_err:
                print(f"[PRE_ANALYZE][VISION] Falha em página {page_idx}: {page_err}")
                continue

        doc.close()
        return {
            "products_found": all_products,
            "key_data_text": "\n".join(all_key_data),
        }
    except Exception as e:
        print(f"[PRE_ANALYZE][VISION] Erro geral: {e}")
        return {"products_found": [], "key_data_text": ""}


async def _extract_deep_key_info(text: str, identified_products: list) -> list:
    """
    Segunda chamada GPT-4o: para cada produto identificado, extrai informações estruturadas
    de tese, retorno, prazo, risco, emissor, rating, aplicação mínima, liquidez e destaques.
    Retorna lista de objetos (um por produto) com chave `ticker` como pivô.
    """
    if not text.strip() or not identified_products:
        return []
    try:
        from openai import OpenAI
        import os as _os
        import json as _json

        client = OpenAI(api_key=_os.environ.get("OPENAI_API_KEY"))

        product_list_str = _json.dumps(
            [
                {
                    "ticker": p.get("ticker"),
                    "name": p.get("name"),
                    "product_type": p.get("product_type"),
                }
                for p in identified_products
            ],
            ensure_ascii=False,
        )

        system_prompt = (
            "You are a financial document analyst specializing in Brazilian variable "
            "income products. Extract detailed structured information."
        )
        user_prompt = (
            f"For each of the following products identified in this document: {product_list_str}\n"
            "Extract all available information you can find. For each product return a JSON "
            "object with these fields (use null if not found):\n"
            "{\n"
            '  "ticker": string,\n'
            '  "investment_thesis": string (the main investment rationale, up to 3 sentences),\n'
            '  "expected_return": string (ex: "IPCA + 6% a.a.", "12% a.a.", "DY ~11%"),\n'
            '  "investment_term": string (ex: "24 meses", "longo prazo", "sem vencimento"),\n'
            '  "main_risk": string (primary risk factor),\n'
            '  "issuer_or_manager": string,\n'
            '  "rating": string or null,\n'
            '  "minimum_investment": string or null,\n'
            '  "liquidity": string or null,\n'
            '  "additional_highlights": array of strings (up to 3 key bullet points)\n'
            "}\n"
            "If a field truly does not appear in the document, return null for that field. "
            'Respond ONLY with a JSON object in the shape: {"products": [ ... ]}. Use Portuguese (pt-BR) '
            "in all string values.\n\n"
            f"Document text:\n{text}"
        )

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=2500,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        for key in parsed:
            if isinstance(parsed[key], list):
                return parsed[key]
        return []
    except Exception as e:
        print(f"[PRE_ANALYZE][DEEP_INFO] Erro: {e}")
        return []


async def _detect_material_nature(text: str) -> str:
    """
    Classifica a natureza de um material que não tem produtos identificados.
    Retorna uma de: 'educacional', 'macro', 'regulatorio', 'outro'.
    """
    if not text.strip():
        return "outro"
    try:
        from openai import OpenAI
        import os as _os
        client = OpenAI(api_key=_os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classifique a natureza de um documento financeiro que NÃO menciona produtos "
                        "específicos (tickers, fundos). Responda APENAS com uma das palavras: "
                        "'educacional' (conceitos, glossário, treinamento), 'macro' (análise de mercado, "
                        "cenário, PIB, juros), 'regulatorio' (norma, CVM, compliance) ou 'outro'."
                    ),
                },
                {"role": "user", "content": text[:6000]},
            ],
            temperature=0,
            max_tokens=10,
        )
        raw = (resp.choices[0].message.content or "outro").strip().lower()
        if raw in ("educacional", "macro", "regulatorio", "outro"):
            return raw
        return "outro"
    except Exception as e:
        print(f"[PRE_ANALYZE][NATURE] Erro: {e}")
        return "outro"


def _merge_key_info_into_product(
    db: Session,
    product: "Product",
    extracted_info: dict,
    material_id: Optional[int] = None,
) -> bool:
    """
    Faz MERGE ACUMULATIVO entre key_info do produto e info extraída.

    Estratégia "soma" (não destrutiva):
      - Listas (additional_highlights): união case-insensitive sem duplicar.
      - Campos textuais (investment_thesis, main_risk, etc.): preserva o
        valor PRIMÁRIO existente; se um valor diferente chegar, registra-o
        em `key_info["key_info_history"]` com tag de origem
        ({field, value, material_id, extracted_at}). Quando o campo
        primário está vazio, adota diretamente o novo valor.
      - Campos de identidade (cnpj, underlying_ticker): se vazios, preenche;
        se conflitarem, sobrescreve e emite warning no log.

    Retorna True se algo foi alterado.
    """
    if not product or not isinstance(extracted_info, dict):
        return False
    import json as _json
    from datetime import datetime as _dt
    try:
        current = _json.loads(product.key_info) if product.key_info else {}
        if not isinstance(current, dict):
            current = {}
    except Exception:
        current = {}

    history = current.get("key_info_history")
    if not isinstance(history, list):
        history = []

    changed = False
    text_fields = [
        "investment_thesis", "expected_return", "investment_term", "main_risk",
        "issuer_or_manager", "rating", "minimum_investment", "liquidity",
    ]
    list_fields = ["additional_highlights"]
    identity_fields = ["cnpj", "underlying_ticker"]
    now_iso = _dt.utcnow().isoformat() + "Z"

    def _push_history(field: str, value):
        history.append({
            "field": field,
            "value": value,
            "material_id": material_id,
            "extracted_at": now_iso,
        })

    for field in text_fields:
        new_val = extracted_info.get(field)
        if new_val in (None, "", [], {}):
            continue
        if not isinstance(new_val, str):
            new_val = str(new_val)
        new_val = new_val.strip()
        if not new_val:
            continue
        cur_val = current.get(field)
        cur_str = (cur_val or "").strip() if isinstance(cur_val, str) else ""
        if not cur_str:
            current[field] = new_val
            changed = True
        elif cur_str != new_val:
            already_in_history = any(
                isinstance(h, dict)
                and h.get("field") == field
                and (h.get("value") or "").strip() == new_val
                for h in history
            )
            if not already_in_history:
                _push_history(field, new_val)
                changed = True

    for field in list_fields:
        new_val = extracted_info.get(field)
        if not isinstance(new_val, list) or not new_val:
            continue
        cur_val = current.get(field)
        if not isinstance(cur_val, list):
            cur_val = []
        seen = {(item or "").strip().lower() for item in cur_val if isinstance(item, str)}
        merged = list(cur_val)
        added_any = False
        for item in new_val:
            if not isinstance(item, str):
                continue
            key = item.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item.strip())
            added_any = True
        if added_any:
            current[field] = merged
            changed = True

    for field in identity_fields:
        new_val = extracted_info.get(field)
        if new_val in (None, "", [], {}):
            continue
        if isinstance(new_val, str):
            new_val = new_val.strip()
            if not new_val:
                continue
        cur_val = current.get(field)
        if cur_val in (None, "", [], {}):
            current[field] = new_val
            changed = True
        elif isinstance(cur_val, str) and isinstance(new_val, str) and cur_val.strip() != new_val.strip():
            print(
                f"[KEY_INFO][CONFLITO] Produto id={product.id} ticker={product.ticker} "
                f"campo de identidade '{field}' conflito: '{cur_val}' → '{new_val}' "
                f"(material_id={material_id}). Sobrescrevendo."
            )
            _push_history(field, cur_val)
            current[field] = new_val
            changed = True

    if history:
        current["key_info_history"] = history

    if changed:
        product.key_info = _json.dumps(current, ensure_ascii=False)
    return changed


@router.get("/search")
async def products_search(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Busca leve de produtos por ticker ou nome (Change 3b)."""
    if current_user.role not in ("admin", "gestao_rv", "broker"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    q = (q or "").strip()
    if not q:
        return {"products": []}

    qnorm = q.upper()
    rows = db.query(Product).filter(
        Product.status == "ativo",
        or_(
            Product.ticker.ilike(f"%{qnorm}%"),
            Product.name.ilike(f"%{q}%"),
        ),
    ).order_by(Product.name.asc()).limit(max(1, min(limit, 50))).all()

    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker,
                "product_type": p.product_type,
                "manager": p.manager,
            }
            for p in rows
        ]
    }


@router.post("/pre-analyze-upload")
async def pre_analyze_upload(
    files: list[UploadFile] = File(...),
    material_type: str = Form("one_page"),
    tags: str = Form("[]"),
    valid_from: str = Form(None),
    valid_until: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fase 1 do SmartUpload inteligente: salva PDFs, cria materiais e analisa produtos via IA.
    Retorna os materiais criados e os produtos identificados para revisão humana.
    NÃO adiciona à fila de processamento. O usuário deve confirmar via /link-and-queue.
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    import json as _json
    from database.models import ProcessingStatus

    parsed_tags = []
    try:
        parsed_tags = _json.loads(tags) if tags else []
    except Exception:
        parsed_tags = []

    parsed_valid_from = None
    parsed_valid_until = None
    if valid_from:
        try:
            parsed_valid_from = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
        except ValueError:
            pass
    if valid_until:
        try:
            parsed_valid_until = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
        except ValueError:
            pass

    results = []

    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            results.append({
                "filename": file.filename,
                "error": "Apenas PDFs são suportados",
                "material_id": None,
                "identified_products": [],
            })
            continue

        content = await file.read()
        name = file.filename.replace(".pdf", "").replace(".PDF", "")

        import hashlib as _hl
        file_hash = _hl.sha256(content).hexdigest()
        existing_dup = db.query(Material).filter(
            Material.file_hash == file_hash,
            Material.file_hash.isnot(None),
            Material.processing_status == "success",
        ).first()
        is_duplicate = existing_dup is not None
        if is_duplicate:
            material = existing_dup
            # Para duplicatas, o arquivo pode ter sumido do disco (ambiente efêmero).
            # Como o conteúdo está em memória agora, salvar em disco imediatamente
            # para que link-and-queue encontre sem precisar restaurar do BYTEA.
            if not material.source_file_path or not os.path.exists(material.source_file_path):
                try:
                    dup_filename = f"{uuid.uuid4()}.pdf"
                    dup_file_path = os.path.join(UPLOAD_DIR_QUEUE, dup_filename)
                    with open(dup_file_path, "wb") as fh:
                        fh.write(content)
                    material.source_file_path = dup_file_path
                    db.commit()
                    print(
                        f"[PRE_ANALYZE] Duplicata material_id={material.id}: "
                        f"arquivo salvo em disco: {dup_file_path}"
                    )
                except Exception as dup_save_err:
                    print(
                        f"[PRE_ANALYZE] Aviso: falha ao salvar duplicata em disco "
                        f"(material_id={material.id}): {dup_save_err}"
                    )
        else:
            ps_value = ProcessingStatus.PENDING.value if hasattr(ProcessingStatus, "PENDING") else "pending"
            material = Material(
                product_id=None,
                material_type=material_type,
                name=name,
                valid_from=parsed_valid_from,
                valid_until=parsed_valid_until,
                tags=_json.dumps(parsed_tags),
                publish_status="rascunho",
                processing_status=ps_value,
                file_hash=file_hash,
            )
            db.add(material)
            db.commit()
            db.refresh(material)

            unique_filename = f"{uuid.uuid4()}.pdf"
            file_path = os.path.join(UPLOAD_DIR_QUEUE, unique_filename)
            with open(file_path, "wb") as fh:
                fh.write(content)

            _save_file_to_db(db, material.id, file.filename or "documento.pdf", content)

            material.source_file_path = file_path
            db.commit()

        text = _extract_pdf_text_for_analysis(content, max_pages=5)
        ai_products = await _identify_products_with_ai(text, file.filename)

        # 1b. Vision pass para páginas com texto extraído < 200 chars
        try:
            per_page = _extract_pdf_text_per_page(content, max_pages=40)
            low_conf_indices = [idx for idx, t in per_page if len(t or "") < 200]
            vision_result = {"products_found": [], "key_data_text": ""}
            if low_conf_indices:
                vision_result = await _vision_pass_low_confidence_pages(
                    content, low_conf_indices, max_pages=3
                )
            if vision_result.get("products_found"):
                existing_tickers = {
                    ((p.get("ticker") or "").strip().upper())
                    for p in ai_products
                }
                for vp in vision_result["products_found"]:
                    tk = (vp.get("ticker") or "").strip().upper()
                    if tk and tk in existing_tickers:
                        continue
                    if not vp.get("ticker") and not vp.get("name"):
                        continue
                    ai_products.append(vp)
                    if tk:
                        existing_tickers.add(tk)
        except Exception as vision_err:
            print(f"[PRE_ANALYZE][VISION] Erro no passe visual: {vision_err}")

        identified = _match_products_to_db(db, ai_products)

        # 1a. Deep key_info extraction (segunda chamada) + MERGE em Product.key_info
        try:
            if identified:
                deep_infos = await _extract_deep_key_info(text, identified)
                deep_by_ticker = {}
                for di in deep_infos:
                    if not isinstance(di, dict):
                        continue
                    t_key = (di.get("ticker") or "").strip().upper()
                    if t_key:
                        deep_by_ticker[t_key] = di

                for idp in identified:
                    tk = (idp.get("ticker") or "").strip().upper()
                    info = deep_by_ticker.get(tk) if tk else None
                    if info:
                        idp["deep_info"] = {
                            k: v for k, v in info.items() if k != "ticker"
                        }
                        pid = idp.get("matched_product_id") or idp.get("product_id")
                        if pid:
                            prod = db.query(Product).filter(Product.id == pid).first()
                            if prod:
                                merge_payload = dict(info)
                                if idp.get("underlying_ticker"):
                                    merge_payload["underlying_ticker"] = idp["underlying_ticker"]
                                if idp.get("cnpj") and not merge_payload.get("cnpj"):
                                    merge_payload["cnpj"] = idp["cnpj"]
                                _merge_key_info_into_product(
                                    db, prod, merge_payload, material_id=material.id
                                )
                db.commit()
        except Exception as deep_err:
            print(f"[PRE_ANALYZE][DEEP_INFO] Erro no deep extract: {deep_err}")

        # 1c. Auto-detecção de material sem produtos
        no_products_detected = False
        material_nature_guess = None
        confident_products = [
            p for p in identified
            if (p.get("match_confidence") in ("exact", "ilike", "alias"))
            or (p.get("ticker"))
        ]
        if not confident_products:
            no_products_detected = True
            try:
                material_nature_guess = await _detect_material_nature(text)
            except Exception:
                material_nature_guess = "outro"

        import json as _json2
        material.ai_product_analysis = _json2.dumps(identified, ensure_ascii=False)
        db.commit()

        results.append({
            "filename": file.filename,
            "material_id": material.id,
            "identified_products": identified,
            "no_products_detected": no_products_detected,
            "material_nature_guess": material_nature_guess,
            "error": None,
            "duplicate": is_duplicate,
            "existing_material_name": material.name if is_duplicate else None,
        })

    return {
        "success": True,
        "materials": results,
    }


@router.post("/find-missing-product")
async def find_missing_product(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change 2b — Vision profundo sobre TODAS as páginas do PDF buscando um produto
    que o usuário alega não ter sido identificado.
    Body JSON: { material_id, description, existing_products: [tickers] }
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    import json as _json
    import base64 as _b64
    import os as _os
    from openai import OpenAI

    body = await request.json()
    material_id = body.get("material_id")
    description = (body.get("description") or "").strip()
    existing_products = body.get("existing_products") or []

    if not material_id or not description:
        raise HTTPException(status_code=400, detail="material_id e description são obrigatórios")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    # Carrega PDF: prioriza material_files (fonte de verdade) → fallback source_file_path
    content = None
    from sqlalchemy import text as _sa_text
    db_file = db.execute(
        _sa_text("SELECT file_data FROM material_files WHERE material_id = :mid"),
        {"mid": material_id},
    ).fetchone()
    if db_file:
        content = bytes(db_file[0])
    elif material.source_file_path and os.path.exists(material.source_file_path):
        with open(material.source_file_path, "rb") as fh:
            content = fh.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo PDF não encontrado para este material")

    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Falha ao abrir PDF: {e}")

    client = OpenAI(api_key=_os.environ.get("OPENAI_API_KEY"))

    existing_str = ", ".join([str(t) for t in existing_products if t]) or "nenhum"
    prompt_text = (
        f"The user says this product was not found in the document: '{description}'. "
        f"Previously identified products: {existing_str}. "
        "Search carefully through this page (inclui tabelas, rodapés, cabeçalhos, gráficos, apêndices). "
        f"Find any information about '{description}' or products matching this description. "
        "If found, extract: ticker, name, product_type (FII/Ação/ETF/Estruturada/Debênture/Fundo/Outro), "
        "gestora, investment_thesis, expected_return, investment_term, main_risk, rating, "
        "minimum_investment, liquidity. If not found at all, say so explicitly. "
        'Return ONLY valid JSON: {"found": boolean, "product": {...} or null, '
        '"page_has_match": boolean}. Use Portuguese for values.'
    )

    found_product = None
    found_on_pages: list[int] = []

    try:
        total_pages = len(doc)
        for idx in range(total_pages):
            try:
                page = doc[idx]
                matrix = fitz.Matrix(150 / 72, 150 / 72)
                pix = page.get_pixmap(matrix=matrix)
                img_bytes = pix.tobytes("png")
                b64 = _b64.b64encode(img_bytes).decode("utf-8")

                resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                    temperature=0,
                    max_tokens=1500,
                    response_format={"type": "json_object"},
                )
                raw = resp.choices[0].message.content or "{}"
                parsed = _json.loads(raw)

                if parsed.get("found") and isinstance(parsed.get("product"), dict):
                    found_on_pages.append(idx + 1)
                    if not found_product:
                        found_product = parsed["product"]
                    else:
                        # Merge de info complementar encontrada em páginas posteriores
                        for k, v in parsed["product"].items():
                            if v in (None, "", [], {}):
                                continue
                            if not found_product.get(k):
                                found_product[k] = v
            except Exception as page_err:
                print(f"[FIND_MISSING] erro página {idx}: {page_err}")
                continue
    finally:
        doc.close()

    if not found_product:
        return {
            "found": False,
            "message": "Produto não encontrado no material",
            "pages_scanned": total_pages,
        }

    # Cascade match do produto encontrado
    ai_candidate = [{
        "ticker": (found_product.get("ticker") or "").strip().upper() or None,
        "name": found_product.get("name"),
        "product_type": found_product.get("product_type"),
        "gestora": found_product.get("gestora"),
        "cnpj": found_product.get("cnpj"),
    }]
    matched = _match_products_to_db(db, ai_candidate)
    card = matched[0] if matched else {
        "ticker": ai_candidate[0]["ticker"],
        "name": ai_candidate[0]["name"],
        "product_type": ai_candidate[0]["product_type"],
        "gestora": ai_candidate[0]["gestora"],
        "product_id": None,
        "exists_in_db": False,
        "match_confidence": None,
        "selected": True,
    }

    # Inclui deep_info retornado pela IA
    deep_info = {
        k: found_product.get(k)
        for k in [
            "investment_thesis", "expected_return", "investment_term", "main_risk",
            "issuer_or_manager", "rating", "minimum_investment", "liquidity",
            "additional_highlights",
        ]
        if found_product.get(k)
    }
    if deep_info:
        card["deep_info"] = deep_info

    return {
        "found": True,
        "product": card,
        "found_on_pages": found_on_pages,
        "pages_scanned": total_pages,
    }


@router.post("/analyze-pdf-products")
async def analyze_pdf_products(
    request: Request,
    material_id: int = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Alias/contrato principal para análise de produtos em PDF.
    - Se `material_id` fornecido: retorna análise cacheada (sem re-processamento).
    - Se `file` fornecido: extrai texto e analisa via IA (sem persistir material).
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    import json as _json

    if material_id:
        mat = db.query(Material).filter(Material.id == material_id).first()
        if not mat:
            raise HTTPException(status_code=404, detail="Material não encontrado")
        cached = mat.ai_product_analysis
        if cached:
            try:
                identified = _json.loads(cached)
                return {"success": True, "material_id": material_id, "identified_products": identified, "cached": True}
            except Exception:
                pass
        if mat.source_file_path and os.path.exists(mat.source_file_path):
            with open(mat.source_file_path, "rb") as fh:
                content = fh.read()
        else:
            from sqlalchemy import text as _sa_text
            db_file = db.execute(
                _sa_text("SELECT file_data FROM material_files WHERE material_id = :mid"),
                {"mid": material_id}
            ).fetchone()
            if not db_file:
                raise HTTPException(status_code=400, detail="Arquivo PDF não encontrado para este material")
            content = bytes(db_file[0])

        text = _extract_pdf_text_for_analysis(content, max_pages=5)
        ai_products = await _identify_products_with_ai(text, mat.name or "")
        identified = _match_products_to_db(db, ai_products)
        mat.ai_product_analysis = _json.dumps(identified, ensure_ascii=False)
        db.commit()
        return {"success": True, "material_id": material_id, "identified_products": identified, "cached": False}

    if file:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Apenas PDFs são suportados")
        content = await file.read()
        text = _extract_pdf_text_for_analysis(content, max_pages=5)
        ai_products = await _identify_products_with_ai(text, file.filename)
        identified = _match_products_to_db(db, ai_products)
        return {"success": True, "identified_products": identified, "cached": False}

    raise HTTPException(status_code=400, detail="Forneça material_id ou file")


@router.post("/{material_id}/link-and-queue")
async def link_products_and_queue(
    material_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fase 2 do SmartUpload: vincula produtos confirmados via MaterialProductLink e enfileira para processamento.
    Body JSON:
      confirmed_products: [{product_id: int|null, name: str, ticker: str}]
      primary_product_id: int|null
      file_path: str (path salvo na fase 1)
    """
    if current_user.role not in ["admin", "gestao_rv", "broker"]:
        raise HTTPException(status_code=403, detail="Acesso negado")

    from database.models import MaterialProductLink
    from services.upload_queue import upload_queue, UploadQueueItem

    body = await request.json()
    confirmed_products = body.get("confirmed_products", [])
    primary_product_id = body.get("primary_product_id")
    products_with_info = body.get("products_with_info", []) or []
    is_conceptual_material = bool(body.get("is_conceptual_material", False))

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    file_path = getattr(material, "source_file_path", None)
    if not file_path or not os.path.exists(file_path):
        # Arquivo não existe no disco (ambiente efêmero ou duplicata de sessão anterior).
        # Tenta restaurar da tabela material_files (BYTEA — fonte de verdade persistente).
        print(
            f"[LINK_QUEUE] source_file_path ausente ou inexistente para material {material_id} "
            f"(path={file_path!r}). Tentando restaurar do banco..."
        )
        restored = _restore_pdf_from_db(db, material_id)
        if restored:
            file_path = restored
            material.source_file_path = restored
            db.commit()
            print(f"[LINK_QUEUE] PDF restaurado com sucesso: {restored}")
        else:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Arquivo PDF não encontrado para processamento e não há cópia no banco. "
                    "Refaça o upload do arquivo."
                ),
            )

    # MERGE ACUMULATIVO do key_info editado pelo usuário (Task #113)
    # Usa _merge_key_info_into_product para preservar histórico ao invés de sobrescrever.
    if products_with_info:
        for entry in products_with_info:
            try:
                pid = entry.get("product_id")
                edited_info = entry.get("key_info") or {}
                if not pid or not isinstance(edited_info, dict):
                    continue
                prod = db.query(Product).filter(Product.id == pid).first()
                if not prod:
                    continue
                _merge_key_info_into_product(
                    db, prod, edited_info, material_id=material_id
                )
            except Exception as merge_err:
                print(f"[LINK_QUEUE] Erro ao mesclar key_info: {merge_err}")
        db.commit()

    # Change 2c — material conceitual: pula vinculação de produtos, enfileira mesmo assim
    if is_conceptual_material:
        material.product_id = None
        db.query(MaterialProductLink).filter(
            MaterialProductLink.material_id == material_id
        ).delete()
        db.commit()

        upload_id = str(uuid.uuid4())
        queue_item = UploadQueueItem(
            upload_id=upload_id,
            file_path=file_path,
            filename=material.name or f"material_{material_id}",
            material_id=material_id,
            name=material.name or f"material_{material_id}",
            user_id=current_user.id,
            material_type=material.material_type or "outro",
            categories=[],
            tags=[],
            selected_product_id=None,
        )
        upload_queue.add(queue_item)

        print(
            f"[LINK_QUEUE] Material {material_id} marcado como conceitual "
            f"(sem produtos) e adicionado à fila (upload_id={upload_id})"
        )
        return {
            "success": True,
            "upload_id": upload_id,
            "material_id": material_id,
            "linked_product_ids": [],
            "primary_product_id": None,
            "is_conceptual_material": True,
            "message": "Material conceitual adicionado à fila (sem produtos vinculados)",
        }

    created_products = []
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
                product_type_raw = (cp.get("product_type") or "").strip() or None
                _pt_alias = {
                    "acao": "Ação", "ação": "Ação",
                    "fii": "FII",
                    "fia": "FIA",
                    "fic-fia": "FIC-FIA", "fic fia": "FIC-FIA",
                    "etf": "ETF", "bdr": "BDR",
                    "cri": "CRI", "cra": "CRA",
                    "debenture": "Debênture", "debênture": "Debênture",
                    "fundo multimercado": "Fundo Multimercado",
                    "fundo de renda fixa": "Fundo de Renda Fixa",
                    "pop": "POP", "collar": "Collar", "coe": "COE",
                    "estruturada": "Estruturada", "estruturado": "Estruturada",
                    "lci": "LCI", "lca": "LCA", "fidc": "FIDC",
                }
                product_type = (
                    _pt_alias.get(product_type_raw.lower(), product_type_raw)
                    if product_type_raw else None
                )
                gestora = (cp.get("gestora") or "").strip() or None

                category_map = {
                    "FII": "fii", "FIA": "fundo_acoes", "FIC-FIA": "fundo_acoes",
                    "ETF": "etf", "BDR": "bdr", "Ação": "acao", "Acao": "acao",
                    "CRI": "renda_fixa", "CRA": "renda_fixa",
                    "Debênture": "renda_fixa", "Debenture": "renda_fixa",
                    "Fundo Multimercado": "multimercado",
                    "Fundo de Renda Fixa": "renda_fixa",
                    "POP": "estruturada", "Collar": "estruturada",
                    "COE": "estruturada", "Estruturada": "estruturada",
                    "LCI": "renda_fixa", "LCA": "renda_fixa",
                    "FIDC": "renda_fixa",
                }
                category = category_map.get(product_type, "") if product_type else ""

                type_to_db_field = {
                    "FII": "fii", "FIA": "fundo_acoes", "FIC-FIA": "fundo_acoes",
                    "ETF": "etf", "BDR": "bdr", "Ação": "acao", "Acao": "acao",
                    "CRI": "debenture", "CRA": "debenture",
                    "Debênture": "debenture", "Debenture": "debenture",
                    "Fundo Multimercado": "outro", "Fundo de Renda Fixa": "outro",
                    "POP": "estruturada", "Collar": "estruturada", "COE": "estruturada",
                    "Estruturada": "estruturada",
                    "LCI": "outro", "LCA": "outro", "FIDC": "outro",
                }
                product_type_db = type_to_db_field.get(product_type, "outro") if product_type else None

                cnpj = (cp.get("cnpj") or "").strip() or None
                underlying_ticker = (cp.get("underlying_ticker") or "").strip().upper() or None
                deep = cp.get("deep_info") if isinstance(cp.get("deep_info"), dict) else {}

                # Fallback (Task #113): se frontend não enviou deep_info, recupera
                # de material.ai_product_analysis por ticker/nome.
                if not deep:
                    try:
                        import json as _json_fb
                        raw = getattr(material, "ai_product_analysis", None)
                        if raw:
                            analysis = _json_fb.loads(raw) if isinstance(raw, str) else raw
                            candidates = []
                            if isinstance(analysis, dict):
                                candidates = (
                                    analysis.get("identified_products")
                                    or analysis.get("products")
                                    or []
                                )
                            elif isinstance(analysis, list):
                                candidates = analysis
                            ticker_up = (ticker or "").upper()
                            name_low = (name or "").lower()
                            for item in candidates:
                                if not isinstance(item, dict):
                                    continue
                                it_tk = (item.get("ticker") or "").upper()
                                it_nm = (item.get("name") or "").lower()
                                if (ticker_up and it_tk == ticker_up) or (
                                    name_low and it_nm == name_low
                                ):
                                    di = item.get("deep_info")
                                    if isinstance(di, dict) and di:
                                        deep = di
                                        print(
                                            f"[LINK_QUEUE][FALLBACK] deep_info recuperado de "
                                            f"material.ai_product_analysis para ticker={ticker_up}"
                                        )
                                    break
                    except Exception as fb_err:
                        print(f"[LINK_QUEUE][FALLBACK] Erro ao ler ai_product_analysis: {fb_err}")

                key_info_dict = {}
                for fld in (
                    "investment_thesis", "expected_return", "investment_term",
                    "main_risk", "issuer_or_manager", "rating",
                    "minimum_investment", "liquidity",
                ):
                    val = deep.get(fld) if deep else None
                    if isinstance(val, str):
                        val = val.strip()
                    if val:
                        key_info_dict[fld] = val
                hl = deep.get("additional_highlights") if deep else None
                if isinstance(hl, list):
                    cleaned = [str(item).strip() for item in hl if isinstance(item, str) and item.strip()]
                    if cleaned:
                        key_info_dict["additional_highlights"] = cleaned
                if cnpj:
                    key_info_dict["cnpj"] = cnpj
                if underlying_ticker:
                    key_info_dict["underlying_ticker"] = underlying_ticker

                import json as _json_inner
                new_p = Product(
                    name=name or ticker,
                    ticker=ticker,
                    manager=gestora,
                    product_type=product_type_db,
                    categories=_json_inner.dumps([category] if category else []),
                    key_info=_json_inner.dumps(key_info_dict, ensure_ascii=False) if key_info_dict else None,
                    description=f"Criado automaticamente via SmartUpload. Tipo: {product_type or 'não identificado'}.",
                    status="ativo",
                )
                db.add(new_p)
                db.flush()
                pid = new_p.id
                print(
                    f"[LINK_QUEUE] Produto criado id={pid}: {name or ticker} "
                    f"(ticker={ticker}, tipo={product_type}, underlying={underlying_ticker}, "
                    f"key_info_fields={list(key_info_dict.keys())})"
                )

        if pid:
            created_products.append(pid)

    if not primary_product_id and created_products:
        primary_product_id = created_products[0]

    if not primary_product_id and not created_products:
        raise HTTPException(
            status_code=400,
            detail="Selecione pelo menos um produto para vincular ao material antes de processar."
        )

    if primary_product_id:
        material.product_id = primary_product_id

    db.query(MaterialProductLink).filter(
        MaterialProductLink.material_id == material_id
    ).delete()

    seen_ids = set()
    if primary_product_id:
        seen_ids.add(primary_product_id)

    for pid in created_products:
        if pid == primary_product_id:
            continue
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        link = MaterialProductLink(
            material_id=material_id,
            product_id=pid,
            excluded_from_committee=False,
        )
        db.add(link)

    db.commit()

    upload_id = str(uuid.uuid4())
    queue_item = UploadQueueItem(
        upload_id=upload_id,
        file_path=file_path,
        filename=material.name or f"material_{material_id}",
        material_id=material_id,
        name=material.name or f"material_{material_id}",
        user_id=current_user.id,
        material_type=material.material_type or "outro",
        categories=[],
        tags=[],
        selected_product_id=primary_product_id,
    )
    upload_queue.add(queue_item)

    print(
        f"[LINK_QUEUE] Material {material_id} vinculado a {len(created_products)} produto(s) "
        f"e adicionado à fila (upload_id={upload_id})"
    )

    return {
        "success": True,
        "upload_id": upload_id,
        "material_id": material_id,
        "linked_product_ids": list(seen_ids),
        "primary_product_id": primary_product_id,
        "message": f"Material vinculado a {len(seen_ids)} produto(s) e adicionado à fila",
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


@router.post("/materials/{material_id}/reassign-product")
async def reassign_material_product(
    material_id: int,
    target_product_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "gestor"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem reassociar materiais")

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material não encontrado")

    target_product = db.query(Product).filter(Product.id == target_product_id).first()
    if not target_product:
        raise HTTPException(status_code=404, detail="Produto de destino não encontrado")

    old_product_name = material.product.name if material.product else "N/A"
    material.product_id = target_product_id
    db.commit()

    from services.product_ingestor import get_product_ingestor
    ingestor = get_product_ingestor()
    result = ingestor.index_approved_blocks(
        material_id=material_id,
        product_name=target_product.name,
        product_ticker=target_product.ticker,
        db=db
    )
    reindexed_blocks = result.get("indexed_count", 0)

    return {
        "success": True,
        "message": f"Material '{material.name}' reassociado de '{old_product_name}' para '{target_product.name}'",
        "reindexed_blocks": reindexed_blocks
    }


@router.post("/admin/backfill-material-files")
async def backfill_material_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Popula material_files para materiais que têm source_file_path mas não têm MaterialFile."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas admins podem executar backfill")

    from sqlalchemy import and_

    materials_without_mf = (
        db.query(Material)
        .outerjoin(MaterialFile, MaterialFile.material_id == Material.id)
        .filter(
            and_(
                MaterialFile.id.is_(None),
                Material.source_file_path.isnot(None),
                Material.source_file_path != ""
            )
        )
        .all()
    )

    from services.product_ingestor import _ensure_material_file

    backfilled = 0
    skipped = 0
    errors = []

    for mat in materials_without_mf:
        try:
            if not mat.source_file_path or not os.path.exists(mat.source_file_path):
                skipped += 1
                continue

            _ensure_material_file(
                db=db,
                material_id=mat.id,
                pdf_path=mat.source_file_path,
                filename=mat.source_filename or os.path.basename(mat.source_file_path)
            )
            backfilled += 1
        except Exception as e:
            errors.append({"material_id": mat.id, "error": str(e)})
            print(f"[BACKFILL] Erro para material_id={mat.id}: {e}")

    return {
        "success": True,
        "backfilled": backfilled,
        "skipped": skipped,
        "errors": errors,
        "total_candidates": len(materials_without_mf)
    }


@router.post("/admin/backfill-product-data")
async def backfill_product_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Backfill completo: preenche tickers em produtos, publica materiais travados em rascunho,
    e atualiza product_ticker nos embeddings correspondentes.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar")

    import json
    import re
    from sqlalchemy import text

    ticker_pattern = re.compile(r'\b([A-Z]{4})([3-9]|1[0-3])\b')
    results = {"tickers_filled": 0, "materials_published": 0, "embeddings_updated": 0, "details": []}

    products_no_ticker = db.query(Product).filter(
        (Product.ticker.is_(None)) | (Product.ticker == ''),
        Product.status == 'ativo'
    ).all()

    for product in products_no_ticker:
        ticker_found = None

        match = ticker_pattern.search((product.name or "").upper())
        if match:
            ticker_found = f"{match.group(1)}{match.group(2)}"

        if not ticker_found:
            materials = db.query(Material).filter(
                Material.product_id == product.id,
                Material.extracted_metadata.isnot(None)
            ).all()
            for mat in materials:
                try:
                    meta = json.loads(mat.extracted_metadata)
                    t = (meta.get("ticker") or "").strip().upper()
                    if t and len(t) >= 4:
                        ticker_found = t
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

        if ticker_found:
            product.ticker = ticker_found
            db.commit()
            results["tickers_filled"] += 1
            results["details"].append(f"Product '{product.name}' (id={product.id}) → ticker={ticker_found}")

            updated = db.execute(text(
                "UPDATE document_embeddings SET product_ticker = :ticker "
                "WHERE product_name = :pname AND (product_ticker IS NULL OR product_ticker = '')"
            ), {"ticker": ticker_found, "pname": product.name})
            db.commit()
            if updated.rowcount > 0:
                results["embeddings_updated"] += updated.rowcount
                results["details"].append(f"  → {updated.rowcount} embeddings atualizados com ticker={ticker_found}")

    materials_rascunho = db.query(Material).filter(
        Material.publish_status.in_([None, 'rascunho', 'draft'])
    ).all()

    for mat in materials_rascunho:
        pending_count = db.query(ContentBlock).filter(
            ContentBlock.material_id == mat.id,
            ContentBlock.status == ContentBlockStatus.PENDING_REVIEW.value
        ).count()

        total_blocks = db.query(ContentBlock).filter(
            ContentBlock.material_id == mat.id
        ).count()

        if pending_count == 0 and total_blocks > 0:
            mat.publish_status = "publicado"
            db.commit()
            results["materials_published"] += 1
            results["details"].append(f"Material '{mat.name}' (id={mat.id}) publicado ({total_blocks} blocos)")

            product = db.query(Product).filter(Product.id == mat.product_id).first()
            if product:
                updated = db.execute(text(
                    "UPDATE document_embeddings SET publish_status = 'publicado' "
                    "WHERE material_id = :mid AND publish_status IN ('rascunho', 'draft')"
                ), {"mid": str(mat.id)})
                db.commit()
                if updated.rowcount > 0:
                    results["embeddings_updated"] += updated.rowcount

    print(f"[BACKFILL] Tickers: {results['tickers_filled']}, Publicados: {results['materials_published']}, "
          f"Embeddings: {results['embeddings_updated']}")

    return {"success": True, **results}


@router.get("/visual-cache/{block_id}/image")
async def get_visual_cache_image(
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from database.models import VisualCache
    from fastapi.responses import Response
    from datetime import datetime, timezone

    cached = db.query(VisualCache).filter(VisualCache.content_block_id == block_id).first()
    if not cached:
        raise HTTPException(status_code=404, detail="Visual cache not found for this block")

    cached.last_accessed_at = datetime.now(timezone.utc)
    db.commit()

    return Response(
        content=cached.image_data,
        media_type=cached.mime_type,
        headers={"Cache-Control": "public, max-age=3600"}
    )
