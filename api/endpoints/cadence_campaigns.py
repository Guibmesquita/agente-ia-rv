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
    daily_limit: int = 50
    contacts: List[ContactInput]


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

    if not data.contacts:
        raise HTTPException(status_code=400, detail="Lista de contatos não pode estar vazia")

    if data.deadline_days < 1:
        raise HTTPException(status_code=400, detail="deadline_days deve ser >= 1")
    if data.daily_limit < 1:
        raise HTTPException(status_code=400, detail="daily_limit deve ser >= 1")

    plan = calculate_daily_plan(len(data.contacts), data.deadline_days, data.daily_limit)

    now = datetime.now(tz)
    campaign = CadenceCampaign(
        name=data.name,
        status="scheduled",
        total_contacts=len(data.contacts),
        daily_limit=data.daily_limit,
        deadline_days=data.deadline_days,
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
    print(f"[CADENCE] Campanha '{campaign.name}' retomada")
    return {"message": "Campanha retomada", "status": "firing"}


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
