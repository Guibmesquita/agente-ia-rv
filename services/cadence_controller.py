import asyncio
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Task #221 — Estas variáveis viraram apenas CACHE em memória do estado
# persistido em `cadence_engine_state` (singleton id=1). A fonte de verdade
# agora é o banco; o cache reduz hits durante o tick. São hidratadas no início
# do tick a partir do banco e gravadas de volta quando mudam.
_last_send_time: Optional[datetime] = None
_consecutive_failures: int = 0
_pause_until: Optional[datetime] = None
_pause_reason: Optional[str] = None
_running: bool = False

# Task #221 (V2) — rastreia o último estado observável emitido para
# deduplicar eventos `out_of_business_hours` / `lunch_break` /
# `global_cooldown` (só emite quando há transição). É só observabilidade;
# não influencia o comportamento do tick.
_last_observed_state: Optional[str] = None


def _emit_engine_state_transition(db, new_state: str, payload: dict):
    """Emite evento de mudança de estado do motor, com dedupe em memória.
    Persiste com kind='engine' e campaign_id=0 (eventos system-wide).
    """
    global _last_observed_state
    if _last_observed_state == new_state:
        return
    _last_observed_state = new_state
    try:
        from services.cadence_events import emit_event as _emit
        _emit(db, "engine", 0, new_state, payload)
    except Exception as e:
        logger.warning(f"[CADENCE-OBS] _emit_engine_state_transition({new_state}) falhou: {e}")


_last_tick_persist_at: Optional[datetime] = None
_TICK_PERSIST_THROTTLE_SECONDS = 60


def _persist_state(db, **fields):
    """Wrapper que silencia erros — persistir estado nunca pode quebrar o tick.

    Throttle: quando o ÚNICO campo é `last_tick_at` (heartbeat sem mudança
    de estado), só faz commit a cada `_TICK_PERSIST_THROTTLE_SECONDS` para
    não pressionar o banco a cada tick (30s). Updates com qualquer outro
    campo (last_send_at, pause_until, consecutive_failures, ...) sempre
    persistem imediatamente.
    """
    global _last_tick_persist_at
    try:
        only_heartbeat = (
            len(fields) == 1
            and "last_tick_at" in fields
            and isinstance(fields["last_tick_at"], datetime)
        )
        if only_heartbeat:
            now_ts = fields["last_tick_at"]
            if (
                _last_tick_persist_at is not None
                and (now_ts - _last_tick_persist_at).total_seconds()
                < _TICK_PERSIST_THROTTLE_SECONDS
            ):
                return
            _last_tick_persist_at = now_ts
        from services.cadence_events import update_engine_state
        update_engine_state(db, **fields)
    except Exception as e:
        logger.warning(f"[CADENCE-OBS] _persist_state falhou: {e}")


def _hydrate_from_db(db):
    """Carrega o estado persistido para o cache em memória no começo do tick."""
    global _last_send_time, _consecutive_failures, _pause_until, _pause_reason
    try:
        from services.cadence_events import get_engine_state
        st = get_engine_state(db)
        _last_send_time = st.get("last_send_at") or _last_send_time
        _consecutive_failures = int(st.get("consecutive_failures") or 0)
        _pause_until = st.get("pause_until") or _pause_until
        _pause_reason = st.get("pause_reason")
    except Exception as e:
        logger.warning(f"[CADENCE-OBS] _hydrate_from_db falhou: {e}")


async def run_cadence_tick():
    global _last_send_time, _consecutive_failures, _pause_until, _pause_reason

    from database.database import SessionLocal
    from database.models import (
        CadenceCampaign, CadenceCampaignContact, CampaignDailyLog,
        Campaign, CampaignDispatch
    )
    from services.whatsapp_client import ZAPIClient
    from services.cadence_events import (
        emit_event, CAMPAIGN_KIND_LEGACY, CAMPAIGN_KIND_UNIFIED,
        EVENT_DISPATCH_SENT, EVENT_DISPATCH_FAILED, EVENT_ANTI_BLOCK_PAUSE,
        EVENT_DAILY_LIMIT_REACHED, EVENT_CAMPAIGN_DONE,
    )
    from sqlalchemy import and_
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)

    # Task #221 (V2) — observabilidade: emitir eventos system-wide de
    # transição de estado ANTES de retornar. NÃO altera o comportamento
    # operacional do motor (mesmas condições de retorno e fluxo).
    # Abrimos uma sessão curta APENAS para o evento de transição se for
    # o caso. Sucesso ou falha desse insert nunca afeta o tick.
    if now.weekday() >= 5 or now < now.replace(hour=9, minute=0, second=0, microsecond=0) or now >= now.replace(hour=18, minute=0, second=0, microsecond=0):
        # Persistir last_tick_at + emitir transição em sessão curta dedicada
        # (não abre a `db` principal para manter o early-return barato).
        try:
            _obs_db = SessionLocal()
            try:
                _persist_state(_obs_db, last_tick_at=now)
                _emit_engine_state_transition(_obs_db, "out_of_business_hours", {
                    "weekday": now.weekday(),
                    "hour": now.hour,
                    "now": now.isoformat(),
                })
            finally:
                _obs_db.close()
        except Exception as e:
            logger.warning(f"[CADENCE-OBS] obs session falhou: {e}")
        return

    db = SessionLocal()
    try:
        # Hidrata do banco e registra tick. Estado persistente sobrevive a reinício.
        _hydrate_from_db(db)
        _persist_state(db, last_tick_at=now)

        if _pause_until and now < _pause_until:
            # last_tick_at já persistido acima — observabilidade preservada
            # mesmo em retorno antecipado por pausa anti-bloqueio.
            _emit_engine_state_transition(db, "anti_block_pause_active", {
                "pause_until": _pause_until.isoformat(),
                "pause_reason": _pause_reason,
            })
            return

        # Pausa de almoço (12:00-13:00 BRT) — comportamento original do motor:
        # bloqueia envios para evitar mensagens fora do padrão comercial.
        # Emite evento de timeline antes de retornar (last_tick_at já persistido).
        if now.hour == 12:
            _emit_engine_state_transition(db, "lunch_break", {
                "now": now.isoformat(),
                "resume_at": now.replace(hour=13, minute=0, second=0, microsecond=0).isoformat(),
            })
            return

        sent_this_tick = False
        # Task #221 (V2) — rastreia se TODAS as candidatas foram bloqueadas
        # apenas pelo cooldown (sem outros impedimentos). Se sim, emitimos
        # um único `global_cooldown` no fim do tick.
        had_candidates = False
        all_blocked_by_cooldown = True

        from services.cadence_profiles import get_profile
        active_legacy = (
            db.query(CadenceCampaign)
            .filter(CadenceCampaign.status == "firing")
            .all()
        )

        today_date = now.date()
        # Para evitar emitir N eventos "daily_limit_reached" por tick, marcamos
        # quais campanhas já tiveram o evento emitido neste tick.
        daily_limit_emitted_legacy: set = set()
        daily_limit_emitted_unified: set = set()

        for campaign in active_legacy:
            if sent_this_tick:
                break

            # Cooldown global — usa o cooldown_seconds do perfil DESTA
            # campanha (a candidata a enviar agora) contra o último envio
            # GLOBAL. Assim só pode haver um envio por janela de cooldown
            # considerando o ritmo do perfil escolhido para a campanha em
            # questão; se a candidata é "acelerada", basta esperar o cooldown
            # menor; se é "conservadora", espera o cooldown maior.
            campaign_profile = get_profile(getattr(campaign, "cadence_profile", None))
            cooldown = int(campaign_profile["cooldown_seconds"])
            had_candidates = True
            if _last_send_time and (now - _last_send_time).total_seconds() < cooldown:
                continue
            # Saiu do bloqueio de cooldown ao menos uma vez nesta candidata —
            # então não foi 100% bloqueio por cooldown.
            all_blocked_by_cooldown = False

            daily_log = (
                db.query(CampaignDailyLog)
                .filter(
                    CampaignDailyLog.campaign_id == campaign.id,
                    CampaignDailyLog.log_date == datetime.combine(today_date, time.min, tzinfo=tz)
                )
                .first()
            )

            effective_daily_limit = campaign.daily_limit or int(campaign_profile["daily_limit"])
            if daily_log and daily_log.sent_count >= effective_daily_limit:
                if campaign.id not in daily_limit_emitted_legacy:
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DAILY_LIMIT_REACHED, {
                        "limit": effective_daily_limit,
                        "sent_today": int(daily_log.sent_count or 0),
                        "profile": campaign_profile.get("label"),
                    })
                    daily_limit_emitted_legacy.add(campaign.id)
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
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_DONE, {
                        "ended_at": now.isoformat(),
                    })
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
                    next_contact.last_error_message = None
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
                    _persist_state(db, last_send_at=now, consecutive_failures=0)
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_SENT, {
                        "phone": next_contact.phone,
                        "contact_id": next_contact.id,
                        "profile": campaign_profile.get("label"),
                    })
                    print(f"[CADENCE] Enviado para {next_contact.phone} (campanha legada '{campaign.name}', perfil={campaign_profile.get('label', '?')})")
                else:
                    next_contact.retry_count += 1
                    error_msg = result.get("error", "desconhecido")
                    # Task #221 — registra erro a cada tentativa, não só na última.
                    next_contact.last_error_message = str(error_msg)[:1000]
                    _consecutive_failures += 1

                    is_final_fail = next_contact.retry_count >= 3
                    if is_final_fail:
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
                    _persist_state(db, consecutive_failures=_consecutive_failures)
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_FAILED, {
                        "phone": next_contact.phone,
                        "contact_id": next_contact.id,
                        "retry_count": int(next_contact.retry_count or 0),
                        "is_final": bool(is_final_fail),
                        "error": str(error_msg)[:500],
                    })
                    print(f"[CADENCE] Falha ao enviar para {next_contact.phone}: {error_msg} (tentativa {next_contact.retry_count})")

                    if _consecutive_failures >= 2:
                        _pause_until = now + timedelta(minutes=20)
                        _pause_reason = "anti_block"
                        _consecutive_failures = 0
                        _persist_state(db, pause_until=_pause_until, pause_reason="anti_block",
                                       consecutive_failures=0)
                        emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_ANTI_BLOCK_PAUSE, {
                            "duration_minutes": 20,
                            "pause_until": _pause_until.isoformat(),
                            "trigger": "2 falhas Z-API consecutivas",
                        })
                        print(f"[CADENCE] ⚠ 2 falhas consecutivas — pausando disparos por 20 minutos até {_pause_until.strftime('%H:%M')}")

            except Exception as send_err:
                next_contact.retry_count += 1
                next_contact.last_error_message = str(send_err)[:1000]
                if next_contact.retry_count >= 3:
                    next_contact.status = "failed"
                db.commit()
                emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_FAILED, {
                    "phone": next_contact.phone,
                    "contact_id": next_contact.id,
                    "retry_count": int(next_contact.retry_count or 0),
                    "is_final": bool(next_contact.retry_count >= 3),
                    "error": str(send_err)[:500],
                    "exception": True,
                })
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
                    stale.last_error_message = "Travado em processing por mais de 10 minutos"
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

                # Cooldown global — mesma política do bloco legacy: o
                # cooldown_seconds vem do perfil da campanha CANDIDATA, mas
                # comparado contra o último envio global. Não há cooldowns
                # paralelos por campanha.
                campaign_profile = get_profile(getattr(campaign, "cadence_profile", None))
                cooldown = int(campaign_profile["cooldown_seconds"])
                had_candidates = True
                if _last_send_time and (now - _last_send_time).total_seconds() < cooldown:
                    continue
                all_blocked_by_cooldown = False

                today_sent = (
                    db.query(CampaignDispatch)
                    .filter(
                        CampaignDispatch.campaign_id == campaign.id,
                        CampaignDispatch.status.in_(["sent", "responded"]),
                        CampaignDispatch.sent_at >= datetime.combine(today_date, time.min, tzinfo=tz),
                    )
                    .count()
                )

                effective_daily_limit = campaign.daily_limit or int(campaign_profile["daily_limit"])
                if today_sent >= effective_daily_limit:
                    if campaign.id not in daily_limit_emitted_unified:
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DAILY_LIMIT_REACHED, {
                            "limit": effective_daily_limit,
                            "sent_today": int(today_sent),
                            "profile": campaign_profile.get("label"),
                        })
                        daily_limit_emitted_unified.add(campaign.id)
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
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_CAMPAIGN_DONE, {
                            "ended_at": now.isoformat(),
                            "sent": int(campaign.messages_sent or 0),
                            "failed": int(campaign.messages_failed or 0),
                        })
                        print(f"[CADENCE] Campanha unificada '{campaign.name}' (id={campaign.id}) concluída!")
                    continue

                phone = next_dispatch.assessor_phone
                message = next_dispatch.message_content

                if not phone:
                    next_dispatch.status = "failed"
                    next_dispatch.error_message = "Telefone não informado"
                    next_dispatch.last_error_message = "Telefone não informado"
                    db.commit()
                    emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_FAILED, {
                        "dispatch_id": next_dispatch.id,
                        "is_final": True,
                        "error": "Telefone não informado",
                    })
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
                        from core.config import resolve_attachment_for_send
                        full_url = resolve_attachment_for_send(attachment_url)
                        if not full_url:
                            # Arquivo não encontrado no disco E sem URL pública
                            # configurada — o Z-API não teria como baixar o
                            # anexo. Falhar imediatamente sem consumir retries.
                            next_dispatch.status = "failed"
                            next_dispatch.error_message = "Arquivo do anexo não encontrado"
                            next_dispatch.last_error_message = "Arquivo do anexo não encontrado"
                            db.commit()
                            emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_FAILED, {
                                "dispatch_id": next_dispatch.id,
                                "is_final": True,
                                "error": "Arquivo do anexo não encontrado",
                            })
                            print(
                                f"[CADENCE] Anexo da campanha '{campaign.name}' (id={campaign.id}) "
                                f"não encontrado no disco e sem URL pública configurada. "
                                f"Dispatch {next_dispatch.id} marcado como FAILED."
                            )
                            sent_this_tick = True
                            continue
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
                        next_dispatch.last_error_message = None
                        _consecutive_failures = 0
                        _last_send_time = now

                        _persist_unified_campaign_message(db, phone, message, campaign.name)

                        db.commit()
                        _persist_state(db, last_send_at=now, consecutive_failures=0)
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_SENT, {
                            "dispatch_id": next_dispatch.id,
                            "phone": phone,
                            "profile": campaign_profile.get("label"),
                        })
                        print(f"[CADENCE] Enviado para {phone} (campanha '{campaign.name}', perfil={campaign_profile.get('label', '?')})")
                    else:
                        next_dispatch.retry_count = (next_dispatch.retry_count or 0) + 1
                        error_msg = result.get("error", "desconhecido")
                        next_dispatch.last_error_message = str(error_msg)[:1000]
                        _consecutive_failures += 1

                        is_final_fail = next_dispatch.retry_count >= 3
                        if is_final_fail:
                            next_dispatch.status = "failed"
                            next_dispatch.error_message = error_msg
                        else:
                            next_dispatch.status = "pending"
                            next_dispatch.scheduled_for = now + timedelta(minutes=10)

                        db.commit()
                        _persist_state(db, consecutive_failures=_consecutive_failures)
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_FAILED, {
                            "dispatch_id": next_dispatch.id,
                            "phone": phone,
                            "retry_count": int(next_dispatch.retry_count or 0),
                            "is_final": bool(is_final_fail),
                            "error": str(error_msg)[:500],
                        })
                        print(f"[CADENCE] Falha ao enviar para {phone}: {error_msg} (tentativa {next_dispatch.retry_count})")

                        if _consecutive_failures >= 2:
                            _pause_until = now + timedelta(minutes=20)
                            _pause_reason = "anti_block"
                            _consecutive_failures = 0
                            _persist_state(db, pause_until=_pause_until, pause_reason="anti_block",
                                           consecutive_failures=0)
                            emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_ANTI_BLOCK_PAUSE, {
                                "duration_minutes": 20,
                                "pause_until": _pause_until.isoformat(),
                                "trigger": "2 falhas Z-API consecutivas",
                            })
                            print(f"[CADENCE] ⚠ 2 falhas consecutivas — pausando disparos por 20 minutos até {_pause_until.strftime('%H:%M')}")

                except Exception as send_err:
                    next_dispatch.retry_count = (next_dispatch.retry_count or 0) + 1
                    next_dispatch.last_error_message = str(send_err)[:1000]
                    if next_dispatch.retry_count >= 3:
                        next_dispatch.status = "failed"
                        next_dispatch.error_message = str(send_err)
                    else:
                        next_dispatch.status = "pending"
                        next_dispatch.scheduled_for = now + timedelta(minutes=10)
                    db.commit()
                    emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_FAILED, {
                        "dispatch_id": next_dispatch.id,
                        "phone": phone,
                        "retry_count": int(next_dispatch.retry_count or 0),
                        "is_final": bool(next_dispatch.retry_count >= 3),
                        "error": str(send_err)[:500],
                        "exception": True,
                    })
                    print(f"[CADENCE] Erro ao enviar para {phone}: {send_err}")

                sent_this_tick = True

        # Task #221 (V2) — observabilidade de fim de tick:
        # se havia campanhas elegíveis MAS todas foram bloqueadas pelo cooldown
        # global, registra um evento dedupe `global_cooldown`. Caso contrário,
        # a transição volta para "ok" (sem evento, mas reseta o dedupe para
        # permitir emissão futura de novos estados off-OK).
        try:
            if had_candidates and all_blocked_by_cooldown and not sent_this_tick:
                _emit_engine_state_transition(db, "global_cooldown", {
                    "last_send_at": _last_send_time.isoformat() if _last_send_time else None,
                    "now": now.isoformat(),
                    "note": "todas as campanhas ativas estão dentro do cooldown global",
                })
            elif now.hour != 12:
                # Normaliza o cache para "ok" sempre que o tick chegou ao final
                # fora dos estados de exceção. Não emite evento; apenas reseta
                # o dedupe para que a próxima transição off-OK seja registrada.
                global _last_observed_state
                _last_observed_state = "ok"
        except Exception as e:
            logger.warning(f"[CADENCE-OBS] fim-de-tick falhou: {e}")

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
