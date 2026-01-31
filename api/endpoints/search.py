"""
Endpoint de Busca Global.
Busca com correspondência parcial (ILIKE) em toda a base de conhecimento.
"""
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from pydantic import BaseModel

from database.database import get_db
from database.models import (
    Product, Material, ContentBlock, 
    KnowledgeDocument, WhatsAppScript
)
from api.endpoints.auth import get_current_user

router = APIRouter(prefix="/api/search", tags=["search"])


class ProductSearchResult(BaseModel):
    id: int
    name: str
    ticker: Optional[str] = None
    manager: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    match_field: str
    match_context: Optional[str] = None

    class Config:
        from_attributes = True


class MaterialSearchResult(BaseModel):
    id: int
    product_id: int
    product_name: str
    name: str
    material_type: Optional[str] = None
    match_field: str
    match_context: Optional[str] = None

    class Config:
        from_attributes = True


class ContentBlockSearchResult(BaseModel):
    id: int
    material_id: int
    material_title: str
    product_id: int
    product_name: str
    block_type: Optional[str] = None
    title: Optional[str] = None
    content_preview: str
    match_context: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentSearchResult(BaseModel):
    id: int
    filename: str
    category: Optional[str] = None
    description: Optional[str] = None
    chunk_count: int
    is_indexed: bool
    match_field: str
    match_context: Optional[str] = None

    class Config:
        from_attributes = True


class ScriptSearchResult(BaseModel):
    id: int
    product_id: int
    product_name: str
    title: str
    content_preview: str
    usage_type: Optional[str] = None
    match_context: Optional[str] = None

    class Config:
        from_attributes = True


class GlobalSearchResponse(BaseModel):
    query: str
    total_results: int
    products: List[ProductSearchResult]
    materials: List[MaterialSearchResult]
    content_blocks: List[ContentBlockSearchResult]
    documents: List[DocumentSearchResult]
    scripts: List[ScriptSearchResult]


def extract_match_context(text: str, query: str, context_size: int = 50) -> Optional[str]:
    """Extrai o contexto onde o termo foi encontrado."""
    if not text or not query:
        return None
    
    text_lower = text.lower()
    query_lower = query.lower()
    
    pos = text_lower.find(query_lower)
    if pos == -1:
        return None
    
    start = max(0, pos - context_size)
    end = min(len(text), pos + len(query) + context_size)
    
    context = text[start:end]
    if start > 0:
        context = "..." + context
    if end < len(text):
        context = context + "..."
    
    return context


@router.get("/global", response_model=GlobalSearchResponse)
async def global_search(
    q: str = Query(..., min_length=1, description="Termo de busca"),
    limit: int = Query(20, ge=1, le=100, description="Limite de resultados por categoria"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Busca global em toda a base de conhecimento.
    Retorna resultados organizados por categoria (produtos, materiais, blocos, documentos, scripts).
    Usa ILIKE para correspondência parcial (case-insensitive).
    """
    search_pattern = f"%{q}%"
    
    products_results: List[ProductSearchResult] = []
    materials_results: List[MaterialSearchResult] = []
    blocks_results: List[ContentBlockSearchResult] = []
    documents_results: List[DocumentSearchResult] = []
    scripts_results: List[ScriptSearchResult] = []
    
    products = db.query(Product).filter(
        or_(
            Product.name.ilike(search_pattern),
            Product.ticker.ilike(search_pattern),
            Product.manager.ilike(search_pattern),
            Product.category.ilike(search_pattern),
            Product.description.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    for p in products:
        match_field = "nome"
        match_context = None
        
        if q.lower() in (p.name or "").lower():
            match_field = "nome"
            match_context = p.name
        elif q.lower() in (p.ticker or "").lower():
            match_field = "ticker"
            match_context = p.ticker
        elif q.lower() in (p.manager or "").lower():
            match_field = "gestor"
            match_context = p.manager
        elif q.lower() in (p.category or "").lower():
            match_field = "categoria"
            match_context = p.category
        elif q.lower() in (p.description or "").lower():
            match_field = "descrição"
            match_context = extract_match_context(p.description, q)
        
        products_results.append(ProductSearchResult(
            id=p.id,
            name=p.name,
            ticker=p.ticker,
            manager=p.manager,
            category=p.category,
            description=p.description,
            status=p.status,
            match_field=match_field,
            match_context=match_context
        ))
    
    materials = db.query(Material).join(Product).filter(
        or_(
            Material.name.ilike(search_pattern),
            Material.description.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    for m in materials:
        match_field = "nome"
        match_context = None
        
        if q.lower() in (m.name or "").lower():
            match_field = "nome"
            match_context = m.name
        elif q.lower() in (m.description or "").lower():
            match_field = "descrição"
            match_context = extract_match_context(m.description, q)
        
        materials_results.append(MaterialSearchResult(
            id=m.id,
            product_id=m.product_id,
            product_name=m.product.name if m.product else "Desconhecido",
            name=m.name or f"Material #{m.id}",
            material_type=m.material_type,
            match_field=match_field,
            match_context=match_context
        ))
    
    blocks = db.query(ContentBlock).join(Material).join(Product).filter(
        or_(
            ContentBlock.title.ilike(search_pattern),
            ContentBlock.content.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    for b in blocks:
        match_context = extract_match_context(b.content, q) if b.content else None
        
        blocks_results.append(ContentBlockSearchResult(
            id=b.id,
            material_id=b.material_id,
            material_title=b.material.name if b.material else "Desconhecido",
            product_id=b.material.product_id if b.material else 0,
            product_name=b.material.product.name if b.material and b.material.product else "Desconhecido",
            block_type=b.block_type,
            title=b.title,
            content_preview=b.content[:200] + "..." if b.content and len(b.content) > 200 else b.content or "",
            match_context=match_context
        ))
    
    documents = db.query(KnowledgeDocument).filter(
        or_(
            KnowledgeDocument.filename.ilike(search_pattern),
            KnowledgeDocument.description.ilike(search_pattern),
            KnowledgeDocument.category.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    for d in documents:
        match_field = "arquivo"
        match_context = None
        
        if q.lower() in (d.filename or "").lower():
            match_field = "arquivo"
            match_context = d.filename
        elif q.lower() in (d.category or "").lower():
            match_field = "categoria"
            match_context = d.category
        elif q.lower() in (d.description or "").lower():
            match_field = "descrição"
            match_context = extract_match_context(d.description, q)
        
        documents_results.append(DocumentSearchResult(
            id=d.id,
            filename=d.filename,
            category=d.category,
            description=d.description,
            chunk_count=d.chunks_count or 0,
            is_indexed=d.is_indexed or False,
            match_field=match_field,
            match_context=match_context
        ))
    
    scripts = db.query(WhatsAppScript).join(Product).filter(
        or_(
            WhatsAppScript.title.ilike(search_pattern),
            WhatsAppScript.content.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    for s in scripts:
        match_context = extract_match_context(s.content, q) if s.content else None
        
        scripts_results.append(ScriptSearchResult(
            id=s.id,
            product_id=s.product_id,
            product_name=s.product.name if s.product else "Desconhecido",
            title=s.title,
            content_preview=s.content[:200] + "..." if s.content and len(s.content) > 200 else s.content or "",
            usage_type=s.usage_type,
            match_context=match_context
        ))
    
    total = len(products_results) + len(materials_results) + len(blocks_results) + len(documents_results) + len(scripts_results)
    
    return GlobalSearchResponse(
        query=q,
        total_results=total,
        products=products_results,
        materials=materials_results,
        content_blocks=blocks_results,
        documents=documents_results,
        scripts=scripts_results
    )


@router.get("/quick")
async def quick_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Busca rápida para autocomplete.
    Retorna apenas produtos com correspondência no nome, ticker ou gestor.
    """
    search_pattern = f"%{q}%"
    
    products = db.query(Product).filter(
        or_(
            Product.name.ilike(search_pattern),
            Product.ticker.ilike(search_pattern),
            Product.manager.ilike(search_pattern)
        )
    ).limit(limit).all()
    
    return {
        "query": q,
        "suggestions": [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker,
                "manager": p.manager,
                "category": p.category
            }
            for p in products
        ]
    }


@router.post("/reindex-chroma")
async def reindex_chroma(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Reindexa todos os content_blocks aprovados no ChromaDB.
    Usado para sincronizar a base vetorial com o banco de dados relacional.
    Apenas admin pode executar esta operação.
    """
    from fastapi import HTTPException
    if current_user.role not in ["admin", "gestao_rv"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem reindexar")
    from services.vector_store import get_vector_store
    
    vector_store = get_vector_store()
    
    blocks = db.query(ContentBlock).filter(
        ContentBlock.status == 'approved'
    ).all()
    
    indexed_count = 0
    errors = []
    
    for block in blocks:
        try:
            material = block.material if hasattr(block, 'material') else None
            product = material.product if material and hasattr(material, 'product') else None
            
            valid_until_str = ""
            if material and material.valid_until:
                valid_until_str = material.valid_until.isoformat()
            
            metadata = {
                "block_id": str(block.id),
                "block_type": block.block_type or "text",
                "title": block.title or "",
                "document_title": block.title or (material.name if material else "Documento"),
                "material_id": str(block.material_id) if block.material_id else "",
                "product_id": str(product.id) if product else "",
                "product_name": product.name if product else "",
                "ticker": product.ticker if product else "",
                "source_page": str(block.source_page) if block.source_page else "",
                "version": str(block.current_version) if block.current_version else "1",
                "valid_until": valid_until_str
            }
            
            doc_id = f"block_{block.id}"
            text_content = f"{block.title or ''}\n\n{block.content or ''}"
            
            try:
                vector_store.collection.delete(ids=[doc_id])
            except:
                pass
            
            vector_store.add_document(doc_id, text_content, metadata)
            indexed_count += 1
            
        except Exception as e:
            errors.append({"block_id": block.id, "error": str(e)})
    
    return {
        "success": True,
        "total_blocks": len(blocks),
        "indexed": indexed_count,
        "errors": errors,
        "message": f"Reindexação concluída: {indexed_count} de {len(blocks)} blocos indexados"
    }
