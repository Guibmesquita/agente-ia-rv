import math
import random
from datetime import datetime, timedelta, date, time
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func


def calculate_daily_plan(total_contacts: int, deadline_days: int, daily_limit: int = 50) -> Dict[str, Any]:
    if total_contacts <= 0 or deadline_days <= 0:
        return {"envios_por_dia": 0, "dias_necessarios": 0, "alerta": None}

    envios_por_dia = math.ceil(total_contacts / deadline_days)
    dias_necessarios = math.ceil(total_contacts / daily_limit) if daily_limit > 0 else deadline_days
    alerta = None

    if envios_por_dia > daily_limit:
        alerta = (
            f"Atenção: volume diário necessário ({envios_por_dia}) ultrapassa o limite seguro de {daily_limit}. "
            f"Considere estender o prazo para {dias_necessarios} dias."
        )

    return {
        "envios_por_dia": envios_por_dia,
        "dias_necessarios": dias_necessarios,
        "alerta": alerta,
    }


def _get_business_days(start_date: date, num_days: int) -> List[date]:
    days = []
    current = start_date
    while len(days) < num_days:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _build_daily_schedule(
    num_contacts: int,
    base_date: date,
    profile: Optional[str] = None,
) -> List[datetime]:
    """
    Constrói os horários de envio para um único dia útil, respeitando a janela
    comercial (09h-18h) e a pausa de almoço (12h-13h30 — máximo 2 envios).

    O parâmetro ``profile`` controla os intervalos entre envios e a duração da
    pausa longa (a cada 10-12 envios). Se for None ou desconhecido, usa o
    perfil ``conservador`` (comportamento histórico).
    """
    from zoneinfo import ZoneInfo
    from services.cadence_profiles import get_profile
    tz = ZoneInfo("America/Sao_Paulo")

    cfg = get_profile(profile)
    interval_min = int(cfg["interval_min"])
    interval_max = int(cfg["interval_max"])
    pause_min = int(cfg["pause_min"])
    pause_max = int(cfg["pause_max"])

    work_start = datetime.combine(base_date, time(9, 0), tzinfo=tz)
    lunch_start = datetime.combine(base_date, time(12, 0), tzinfo=tz)
    lunch_end = datetime.combine(base_date, time(13, 30), tzinfo=tz)
    work_end = datetime.combine(base_date, time(18, 0), tzinfo=tz)

    scheduled_times = []
    current_time = work_start
    block_count = 0
    lunch_sends = 0

    for i in range(num_contacts):
        if current_time >= work_end:
            break

        if lunch_start <= current_time < lunch_end:
            if lunch_sends >= 2:
                current_time = lunch_end
                lunch_sends = 0
            else:
                lunch_sends += 1

        if current_time >= work_end:
            break

        scheduled_times.append(current_time)
        block_count += 1

        if block_count >= random.randint(10, 12):
            pause_minutes = random.randint(pause_min, pause_max)
            current_time += timedelta(minutes=pause_minutes)
            block_count = 0
        else:
            interval_minutes = random.randint(interval_min, interval_max)
            current_time += timedelta(minutes=interval_minutes)

    return scheduled_times


def prioritize_contacts(campaign_id: int, db: Session):
    from database.models import CadenceCampaignContact, Conversation, WhatsAppMessage
    from datetime import timezone

    contacts = (
        db.query(CadenceCampaignContact)
        .filter(CadenceCampaignContact.campaign_id == campaign_id)
        .all()
    )

    now = datetime.now(timezone.utc)
    two_days_ago = now - timedelta(days=2)

    for contact in contacts:
        phone = contact.phone
        if not phone:
            contact.priority = 3
            continue

        recent_msg = (
            db.query(WhatsAppMessage.id)
            .join(Conversation, Conversation.id == WhatsAppMessage.conversation_id)
            .filter(
                Conversation.phone.ilike(f"%{phone[-8:]}%"),
                WhatsAppMessage.direction == "INBOUND",
                WhatsAppMessage.created_at >= two_days_ago,
            )
            .first()
        )

        if recent_msg:
            contact.priority = 1
            continue

        any_msg = (
            db.query(Conversation.id)
            .filter(Conversation.phone.ilike(f"%{phone[-8:]}%"))
            .first()
        )

        if any_msg:
            contact.priority = 2
        else:
            contact.priority = 3

    db.commit()
    print(f"[CADENCE_PLANNER] Prioridades atribuídas para campanha {campaign_id}: "
          f"{sum(1 for c in contacts if c.priority == 1)} P1, "
          f"{sum(1 for c in contacts if c.priority == 2)} P2, "
          f"{sum(1 for c in contacts if c.priority == 3)} P3")


def assign_scheduled_times(campaign_id: int, db: Session, only_pending: bool = False):
    from database.models import CadenceCampaign, CadenceCampaignContact
    from services.cadence_profiles import get_profile

    campaign = db.query(CadenceCampaign).filter(CadenceCampaign.id == campaign_id).first()
    if not campaign:
        print(f"[CADENCE_PLANNER] Campanha {campaign_id} não encontrada")
        return 0

    profile_name = getattr(campaign, "cadence_profile", None) or "conservador"
    profile_cfg = get_profile(profile_name)

    query = (
        db.query(CadenceCampaignContact)
        .filter(CadenceCampaignContact.campaign_id == campaign_id)
    )
    if only_pending:
        query = query.filter(CadenceCampaignContact.status == "pending")

    contacts = query.order_by(
        CadenceCampaignContact.priority.asc(),
        sql_func.random()
    ).all()

    if not contacts:
        print(f"[CADENCE_PLANNER] Sem contatos para agendar na campanha {campaign_id}")
        return 0

    today = date.today()
    business_days = _get_business_days(today, campaign.deadline_days)
    # daily_limit explícito no registro tem prioridade; senão usa o do perfil.
    daily_limit = campaign.daily_limit or int(profile_cfg["daily_limit"])

    daily_cap = min(daily_limit, math.ceil(len(contacts) / len(business_days))) if business_days else daily_limit

    p3_daily_limit = 15
    contact_idx = 0

    for day in business_days:
        if contact_idx >= len(contacts):
            break

        day_contacts = []
        p3_count = 0
        for i in range(contact_idx, len(contacts)):
            if len(day_contacts) >= daily_cap:
                break
            c = contacts[i]
            if c.priority == 3:
                if p3_count >= p3_daily_limit:
                    continue
                p3_count += 1
            day_contacts.append(c)

        times = _build_daily_schedule(len(day_contacts), day, profile=profile_name)

        for j, contact in enumerate(day_contacts):
            if j < len(times):
                contact.scheduled_for = times[j]
            contact_idx += 1

    overflow = contacts[contact_idx:]
    if overflow:
        extra_day = business_days[-1] + timedelta(days=1) if business_days else today + timedelta(days=1)
        extra_days = _get_business_days(extra_day, math.ceil(len(overflow) / daily_cap) + 1)
        ov_idx = 0
        for ed in extra_days:
            if ov_idx >= len(overflow):
                break
            batch = overflow[ov_idx:ov_idx + daily_cap]
            times = _build_daily_schedule(len(batch), ed, profile=profile_name)
            for j, c in enumerate(batch):
                if j < len(times):
                    c.scheduled_for = times[j]
            ov_idx += len(batch)
        print(f"[CADENCE_PLANNER] {len(overflow)} contatos excedentes agendados em dias adicionais")

    db.commit()
    print(
        f"[CADENCE_PLANNER] {len(contacts)} contatos agendados para campanha "
        f"{campaign_id} (perfil={profile_name}) em {len(business_days)} dias úteis"
    )
    return len(contacts)


def reschedule_unified_pending_dispatches(campaign_id: int, db: Session) -> int:
    """
    Reagenda apenas os ``CampaignDispatch`` com ``status='pending'`` da
    campanha unificada, usando o perfil atual da campanha. Não toca em
    dispatches já enviados, em processamento ou falhos.

    Retorna o número de dispatches reagendados.
    """
    from database.models import Campaign, CampaignDispatch
    from services.cadence_profiles import get_profile
    from zoneinfo import ZoneInfo

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        return 0

    profile_name = getattr(campaign, "cadence_profile", None) or "conservador"
    profile_cfg = get_profile(profile_name)

    pending = (
        db.query(CampaignDispatch)
        .filter(
            CampaignDispatch.campaign_id == campaign_id,
            CampaignDispatch.status == "pending",
        )
        .order_by(
            CampaignDispatch.priority.asc(),
            CampaignDispatch.scheduled_for.asc(),
        )
        .all()
    )

    if not pending:
        return 0

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    today = now.date()

    deadline_days = campaign.deadline_days or 5
    daily_limit = campaign.daily_limit or int(profile_cfg["daily_limit"])

    business_days = _get_business_days(today, deadline_days)
    if not business_days:
        return 0

    daily_cap = min(daily_limit, math.ceil(len(pending) / len(business_days)))

    p3_daily_limit = 15
    idx = 0

    for day in business_days:
        if idx >= len(pending):
            break
        day_batch = []
        p3_count = 0
        for i in range(idx, len(pending)):
            if len(day_batch) >= daily_cap:
                break
            d = pending[i]
            if (d.priority or 3) == 3:
                if p3_count >= p3_daily_limit:
                    continue
                p3_count += 1
            day_batch.append(d)

        times = _build_daily_schedule(len(day_batch), day, profile=profile_name)
        fallback_time = datetime.combine(day, time(9, 0), tzinfo=tz)

        for j, d in enumerate(day_batch):
            d.scheduled_for = times[j] if j < len(times) else fallback_time
            idx += 1

    overflow = pending[idx:]
    if overflow:
        extra_day = business_days[-1] + timedelta(days=1)
        extra_days = _get_business_days(extra_day, math.ceil(len(overflow) / daily_cap) + 1)
        ov_idx = 0
        for ed in extra_days:
            if ov_idx >= len(overflow):
                break
            batch = overflow[ov_idx:ov_idx + daily_cap]
            times = _build_daily_schedule(len(batch), ed, profile=profile_name)
            fallback_time = datetime.combine(ed, time(9, 0), tzinfo=tz)
            for j, d in enumerate(batch):
                d.scheduled_for = times[j] if j < len(times) else fallback_time
            ov_idx += len(batch)

    db.commit()
    print(
        f"[CADENCE_PLANNER] {len(pending)} dispatches reagendados para campanha "
        f"unificada {campaign_id} (perfil={profile_name})"
    )
    return len(pending)
