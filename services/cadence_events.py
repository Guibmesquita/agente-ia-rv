"""
Task #221 — Helper para emissão de eventos do motor de cadência e
manutenção do estado persistente (CadenceEngineState).

Todas as funções são tolerantes a falha (try/except amplo): observabilidade
NUNCA pode atrapalhar o tick do motor. Em caso de erro de gravação, apenas
logamos e seguimos.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Iterable
from sqlalchemy.orm import Session
from sqlalchemy import desc

logger = logging.getLogger(__name__)

# Tipos de evento canônicos (mantenha em pt-BR amigável no frontend; aqui é o id técnico).
EVENT_CAMPAIGN_CREATED = "campaign_created"
EVENT_CAMPAIGN_STARTED = "campaign_started"
EVENT_CAMPAIGN_PAUSED = "campaign_paused"
EVENT_CAMPAIGN_RESUMED = "campaign_resumed"
EVENT_PROFILE_CHANGED = "cadence_profile_changed"
EVENT_DISPATCH_SENT = "dispatch_sent"
EVENT_DISPATCH_FAILED = "dispatch_failed"
EVENT_ANTI_BLOCK_PAUSE = "anti_block_pause"
EVENT_DAILY_LIMIT_REACHED = "daily_limit_reached"
EVENT_CAMPAIGN_DONE = "campaign_done"

CAMPAIGN_KIND_UNIFIED = "unified"
CAMPAIGN_KIND_LEGACY = "legacy"


def emit_event(
    db: Session,
    campaign_kind: str,
    campaign_id: int,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
    autocommit: bool = True,
) -> bool:
    """
    Insere um evento. Retorna True se gravou, False em caso de falha.
    Nunca levanta exceção para o chamador (motor não pode quebrar por log).
    """
    try:
        from database.models import CadenceCampaignEvent
        evt = CadenceCampaignEvent(
            campaign_kind=campaign_kind,
            campaign_id=int(campaign_id),
            event_type=event_type,
            payload=json.dumps(payload or {}, default=str, ensure_ascii=False),
            user_id=user_id,
            occurred_at=occurred_at or datetime.utcnow(),
        )
        db.add(evt)
        if autocommit:
            db.commit()
        else:
            db.flush()
        return True
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"[CADENCE-OBS] falha ao emitir evento {event_type}: {e}")
        return False


def emit_event_safe_new_session(
    campaign_kind: str,
    campaign_id: int,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> bool:
    """Versão que abre a própria sessão. Útil quando não temos `db` acessível."""
    try:
        from database.database import SessionLocal
        s = SessionLocal()
        try:
            return emit_event(s, campaign_kind, campaign_id, event_type, payload, user_id)
        finally:
            s.close()
    except Exception as e:
        logger.warning(f"[CADENCE-OBS] emit_event_safe_new_session falhou: {e}")
        return False


def get_engine_state(db: Session) -> Dict[str, Any]:
    """
    Lê (ou cria, se inexistente) a linha singleton id=1.
    Retorna dict serializável com campos: last_tick_at, last_send_at,
    pause_until, pause_reason, consecutive_failures, updated_at.
    """
    from database.models import CadenceEngineState
    row = db.query(CadenceEngineState).filter(CadenceEngineState.id == 1).first()
    if not row:
        row = CadenceEngineState(id=1, consecutive_failures=0)
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
        except Exception:
            db.rollback()
            row = db.query(CadenceEngineState).filter(CadenceEngineState.id == 1).first()
    return _row_to_dict(row)


def update_engine_state(db: Session, **fields: Any) -> Dict[str, Any]:
    """
    Atualiza campos do singleton. Chaves aceitas: last_tick_at, last_send_at,
    pause_until, pause_reason, consecutive_failures.
    Retorna o estado atualizado.
    """
    from database.models import CadenceEngineState
    try:
        row = db.query(CadenceEngineState).filter(CadenceEngineState.id == 1).first()
        if not row:
            row = CadenceEngineState(id=1, consecutive_failures=0)
            db.add(row)
        for k, v in fields.items():
            if hasattr(row, k):
                setattr(row, k, v)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"[CADENCE-OBS] update_engine_state falhou: {e}")
        return {}


def _row_to_dict(row) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "last_tick_at": row.last_tick_at,
        "last_send_at": row.last_send_at,
        "pause_until": row.pause_until,
        "pause_reason": row.pause_reason,
        "consecutive_failures": int(row.consecutive_failures or 0),
        "updated_at": row.updated_at,
    }


def cleanup_old_events(db: Session, retention_days: int = 90) -> int:
    """
    Remove eventos com mais de N dias. Retorna quantos foram apagados.
    Chamado uma vez no startup; barato.
    """
    from database.models import CadenceCampaignEvent
    try:
        cutoff = datetime.utcnow() - timedelta(days=int(retention_days))
        n = (
            db.query(CadenceCampaignEvent)
            .filter(CadenceCampaignEvent.occurred_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(n or 0)
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning(f"[CADENCE-OBS] cleanup_old_events falhou: {e}")
        return 0


def list_events_for_campaign(
    db: Session,
    campaign_kind: str,
    campaign_id: int,
    limit: int = 100,
    before_id: Optional[int] = None,
) -> Iterable[Dict[str, Any]]:
    """
    Lista eventos de uma campanha em ordem cronológica decrescente,
    com paginação por cursor (before_id).
    """
    from database.models import CadenceCampaignEvent, User
    q = (
        db.query(CadenceCampaignEvent, User)
        .outerjoin(User, User.id == CadenceCampaignEvent.user_id)
        .filter(
            CadenceCampaignEvent.campaign_kind == campaign_kind,
            CadenceCampaignEvent.campaign_id == int(campaign_id),
        )
    )
    if before_id:
        q = q.filter(CadenceCampaignEvent.id < int(before_id))
    rows = q.order_by(desc(CadenceCampaignEvent.occurred_at), desc(CadenceCampaignEvent.id)).limit(int(limit)).all()
    out = []
    for evt, user in rows:
        try:
            payload = json.loads(evt.payload) if evt.payload else {}
        except Exception:
            payload = {}
        out.append({
            "id": evt.id,
            "event_type": evt.event_type,
            "payload": payload,
            "user_id": evt.user_id,
            "user_name": (user.full_name if user and getattr(user, "full_name", None) else (user.username if user else None)),
            "occurred_at": evt.occurred_at.isoformat() if evt.occurred_at else None,
            "created_at": evt.created_at.isoformat() if evt.created_at else None,
            "is_backfill": bool(payload.get("is_backfill")) if isinstance(payload, dict) else False,
        })
    return out
