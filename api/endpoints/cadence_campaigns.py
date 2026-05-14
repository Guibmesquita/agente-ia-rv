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


class CadenceFinalizeNowInput(BaseModel):
    """Task #222 — payload do "Finalizar disparos agora" (legada).

    ``confirmation`` deve ser exatamente "FINALIZAR" para evitar acionamento
    acidental. ``override_business_hours`` é opt-in.
    """
    confirmation: str
    override_business_hours: bool = False


def _build_campaign_response(campaign: CadenceCampaign, db: Session, include_contacts: bool = False):
    from datetime import datetime, timedelta
    from services.cadence_profiles import get_profile

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

    # Task #221 — observabilidade
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    sent_last_hour = db.query(sql_func.count(CadenceCampaignContact.id)).filter(
        CadenceCampaignContact.campaign_id == campaign.id,
        CadenceCampaignContact.status.in_(["sent", "responded"]),
        CadenceCampaignContact.sent_at >= one_hour_ago,
    ).scalar() or 0

    next_pending = (
        db.query(CadenceCampaignContact)
        .filter(
            CadenceCampaignContact.campaign_id == campaign.id,
            CadenceCampaignContact.status == "pending",
            CadenceCampaignContact.scheduled_for.isnot(None),
        )
        .order_by(CadenceCampaignContact.scheduled_for.asc())
        .first()
    )
    next_send_eta = next_pending.scheduled_for.isoformat() if (next_pending and next_pending.scheduled_for) else None

    last_err_row = (
        db.query(CadenceCampaignContact)
        .filter(
            CadenceCampaignContact.campaign_id == campaign.id,
            CadenceCampaignContact.last_error_message.isnot(None),
        )
        .order_by(CadenceCampaignContact.sent_at.desc().nullslast(), CadenceCampaignContact.id.desc())
        .first()
    )
    last_error_message = last_err_row.last_error_message if last_err_row else None
    profile_cfg = get_profile(getattr(campaign, "cadence_profile", None))

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
        # Task #222 — flags do modo "Finalizar disparos agora"
        "cadence_turbo_active": bool(getattr(campaign, "cadence_turbo_active", False)),
        "cadence_turbo_origin_profile": getattr(campaign, "cadence_turbo_origin_profile", None),
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        # Task #221 — paridade observabilidade
        "sent_last_hour": int(sent_last_hour),
        "next_send_eta": next_send_eta,
        "last_error_message": last_error_message,
        "cooldown_seconds": int(profile_cfg.get("cooldown_seconds", 0)),
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
    from services.cadence_profiles import is_valid_profile, PROFILES, USER_SELECTABLE_PROFILES

    if not data.contacts:
        raise HTTPException(status_code=400, detail="Lista de contatos não pode estar vazia")

    if data.deadline_days < 1:
        raise HTTPException(status_code=400, detail="deadline_days deve ser >= 1")
    if data.daily_limit is not None and data.daily_limit < 1:
        raise HTTPException(status_code=400, detail="daily_limit deve ser >= 1")
    if not is_valid_profile(data.cadence_profile):
        raise HTTPException(
            status_code=400,
            detail=f"Perfil inválido. Opções: {', '.join(USER_SELECTABLE_PROFILES)}"
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

    # Task #224 — resolver channel_id de cada contato pelo telefone via assessor.
    from database.models import Assessor as _Assessor
    from database.models import UnidadeChannelMapping as _UCM

    def _resolve_channel_for_phone(phone: str) -> int | None:
        if not phone:
            return None
        # Normaliza e compara pelos últimos 10 dígitos para tolerância de DDI.
        norm = phone.lstrip("+").replace(" ", "").replace("-", "")
        suffix = norm[-10:]
        assessor = (
            db.query(_Assessor)
            .filter(_Assessor.telefone_whatsapp.ilike(f"%{suffix}%"))
            .first()
        )
        if assessor and assessor.channel_id:
            return assessor.channel_id
        if assessor and assessor.unidade:
            mapping = (
                db.query(_UCM)
                .filter(_UCM.unidade == assessor.unidade)
                .first()
            )
            if mapping:
                return mapping.channel_id
        return None

    for contact_data in data.contacts:
        contact = CadenceCampaignContact(
            campaign_id=campaign.id,
            phone=contact_data.phone,
            name=contact_data.name,
            custom_message=contact_data.message,
            status="pending",
            channel_id=_resolve_channel_for_phone(contact_data.phone),
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

    # Task #222 — em turbo, reagenda com o cronograma turbo (30-90s).
    if bool(getattr(campaign, "cadence_turbo_active", False)):
        from services.campaign_planner import reschedule_legacy_for_turbo
        reschedule_legacy_for_turbo(
            campaign.id,
            db,
            override_business_hours=False,
        )
    else:
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
    from services.cadence_profiles import is_valid_profile, PROFILES, USER_SELECTABLE_PROFILES

    if not is_valid_profile(data.cadence_profile):
        raise HTTPException(
            status_code=400,
            detail=f"Perfil inválido. Opções: {', '.join(USER_SELECTABLE_PROFILES)}"
        )

    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")

    # Task #222 — não permitir troca manual de perfil enquanto a campanha está
    # em modo turbo, para evitar estado contraditório (flag turbo + perfil normal).
    if bool(getattr(campaign, "cadence_turbo_active", False)):
        raise HTTPException(
            status_code=409,
            detail="Campanha em modo turbo — não é possível trocar o perfil agora. Aguarde a conclusão dos disparos.",
        )

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


@router.post("/{campaign_id}/finalize-now")
async def finalize_legacy_cadence_now(
    campaign_id: int,
    data: CadenceFinalizeNowInput,
    db: Session = Depends(get_db),
    current_user=Depends(_get_auth()),
):
    """
    Task #222 — Modo "Finalizar disparos agora" (turbo seguro) para
    campanhas legadas. Comprime os contatos pendentes com intervalo
    30-90s. Mantém defesas anti-bloqueio mínimas. Idempotente.
    """
    from services.campaign_planner import reschedule_legacy_for_turbo
    from services.cadence_profiles import TURBO_PROFILE_NAME
    from services.cadence_events import (
        emit_event, CAMPAIGN_KIND_LEGACY, EVENT_TURBO_STARTED,
    )

    if (data.confirmation or "").strip().upper() != "FINALIZAR":
        raise HTTPException(
            status_code=400,
            detail='Confirmação inválida — digite exatamente "FINALIZAR".',
        )

    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if campaign.status not in ("firing", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Apenas campanhas em disparo podem ser finalizadas (status: {campaign.status})",
        )

    pending_count = (
        db.query(CadenceCampaignContact)
        .filter(
            CadenceCampaignContact.campaign_id == campaign_id,
            CadenceCampaignContact.status == "pending",
        )
        .count()
    )
    if pending_count == 0:
        raise HTTPException(status_code=400, detail="Sem contatos pendentes para finalizar.")

    origin_profile = campaign.cadence_turbo_origin_profile or (
        getattr(campaign, "cadence_profile", None) or "conservador"
    )
    campaign.cadence_turbo_origin_profile = origin_profile
    campaign.cadence_turbo_active = True
    campaign.cadence_turbo_override_business_hours = bool(data.override_business_hours)
    campaign.cadence_profile = TURBO_PROFILE_NAME
    if campaign.status == "paused":
        campaign.status = "firing"
    db.commit()

    rescheduled = reschedule_legacy_for_turbo(
        campaign_id, db, override_business_hours=bool(data.override_business_hours)
    )

    eta_seconds = int(pending_count) * 60

    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_TURBO_STARTED, {
        "original_profile": origin_profile,
        "origin_profile": origin_profile,
        "override_business_hours": bool(data.override_business_hours),
        "rescheduled_count": int(rescheduled),
        "pending_at_start": int(pending_count),
        "pending_count": int(pending_count),
        "eta_seconds": int(eta_seconds),
    }, user_id=getattr(current_user, "id", None))

    print(
        f"[CADENCE-TURBO] Campanha legada '{campaign.name}' (id={campaign_id}) em modo turbo. "
        f"{rescheduled} contatos reagendados (origin={origin_profile})."
    )

    return {
        "message": "Modo turbo ativado",
        "status": campaign.status,
        "cadence_profile": campaign.cadence_profile,
        "original_profile": origin_profile,
        "origin_profile": origin_profile,
        "rescheduled_contacts": rescheduled,
        "pending_count": int(pending_count),
        "eta_seconds": int(eta_seconds),
        "override_business_hours": bool(data.override_business_hours),
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
    safe_limit = max(1, min(int(limit), 500))
    events = list(list_events_for_campaign(db, CAMPAIGN_KIND_LEGACY, campaign_id, limit=safe_limit, before_id=before_id))
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
