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
                 is_resume=False, resume_from_page=0, existing_job_id=None,
                 priority=0):
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
        self.priority = priority
        self._db_id = None
        self._page_times = []
        self._last_page_timestamp = None
        self.eta_seconds = None
        self.avg_page_time = None

    def record_page_completed(self, completed_page_num, total_pages):
        now = datetime.utcnow()
        if self._last_page_timestamp is not None:
            elapsed = (now - self._last_page_timestamp).total_seconds()
            self._page_times.append(elapsed)
        elif self.started_at:
            elapsed = (now - self.started_at).total_seconds()
            self._page_times.append(elapsed)
        self._last_page_timestamp = now
        pages_done = completed_page_num + 1
        total = total_pages if total_pages > 0 else self.total_pages
        if self._page_times and total > 0:
            self.avg_page_time = round(sum(self._page_times) / len(self._page_times), 1)
            pages_remaining = max(0, total - pages_done)
            self.eta_seconds = round(self.avg_page_time * pages_remaining) if pages_remaining > 0 else 0

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
            "status": self.status.value if isinstance(self.status, UploadStatus) else self.status,
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
            "priority": self.priority,
            "eta_seconds": self.eta_seconds,
            "avg_page_time": self.avg_page_time,
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
        self._initialized = False

    def _persist_item(self, item: UploadQueueItem):
        from database.database import SessionLocal
        from database.models import PersistentQueueItem, QueueItemStatus
        db = SessionLocal()
        try:
            db_item = PersistentQueueItem(
                upload_id=item.upload_id,
                file_path=item.file_path,
                filename=item.filename,
                material_id=item.material_id,
                name=item.name,
                user_id=item.user_id,
                material_type=item.material_type,
                categories=json.dumps(item.categories) if item.categories else "[]",
                tags=json.dumps(item.tags) if item.tags else "[]",
                valid_from=item.valid_from,
                valid_until=item.valid_until,
                selected_product_id=item.selected_product_id,
                is_resume=item.is_resume,
                resume_from_page=item.resume_from_page,
                existing_job_id=item.existing_job_id,
                status=QueueItemStatus.QUEUED.value,
                priority=item.priority,
                created_at=item.created_at,
            )
            db.add(db_item)
            db.commit()
            db.refresh(db_item)
            item._db_id = db_item.id
        except Exception as e:
            logger.error(f"Erro ao persistir item na fila: {e}")
            db.rollback()
        finally:
            db.close()

    def _update_db_status(self, item: UploadQueueItem):
        from database.database import SessionLocal
        from database.models import PersistentQueueItem
        db = SessionLocal()
        try:
            db_item = db.query(PersistentQueueItem).filter(
                PersistentQueueItem.upload_id == item.upload_id
            ).first()
            if db_item:
                status_val = item.status.value if isinstance(item.status, UploadStatus) else item.status
                db_item.status = status_val
                db_item.progress = item.progress
                db_item.current_page = item.current_page
                db_item.total_pages = item.total_pages
                db_item.error = item.error
                db_item.stats = json.dumps(item.stats) if item.stats else None
                db_item.product_name = item.product_name
                db_item.product_ticker = item.product_ticker
                db_item.started_at = item.started_at
                db_item.completed_at = item.completed_at
                db_item.logs = json.dumps(item.logs[-50:])
                db.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar status no DB: {e}")
            db.rollback()
        finally:
            db.close()

    def _load_pending_from_db(self):
        from database.database import SessionLocal
        from database.models import PersistentQueueItem, QueueItemStatus
        db = SessionLocal()
        try:
            pending = db.query(PersistentQueueItem).filter(
                PersistentQueueItem.status.in_([
                    QueueItemStatus.QUEUED.value,
                    QueueItemStatus.PROCESSING.value
                ])
            ).order_by(
                PersistentQueueItem.priority.desc(),
                PersistentQueueItem.created_at.asc()
            ).all()

            loaded = 0
            for db_item in pending:
                if db_item.upload_id in self._items:
                    continue

                if not os.path.exists(db_item.file_path):
                    db_item.status = QueueItemStatus.FAILED.value
                    db_item.error = "Arquivo não encontrado após reinício"
                    db.commit()
                    continue

                item = UploadQueueItem(
                    upload_id=db_item.upload_id,
                    file_path=db_item.file_path,
                    filename=db_item.filename,
                    material_id=db_item.material_id,
                    name=db_item.name,
                    user_id=db_item.user_id,
                    material_type=db_item.material_type,
                    categories=json.loads(db_item.categories or "[]"),
                    tags=json.loads(db_item.tags or "[]"),
                    valid_from=db_item.valid_from,
                    valid_until=db_item.valid_until,
                    selected_product_id=db_item.selected_product_id,
                    is_resume=db_item.is_resume,
                    resume_from_page=db_item.resume_from_page,
                    existing_job_id=db_item.existing_job_id,
                    priority=db_item.priority or 0,
                )
                item.created_at = db_item.created_at
                item._db_id = db_item.id
                item.product_name = db_item.product_name
                item.product_ticker = db_item.product_ticker

                if db_item.status == QueueItemStatus.PROCESSING.value:
                    item.is_resume = True
                    from database.models import DocumentProcessingJob
                    job = db.query(DocumentProcessingJob).filter(
                        DocumentProcessingJob.material_id == db_item.material_id
                    ).order_by(DocumentProcessingJob.created_at.desc()).first()
                    if job:
                        item.existing_job_id = job.id
                        item.resume_from_page = job.last_processed_page or 0
                        item.total_pages = job.total_pages or 0
                        item.current_page = job.last_processed_page or 0
                        if item.total_pages > 0:
                            item.progress = int((item.current_page / item.total_pages) * 100)
                        item._last_page_timestamp = datetime.utcnow()
                        item.started_at = datetime.utcnow()

                try:
                    logs = json.loads(db_item.logs or "[]")
                    item.logs = logs
                except Exception:
                    pass

                item.add_log("Retomado automaticamente após reinício do servidor", "info")
                self._items[item.upload_id] = item
                self._queue.put(item.upload_id)
                loaded += 1

            if loaded > 0:
                logger.info(f"[UploadQueue] {loaded} item(ns) pendente(s) carregado(s) do banco")

        except Exception as e:
            logger.error(f"Erro ao carregar fila do banco: {e}")
        finally:
            db.close()

    def initialize(self):
        if self._initialized:
            return
        self._initialized = True
        self._load_pending_from_db()
        if not self._queue.empty():
            self._ensure_worker_running()

    def add(self, item: UploadQueueItem):
        self._persist_item(item)
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
        active.sort(key=lambda x: (-(x.get("priority") or 0), x["created_at"] or ""))
        history.sort(key=lambda x: x["completed_at"] or "", reverse=True)
        return {
            "active": active,
            "history": history[:self._max_history],
            "queue_size": self._queue.qsize(),
            "is_processing": self._processing,
        }

    def remove_from_queue(self, upload_id: str):
        item = self._items.get(upload_id)
        if not item:
            return False
        if item.status != UploadStatus.QUEUED:
            return False
        new_queue = queue.Queue()
        while not self._queue.empty():
            try:
                uid = self._queue.get_nowait()
                if uid != upload_id:
                    new_queue.put(uid)
            except queue.Empty:
                break
        self._queue = new_queue

        from database.database import SessionLocal
        from database.models import Material, PersistentQueueItem, ContentBlock
        db = SessionLocal()
        try:
            db.query(PersistentQueueItem).filter(
                PersistentQueueItem.upload_id == upload_id
            ).delete()

            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if mat:
                blocks_count = db.query(ContentBlock).filter(ContentBlock.material_id == mat.id).count()
                if blocks_count == 0:
                    db.delete(mat)
                else:
                    mat.processing_status = 'failed'
                    mat.processing_error = 'Removido da fila pelo usuário'
            db.commit()
        except Exception as e:
            logger.error(f"Erro ao limpar dados ao remover da fila: {e}")
            db.rollback()
        finally:
            db.close()

        if item.file_path and os.path.exists(item.file_path):
            try:
                os.remove(item.file_path)
            except Exception:
                pass

        del self._items[upload_id]
        self._broadcast_event({"type": "removed", "upload_id": upload_id})
        return True

    def reorder(self, upload_id: str, direction: str):
        active_items = [
            item for item in self._items.values()
            if item.status == UploadStatus.QUEUED
        ]
        active_items.sort(key=lambda x: (-(x.priority or 0), x.created_at))

        target = None
        target_idx = -1
        for i, item in enumerate(active_items):
            if item.upload_id == upload_id:
                target = item
                target_idx = i
                break

        if not target:
            return False

        if direction == "up" and target_idx > 0:
            swap_item = active_items[target_idx - 1]
            target.priority, swap_item.priority = swap_item.priority, target.priority
            if target.priority == swap_item.priority:
                target.priority = swap_item.priority + 1
            self._update_db_status(target)
            self._update_db_status(swap_item)
            return True
        elif direction == "down" and target_idx < len(active_items) - 1:
            swap_item = active_items[target_idx + 1]
            target.priority, swap_item.priority = swap_item.priority, target.priority
            if target.priority == swap_item.priority:
                swap_item.priority = target.priority + 1
            self._update_db_status(target)
            self._update_db_status(swap_item)
            return True

        return False

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
            self._update_db_status(item)
            self._broadcast_event({"type": "status_change", "upload_id": upload_id, "status": "processing"})

            try:
                self._process_item(item)
            except Exception as e:
                logger.error(f"Erro ao processar upload {upload_id}: {e}")
                item.status = UploadStatus.FAILED
                item.error = str(e)[:500]
                item.add_log(f"Erro: {str(e)[:200]}", "error")
                self._update_db_status(item)
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
                    self._update_db_status(item)
                    self._broadcast_event({
                        "type": "progress", "upload_id": item.upload_id,
                        "message": f"Retomando da página {start_page + 1}...",
                        "current": start_page, "total": processing_job.total_pages,
                        "progress": item.progress
                    })

            if not processing_job:
                with open(item.file_path, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                duplicate = db.query(Material).filter(
                    Material.file_hash == file_hash,
                    Material.file_hash != None,
                    Material.id != item.material_id
                ).first()
                if duplicate:
                    dup_date = duplicate.created_at.strftime('%d/%m/%Y') if duplicate.created_at else 'data desconhecida'
                    dup_msg = (
                        f"Arquivo idêntico já carregado como "
                        f"'{duplicate.name}' em {dup_date}."
                    )
                    item.add_log(f"Aviso: {dup_msg}", "warning")
                    self._broadcast_event({
                        "type": "warning", "upload_id": item.upload_id,
                        "message": dup_msg,
                        "existing_material_id": duplicate.id
                    })
                    logger.warning(f"[UPLOAD] Duplicata detectada: file_hash={file_hash[:12]}... material_id={duplicate.id}")

                mat.file_hash = file_hash
                mat.file_hash_checked_at = datetime.utcnow()
                db.commit()

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

                mat.source_file_path = item.file_path
                mat.source_filename = mat.source_filename or item.filename
                db.commit()

                for page_num in range(1, total_pages + 1):
                    page_result = DocumentPageResult(
                        job_id=processing_job.id,
                        page_number=page_num,
                        status=PageProcessingStatus.PENDING.value
                    )
                    db.add(page_result)
                db.commit()

                item.add_log("Extraindo metadados do documento...", "info")
                self._update_db_status(item)
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
                        from services.product_resolver import get_product_resolver
                        resolver = get_product_resolver(db)
                        resolve_result = resolver.resolve(
                            fund_name=metadata.fund_name,
                            ticker=metadata.ticker,
                            gestora=metadata.gestora,
                            confidence=metadata.confidence,
                        )

                        if resolve_result.is_confident:
                            mat.product_id = resolve_result.matched_product_id
                            mat.processing_status = "processing"
                            db.commit()
                            item.product_name = resolve_result.matched_product_name
                            item.product_ticker = resolve_result.matched_product_ticker
                            item.add_log(
                                f"Produto vinculado: {resolve_result.matched_product_name} "
                                f"({resolve_result.matched_product_ticker or 'sem ticker'}) "
                                f"[{resolve_result.match_type}]",
                                "success"
                            )
                            if metadata.fund_name and resolve_result.match_type == "ticker_exact":
                                resolver.save_alias_on_match(resolve_result.matched_product_id, metadata.fund_name)

                        elif resolve_result.match_type == "fuzzy_high_confidence":
                            mat.product_id = resolve_result.matched_product_id
                            mat.processing_status = "processing"
                            db.commit()
                            item.product_name = resolve_result.matched_product_name
                            item.product_ticker = resolve_result.matched_product_ticker
                            item.add_log(
                                f"Produto vinculado (alta similaridade): {resolve_result.matched_product_name} "
                                f"(score={resolve_result.match_confidence})",
                                "success"
                            )
                            if metadata.fund_name:
                                resolver.save_alias_on_match(resolve_result.matched_product_id, metadata.fund_name)

                        else:
                            resolve_data = {
                                "resolver_result": resolve_result.to_dict(),
                                "extracted_metadata": metadata.to_dict(),
                            }
                            existing_meta = {}
                            if mat.extracted_metadata:
                                try:
                                    existing_meta = json.loads(mat.extracted_metadata)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            existing_meta["product_resolver"] = resolve_data
                            mat.extracted_metadata = json.dumps(existing_meta, ensure_ascii=False)
                            mat.processing_status = "pending_product_match"
                            db.commit()

                            if resolve_result.has_candidates:
                                candidate_names = ", ".join(
                                    f"{c.product_name} ({c.score:.0%})"
                                    for c in resolve_result.candidates[:3]
                                )
                                item.add_log(
                                    f"Produto não confirmado. Candidatos: {candidate_names}",
                                    "warning"
                                )
                            else:
                                item.add_log(
                                    f"Produto não encontrado: {metadata.fund_name or 'N/A'}. "
                                    f"Requer confirmação manual.",
                                    "warning"
                                )
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
                processing_job.last_processed_page = current
                item.record_page_completed(current - 1, total)
                try:
                    db.commit()
                except Exception:
                    pass
                self._update_db_status(item)
                self._broadcast_event({
                    "type": "eta_update", "upload_id": item.upload_id,
                    "eta_seconds": item.eta_seconds,
                    "avg_page_time": item.avg_page_time,
                })

            def page_completed_callback(page_num, total):
                if processing_job.last_processed_page and processing_job.last_processed_page >= page_num + 1:
                    return
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
            self._update_db_status(item)
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
            self._update_db_status(item)
            raise
        finally:
            db.close()


upload_queue = UploadQueue.get_instance()
