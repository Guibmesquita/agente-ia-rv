import logging
import time

logger = logging.getLogger(__name__)

_startup_time = time.time()


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

    zapi_status = "ok"
    try:
        from core.config import get_settings
        settings = get_settings()
        if not settings.ZAPI_INSTANCE_ID or not settings.ZAPI_TOKEN:
            zapi_status = "not_configured"
    except Exception as e:
        zapi_status = f"error: {str(e)}"

    dep_summary = {
        "database": db_status,
        "vector_store": vector_store_status,
        "pdf_processing": "ok" if deps.get("pymupdf", {}).get("ok") else "error",
        "openai": "ok" if deps.get("openai_key", {}).get("ok") else "not_configured",
        "zapi": zapi_status,
    }

    critical_deps = ["database", "pdf_processing", "openai"]
    has_critical_failure = any(
        dep_summary.get(d, "error") not in ("ok", "not_configured")
        for d in critical_deps
    )

    all_ok = all(v == "ok" for v in dep_summary.values())

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
