"""
Motor de auto-sincronização FNET → SmartUpload.

Para cada fundo monitorado:
1. Consulta a API pública do FNET buscando documentos entregues no mês corrente
   (e, opcionalmente, no mês anterior para cobrir entregas em atraso).
2. Filtra apenas os tipos de documento configurados (default: "Informe Mensal"
   e "Relatório Gerencial").
3. Dedup por (fund_name, reference_month, document_type) — se já há linha
   `FnetSyncLog` com status `uploaded`/`downloaded` para esse trio, pula.
4. Para cada documento novo: baixa o PDF, cria `Material` + `MaterialFile`,
   enfileira no `UploadQueue` (mesmo pipeline do botão "SmartUpload" da UI)
   e grava `FnetSyncLog`.

Idempotente: rodar duas vezes seguidas no mesmo dia não cria duplicatas.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from database.database import SessionLocal
from database.models import (
    FnetMonitoredFund,
    FnetSyncLog,
    Material,
    ProcessingStatus,
)
from services.fnet_client import FnetClient, FnetClientError, FnetDocument

logger = logging.getLogger(__name__)


DEFAULT_DOCUMENT_TYPES = ["Informe Mensal", "Relatório Gerencial"]
UPLOAD_DIR_QUEUE = "uploads/materials"


@dataclass
class FundSyncResult:
    fund_id: int
    fund_name: str
    cnpj: str
    docs_found: int = 0
    docs_new: int = 0
    docs_skipped_duplicate: int = 0
    docs_downloaded: int = 0
    docs_failed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_id": self.fund_id,
            "fund_name": self.fund_name,
            "cnpj": self.cnpj,
            "docs_found": self.docs_found,
            "docs_new": self.docs_new,
            "docs_skipped_duplicate": self.docs_skipped_duplicate,
            "docs_downloaded": self.docs_downloaded,
            "docs_failed": self.docs_failed,
            "errors": self.errors[:10],
        }


@dataclass
class SyncRunResult:
    started_at: datetime
    finished_at: Optional[datetime] = None
    funds_processed: int = 0
    docs_downloaded: int = 0
    docs_failed: int = 0
    docs_skipped_duplicate: int = 0
    per_fund: list[FundSyncResult] = field(default_factory=list)
    fatal_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "funds_processed": self.funds_processed,
            "docs_downloaded": self.docs_downloaded,
            "docs_failed": self.docs_failed,
            "docs_skipped_duplicate": self.docs_skipped_duplicate,
            "per_fund": [f.to_dict() for f in self.per_fund],
            "fatal_error": self.fatal_error,
        }


def _normalize_cnpj(cnpj: str) -> str:
    """Remove pontuação do CNPJ (mantém apenas dígitos)."""
    return "".join(c for c in (cnpj or "") if c.isdigit())


def _format_cnpj_br(cnpj_digits: str) -> str:
    """Formata 14 dígitos como XX.XXX.XXX/XXXX-XX (formato esperado pela API FNET)."""
    s = _normalize_cnpj(cnpj_digits)
    if len(s) != 14:
        return cnpj_digits  # devolve original se inválido — FNET pode aceitar variações
    return f"{s[0:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:14]}"


def _current_month_window() -> tuple[date, date]:
    """
    Retorna (start_date, end_date) cobrindo APENAS o mês corrente de calendário
    (do dia 1 até hoje). Sincronização retroativa de meses anteriores está
    explicitamente fora de escopo (fnet-backend.md §Out of scope).
    """
    today = date.today()
    return date(today.year, today.month, 1), today


def _matches_target_types(doc: FnetDocument, target_types: list[str]) -> bool:
    """
    Verifica se o documento bate com algum dos tipos-alvo. Comparação case-insensitive
    e tolerante a acentos. Bate em `categoria_documento` ou `tipo_documento`.
    """
    import unicodedata

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.lower().strip()

    cat = norm(doc.categoria_documento)
    tipo = norm(doc.tipo_documento)
    for t in target_types:
        tn = norm(t)
        if not tn:
            continue
        if tn in cat or tn in tipo or cat in tn or tipo in tn:
            return True
    return False


def _build_material_name(fund_name: str, tipo_documento: str, reference_ym: str) -> str:
    """Nome humano consistente, ex.: 'MAXI RENDA - Informe Mensal 2026-05'."""
    parts = [fund_name.strip()]
    if tipo_documento:
        parts.append(tipo_documento.strip())
    parts.append(reference_ym)
    return " - ".join(p for p in parts if p)


async def sync_single_fund(
    fund: FnetMonitoredFund,
    client: Optional[FnetClient] = None,
    db_factory=SessionLocal,
) -> FundSyncResult:
    """
    Sincroniza um único fundo monitorado. Cada documento é processado em sua
    própria transação para que uma falha pontual não derrube o restante.
    """
    result = FundSyncResult(
        fund_id=fund.id,
        fund_name=fund.fund_name,
        cnpj=fund.cnpj,
    )

    client = client or FnetClient()

    # Tipos de documento configurados (ou default)
    target_types: list[str] = DEFAULT_DOCUMENT_TYPES
    if fund.document_types:
        try:
            parsed = json.loads(fund.document_types)
            if isinstance(parsed, list) and parsed:
                target_types = [str(x) for x in parsed]
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "[FNET-SYNC] document_types inválido em fund_id=%s: %s — usando default",
                fund.id,
                exc,
            )

    start_date, end_date = _current_month_window()
    cnpj_formatted = _format_cnpj_br(fund.cnpj)

    # 1) Lista documentos no FNET
    try:
        documents = await client.list_documents(
            cnpj=cnpj_formatted,
            date_start=start_date,
            date_end=end_date,
        )
    except FnetClientError as exc:
        msg = (
            f"FNET API falhou para {fund.fund_name} (CNPJ {cnpj_formatted}): "
            f"{type(exc).__name__}: {exc}"
        )
        # logger.exception() inclui traceback completo — útil para diagnosticar
        # falhas que vão além da mensagem curta persistida em error_message
        # (limitada a ~500 chars). NÃO altera o que vai para o banco.
        logger.exception("[FNET-SYNC] %s", msg)
        result.errors.append(msg)
        # Persiste log de falha no NÍVEL DO FUNDO para auditabilidade (ex.:
        # timeouts, CNPJ inválido, FNET fora do ar). Idempotente por mês via
        # UPSERT em (fund_name, reference_month, document_type=__fund_level__).
        _persist_fund_level_failure(db_factory, fund, msg)
        return result
    except Exception as exc:
        # Defensive: erros inesperados ao listar (ex.: parse falhou) também
        # devem ficar auditáveis sem derrubar os outros fundos do run.
        msg = (
            f"Erro inesperado ao listar docs FNET de {fund.fund_name} "
            f"(CNPJ {cnpj_formatted}): {type(exc).__name__}: {exc}"
        )
        logger.exception("[FNET-SYNC] %s", msg)
        result.errors.append(msg)
        _persist_fund_level_failure(db_factory, fund, msg)
        return result

    # 2) Filtra por tipo
    relevant = [d for d in documents if _matches_target_types(d, target_types)]
    result.docs_found = len(relevant)

    # 3) Para cada doc: dedup + download + upload
    for doc in relevant:
        try:
            await _process_single_document(
                doc=doc,
                fund=fund,
                client=client,
                result=result,
                db_factory=db_factory,
            )
        except Exception as exc:
            # Salvaguarda final: _process_single_document gerencia seus
            # próprios logs (claim/mark_failed/mark_downloaded). Este except
            # captura apenas erros realmente inesperados (ex.: bug, OOM).
            # Não tentamos persistir log aqui porque pode não haver linha
            # reservada — se o claim foi feito antes do crash, ficará em
            # 'pending' e será re-reivindicada pelo próximo run.
            msg = (
                f"Erro inesperado em doc FNET id={doc.id} "
                f"({doc.tipo_documento} {doc.data_referencia}): "
                f"{type(exc).__name__}: {exc}"
            )
            logger.exception("[FNET-SYNC] %s", msg)
            result.errors.append(msg)
            result.docs_failed += 1

    return result


async def _process_single_document(
    doc: FnetDocument,
    fund: FnetMonitoredFund,
    client: FnetClient,
    result: FundSyncResult,
    db_factory,
) -> None:
    reference_ym = doc.reference_month_ym()
    if not reference_ym:
        msg = (
            f"Documento FNET id={doc.id} sem dataReferencia parseável "
            f"({doc.data_referencia!r}) — pulando."
        )
        logger.warning("[FNET-SYNC] %s", msg)
        result.errors.append(msg)
        result.docs_failed += 1
        return

    # Nome do fundo usado para dedup: preferir nome configurado pelo admin
    # (estável, controlado) em vez do retorno do FNET (que pode variar entre
    # documentos do mesmo fundo).
    dedup_fund_name = fund.fund_name.strip()
    dedup_doc_type = doc.tipo_documento.strip() or doc.categoria_documento.strip()

    # 3.a) CLAIM ATÔMICO via UPSERT — única fonte de verdade para dedup.
    # - Se a linha não existe, insere com status='pending' e retorna id (claim).
    # - Se existe com status terminal (success/skipped), retorna NADA
    #   (linha já bate, sem update) → tratamos como duplicata.
    # - Se existe com status retriável (pending expirado/failed), promove a 'pending'
    #   e retorna id (re-claim) → permite re-tentativas após falha sem violar UNIQUE.
    # Dois workers concorrentes não podem ambos receber id: o UPSERT é atômico no PG.
    # Hash determinístico do documento — protege contra reprocessamento
    # mesmo se chaves semânticas mudarem (ex.: tipo do doc reclassificado).
    document_hash = _compute_document_hash(fund.cnpj, doc.id)

    claimed_log_id = _claim_document_for_processing(
        db_factory=db_factory,
        fund=fund,
        doc=doc,
        reference_ym=reference_ym,
        dedup_fund_name=dedup_fund_name,
        dedup_doc_type=dedup_doc_type,
        document_hash=document_hash,
    )
    if claimed_log_id is None:
        # Outra run já processou (status terminal) — dedup hit clássico.
        result.docs_skipped_duplicate += 1
        logger.debug(
            "[FNET-SYNC] Dedup hit (claim recusado): %s | %s | %s",
            dedup_fund_name,
            reference_ym,
            dedup_doc_type,
        )
        return

    result.docs_new += 1

    # 3.b) Download (fora da transação DB para não segurar conexão)
    try:
        pdf_bytes, suggested_filename = await client.download_document(doc.id)
    except FnetClientError as exc:
        msg = (
            f"Falha ao baixar PDF FNET id={doc.id} ({dedup_doc_type} {reference_ym}): "
            f"{exc}"
        )
        logger.error("[FNET-SYNC] %s", msg)
        result.errors.append(msg)
        result.docs_failed += 1
        _mark_log_failed(db_factory, claimed_log_id, msg)
        return

    # 3.c) Criar Material + MaterialFile + enfileirar no UploadQueue
    try:
        material_id, upload_id = await asyncio.to_thread(
            _create_material_and_enqueue,
            fund=fund,
            doc=doc,
            reference_ym=reference_ym,
            dedup_doc_type=dedup_doc_type,
            pdf_bytes=pdf_bytes,
            suggested_filename=suggested_filename,
        )
    except Exception as exc:
        msg = (
            f"Falha ao criar Material/enqueue para doc FNET id={doc.id}: "
            f"{type(exc).__name__}: {exc}"
        )
        logger.exception("[FNET-SYNC] %s", msg)
        result.errors.append(msg)
        result.docs_failed += 1
        _mark_log_failed(db_factory, claimed_log_id, msg)
        return

    # 3.d) Sucesso — promove o claim a 'success' com material_id
    _mark_log_success(db_factory, claimed_log_id, material_id)
    result.docs_downloaded += 1
    logger.info(
        "[FNET-SYNC] ✅ Enfileirado: %s | %s | %s | material_id=%s upload_id=%s log_id=%s",
        fund.fund_name,
        dedup_doc_type,
        reference_ym,
        material_id,
        upload_id,
        claimed_log_id,
    )


def _create_material_and_enqueue(
    *,
    fund: FnetMonitoredFund,
    doc: FnetDocument,
    reference_ym: str,
    dedup_doc_type: str,
    pdf_bytes: bytes,
    suggested_filename: str,
) -> tuple[int, str]:
    """
    Executado em thread separada (DB sync + filesystem I/O). Cria o Material,
    salva o MaterialFile, persiste o PDF em uploads/materials/ e adiciona um
    item à UploadQueue. Retorna (material_id, upload_id).
    """
    # Imports tardios para evitar ciclos durante o startup do app.
    from api.endpoints.products import (
        _save_file_to_db,
        find_or_create_product_from_name,
    )
    from services.upload_queue import UploadQueue, UploadQueueItem

    os.makedirs(UPLOAD_DIR_QUEUE, exist_ok=True)

    db: Session = SessionLocal()
    try:
        # Resolve produto: preferir product_id explícito do fundo monitorado;
        # senão tenta resolver por nome (find_or_create_product_from_name).
        product_id: Optional[int] = fund.product_id
        if product_id is None:
            auto_prod = find_or_create_product_from_name(
                db,
                material_name=fund.fund_name,
                gestora=None,
                document_type=dedup_doc_type,
            )
            if auto_prod is not None:
                product_id = auto_prod.id

        material_name = _build_material_name(
            fund_name=fund.fund_name,
            tipo_documento=dedup_doc_type,
            reference_ym=reference_ym,
        )

        # Tipo do material — mapeamento simples por tipo do documento.
        tipo_lower = dedup_doc_type.lower()
        if "relat" in tipo_lower and "gerenc" in tipo_lower:
            material_type = "relatorio_gerencial"
        else:
            material_type = "outro"

        # Hash do conteúdo para o filtro de duplicatas do batch_upload (defensivo).
        import hashlib

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

        material = Material(
            product_id=product_id,
            material_type=material_type,
            name=material_name,
            description=(
                f"Importado automaticamente do FNET em "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. "
                f"Documento FNET id={doc.id}, categoria='{doc.categoria_documento}', "
                f"tipo='{doc.tipo_documento}', dataReferencia={doc.data_referencia}."
            ),
            tags=json.dumps(["fnet_auto_sync", reference_ym], ensure_ascii=False),
            publish_status="rascunho",
            processing_status=(
                ProcessingStatus.PENDING.value
                if hasattr(ProcessingStatus, "PENDING")
                else "pending"
            ),
            file_hash=file_hash,
        )
        db.add(material)
        db.commit()
        db.refresh(material)
        material_id = material.id

        # Persiste o PDF em disco (consumido pelo upload_queue worker)
        unique_filename = f"{uuid.uuid4()}.pdf"
        file_path = os.path.join(UPLOAD_DIR_QUEUE, unique_filename)
        with open(file_path, "wb") as f:
            f.write(pdf_bytes)

        # E também salva no banco (MaterialFile) — mesma estratégia do batch_upload
        _save_file_to_db(db, material_id, suggested_filename, pdf_bytes)
    finally:
        db.close()

    upload_id = str(uuid.uuid4())
    queue_item = UploadQueueItem(
        upload_id=upload_id,
        file_path=file_path,
        filename=suggested_filename,
        material_id=material_id,
        name=material_name,
        user_id=None,  # auto-sync não tem usuário humano
        material_type=material_type,
        categories=[],
        tags=["fnet_auto_sync", reference_ym],
        valid_from=None,
        valid_until=None,
        selected_product_id=product_id,
    )
    UploadQueue.get_instance().add(queue_item)

    return material_id, upload_id


def _compute_document_hash(cnpj: str, fnet_document_id: int) -> str:
    """sha256(cnpj|fnet_doc_id) — chave determinística do documento físico no FNET."""
    payload = f"{(cnpj or '').strip()}|{int(fnet_document_id)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _claim_document_for_processing(
    *,
    db_factory,
    fund: FnetMonitoredFund,
    doc: FnetDocument,
    reference_ym: str,
    dedup_fund_name: str,
    dedup_doc_type: str,
    document_hash: str,
) -> Optional[int]:
    """
    Tenta reservar (claim) o documento para processamento de forma atômica.

    Estratégia: INSERT ... ON CONFLICT (fund_name, reference_month, document_type)
    DO UPDATE SET status='pending' WHERE existing.status NOT IN
    ('success','skipped') RETURNING id.

    Status canônico (alinhado com fnet-backend.md): pending / success / failed / skipped.

    - Linha não existe                                  → insere com 'pending' e retorna id (claim novo).
    - Linha existe com 'failed'                         → re-claim para retry, retorna id.
    - Linha existe com 'pending' antiga (>1h)           → assume worker crashed,
                                                          re-claim para retry, retorna id (lease expirado).
    - Linha existe com 'pending' recente (<1h)          → outro worker está
                                                          trabalhando; RETURNING vazio → None (skip).
    - Linha existe com 'success' ou 'skipped'           → trabalho terminal já feito;
                                                          RETURNING vazio → None (dedup hit).

    Em conjunto com o pg_advisory_lock global em run_sync(), garante que
    nenhum documento é processado em paralelo nem duplicado. O lease de 1h
    protege contra worker mortos sem deixar 'pending' órfão para sempre.
    """
    db = db_factory()
    try:
        raw_meta = json.dumps(doc.raw, ensure_ascii=False, default=str)[:8000]
        # Importante: o predicate no DO UPDATE refere-se à linha existente
        # via prefixo da tabela (`fnet_sync_logs.status`), garantindo que o
        # update só acontece para status NÃO terminais. Se for terminal, o
        # ON CONFLICT vira no-op e o RETURNING não devolve linha.
        stmt = sql_text(
            """
            INSERT INTO fnet_sync_logs (
                monitored_fund_id, fnet_document_id, document_hash, fund_name,
                reference_month, document_category, document_type, status,
                raw_metadata, created_at
            ) VALUES (
                :monitored_fund_id, :fnet_document_id, :document_hash, :fund_name,
                :reference_month, :document_category, :document_type, 'pending',
                :raw_metadata, NOW()
            )
            ON CONFLICT ON CONSTRAINT uq_fnet_sync_log_dedup
            DO UPDATE SET
                status = 'pending',
                fnet_document_id = EXCLUDED.fnet_document_id,
                document_hash = EXCLUDED.document_hash,
                monitored_fund_id = EXCLUDED.monitored_fund_id,
                document_category = EXCLUDED.document_category,
                error_message = NULL,
                raw_metadata = EXCLUDED.raw_metadata
            WHERE fnet_sync_logs.status = 'failed'
               OR (fnet_sync_logs.status = 'pending'
                   AND fnet_sync_logs.created_at < NOW() - INTERVAL '1 hour')
            RETURNING id
            """
        )
        result = db.execute(
            stmt,
            {
                "monitored_fund_id": fund.id,
                "fnet_document_id": doc.id,
                "document_hash": document_hash,
                "fund_name": dedup_fund_name,
                "reference_month": reference_ym,
                "document_category": doc.categoria_documento,
                "document_type": dedup_doc_type,
                "raw_metadata": raw_meta,
            },
        )
        row = result.first()
        db.commit()
        return int(row[0]) if row else None
    except Exception as exc:
        db.rollback()
        logger.error(
            "[FNET-SYNC] Falha no claim atômico (fund_id=%s, doc_id=%s): %s: %s",
            fund.id,
            doc.id,
            type(exc).__name__,
            exc,
        )
        # Sem claim, não processamos — devolvendo None marca como skipped.
        return None
    finally:
        db.close()


def _mark_log_success(db_factory, log_id: int, material_id: int) -> None:
    """Promove um log 'pending' para 'success' com material_id."""
    db = db_factory()
    try:
        db.execute(
            sql_text(
                """
                UPDATE fnet_sync_logs
                   SET status = 'success',
                       material_id = :material_id,
                       error_message = NULL
                 WHERE id = :id
                """
            ),
            {"material_id": material_id, "id": log_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "[FNET-SYNC] Falha ao marcar log_id=%s como downloaded: %s: %s",
            log_id,
            type(exc).__name__,
            exc,
        )
    finally:
        db.close()


_FUND_LEVEL_FAILURE_TYPE = "__fund_level_failure__"


def _persist_fund_level_failure(
    db_factory, fund: FnetMonitoredFund, error_message: str
) -> None:
    """
    Registra uma falha que aconteceu ANTES de termos um documento específico
    (ex.: list_documents do FNET falhou para o fundo inteiro).

    Usa UPSERT em (fund_name, current_month, '__fund_level_failure__') para
    ser idempotente: múltiplas falhas no mesmo mês atualizam a mesma linha
    com a mensagem mais recente, sem violar a UNIQUE.
    """
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    db = db_factory()
    try:
        db.execute(
            sql_text(
                """
                INSERT INTO fnet_sync_logs (
                    monitored_fund_id, fnet_document_id, document_hash, fund_name,
                    reference_month, document_category, document_type, status,
                    error_message, created_at
                ) VALUES (
                    :monitored_fund_id, NULL, NULL, :fund_name,
                    :reference_month, NULL, :document_type, 'failed',
                    :error_message, NOW()
                )
                ON CONFLICT ON CONSTRAINT uq_fnet_sync_log_dedup
                DO UPDATE SET
                    status = 'failed',
                    error_message = EXCLUDED.error_message,
                    monitored_fund_id = EXCLUDED.monitored_fund_id,
                    created_at = NOW()
                """
            ),
            {
                "monitored_fund_id": fund.id,
                "fund_name": fund.fund_name.strip(),
                "reference_month": current_month,
                "document_type": _FUND_LEVEL_FAILURE_TYPE,
                "error_message": (error_message or "")[:2000],
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        # exception() inclui traceback: se a própria auditoria falhar,
        # precisamos ver o stack completo para diagnosticar (DB indisponível,
        # constraint nova, etc.) — não há outro registro desse erro.
        logger.exception(
            "[FNET-SYNC] Falha ao persistir log de erro no nível do fundo "
            "(fund_id=%s): %s: %s",
            fund.id,
            type(exc).__name__,
            exc,
        )
    finally:
        db.close()


def _mark_log_failed(db_factory, log_id: int, error_message: str) -> None:
    """Promove um log 'pending' para 'failed' preservando a UNIQUE row."""
    db = db_factory()
    try:
        db.execute(
            sql_text(
                """
                UPDATE fnet_sync_logs
                   SET status = 'failed',
                       error_message = :error_message
                 WHERE id = :id
                """
            ),
            {"error_message": (error_message or "")[:2000], "id": log_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "[FNET-SYNC] Falha ao marcar log_id=%s como failed: %s: %s",
            log_id,
            type(exc).__name__,
            exc,
        )
    finally:
        db.close()


# Chave fixa do PostgreSQL advisory lock para mutex global do FNET sync.
# Qualquer inteiro de 64 bits serve; o valor abaixo é arbitrário e estável.
_FNET_SYNC_ADVISORY_LOCK_KEY = 7324_2024_0001  # Task #324 marker


async def run_sync(
    fund_ids: Optional[list[int]] = None,
    client: Optional[FnetClient] = None,
    db_factory=SessionLocal,
) -> SyncRunResult:
    """
    Executa um ciclo completo de sincronização. Se `fund_ids` for fornecido,
    sincroniza apenas esses fundos; caso contrário, todos os ativos.

    Idempotente em dois níveis:
    1. **Mutex global** via `pg_try_advisory_lock`: scheduler diário e disparo
       manual (`/sync-now`) não podem rodar simultaneamente. Se outro run já
       detém o lock, devolvemos imediatamente com `fatal_error` explicativo.
    2. **Dedup por documento** via UPSERT atômico em `FnetSyncLog` (UNIQUE em
       `fund_name, reference_month, document_type`) dentro de
       `_claim_document_for_processing`.
    """
    started_at = datetime.now(timezone.utc)
    run_result = SyncRunResult(started_at=started_at)

    # 1) Tenta adquirir o lock global. Mantemos uma sessão dedicada aberta
    #    durante todo o run; pg_advisory_unlock é chamado no finally.
    lock_db = db_factory()
    lock_acquired = False
    try:
        lock_row = lock_db.execute(
            sql_text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _FNET_SYNC_ADVISORY_LOCK_KEY},
        ).scalar()
        lock_acquired = bool(lock_row)
        if not lock_acquired:
            msg = (
                "Outro run de sincronização FNET já está em andamento "
                "(advisory lock ocupado). Encerrando este run sem alterações."
            )
            logger.warning("[FNET-SYNC] %s", msg)
            run_result.fatal_error = msg
            run_result.finished_at = datetime.now(timezone.utc)
            return run_result

        # 2) Dentro do lock — carrega fundos monitorados.
        db = db_factory()
        try:
            query = db.query(FnetMonitoredFund).filter(FnetMonitoredFund.is_active.is_(True))
            if fund_ids:
                query = query.filter(FnetMonitoredFund.id.in_(fund_ids))
            funds = query.order_by(FnetMonitoredFund.fund_name).all()
            for f in funds:
                db.expunge(f)
        except Exception as exc:
            run_result.fatal_error = (
                f"Falha ao carregar fundos monitorados: {type(exc).__name__}: {exc}"
            )
            run_result.finished_at = datetime.now(timezone.utc)
            logger.exception("[FNET-SYNC] %s", run_result.fatal_error)
            return run_result
        finally:
            db.close()

        if not funds:
            logger.info("[FNET-SYNC] Nenhum fundo monitorado ativo — encerrando run.")
            run_result.finished_at = datetime.now(timezone.utc)
            return run_result

        client = client or FnetClient()

        logger.info("[FNET-SYNC] Iniciando run para %d fundo(s) (lock adquirido)", len(funds))
        await _run_sync_inner(funds, client, db_factory, run_result)
        run_result.finished_at = datetime.now(timezone.utc)
        logger.info(
            "[FNET-SYNC] Run concluído: %d fundo(s), %d novo(s), %d duplicado(s), %d falha(s)",
            run_result.funds_processed,
            run_result.docs_downloaded,
            run_result.docs_skipped_duplicate,
            run_result.docs_failed,
        )
        return run_result
    finally:
        if lock_acquired:
            try:
                lock_db.execute(
                    sql_text("SELECT pg_advisory_unlock(:key)"),
                    {"key": _FNET_SYNC_ADVISORY_LOCK_KEY},
                )
                lock_db.commit()
            except Exception as exc:
                logger.error("[FNET-SYNC] Falha ao liberar advisory lock: %s", exc)
        lock_db.close()


async def _run_sync_inner(
    funds: list,
    client: FnetClient,
    db_factory,
    run_result: SyncRunResult,
) -> None:
    """Loop interno (sem lock/setup) — extraído para clareza do mutex."""
    for fund in funds:
        try:
            fund_result = await sync_single_fund(fund, client=client, db_factory=db_factory)
        except Exception as exc:
            fund_result = FundSyncResult(
                fund_id=fund.id, fund_name=fund.fund_name, cnpj=fund.cnpj
            )
            fund_result.errors.append(f"Erro inesperado: {type(exc).__name__}: {exc}")
            logger.exception(
                "[FNET-SYNC] Erro processando fundo %s (id=%s)",
                fund.fund_name,
                fund.id,
            )

        run_result.per_fund.append(fund_result)
        run_result.funds_processed += 1
        run_result.docs_downloaded += fund_result.docs_downloaded
        run_result.docs_failed += fund_result.docs_failed
        run_result.docs_skipped_duplicate += fund_result.docs_skipped_duplicate
