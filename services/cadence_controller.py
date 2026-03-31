import asyncio
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_last_send_time: Optional[datetime] = None
_consecutive_failures: int = 0
_pause_until: Optional[datetime] = None
_running: bool = False


async def run_cadence_tick():
    global _last_send_time, _consecutive_failures, _pause_until

    from database.database import SessionLocal
    from database.models import (
        CadenceCampaign, CadenceCampaignContact, CampaignDailyLog
    )
    from services.whatsapp_client import ZAPIClient
    from sqlalchemy import and_
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)

    if now.weekday() >= 5:
        return

    work_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    work_end = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now < work_start or now >= work_end:
        return

    if _pause_until and now < _pause_until:
        return

    if _last_send_time:
        elapsed = (now - _last_send_time).total_seconds()
        if elapsed < 480:
            return

    db = SessionLocal()
    try:
        active_campaigns = (
            db.query(CadenceCampaign)
            .filter(CadenceCampaign.status == "firing")
            .all()
        )

        if not active_campaigns:
            return

        today_date = now.date()

        for campaign in active_campaigns:
            daily_log = (
                db.query(CampaignDailyLog)
                .filter(
                    CampaignDailyLog.campaign_id == campaign.id,
                    CampaignDailyLog.log_date == datetime.combine(today_date, time.min, tzinfo=tz)
                )
                .first()
            )

            if daily_log and daily_log.sent_count >= campaign.daily_limit:
                continue

            next_contact = (
                db.query(CadenceCampaignContact)
                .filter(
                    CadenceCampaignContact.campaign_id == campaign.id,
                    CadenceCampaignContact.status == "pending",
                    CadenceCampaignContact.scheduled_for <= now,
                )
                .order_by(CadenceCampaignContact.scheduled_for.asc())
                .first()
            )

            if not next_contact:
                pending_count = (
                    db.query(CadenceCampaignContact)
                    .filter(
                        CadenceCampaignContact.campaign_id == campaign.id,
                        CadenceCampaignContact.status == "pending",
                    )
                    .count()
                )
                if pending_count == 0:
                    campaign.status = "done"
                    campaign.end_date = now
                    db.commit()
                    print(f"[CADENCE] Campanha '{campaign.name}' (id={campaign.id}) concluída!")
                continue

            zapi = ZAPIClient()
            if not zapi.is_configured():
                print("[CADENCE] Z-API não configurada, pulando envio")
                return

            try:
                result = await zapi.send_text(
                    to=next_contact.phone,
                    message=next_contact.custom_message,
                    delay_typing=3,
                )

                if result.get("success"):
                    next_contact.status = "sent"
                    next_contact.sent_at = now
                    next_contact.delivered = True
                    _consecutive_failures = 0

                    if not daily_log:
                        daily_log = CampaignDailyLog(
                            campaign_id=campaign.id,
                            log_date=datetime.combine(today_date, time.min, tzinfo=tz),
                            sent_count=1,
                        )
                        db.add(daily_log)
                    else:
                        daily_log.sent_count += 1

                    _last_send_time = now
                    db.commit()
                    print(f"[CADENCE] Enviado para {next_contact.phone} (campanha '{campaign.name}')")
                else:
                    next_contact.retry_count += 1
                    _consecutive_failures += 1

                    if next_contact.retry_count >= 3:
                        next_contact.status = "failed"
                        if not daily_log:
                            daily_log = CampaignDailyLog(
                                campaign_id=campaign.id,
                                log_date=datetime.combine(today_date, time.min, tzinfo=tz),
                                failed_count=1,
                            )
                            db.add(daily_log)
                        else:
                            daily_log.failed_count += 1

                    db.commit()
                    error_msg = result.get("error", "desconhecido")
                    print(f"[CADENCE] Falha ao enviar para {next_contact.phone}: {error_msg} (tentativa {next_contact.retry_count})")

                    if _consecutive_failures >= 2:
                        _pause_until = now + timedelta(minutes=20)
                        _consecutive_failures = 0
                        print(f"[CADENCE] ⚠ 2 falhas consecutivas — pausando disparos por 20 minutos até {_pause_until.strftime('%H:%M')}")

            except Exception as send_err:
                next_contact.retry_count += 1
                if next_contact.retry_count >= 3:
                    next_contact.status = "failed"
                db.commit()
                print(f"[CADENCE] Erro ao enviar para {next_contact.phone}: {send_err}")

            return

    except Exception as e:
        print(f"[CADENCE] Erro no tick: {e}")
    finally:
        db.close()


async def cadence_loop():
    global _running
    if _running:
        return
    _running = True
    print("[CADENCE] Motor de cadência iniciado")

    await asyncio.sleep(15)

    while _running:
        try:
            await run_cadence_tick()
        except Exception as e:
            if "UndefinedTable" in str(e) or "does not exist" in str(e):
                await asyncio.sleep(30)
            else:
                print(f"[CADENCE] Erro no loop: {e}")
        await asyncio.sleep(30)


def stop_cadence():
    global _running
    _running = False
    print("[CADENCE] Motor de cadência parado")


def track_campaign_response(phone: str, db):
    from database.models import CadenceCampaignContact, CampaignDailyLog
    from datetime import timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)

    phone_suffix = phone[-8:] if phone and len(phone) >= 8 else phone

    contact = (
        db.query(CadenceCampaignContact)
        .filter(
            CadenceCampaignContact.status == "sent",
            CadenceCampaignContact.responded_at.is_(None),
            CadenceCampaignContact.phone.ilike(f"%{phone_suffix}%"),
        )
        .first()
    )

    if contact:
        contact.responded_at = now
        contact.status = "responded"

        today_date = now.date()
        from datetime import time as dt_time
        daily_log = (
            db.query(CampaignDailyLog)
            .filter(
                CampaignDailyLog.campaign_id == contact.campaign_id,
                CampaignDailyLog.log_date == datetime.combine(today_date, dt_time.min, tzinfo=tz)
            )
            .first()
        )
        if daily_log:
            daily_log.responded_count += 1
        else:
            daily_log = CampaignDailyLog(
                campaign_id=contact.campaign_id,
                log_date=datetime.combine(today_date, dt_time.min, tzinfo=tz),
                responded_count=1,
            )
            db.add(daily_log)

        db.commit()
        print(f"[CADENCE] Resposta registrada de {phone} para campanha {contact.campaign_id}")
