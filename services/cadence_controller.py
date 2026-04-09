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
        CadenceCampaign, CadenceCampaignContact, CampaignDailyLog,
        Campaign, CampaignDispatch
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
        sent_this_tick = False

        active_legacy = (
            db.query(CadenceCampaign)
            .filter(CadenceCampaign.status == "firing")
            .all()
        )

        today_date = now.date()

        for campaign in active_legacy:
            if sent_this_tick:
                break

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
                    print(f"[CADENCE] Campanha legada '{campaign.name}' (id={campaign.id}) concluída!")
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
                    print(f"[CADENCE] Enviado para {next_contact.phone} (campanha legada '{campaign.name}')")
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

            sent_this_tick = True

        if not sent_this_tick:
            stale_threshold = now - timedelta(minutes=10)
            stale_dispatches = (
                db.query(CampaignDispatch)
                .filter(
                    CampaignDispatch.status == "processing",
                    CampaignDispatch.scheduled_for < stale_threshold,
                )
                .all()
            )
            for stale in stale_dispatches:
                stale.retry_count = (stale.retry_count or 0) + 1
                if stale.retry_count >= 3:
                    stale.status = "failed"
                    stale.error_message = "Travado em processing por mais de 10 minutos"
                else:
                    stale.status = "pending"
                    stale.scheduled_for = now + timedelta(minutes=5)
            if stale_dispatches:
                db.commit()
                print(f"[CADENCE] Recuperados {len(stale_dispatches)} dispatches travados em processing")

            active_unified = (
                db.query(Campaign)
                .filter(Campaign.status == "firing_cadence")
                .all()
            )

            for campaign in active_unified:
                if sent_this_tick:
                    break

                today_sent = (
                    db.query(CampaignDispatch)
                    .filter(
                        CampaignDispatch.campaign_id == campaign.id,
                        CampaignDispatch.status.in_(["sent", "responded"]),
                        CampaignDispatch.sent_at >= datetime.combine(today_date, time.min, tzinfo=tz),
                    )
                    .count()
                )

                if today_sent >= (campaign.daily_limit or 50):
                    continue

                from sqlalchemy import text as sql_text
                claim_result = db.execute(
                    sql_text("""
                        UPDATE campaign_dispatches SET status = 'processing'
                        WHERE id = (
                            SELECT id FROM campaign_dispatches
                            WHERE campaign_id = :cid AND status = 'pending' AND scheduled_for <= :now
                            ORDER BY scheduled_for ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING id
                    """),
                    {"cid": campaign.id, "now": now}
                )
                claimed_row = claim_result.fetchone()
                db.commit()

                if claimed_row:
                    next_dispatch = db.query(CampaignDispatch).filter(CampaignDispatch.id == claimed_row[0]).first()
                else:
                    next_dispatch = None

                if not next_dispatch:
                    remaining = (
                        db.query(CampaignDispatch)
                        .filter(
                            CampaignDispatch.campaign_id == campaign.id,
                            CampaignDispatch.status.in_(["pending", "processing"]),
                        )
                        .count()
                    )
                    if remaining == 0:
                        campaign.status = "cadence_done"
                        campaign.messages_sent = (
                            db.query(CampaignDispatch)
                            .filter(
                                CampaignDispatch.campaign_id == campaign.id,
                                CampaignDispatch.status.in_(["sent", "responded"]),
                            )
                            .count()
                        )
                        campaign.messages_failed = (
                            db.query(CampaignDispatch)
                            .filter(
                                CampaignDispatch.campaign_id == campaign.id,
                                CampaignDispatch.status == "failed",
                            )
                            .count()
                        )
                        db.commit()
                        print(f"[CADENCE] Campanha unificada '{campaign.name}' (id={campaign.id}) concluída!")
                    continue

                phone = next_dispatch.assessor_phone
                message = next_dispatch.message_content

                if not phone:
                    next_dispatch.status = "failed"
                    next_dispatch.error_message = "Telefone não informado"
                    db.commit()
                    continue

                zapi = ZAPIClient()
                if not zapi.is_configured():
                    next_dispatch.status = "pending"
                    next_dispatch.scheduled_for = now + timedelta(minutes=5)
                    db.commit()
                    print("[CADENCE] Z-API não configurada, dispatch devolvido para pending")
                    return

                try:
                    attachment_url = campaign.attachment_url
                    attachment_type = campaign.attachment_type
                    attachment_filename = campaign.attachment_filename

                    if attachment_url and attachment_type:
                        from core.config import get_public_domain
                        replit_domain = get_public_domain()
                        full_url = f"https://{replit_domain}{attachment_url}" if replit_domain and attachment_url.startswith('/') else attachment_url
                        if attachment_type == "image":
                            result = await zapi.send_image(phone, full_url, message)
                        elif attachment_type == "video":
                            result = await zapi.send_video(phone, full_url, message)
                        elif attachment_type == "audio":
                            result = await zapi.send_audio(phone, full_url)
                        else:
                            result = await zapi.send_document(phone, full_url, attachment_filename or "", message)
                    else:
                        result = await zapi.send_text(
                            to=phone,
                            message=message,
                            delay_typing=3,
                        )

                    if result.get("success"):
                        next_dispatch.status = "sent"
                        next_dispatch.sent_at = now
                        _consecutive_failures = 0
                        _last_send_time = now

                        _persist_unified_campaign_message(db, phone, message, campaign.name)

                        db.commit()
                        print(f"[CADENCE] Enviado para {phone} (campanha '{campaign.name}')")
                    else:
                        next_dispatch.retry_count = (next_dispatch.retry_count or 0) + 1
                        _consecutive_failures += 1

                        if next_dispatch.retry_count >= 3:
                            next_dispatch.status = "failed"
                            next_dispatch.error_message = result.get("error", "desconhecido")
                        else:
                            next_dispatch.status = "pending"
                            next_dispatch.scheduled_for = now + timedelta(minutes=10)

                        db.commit()
                        error_msg = result.get("error", "desconhecido")
                        print(f"[CADENCE] Falha ao enviar para {phone}: {error_msg} (tentativa {next_dispatch.retry_count})")

                        if _consecutive_failures >= 2:
                            _pause_until = now + timedelta(minutes=20)
                            _consecutive_failures = 0
                            print(f"[CADENCE] ⚠ 2 falhas consecutivas — pausando disparos por 20 minutos até {_pause_until.strftime('%H:%M')}")

                except Exception as send_err:
                    next_dispatch.retry_count = (next_dispatch.retry_count or 0) + 1
                    if next_dispatch.retry_count >= 3:
                        next_dispatch.status = "failed"
                        next_dispatch.error_message = str(send_err)
                    else:
                        next_dispatch.status = "pending"
                        next_dispatch.scheduled_for = now + timedelta(minutes=10)
                    db.commit()
                    print(f"[CADENCE] Erro ao enviar para {phone}: {send_err}")

                sent_this_tick = True

    except Exception as e:
        print(f"[CADENCE] Erro no tick: {e}")
    finally:
        db.close()


def _persist_unified_campaign_message(db, phone: str, message: str, campaign_name: str):
    try:
        from database.models import WhatsAppMessage, MessageDirection, MessageType, SenderType, Conversation
        clean_phone = ''.join(filter(str.isdigit, phone))
        if not clean_phone:
            return

        conversation = db.query(Conversation).filter(
            Conversation.phone == clean_phone
        ).first()
        if not conversation:
            conversation = Conversation(phone=clean_phone)
            db.add(conversation)
            db.flush()

        tag = f"[Campanha: {campaign_name}] " if campaign_name else ""
        record = WhatsAppMessage(
            chat_id=clean_phone,
            phone=clean_phone,
            direction=MessageDirection.OUTBOUND.value,
            message_type=MessageType.TEXT.value,
            from_me=True,
            body=f"{tag}{message}",
            ai_response=None,
            ai_intent="campaign_dispatch",
            sender_type=SenderType.BOT.value,
            conversation_id=conversation.id,
        )
        db.add(record)
        db.flush()
    except Exception as e:
        print(f"[CADENCE] Erro ao salvar mensagem de campanha: {e}")


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
    from database.models import CadenceCampaignContact, CampaignDailyLog, CampaignDispatch
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
        print(f"[CADENCE] Resposta registrada de {phone} para campanha legada {contact.campaign_id}")
        return True

    dispatch = (
        db.query(CampaignDispatch)
        .filter(
            CampaignDispatch.status == "sent",
            CampaignDispatch.responded_at.is_(None),
            CampaignDispatch.assessor_phone.ilike(f"%{phone_suffix}%"),
        )
        .first()
    )

    if dispatch:
        dispatch.responded_at = now
        dispatch.status = "responded"
        db.commit()
        print(f"[CADENCE] Resposta registrada de {phone} para campanha unificada {dispatch.campaign_id}")
        return True

    return False
