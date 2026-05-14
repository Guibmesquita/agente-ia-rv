import asyncio
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

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

# Task #224 — controles por canal (channel_id → valor).
# None = canal legado (env vars). Chaves int = canal ZAPIChannel específico.
# O bloqueio de um canal NÃO paralisa os demais.
_last_send_time_by_channel: Dict[Optional[int], Optional[datetime]] = {}
_consecutive_failures_by_channel: Dict[Optional[int], int] = {}
_pause_until_by_channel: Dict[Optional[int], Optional[datetime]] = {}
_pause_reason_by_channel: Dict[Optional[int], Optional[str]] = {}

# Task #221 (V2) — rastreia o último estado observável emitido para
# deduplicar eventos `out_of_business_hours` / `lunch_break` /
# `global_cooldown` (só emite quando há transição). É só observabilidade;
# não influencia o comportamento do tick.
_last_observed_state: Optional[str] = None

# Task #222 — contador POR CAMPANHA de falhas Z-API consecutivas, exclusivo
# do freio de segurança do turbo (independente de `_consecutive_failures`,
# que zera após cada anti_block_pause). Reset apenas em send bem-sucedido
# da MESMA campanha. Estado em memória (volátil — sobrevive enquanto o
# processo viver). Chave: (kind, campaign_id) com kind in {"unified","legacy"}.
_turbo_failure_streak_by_campaign: Dict[tuple, int] = {}
_TURBO_FAILURE_BRAKE_THRESHOLD = 3
# Task #222 — pausa anti-bloqueio CURTA aplicada quando a falha ocorre em
# campanha turbo. Spec: 5 min (vs 20 min do modo normal).
_TURBO_ANTI_BLOCK_PAUSE_MINUTES = 5


def _get_channel_label(db, channel_id) -> str:
    """Task #224 — retorna o label legível do canal Z-API para enriquecer payloads de eventos.
    Retorna 'Canal legado' para channel_id=None ou se o canal não for encontrado."""
    if channel_id is None:
        return "Canal legado"
    try:
        from database.models import ZAPIChannel as _ZCh_Label
        ch = db.query(_ZCh_Label).filter(_ZCh_Label.id == channel_id).first()
        return ch.label if (ch and ch.label) else f"Canal #{channel_id}"
    except Exception:
        return f"Canal #{channel_id}"


def _abort_turbo_campaigns(
    db,
    reason: str,
    trigger_payload: Optional[dict] = None,
    *,
    only_unified_ids: Optional[set] = None,
    only_legacy_ids: Optional[set] = None,
):
    """Task #222 — Reverte campanhas em modo turbo para o perfil de origem
    e reagenda seus pendentes via planner padrão. Idempotente — seguro de
    chamar repetidamente.

    Quando ``only_unified_ids`` / ``only_legacy_ids`` são fornecidos, age
    APENAS sobre essas campanhas (uso por-campanha). Sem filtros, aborta
    TODAS as turbo ativas (uso global, ex: Z-API disconnected).
    """
    global _turbo_failure_streak_by_campaign
    try:
        from database.models import Campaign, CadenceCampaign
        from services.campaign_planner import (
            reschedule_unified_pending_dispatches, assign_scheduled_times,
        )
        from services.cadence_events import (
            emit_event as _obs_emit, CAMPAIGN_KIND_UNIFIED, CAMPAIGN_KIND_LEGACY,
            EVENT_TURBO_ABORTED_SAFETY,
        )

        u_q = db.query(Campaign).filter(Campaign.cadence_turbo_active.is_(True))
        if only_unified_ids is not None:
            u_q = u_q.filter(Campaign.id.in_(list(only_unified_ids)))
        l_q = db.query(CadenceCampaign).filter(CadenceCampaign.cadence_turbo_active.is_(True))
        if only_legacy_ids is not None:
            l_q = l_q.filter(CadenceCampaign.id.in_(list(only_legacy_ids)))
        unified = u_q.all() if (only_unified_ids is None or only_unified_ids) else []
        legacy = l_q.all() if (only_legacy_ids is None or only_legacy_ids) else []

        if not unified and not legacy:
            return

        for c in unified:
            origin = c.cadence_turbo_origin_profile or "conservador"
            c.cadence_profile = origin
            c.cadence_turbo_active = False
            c.cadence_turbo_origin_profile = None
            # Task #222 — limpa override persistido junto com a flag turbo.
            c.cadence_turbo_override_business_hours = False
        for c in legacy:
            origin = c.cadence_turbo_origin_profile or "conservador"
            c.cadence_profile = origin
            c.cadence_turbo_active = False
            c.cadence_turbo_origin_profile = None
            c.cadence_turbo_override_business_hours = False
        db.commit()

        # Reagenda pendentes com perfil restaurado
        for c in unified:
            try:
                reschedule_unified_pending_dispatches(c.id, db)
            except Exception as e:
                logger.warning(f"[CADENCE-TURBO] reagendar unificada {c.id} falhou: {e}")
        for c in legacy:
            try:
                assign_scheduled_times(c.id, db, only_pending=True)
            except Exception as e:
                logger.warning(f"[CADENCE-TURBO] reagendar legada {c.id} falhou: {e}")

        # Emite evento auditável por campanha afetada
        for c in unified:
            _obs_emit(db, CAMPAIGN_KIND_UNIFIED, c.id, EVENT_TURBO_ABORTED_SAFETY, {
                "reason": reason,
                "restored_profile": c.cadence_profile,
                **(trigger_payload or {}),
            })
        for c in legacy:
            _obs_emit(db, CAMPAIGN_KIND_LEGACY, c.id, EVENT_TURBO_ABORTED_SAFETY, {
                "reason": reason,
                "restored_profile": c.cadence_profile,
                **(trigger_payload or {}),
            })

        # Limpa apenas as entradas das campanhas afetadas no streak.
        for c in unified:
            _turbo_failure_streak_by_campaign.pop(("unified", c.id), None)
        for c in legacy:
            _turbo_failure_streak_by_campaign.pop(("legacy", c.id), None)
        print(
            f"[CADENCE-TURBO] ⚠ Freio de segurança disparado ({reason}) — "
            f"turbo abortado em {len(unified)} unificadas e {len(legacy)} legadas."
        )
    except Exception as e:
        logger.warning(f"[CADENCE-TURBO] _abort_turbo_campaigns falhou: {e}")


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

# Dedupe persistente em memória de daily_limit_reached: {(kind, campaign_id): date}.
# Evita escrever um evento por tick (a cada 30s) enquanto a campanha ficar
# travada no limite diário — emitimos apenas uma vez por dia por campanha.
# Reseta automaticamente em qualquer dia novo (chave de data).
_daily_limit_emitted_day: Dict[Any, Any] = {}

# Task #224 — contadores diários por canal para isolamento de quota.
# Chave: (campaign_kind, campaign_id, channel_id_or_None) → int enviados hoje.
# Reseta automaticamente na virada do dia BRT sem necessidade de migration.
# Efeito: canal A atingindo seu limite não bloqueia canal B da mesma campanha.
_channel_daily_sent: Dict[Tuple, int] = {}
_channel_daily_reset_date: Optional[date] = None


def _should_emit_daily_limit(kind: str, campaign_id: int, today_date) -> bool:
    """True se ainda não emitimos o evento daily_limit_reached para essa
    campanha no dia atual. Idempotente em memória (sobrevive entre ticks)."""
    key = (kind, campaign_id)
    last = _daily_limit_emitted_day.get(key)
    if last == today_date:
        return False
    _daily_limit_emitted_day[key] = today_date
    return True


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
    global _turbo_failure_streak_by_campaign  # Task #222 — contador por-campanha

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
    # Task #222 — exceção: se houver QUALQUER campanha turbo com override
    # de janela comercial ATIVO + dispatches pendentes, o tick prossegue
    # (apenas as campanhas com override conseguem enviar fora de horário;
    # as demais ficam filtradas dentro do loop). Caso contrário, mantém o
    # early-return histórico.
    _is_out_of_hours = (
        now.weekday() >= 5
        or now < now.replace(hour=9, minute=0, second=0, microsecond=0)
        or now >= now.replace(hour=18, minute=0, second=0, microsecond=0)
    )
    if _is_out_of_hours:
        # Verifica em sessão curta se algum override turbo está pedindo passagem.
        _has_override_pending = False
        try:
            _obs_db = SessionLocal()
            try:
                from database.models import (
                    Campaign as _C, CadenceCampaign as _CC,
                    CampaignDispatch as _CD, CadenceCampaignContact as _CCC,
                )
                _u_override_ids = [
                    cid for (cid,) in _obs_db.query(_C.id).filter(
                        _C.cadence_turbo_active.is_(True),
                        _C.cadence_turbo_override_business_hours.is_(True),
                        _C.status == "firing_cadence",
                    ).all()
                ]
                _l_override_ids = [
                    cid for (cid,) in _obs_db.query(_CC.id).filter(
                        _CC.cadence_turbo_active.is_(True),
                        _CC.cadence_turbo_override_business_hours.is_(True),
                        _CC.status == "firing",
                    ).all()
                ]
                if _u_override_ids:
                    _has_override_pending = (
                        _obs_db.query(_CD.id).filter(
                            _CD.campaign_id.in_(_u_override_ids),
                            _CD.status == "pending",
                        ).first() is not None
                    )
                if not _has_override_pending and _l_override_ids:
                    _has_override_pending = (
                        _obs_db.query(_CCC.id).filter(
                            _CCC.campaign_id.in_(_l_override_ids),
                            _CCC.status == "pending",
                        ).first() is not None
                    )
                _persist_state(_obs_db, last_tick_at=now)
                if not _has_override_pending:
                    _emit_engine_state_transition(_obs_db, "out_of_business_hours", {
                        "weekday": now.weekday(),
                        "hour": now.hour,
                        "now": now.isoformat(),
                    })
            finally:
                _obs_db.close()
        except Exception as e:
            logger.warning(f"[CADENCE-OBS] obs session falhou: {e}")
        if not _has_override_pending:
            return
        # Caso contrário, prossegue — o gate por-campanha abaixo filtra
        # campanhas sem override.

    db = SessionLocal()
    try:
        # Hidrata do banco e registra tick. Estado persistente sobrevive a reinício.
        _hydrate_from_db(db)
        _persist_state(db, last_tick_at=now)

        # Task #222 — freio de segurança do turbo (POR CAMPANHA): aborta
        # apenas as campanhas turbo cujo streak local tenha estourado o
        # threshold. Idempotente; chave em RAM zera junto com a campanha.
        unified_offenders = {
            cid for (kind, cid), streak in _turbo_failure_streak_by_campaign.items()
            if kind == "unified" and streak >= _TURBO_FAILURE_BRAKE_THRESHOLD
        }
        legacy_offenders = {
            cid for (kind, cid), streak in _turbo_failure_streak_by_campaign.items()
            if kind == "legacy" and streak >= _TURBO_FAILURE_BRAKE_THRESHOLD
        }
        if unified_offenders or legacy_offenders:
            _abort_turbo_campaigns(
                db,
                "consecutive_zapi_failures",
                {
                    "threshold": _TURBO_FAILURE_BRAKE_THRESHOLD,
                    "scope": "per_campaign",
                },
                only_unified_ids=unified_offenders or None,
                only_legacy_ids=legacy_offenders or None,
            )

        # Task #222 — abort GLOBAL adicional: Z-API desconectado/erro força
        # o turbo a recuar para o perfil de origem em TODAS as campanhas.
        # Mantém o motor rodando (envios normais já tratam falhas isoladas).
        try:
            from services.dependency_check import get_zapi_status_cache
            zapi_health = (get_zapi_status_cache() or {}).get("status")
            if zapi_health in ("disconnected", "error"):
                _abort_turbo_campaigns(
                    db,
                    "zapi_health_unhealthy",
                    {"zapi_status": zapi_health, "scope": "global"},
                )
        except Exception as _e:
            logger.warning(f"[CADENCE-TURBO] verificação Z-API health falhou: {_e}")

        if _pause_until and now < _pause_until:
            # Task #224 — não retorna globalmente. O controle de pausa
            # anti-bloqueio é agora por canal (_pause_until_by_channel).
            # Emite o evento apenas para observabilidade do engine state.
            _emit_engine_state_transition(db, "anti_block_pause_active", {
                "pause_until": _pause_until.isoformat(),
                "pause_reason": _pause_reason,
            })
            # Sem return: outros canais seguem operando normalmente.

        # Pausa de almoço (12:00-13:00 BRT): estado APENAS observado.
        # Não estava no comportamento original do motor (`git show` confirma
        # que cadence_controller.py nunca teve gate em hour==12), então a
        # observabilidade NÃO altera o tick — apenas emite o evento.
        if now.hour == 12:
            _emit_engine_state_transition(db, "lunch_break", {
                "now": now.isoformat(),
                "note": "informativo — motor segue ativo",
            })

        sent_this_tick = False
        # Task #221 (V2) — rastreia se TODAS as candidatas foram bloqueadas
        # apenas pelo cooldown (sem outros impedimentos). Se sim, emitimos
        # um único `global_cooldown` no fim do tick.
        had_candidates = False
        all_blocked_by_cooldown = True

        today_date = now.date()

        # Task #224 — reset diário dos contadores por canal na virada do dia.
        # Deve ficar APÓS today_date ser definido para evitar UnboundLocalError.
        global _channel_daily_sent, _channel_daily_reset_date
        if _channel_daily_reset_date != today_date:
            _channel_daily_sent.clear()
            _channel_daily_reset_date = today_date

        from services.cadence_profiles import get_profile
        active_legacy = (
            db.query(CadenceCampaign)
            .filter(CadenceCampaign.status == "firing")
            .all()
        )

        for campaign in active_legacy:
            if sent_this_tick:
                break

            # Task #222 — fora da janela 09-18h, só campanhas turbo com
            # override explícito podem disparar. Demais permanecem no
            # comportamento histórico (skip silencioso).
            if _is_out_of_hours and not (
                bool(getattr(campaign, "cadence_turbo_active", False))
                and bool(getattr(campaign, "cadence_turbo_override_business_hours", False))
            ):
                continue

            # Task #224 — cooldown avaliado por canal (ver had_candidates /
            # all_blocked_by_cooldown abaixo, após fetch do next_contact).
            campaign_profile = get_profile(getattr(campaign, "cadence_profile", None))
            cooldown = int(campaign_profile["cooldown_seconds"])

            daily_log = (
                db.query(CampaignDailyLog)
                .filter(
                    CampaignDailyLog.campaign_id == campaign.id,
                    CampaignDailyLog.log_date == datetime.combine(today_date, time.min, tzinfo=tz)
                )
                .first()
            )

            # Task #222 — em modo turbo, o cap diário é SEMPRE o do perfil
            # turbo (150/dia), ignorando `campaign.daily_limit` salvo.
            if bool(getattr(campaign, "cadence_turbo_active", False)):
                effective_daily_limit = int(campaign_profile["daily_limit"])
            else:
                effective_daily_limit = campaign.daily_limit or int(campaign_profile["daily_limit"])
            # Task #224 — construir conjunto de canais bloqueados (cooldown + pausa +
            # cota diária por canal) ANTES da query, para que cada canal seja
            # bloqueado de forma independente sem afetar os demais.
            _leg_blocked: set = set()
            for _ch_id, _last in _last_send_time_by_channel.items():
                if _last and (now - _last).total_seconds() < cooldown:
                    _leg_blocked.add(_ch_id)
            for _ch_id, _pu in _pause_until_by_channel.items():
                if _pu and now < _pu:
                    _leg_blocked.add(_ch_id)
            # Bloqueia apenas os canais que atingiram sua cota diária (Task #224).
            # Canal A não bloqueia Canal B — cada um tem contador independente.
            for (_dl_kind, _dl_cid, _dl_ch), _dl_cnt in list(_channel_daily_sent.items()):
                if (
                    _dl_kind == CAMPAIGN_KIND_LEGACY
                    and _dl_cid == campaign.id
                    and _dl_cnt >= effective_daily_limit
                ):
                    _leg_blocked.add(_dl_ch)

            # Observabilidade: emite daily_limit_reached se o log global de campanha
            # indica que o total global atingiu o limite. Não bloqueia o loop —
            # o bloqueio por-canal via _leg_blocked já isola os canais corretos.
            if daily_log and daily_log.sent_count >= effective_daily_limit:
                if _should_emit_daily_limit(CAMPAIGN_KIND_LEGACY, campaign.id, today_date):
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DAILY_LIMIT_REACHED, {
                        "limit": effective_daily_limit,
                        "sent_today": int(daily_log.sent_count or 0),
                        "profile": campaign_profile.get("label"),
                    })

            _cq = (
                db.query(CadenceCampaignContact)
                .filter(
                    CadenceCampaignContact.campaign_id == campaign.id,
                    CadenceCampaignContact.status == "pending",
                    CadenceCampaignContact.scheduled_for <= now,
                )
            )
            if _leg_blocked:
                from sqlalchemy import or_ as _or_leg
                _none_blk_l = None in _leg_blocked
                _int_blk_l = {c for c in _leg_blocked if c is not None}
                if _none_blk_l and _int_blk_l:
                    _cq = _cq.filter(
                        CadenceCampaignContact.channel_id.isnot(None),
                        ~CadenceCampaignContact.channel_id.in_(_int_blk_l),
                    )
                elif _none_blk_l:
                    _cq = _cq.filter(CadenceCampaignContact.channel_id.isnot(None))
                else:
                    _cq = _cq.filter(
                        _or_leg(
                            CadenceCampaignContact.channel_id.is_(None),
                            ~CadenceCampaignContact.channel_id.in_(_int_blk_l),
                        )
                    )
            next_contact = _cq.order_by(CadenceCampaignContact.scheduled_for.asc()).first()

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
                    # Task #222 — captura flag turbo ANTES de limpar.
                    _was_turbo = bool(getattr(campaign, "cadence_turbo_active", False))
                    campaign.cadence_turbo_active = False
                    campaign.cadence_turbo_origin_profile = None
                    campaign.cadence_turbo_override_business_hours = False
                    db.commit()
                    _turbo_failure_streak_by_campaign.pop(("legacy", campaign.id), None)
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_CAMPAIGN_DONE, {
                        "ended_at": now.isoformat(),
                        "via_turbo": _was_turbo,
                    })
                    print(f"[CADENCE] Campanha legada '{campaign.name}' (id={campaign.id}) concluída!")
                continue

            # Task #224 — o channel_id já foi filtrado pela query acima.
            channel_id = getattr(next_contact, "channel_id", None)
            had_candidates = True
            all_blocked_by_cooldown = False  # chegou aqui, ao menos um canal disponível

            # Verifica se o canal explícito está ativo ANTES de obter o cliente
            # (Task #224: inativo → falha determinística, não "não configurada").
            if channel_id is not None:
                from database.models import ZAPIChannel as _ZCh_L
                _ch_row_l = db.query(_ZCh_L).filter(
                    _ZCh_L.id == channel_id, _ZCh_L.is_active.is_(False)
                ).first()
                if _ch_row_l:
                    next_contact.status = "failed"
                    next_contact.last_error_message = "Canal desativado"
                    db.commit()
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_FAILED, {
                        "phone": next_contact.phone,
                        "contact_id": next_contact.id,
                        "channel_id": channel_id,
                        "channel_label": _get_channel_label(db, channel_id),
                        "is_final": True,
                        "error": "Canal desativado",
                    })
                    sent_this_tick = True
                    continue

            # Cliente Z-API específico do canal.
            from services.whatsapp_client import get_zapi_client_for_channel as _gzc_leg
            try:
                zapi = _gzc_leg(channel_id, db)
            except Exception:
                zapi = ZAPIClient()
            if not zapi.is_configured():
                print(f"[CADENCE] Z-API canal {channel_id} não configurada — campanha '{campaign.name}' pulada")
                continue  # Task #224: não bloqueia outros canais

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
                    _consecutive_failures_by_channel[channel_id] = 0
                    # Task #222 — reset do streak APENAS desta campanha turbo.
                    _turbo_failure_streak_by_campaign.pop(("legacy", campaign.id), None)

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
                    _last_send_time_by_channel[channel_id] = now
                    # Task #224 — incrementa contador diário por canal (isolamento de cota).
                    _cds_key_leg = (CAMPAIGN_KIND_LEGACY, campaign.id, channel_id)
                    _channel_daily_sent[_cds_key_leg] = _channel_daily_sent.get(_cds_key_leg, 0) + 1
                    db.commit()
                    _persist_state(db, last_send_at=now, consecutive_failures=0)
                    emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_SENT, {
                        "phone": next_contact.phone,
                        "contact_id": next_contact.id,
                        "channel_id": channel_id,
                        "channel_label": _get_channel_label(db, channel_id),
                        "profile": campaign_profile.get("label"),
                    })
                    print(f"[CADENCE] Enviado para {next_contact.phone} (legada '{campaign.name}', canal={channel_id}, perfil={campaign_profile.get('label', '?')})")
                else:
                    next_contact.retry_count += 1
                    error_msg = result.get("error", "desconhecido")
                    next_contact.last_error_message = str(error_msg)[:1000]
                    _consecutive_failures += 1
                    ch_failures = _consecutive_failures_by_channel.get(channel_id, 0) + 1
                    _consecutive_failures_by_channel[channel_id] = ch_failures
                    # Task #222 — incrementa streak POR CAMPANHA somente se turbo.
                    _is_turbo_now = bool(getattr(campaign, "cadence_turbo_active", False))
                    if _is_turbo_now:
                        _key = ("legacy", campaign.id)
                        _turbo_failure_streak_by_campaign[_key] = (
                            _turbo_failure_streak_by_campaign.get(_key, 0) + 1
                        )

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
                        "channel_id": channel_id,
                        "channel_label": _get_channel_label(db, channel_id),
                        "retry_count": int(next_contact.retry_count or 0),
                        "is_final": bool(is_final_fail),
                        "error": str(error_msg)[:500],
                    })
                    print(f"[CADENCE] Falha para {next_contact.phone}: {error_msg} (tentativa {next_contact.retry_count}, canal={channel_id})")

                    # Pausa anti-bloqueio por canal (Task #224).
                    if ch_failures >= 2:
                        _pause_minutes = (
                            _TURBO_ANTI_BLOCK_PAUSE_MINUTES if _is_turbo_now else 20
                        )
                        _pause_until_by_channel[channel_id] = now + timedelta(minutes=_pause_minutes)
                        _pause_reason_by_channel[channel_id] = "anti_block"
                        _consecutive_failures_by_channel[channel_id] = 0
                        # Mantém global para observabilidade (engine state).
                        _pause_until = now + timedelta(minutes=_pause_minutes)
                        _pause_reason = "anti_block"
                        _consecutive_failures = 0
                        _persist_state(db, pause_until=_pause_until, pause_reason="anti_block",
                                       consecutive_failures=0)
                        emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_ANTI_BLOCK_PAUSE, {
                            "duration_minutes": _pause_minutes,
                            "pause_until": _pause_until_by_channel[channel_id].isoformat(),
                            "trigger": "2 falhas Z-API consecutivas",
                            "channel_id": channel_id,
                            "turbo": _is_turbo_now,
                        })
                        print(f"[CADENCE] ⚠ 2 falhas canal {channel_id} — pausando {_pause_minutes}min")

            except Exception as send_err:
                next_contact.retry_count += 1
                next_contact.last_error_message = str(send_err)[:1000]
                if next_contact.retry_count >= 3:
                    next_contact.status = "failed"
                db.commit()
                emit_event(db, CAMPAIGN_KIND_LEGACY, campaign.id, EVENT_DISPATCH_FAILED, {
                    "phone": next_contact.phone,
                    "contact_id": next_contact.id,
                    "channel_id": channel_id,
                    "channel_label": _get_channel_label(db, channel_id),
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

                # Task #222 — gate por-campanha: fora de horário, só turbo
                # com override explícito é despachada.
                if _is_out_of_hours and not (
                    bool(getattr(campaign, "cadence_turbo_active", False))
                    and bool(getattr(campaign, "cadence_turbo_override_business_hours", False))
                ):
                    continue

                # Task #224 — cooldown e pausa avaliados por canal.
                campaign_profile = get_profile(getattr(campaign, "cadence_profile", None))
                cooldown = int(campaign_profile["cooldown_seconds"])

                # Task #222 — em turbo, prevalece o cap do perfil (150/dia).
                if bool(getattr(campaign, "cadence_turbo_active", False)):
                    effective_daily_limit = int(campaign_profile["daily_limit"])
                else:
                    effective_daily_limit = campaign.daily_limit or int(campaign_profile["daily_limit"])

                # Task #224 — construir conjunto de canais bloqueados ANTES de
                # selecionar/clammar o dispatch (cooldown + pausa + cota diária).
                # Cada canal tem contador independente: canal A não bloqueia canal B.
                _uni_blocked: set = set()
                for _ch_id, _last in _last_send_time_by_channel.items():
                    if _last and (now - _last).total_seconds() < cooldown:
                        _uni_blocked.add(_ch_id)
                for _ch_id, _pu in _pause_until_by_channel.items():
                    if _pu and now < _pu:
                        _uni_blocked.add(_ch_id)
                # Bloqueia apenas os canais que atingiram a cota diária (Task #224).
                for (_dl_kind, _dl_cid, _dl_ch), _dl_cnt in list(_channel_daily_sent.items()):
                    if (
                        _dl_kind == CAMPAIGN_KIND_UNIFIED
                        and _dl_cid == campaign.id
                        and _dl_cnt >= effective_daily_limit
                    ):
                        _uni_blocked.add(_dl_ch)

                # Observabilidade global: emite daily_limit_reached se todos os
                # dispatches enviados hoje (todos canais) atingiram o limite.
                # Não bloqueia o loop — o bloqueio é via _uni_blocked por canal.
                today_sent = (
                    db.query(CampaignDispatch)
                    .filter(
                        CampaignDispatch.campaign_id == campaign.id,
                        CampaignDispatch.status.in_(["sent", "responded"]),
                        CampaignDispatch.sent_at >= datetime.combine(today_date, time.min, tzinfo=tz),
                    )
                    .count()
                )
                if today_sent >= effective_daily_limit:
                    if _should_emit_daily_limit(CAMPAIGN_KIND_UNIFIED, campaign.id, today_date):
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DAILY_LIMIT_REACHED, {
                            "limit": effective_daily_limit,
                            "sent_today": int(today_sent),
                            "profile": campaign_profile.get("label"),
                        })
                    # Sem continue — verificação por canal via _uni_blocked já isola.

                # Construir cláusula SQL de exclusão de canais (sem user-input;
                # apenas inteiros internos → seguro para interpolação).
                _none_blk_u = None in _uni_blocked
                _int_blk_u = {c for c in _uni_blocked if c is not None}
                if _none_blk_u and _int_blk_u:
                    _ch_cond_u = (
                        " AND channel_id IS NOT NULL"
                        " AND channel_id NOT IN ({})".format(",".join(str(c) for c in _int_blk_u))
                    )
                elif _none_blk_u:
                    _ch_cond_u = " AND channel_id IS NOT NULL"
                elif _int_blk_u:
                    _ch_cond_u = " AND (channel_id IS NULL OR channel_id NOT IN ({}))".format(
                        ",".join(str(c) for c in _int_blk_u)
                    )
                else:
                    _ch_cond_u = ""

                from sqlalchemy import text as sql_text

                # Verifica se há candidatos para had_candidates.
                peek_row = db.execute(
                    sql_text(
                        "SELECT id, channel_id FROM campaign_dispatches "
                        "WHERE campaign_id = :cid AND status = 'pending' "
                        "AND scheduled_for <= :now "
                        "ORDER BY scheduled_for ASC LIMIT 1"
                    ),
                    {"cid": campaign.id, "now": now},
                ).fetchone()
                if peek_row:
                    had_candidates = True
                    all_blocked_by_cooldown = False  # ao menos um canal disponível

                # Claim atômico do próximo dispatch elegível (excluindo canais bloqueados).
                claim_result = db.execute(
                    sql_text(
                        "UPDATE campaign_dispatches SET status = 'processing' "
                        "WHERE id = ("
                        "  SELECT id FROM campaign_dispatches "
                        "  WHERE campaign_id = :cid AND status = 'pending' AND scheduled_for <= :now"
                        + _ch_cond_u +
                        "  ORDER BY scheduled_for ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
                        ") RETURNING id"
                    ),
                    {"cid": campaign.id, "now": now},
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
                        # Task #222 — captura flag turbo ANTES de limpar para
                        # marcar via_turbo no evento de conclusão.
                        _was_turbo_u = bool(getattr(campaign, "cadence_turbo_active", False))
                        campaign.cadence_turbo_active = False
                        campaign.cadence_turbo_origin_profile = None
                        campaign.cadence_turbo_override_business_hours = False
                        _turbo_failure_streak_by_campaign.pop(("unified", campaign.id), None)
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
                            "via_turbo": _was_turbo_u,
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

                # Task #224 — cliente Z-API por canal do dispatch.
                dispatch_channel_id = getattr(next_dispatch, "channel_id", None)

                # Verifica se o canal explícito está ativo.
                if dispatch_channel_id is not None:
                    from database.models import ZAPIChannel as _ZCh_U
                    _ch_row_u = db.query(_ZCh_U).filter(
                        _ZCh_U.id == dispatch_channel_id, _ZCh_U.is_active.is_(False)
                    ).first()
                    if _ch_row_u:
                        next_dispatch.status = "failed"
                        next_dispatch.error_message = "Canal desativado"
                        next_dispatch.last_error_message = "Canal desativado"
                        db.commit()
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_FAILED, {
                            "dispatch_id": next_dispatch.id,
                            "channel_id": dispatch_channel_id,
                            "channel_label": _get_channel_label(db, dispatch_channel_id),
                            "is_final": True,
                            "error": "Canal desativado",
                        })
                        sent_this_tick = True
                        continue

                from services.whatsapp_client import get_zapi_client_for_channel as _gzc_u
                try:
                    zapi = _gzc_u(dispatch_channel_id, db)
                except Exception:
                    zapi = ZAPIClient()
                if not zapi.is_configured():
                    next_dispatch.status = "pending"
                    next_dispatch.scheduled_for = now + timedelta(minutes=5)
                    db.commit()
                    print(f"[CADENCE] Z-API canal {dispatch_channel_id} não configurada, dispatch devolvido para pending")
                    continue  # Task #224: não bloqueia outros canais

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
                                "channel_id": dispatch_channel_id,
                                "channel_label": _get_channel_label(db, dispatch_channel_id),
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
                        _consecutive_failures_by_channel[dispatch_channel_id] = 0
                        # Task #222 — reset do streak APENAS desta campanha turbo.
                        _turbo_failure_streak_by_campaign.pop(("unified", campaign.id), None)
                        _last_send_time = now
                        _last_send_time_by_channel[dispatch_channel_id] = now
                        # Task #224 — incrementa contador diário por canal (isolamento de cota).
                        _cds_key_uni = (CAMPAIGN_KIND_UNIFIED, campaign.id, dispatch_channel_id)
                        _channel_daily_sent[_cds_key_uni] = _channel_daily_sent.get(_cds_key_uni, 0) + 1

                        _persist_unified_campaign_message(db, phone, message, campaign.name)

                        db.commit()
                        _persist_state(db, last_send_at=now, consecutive_failures=0)
                        emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_DISPATCH_SENT, {
                            "dispatch_id": next_dispatch.id,
                            "phone": phone,
                            "channel_id": dispatch_channel_id,
                            "channel_label": _get_channel_label(db, dispatch_channel_id),
                            "profile": campaign_profile.get("label"),
                        })
                        print(f"[CADENCE] Enviado para {phone} (unificada '{campaign.name}', canal={dispatch_channel_id}, perfil={campaign_profile.get('label', '?')})")
                    else:
                        next_dispatch.retry_count = (next_dispatch.retry_count or 0) + 1
                        error_msg = result.get("error", "desconhecido")
                        next_dispatch.last_error_message = str(error_msg)[:1000]
                        _consecutive_failures += 1
                        ch_failures_u = _consecutive_failures_by_channel.get(dispatch_channel_id, 0) + 1
                        _consecutive_failures_by_channel[dispatch_channel_id] = ch_failures_u
                        # Task #222 — streak por-campanha (somente turbo).
                        _is_turbo_now_u = bool(getattr(campaign, "cadence_turbo_active", False))
                        if _is_turbo_now_u:
                            _key_u = ("unified", campaign.id)
                            _turbo_failure_streak_by_campaign[_key_u] = (
                                _turbo_failure_streak_by_campaign.get(_key_u, 0) + 1
                            )

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
                            "channel_id": dispatch_channel_id,
                            "channel_label": _get_channel_label(db, dispatch_channel_id),
                            "retry_count": int(next_dispatch.retry_count or 0),
                            "is_final": bool(is_final_fail),
                            "error": str(error_msg)[:500],
                        })
                        print(f"[CADENCE] Falha para {phone}: {error_msg} (tentativa {next_dispatch.retry_count}, canal={dispatch_channel_id})")

                        # Pausa anti-bloqueio por canal (Task #224).
                        if ch_failures_u >= 2:
                            _pause_minutes_u = (
                                _TURBO_ANTI_BLOCK_PAUSE_MINUTES if _is_turbo_now_u else 20
                            )
                            _pause_until_by_channel[dispatch_channel_id] = now + timedelta(minutes=_pause_minutes_u)
                            _pause_reason_by_channel[dispatch_channel_id] = "anti_block"
                            _consecutive_failures_by_channel[dispatch_channel_id] = 0
                            # Mantém global para observabilidade.
                            _pause_until = now + timedelta(minutes=_pause_minutes_u)
                            _pause_reason = "anti_block"
                            _consecutive_failures = 0
                            _persist_state(db, pause_until=_pause_until, pause_reason="anti_block",
                                           consecutive_failures=0)
                            emit_event(db, CAMPAIGN_KIND_UNIFIED, campaign.id, EVENT_ANTI_BLOCK_PAUSE, {
                                "duration_minutes": _pause_minutes_u,
                                "turbo": _is_turbo_now_u,
                                "pause_until": _pause_until_by_channel[dispatch_channel_id].isoformat(),
                                "trigger": "2 falhas Z-API consecutivas",
                                "channel_id": dispatch_channel_id,
                            })
                            print(f"[CADENCE] ⚠ 2 falhas canal {dispatch_channel_id} — pausando {_pause_minutes_u}min")

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
                        "channel_id": dispatch_channel_id,
                        "channel_label": _get_channel_label(db, dispatch_channel_id),
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
