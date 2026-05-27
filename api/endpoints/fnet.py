"""
Endpoints REST para gerenciar a auto-sincronização FNET → SmartUpload.

Rotas:
- GET    /api/fnet/monitored-funds         — lista fundos monitorados.
- POST   /api/fnet/monitored-funds         — cria fundo monitorado.
- PATCH  /api/fnet/monitored-funds/{id}    — atualiza fundo.
- DELETE /api/fnet/monitored-funds/{id}    — remove fundo.
- GET    /api/fnet/sync-log                — paginação por fundo / status / mês.
                                              Alias: /api/fnet/sync-logs (compat).
- POST   /api/fnet/sync-now                — dispara um ciclo manual de sync.

Acesso restrito a `admin` e `gestao_rv` (alinhado com o resto do CMS).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.endpoints.auth import get_current_user
from database.database import get_db
from database.models import FnetMonitoredFund, FnetSyncLog, Product, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fnet", tags=["fnet"])


# ============================================================================
# Schemas
# ============================================================================


class MonitoredFundCreate(BaseModel):
    cnpj: str = Field(..., min_length=11, max_length=20)
    fund_name: str = Field(..., min_length=2, max_length=255)
    ticker: Optional[str] = Field(default=None, max_length=20)
    product_id: Optional[int] = None
    # Código `idTipoFundo` do FNET. 1=FII (default), 2=FIP, 3=FIDC, 4=ETF.
    # Mapa completo em services/fnet_fund_types.py.
    tipo_fundo: int = Field(default=1)
    document_types: Optional[list[str]] = None
    is_active: bool = True

    @field_validator("cnpj")
    @classmethod
    def _normalize_cnpj(cls, v: str) -> str:
        digits = "".join(c for c in (v or "") if c.isdigit())
        if len(digits) != 14:
            raise ValueError(
                f"CNPJ inválido: '{v}' (são necessários 14 dígitos, obtidos {len(digits)})."
            )
        return digits

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        return v or None

    @field_validator("tipo_fundo")
    @classmethod
    def _validate_tipo_fundo(cls, v: int) -> int:
        from services.fnet_fund_types import PREFIX_BY_TIPO_FUNDO
        if v not in PREFIX_BY_TIPO_FUNDO:
            raise ValueError(
                f"tipo_fundo={v} inválido. Valores aceitos: "
                f"{sorted(PREFIX_BY_TIPO_FUNDO.keys())} "
                f"(1=FII, 2=FIP, 3=FIDC, 4=ETF)."
            )
        return v


class MonitoredFundUpdate(BaseModel):
    cnpj: Optional[str] = Field(default=None, min_length=11, max_length=20)
    fund_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    ticker: Optional[str] = Field(default=None, max_length=20)
    product_id: Optional[int] = None
    tipo_fundo: Optional[int] = None
    document_types: Optional[list[str]] = None
    is_active: Optional[bool] = None

    @field_validator("tipo_fundo")
    @classmethod
    def _validate_tipo_fundo(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        from services.fnet_fund_types import PREFIX_BY_TIPO_FUNDO
        if v not in PREFIX_BY_TIPO_FUNDO:
            raise ValueError(
                f"tipo_fundo={v} inválido. Valores aceitos: "
                f"{sorted(PREFIX_BY_TIPO_FUNDO.keys())} "
                f"(1=FII, 2=FIP, 3=FIDC, 4=ETF)."
            )
        return v

    @field_validator("cnpj")
    @classmethod
    def _normalize_cnpj(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) != 14:
            raise ValueError(
                f"CNPJ inválido: '{v}' (são necessários 14 dígitos, obtidos {len(digits)})."
            )
        return digits

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        return v or None


class SyncNowRequest(BaseModel):
    fund_ids: Optional[list[int]] = Field(
        default=None,
        description=(
            "Lista de fund_ids para sincronizar. Se omitido ou vazio, "
            "sincroniza todos os fundos ativos."
        ),
    )


# ============================================================================
# Helpers
# ============================================================================


def _require_admin_or_gestao(user: User) -> None:
    if user.role not in ("admin", "gestao_rv"):
        raise HTTPException(
            status_code=403,
            detail=f"Acesso restrito a admin/gestao_rv (role atual: '{user.role}').",
        )


def _format_cnpj(digits: str) -> str:
    s = (digits or "").strip()
    if len(s) != 14 or not s.isdigit():
        return digits
    return f"{s[0:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:14]}"


def _serialize_fund(fund: FnetMonitoredFund, db: Session) -> dict:
    from services.fnet_fund_types import label_for

    product_name = None
    product_ticker = None
    if fund.product_id:
        prod = db.query(Product).filter(Product.id == fund.product_id).first()
        if prod:
            product_name = prod.name
            product_ticker = prod.ticker

    try:
        document_types = json.loads(fund.document_types) if fund.document_types else None
    except (json.JSONDecodeError, TypeError):
        document_types = None

    tipo = int(fund.tipo_fundo or 1)
    return {
        "id": fund.id,
        "cnpj": fund.cnpj,
        "cnpj_formatted": _format_cnpj(fund.cnpj),
        "fund_name": fund.fund_name,
        "ticker": fund.ticker,
        "product_id": fund.product_id,
        "product_name": product_name,
        "product_ticker": product_ticker,
        "tipo_fundo": tipo,
        "tipo_fundo_label": label_for(tipo),
        "document_types": document_types,
        "is_active": fund.is_active,
        "last_sync_at": fund.last_sync_at.isoformat() if fund.last_sync_at else None,
        "created_at": fund.created_at.isoformat() if fund.created_at else None,
        "updated_at": fund.updated_at.isoformat() if fund.updated_at else None,
    }


def _serialize_log(log: FnetSyncLog) -> dict:
    return {
        "id": log.id,
        "monitored_fund_id": log.monitored_fund_id,
        "fnet_document_id": log.fnet_document_id,
        "fund_name": log.fund_name,
        "reference_month": log.reference_month,
        "document_category": log.document_category,
        "document_type": log.document_type,
        "status": log.status,
        "material_id": log.material_id,
        "error_message": log.error_message,
        # Task #339: traceback técnico (Python format_exc) — pode ser longo.
        # Só vem preenchido para status='failed'. UI exibe sob demanda no
        # modal "Diagnóstico"; nas listagens padrão segue oculto.
        "error_traceback": log.error_traceback,
        # Task #339: UUID do run de sincronização que gravou esta linha.
        # Permite ao frontend destacar "última tentativa" vs. histórico.
        "run_id": log.run_id,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


# ============================================================================
# Monitored Funds CRUD
# ============================================================================


@router.get("/monitored-funds")
async def list_monitored_funds(
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)
    q = db.query(FnetMonitoredFund)
    if is_active is not None:
        q = q.filter(FnetMonitoredFund.is_active.is_(is_active))
    total = q.count()
    funds = (
        q.order_by(FnetMonitoredFund.fund_name)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "funds": [_serialize_fund(f, db) for f in funds],
    }


@router.post("/monitored-funds", status_code=201)
async def create_monitored_fund(
    payload: MonitoredFundCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)

    existing = (
        db.query(FnetMonitoredFund).filter(FnetMonitoredFund.cnpj == payload.cnpj).first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Já existe fundo monitorado com CNPJ {_format_cnpj(payload.cnpj)} "
                f"(id={existing.id}, nome='{existing.fund_name}')."
            ),
        )

    if payload.product_id is not None:
        prod = db.query(Product).filter(Product.id == payload.product_id).first()
        if not prod:
            raise HTTPException(
                status_code=404,
                detail=f"product_id={payload.product_id} não encontrado.",
            )

    fund = FnetMonitoredFund(
        cnpj=payload.cnpj,
        fund_name=payload.fund_name.strip(),
        ticker=payload.ticker,
        product_id=payload.product_id,
        tipo_fundo=payload.tipo_fundo,
        document_types=(
            json.dumps(payload.document_types, ensure_ascii=False)
            if payload.document_types
            else None
        ),
        is_active=payload.is_active,
    )
    db.add(fund)
    db.commit()
    db.refresh(fund)

    logger.info(
        "[FNET] Fundo monitorado criado por user=%s: %s (CNPJ %s, id=%s)",
        current_user.username,
        fund.fund_name,
        _format_cnpj(fund.cnpj),
        fund.id,
    )
    return _serialize_fund(fund, db)


@router.patch("/monitored-funds/{fund_id}")
async def update_monitored_fund(
    fund_id: int,
    payload: MonitoredFundUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)

    fund = db.query(FnetMonitoredFund).filter(FnetMonitoredFund.id == fund_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail=f"Fundo monitorado id={fund_id} não encontrado.")

    if payload.cnpj is not None and payload.cnpj != fund.cnpj:
        # Garante unicidade do CNPJ entre fundos monitorados.
        conflict = (
            db.query(FnetMonitoredFund)
            .filter(
                FnetMonitoredFund.cnpj == payload.cnpj,
                FnetMonitoredFund.id != fund_id,
            )
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"CNPJ {_format_cnpj(payload.cnpj)} já está vinculado ao fundo "
                    f"id={conflict.id} ('{conflict.fund_name}')."
                ),
            )
        fund.cnpj = payload.cnpj

    if payload.product_id is not None:
        prod = db.query(Product).filter(Product.id == payload.product_id).first()
        if not prod:
            raise HTTPException(
                status_code=404,
                detail=f"product_id={payload.product_id} não encontrado.",
            )
        fund.product_id = payload.product_id

    if payload.fund_name is not None:
        fund.fund_name = payload.fund_name.strip()
    if payload.ticker is not None:
        fund.ticker = payload.ticker
    if payload.tipo_fundo is not None:
        fund.tipo_fundo = payload.tipo_fundo
    if payload.document_types is not None:
        fund.document_types = (
            json.dumps(payload.document_types, ensure_ascii=False)
            if payload.document_types
            else None
        )
    if payload.is_active is not None:
        fund.is_active = payload.is_active

    db.commit()
    db.refresh(fund)
    return _serialize_fund(fund, db)


@router.delete("/monitored-funds/{fund_id}", status_code=204)
async def delete_monitored_fund(
    fund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)

    fund = db.query(FnetMonitoredFund).filter(FnetMonitoredFund.id == fund_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail=f"Fundo monitorado id={fund_id} não encontrado.")

    # SOFT DELETE: preserva FnetSyncLog (cascade='all, delete-orphan' apagaria
    # todo o histórico de sincronização — auditoria seria perdida).
    # Para reativar, basta PATCH com is_active=true.
    if not fund.is_active:
        logger.info(
            "[FNET] DELETE no-op: fundo id=%s ('%s') já estava inativo.",
            fund_id,
            fund.fund_name,
        )
        return None
    fund.is_active = False
    db.commit()
    logger.info(
        "[FNET] Fundo monitorado desativado (soft delete) por user=%s: id=%s nome='%s'",
        current_user.username,
        fund_id,
        fund.fund_name,
    )
    return None


# ============================================================================
# Sync Logs
# ============================================================================


@router.get("/sync-log")
@router.get("/sync-logs", include_in_schema=False)  # alias de compatibilidade
async def list_sync_logs(
    fund_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(
        default=None,
        description="Filtra por UUID do run de sincronização (Task #339).",
    ),
    month: Optional[str] = Query(
        default=None,
        description="Filtra por mês de referência no formato YYYY-MM (ex.: '2026-05').",
        pattern=r"^\d{4}-\d{2}$",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)
    q = db.query(FnetSyncLog)
    if fund_id is not None:
        q = q.filter(FnetSyncLog.monitored_fund_id == fund_id)
    if status:
        q = q.filter(FnetSyncLog.status == status)
    if run_id:
        q = q.filter(FnetSyncLog.run_id == run_id)
    if month:
        q = q.filter(FnetSyncLog.reference_month == month)
    total = q.count()
    logs = (
        q.order_by(FnetSyncLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [_serialize_log(lg) for lg in logs],
    }


# ----------------------------------------------------------------------------
# Task #339: limpar falhas históricas. Operação destrutiva mas restrita —
# só remove status='failed', exige fund_id e nunca toca em success/skipped.
# ----------------------------------------------------------------------------
@router.delete("/sync-log")
async def delete_sync_logs(
    fund_id: int = Query(..., description="Fundo monitorado alvo (obrigatório)."),
    status: str = Query(
        "failed",
        description=(
            "Status alvo. Por segurança, apenas 'failed' é aceito — "
            "linhas de sucesso/pulado/pending nunca são apagadas aqui."
        ),
    ),
    before: Optional[str] = Query(
        default=None,
        description=(
            "ISO datetime opcional: apaga apenas linhas criadas ANTES "
            "desse instante. Útil para limpar histórico antigo preservando "
            "a tentativa mais recente."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)
    if status != "failed":
        raise HTTPException(
            status_code=400,
            detail=(
                "Apenas linhas com status='failed' podem ser apagadas. "
                "Sucesso, pulado e pendente são preservados."
            ),
        )
    fund = db.query(FnetMonitoredFund).filter(FnetMonitoredFund.id == fund_id).first()
    if not fund:
        raise HTTPException(
            status_code=404,
            detail=f"Fundo monitorado id={fund_id} não encontrado.",
        )

    q = db.query(FnetSyncLog).filter(
        FnetSyncLog.monitored_fund_id == fund_id,
        FnetSyncLog.status == "failed",
    )
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Parâmetro 'before' inválido: '{before}' não é ISO datetime.",
            )
        q = q.filter(FnetSyncLog.created_at < before_dt)

    deleted = q.delete(synchronize_session=False)
    db.commit()
    logger.info(
        "[FNET] Limpeza de histórico de falhas por user=%s: fund_id=%s before=%s removidos=%d",
        current_user.username, fund_id, before, deleted,
    )
    return {"deleted": deleted, "fund_id": fund_id, "before": before}


# ============================================================================
# Sync Now (manual trigger)
# ============================================================================


@router.post("/sync-now")
async def sync_now(
    payload: SyncNowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)
    # Import tardio para evitar carga em cold-start
    from services.fnet_sync import run_sync

    # Validação prévia: se fund_ids vier, todos devem existir
    if payload.fund_ids:
        existing_ids = {
            r[0]
            for r in db.query(FnetMonitoredFund.id)
            .filter(FnetMonitoredFund.id.in_(payload.fund_ids))
            .all()
        }
        missing = [fid for fid in payload.fund_ids if fid not in existing_ids]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Fund IDs não encontrados: {missing}",
            )

    logger.info(
        "[FNET] Sync manual disparado por user=%s (fund_ids=%s)",
        current_user.username,
        payload.fund_ids,
    )

    try:
        # Roda inline e devolve o resumo. Não bloqueia o tick do scheduler diário.
        result = await asyncio.wait_for(
            run_sync(fund_ids=payload.fund_ids),
            timeout=600.0,  # 10 min — bastante folga para muitos fundos
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Sync FNET excedeu 10 minutos. Consulte /api/fnet/sync-log para resultados parciais.",
        )
    except Exception as exc:
        logger.exception("[FNET] Erro inesperado no sync manual")
        raise HTTPException(
            status_code=500,
            detail=f"Sync FNET falhou: {type(exc).__name__}: {exc}",
        )

    return result.to_dict()


# ============================================================================
# Task #339 — Auto-diagnóstico
# ============================================================================
# Dois endpoints novos para destravar Railway/produção quando o pipeline
# FNET falha mas o usuário não tem acesso a logs:
#   GET  /api/fnet/version           — hash dos módulos críticos + proxy status
#   POST /api/fnet/diagnose/{id}     — dry-run de warm-up → download (sem
#                                       persistir nada) com timeline pt-BR.
# Ambos read-only do ponto de vista de dados (diagnose baixa o PDF mas
# não cria Material). Restrito a admin/gestao_rv.
# ============================================================================


def _file_sha256(path: str) -> str:
    """SHA-256 do arquivo no disco. Identifica o bytecode em produção."""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        return f"erro:{type(exc).__name__}"


def _git_short_sha() -> Optional[str]:
    """Lê `.git/HEAD` direto do disco — não depende do binário `git` no container.

    Resolve refs simbólicos (ex.: `ref: refs/heads/main` → conteúdo de
    `.git/refs/heads/main`). Devolve os 12 primeiros chars do SHA ou None.
    Em containers de produção sem `.git/`, retorna None silenciosamente.
    """
    import os as _os
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    project_root = _os.path.dirname(base)
    head_path = _os.path.join(project_root, ".git", "HEAD")
    try:
        with open(head_path, "r", encoding="utf-8") as f:
            head = f.read().strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            ref_path = _os.path.join(project_root, ".git", ref)
            with open(ref_path, "r", encoding="utf-8") as f:
                return f.read().strip()[:12]
        # detached HEAD — já é SHA puro
        return head[:12] if head else None
    except OSError:
        return None


# Timestamp de boot do processo (ms desde epoch). Capturado uma única
# vez no import — diferencia containers reiniciados na mesma versão.
import time as _boot_time
_BUILD_TIMESTAMP_MS = int(_boot_time.time() * 1000)


def _mask_proxy(url: Optional[str]) -> Optional[str]:
    """Mascarar user:pass em URLs de proxy antes de devolver ao cliente."""
    if not url:
        return None
    try:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(url)
        if p.username or p.password:
            netloc = (p.hostname or "") + (f":{p.port}" if p.port else "")
            netloc = f"***:***@{netloc}"
            return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))
        return url
    except Exception:  # noqa: BLE001 — diagnóstico não pode falhar por aux
        return "<proxy mascarado: parse falhou>"


@router.get("/version")
async def fnet_version(
    current_user: User = Depends(get_current_user),
):
    """
    Retorna a SHA do código FNET em execução. Diagnóstico crítico para
    Railway/produção: se o bytecode estiver cacheado e o deploy não tiver
    surtido efeito, o SHA aqui será o do código ANTIGO. Comparar com o SHA
    no repositório local antes de abrir bug.

    Inclui também o status do proxy opcional (URL mascarada) — útil para
    confirmar se `FNET_HTTP_PROXY` está realmente aplicado em produção.
    """
    _require_admin_or_gestao(current_user)
    import os as _os
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    # api/endpoints/fnet.py → sobe 2 níveis até a raiz do projeto.
    project_root = _os.path.dirname(base)
    files = {
        "services/fnet_client.py": _os.path.join(project_root, "services", "fnet_client.py"),
        "services/fnet_sync.py": _os.path.join(project_root, "services", "fnet_sync.py"),
        "api/endpoints/fnet.py": _os.path.join(project_root, "api", "endpoints", "fnet.py"),
    }
    return {
        "task_baseline": "339",
        # SHA curto do commit em execução — None em containers sem .git/.
        "git_short_sha": _git_short_sha(),
        # Timestamp de boot do processo (ms). Diferencia restarts do mesmo
        # SHA — se mudou, o container foi reiniciado / re-deployado.
        "build_timestamp_ms": _BUILD_TIMESTAMP_MS,
        "file_hashes": {name: _file_sha256(p) for name, p in files.items()},
        "fnet_http_proxy": _mask_proxy(_os.getenv("FNET_HTTP_PROXY") or None),
        "fnet_http_proxy_configured": bool(_os.getenv("FNET_HTTP_PROXY")),
    }


@router.post("/diagnose/{fund_id}")
async def diagnose_fund(
    fund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dry-run completo do pipeline FNET para um fundo monitorado, etapa a etapa:
      1. warm-up de sessão (cookies + CSRF)
      2. autocomplete `listarFundos` → idFundo
      3. search `pesquisarGerenciadorDocumentosDados`
      4. download do PDF do 1º documento (se houver), só em memória
      5. simulação do estágio Material/Upload sem persistir

    Retorna uma timeline em pt-BR com `step`, `status` (ok/aviso/erro),
    `elapsed_ms`, mensagem amigável e diagnóstico técnico curto. NÃO
    grava nada no banco e NÃO interfere com a sincronização agendada.
    """
    _require_admin_or_gestao(current_user)
    import httpx
    from services.fnet_client import (
        FnetClient,
        FnetClientError,
        FnetFundNotFoundError,
        FNET_WARMUP_URL,
        FNET_LIST_FUNDS_URL,
        FNET_SEARCH_URL,
        _DEFAULT_HEADERS,
        _CSRF_REGEX,
        _extract_diag_headers,
        _warmup_headers,
    )
    from services.fnet_sync import _current_month_window, _format_cnpj_br
    import os as _os
    import time as _time

    fund = db.query(FnetMonitoredFund).filter(FnetMonitoredFund.id == fund_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail=f"Fundo id={fund_id} não encontrado.")

    timeline: list[dict] = []

    def _step(
        name: str,
        status: str,
        msg: str,
        started: float,
        technical: str = "",
        http: Optional[dict] = None,
    ) -> None:
        """Adiciona linha à timeline. `http` carrega diagnóstico estruturado
        por etapa (status_code, headers selecionados, body excerpt)."""
        entry: dict = {
            "step": name,
            "status": status,
            "elapsed_ms": int((_time.monotonic() - started) * 1000),
            "message": msg,
            "technical": technical[:1000],
        }
        if http:
            entry["http"] = http
        timeline.append(entry)

    def _http_diag(response: httpx.Response) -> dict:
        """Empacota status, headers de diagnóstico (CF-Ray/Server/cf-mitigated/
        x-amzn-trace-id/cf-cache-status) e excerpt do body (300 chars) para
        que o operador identifique geo-block/anti-bot sem expor segredos."""
        body_excerpt = ""
        try:
            body_excerpt = response.text[:300]
        except Exception:  # noqa: BLE001
            body_excerpt = "<binary>"
        return {
            "status_code": response.status_code,
            "headers": _extract_diag_headers(response),
            "body_excerpt": body_excerpt,
            "request_url": str(response.request.url) if response.request else "",
        }

    proxy_url = _os.getenv("FNET_HTTP_PROXY") or None
    start_date, end_date = _current_month_window()
    cnpj_formatted = _format_cnpj_br(fund.cnpj)
    cnpj_digits = "".join(ch for ch in (fund.cnpj or "") if ch.isdigit())
    overall_ok = True
    summary = "Pipeline FNET funcionando para este fundo."

    # =========================================================
    # Etapas 1-3 — probes HTTP explícitos (warmup → autocomplete → search).
    # NÃO usamos client.list_documents aqui porque o validador exigiu
    # granularidade por etapa + diagnóstico HTTP estruturado. Os probes
    # mimetizam exatamente os requests do FnetClient (mesmas URLs/headers)
    # para que sucesso aqui implique sucesso no pipeline real.
    # =========================================================
    csrf_token: Optional[str] = None
    id_fundo: Optional[int] = None
    canonical_name: Optional[str] = None

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            proxies=proxy_url,
        ) as http_client:
            # ----- Etapa 1: warmup -----
            t0 = _time.monotonic()
            try:
                r1 = await http_client.get(FNET_WARMUP_URL, headers=_warmup_headers())
                diag1 = _http_diag(r1)
                if r1.status_code >= 400:
                    overall_ok = False
                    msg = (
                        f"FNET bloqueou o warmup com HTTP {r1.status_code}. "
                        "Provável anti-bot/geo-block (Cloudflare). "
                        "Verifique CF-Ray / cf-mitigated em 'http.headers'."
                    )
                    _step("warmup", "erro", msg, t0, http=diag1)
                    return {
                        "fund_id": fund.id, "fund_name": fund.fund_name,
                        "overall_status": "erro", "summary": msg,
                        "timeline": timeline,
                    }
                m = _CSRF_REGEX.search(r1.text)
                if not m:
                    overall_ok = False
                    msg = (
                        "Warmup respondeu OK mas sem csrf_token — formato "
                        "da página FNET pode ter mudado."
                    )
                    _step("warmup", "erro", msg, t0,
                          technical=f"len(html)={len(r1.text)}", http=diag1)
                    return {
                        "fund_id": fund.id, "fund_name": fund.fund_name,
                        "overall_status": "erro", "summary": msg,
                        "timeline": timeline,
                    }
                csrf_token = m.group(1)
                _step(
                    "warmup", "ok",
                    f"Sessão estabelecida (csrf={csrf_token[:8]}…, "
                    f"cookies={len(http_client.cookies.jar)} no jar).",
                    t0, http=diag1,
                )
            except httpx.HTTPError as exc:
                overall_ok = False
                _step("warmup", "erro",
                      f"Falha de rede no warmup: {type(exc).__name__}: {exc}",
                      t0, technical=str(exc))
                return {
                    "fund_id": fund.id, "fund_name": fund.fund_name,
                    "overall_status": "erro",
                    "summary": "FNET inalcançável no warmup.", "timeline": timeline,
                }

            # ----- Etapa 2: autocomplete (listarFundos) -----
            # Headers idênticos ao FnetClient._raw_get_with_retry — incluem
            # CSRFToken pra evitar 403 e refletir fielmente o request real.
            xhr_headers = {**_DEFAULT_HEADERS, "CSRFToken": csrf_token}
            t1 = _time.monotonic()
            try:
                r2 = await http_client.get(
                    FNET_LIST_FUNDS_URL,
                    headers=xhr_headers,
                    # Params alinhados a FnetClient._resolve_fund — o FNET
                    # exige page, idAdm e paraCerts e retorna HTTP 500 sem eles.
                    params={
                        "term": cnpj_digits,
                        "page": 1,
                        "idTipoFundo": int(fund.tipo_fundo or 1),
                        "idAdm": 0,
                        "paraCerts": "false",
                    },
                )
                diag2 = _http_diag(r2)
                if r2.status_code >= 400:
                    overall_ok = False
                    msg = f"Autocomplete FNET retornou HTTP {r2.status_code}."
                    _step("autocomplete_fundo", "erro", msg, t1, http=diag2)
                    return {
                        "fund_id": fund.id, "fund_name": fund.fund_name,
                        "overall_status": "erro", "summary": msg, "timeline": timeline,
                    }
                try:
                    # FNET retorna {"results": [...], "total": N} — não uma
                    # lista plana. Lemos .get("results") como o _resolve_fund
                    # real faz. Fallback para lista direta por robustez.
                    raw_json = r2.json()
                    results = (
                        raw_json.get("results") or []
                        if isinstance(raw_json, dict)
                        else raw_json or []
                    )
                except Exception:  # noqa: BLE001
                    results = []
                if not results:
                    overall_ok = False
                    msg = (
                        f"CNPJ {cnpj_formatted} não encontrado no autocomplete "
                        "(tipoFundo={}). Verifique o cadastro do fundo no "
                        "FNET ou se o tipo está correto."
                    ).format(fund.tipo_fundo)
                    _step("autocomplete_fundo", "erro", msg, t1, http=diag2)
                    return {
                        "fund_id": fund.id, "fund_name": fund.fund_name,
                        "overall_status": "erro",
                        "summary": "CNPJ não localizado pelo FNET.",
                        "timeline": timeline,
                    }
                first = results[0] if results else {}
                id_fundo = int(first.get("id") or 0) or None
                canonical_name = str(first.get("text") or "")[:120]
                _step(
                    "autocomplete_fundo", "ok",
                    f"Fundo resolvido: '{canonical_name}' (idFundo={id_fundo}). "
                    f"Total de candidatos: {len(results)}.",
                    t1, http=diag2,
                )
            except httpx.HTTPError as exc:
                overall_ok = False
                _step("autocomplete_fundo", "erro",
                      f"Falha de rede no autocomplete: {type(exc).__name__}: {exc}",
                      t1, technical=str(exc))
                return {
                    "fund_id": fund.id, "fund_name": fund.fund_name,
                    "overall_status": "erro",
                    "summary": "FNET inalcançável no autocomplete.", "timeline": timeline,
                }

            # ----- Etapa 3: search (apenas valida endpoint; o list_documents
            # completo + filtragem cliente-side roda na Etapa 4 a seguir). -----
            # Params alinhados com _fetch_documents_paged do FnetClient
            # (tipoFundo, cnpjFundo, paginaCertificados, isSession) — sem
            # isso o endpoint pode responder diferente do fluxo real.
            t2 = _time.monotonic()
            try:
                r3 = await http_client.get(
                    FNET_SEARCH_URL,
                    headers=xhr_headers,
                    params={
                        "d": 1, "s": 0, "l": 1,
                        "tipoFundo": int(fund.tipo_fundo or 1),
                        "idFundo": id_fundo or "",
                        "cnpj": cnpj_digits,
                        "cnpjFundo": cnpj_digits,
                        "dataInicial": start_date.strftime("%d/%m/%Y"),
                        "dataFinal": end_date.strftime("%d/%m/%Y"),
                        "paginaCertificados": "false",
                        "isSession": "true",
                    },
                )
                diag3 = _http_diag(r3)
                if r3.status_code >= 400:
                    overall_ok = False
                    msg = f"Endpoint de busca FNET retornou HTTP {r3.status_code}."
                    _step("search_endpoint", "erro", msg, t2, http=diag3)
                    return {
                        "fund_id": fund.id, "fund_name": fund.fund_name,
                        "overall_status": "erro", "summary": msg, "timeline": timeline,
                    }
                _step(
                    "search_endpoint", "ok",
                    "Endpoint de busca respondeu OK — a Etapa 4 vai usar o "
                    "FnetClient para listar/filtrar documentos do mês.",
                    t2, http=diag3,
                )
            except httpx.HTTPError as exc:
                overall_ok = False
                _step("search_endpoint", "erro",
                      f"Falha de rede no search: {type(exc).__name__}: {exc}",
                      t2, technical=str(exc))
                return {
                    "fund_id": fund.id, "fund_name": fund.fund_name,
                    "overall_status": "erro",
                    "summary": "FNET inalcançável no search.", "timeline": timeline,
                }
    except Exception as exc:  # noqa: BLE001 — defense in depth
        import traceback as _tb
        overall_ok = False
        _step("probe_http", "erro",
              f"Erro inesperado nos probes HTTP: {type(exc).__name__}: {exc}",
              _time.monotonic(), technical=_tb.format_exc()[:1000])
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro", "summary": "Erro inesperado nos probes.",
            "timeline": timeline,
        }

    # =========================================================
    # Etapa 4 — `listar_documentos` real via FnetClient (com filtro cliente).
    # =========================================================
    client = FnetClient(proxy=proxy_url, max_retries=2)
    t3 = _time.monotonic()
    try:
        documents, id_fundo_full, canonical = await client.list_documents(
            cnpj=cnpj_formatted,
            date_start=start_date,
            date_end=end_date,
            tipo_fundo=int(fund.tipo_fundo or 1),
            cached_internal_id=fund.fnet_internal_id,
            cached_canonical_name=fund.fnet_canonical_name,
        )
        _step(
            "listar_documentos", "ok",
            f"Listagem completa OK: {len(documents)} documento(s) no período "
            f"{start_date:%d/%m/%Y}–{end_date:%d/%m/%Y}.",
            t3, technical=f"canonical='{canonical[:80]}' idFundo={id_fundo_full}",
        )
    except FnetFundNotFoundError as exc:
        overall_ok = False
        _step("listar_documentos", "erro",
              f"Fundo não encontrado no FnetClient: {exc}",
              t3, technical=f"{type(exc).__name__}: {exc}")
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro",
            "summary": "CNPJ rejeitado pelo FnetClient apesar do probe ter passado.",
            "timeline": timeline,
        }
    except FnetClientError as exc:
        overall_ok = False
        _step("listar_documentos", "erro",
              f"FnetClient.list_documents falhou: {exc}",
              t3, technical=f"{type(exc).__name__}: {exc}")
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro", "summary": str(exc), "timeline": timeline,
        }
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        overall_ok = False
        _step("listar_documentos", "erro",
              f"Erro inesperado: {type(exc).__name__}: {exc}",
              t3, technical=_tb.format_exc()[:1000])
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro",
            "summary": "Erro inesperado — veja traceback.",
            "timeline": timeline,
        }

    # Etapa 4: download do 1º doc (se houver) — em memória, não grava nada.
    if not documents:
        summary = (
            "FNET respondeu OK mas não há documentos neste mês. "
            "Nada para baixar — normal no início de cada mês."
        )
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "ok" if overall_ok else "aviso",
            "summary": summary, "timeline": timeline,
        }

    first_doc = documents[0]
    t1 = _time.monotonic()
    try:
        pdf_bytes, suggested_filename = await client.download_document(first_doc.id)
        size_kb = len(pdf_bytes) // 1024
        _step(
            "baixar_pdf", "ok",
            f"Download OK: '{suggested_filename}' ({size_kb} KB) — documento FNET "
            f"id={first_doc.id} ({first_doc.tipo_documento} {first_doc.data_referencia}).",
            t1,
        )
    except FnetClientError as exc:
        overall_ok = False
        status_code = getattr(exc, "status_code", None)
        _step(
            "baixar_pdf", "erro",
            (
                f"Falha ao baixar PDF do FNET (HTTP {status_code}). "
                "Listagem funcionou mas o download não — pode ser bloqueio "
                "anti-bot só na rota de download."
            ),
            t1, f"{type(exc).__name__}: {exc}",
        )
        summary = "Download bloqueado pelo FNET."
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro", "summary": summary, "timeline": timeline,
        }
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        overall_ok = False
        _step(
            "baixar_pdf", "erro",
            f"Erro inesperado no download: {type(exc).__name__}: {exc}",
            t1, _tb.format_exc()[:1000],
        )
        return {
            "fund_id": fund.id, "fund_name": fund.fund_name,
            "overall_status": "erro",
            "summary": "Erro inesperado no download.",
            "timeline": timeline,
        }

    # Etapa 5: simulação do estágio Material — apenas validação que o helper
    # consegue ser importado e que as dependências (produto, queue) estão OK.
    t2 = _time.monotonic()
    try:
        from services.upload_queue import UploadQueue  # noqa: F401
        # Apenas instanciamos para garantir que a queue está viva.
        _ = UploadQueue.get_instance()
        _step(
            "validar_pipeline_material", "ok",
            "Componentes do pipeline Material/UploadQueue carregaram OK. "
            "Em uma sincronização real, este PDF seria persistido e enfileirado.",
            t2,
        )
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        overall_ok = False
        _step(
            "validar_pipeline_material", "erro",
            f"Falha ao carregar pipeline Material: {type(exc).__name__}: {exc}",
            t2, _tb.format_exc()[:1000],
        )

    return {
        "fund_id": fund.id, "fund_name": fund.fund_name,
        "overall_status": "ok" if overall_ok else "aviso",
        "summary": summary if overall_ok else "Pipeline com avisos — veja timeline.",
        "timeline": timeline,
    }
