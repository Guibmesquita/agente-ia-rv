import threading
import queue
import uuid
import os
import hashlib
import json
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


def _get_retention_days() -> int:
    """Lê a política de retenção (em dias) para itens terminais da fila.

    Configurável via env `UPLOAD_QUEUE_RETENTION_DAYS` (default: 30).
    Valor <= 0 desativa a limpeza automática.
    """
    raw = os.getenv("UPLOAD_QUEUE_RETENTION_DAYS", "30")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 30


def _get_cleanup_interval_hours() -> int:
    """Intervalo (em horas) entre execuções do job de limpeza.

    Configurável via env `UPLOAD_QUEUE_CLEANUP_INTERVAL_HOURS` (default: 24).
    """
    raw = os.getenv("UPLOAD_QUEUE_CLEANUP_INTERVAL_HOURS", "24")
    try:
        v = int(raw)
        return v if v > 0 else 24
    except (TypeError, ValueError):
        return 24

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
        self.additional_tickers = []
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
            "additional_tickers": self.additional_tickers or [],
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
        self._cleanup_thread = None
        self._cleanup_stop = threading.Event()

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
        self._start_cleanup_scheduler()

    def cleanup_old_terminal_items(self, retention_days: Optional[int] = None) -> int:
        """Remove registros terminais antigos da tabela `upload_queue_items`.

        Apaga linhas em estado `completed` ou `failed` cuja
        `completed_at` (ou `created_at` como fallback) é mais antiga que o TTL.
        Retorna a quantidade de linhas removidas.

        Args:
            retention_days: Se informado, sobrescreve o valor da env
                `UPLOAD_QUEUE_RETENTION_DAYS`. Valor <= 0 é tratado como
                "limpeza desativada" e a função retorna 0 sem tocar no banco.
        """
        from database.database import SessionLocal
        from database.models import PersistentQueueItem, QueueItemStatus
        from sqlalchemy import func as sql_func

        days = retention_days if retention_days is not None else _get_retention_days()
        if days <= 0:
            logger.info(
                f"[UploadQueue] Limpeza automática desativada "
                f"(UPLOAD_QUEUE_RETENTION_DAYS={days})"
            )
            return 0

        cutoff = datetime.utcnow() - timedelta(days=days)
        terminal_states = [
            QueueItemStatus.COMPLETED.value,
            QueueItemStatus.FAILED.value,
        ]

        db = SessionLocal()
        try:
            # Usa COALESCE para que itens sem `completed_at` (raros, mas
            # possíveis em estados terminais antigos) caiam no critério
            # via `created_at`.
            removed = db.query(PersistentQueueItem).filter(
                PersistentQueueItem.status.in_(terminal_states),
                sql_func.coalesce(
                    PersistentQueueItem.completed_at,
                    PersistentQueueItem.created_at,
                ) < cutoff,
            ).delete(synchronize_session=False)
            db.commit()
            if removed:
                logger.info(
                    f"[UploadQueue] Limpeza removeu {removed} registro(s) "
                    f"terminal(is) com mais de {days} dia(s)"
                )
            return removed or 0
        except Exception as e:
            logger.error(f"[UploadQueue] Erro na limpeza de itens antigos: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    def _start_cleanup_scheduler(self):
        """Sobe um daemon thread que roda `cleanup_old_terminal_items`
        periodicamente. A primeira execução acontece logo no startup; as
        próximas seguem o intervalo configurado.
        """
        if _get_retention_days() <= 0:
            logger.info(
                "[UploadQueue] Scheduler de limpeza não iniciado "
                "(UPLOAD_QUEUE_RETENTION_DAYS <= 0)"
            )
            return
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return

        interval_seconds = _get_cleanup_interval_hours() * 3600

        def _loop():
            # Executa uma vez logo no startup para limpar acúmulo histórico.
            try:
                self.cleanup_old_terminal_items()
            except Exception as e:
                logger.error(f"[UploadQueue] Erro na limpeza inicial: {e}")
            while not self._cleanup_stop.wait(interval_seconds):
                try:
                    self.cleanup_old_terminal_items()
                except Exception as e:
                    logger.error(f"[UploadQueue] Erro na limpeza periódica: {e}")

        t = threading.Thread(
            target=_loop, name="upload-queue-cleanup", daemon=True
        )
        t.start()
        self._cleanup_thread = t
        logger.info(
            f"[UploadQueue] Scheduler de limpeza ativo "
            f"(retenção={_get_retention_days()}d, intervalo={_get_cleanup_interval_hours()}h)"
        )

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

    # Padrões de estruturas (Renda Variável estruturada). Quando aparecem no
    # nome do material/fund_name, o produto criado é OBRIGATORIAMENTE do tipo
    # `estruturada` (e não `acao`/`fii` por padrão). Cobre as siglas mais
    # usadas pela mesa SVN (POP, Collar, Fence, Put Spread, Booster, Worst Of).
    # Fonte única da verdade em `services/structure_keywords.STRUCTURE_KEYWORDS`,
    # consumida também por _candidate_is_structure / _cp_is_structure nos endpoints.
    from services.structure_keywords import STRUCTURE_KEYWORDS as _STRUCTURE_KEYWORDS

    @classmethod
    def _detect_structure_in_name(cls, *texts) -> Optional[str]:
        """Retorna a primeira sigla de estrutura encontrada nos textos (ex.: 'pop'),
        ou None se nenhuma casar. Usa busca case-insensitive em palavras inteiras
        para evitar falsos positivos (ex.: 'pop' não casa com 'popular')."""
        from services.structure_keywords import find_structure_keyword
        return find_structure_keyword(*texts)

    @classmethod
    def _detect_swap_in_name(cls, *texts) -> Optional[str]:
        """Retorna a primeira keyword de troca/swap encontrada nos textos
        (ex.: 'troca', 'rotação', 'pair trade', 'swap'), ou None se nenhuma casar.

        Usado para evitar que material "Troca PETR4 por VALE3.pdf" caia nas
        ações PETR4 ou VALE3 já cadastradas — ele é UMA recomendação tática
        (operação de troca), não duas análises individuais.
        """
        from services.swap_keywords import find_swap_keyword
        return find_swap_keyword(*texts)

    @classmethod
    def _detect_portfolio_in_name(cls, *texts) -> Optional[str]:
        """Task #200 — Retorna a primeira palavra-chave de carteira encontrada
        nos textos (ex.: 'carteira', 'portfólio', 'rebalanceamento'), ou None.

        Usa o mesmo regex de `services.product_ingestor._is_portfolio_material`
        para garantir critério ÚNICO em todo o pipeline (extractor, ingestor,
        upload_queue). Isso evita que o `_auto_create_product` reuse um produto
        FII/ação existente quando o material é uma CARTEIRA — caso em que o
        material precisa de produto novo do tipo `carteira`, sem ticker.
        """
        from services.product_ingestor import _PORTFOLIO_REGEX
        for txt in texts:
            if not txt:
                continue
            match = _PORTFOLIO_REGEX.search(str(txt))
            if match:
                return match.group(0).lower()
        return None

    def _auto_create_product(self, db, fund_name, ticker, gestora, document_type=None,
                             filename_hint=None, material_name=None):
        from database.models import Product, ProductStatus
        from services.product_resolver import ProductResolver
        from services.product_type_inference import coerce_product_type
        import json

        # Detecta se o material é sobre uma TROCA/SWAP (recomendação tática
        # de substituir A por B). Para swap, ticker é OPCIONAL — a operação
        # não tem ticker próprio. Por isso a checagem `if not fund_name and
        # not ticker: return None` precisa vir DEPOIS de `swap_kw`.
        swap_kw = self._detect_swap_in_name(
            fund_name, document_type, filename_hint, material_name,
        )

        if not fund_name and not ticker and not swap_kw:
            return None

        # Detecta se o material é sobre uma ESTRUTURA (POP/Collar/Fence...).
        # Quando for, o resolve normal por ticker do underlying é perigoso —
        # ele encontraria a ação nua e linkaria o material da estrutura à ação,
        # apagando o vínculo correto e silenciando o tipo `estruturada`.
        # IMPORTANTE: além de fund_name/document_type, inspecionamos também o
        # FILENAME e o NOME DO MATERIAL — quando a IA falha em ler "POP/Collar"
        # do PDF, o nome do arquivo costuma carregá-lo.
        structure_kw = self._detect_structure_in_name(
            fund_name, document_type, filename_hint, material_name,
        )

        # Task #200 — Detecta CARTEIRA. Quando o material é uma carteira de
        # FIIs/ações, o resolver tende a casar com o ticker da primeira linha
        # da composição (ex.: TVRI11) e devolveria o produto-FII errado.
        # Aqui aplicamos a mesma estratégia de structure_kw/swap_kw: só reusa
        # match se ele for `carteira` E sem ticker; caso contrário cria
        # produto-carteira novo com ticker=None.
        portfolio_kw = self._detect_portfolio_in_name(
            fund_name, document_type, filename_hint, material_name,
        )

        resolver = ProductResolver(db)
        result = resolver.resolve(
            fund_name=fund_name,
            ticker=ticker,
            gestora=gestora,
        )

        if result.matched_product_id and not structure_kw and not swap_kw and not portfolio_kw:
            matched = db.query(Product).filter(Product.id == result.matched_product_id).first()
            if matched:
                logger.info(f"[AutoCreate] ProductResolver encontrou match: {matched.name} (id={matched.id}, tipo={result.match_type})")
                return matched

        # Task #200 — guarda de CARTEIRA, gêmea da de structure_kw/swap_kw.
        # Só reusa um produto existente se ele for `carteira` SEM ticker.
        if result.matched_product_id and portfolio_kw:
            matched = db.query(Product).filter(Product.id == result.matched_product_id).first()
            matched_type = (matched.product_type or "").lower() if matched else ""
            matched_ticker = (matched.ticker or "").strip() if matched else ""
            if matched and matched_type == "carteira" and not matched_ticker:
                logger.info(
                    f"[AutoCreate] Match em produto-carteira existente: "
                    f"{matched.name} (id={matched.id})"
                )
                return matched
            if matched:
                logger.info(
                    f"[AutoCreate] Material parece carteira ({portfolio_kw!r}) mas "
                    f"resolver matched {matched.name} "
                    f"(type={matched_type!r}, ticker={matched_ticker!r}). "
                    f"Criando produto-carteira novo em vez de reusar."
                )

        # Quando é SWAP/troca, evitamos cair na ação subjacente (mesmo padrão
        # da guarda de estrutura): só reusa match se ele também for `swap`.
        if result.matched_product_id and swap_kw:
            matched = db.query(Product).filter(Product.id == result.matched_product_id).first()
            if matched and (matched.product_type or "").lower() == "swap":
                logger.info(f"[AutoCreate] Match em produto-swap existente: {matched.name} (id={matched.id})")
                return matched
            if matched:
                logger.info(
                    f"[AutoCreate] Material parece troca/swap ({swap_kw!r}) mas resolver "
                    f"matched produto não-swap {matched.name} (type={matched.product_type!r}). "
                    f"Criando produto-swap novo em vez de reusar."
                )

        # Quando é estrutura, evitamos cair na ação nua: só reusa match se ele
        # também for `estruturada`. Caso contrário, criamos um produto novo do
        # tipo `estruturada`.
        if result.matched_product_id and structure_kw:
            matched = db.query(Product).filter(Product.id == result.matched_product_id).first()
            if matched and (matched.product_type or "").lower() in ("estruturada", "estrutura", "estruturado"):
                logger.info(f"[AutoCreate] Match em produto estruturado existente: {matched.name} (id={matched.id})")
                return matched
            if matched:
                logger.info(
                    f"[AutoCreate] Material parece estrutura ({structure_kw!r}) mas resolver "
                    f"matched produto não-estruturado {matched.name} (type={matched.product_type!r}). "
                    f"Criando produto estruturado novo em vez de reusar."
                )

        if ticker and not structure_kw and not swap_kw and not portfolio_kw:
            existing = db.query(Product).filter(Product.ticker == ticker).first()
            if existing:
                logger.info(f"[AutoCreate] Produto já existe com ticker {ticker}: {existing.name} (id={existing.id})")
                return existing

        # Monta o nome do produto.
        # SWAP: nome humano é a operação inteira ("Troca: PETR4 → VALE3").
        # Estrutura: "POP sobre BEEF3" é mais útil que apenas "BEEF3".
        # CARTEIRA: usa fund_name/material_name/filename — NUNCA o ticker isolado
        # (carteira não tem ticker próprio).
        if swap_kw:
            product_name = (
                fund_name
                or material_name
                or filename_hint
                or (f"{swap_kw.title()} envolvendo {ticker}" if ticker else "Troca de ativos")
            )
            # Para swap NÃO anexamos "(TICKER)" — a operação não tem ticker próprio
            # e o nome já carrega a semântica (ex.: "Troca: PETR4 → VALE3").
        elif structure_kw and ticker:
            product_name = fund_name or f"{structure_kw.upper()} sobre {ticker}"
        elif portfolio_kw:
            product_name = (
                fund_name
                or material_name
                or filename_hint
                or "Carteira recomendada"
            )
        else:
            product_name = fund_name or ticker
            if ticker and ticker not in (product_name or ""):
                product_name = f"{product_name} ({ticker})"

        # Infere `product_type` canônico via helper compartilhado. Para estruturas,
        # swaps e carteiras forçamos o tipo (a heurística por ticker confundiria
        # os ativos subjacentes — BEEF3 viraria ação, PETR4/VALE3 também,
        # TVRI11 viraria FII).
        if swap_kw:
            product_type = "swap"
        elif structure_kw:
            product_type = "estruturada"
        elif portfolio_kw:
            product_type = "carteira"
        else:
            product_type = coerce_product_type(
                ticker=ticker,
                name=product_name,
                description=fund_name or document_type,
            )

        # Para swap E carteira, NÃO persistimos o ticker do underlying no
        # produto — isso reintroduziria o bug de captura em buscas por ticker.
        # O nome carrega a semântica e os tickers da composição entram via
        # MaterialProductLink/aliases.
        if swap_kw or portfolio_kw:
            ticker_to_persist = None
        else:
            ticker_to_persist = ticker

        # Para carteira a "gestora" extraída pela Vision normalmente é a
        # gestora do PRIMEIRO FII da composição (ruído). Carteira é
        # recomendação da casa, sem gestora própria.
        gestora_to_persist = None if portfolio_kw else gestora

        category = product_type if product_type and product_type != "outro" else "fii"

        # name_aliases: salva o fund_name original (nome da empresa/emissor) para
        # que perguntas como "Minerva" casem com BEEF3, "Petrobras" com PETR4 etc.
        aliases: list[str] = []
        if fund_name and fund_name.strip().upper() != (ticker or "").strip().upper():
            aliases.append(fund_name.strip())

        try:
            new_product = Product(
                name=product_name,
                ticker=ticker_to_persist,
                manager=gestora_to_persist,
                category=category,
                product_type=product_type,
                name_aliases=json.dumps(aliases, ensure_ascii=False) if aliases else "[]",
                status=ProductStatus.ACTIVE.value,
                description=(
                    f"Produto criado automaticamente a partir de upload de documento "
                    f"({document_type or 'N/A'}). Tipo inferido: {product_type}."
                    + (f" Estrutura detectada: {structure_kw.upper()}." if structure_kw else "")
                    + (
                        f" Operação de troca/swap detectada: {swap_kw.upper()}"
                        + (f" (ativo subjacente referenciado: {ticker})." if ticker else ".")
                        if swap_kw else ""
                    )
                    + (f" Carteira detectada ({portfolio_kw})." if portfolio_kw else "")
                ),
            )
            db.add(new_product)
            db.commit()
            db.refresh(new_product)
            logger.info(
                f"[AutoCreate] Produto criado: {new_product.name} "
                f"(ticker={ticker_to_persist}, id={new_product.id}, type={product_type}, "
                f"aliases={aliases}, swap_kw={swap_kw!r}, structure_kw={structure_kw!r}, "
                f"portfolio_kw={portfolio_kw!r})"
            )
            return new_product
        except Exception as e:
            db.rollback()
            # Para swap, ticker não é persistido — não há fallback por ticker possível.
            if ticker_to_persist:
                existing = db.query(Product).filter(Product.ticker == ticker_to_persist).first()
                if existing:
                    # Quando o material é estrutura, NÃO devolvemos a ação nua
                    # mesmo que ela exista por race condition — isso reintroduziria
                    # o bug "POP de BEEF3 cai na ação BEEF3".
                    if structure_kw and (existing.product_type or "").lower() not in (
                        "estruturada", "estrutura", "estruturado"
                    ):
                        logger.warning(
                            f"[AutoCreate] Erro na criação ({e}); fallback ignorado porque "
                            f"o produto existente (ticker {ticker_to_persist}) é "
                            f"{existing.product_type!r}, mas o material é estrutura "
                            f"({structure_kw!r})."
                        )
                        return None
                    logger.info(f"[AutoCreate] Produto já existia (concurrent): {existing.name}")
                    return existing
            logger.error(f"[AutoCreate] Erro ao criar produto: {e}")
            return None

    def _auto_create_product_from_material_name(self, db, mat, item):
        import re
        from database.models import Product
        from services.document_metadata_extractor import TICKER_PATTERN

        material_name = mat.name or ""
        ticker_match = TICKER_PATTERN.search(material_name.upper())
        ticker = f"{ticker_match.group(1)}{ticker_match.group(2)}" if ticker_match else None

        fund_name = material_name
        for prefix in ["Relatório gerencial ", "Relatório Gerencial ", "MP ", "Material Publicitário "]:
            if fund_name.startswith(prefix):
                fund_name = fund_name[len(prefix):]
                break

        fund_name = re.sub(r'\s*\(\d+\)\s*$', '', fund_name).strip()
        fund_name = re.sub(r'\s*\(vf\)\s*', ' ', fund_name, flags=re.IGNORECASE).strip()

        if not fund_name and not ticker:
            logger.warning(f"[AutoCreate] Não foi possível extrair nome/ticker do material: {material_name}")
            return None

        return self._auto_create_product(
            db=db,
            fund_name=fund_name,
            ticker=ticker,
            gestora=None,
            document_type="relatorio_gerencial",
        )

    def _create_product_links(self, db, item: "UploadQueueItem", mat, metadata):
        """Cria vínculos adicionais em material_product_links para cada ticker extra detectado."""
        from database.models import MaterialProductLink, Product
        additional = metadata.additional_tickers if hasattr(metadata, "additional_tickers") else []
        if not additional:
            return

        primary_id = mat.product_id

        # Quando o material primário é uma ESTRUTURA (POP/Collar/Fence...),
        # tickers extras são tipicamente o UNDERLYING ou ativos comparáveis.
        # Não devemos criar produtos-ação fantasmas (ex.: criar BEEF3 ação
        # quando o material é "POP de BEEF3"). Só linkamos a produtos
        # PRÉ-EXISTENTES desses tickers; não criamos novos.
        primary_product = db.query(Product).filter(Product.id == primary_id).first() if primary_id else None
        primary_is_structure = (
            primary_product is not None
            and (primary_product.product_type or "").lower() in ("estruturada", "estrutura", "estruturado")
        )
        primary_is_swap = (
            primary_product is not None
            and (primary_product.product_type or "").lower() == "swap"
        )
        material_looks_like_structure = bool(
            self._detect_structure_in_name(
                getattr(metadata, "fund_name", None),
                getattr(mat, "name", None),
            )
        )
        # Quando o material é troca/swap, tickers extras detectados são os
        # PRÓPRIOS ativos da troca (PETR4 e VALE3 em "Troca PETR4 por VALE3").
        # Não devemos criar/linkar produtos-ação individuais para eles —
        # isso fragmentaria a recomendação no RAG.
        material_looks_like_swap = bool(
            self._detect_swap_in_name(
                getattr(metadata, "fund_name", None),
                getattr(mat, "name", None),
            )
        )
        # Task #200 — Quando o material é uma CARTEIRA (e.g. "Carteira Seven
        # FII's"), os tickers da composição são FIIs INDIVIDUAIS já cadastrados
        # ou que serão cadastrados separadamente. NÃO devemos auto-criar
        # produtos-ação para eles — isso pollui o catálogo. Mantemos só o
        # link M:N quando o produto-FII já existe (útil para o RAG saber que
        # a carteira mencionou aquele FII).
        try:
            from services.product_ingestor import _is_portfolio_material
            primary_is_portfolio = _is_portfolio_material(
                mat,
                primary_product,
                getattr(metadata, "fund_name", None),
            )
        except Exception:
            primary_is_portfolio = False
        # Fallback redundante baseado só em metadata flag (caso o helper acima
        # falhe por import / shape inesperado).
        if not primary_is_portfolio:
            try:
                raw_extr = getattr(metadata, "raw_extraction", {}) or {}
                if isinstance(raw_extr, dict) and raw_extr.get("is_portfolio_document"):
                    primary_is_portfolio = True
            except Exception:
                pass

        skip_auto_create = (
            primary_is_structure or material_looks_like_structure
            or primary_is_swap or material_looks_like_swap
            or primary_is_portfolio
        )

        created_count = 0
        for ticker in additional:
            try:
                product = db.query(Product).filter(
                    Product.ticker.ilike(ticker),
                    Product.status == "ativo"
                ).first()

                if not product and not skip_auto_create:
                    product = self._auto_create_product(
                        db=db,
                        fund_name=None,
                        ticker=ticker,
                        gestora=metadata.gestora,
                        document_type=metadata.document_type,
                    )
                elif not product and skip_auto_create:
                    primary_kind_parts = []
                    if primary_is_structure:
                        primary_kind_parts.append("estrutura")
                    if primary_is_swap:
                        primary_kind_parts.append("swap")
                    if primary_is_portfolio:
                        primary_kind_parts.append("carteira")
                    primary_kind = "/".join(primary_kind_parts) or "especial"
                    logger.info(
                        f"[MultiProduct] Pulando auto-criação de produto ação para "
                        f"ticker {ticker!r} — material primário é {primary_kind} "
                        f"(primary_id={primary_id})."
                    )

                if not product or product.id == primary_id:
                    continue

                exists = db.query(MaterialProductLink).filter_by(
                    material_id=mat.id,
                    product_id=product.id
                ).first()
                if not exists:
                    link = MaterialProductLink(material_id=mat.id, product_id=product.id)
                    db.add(link)
                    try:
                        db.flush()
                        created_count += 1
                    except Exception as flush_err:
                        logger.warning(f"[MultiProduct] Falha ao vincular {ticker}: {flush_err}")
                        db.rollback()

            except Exception as link_err:
                logger.warning(f"[MultiProduct] Erro inesperado ao processar ticker {ticker}: {link_err}")

        if created_count:
            try:
                db.commit()
                item.add_log(
                    f"Vínculos multi-produto criados: {created_count} produto(s) adicional(is)",
                    "success"
                )
            except Exception as commit_err:
                logger.error(f"[MultiProduct] Erro ao salvar vínculos: {commit_err}")
                db.rollback()

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
        from database.database import SessionLocal, engine
        from database.models import (
            Material, Product, ContentBlock, PendingReviewItem,
            ProcessingStatus, DocumentProcessingJob, DocumentPageResult,
            ProcessingJobStatus, PageProcessingStatus, ContentBlockStatus
        )
        from services.product_ingestor import get_product_ingestor
        from services.document_metadata_extractor import get_metadata_extractor
        from services.document_processor import get_document_processor

        db_url_str = str(engine.url)
        is_sqlite = "sqlite" in db_url_str.lower()
        db_type = "SQLite" if is_sqlite else "PostgreSQL"
        safe_url = db_url_str.split("@")[-1] if "@" in db_url_str else db_url_str
        print(f"[UPLOAD_WORKER] Engine: {db_type} ({safe_url})")
        logger.info(f"[UPLOAD_WORKER] Engine: {db_type} ({safe_url})")
        if is_sqlite:
            print("[UPLOAD_WORKER] ALERTA CRÍTICO: Worker conectado a SQLite!")
            logger.error("[UPLOAD_WORKER] ALERTA CRÍTICO: Worker conectado a SQLite! Dados NÃO serão persistidos no PostgreSQL.")

        db = SessionLocal()
        try:
            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if not mat:
                raise Exception(f"Material id={item.material_id} não encontrado no banco ({db_type})")

            mat.processing_status = ProcessingStatus.PROCESSING.value
            db.commit()

            # REVALIDA vínculo pré-existente: se o material veio da confirmação
            # já apontando para um produto-ação mas filename/material.name dizem
            # que é estrutura (POP/Collar/Fence...), zera o vínculo aqui para
            # que `_auto_create_product` (lógica abaixo) crie a estrutura nova.
            if mat.product_id:
                # Inclui também extracted_metadata (fund_name/document_type) quando
                # disponível — cobre casos em que o material foi pré-processado e o
                # tipo de documento já tem o termo "POP" mas o filename não.
                _meta_fund_name = None
                _meta_doc_type = None
                try:
                    if mat.extracted_metadata:
                        import json as _json
                        _md = _json.loads(mat.extracted_metadata)
                        _meta_fund_name = _md.get("fund_name") if isinstance(_md, dict) else None
                        _meta_doc_type = _md.get("document_type") if isinstance(_md, dict) else None
                except Exception:
                    pass

                preexisting_struct_kw = self._detect_structure_in_name(
                    item.filename,
                    mat.name,
                    getattr(mat, "source_filename", None),
                    _meta_fund_name,
                    _meta_doc_type,
                )
                preexisting_swap_kw = self._detect_swap_in_name(
                    item.filename,
                    mat.name,
                    getattr(mat, "source_filename", None),
                    _meta_fund_name,
                    _meta_doc_type,
                )
                if preexisting_swap_kw:
                    linked = db.query(Product).filter(Product.id == mat.product_id).first()
                    linked_type = (linked.product_type or "").lower() if linked else ""
                    if linked and linked_type != "swap":
                        msg = (
                            f"[SWAP_GUARD] layer=worker filename={item.filename!r} "
                            f"matched_product={{id:{linked.id}, name:{linked.name!r}, "
                            f"type:{linked.product_type!r}}} decision=rejected "
                            f"reason='material parece troca/swap ({preexisting_swap_kw!r}) "
                            f"mas vínculo é {linked.product_type or 'sem tipo'}'"
                        )
                        print(msg)
                        logger.warning(msg)
                        item.add_log(
                            f"Vínculo descartado: material parece troca/swap "
                            f"({preexisting_swap_kw!r}) mas estava ligado a "
                            f"{linked.name} ({linked_type or 'sem tipo'}). "
                            f"Criaremos um produto-swap novo.",
                            "warning",
                        )
                        try:
                            from database.models import MaterialProductLink as _MPL
                            db.query(_MPL).filter(
                                _MPL.material_id == mat.id,
                                _MPL.product_id == linked.id,
                            ).delete()
                        except Exception as link_del_err:
                            logger.warning(
                                f"[UPLOAD_WORKER] Falha ao remover MaterialProductLink "
                                f"antigo (swap guard): {link_del_err}"
                            )
                        mat.product_id = None
                        db.commit()

                if preexisting_struct_kw:
                    linked = db.query(Product).filter(Product.id == mat.product_id).first()
                    linked_type = (linked.product_type or "").lower() if linked else ""
                    if linked and linked_type not in (
                        "estruturada", "estrutura", "estruturado"
                    ):
                        msg = (
                            f"[STRUCTURE_GUARD] layer=worker filename={item.filename!r} "
                            f"matched_product={{id:{linked.id}, name:{linked.name!r}, "
                            f"type:{linked.product_type!r}}} decision=rejected "
                            f"reason='material parece estrutura ({preexisting_struct_kw!r}) "
                            f"mas vínculo é {linked.product_type or 'sem tipo'}'"
                        )
                        print(msg)
                        logger.warning(msg)
                        item.add_log(
                            f"Vínculo descartado: material parece estrutura "
                            f"({preexisting_struct_kw!r}) mas estava ligado a "
                            f"{linked.name} ({linked_type or 'sem tipo'}). "
                            f"Criaremos um produto novo.",
                            "warning",
                        )
                        # Limpa link MaterialProductLink antigo do produto errado.
                        try:
                            from database.models import MaterialProductLink as _MPL
                            db.query(_MPL).filter(
                                _MPL.material_id == mat.id,
                                _MPL.product_id == linked.id,
                            ).delete()
                        except Exception as link_del_err:
                            logger.warning(
                                f"[UPLOAD_WORKER] Falha ao remover MaterialProductLink "
                                f"antigo: {link_del_err}"
                            )
                        mat.product_id = None
                        db.commit()

            start_page = 0
            processing_job = None

            if item.is_resume and item.existing_job_id:
                processing_job = db.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.id == item.existing_job_id
                ).first()

                if processing_job:
                    start_page = processing_job.last_processed_page or 0

                    has_blocks = db.query(ContentBlock).filter(
                        ContentBlock.material_id == item.material_id
                    ).count() > 0
                    if not has_blocks or start_page >= (processing_job.total_pages or 0):
                        start_page = 0
                        processing_job.last_processed_page = 0
                        processing_job.processed_pages = 0
                        print(f"[UPLOAD_WORKER] Material {item.material_id}: 0 blocos ou start_page >= total_pages — reprocessando do zero")

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
                # IDEMPOTÊNCIA: se este material já tem blocos/jobs de uma rodada
                # anterior interrompida (worker morreu, reupload manual, etc.),
                # limpa esses artefatos antes de iniciar do zero. Sem isso, a
                # nova rodada cria blocos duplicados e pode falhar com erros de
                # uniqueness ao reindexar embeddings. Preservamos `material_files`,
                # `material_product_links` e `material.product_id` — só os artefatos
                # derivados do processamento são removidos.
                from database.models import ContentBlock as _CB
                existing_blocks = db.query(_CB).filter(
                    _CB.material_id == item.material_id
                ).count()
                existing_jobs = db.query(DocumentProcessingJob).filter(
                    DocumentProcessingJob.material_id == item.material_id
                ).count()
                if existing_blocks or existing_jobs:
                    logger.info(
                        f"[UPLOAD_WORKER] Material {item.material_id} tem "
                        f"{existing_blocks} blocos e {existing_jobs} jobs "
                        f"de rodada anterior — limpando antes de reprocessar."
                    )
                    try:
                        from services.material_cleanup import purge_processing_artifacts
                        purge_processing_artifacts(db, item.material_id)
                        # Reabre o material após o commit do purge.
                        mat = db.query(Material).filter(
                            Material.id == item.material_id
                        ).first()
                        if not mat:
                            raise Exception(
                                f"Material {item.material_id} desapareceu após "
                                f"limpeza de artefatos órfãos."
                            )
                    except Exception as orphan_err:
                        logger.error(
                            f"[UPLOAD_WORKER] Falha ao limpar artefatos órfãos do "
                            f"material {item.material_id}: "
                            f"{type(orphan_err).__name__}: {orphan_err}"
                        )
                        raise

                with open(item.file_path, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()

                duplicate = db.query(Material).filter(
                    Material.file_hash == file_hash,
                    Material.file_hash != None,
                    Material.id != item.material_id
                ).first()
                if duplicate and duplicate.processing_status == ProcessingStatus.SUCCESS.value:
                    dup_date = duplicate.created_at.strftime('%d/%m/%Y') if duplicate.created_at else 'data desconhecida'
                    dup_msg = (
                        f"Arquivo idêntico já processado com sucesso como "
                        f"'{duplicate.name}' em {dup_date}. Upload duplicado bloqueado."
                    )
                    item.add_log(f"Bloqueado: {dup_msg}", "error")
                    self._broadcast_event({
                        "type": "error", "upload_id": item.upload_id,
                        "message": dup_msg,
                        "existing_material_id": duplicate.id
                    })
                    logger.warning(f"[UPLOAD] Duplicata bloqueada: file_hash={file_hash[:12]}... material_id_existente={duplicate.id}")
                    # Material fantasma: descarta TODAS as tabelas filhas via helper
                    # central. O cleanup parcial anterior só limpava 3 das ~9 tabelas
                    # e quebrava com ForeignKeyViolation em re-uploads de swap/estrutura
                    # (porque a pré-análise já criou MaterialProductLink, blocos, etc.).
                    try:
                        from services.material_cleanup import purge_material_dependencies
                        purge_material_dependencies(db, mat.id)
                        db.delete(mat)
                        db.commit()
                        logger.info(
                            f"[UPLOAD] Material fantasma {item.material_id} deletado "
                            f"(duplicata de {duplicate.id})"
                        )
                    except Exception as del_err:
                        db.rollback()
                        logger.warning(
                            f"[UPLOAD] Não foi possível deletar material fantasma "
                            f"{item.material_id}: {type(del_err).__name__}: {del_err}"
                        )
                        # Re-fetch porque o purge pode ter feito rollback e deixado
                        # `mat` em estado detached/transient.
                        mat = db.query(Material).filter(Material.id == item.material_id).first()
                        if mat:
                            mat.processing_status = (
                                ProcessingStatus.FAILED.value
                                if hasattr(ProcessingStatus, 'FAILED') else "failed"
                            )
                            mat.processing_error = dup_msg
                            db.commit()
                    item.status = UploadStatus.FAILED
                    item.error = dup_msg
                    self._update_db_status(item)
                    return
                elif duplicate:
                    dup_date = duplicate.created_at.strftime('%d/%m/%Y') if duplicate.created_at else 'data desconhecida'
                    dup_msg = (
                        f"Arquivo idêntico encontrado como "
                        f"'{duplicate.name}' em {dup_date} (status: {duplicate.processing_status}). "
                        f"Reprocessando."
                    )
                    item.add_log(f"Aviso: {dup_msg}", "warning")
                    self._broadcast_event({
                        "type": "warning", "upload_id": item.upload_id,
                        "message": dup_msg,
                        "existing_material_id": duplicate.id
                    })
                    logger.warning(f"[UPLOAD] Duplicata com status={duplicate.processing_status}: file_hash={file_hash[:12]}... Reprocessando.")

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

                try:
                    from database.models import MaterialFile as MF
                    has_mf = db.query(MF).filter(MF.material_id == mat.id).first()
                    if not has_mf and os.path.exists(item.file_path):
                        with open(item.file_path, 'rb') as pdf_f:
                            pdf_bytes = pdf_f.read()
                        if pdf_bytes:
                            new_mf = MF(
                                material_id=mat.id,
                                filename=item.filename or "documento.pdf",
                                content_type="application/pdf",
                                file_data=pdf_bytes,
                                file_size=len(pdf_bytes),
                            )
                            db.add(new_mf)
                            db.commit()
                            print(f"[UPLOAD_WORKER] material_files populado antecipadamente para material_id={mat.id} ({len(pdf_bytes)} bytes)")
                except Exception as mf_err:
                    db.rollback()
                    logger.warning(f"[UPLOAD_WORKER] Erro ao popular material_files antecipadamente: {mf_err}")

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
                    existing_products = db.query(Product).all()
                    existing_products_list = [{"id": p.id, "name": p.name, "ticker": p.ticker} for p in existing_products]

                    metadata = extractor.extract_metadata(
                        pdf_path=item.file_path,
                        pages_to_analyze=[0, 1, 2],
                        existing_products=existing_products_list
                    )

                    if mat:
                        mat.extracted_metadata = json.dumps(metadata.to_dict(), ensure_ascii=False)
                        db.commit()

                    all_found = [metadata.ticker] if metadata.ticker else []
                    all_found += [t for t in (metadata.additional_tickers or []) if t not in all_found]
                    tickers_str = ", ".join(all_found) if all_found else "N/A"
                    item.add_log(
                        f"Metadados: {metadata.fund_name or 'N/A'} | Tickers: {tickers_str}",
                        "info"
                    )
                    item.additional_tickers = metadata.additional_tickers or []

                    # CRÍTICO: captura se o material já tem produto CONFIRMADO pelo usuário.
                    # O guard acima (linhas 832-931) pode ter zerado product_id quando detectou
                    # captura errada (estrutura linkada a ação). Se product_id ainda está setado
                    # aqui, o usuário confirmou explicitamente esse vínculo na tela do SmartUpload
                    # OU o vínculo sobreviveu ao guard — em ambos os casos o resolver NÃO deve
                    # sobrescrever. Bug corrigido: "WEGE3 material criou novo produto mas o worker
                    # re-linkava para 'Research WEGE3' existente via ProductResolver".
                    _confirmed_product_id = mat.product_id  # None se guard zerou, int se confirmado

                    if metadata.ticker or metadata.fund_name:
                        from services.product_resolver import get_product_resolver
                        resolver = get_product_resolver(db)
                        resolve_result = resolver.resolve(
                            fund_name=metadata.fund_name,
                            ticker=metadata.ticker,
                            gestora=metadata.gestora,
                            confidence=metadata.confidence,
                        )

                        # GUARDA-CHUVA ANTI-CAPTURA POR AÇÃO SUBJACENTE:
                        # Se o material é uma ESTRUTURA (POP/Collar/Fence...) e o resolver
                        # encontrou um produto existente, só aceitamos o vínculo se o
                        # produto também for `estruturada`. Caso contrário, descartamos o
                        # match e forçamos `_auto_create_product` (que sabe criar a estrutura
                        # nova). Sem essa guarda, "POP de MYPK3" cai no produto research
                        # MYPK3 (ação) já cadastrado.
                        structure_kw = self._detect_structure_in_name(
                            metadata.fund_name,
                            metadata.document_type,
                            getattr(item, "filename", None),
                            mat.name if mat else None,
                        )
                        if structure_kw and resolve_result.matched_product_id:
                            matched_existing = db.query(Product).filter(
                                Product.id == resolve_result.matched_product_id
                            ).first()
                            matched_type = (
                                (matched_existing.product_type or "").lower()
                                if matched_existing else ""
                            )
                            if matched_type not in ("estruturada", "estrutura", "estruturado"):
                                item.add_log(
                                    f"Match descartado: material é estrutura "
                                    f"({structure_kw!r}) mas o produto encontrado "
                                    f"({matched_existing.name if matched_existing else '?'}) "
                                    f"é {matched_type or 'sem tipo'} — criando produto novo.",
                                    "info"
                                )
                                logger.info(
                                    f"[UploadQueue] Estrutura {structure_kw!r}: rejeitando "
                                    f"match com produto não-estruturado "
                                    f"id={resolve_result.matched_product_id} "
                                    f"({matched_type!r}) — vai criar produto novo."
                                )
                                # Substitui o resultado por um "no-match" para cair no else
                                # (is_confident é uma property derivada de match_type).
                                from services.product_resolver import ResolverResult
                                resolve_result = ResolverResult(
                                    matched_product_id=None,
                                    matched_product_name=None,
                                    matched_product_ticker=None,
                                    match_type="rejected_structure_mismatch",
                                    match_confidence=0.0,
                                )

                        # GUARDA-CHUVA ANTI-CAPTURA POR FII DA COMPOSIÇÃO
                        # (Task #200, code-review):
                        # Quando o material é uma CARTEIRA (`is_portfolio_document`
                        # marcado pelo extractor) e o resolver casou com um
                        # produto que tem ticker (= é um FII/ação individual)
                        # ou cujo product_type não é "carteira", REJEITAMOS o
                        # match. Sem isso, "Carteira Seven FII's" cuja Vision
                        # devolveu fund_name="TVRI11" (ou que casou por nome
                        # parcial com um FII existente) ficaria vinculada ao
                        # produto FII errado — exatamente o bug que a Task #200
                        # corrige no pipeline.
                        is_portfolio_meta = bool(
                            (metadata.raw_extraction or {}).get("is_portfolio_document")
                        )
                        if is_portfolio_meta and resolve_result.matched_product_id:
                            matched_existing = db.query(Product).filter(
                                Product.id == resolve_result.matched_product_id
                            ).first()
                            matched_type = (
                                (matched_existing.product_type or "").lower()
                                if matched_existing else ""
                            )
                            matched_ticker = (
                                (matched_existing.ticker or "").strip()
                                if matched_existing else ""
                            )
                            if matched_ticker or matched_type != "carteira":
                                item.add_log(
                                    f"Match descartado: material é CARTEIRA mas "
                                    f"o produto encontrado "
                                    f"({matched_existing.name if matched_existing else '?'}) "
                                    f"tem ticker={matched_ticker or 'NULL'} / "
                                    f"type={matched_type or 'sem tipo'} — "
                                    f"criando produto-carteira novo.",
                                    "info"
                                )
                                logger.info(
                                    f"[UploadQueue] Carteira: rejeitando match com "
                                    f"produto não-carteira id="
                                    f"{resolve_result.matched_product_id} "
                                    f"(ticker={matched_ticker!r}, type={matched_type!r}) — "
                                    f"vai criar produto-carteira novo."
                                )
                                from services.product_resolver import ResolverResult
                                resolve_result = ResolverResult(
                                    matched_product_id=None,
                                    matched_product_name=None,
                                    matched_product_ticker=None,
                                    match_type="rejected_portfolio_mismatch",
                                    match_confidence=0.0,
                                )

                        # Se o material já veio com produto confirmado pelo usuário (SmartUpload),
                        # respeitamos o vínculo e não deixamos o resolver sobrescrever.
                        if _confirmed_product_id is not None:
                            confirmed_prod = db.query(Product).filter(
                                Product.id == _confirmed_product_id
                            ).first()
                            if confirmed_prod:
                                item.product_name = confirmed_prod.name
                                item.product_ticker = confirmed_prod.ticker
                                item.add_log(
                                    f"Produto já confirmado pelo usuário: {confirmed_prod.name} "
                                    f"({confirmed_prod.ticker or 'sem ticker'}) — resolver não sobrescreve.",
                                    "info"
                                )
                                logger.info(
                                    f"[UploadQueue] Produto id={_confirmed_product_id} "
                                    f"confirmado pelo usuário — ignorando resultado do resolver "
                                    f"(would have matched: {resolve_result.matched_product_name!r})."
                                )
                            # Mesmo sem sobrescrever produto, ainda criamos links adicionais
                            # para tickers secundários encontrados nos metadados.

                        elif resolve_result.is_confident:
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
                            new_product = self._auto_create_product(
                                db=db,
                                fund_name=metadata.fund_name,
                                ticker=metadata.ticker,
                                gestora=metadata.gestora,
                                document_type=metadata.document_type,
                                filename_hint=getattr(item, "filename", None),
                                material_name=mat.name if mat else None,
                            )
                            if new_product:
                                mat.product_id = new_product.id
                                mat.processing_status = "processing"
                                db.commit()
                                item.product_name = new_product.name
                                item.product_ticker = new_product.ticker
                                item.add_log(
                                    f"Produto criado automaticamente: {new_product.name} "
                                    f"({new_product.ticker or 'sem ticker'})",
                                    "success"
                                )
                            else:
                                item.add_log(
                                    f"Metadados insuficientes para criar produto: "
                                    f"{metadata.fund_name or 'N/A'}",
                                    "warning"
                                )
                    self._create_product_links(db, item, mat, metadata)

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
                if processing_job.last_processed_page and processing_job.last_processed_page >= page_num:
                    return
                processing_job.last_processed_page = page_num
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

            from sqlalchemy import text as sql_text
            verify_count = db.execute(sql_text(
                f"SELECT COUNT(*) FROM content_blocks WHERE material_id = {item.material_id}"
            )).scalar()
            print(f"[UPLOAD_WORKER] Verificação pós-processamento: material_id={item.material_id}, blocos no banco={verify_count}")

            mat = db.query(Material).filter(Material.id == item.material_id).first()
            if mat:
                if verify_count > 0:
                    mat.processing_status = ProcessingStatus.SUCCESS.value
                    mat.processing_error = None
                    db.commit()
                    print(f"[UPLOAD_WORKER] Material {item.material_id} marcado como success ({verify_count} blocos), product_id={mat.product_id}")
                else:
                    mat.processing_status = ProcessingStatus.FAILED.value if hasattr(ProcessingStatus, 'FAILED') else "failed"
                    mat.processing_error = "Processamento completou mas nenhum bloco de conteúdo foi gerado. Verifique o PDF."
                    db.commit()
                    print(f"[UPLOAD_WORKER] Material {item.material_id} marcado como FAILED — 0 blocos gerados")
                    item.status = UploadStatus.FAILED
                    item.error = "Nenhum bloco de conteúdo gerado"
                    self._update_db_status(item)
                    self._broadcast_event({
                        "type": "error",
                        "upload_id": item.upload_id,
                        "message": "Processamento completou mas nenhum conteúdo foi extraído do PDF.",
                        "material_id": item.material_id
                    })
                    return

                from services.product_ingestor import _ensure_material_file
                _ensure_material_file(
                    db=db,
                    material_id=item.material_id,
                    pdf_path=item.file_path,
                    filename=item.filename or "documento.pdf"
                )

                if not mat.product:
                    auto_product = self._auto_create_product_from_material_name(db, mat, item)
                    if auto_product:
                        mat.product_id = auto_product.id
                        db.commit()
                        item.product_name = auto_product.name
                        item.product_ticker = auto_product.ticker
                        item.add_log(
                            f"Produto criado a partir do nome do material: {auto_product.name} "
                            f"({auto_product.ticker or 'sem ticker'})",
                            "success"
                        )

                try:
                    from api.endpoints.products import auto_publish_if_ready
                    published = auto_publish_if_ready(mat, db)
                    if published:
                        item.add_log(f"Material auto-publicado com sucesso", "success")
                    else:
                        pending = db.query(ContentBlock).filter(
                            ContentBlock.material_id == mat.id,
                            ContentBlock.status == ContentBlockStatus.PENDING_REVIEW.value
                        ).count()
                        logger.info(f"[UPLOAD_WORKER] Material {item.material_id} não auto-publicado: "
                                    f"publish_status={mat.publish_status}, pending_blocks={pending}")
                except Exception as pub_err:
                    import traceback
                    logger.error(f"[UPLOAD_WORKER] Erro ao auto-publicar material {item.material_id}: {pub_err}\n"
                                 f"{traceback.format_exc()}")

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
            logger.error(f"[UPLOAD_WORKER] ERRO no processamento material_id={item.material_id}: {e}", exc_info=True)
            try:
                db.rollback()
                mat = db.query(Material).filter(Material.id == item.material_id).first()
                if mat:
                    mat.processing_status = ProcessingStatus.FAILED.value if hasattr(ProcessingStatus, 'FAILED') else "failed"
                    mat.processing_error = str(e)[:500]
                    db.commit()
            except Exception as inner_e:
                logger.error(f"[UPLOAD_WORKER] Erro ao marcar material como falho: {inner_e}")
            self._update_db_status(item)
            raise
        finally:
            db.close()


upload_queue = UploadQueue.get_instance()
