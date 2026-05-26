"""
Endpoints REST para gerenciar a auto-sincronização FNET → SmartUpload.

Rotas:
- GET    /api/fnet/monitored-funds         — lista fundos monitorados.
- POST   /api/fnet/monitored-funds         — cria fundo monitorado.
- PATCH  /api/fnet/monitored-funds/{id}    — atualiza fundo.
- DELETE /api/fnet/monitored-funds/{id}    — remove fundo.
- GET    /api/fnet/sync-logs               — paginação por fundo / status.
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


class MonitoredFundUpdate(BaseModel):
    fund_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    ticker: Optional[str] = Field(default=None, max_length=20)
    product_id: Optional[int] = None
    document_types: Optional[list[str]] = None
    is_active: Optional[bool] = None

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

    return {
        "id": fund.id,
        "cnpj": fund.cnpj,
        "cnpj_formatted": _format_cnpj(fund.cnpj),
        "fund_name": fund.fund_name,
        "ticker": fund.ticker,
        "product_id": fund.product_id,
        "product_name": product_name,
        "product_ticker": product_ticker,
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
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


# ============================================================================
# Monitored Funds CRUD
# ============================================================================


@router.get("/monitored-funds")
async def list_monitored_funds(
    is_active: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin_or_gestao(current_user)
    q = db.query(FnetMonitoredFund)
    if is_active is not None:
        q = q.filter(FnetMonitoredFund.is_active.is_(is_active))
    funds = q.order_by(FnetMonitoredFund.fund_name).all()
    return {"funds": [_serialize_fund(f, db) for f in funds]}


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

    db.delete(fund)
    db.commit()
    logger.info(
        "[FNET] Fundo monitorado removido por user=%s: id=%s nome='%s'",
        current_user.username,
        fund_id,
        fund.fund_name,
    )
    return None


# ============================================================================
# Sync Logs
# ============================================================================


@router.get("/sync-logs")
async def list_sync_logs(
    fund_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
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
            detail="Sync FNET excedeu 10 minutos. Consulte /api/fnet/sync-logs para resultados parciais.",
        )
    except Exception as exc:
        logger.exception("[FNET] Erro inesperado no sync manual")
        raise HTTPException(
            status_code=500,
            detail=f"Sync FNET falhou: {type(exc).__name__}: {exc}",
        )

    return result.to_dict()
