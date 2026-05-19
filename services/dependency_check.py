import logging
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_startup_time = time.time()

_zapi_status_cache: dict = {"status": "unknown", "checked_at": None}

_openai_status_cache: dict = {"status": "ok", "checked_at": None, "acknowledged_by": None}

# Task #308 — cache de saúde por canal não-legado: channel_id -> health dict
_channel_health_cache: dict = {}


async def check_zapi_connectivity() -> dict:
    import httpx
    import os
    from core.config import get_settings

    try:
        settings = get_settings()
        instance_id = os.getenv("ZAPI_INSTANCE_ID", "") or settings.ZAPI_INSTANCE_ID
        token = os.getenv("ZAPI_TOKEN", "") or settings.ZAPI_TOKEN
        client_token = os.getenv("ZAPI_CLIENT_TOKEN", "") or settings.ZAPI_CLIENT_TOKEN

        if not (instance_id and token and client_token):
            return {
                "status": "disconnected",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "detail": "credentials_missing",
            }

        url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
        headers = {"Content-Type": "application/json", "Client-Token": client_token}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=5.0)
            data = response.json() if response.content else {}

            if response.status_code == 200 and data.get("connected"):
                return {
                    "status": "connected",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                return {
                    "status": "disconnected",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "detail": data.get("error", data.get("status", "not_connected")),
                }

    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": str(e),
        }


async def check_zapi_connectivity_for_channel(
    instance_id: str,
    token: str,
    client_token: Optional[str],
    global_client_token: str = "",
) -> dict:
    """
    Task #308 — Verifica conectividade Z-API com credenciais explícitas de canal.
    Usado pelo health loop para monitorar canais não-legados individualmente.
    """
    import httpx

    effective_ct = client_token or global_client_token
    if not (instance_id and token and effective_ct):
        return {
            "status": "disconnected",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": "credentials_missing",
        }

    url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
    headers = {"Content-Type": "application/json", "Client-Token": effective_ct}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=5.0)
            data = response.json() if response.content else {}
            if response.status_code == 200 and data.get("connected"):
                return {
                    "status": "connected",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                return {
                    "status": "disconnected",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "detail": data.get("error", data.get("status", "not_connected")),
                }
    except httpx.TimeoutException:
        return {
            "status": "timeout",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "status": "error",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "detail": str(e),
        }


async def _update_channel_health_cache() -> None:
    """
    Task #308 — Atualiza o cache de saúde de todos os canais Z-API ativos não-legados.

    Para cada canal:
    1. Sonda conectividade via API Z-API (status da instância).
    2. Verifica webhook_receipt_log: se houver token_rejected nos últimos 30 min,
       o status é sobrescrito para 'token_invalid' (prioridade máxima).

    Chamado dentro de _zapi_health_loop() a cada ciclo (5 min).
    """
    global _channel_health_cache
    try:
        from database.database import SessionLocal
        from database.models import ZAPIChannel, WebhookReceiptLog
        from datetime import timedelta
        import os

        db = SessionLocal()
        try:
            channels = (
                db.query(ZAPIChannel)
                .filter(
                    ZAPIChannel.is_active == True,
                    ZAPIChannel.is_legacy == False,
                )
                .all()
            )

            if not channels:
                _channel_health_cache = {}
                return

            global_ct = os.getenv("ZAPI_CLIENT_TOKEN", "")

            # Detecta rejeições de token nos últimos 30 minutos, por canal
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            rejection_rows = (
                db.query(WebhookReceiptLog)
                .filter(
                    WebhookReceiptLog.validation_result == "token_rejected",
                    WebhookReceiptLog.channel_id.isnot(None),
                    WebhookReceiptLog.created_at >= cutoff,
                )
                .all()
            )
            # Mantém apenas o timestamp mais recente por canal
            rejection_map: dict = {}
            for row in rejection_rows:
                cid = row.channel_id
                ts = row.created_at
                if cid not in rejection_map or (ts and ts > rejection_map[cid]):
                    rejection_map[cid] = ts

            # Sonda conectividade de cada canal concorrentemente
            results = await asyncio.gather(
                *[
                    check_zapi_connectivity_for_channel(
                        ch.instance_id, ch.token, ch.client_token, global_ct
                    )
                    for ch in channels
                ],
                return_exceptions=True,
            )

            new_cache: dict = {}
            for ch, result in zip(channels, results):
                if isinstance(result, Exception):
                    entry: dict = {
                        "status": "error",
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "detail": str(result),
                    }
                else:
                    entry = dict(result)

                # Token inválido tem prioridade sobre qualquer status de conectividade
                if ch.id in rejection_map:
                    entry["status"] = "token_invalid"
                    ts = rejection_map[ch.id]
                    entry["last_rejection_at"] = ts.isoformat() if ts else None

                new_cache[ch.id] = {
                    "channel_id": ch.id,
                    "label": ch.label or ch.name,
                    **entry,
                }

            _channel_health_cache = new_cache
            logger.info(
                f"[CHANNEL-HEALTH] Cache atualizado: {len(new_cache)} canal(is) — "
                + ", ".join(f"ch{cid}={v.get('status')}" for cid, v in new_cache.items())
            )
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[CHANNEL-HEALTH] Erro ao atualizar cache de canais: {e}")


def get_channel_health_cache() -> dict:
    """Task #308 — Retorna o cache de saúde por canal (dict channel_id -> health dict)."""
    return _channel_health_cache


async def _zapi_health_loop():
    global _zapi_status_cache
    try:
        while True:
            try:
                result = await check_zapi_connectivity()
                _zapi_status_cache = result
                logger.info(f"[ZAPI-HEALTH] Status canal legado: {result['status']}")
                # Task #308 — também atualiza cache de saúde por canal não-legado
                await _update_channel_health_cache()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _zapi_status_cache = {
                    "status": "error",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "detail": f"loop_error: {e}",
                }
                logger.error(f"[ZAPI-HEALTH] Erro no loop: {e}")
            await asyncio.sleep(300)
    except asyncio.CancelledError:
        logger.info("[ZAPI-HEALTH] Loop cancelado")


def get_zapi_status_cache() -> dict:
    return _zapi_status_cache


def set_openai_quota_exceeded(error_detail: str = ""):
    global _openai_status_cache
    if _openai_status_cache.get("status") == "quota_exceeded":
        return
    _openai_status_cache = {
        "status": "quota_exceeded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error_detail": error_detail[:500] if error_detail else "",
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "acknowledged_by": None,
    }
    logger.critical(f"[OPENAI-HEALTH] Status marcado como quota_exceeded: {error_detail[:200]}")


def acknowledge_openai_status(username: str = "admin"):
    global _openai_status_cache
    _openai_status_cache = {
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "acknowledged_by": username,
    }
    logger.info(f"[OPENAI-HEALTH] Status reconhecido manualmente por {username}")


def get_openai_status_cache() -> dict:
    return _openai_status_cache


async def check_openai_availability() -> dict:
    try:
        from openai import OpenAI
        from core.config import get_settings
        s = get_settings()
        if not s.OPENAI_API_KEY:
            return {"status": "not_configured", "checked_at": datetime.now(timezone.utc).isoformat()}

        client = OpenAI(api_key=s.OPENAI_API_KEY)
        import asyncio
        result = await asyncio.to_thread(lambda: client.models.list())
        return {"status": "ok", "checked_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        error_str = str(e).lower()
        if "429" in str(e) or "quota" in error_str or "rate_limit" in error_str:
            return {"status": "quota_exceeded", "checked_at": datetime.now(timezone.utc).isoformat(), "error": str(e)[:300]}
        return {"status": "error", "checked_at": datetime.now(timezone.utc).isoformat(), "error": str(e)[:300]}


async def _openai_health_loop():
    global _openai_status_cache
    try:
        while True:
            await asyncio.sleep(120)
            try:
                if _openai_status_cache.get("status") != "quota_exceeded":
                    continue

                result = await check_openai_availability()
                if result["status"] == "ok":
                    _openai_status_cache = {
                        "status": "ok",
                        "checked_at": result["checked_at"],
                        "recovered_automatically": True,
                    }
                    logger.info("[OPENAI-HEALTH] Créditos OpenAI recuperados automaticamente!")
                else:
                    _openai_status_cache["checked_at"] = result["checked_at"]
                    logger.warning(f"[OPENAI-HEALTH] Ainda com problema: {result.get('status')}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[OPENAI-HEALTH] Erro no loop: {e}")
    except asyncio.CancelledError:
        logger.info("[OPENAI-HEALTH] Loop cancelado")


def check_critical_dependencies() -> dict:
    results = {}

    try:
        import fitz
        results["pymupdf"] = {"ok": True, "version": fitz.version[0]}
    except ImportError as e:
        results["pymupdf"] = {"ok": False, "error": str(e)}
        logger.critical("[STARTUP] PyMuPDF não disponível — upload de PDF vai falhar")

    try:
        from core.config import get_settings
        settings = get_settings()
        has_key = bool(settings.OPENAI_API_KEY)
        results["openai_key"] = {"ok": has_key, "configured": has_key}
        if not has_key:
            logger.critical("[STARTUP] OPENAI_API_KEY não configurada")
    except Exception as e:
        results["openai_key"] = {"ok": False, "error": str(e)}

    try:
        import pgvector
        results["pgvector"] = {"ok": True}
    except ImportError as e:
        results["pgvector"] = {"ok": False, "error": str(e)}
        logger.critical("[STARTUP] pgvector não disponível — busca semântica vai falhar")

    try:
        import magic
        magic.from_buffer(b"test", mime=True)
        results["python_magic"] = {"ok": True, "mode": "libmagic"}
    except ImportError:
        results["python_magic"] = {"ok": True, "mode": "fallback"}
        logger.warning("[STARTUP] python-magic não disponível — validação MIME usa fallback por magic bytes")
    except Exception as e:
        results["python_magic"] = {"ok": False, "error": str(e)}

    try:
        from PIL import Image
        results["pillow"] = {"ok": True}
    except ImportError as e:
        results["pillow"] = {"ok": False, "error": str(e)}
        logger.critical("[STARTUP] Pillow não disponível — processamento de imagens vai falhar")

    failed = [k for k, v in results.items() if not v["ok"]]
    if failed:
        logger.critical(f"[STARTUP] {len(failed)} dependência(s) crítica(s) ausente(s): {failed}")
    else:
        logger.info(f"[STARTUP] Todas as {len(results)} dependências validadas com sucesso")

    return results


def get_detailed_health() -> dict:
    deps = check_critical_dependencies()

    db_status = "ok"
    try:
        from database.database import engine
        from sqlalchemy import text as sql_text
        with engine.connect() as conn:
            conn.execute(sql_text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
        logger.error(f"[HEALTH] Database check failed: {e}")

    vector_store_status = "ok"
    try:
        from services.vector_store import VectorStore
        vs = VectorStore()
        if not vs.openai_client:
            vector_store_status = "degraded: no OpenAI client"
    except Exception as e:
        vector_store_status = f"error: {str(e)}"

    zapi_configured = False
    try:
        from core.config import get_settings
        import os
        settings = get_settings()
        instance_id = os.getenv("ZAPI_INSTANCE_ID", "") or settings.ZAPI_INSTANCE_ID
        token = os.getenv("ZAPI_TOKEN", "") or settings.ZAPI_TOKEN
        client_token = os.getenv("ZAPI_CLIENT_TOKEN", "") or settings.ZAPI_CLIENT_TOKEN
        zapi_configured = bool(instance_id and token and client_token)
    except Exception:
        pass

    cached = get_zapi_status_cache()
    zapi_connectivity = cached.get("status", "unknown")

    if not zapi_configured:
        zapi_report = {"configured": False, "connectivity": "unknown"}
    else:
        zapi_report = {"configured": True, "connectivity": zapi_connectivity, "checked_at": cached.get("checked_at")}

    dep_summary = {
        "database": db_status,
        "vector_store": vector_store_status,
        "pdf_processing": "ok" if deps.get("pymupdf", {}).get("ok") else "error",
        "openai": "ok" if deps.get("openai_key", {}).get("ok") else "not_configured",
        "zapi": zapi_report,
    }

    critical_deps = ["database", "pdf_processing", "openai"]
    has_critical_failure = any(
        dep_summary.get(d, "error") not in ("ok", "not_configured")
        for d in critical_deps
    )

    scalar_statuses = {k: v for k, v in dep_summary.items() if isinstance(v, str)}
    zapi_ok = isinstance(dep_summary.get("zapi"), dict) and dep_summary["zapi"].get("configured") and dep_summary["zapi"].get("connectivity") == "connected"
    all_ok = all(v == "ok" for v in scalar_statuses.values()) and zapi_ok

    if has_critical_failure:
        status = "critical"
    elif all_ok:
        status = "ok"
    else:
        status = "degraded"

    uptime = int(time.time() - _startup_time)

    return {
        "status": status,
        "dependencies": dep_summary,
        "libraries": deps,
        "uptime_seconds": uptime,
    }
