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
    Material, ContentBlock, BlockVersion, PendingReviewItem, IngestionLog,
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
        
        tables_count = sum(1 for p in processed.get("pages", []) 
                          if p.get("raw_data", {}).get("tables"))
        charts_count = sum(1 for p in processed.get("pages", []) 
                          if p.get("content_type") == "infographic")
        
        ingestion_log = IngestionLog(
            material_id=material_id,
            document_name=os.path.basename(pdf_path),
            document_type="pdf",
            total_pages=processed.get("total_pages", 0),
            blocks_created=stats["blocks_created"],
            blocks_auto_approved=stats["auto_approved"],
            blocks_pending_review=stats["pending_review"],
            blocks_rejected=0,
            tables_detected=tables_count,
            charts_detected=charts_count,
            status="success",
            details_json=json.dumps({
                "products_detected": stats.get("products_detected", []),
                "pages_processed": len(processed.get("pages", []))
            }),
            user_id=user_id
        )
        db.add(ingestion_log)
        db.commit()
        
        return {"success": True, "stats": stats}
    
    def process_pdf_with_product_detection(
        self,
        pdf_path: str,
        material_id: int,
        document_title: str,
        db: Session,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Processa PDF identificando automaticamente produtos mencionados em cada página.
        Vincula os blocos criados aos produtos detectados.
        """
        from database.models import Product, Material
        
        processed = self.doc_processor.process_pdf(
            pdf_path=pdf_path,
            document_title=document_title,
            progress_callback=None
        )
        
        if processed.get("error"):
            return {"success": False, "error": processed["error"]}
        
        all_products = db.query(Product).filter(
            Product.ticker != "__SYSTEM_UNASSIGNED__",
            Product.status == "ativo"
        ).all()
        
        product_lookup = {}
        for p in all_products:
            if p.ticker:
                product_lookup[p.ticker.upper()] = p
            product_lookup[p.name.upper()] = p
        
        stats = {
            "total_pages": processed["total_pages"],
            "blocks_created": 0,
            "products_matched": set(),
            "auto_approved": 0,
            "pending_review": 0
        }
        
        block_order = 0
        
        for page in processed.get("pages", []):
            page_num = page.get("page_number", 0)
            content_type = page.get("content_type", "text")
            summary = page.get("summary", "")
            facts = page.get("facts", [])
            raw_data = page.get("raw_data", {})
            products_in_page = page.get("products", [])
            
            matched_product = None
            for prod_name in products_in_page:
                prod_upper = prod_name.upper().strip()
                if prod_upper in product_lookup:
                    matched_product = product_lookup[prod_upper]
                    stats["products_matched"].add(matched_product.ticker or matched_product.name)
                    break
            
            if not matched_product:
                page_text = summary + " " + " ".join(facts)
                import re
                ticker_pattern = r'\b([A-Z]{4}\d{1,2})\b'
                tickers_found = re.findall(ticker_pattern, page_text.upper())
                for ticker in tickers_found:
                    if ticker in product_lookup:
                        matched_product = product_lookup[ticker]
                        stats["products_matched"].add(ticker)
                        break
            
            target_material_id = material_id
            
            if matched_product:
                existing_material = db.query(Material).filter(
                    Material.product_id == matched_product.id,
                    Material.name == document_title
                ).first()
                
                if existing_material:
                    target_material_id = existing_material.id
                else:
                    new_material = Material(
                        product_id=matched_product.id,
                        material_type="smart_upload",
                        name=document_title,
                        description=f"Importado automaticamente de {os.path.basename(pdf_path)}",
                        publish_status="rascunho"
                    )
                    db.add(new_material)
                    db.commit()
                    db.refresh(new_material)
                    target_material_id = new_material.id
            
            if content_type == "table" or raw_data.get("tables"):
                tables = raw_data.get("tables", [])
                for i, table in enumerate(tables):
                    table_json = json.dumps(table, ensure_ascii=False)
                    block = self._create_block(
                        material_id=target_material_id,
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
                    material_id=target_material_id,
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
                    material_id=target_material_id,
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
        
        original_material = db.query(Material).filter(Material.id == material_id).first()
        if original_material:
            original_material.source_file_path = pdf_path
            original_material.source_filename = os.path.basename(pdf_path)
            db.commit()
            
            from database.models import ContentBlock as CB
            blocks_in_original = db.query(CB).filter(CB.material_id == material_id).count()
            
            if blocks_in_original == 0 and stats["products_matched"]:
                db.delete(original_material)
                db.commit()
                print(f"[SMART_UPLOAD] Material placeholder {material_id} removido - todos os blocos foram redistribuídos")
        
        stats["products_matched"] = list(stats["products_matched"])
        
        ingestion_log = IngestionLog(
            material_id=material_id,
            document_name=os.path.basename(pdf_path),
            document_type="pdf",
            total_pages=processed.get("total_pages", 0),
            blocks_created=stats["blocks_created"],
            blocks_auto_approved=stats["auto_approved"],
            blocks_pending_review=stats["pending_review"],
            blocks_rejected=0,
            tables_detected=sum(1 for p in processed.get("pages", []) if p.get("raw_data", {}).get("tables")),
            charts_detected=sum(1 for p in processed.get("pages", []) if p.get("content_type") == "infographic"),
            status="success",
            details_json=json.dumps({
                "products_matched": stats["products_matched"],
                "smart_upload": True
            }),
            user_id=user_id
        )
        db.add(ingestion_log)
        db.commit()
        
        return {"success": True, "stats": stats}
    
    def process_pdf_with_product_detection_streaming(
        self,
        pdf_path: str,
        material_id: int,
        document_title: str,
        db: Session,
        user_id: Optional[int] = None,
        progress_callback: Optional[callable] = None,
        log_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Processa PDF com detecção automática de produtos, enviando logs em tempo real.
        """
        from database.models import Product, Material
        
        def log(msg, log_type="info"):
            if log_callback:
                log_callback(msg, log_type)
            print(f"[SMART_UPLOAD] {msg}")
        
        log("Convertendo PDF em imagens...")
        
        processed = self.doc_processor.process_pdf(
            pdf_path=pdf_path,
            document_title=document_title,
            progress_callback=progress_callback
        )
        
        if processed.get("error"):
            log(f"Erro: {processed['error']}", "error")
            return {"success": False, "error": processed["error"]}
        
        total_pages = processed.get("total_pages", 0)
        log(f"Documento com {total_pages} páginas detectado", "success")
        
        all_products = db.query(Product).filter(
            Product.ticker != "__SYSTEM_UNASSIGNED__",
            Product.status == "ativo"
        ).all()
        
        product_lookup = {}
        for p in all_products:
            if p.ticker:
                product_lookup[p.ticker.upper()] = p
            product_lookup[p.name.upper()] = p
        
        log(f"Base de produtos carregada: {len(all_products)} produtos ativos")
        
        stats = {
            "total_pages": total_pages,
            "blocks_created": 0,
            "products_matched": set(),
            "auto_approved": 0,
            "pending_review": 0
        }
        
        all_auto_tags = {
            "contexto": set(),
            "perfil": set(),
            "momento": set(),
            "informacao": set()
        }
        
        block_order = 0
        
        for page in processed.get("pages", []):
            page_num = page.get("page_number", 0)
            content_type = page.get("content_type", "text")
            summary = page.get("summary", "")
            facts = page.get("facts", [])
            raw_data = page.get("raw_data", {})
            products_in_page = page.get("products", [])
            
            page_auto_tags = page.get("auto_tags", {})
            for category in ["contexto", "perfil", "momento", "informacao"]:
                tags_in_category = page_auto_tags.get(category, [])
                if isinstance(tags_in_category, list):
                    all_auto_tags[category].update(tags_in_category)
            
            matched_product = None
            for prod_name in products_in_page:
                prod_upper = prod_name.upper().strip()
                if prod_upper in product_lookup:
                    matched_product = product_lookup[prod_upper]
                    stats["products_matched"].add(matched_product.ticker or matched_product.name)
                    break
            
            if not matched_product:
                page_text = summary + " " + " ".join(facts)
                import re
                ticker_pattern = r'\b([A-Z]{4}\d{1,2})\b'
                tickers_found = re.findall(ticker_pattern, page_text.upper())
                for ticker in tickers_found:
                    if ticker in product_lookup:
                        matched_product = product_lookup[ticker]
                        stats["products_matched"].add(ticker)
                        break
            
            target_material_id = material_id
            
            if matched_product:
                log(f"Página {page_num}: Produto identificado - {matched_product.ticker or matched_product.name}", "success")
                existing_material = db.query(Material).filter(
                    Material.product_id == matched_product.id,
                    Material.name == document_title
                ).first()
                
                if existing_material:
                    target_material_id = existing_material.id
                else:
                    new_material = Material(
                        product_id=matched_product.id,
                        material_type="smart_upload",
                        name=document_title,
                        description=f"Importado automaticamente de {os.path.basename(pdf_path)}",
                        publish_status="rascunho"
                    )
                    db.add(new_material)
                    db.commit()
                    db.refresh(new_material)
                    target_material_id = new_material.id
            else:
                log(f"Página {page_num}: Nenhum produto identificado - enviando para revisão", "warning")
            
            blocks_created_page = 0
            
            if content_type == "table" or raw_data.get("tables"):
                tables = raw_data.get("tables", [])
                for i, table in enumerate(tables):
                    table_json = json.dumps(table, ensure_ascii=False)
                    block = self._create_block(
                        material_id=target_material_id,
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
                    blocks_created_page += 1
                    if block.status == ContentBlockStatus.AUTO_APPROVED.value:
                        stats["auto_approved"] += 1
                    else:
                        stats["pending_review"] += 1
            
            if content_type == "infographic":
                block = self._create_block(
                    material_id=target_material_id,
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
                blocks_created_page += 1
                stats["pending_review"] += 1
            
            if facts and content_type not in ["table", "infographic"]:
                text_content = "\n\n".join(facts)
                if summary:
                    text_content = f"{summary}\n\n{text_content}"
                
                block = self._create_block(
                    material_id=target_material_id,
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
                blocks_created_page += 1
                if block.status == ContentBlockStatus.AUTO_APPROVED.value:
                    stats["auto_approved"] += 1
                else:
                    stats["pending_review"] += 1
            
            if blocks_created_page > 0:
                log(f"Página {page_num}: {blocks_created_page} bloco(s) criado(s)")
        
        original_material = db.query(Material).filter(Material.id == material_id).first()
        if original_material:
            original_material.source_file_path = pdf_path
            original_material.source_filename = os.path.basename(pdf_path)
            
            auto_tags_flat = []
            for category, tag_set in all_auto_tags.items():
                auto_tags_flat.extend(list(tag_set))
            
            if auto_tags_flat:
                original_material.auto_generated_tags = json.dumps(auto_tags_flat)
                log(f"Tags auto-geradas: {', '.join(auto_tags_flat)}", "info")
                
                existing_tags = []
                try:
                    existing_tags = json.loads(original_material.tags or "[]")
                except:
                    existing_tags = []
                
                merged_tags = list(set(existing_tags + auto_tags_flat))
                original_material.tags = json.dumps(merged_tags)
            
            db.commit()
            
            from database.models import ContentBlock as CB
            blocks_in_original = db.query(CB).filter(CB.material_id == material_id).count()
            
            if blocks_in_original == 0 and stats["products_matched"]:
                db.delete(original_material)
                db.commit()
                log("Material placeholder removido - blocos redistribuídos para produtos identificados")
        
        stats["products_matched"] = list(stats["products_matched"])
        stats["auto_tags"] = {k: list(v) for k, v in all_auto_tags.items()}
        
        log(f"Processamento finalizado: {stats['blocks_created']} blocos, {len(stats['products_matched'])} produtos identificados", "success")
        
        ingestion_log = IngestionLog(
            material_id=material_id,
            document_name=os.path.basename(pdf_path),
            document_type="pdf",
            total_pages=total_pages,
            blocks_created=stats["blocks_created"],
            blocks_auto_approved=stats["auto_approved"],
            blocks_pending_review=stats["pending_review"],
            blocks_rejected=0,
            tables_detected=sum(1 for p in processed.get("pages", []) if p.get("raw_data", {}).get("tables")),
            charts_detected=sum(1 for p in processed.get("pages", []) if p.get("content_type") == "infographic"),
            status="success",
            details_json=json.dumps({
                "products_matched": stats["products_matched"],
                "smart_upload": True,
                "streaming": True
            }),
            user_id=user_id
        )
        db.add(ingestion_log)
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
        
        material_tags = []
        try:
            material_tags = json.loads(material.tags or "[]")
        except:
            material_tags = []
        
        material_categories = []
        try:
            material_categories = json.loads(material.material_categories or "[]")
        except:
            material_categories = []
        
        tags_text = ""
        if material_tags or material_categories:
            all_enrichment = material_tags + material_categories
            tags_text = f"\n\n[Tags: {', '.join(all_enrichment)}]"
        
        for block in blocks:
            content_for_indexing = block.content
            if block.block_type == ContentBlockType.TABLE.value:
                try:
                    table_data = json.loads(block.content)
                    text_repr = self._table_to_text(table_data)
                    content_for_indexing = f"Tabela: {block.title}\n{text_repr}"
                except:
                    pass
            
            content_for_indexing += tags_text
            
            chunk_id = f"product_block_{block.id}"
            
            valid_until_str = ""
            if material.valid_until:
                valid_until_str = material.valid_until.isoformat()
            
            tags_str = ",".join(material_tags) if material_tags else ""
            
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
                "valid_until": valid_until_str,
                "tags": tags_str
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
