import threading
import queue
import uuid
import os
import hashlib
import json
import logging
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class UploadStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadQueueItem:
    def __init__(self, upload_id, file_path, filename, material_id, name, user_id,
                 material_type="outro", categories=None, tags=None,
                 valid_from=None, valid_until=None, selected_product_id=None,
                 is_resume=False, resume_from_page=0, existing_job_id=None):
        self.upload_id = upload_id
        self.file_path = file_path
        self.filename = filename
        self.material_id = material_id
        self.name = name
        self.user_id = user_id
        self.material_type = material_type
        self.categories = categories or []
        self.tags = tags or []
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.selected_product_id = selected_product_id
        self.is_resume = is_resume
        self.resume_from_page = resume_from_page
        self.existing_job_id = existing_job_id
        self.status = UploadStatus.QUEUED
        self.progress = 0
        self.current_page = 0
        self.total_pages = 0
        self.logs = []
        self.error = None
        self.stats = None
        self.created_at = datetime.utcnow()
        self.started_at = None
        self.completed_at = None
        self.product_name = None
        self.product_ticker = None

    def add_log(self, message, log_type="info"):
        self.logs.append({
            "time": datetime.utcnow().strftime("%H:%M:%S"),
            "message": message,
            "type": log_type
        })

    def to_dict(self):
        return {
            "upload_id": self.upload_id,
            "filename": self.filename,
            "name": self.name,
            "material_id": self.material_id,
            "status": self.status.value,
            "progress": self.progress,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "logs": self.logs[-20:],
            "error": self.error,
            "stats": self.stats,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "product_name": self.product_name,
            "product_ticker": self.product_ticker,
        }


class UploadQueue:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._queue = queue.Queue()
        self._items = {}
        self._processing = False
        self._worker_thread = None
        self._event_listeners = {}
        self._history = []
        self._max_history = 50

    def add(self, item: UploadQueueItem):
        self._items[item.upload_id] = item
        self._queue.put(item.upload_id)
        self._ensure_worker_running()
        return item.upload_id

    def get_status(self, upload_id):
        item = self._items.get(upload_id)
        if item:
            return item.to_dict()
        return None

    def get_all_status(self):
        active = []
        history = []
        for uid, item in self._items.items():
            d = item.to_dict()
            if item.status in (UploadStatus.QUEUED, UploadStatus.PROCESSING):
                active.append(d)
            else:
                history.append(d)
        active.sort(key=lambda x: x["created_at"] or "")
        history.sort(key=lambda x: x["completed_at"] or "", reverse=True)
        return {
            "active": active,
            "history": history[:self._max_history],
            "queue_size": self._queue.qsize(),
            "is_processing": self._processing,
        }

    def subscribe(self, listener_id):
        q = queue.Queue()
        self._event_listeners[listener_id] = q
        return q

    def unsubscribe(self, listener_id):
        self._event_listeners.pop(listener_id, None)

    def _broadcast_event(self, event):
        dead = []
        listeners = dict(self._event_listeners)
        for lid, q in listeners.items():
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(lid)
        for lid in dead:
            self._event_listeners.pop(lid, None)

    def _ensure_worker_running(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker, daemon=True)
            self._worker_thread.start()

    def _worker(self):
        while True:
            try:
                upload_id = self._queue.get(timeout=30)
            except queue.Empty:
                break

            item = self._items.get(upload_id)
            if not item:
                continue

            self._processing = True
            item.status = UploadStatus.PROCESSING
            item.started_at = datetime.utcnow()
            item.add_log("Iniciando processamento...", "info")
            self._broadcast_event({"type": "status_change", "upload_id": upload_id, "status": "processing"})

            try:
                self._process_item(item)
            except Exception as e:
                logger.error(f"Erro ao processar upload {upload_id}: {e}")
                item.status = UploadStatus.FAILED
                item.error = str(e)[:500]
                item.add_log(f"Erro: {str(e)[:200]}", "error")
                self._broadcast_event({
                    "type": "status_change", "upload_id": upload_id,
                    "status": "failed", "error": str(e)[:200]
                })
            finally:
                self._processing = False

    def _process_item(self, item: UploadQueueItem):
        from database.database import SessionLocal
        from database.models import (
            Material, Product, ContentBlock, PendingReviewItem,
            ProcessingStatus, DocumentProcessingJob, DocumentPageResult,
            ProcessingJobStatus, PageProcessingStatus, ContentBlockStatus
        )
        from services.product_ingestor import get_product_ingestor
        from services.document_metadata_extractor import get_metadata_extractor
        from services.document_processor import get_document_processor

        db = SessionLocal()
        try:
            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if not mat:
                raise Exception("Material não encontrado no banco")

            mat.processing_status = ProcessingStatus.PROCESSING.value
            db.commit()

            start_page = 0
            processing_job = None

            if item.is_resume and item.existing_job_id:
                processing_job = db.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.id == item.existing_job_id
                ).first()

                if processing_job:
                    start_page = processing_job.last_processed_page or 0
                    processing_job.status = ProcessingJobStatus.PROCESSING.value
                    processing_job.retry_count = (processing_job.retry_count or 0) + 1
                    db.commit()

                    item.total_pages = processing_job.total_pages
                    item.current_page = start_page
                    item.progress = int((start_page / processing_job.total_pages) * 100) if processing_job.total_pages > 0 else 0
                    item.add_log(f"Retomando da página {start_page + 1}/{processing_job.total_pages}...", "info")
                    self._broadcast_event({
                        "type": "progress", "upload_id": item.upload_id,
                        "message": f"Retomando da página {start_page + 1}...",
                        "current": start_page, "total": processing_job.total_pages,
                        "progress": item.progress
                    })

            if not processing_job:
                with open(item.file_path, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                doc_processor = get_document_processor()
                total_pages = doc_processor.get_pdf_page_count(item.file_path)
                item.total_pages = total_pages

                processing_job = DocumentProcessingJob(
                    material_id=item.material_id,
                    file_path=item.file_path,
                    file_hash=file_hash,
                    total_pages=total_pages,
                    status=ProcessingJobStatus.PROCESSING.value,
                    started_at=datetime.utcnow()
                )
                db.add(processing_job)
                db.commit()
                db.refresh(processing_job)

                for page_num in range(1, total_pages + 1):
                    page_result = DocumentPageResult(
                        job_id=processing_job.id,
                        page_number=page_num,
                        status=PageProcessingStatus.PENDING.value
                    )
                    db.add(page_result)
                db.commit()

                item.add_log("Extraindo metadados do documento...", "info")
                self._broadcast_event({
                    "type": "progress", "upload_id": item.upload_id,
                    "message": "Extraindo metadados...", "progress": 5
                })

                try:
                    extractor = get_metadata_extractor()
                    existing_products = db.query(Product).filter(
                        (Product.ticker != "__SYSTEM_UNASSIGNED__") | (Product.ticker == None)
                    ).all()
                    existing_products_list = [{"id": p.id, "name": p.name, "ticker": p.ticker} for p in existing_products]

                    metadata = extractor.extract_metadata(
                        pdf_path=item.file_path,
                        pages_to_analyze=[0, 1, 2],
                        existing_products=existing_products_list
                    )

                    if mat:
                        mat.extracted_metadata = json.dumps(metadata.to_dict(), ensure_ascii=False)
                        db.commit()

                    item.add_log(f"Metadados: {metadata.fund_name or 'N/A'} | Ticker: {metadata.ticker or 'N/A'}", "info")

                    if metadata.confidence >= 0.5 and (metadata.ticker or metadata.fund_name):
                        matched_product = None
                        if metadata.ticker:
                            matched_product = db.query(Product).filter(Product.ticker == metadata.ticker).first()
                        if not matched_product and metadata.fund_name:
                            from services.document_metadata_extractor import normalize_text
                            fund_normalized = normalize_text(metadata.fund_name)
                            for prod in existing_products:
                                if normalize_text(prod.name) in fund_normalized or fund_normalized in normalize_text(prod.name):
                                    matched_product = prod
                                    break

                        if matched_product and matched_product.ticker != "__SYSTEM_UNASSIGNED__":
                            mat.product_id = matched_product.id
                            db.commit()
                            item.product_name = matched_product.name
                            item.product_ticker = matched_product.ticker
                            item.add_log(f"Produto: {matched_product.name} ({matched_product.ticker})", "success")
                        elif metadata.fund_name and metadata.confidence >= 0.8:
                            new_product = Product(
                                name=metadata.fund_name,
                                ticker=metadata.ticker,
                                category=metadata.gestora or "FII",
                                manager=metadata.gestora,
                                status="ativo"
                            )
                            db.add(new_product)
                            db.commit()
                            db.refresh(new_product)
                            mat.product_id = new_product.id
                            db.commit()
                            item.product_name = new_product.name
                            item.product_ticker = new_product.ticker
                            item.add_log(f"Novo produto criado: {new_product.name}", "success")
                except Exception as meta_err:
                    item.add_log(f"Aviso: Metadados falhou ({str(meta_err)[:100]})", "warning")

            if mat.product:
                item.product_name = mat.product.name
                item.product_ticker = mat.product.ticker

            ingestor = get_product_ingestor()

            def progress_callback(current, total):
                item.current_page = current
                item.total_pages = total
                item.progress = int((current / total) * 100) if total > 0 else 0
                self._broadcast_event({
                    "type": "progress", "upload_id": item.upload_id,
                    "current": current, "total": total,
                    "progress": item.progress,
                    "message": f"Página {current}/{total}"
                })
                processing_job.processed_pages = current
                try:
                    db.commit()
                except Exception:
                    pass

            def page_completed_callback(page_num, total):
                processing_job.last_processed_page = page_num + 1
                try:
                    db.commit()
                except Exception:
                    pass

            result = ingestor.process_pdf_with_product_detection_streaming(
                pdf_path=item.file_path,
                material_id=item.material_id,
                document_title=item.name,
                db=db,
                user_id=item.user_id,
                progress_callback=progress_callback,
                log_callback=lambda msg, t: item.add_log(msg, t),
                start_page=start_page,
                page_completed_callback=page_completed_callback
            )

            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if mat:
                mat.processing_status = ProcessingStatus.SUCCESS.value
                db.commit()

                placeholder = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
                if placeholder and mat.product_id == placeholder.id:
                    first_block = db.query(ContentBlock).filter(
                        ContentBlock.material_id == mat.id
                    ).first()
                    if first_block:
                        existing_review = db.query(PendingReviewItem).filter(
                            PendingReviewItem.block_id == first_block.id
                        ).first()
                        if not existing_review:
                            first_block.status = ContentBlockStatus.PENDING_REVIEW.value
                            first_block.is_high_risk = True
                            db.commit()
                            review_item = PendingReviewItem(
                                block_id=first_block.id,
                                original_content=first_block.content[:500] if first_block.content else "",
                                extracted_content=first_block.content,
                                confidence_score=30,
                                risk_reason="Material não vinculado a produto"
                            )
                            db.add(review_item)
                            db.commit()
                            item.add_log("Enviado para revisão (produto não identificado)", "warning")

            processing_job.status = ProcessingJobStatus.COMPLETED.value
            processing_job.processed_pages = processing_job.total_pages
            processing_job.last_processed_page = processing_job.total_pages
            processing_job.completed_at = datetime.utcnow()
            for page_result in db.query(DocumentPageResult).filter(
                DocumentPageResult.job_id == processing_job.id
            ).all():
                page_result.status = PageProcessingStatus.SUCCESS.value
                page_result.processed_at = datetime.utcnow()
            db.commit()

            item.status = UploadStatus.COMPLETED
            item.progress = 100
            item.completed_at = datetime.utcnow()
            item.stats = {
                "blocks_created": result.get("stats", {}).get("blocks_created", 0),
                "products_matched": list(result.get("stats", {}).get("products_matched", [])),
                "auto_approved": result.get("stats", {}).get("auto_approved", 0),
                "pending_review": result.get("stats", {}).get("pending_review", 0)
            }
            item.add_log("Processamento concluído!", "success")
            self._broadcast_event({
                "type": "status_change", "upload_id": item.upload_id,
                "status": "completed", "stats": item.stats
            })

        except Exception as e:
            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if mat:
                mat.processing_status = ProcessingStatus.FAILED.value if hasattr(ProcessingStatus, 'FAILED') else "failed"
                mat.processing_error = str(e)[:500]
                db.commit()
            raise
        finally:
            db.close()


upload_queue = UploadQueue.get_instance()
