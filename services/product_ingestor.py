"""
Serviço de ingestão de documentos para o CMS de Produtos.
Processa PDFs usando GPT-4 Vision e gera content_blocks estruturados.
Implementa sistema de Lanes: Fast Lane (auto-aprovação) e High-Risk Lane (revisão).
"""
import json
import hashlib
import os
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from services.document_processor import get_document_processor
from services.vector_store import get_vector_store
from database.models import (
    Material, ContentBlock, BlockVersion, PendingReviewItem,
    ContentBlockType, ContentBlockStatus, ContentSourceType
)


HIGH_RISK_KEYWORDS = [
    "taxa", "taxas", "custo", "custos", "rentabilidade", "dy", "dividend",
    "yield", "preço", "price", "cdi", "ipca", "selic", "performance",
    "retorno", "fee", "spread", "anbima", "cota", "cotas", "pgbl", "vgbl",
    "pgto", "pagamento", "ir", "come-cotas", "iof", "tributação"
]


def compute_hash(content: str) -> str:
    """Computa hash SHA-256 do conteúdo."""
    return hashlib.sha256(content.encode()).hexdigest()


def detect_high_risk(content: str, content_type: str) -> Tuple[bool, str, int]:
    """
    Detecta se o conteúdo é de alto risco.
    
    Returns:
        (is_high_risk, reason, confidence_score)
    """
    content_lower = content.lower()
    
    if content_type in ["table", "tabela"]:
        for keyword in HIGH_RISK_KEYWORDS:
            if keyword in content_lower:
                return True, f"Tabela contém '{keyword}'", 70
        if "%" in content:
            return True, "Tabela contém percentuais", 75
        return False, "", 90
    
    if content_type in ["infographic", "grafico", "chart"]:
        return True, "Gráfico requer validação visual", 60
    
    risk_count = sum(1 for kw in HIGH_RISK_KEYWORDS if kw in content_lower)
    has_percentage = "%" in content
    
    if risk_count >= 3 or (risk_count >= 1 and has_percentage):
        return True, f"Texto contém {risk_count} termos de risco", 80
    
    return False, "", 95


def determine_block_type(content_type: str) -> str:
    """Mapeia tipo de conteúdo da análise para tipo de bloco."""
    mapping = {
        "table": ContentBlockType.TABLE.value,
        "infographic": ContentBlockType.CHART.value,
        "chart": ContentBlockType.CHART.value,
        "text": ContentBlockType.TEXT.value,
        "mixed": ContentBlockType.TEXT.value,
        "image_only": ContentBlockType.IMAGE.value
    }
    return mapping.get(content_type, ContentBlockType.TEXT.value)


class ProductIngestor:
    """
    Serviço de ingestão para o CMS de Produtos.
    Converte PDFs em blocos de conteúdo estruturados.
    """
    
    def __init__(self):
        self.doc_processor = get_document_processor()
        self.vector_store = get_vector_store()
    
    def process_pdf_to_blocks(
        self,
        pdf_path: str,
        material_id: int,
        document_title: str,
        db: Session,
        user_id: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Processa um PDF e cria content_blocks no banco de dados.
        
        Implementa sistema de Lanes:
        - Fast Lane: Texto simples é auto-aprovado
        - High-Risk Lane: Tabelas com taxas/custos e gráficos exigem revisão
        
        Returns:
            Dict com estatísticas do processamento
        """
        processed = self.doc_processor.process_pdf(
            pdf_path=pdf_path,
            document_title=document_title,
            progress_callback=progress_callback
        )
        
        if processed.get("error"):
            return {"success": False, "error": processed["error"]}
        
        stats = {
            "total_pages": processed["total_pages"],
            "blocks_created": 0,
            "auto_approved": 0,
            "pending_review": 0,
            "products_detected": processed.get("all_products", [])
        }
        
        block_order = 0
        
        for page in processed.get("pages", []):
            page_num = page.get("page_number", 0)
            content_type = page.get("content_type", "text")
            summary = page.get("summary", "")
            facts = page.get("facts", [])
            raw_data = page.get("raw_data", {})
            
            if content_type == "table" or raw_data.get("tables"):
                tables = raw_data.get("tables", [])
                for i, table in enumerate(tables):
                    table_json = json.dumps(table, ensure_ascii=False)
                    block = self._create_block(
                        material_id=material_id,
                        block_type=ContentBlockType.TABLE.value,
                        title=f"Tabela - Página {page_num}" + (f" ({i+1})" if len(tables) > 1 else ""),
                        content=table_json,
                        source_page=page_num,
                        order=block_order,
                        db=db,
                        user_id=user_id
                    )
                    block_order += 1
                    stats["blocks_created"] += 1
                    
                    if block.status == ContentBlockStatus.AUTO_APPROVED.value:
                        stats["auto_approved"] += 1
                    else:
                        stats["pending_review"] += 1
            
            if content_type == "infographic":
                block = self._create_block(
                    material_id=material_id,
                    block_type=ContentBlockType.CHART.value,
                    title=f"Gráfico - Página {page_num}",
                    content=summary + ("\n\n" + "\n".join(facts) if facts else ""),
                    source_page=page_num,
                    order=block_order,
                    db=db,
                    user_id=user_id
                )
                block_order += 1
                stats["blocks_created"] += 1
                stats["pending_review"] += 1
            
            if facts and content_type not in ["table", "infographic"]:
                text_content = "\n\n".join(facts)
                if summary:
                    text_content = f"{summary}\n\n{text_content}"
                
                block = self._create_block(
                    material_id=material_id,
                    block_type=ContentBlockType.TEXT.value,
                    title=f"Conteúdo - Página {page_num}",
                    content=text_content,
                    source_page=page_num,
                    order=block_order,
                    db=db,
                    user_id=user_id
                )
                block_order += 1
                stats["blocks_created"] += 1
                
                if block.status == ContentBlockStatus.AUTO_APPROVED.value:
                    stats["auto_approved"] += 1
                else:
                    stats["pending_review"] += 1
        
        material = db.query(Material).filter(Material.id == material_id).first()
        if material:
            material.source_file_path = pdf_path
            material.source_filename = os.path.basename(pdf_path)
            db.commit()
        
        return {"success": True, "stats": stats}
    
    def _create_block(
        self,
        material_id: int,
        block_type: str,
        title: str,
        content: str,
        source_page: int,
        order: int,
        db: Session,
        user_id: Optional[int] = None
    ) -> ContentBlock:
        """Cria um ContentBlock com detecção de risco automática."""
        content_hash = compute_hash(content)
        is_high_risk, risk_reason, confidence = detect_high_risk(content, block_type)
        
        if is_high_risk:
            status = ContentBlockStatus.PENDING_REVIEW.value
        else:
            status = ContentBlockStatus.AUTO_APPROVED.value
        
        block = ContentBlock(
            material_id=material_id,
            block_type=block_type,
            title=title,
            content=content,
            content_hash=content_hash,
            source_type=ContentSourceType.PDF_UPLOAD.value,
            source_page=source_page,
            status=status,
            confidence_score=confidence,
            is_high_risk=is_high_risk,
            order=order,
            current_version=1
        )
        
        db.add(block)
        db.flush()
        
        version = BlockVersion(
            block_id=block.id,
            version=1,
            content=content,
            content_hash=content_hash,
            author_id=user_id,
            change_reason="Extração automática de PDF"
        )
        db.add(version)
        
        if is_high_risk:
            review_item = PendingReviewItem(
                block_id=block.id,
                original_content=content,
                extracted_content=content,
                confidence_score=confidence,
                risk_reason=risk_reason
            )
            db.add(review_item)
        
        db.commit()
        return block
    
    def index_approved_blocks(
        self,
        material_id: int,
        product_name: str,
        product_ticker: Optional[str],
        db: Session
    ) -> Dict[str, Any]:
        """
        Indexa blocos aprovados no vector store.
        Só indexa blocos com status APPROVED ou AUTO_APPROVED.
        """
        material = db.query(Material).filter(Material.id == material_id).first()
        if not material:
            return {"success": False, "error": "Material não encontrado"}
        
        blocks = db.query(ContentBlock).filter(
            ContentBlock.material_id == material_id,
            ContentBlock.status.in_([
                ContentBlockStatus.APPROVED.value,
                ContentBlockStatus.AUTO_APPROVED.value
            ])
        ).all()
        
        indexed_count = 0
        
        for block in blocks:
            content_for_indexing = block.content
            if block.block_type == ContentBlockType.TABLE.value:
                try:
                    table_data = json.loads(block.content)
                    text_repr = self._table_to_text(table_data)
                    content_for_indexing = f"Tabela: {block.title}\n{text_repr}"
                except:
                    pass
            
            chunk_id = f"product_block_{block.id}"
            
            valid_until_str = ""
            if material.valid_until:
                valid_until_str = material.valid_until.isoformat()
            
            metadata = {
                "source": f"{product_name} - {material.name or material.material_type}",
                "title": f"{product_name}: {block.title}",
                "type": "product_content",
                "block_type": block.block_type,
                "product_name": product_name,
                "material_id": str(material_id),
                "block_id": str(block.id),
                "page": str(block.source_page or 0),
                "products": product_ticker.upper() if product_ticker else product_name.upper(),
                "material_type": material.material_type,
                "publish_status": material.publish_status or "rascunho",
                "valid_until": valid_until_str
            }
            
            try:
                self.vector_store.add_document(
                    doc_id=chunk_id,
                    text=content_for_indexing,
                    metadata=metadata
                )
                indexed_count += 1
            except Exception as e:
                print(f"[INGESTOR] Erro ao indexar bloco {block.id}: {e}")
        
        material.is_indexed = indexed_count > 0
        db.commit()
        
        return {"success": True, "indexed_count": indexed_count}
    
    def _table_to_text(self, table_data: Dict) -> str:
        """Converte dados de tabela para texto legível."""
        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        
        lines = []
        for row in rows:
            facts = []
            for i, cell in enumerate(row):
                if i < len(headers) and cell:
                    facts.append(f"{headers[i]}: {cell}")
            if facts:
                lines.append(", ".join(facts))
        
        return "\n".join(lines)
    
    def reindex_material(
        self,
        material_id: int,
        product_name: str,
        product_ticker: Optional[str],
        db: Session
    ) -> Dict[str, Any]:
        """Remove indexação antiga e reindexa o material."""
        blocks = db.query(ContentBlock).filter(
            ContentBlock.material_id == material_id
        ).all()
        
        for block in blocks:
            chunk_id = f"product_block_{block.id}"
            try:
                self.vector_store.delete_document(chunk_id)
            except:
                pass
        
        return self.index_approved_blocks(
            material_id=material_id,
            product_name=product_name,
            product_ticker=product_ticker,
            db=db
        )


_product_ingestor = None

def get_product_ingestor() -> ProductIngestor:
    """Retorna instância singleton do ProductIngestor."""
    global _product_ingestor
    if _product_ingestor is None:
        _product_ingestor = ProductIngestor()
    return _product_ingestor
