from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func
from database.database import get_db
from database.models import (
    CadenceCampaign, CadenceCampaignContact, CampaignDailyLog
)
from api.endpoints.auth import require_role
from datetime import datetime, date, time as dt_time
from typing import List, Optional
from pydantic import BaseModel
from zoneinfo import ZoneInfo

router = APIRouter(prefix="/api/cadence-campaigns", tags=["cadence-campaigns"])

tz = ZoneInfo("America/Sao_Paulo")

def _get_auth():
    return require_role(["admin", "gestao_rv"])


class ContactInput(BaseModel):
    phone: str
    name: Optional[str] = None
    message: str


class CampaignCreateInput(BaseModel):
    name: str
    deadline_days: int = 5
    # Optional: quando None, o limite efetivo é derivado do perfil
    # (50 conservador / 80 padrão / 120 acelerado).
    daily_limit: Optional[int] = None
    cadence_profile: str = "conservador"
    contacts: List[ContactInput]


class CadenceProfileInput(BaseModel):
    cadence_profile: str


def _build_campaign_response(campaign: CadenceCampaign, db: Session, include_contacts: bool = False):
    sent = db.query(sql_func.count(CadenceCampaignContact.id)).filter(
        CadenceCampaignContact.campaign_id == campaign.id,
        CadenceCampaignContact.status == "sent"
    ).scalar() or 0

    pending = db.query(sql_func.count(CadenceCampaignContact.id)).filter(
        CadenceCampaignContact.campaign_id == campaign.id,
        CadenceCampaignContact.status == "pending"
    ).scalar() or 0

    failed = db.query(sql_func.count(CadenceCampaignContact.id)).filter(
        CadenceCampaignContact.campaign_id == campaign.id,
        CadenceCampaignContact.status == "failed"
    ).scalar() or 0

    responded = db.query(sql_func.count(CadenceCampaignContact.id)).filter(
        CadenceCampaignContact.campaign_id == campaign.id,
        CadenceCampaignContact.status == "responded"
    ).scalar() or 0

    total_delivered = sent + responded
    response_rate = round((responded / total_delivered * 100), 1) if total_delivered > 0 else 0.0

    daily_logs = (
        db.query(CampaignDailyLog)
        .filter(CampaignDailyLog.campaign_id == campaign.id)
        .order_by(CampaignDailyLog.log_date.asc())
        .all()
    )

    result = {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "total_contacts": campaign.total_contacts,
        "sent": sent + responded,
        "pending": pending,
        "failed": failed,
        "responded": responded,
        "response_rate": response_rate,
        "daily_limit": campaign.daily_limit,
        "deadline_days": campaign.deadline_days,
        "cadence_profile": getattr(campaign, "cadence_profile", None) or "conservador",
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "daily_log": [
            {
                "date": dl.log_date.strftime("%Y-%m-%d") if dl.log_date else None,
                "sent": dl.sent_count or 0,
                "failed": dl.failed_count or 0,
                "responded": dl.responded_count or 0,
            }
            for dl in daily_logs
        ],
    }

    if include_contacts:
        contacts = (
            db.query(CadenceCampaignContact)
            .filter(CadenceCampaignContact.campaign_id == campaign.id)
            .order_by(CadenceCampaignContact.priority.asc(), CadenceCampaignContact.scheduled_for.asc())
            .all()
        )
        result["contacts"] = [
            {
                "id": c.id,
                "phone": c.phone,
                "name": c.name,
                "status": c.status,
                "priority": c.priority,
                "scheduled_for": c.scheduled_for.isoformat() if c.scheduled_for else None,
                "sent_at": c.sent_at.isoformat() if c.sent_at else None,
                "delivered": c.delivered,
                "responded_at": c.responded_at.isoformat() if c.responded_at else None,
                "retry_count": c.retry_count,
                "custom_message": c.custom_message[:100] + "..." if c.custom_message and len(c.custom_message) > 100 else c.custom_message,
            }
            for c in contacts
        ]

    return result


@router.get("")
async def list_campaigns(db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    campaigns = (
        db.query(CadenceCampaign)
        .order_by(CadenceCampaign.created_at.desc())
        .all()
    )
    return [_build_campaign_response(c, db) for c in campaigns]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: int, db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return _build_campaign_response(campaign, db, include_contacts=True)


@router.post("")
async def create_campaign(data: CampaignCreateInput, db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    from services.campaign_planner import calculate_daily_plan, prioritize_contacts, assign_scheduled_times
    from services.cadence_profiles import is_valid_profile, PROFILES

    if not data.contacts:
        raise HTTPException(status_code=400, detail="Lista de contatos não pode estar vazia")

    if data.deadline_days < 1:
        raise HTTPException(status_code=400, detail="deadline_days deve ser >= 1")
    if data.daily_limit is not None and data.daily_limit < 1:
        raise HTTPException(status_code=400, detail="daily_limit deve ser >= 1")
    if not is_valid_profile(data.cadence_profile):
        raise HTTPException(
            status_code=400,
            detail=f"Perfil inválido. Opções: {', '.join(PROFILES.keys())}"
        )

    # Resolve o limite diário efetivo a partir do perfil quando não informado.
    profile_cfg = PROFILES[str(data.cadence_profile).strip().lower()]
    effective_daily_limit = data.daily_limit if data.daily_limit is not None else int(profile_cfg["daily_limit"])

    plan = calculate_daily_plan(len(data.contacts), data.deadline_days, effective_daily_limit)

    now = datetime.now(tz)
    campaign = CadenceCampaign(
        name=data.name,
        status="scheduled",
        total_contacts=len(data.contacts),
        # Persistimos None quando o usuário não informa, para que futuras
        # alterações de perfil (ex: PATCH /profile) recalculem corretamente
        # contra o novo perfil em vez de ficarem presas ao default antigo.
        daily_limit=data.daily_limit,
        deadline_days=data.deadline_days,
        cadence_profile=str(data.cadence_profile).strip().lower(),
        start_date=now,
        created_by=current_user.id if hasattr(current_user, 'id') else None,
    )
    db.add(campaign)
    db.flush()

    for contact_data in data.contacts:
        contact = CadenceCampaignContact(
            campaign_id=campaign.id,
            phone=contact_data.phone,
            name=contact_data.name,
            custom_message=contact_data.message,
            status="pending",
        )
        db.add(contact)

    db.commit()
    db.refresh(campaign)

    prioritize_contacts(campaign.id, db)
    assign_scheduled_times(campaign.id, db)

    campaign.status = "firing"
    db.commit()

    # Task #221 — eventos de criação e início
    from services.cadence_events import (
        emit_event, CAMPAIGN_KIND_LEGACY,
        EVENT_CAMPAIGN_CREATED, EVENT_CAMPAIGN_STARTED,
    )
    user_id_actor = getattr(current_user, "id", None)
    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_CREATED, {
        "name": campaign.name,
        "total_contacts": len(data.contacts),
        "deadline_days": data.deadline_days,
        "daily_limit": effective_daily_limit,
        "cadence_profile": campaign.cadence_profile,
    }, user_id=user_id_actor)
    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_STARTED, {
        "auto": True,
    }, user_id=user_id_actor)

    response = _build_campaign_response(campaign, db)
    response["alerta"] = plan.get("alerta")
    response["plano"] = plan

    print(f"[CADENCE] Campanha '{campaign.name}' criada com {len(data.contacts)} contatos, prazo {data.deadline_days} dias")
    return response


@router.patch("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.status != "firing":
        raise HTTPException(status_code=400, detail=f"Campanha não pode ser pausada (status atual: {campaign.status})")

    campaign.status = "paused"
    db.commit()
    from services.cadence_events import emit_event, CAMPAIGN_KIND_LEGACY, EVENT_CAMPAIGN_PAUSED
    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_PAUSED, {
        "manual": True,
    }, user_id=getattr(current_user, "id", None))
    print(f"[CADENCE] Campanha '{campaign.name}' pausada")
    return {"message": "Campanha pausada", "status": "paused"}


@router.patch("/{campaign_id}/resume")
async def resume_campaign(campaign_id: int, db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    from services.campaign_planner import assign_scheduled_times

    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.status != "paused":
        raise HTTPException(status_code=400, detail=f"Campanha não pode ser retomada (status atual: {campaign.status})")

    assign_scheduled_times(campaign.id, db, only_pending=True)

    campaign.status = "firing"
    db.commit()
    from services.cadence_events import emit_event, CAMPAIGN_KIND_LEGACY, EVENT_CAMPAIGN_RESUMED
    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_RESUMED, {
        "manual": True,
    }, user_id=getattr(current_user, "id", None))
    print(f"[CADENCE] Campanha '{campaign.name}' retomada")
    return {"message": "Campanha retomada", "status": "firing"}


@router.patch("/{campaign_id}/profile")
async def change_profile(
    campaign_id: int,
    data: CadenceProfileInput,
    db: Session = Depends(get_db),
    current_user=Depends(_get_auth()),
):
    """
    Troca o perfil de velocidade da campanha legada e reagenda apenas os
    contatos com status 'pending'. Os já enviados/falhados não são tocados.
    """
    from services.campaign_planner import assign_scheduled_times
    from services.cadence_profiles import is_valid_profile, PROFILES

    if not is_valid_profile(data.cadence_profile):
        raise HTTPException(
            status_code=400,
            detail=f"Perfil inválido. Opções: {', '.join(PROFILES.keys())}"
        )

    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")

    old_profile = getattr(campaign, "cadence_profile", None) or "conservador"
    campaign.cadence_profile = str(data.cadence_profile).strip().lower()
    db.commit()

    rescheduled_count = 0
    if campaign.status in ("firing", "paused"):
        rescheduled_count = assign_scheduled_times(campaign.id, db, only_pending=True) or 0

    from services.cadence_events import emit_event, CAMPAIGN_KIND_LEGACY, EVENT_PROFILE_CHANGED
    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_PROFILE_CHANGED, {
        "old_profile": old_profile,
        "new_profile": campaign.cadence_profile,
        "rescheduled_count": int(rescheduled_count),
    }, user_id=getattr(current_user, "id", None))

    print(
        f"[CADENCE] Perfil da campanha legada '{campaign.name}' (id={campaign_id}) alterado: "
        f"{old_profile} → {campaign.cadence_profile} ({rescheduled_count} contatos reagendados)"
    )

    return {
        "message": "Perfil atualizado",
        "cadence_profile": campaign.cadence_profile,
        "rescheduled_count": rescheduled_count,
    }


@router.get("/profiles/list")
async def list_cadence_profiles(current_user=Depends(_get_auth())):
    from services.cadence_profiles import list_profiles
    return {"profiles": list_profiles()}


@router.get("/{campaign_id}/events")
async def get_legacy_campaign_events(
    campaign_id: int,
    limit: int = 100,
    before_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(_get_auth())
):
    """Task #221 — timeline de eventos de uma campanha de cadência legada."""
    from services.cadence_events import list_events_for_campaign, CAMPAIGN_KIND_LEGACY
    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    events = list(list_events_for_campaign(db, CAMPAIGN_KIND_LEGACY, campaign_id, limit=int(limit), before_id=before_id))
    return {
        "campaign_id": campaign_id,
        "campaign_kind": CAMPAIGN_KIND_LEGACY,
        "count": len(events),
        "events": events,
    }


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db), current_user=Depends(_get_auth())):
    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.status == "firing":
        raise HTTPException(status_code=400, detail="Não é possível excluir uma campanha em andamento. Pause-a primeiro.")

    db.delete(campaign)
    db.commit()
    print(f"[CADENCE] Campanha '{campaign.name}' excluída")
    return {"message": "Campanha excluída"}
