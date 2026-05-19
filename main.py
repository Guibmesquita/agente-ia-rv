"""
Ponto de entrada da aplicacao FastAPI.
Configura rotas, middleware e inicializacao do banco de dados.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
import asyncio
import os
from typing import Optional

from core.config import is_production


def _register_routers():
    """Importa e registra todos os routers da aplicação. Executado de forma síncrona antes do yield."""
    from api.endpoints import (
        auth, users, tickets, whatsapp_webhook, integrations, agent_config,
        assessores, campaigns, knowledge, agent_test, conversations, products,
        files, insights, search, trusted_sources, costs, health, committee, admin
    )
    from api.endpoints import recommendations as recommendations_mod
    from api.endpoints import portfolios as portfolios_mod
    from api.endpoints import cadence_campaigns as cadence_campaigns_mod

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(tickets.router)
    app.include_router(whatsapp_webhook.router)
    app.include_router(whatsapp_webhook.multichannel_router)
    app.include_router(integrations.router)
    app.include_router(agent_config.router)
    app.include_router(assessores.router)
    app.include_router(assessores.custom_fields_router)
    app.include_router(assessores.upload_router)
    app.include_router(campaigns.router)
    app.include_router(campaigns.cadence_router)
    app.include_router(knowledge.router)
    app.include_router(agent_test.router)
    app.include_router(conversations.router)
    app.include_router(products.router)
    app.include_router(files.router)
    app.include_router(insights.router)
    app.include_router(search.router)
    app.include_router(trusted_sources.router)
    app.include_router(costs.router)
    app.include_router(health.router)
    app.include_router(committee.router)
    app.include_router(admin.router)
    app.include_router(recommendations_mod.router)
    app.include_router(recommendations_mod.materials_router)
    app.include_router(recommendations_mod.page_router)
    app.include_router(portfolios_mod.router)
    app.include_router(cadence_campaigns_mod.router)
    print("[INIT] Routers registrados com sucesso.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação.
    Routers são registrados de forma síncrona antes do yield para garantir que todas
    as rotas estejam disponíveis desde o primeiro request.
    Inicialização pesada (banco, upload queue) roda em background.
    """
    # Registrar routers antes do yield — garante disponibilidade imediata de todas as rotas
    # Executado diretamente (sem to_thread) pois app.include_router deve rodar no event loop principal
    try:
        _register_routers()
    except Exception as e:
        print(f"[INIT] Erro ao registrar routers: {e}")
        import traceback
        traceback.print_exc()

    background_tasks = []

    init_task = asyncio.create_task(run_init_background())
    background_tasks.append(init_task)
    
    reindex_task = asyncio.create_task(check_and_reindex_embeddings())
    background_tasks.append(reindex_task)
    
    confirmation_task = asyncio.create_task(confirmation_timeout_scheduler())
    background_tasks.append(confirmation_task)
    
    token_cleanup_task = asyncio.create_task(revoked_tokens_cleanup_scheduler())
    background_tasks.append(token_cleanup_task)

    from services.dependency_check import _zapi_health_loop, _openai_health_loop
    zapi_health_task = asyncio.create_task(_zapi_health_loop())
    background_tasks.append(zapi_health_task)

    openai_health_task = asyncio.create_task(_openai_health_loop())
    background_tasks.append(openai_health_task)

    from services.cadence_controller import cadence_loop
    cadence_task = asyncio.create_task(cadence_loop())
    background_tasks.append(cadence_task)

    # Task #309 — Loop de revalidação periódica de webhooks (diário + startup após 30s).
    webhook_revalidation_task = asyncio.create_task(_webhook_revalidation_loop())
    background_tasks.append(webhook_revalidation_task)

    yield
    
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def run_init_background():
    """Inicialização pesada em background: dependency check, tabelas, upload queue."""
    try:
        from services.dependency_check import check_critical_dependencies
        check_critical_dependencies()
    except Exception as e:
        print(f"[INIT] dependency check warning: {e}")

    try:
        await asyncio.to_thread(_sync_init_database)
        print("[INIT] Banco de dados inicializado com sucesso.")
    except Exception as e:
        print(f"[INIT] Erro na inicialização do banco: {e}")
        import traceback
        traceback.print_exc()

    try:
        from services.upload_queue import UploadQueue
        upload_queue_instance = UploadQueue.get_instance()
        upload_queue_instance.initialize()
    except Exception as e:
        print(f"[INIT] Erro no upload queue: {e}")

    try:
        _resume_interrupted_uploads()
    except Exception as e:
        print(f"[INIT] Erro ao retomar uploads: {e}")

    try:
        _cleanup_stale_processing_jobs()
    except Exception as e:
        print(f"[INIT] Erro no cleanup de jobs travados: {e}")

    try:
        _cleanup_old_webhook_logs()
    except Exception as e:
        print(f"[INIT] Erro no cleanup de webhook_receipt_log: {e}")

    try:
        await _auto_register_webhooks_startup()
    except Exception as e:
        print(f"[INIT] Erro no re-registro automático de webhooks: {e}")


async def _auto_register_webhooks_startup():
    """
    Task #293 — Re-registra webhooks de canais ativos não-legados com
    webhook_auto_registered=False usando WEBHOOK_BASE_URL ou APP_BASE_URL.
    Idempotente e não-bloqueante: falhas por canal são logadas mas não interrompem o startup.
    Só executa quando há base URL configurada via env vars (sem request disponível).
    """
    import os
    from database.database import SessionLocal
    from database.models import ZAPIChannel
    from services.whatsapp_client import ZAPIClient

    # Task #296 — usar RAILWAY_STATIC_URL como fallback adicional.
    # Railway injeta RAILWAY_STATIC_URL automaticamente; APP_BASE_URL e WEBHOOK_BASE_URL
    # são explícitos mas raramente configurados em Railway sem env vars manuais.
    webhook_base = (
        os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
        or os.getenv("APP_BASE_URL", "").rstrip("/")
        or os.getenv("RAILWAY_STATIC_URL", "").rstrip("/")
    )

    db = SessionLocal()
    try:
        channels = (
            db.query(ZAPIChannel)
            .filter(
                ZAPIChannel.is_legacy.is_(False),
                ZAPIChannel.is_active.is_(True),
                ZAPIChannel.webhook_auto_registered.is_(False),
            )
            .all()
        )

        # Task #304 — helper definido antes de qualquer uso para evitar UnboundLocalError
        # quando _persist_startup_log é chamado no bloco "sem base URL" logo abaixo.
        def _persist_startup_log(channel_id: Optional[int], validation: str, detail: Optional[str] = None):
            """Persiste tentativa de registro de startup no webhook_receipt_log."""
            try:
                from database.models import WebhookReceiptLog
                _log_db = SessionLocal()
                try:
                    _log_db.add(WebhookReceiptLog(
                        channel_id=channel_id,
                        remote_ip="startup",
                        event_type="startup_register",
                        validation_result=validation[:32],
                        error_detail=(detail[:256] if detail else None),
                    ))
                    _log_db.commit()
                except Exception:
                    _log_db.rollback()
                finally:
                    _log_db.close()
            except Exception:
                pass

        if not webhook_base:
            # Quando base URL ausente, persiste log de falha por canal para
            # observabilidade completa (antes retornava cedo sem nenhuma linha no receipt_log).
            _env_hint = (
                "WEBHOOK_BASE_URL, APP_BASE_URL e RAILWAY_STATIC_URL não configurados. "
                "Em Railway, RAILWAY_STATIC_URL deve ser injetado automaticamente."
            )
            print(f"[WEBHOOK-STARTUP] {_env_hint} Re-registro automático ignorado.")
            if channels:
                for _ch in channels:
                    _persist_startup_log(_ch.id, "failed", _env_hint[:256])
                print(
                    f"[WEBHOOK-STARTUP] {len(channels)} canal(is) marcado(s) como falha "
                    "no receipt_log (sem base URL)."
                )
            return

        if not channels:
            print("[WEBHOOK-STARTUP] Todos os canais ativos já têm webhook registrado.")
            return

        print(
            f"[WEBHOOK-STARTUP] {len(channels)} canal(is) com webhook_auto_registered=false "
            "— tentando re-registro automático..."
        )

        updated = 0
        results_log = []

        for ch in channels:
            webhook_url = f"{webhook_base}/api/whatsapp/webhook/{ch.id}"
            canal_label = ch.label or ch.name
            try:
                client = ZAPIClient(
                    instance_id=ch.instance_id,
                    token=ch.token,
                    client_token=ch.client_token,
                )
                # Task #304 — usa update_all_webhooks (configura todos os tipos de evento)
                # com fallback automático para update_webhook se não suportado.
                result = await client.update_all_webhooks(webhook_url)
                if result.get("success"):
                    ch.webhook_auto_registered = True
                    ch.webhook_url = webhook_url
                    updated += 1
                    endpoint_used = result.get("endpoint_used", "?")
                    print(
                        f"[WEBHOOK-STARTUP] ✅ Canal {ch.id} ({canal_label}) "
                        f"registrado — url={webhook_url} endpoint={endpoint_used}"
                    )
                    results_log.append(
                        f"  ✅ Canal {ch.id} ({canal_label}): OK ({endpoint_used})"
                    )
                    _persist_startup_log(ch.id, "ok", f"url={webhook_url} endpoint={endpoint_used}")
                else:
                    err = result.get("error") or result.get("body_error") or str(result)
                    print(
                        f"[WEBHOOK-STARTUP] ❌ Canal {ch.id} ({canal_label}) "
                        f"— falha (instância pode estar desconectada): {err}"
                    )
                    results_log.append(
                        f"  ❌ Canal {ch.id} ({canal_label}): falha — {err}"
                    )
                    _persist_startup_log(ch.id, "failed", err[:256] if err else None)
            except Exception as exc:
                _etype = type(exc).__name__
                _emsg = f"{_etype}: {exc}"
                print(
                    f"[WEBHOOK-STARTUP] ❌ Canal {ch.id} ({canal_label}) "
                    f"— erro {_emsg}"
                )
                results_log.append(
                    f"  ❌ Canal {ch.id} ({canal_label}): {_emsg}"
                )
                _persist_startup_log(ch.id, "failed", _emsg[:256])

        if updated > 0:
            db.commit()

        # Sumário consolidado — facilita diagnóstico em logs Railway/produção
        print(
            f"[WEBHOOK-STARTUP] Resultado: {updated}/{len(channels)} canal(is) registrado(s). "
            f"(base_url={webhook_base!r})"
        )
        if results_log:
            print("[WEBHOOK-STARTUP] Detalhe por canal:\n" + "\n".join(results_log))
    except Exception as exc:
        print(f"[WEBHOOK-STARTUP] Erro inesperado: {type(exc).__name__}: {exc}")
        db.rollback()
    finally:
        db.close()


async def _verify_and_reregister_channel(ch, webhook_base: str, db) -> str:
    """
    Task #309 — Verifica se a URL de webhook registrada no Z-API para o canal `ch`
    bate com a URL esperada. Se houver divergência (ou webhook ausente), re-registra.

    Retorna um dos três valores de `validation_result`:
    - "ok"               — URL bate, sem ação necessária.
    - "url_mismatch_fixed" — URL divergia; re-registro bem-sucedido.
    - "failed"           — não foi possível verificar ou re-registrar.

    Persiste um evento `periodic_revalidation` em `webhook_receipt_log` em todos os casos.
    Atualiza `last_webhook_verified_at` no canal quando o resultado é `ok` ou
    `url_mismatch_fixed`.
    """
    from database.models import WebhookReceiptLog
    import os

    global_ct = os.getenv("ZAPI_CLIENT_TOKEN", "")
    expected_url = f"{webhook_base}/api/whatsapp/webhook/{ch.id}"
    canal_label = ch.label or ch.name

    def _log(validation: str, detail: Optional[str] = None):
        """Persiste evento de revalidação periódica no webhook_receipt_log."""
        try:
            from database.database import SessionLocal as _SL
            _db = _SL()
            try:
                _db.add(WebhookReceiptLog(
                    channel_id=ch.id,
                    remote_ip="periodic_check",
                    event_type="periodic_revalidation",
                    validation_result=validation[:32],
                    error_detail=(detail[:256] if detail else None),
                ))
                _db.commit()
            except Exception:
                _db.rollback()
            finally:
                _db.close()
        except Exception:
            pass

    try:
        from services.whatsapp_client import ZAPIClient
        client = ZAPIClient(
            instance_id=ch.instance_id,
            token=ch.token,
            client_token=ch.client_token or global_ct or None,
        )
        settings_result = await client.get_webhook_settings(timeout=10.0)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — erro ao buscar settings: {msg}")
        _log("failed", msg)
        return "failed"

    if not settings_result.get("success"):
        err = settings_result.get("error", "falha ao chamar /webhooks")
        print(f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — /webhooks retornou erro: {err}")
        _log("failed", err[:256] if err else None)
        return "failed"

    # Quando endpoint não existe no Z-API (NOT_FOUND), não podemos verificar mas
    # também não é um erro real — preserva o estado atual e anota como ok
    # (comportamento conservador: evita re-registro desnecessário).
    if settings_result.get("endpoint_not_found"):
        print(
            f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — GET /webhooks não suportado; "
            "assumindo ok (endpoint_not_found)."
        )
        from datetime import datetime, timezone as _tz
        ch.last_webhook_verified_at = datetime.now(_tz.utc)
        _log("ok", "endpoint_not_found — URL não verificável, assumindo registrado")
        return "ok"

    # Extrai URL registrada — Z-API pode guardar em vários campos dependendo da versão
    settings = settings_result.get("settings") or {}
    registered_url: Optional[str] = None
    for field in ("deliveryUrl", "url", "webhookUrl", "value", "received"):
        val = settings.get(field)
        if isinstance(val, str) and val.startswith("http"):
            registered_url = val
            break
        # Subestrutura (ex: {"received": {"url": "..."}})
        if isinstance(val, dict):
            sub = val.get("url") or val.get("value") or val.get("deliveryUrl")
            if isinstance(sub, str) and sub.startswith("http"):
                registered_url = sub
                break

    if registered_url and registered_url.rstrip("/") == expected_url.rstrip("/"):
        # URL correta — apenas anota verificação
        from datetime import datetime, timezone as _tz
        ch.last_webhook_verified_at = datetime.now(_tz.utc)
        print(
            f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — ✅ URL correta: {registered_url}"
        )
        _log("ok", f"url={registered_url}")
        return "ok"

    # URL divergente (ou webhook ausente) — re-registra
    mismatch_detail = (
        f"registrada={registered_url!r} esperada={expected_url!r}"
        if registered_url
        else f"webhook ausente; esperada={expected_url!r}"
    )
    print(
        f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — ⚠️ divergência detectada: "
        f"{mismatch_detail}. Re-registrando..."
    )

    try:
        reg_result = await client.update_all_webhooks(expected_url)
    except Exception as exc:
        msg = f"re-registro falhou: {type(exc).__name__}: {exc}"
        print(f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — ❌ {msg}")
        ch.webhook_auto_registered = False
        _log("failed", f"{mismatch_detail} | {msg}")
        return "failed"

    if reg_result.get("success"):
        from datetime import datetime, timezone as _tz
        ch.webhook_auto_registered = True
        ch.webhook_url = expected_url
        ch.last_webhook_verified_at = datetime.now(_tz.utc)
        print(
            f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — ✅ re-registrado: "
            f"url={expected_url} endpoint={reg_result.get('endpoint_used', '?')}"
        )
        _log("url_mismatch_fixed", f"{mismatch_detail} → corrigido")
        return "url_mismatch_fixed"
    else:
        err = reg_result.get("error") or reg_result.get("body_error") or str(reg_result)
        print(f"[WEBHOOK-VERIFY] Canal {ch.id} ({canal_label}) — ❌ re-registro falhou: {err}")
        ch.webhook_auto_registered = False
        _log("failed", f"{mismatch_detail} | {err[:200] if err else None}")
        return "failed"


async def _run_webhook_revalidation(webhook_base: str):
    """
    Task #309 — Executa _verify_and_reregister_channel para todos os canais
    ativos não-legados. Chamado no startup (após _auto_register_webhooks_startup)
    e pelo loop diário.
    """
    from database.database import SessionLocal
    from database.models import ZAPIChannel

    db = SessionLocal()
    try:
        channels = (
            db.query(ZAPIChannel)
            .filter(
                ZAPIChannel.is_active.is_(True),
                ZAPIChannel.is_legacy.is_(False),
            )
            .all()
        )

        if not channels:
            print("[WEBHOOK-VERIFY] Nenhum canal ativo não-legado para verificar.")
            return

        print(
            f"[WEBHOOK-VERIFY] Iniciando verificação periódica de {len(channels)} canal(is) "
            f"(base_url={webhook_base!r})..."
        )

        ok_count = mismatch_fixed = failed_count = 0
        for ch in channels:
            result = await _verify_and_reregister_channel(ch, webhook_base, db)
            if result == "ok":
                ok_count += 1
            elif result == "url_mismatch_fixed":
                mismatch_fixed += 1
            else:
                failed_count += 1

        # Sempre faz commit quando qualquer canal teve estado alterado — inclusive
        # falhas que marcam webhook_auto_registered=False (sem commit, o banner de
        # alerta na UI não apareceria no cenário de degradação total).
        any_mutated = ok_count + mismatch_fixed + failed_count > 0
        if any_mutated:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                print(f"[WEBHOOK-VERIFY] Erro ao persistir resultados: {exc}")

        print(
            f"[WEBHOOK-VERIFY] Resultado: {ok_count} ok, {mismatch_fixed} corrigidos, "
            f"{failed_count} com falha. Total: {len(channels)}"
        )
    except Exception as exc:
        print(f"[WEBHOOK-VERIFY] Erro inesperado: {type(exc).__name__}: {exc}")
        db.rollback()
    finally:
        db.close()


async def _webhook_revalidation_loop():
    """
    Task #309 — Loop de revalidação periódica de webhooks.
    Executa uma vez no startup (após aguardar 30s para o servidor estabilizar)
    e depois diariamente (a cada 24h).
    """
    import asyncio
    import os

    # Aguarda o startup se estabilizar antes da primeira verificação.
    await asyncio.sleep(30)

    while True:
        webhook_base = (
            os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
            or os.getenv("APP_BASE_URL", "").rstrip("/")
            or os.getenv("RAILWAY_STATIC_URL", "").rstrip("/")
        )
        if webhook_base:
            try:
                await _run_webhook_revalidation(webhook_base)
            except Exception as exc:
                print(f"[WEBHOOK-VERIFY] Erro no loop de revalidação: {type(exc).__name__}: {exc}")
        else:
            print(
                "[WEBHOOK-VERIFY] Loop de revalidação: sem base URL configurada — "
                "verificação ignorada neste ciclo."
            )

        # Aguarda 24h até a próxima rodada
        await asyncio.sleep(86400)


def _cleanup_old_webhook_logs():
    """
    Task #296 — Remove entradas de webhook_receipt_log com mais de 7 dias.
    Evita crescimento ilimitado da tabela de audit log. Idempotente.
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(days=7)
    db = SessionLocal()
    try:
        result = db.execute(
            sql_text("DELETE FROM webhook_receipt_log WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        db.commit()
        deleted = result.rowcount
        if deleted:
            print(f"[INIT] webhook_receipt_log: {deleted} entradas antigas removidas (>7d)")
    except Exception as exc:
        db.rollback()
        print(f"[INIT] Erro no cleanup de webhook_receipt_log: {exc}")
    finally:
        db.close()


def _cleanup_stale_processing_jobs():
    """Marca jobs travados em 'processing' (>30min sem update) como 'failed'."""
    from database.database import SessionLocal
    from database.models import DocumentProcessingJob, ProcessingJobStatus
    from datetime import datetime, timedelta
    from sqlalchemy import func as sql_func

    db = SessionLocal()
    try:
        stale_cutoff = datetime.utcnow() - timedelta(minutes=30)
        stale_jobs = db.query(DocumentProcessingJob).filter(
            DocumentProcessingJob.status == ProcessingJobStatus.PROCESSING.value,
            sql_func.coalesce(DocumentProcessingJob.updated_at, DocumentProcessingJob.created_at) < stale_cutoff
        ).all()
        if stale_jobs:
            for j in stale_jobs:
                j.status = ProcessingJobStatus.FAILED.value
                j.error_message = "Processamento interrompido (cleanup automatico na inicializacao)"
            db.commit()
            print(f"[INIT] {len(stale_jobs)} jobs travados em 'processing' marcados como 'failed'")
    finally:
        db.close()


def _apply_incremental_migrations():
    """
    Aplica migrações incrementais de schema que o create_all não cobre.
    Usa ADD COLUMN IF NOT EXISTS (idempotente no PostgreSQL) — seguro para rodar
    no startup de dev e produção quantas vezes for necessário.
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text
    migrations = [
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS intent_detected VARCHAR(50)",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS entities_detected TEXT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS composite_score_max FLOAT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS web_search_used BOOLEAN DEFAULT FALSE",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS blocks_with_scores TEXT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS is_comparative BOOLEAN DEFAULT FALSE",
        # Task #152 — RAG V3.3: telemetria, markdown-tables, reranker
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS tools_used TEXT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS reranker_kept_ids TEXT",
        "ALTER TABLE content_blocks ADD COLUMN IF NOT EXISTS content_for_embedding TEXT",
        "ALTER TABLE content_blocks ADD COLUMN IF NOT EXISTS embedding_version INTEGER DEFAULT 1",
        "ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS valid_until_dt TIMESTAMP",
        "ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS embedding_version INTEGER DEFAULT 1",
        "CREATE INDEX IF NOT EXISTS ix_document_embeddings_valid_until_dt ON document_embeddings(valid_until_dt)",
        "CREATE INDEX IF NOT EXISTS ix_document_embeddings_embedding_version ON document_embeddings(embedding_version)",
        # Backfill valid_until_dt a partir das strings parseáveis (DD/MM/YYYY ou YYYY-MM-DD)
        """UPDATE document_embeddings
           SET valid_until_dt = CASE
               WHEN valid_until ~ '^\\d{4}-\\d{2}-\\d{2}' THEN to_timestamp(substring(valid_until from 1 for 10), 'YYYY-MM-DD')
               WHEN valid_until ~ '^\\d{2}/\\d{2}/\\d{4}' THEN to_timestamp(substring(valid_until from 1 for 10), 'DD/MM/YYYY')
               ELSE NULL
           END
           WHERE valid_until_dt IS NULL AND valid_until IS NOT NULL AND valid_until != ''""",
        # Backfill material_product_links a partir de document_embeddings.product_ticker × products.ticker
        """INSERT INTO material_product_links (material_id, product_id, excluded_from_committee, created_at)
           SELECT DISTINCT
               de.material_id::INTEGER AS material_id,
               p.id AS product_id,
               FALSE AS excluded_from_committee,
               NOW() AS created_at
           FROM document_embeddings de
           JOIN products p ON UPPER(p.ticker) = UPPER(de.product_ticker)
           WHERE de.material_id IS NOT NULL
             AND de.material_id ~ '^\\d+$'
             AND de.product_ticker IS NOT NULL
             AND de.product_ticker != ''
             AND EXISTS (SELECT 1 FROM materials m WHERE m.id = de.material_id::INTEGER)
           ON CONFLICT ON CONSTRAINT uq_material_product_link DO NOTHING""",
        """CREATE TABLE IF NOT EXISTS material_files (
            id SERIAL PRIMARY KEY,
            material_id INTEGER NOT NULL UNIQUE REFERENCES materials(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            content_type VARCHAR(100) NOT NULL DEFAULT 'application/pdf',
            file_data BYTEA NOT NULL,
            file_size INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_material_files_material_id ON material_files(material_id)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_session_summary TEXT",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_session_ended_at TIMESTAMPTZ",
        """CREATE TABLE IF NOT EXISTS campaign_structures (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            ticker VARCHAR(20),
            structure_type VARCHAR(100) NOT NULL,
            campaign_slug VARCHAR(100) NOT NULL UNIQUE,
            key_data TEXT DEFAULT '{}',
            diagram_filename VARCHAR(255),
            material_id INTEGER REFERENCES materials(id),
            valid_from TIMESTAMPTZ,
            valid_until TIMESTAMPTZ,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_campaign_structures_slug ON campaign_structures(campaign_slug)",
        "CREATE INDEX IF NOT EXISTS ix_campaign_structures_ticker ON campaign_structures(ticker)",
        "CREATE INDEX IF NOT EXISTS ix_campaign_structures_name ON campaign_structures(name)",
        """CREATE TABLE IF NOT EXISTS outbox_messages (
            id SERIAL PRIMARY KEY,
            dedupe_key VARCHAR(255) NOT NULL UNIQUE,
            phone VARCHAR(50) NOT NULL,
            message_type VARCHAR(20) NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'PENDING',
            zaap_id VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            sent_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_outbox_messages_dedupe_key ON outbox_messages(dedupe_key)",
        "ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS ai_error_detail TEXT",
        """CREATE TABLE IF NOT EXISTS cadence_campaigns (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            status VARCHAR(20) DEFAULT 'scheduled',
            total_contacts INTEGER DEFAULT 0,
            daily_limit INTEGER DEFAULT 50,
            deadline_days INTEGER DEFAULT 5,
            start_date TIMESTAMPTZ,
            end_date TIMESTAMPTZ,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS cadence_campaign_contacts (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER NOT NULL REFERENCES cadence_campaigns(id) ON DELETE CASCADE,
            phone VARCHAR(50) NOT NULL,
            name VARCHAR(255),
            custom_message TEXT NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            priority INTEGER DEFAULT 3,
            scheduled_for TIMESTAMPTZ,
            sent_at TIMESTAMPTZ,
            delivered BOOLEAN DEFAULT FALSE,
            responded_at TIMESTAMPTZ,
            retry_count INTEGER DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS ix_cadence_cc_campaign_id ON cadence_campaign_contacts(campaign_id)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_cc_status ON cadence_campaign_contacts(status)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_cc_scheduled ON cadence_campaign_contacts(scheduled_for)",
        """CREATE TABLE IF NOT EXISTS campaign_daily_log (
            id SERIAL PRIMARY KEY,
            campaign_id INTEGER NOT NULL REFERENCES cadence_campaigns(id) ON DELETE CASCADE,
            log_date TIMESTAMPTZ NOT NULL,
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            responded_count INTEGER DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS ix_campaign_daily_log_campaign ON campaign_daily_log(campaign_id)",
        """DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cost_tracking'
                AND column_name = 'conversation_id'
                AND data_type = 'integer'
            ) THEN
                ALTER TABLE cost_tracking ALTER COLUMN conversation_id TYPE VARCHAR(100) USING conversation_id::VARCHAR;
            END IF;
        END $$""",
        """DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'document_processing_jobs_material_id_fkey'
                AND confdeltype != 'c'
            ) THEN
                ALTER TABLE document_processing_jobs
                    DROP CONSTRAINT document_processing_jobs_material_id_fkey,
                    ADD CONSTRAINT document_processing_jobs_material_id_fkey
                        FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE;
            END IF;
        END $$""",
        """DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'document_page_results_job_id_fkey'
                AND confdeltype != 'c'
            ) THEN
                ALTER TABLE document_page_results
                    DROP CONSTRAINT document_page_results_job_id_fkey,
                    ADD CONSTRAINT document_page_results_job_id_fkey
                        FOREIGN KEY (job_id) REFERENCES document_processing_jobs(id) ON DELETE CASCADE;
            END IF;
        END $$""",
        """DO $$
        DECLARE
            dup RECORD;
            moved_msgs INTEGER;
            moved_tickets INTEGER;
            moved_history INTEGER;
            total_cleaned INTEGER := 0;
        BEGIN
            FOR dup IN
                SELECT c1.id AS dup_id, c1.phone AS dup_phone, c2.id AS real_id, c2.phone AS real_phone
                FROM conversations c1
                JOIN conversations c2 ON c2.chat_lid = c1.phone || '@lid'
                WHERE c1.id != c2.id
                  AND c1.phone IS NOT NULL
                  AND c2.chat_lid IS NOT NULL
                  AND length(regexp_replace(c1.phone, '[^0-9]', '', 'g')) > 13
                UNION
                SELECT c1.id AS dup_id, c1.phone AS dup_phone, c2.id AS real_id, c2.phone AS real_phone
                FROM conversations c1
                JOIN conversations c2 ON c2.chat_lid = c1.phone
                WHERE c1.id != c2.id
                  AND c1.phone LIKE '%@lid'
                  AND c2.chat_lid IS NOT NULL
            LOOP
                UPDATE whatsapp_messages SET conversation_id = dup.real_id
                WHERE conversation_id = dup.dup_id;
                GET DIAGNOSTICS moved_msgs = ROW_COUNT;
                UPDATE conversation_tickets SET conversation_id = dup.real_id
                WHERE conversation_id = dup.dup_id;
                GET DIAGNOSTICS moved_tickets = ROW_COUNT;
                UPDATE ticket_history SET conversation_id = dup.real_id
                WHERE conversation_id = dup.dup_id;
                GET DIAGNOSTICS moved_history = ROW_COUNT;
                RAISE NOTICE 'LID cleanup: dup_id=% (phone=%) → real_id=% (phone=%): msgs=%, tickets=%, history=%',
                    dup.dup_id, dup.dup_phone, dup.real_id, dup.real_phone, moved_msgs, moved_tickets, moved_history;
                DELETE FROM conversations WHERE id = dup.dup_id;
                total_cleaned := total_cleaned + 1;
            END LOOP;
            IF total_cleaned > 0 THEN
                RAISE NOTICE 'LID cleanup: consolidated % duplicate conversations total', total_cleaned;
            END IF;
        END $$""",
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS delivery_mode VARCHAR(20) DEFAULT 'immediate'",
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS daily_limit INTEGER",
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS deadline_days INTEGER",
        # Task #220: perfis de velocidade da cadência
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_profile VARCHAR(20) NOT NULL DEFAULT 'conservador'",
        "ALTER TABLE cadence_campaigns ADD COLUMN IF NOT EXISTS cadence_profile VARCHAR(20) NOT NULL DEFAULT 'conservador'",
        # Task #222: flag do modo "Finalizar disparos agora" (turbo seguro)
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_active BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_origin_profile VARCHAR(20)",
        "ALTER TABLE cadence_campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_active BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE cadence_campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_origin_profile VARCHAR(20)",
        # Task #222 — override persistido de janela comercial em modo turbo.
        "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_override_business_hours BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE cadence_campaigns ADD COLUMN IF NOT EXISTS cadence_turbo_override_business_hours BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ",
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 3",
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS responded_at TIMESTAMPTZ",
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS ix_campaign_dispatches_status ON campaign_dispatches(status)",
        "CREATE INDEX IF NOT EXISTS ix_campaign_dispatches_scheduled ON campaign_dispatches(scheduled_for)",
        "ALTER TABLE materials ADD COLUMN IF NOT EXISTS pdf_whatsapp_dismissed BOOLEAN DEFAULT FALSE",
        "ALTER TABLE materials ADD COLUMN IF NOT EXISTS is_committee_active BOOLEAN DEFAULT FALSE",
        "ALTER TABLE materials ADD COLUMN IF NOT EXISTS available_for_whatsapp BOOLEAN DEFAULT TRUE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS key_info TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_committee BOOLEAN DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_products_is_committee ON products(is_committee)",
        "ALTER TABLE material_product_links ADD COLUMN IF NOT EXISTS excluded_from_committee BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS categories TEXT DEFAULT '[]'",
        """UPDATE products SET categories = json_build_array(category)::text
           WHERE category IS NOT NULL AND category != ''
             AND (categories IS NULL OR categories = '[]')""",
        """UPDATE products SET categories = '[]', category = NULL
           WHERE description LIKE '%criado automaticamente%'
             AND categories = '["fii"]'""",
        """UPDATE whatsapp_messages
           SET conversation_id = c.id
           FROM conversations c
           WHERE whatsapp_messages.conversation_id IS NULL
             AND whatsapp_messages.chat_id LIKE '%@%'
             AND c.phone = REGEXP_REPLACE(whatsapp_messages.chat_id, '@[a-z.]+$', '', 'g')
        """,
        # Sub-A: limpar gestora names incorretamente copiados para categories (Task #98)
        """UPDATE products SET categories = '[]', category = NULL
           WHERE categories IN (
             '["Manatí Capital Management"]',
             '["BTG Pactual"]',
             '["Guardian Gestora"]',
             '["BTG Pactual Gestora"]',
             '["XP Asset"]',
             '["Kinea"]',
             '["RBR Asset"]',
             '["Hedge"]',
             '["Iridium"]',
             '["Vinci"]',
             '["TRX"]',
             '["Habitus"]'
           )""",
        # Sub-B: tabela de recomendações formais do Comitê SVN (Task #98)
        """CREATE TABLE IF NOT EXISTS recommendation_entries (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            rating VARCHAR(30),
            target_price FLOAT,
            rationale TEXT,
            added_by VARCHAR(255),
            added_at TIMESTAMPTZ DEFAULT NOW(),
            valid_from TIMESTAMPTZ DEFAULT NOW(),
            valid_until TIMESTAMPTZ,
            is_active BOOLEAN DEFAULT TRUE,
            notes TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS ix_recommendation_entries_product ON recommendation_entries(product_id)",
        "CREATE INDEX IF NOT EXISTS ix_recommendation_entries_active ON recommendation_entries(is_active)",
        "ALTER TABLE materials ADD COLUMN IF NOT EXISTS ai_product_analysis TEXT",
        "ALTER TABLE materials ALTER COLUMN product_id DROP NOT NULL",
        # Task #134: Categorias padrão para FIIs sem categoria (ticker terminado em 11)
        # Restrito a produtos cujo nome contém termos imobiliários para evitar classificar ETFs/units
        """UPDATE products SET category = 'FII'
           WHERE (category IS NULL OR category = '' OR category = 'fii')
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'
             AND LENGTH(ticker) BETWEEN 5 AND 7
             AND (
               name ~* '\\y(fundo|fii|imobiliário|imobiliario|fiagro|cri\\b|recebíveis|renda imobiliária|reit)\\y'
               OR description ~* '\\y(fundo de investimento imobiliário|fii|cri\\b|imóveis|imóvel)\\y'
             )""",
        # Task #134: Garantir que categories (JSON array) esteja alinhado com category para FIIs
        """UPDATE products SET categories = json_build_array(category)::text
           WHERE category = 'FII'
             AND (categories IS NULL OR categories = '[]' OR categories = '["fii"]')
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        # Task #134 (v2): Subcategorias de FII por padrão de nome do produto
        """UPDATE products SET category = 'FII de Papel'
           WHERE category = 'FII'
             AND (
               name ~* '\\y(papel|receb[ií]vel|crédito|credito|cri\\b|high.?grade|lci\\b|hipotecário)\\y'
               OR name ~* '\\y(high grade|papel imobiliário|renda imobiliária)\\y'
             )
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        """UPDATE products SET category = 'FII Logística'
           WHERE category = 'FII'
             AND (
               name ~* '\\y(log[ií]stic|galpão|galpao|industrial|armazém|armazem|condomínio logístico)\\y'
             )
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        """UPDATE products SET category = 'FII de Fundos'
           WHERE category = 'FII'
             AND (
               name ~* '\\y(fundo de fundos|fof\\b|multigestão|multi.gestão|fundo.s.imobiliário.s.acesso)\\y'
             )
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        """UPDATE products SET category = 'FII Híbrido'
           WHERE category = 'FII'
             AND (
               name ~* '\\y(híbrido|hibrido|misto|diversificado)\\y'
             )
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        # Task #134 (v2): Sincronizar categories array com as subcategorias atribuídas
        """UPDATE products SET categories = json_build_array(category)::text
           WHERE category IN ('FII de Papel','FII Logística','FII de Fundos','FII Híbrido','FII Tijolo')
             AND (categories IS NULL OR categories = '[]' OR categories = '["FII"]' OR categories = '["fii"]')
             AND ticker IS NOT NULL
             AND UPPER(ticker) LIKE '%11'""",
        # Task #137: Normalizar 'FII de Papel' → 'FII Papel' (nome canônico sem 'de')
        """UPDATE products SET category = 'FII Papel',
                               categories = REPLACE(categories, 'FII de Papel', 'FII Papel')
           WHERE category = 'FII de Papel'""",
        # Task #137: Subcategorias de FII — tickers conhecidos com classificação manual
        """UPDATE products SET category = 'FII Papel', categories = '["FII Papel"]'
           WHERE UPPER(ticker) IN ('GARE11','MANA11','RZAT11','MCRE11','PCIP11')
             AND (category IS NULL OR category = '' OR category = 'FII')""",
        """UPDATE products SET category = 'FII Logística', categories = '["FII Logística"]'
           WHERE UPPER(ticker) IN ('LVBI11','BTLG11')
             AND (category IS NULL OR category = '' OR category = 'FII')""",
        """UPDATE products SET category = 'FII Tijolo', categories = '["FII Tijolo"]'
           WHERE UPPER(ticker) IN ('LIFE11')
             AND (category IS NULL OR category = '' OR category = 'FII')""",
        # RAG V3.6 — Telemetria de respostas evasivas. Quando o agente
        # responde com padrões como "documento não detalha", "não encontrei
        # nos materiais", apesar do RAG ter retornado resultados, gravamos
        # aqui para auditoria e calibração contínua.
        """CREATE TABLE IF NOT EXISTS rag_evasive_responses (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            conversation_id VARCHAR(100),
            user_query TEXT NOT NULL,
            ai_response TEXT NOT NULL,
            evasive_pattern VARCHAR(255),
            had_kb_results BOOLEAN DEFAULT FALSE,
            kb_results_count INTEGER DEFAULT 0,
            completeness_mode BOOLEAN DEFAULT FALSE,
            tools_used TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS ix_rag_evasive_created_at ON rag_evasive_responses(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_rag_evasive_conversation ON rag_evasive_responses(conversation_id)",
        # RAG V3.6 — enriquecimento da telemetria evasiva: identificadores e
        # nomes dos materiais recuperados (JSON), top_k efetivo (page_size da
        # última chamada KB) e label textual do intent classificado. Permite
        # diagnóstico segmentado por material/query no painel admin.
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS retrieved_material_ids TEXT",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS retrieved_material_names TEXT",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS top_k INTEGER",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS intent_label VARCHAR(50)",
        # Task #190 — painel admin para triagem de evasivas. Permite marcar
        # cada registro como 'resolved' (problema corrigido — prompt/reranker
        # ajustados / PDF re-extraído) ou 'false_positive' (a resposta era
        # de fato adequada). Linhas em aberto têm resolution_status NULL.
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS resolution_status VARCHAR(50)",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS resolved_by_user_id INTEGER",
        "ALTER TABLE rag_evasive_responses ADD COLUMN IF NOT EXISTS resolution_note TEXT",
        "CREATE INDEX IF NOT EXISTS ix_rag_evasive_resolution ON rag_evasive_responses(resolution_status)",
        # Task #206 — Sistema de Carteiras Recomendadas
        """CREATE TABLE IF NOT EXISTS portfolios (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            portfolio_type VARCHAR(100),
            description TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_portfolios_name ON portfolios(name)",
        "CREATE INDEX IF NOT EXISTS ix_portfolios_is_active ON portfolios(is_active)",
        """CREATE TABLE IF NOT EXISTS portfolio_products (
            id SERIAL PRIMARY KEY,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_portfolio_product UNIQUE (portfolio_id, product_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_portfolio_products_portfolio ON portfolio_products(portfolio_id)",
        "CREATE INDEX IF NOT EXISTS ix_portfolio_products_product ON portfolio_products(product_id)",
        "ALTER TABLE materials ADD COLUMN IF NOT EXISTS portfolio_id INTEGER REFERENCES portfolios(id)",
        "CREATE INDEX IF NOT EXISTS ix_materials_portfolio_id ON materials(portfolio_id)",
        "ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS portfolio_id INTEGER",
        "ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS portfolio_name VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS ix_doc_embeddings_portfolio_id ON document_embeddings(portfolio_id)",
        # Task #213 — Apelidos/sinônimos de Carteiras Recomendadas
        "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS aliases TEXT DEFAULT '[]'",
        # Task #214 — Data da última revisão da Carteira Recomendada
        "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS last_reviewed_at TIMESTAMPTZ",
        # Task #221 — Observabilidade do motor de cadência
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS last_error_message TEXT",
        "ALTER TABLE cadence_campaign_contacts ADD COLUMN IF NOT EXISTS last_error_message TEXT",
        """CREATE TABLE IF NOT EXISTS cadence_engine_state (
            id INTEGER PRIMARY KEY,
            last_tick_at TIMESTAMPTZ,
            last_send_at TIMESTAMPTZ,
            pause_until TIMESTAMPTZ,
            pause_reason VARCHAR(64),
            consecutive_failures INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        "INSERT INTO cadence_engine_state (id, consecutive_failures) VALUES (1, 0) ON CONFLICT (id) DO NOTHING",
        """CREATE TABLE IF NOT EXISTS cadence_campaign_events (
            id SERIAL PRIMARY KEY,
            campaign_kind VARCHAR(16) NOT NULL,
            campaign_id INTEGER NOT NULL,
            event_type VARCHAR(48) NOT NULL,
            payload TEXT,
            user_id INTEGER REFERENCES users(id),
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_cadence_event_dedupe UNIQUE (campaign_kind, campaign_id, event_type, occurred_at)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_kind ON cadence_campaign_events(campaign_kind)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_campaign_id ON cadence_campaign_events(campaign_id)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_event_type ON cadence_campaign_events(event_type)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_occurred_at ON cadence_campaign_events(occurred_at)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_campaign_lookup ON cadence_campaign_events(campaign_kind, campaign_id, occurred_at)",
        # Task #221 V13 — discriminador para idempotência sem bloquear runtime.
        # 1) Adiciona coluna dedupe_key (nullable).
        # 2) Substitui a UNIQUE antiga (que envolvia occurred_at e bloqueava
        #    múltiplos dispatch_failed no mesmo segundo) por uma UNIQUE em
        #    (kind, id, type, dedupe_key). NULLs em dedupe_key não colidem,
        #    preservando inserts de runtime livres.
        "ALTER TABLE cadence_campaign_events ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(80)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_events_dedupe_key ON cadence_campaign_events(dedupe_key)",
        "ALTER TABLE cadence_campaign_events DROP CONSTRAINT IF EXISTS uq_cadence_event_dedupe",
        "ALTER TABLE cadence_campaign_events ADD CONSTRAINT uq_cadence_event_dedupe "
        "UNIQUE (campaign_kind, campaign_id, event_type, dedupe_key)",
        # Task #223 — Fundação multi-canal WhatsApp
        # 1) Tabela de canais Z-API
        """CREATE TABLE IF NOT EXISTS zapi_channels (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            instance_id VARCHAR(255) NOT NULL,
            token VARCHAR(255) NOT NULL,
            client_token VARCHAR(255),
            webhook_url VARCHAR(500),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_legacy BOOLEAN NOT NULL DEFAULT FALSE,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_zapi_channels_is_active ON zapi_channels(is_active)",
        "CREATE INDEX IF NOT EXISTS ix_zapi_channels_is_legacy ON zapi_channels(is_legacy)",
        # 2) Mapeamento unidade → canal
        """CREATE TABLE IF NOT EXISTS unidade_channel_mapping (
            id SERIAL PRIMARY KEY,
            unidade VARCHAR(100) NOT NULL UNIQUE,
            channel_id INTEGER NOT NULL REFERENCES zapi_channels(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ
        )""",
        "CREATE INDEX IF NOT EXISTS ix_unidade_channel_mapping_unidade ON unidade_channel_mapping(unidade)",
        "CREATE INDEX IF NOT EXISTS ix_unidade_channel_mapping_channel ON unidade_channel_mapping(channel_id)",
        # 3) FK channel_id em tabelas de despacho / conversas / mensagens
        "ALTER TABLE assessores ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES zapi_channels(id)",
        "ALTER TABLE campaign_dispatches ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES zapi_channels(id)",
        "ALTER TABLE cadence_campaign_contacts ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES zapi_channels(id)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES zapi_channels(id)",
        "ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES zapi_channels(id)",
        "CREATE INDEX IF NOT EXISTS ix_assessores_channel_id ON assessores(channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_campaign_dispatches_channel_id ON campaign_dispatches(channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_cadence_contacts_channel_id ON cadence_campaign_contacts(channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_conversations_channel_id ON conversations(channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_channel_id ON whatsapp_messages(channel_id)",
        # Task #223 — Colunas adicionadas ao modelo ZAPIChannel após create_all inicial.
        # A tabela já existe (criada pelo create_all), então usamos ADD COLUMN IF NOT EXISTS.
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS description TEXT",
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500)",
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS label VARCHAR(100)",
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS phone_number VARCHAR(50)",
        "ALTER TABLE zapi_channels ALTER COLUMN name TYPE VARCHAR(100)",
        "ALTER TABLE zapi_channels ALTER COLUMN client_token DROP NOT NULL",
        # Task #261 — marca mensagens originadas de disparos de teste.
        "ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS is_test_dispatch BOOLEAN DEFAULT FALSE",
        # Task #264 — rastreia se o webhook foi registrado com sucesso na instância Z-API.
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS webhook_auto_registered BOOLEAN DEFAULT FALSE",
        # Task #296 — audit log de tentativas de recepção de webhook (sucesso e falhas).
        """CREATE TABLE IF NOT EXISTS webhook_receipt_log (
            id SERIAL PRIMARY KEY,
            channel_id INTEGER REFERENCES zapi_channels(id) ON DELETE SET NULL,
            remote_ip VARCHAR(64),
            event_type VARCHAR(64),
            validation_result VARCHAR(32) NOT NULL,
            error_detail VARCHAR(256),
            created_at TIMESTAMPTZ DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS ix_webhook_receipt_log_channel_created ON webhook_receipt_log(channel_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_webhook_receipt_log_created ON webhook_receipt_log(created_at DESC)",
        # Task #309 — timestamp da última verificação periódica bem-sucedida do webhook.
        "ALTER TABLE zapi_channels ADD COLUMN IF NOT EXISTS last_webhook_verified_at TIMESTAMPTZ",
    ]
    db = SessionLocal()
    ok = 0
    failed = 0
    try:
        for sql in migrations:
            # Cada instrução em sua própria transação para que uma falha não anule
            # todo o lote (Task #152). Erros são logados com o trecho da SQL.
            try:
                db.execute(sql_text(sql))
                db.commit()
                ok += 1
            except Exception as stmt_err:
                db.rollback()
                failed += 1
                snippet = " ".join(sql.split())[:140]
                print(f"[INIT] Migração falhou (continuando): {stmt_err} | SQL: {snippet}")
        print(
            f"[INIT] Migrações incrementais aplicadas: {ok} OK, {failed} falharam "
            f"de {len(migrations)} instruções"
        )
    finally:
        db.close()


def _bootstrap_legacy_channel():
    """
    Task #223 — Garante que o canal Z-API legado (env vars) existe em `zapi_channels`.
    Executado no startup, após as migrations, sempre que a tabela estiver vazia.
    Idempotente: não recria se já existir um canal is_legacy=True.
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text

    instance_id = os.getenv("ZAPI_INSTANCE_ID", "")
    token = os.getenv("ZAPI_TOKEN", "")
    client_token = os.getenv("ZAPI_CLIENT_TOKEN", "")

    if not instance_id or not token:
        print("[INIT] Bootstrap canal legado ignorado: ZAPI_INSTANCE_ID ou ZAPI_TOKEN não configurados")
        return

    db = SessionLocal()
    try:
        count = db.execute(sql_text("SELECT COUNT(*) FROM zapi_channels")).scalar()
        if count > 0:
            print(f"[INIT] zapi_channels já contém {count} canal(is) — bootstrap ignorado")
            return

        db.execute(
            sql_text("""
                INSERT INTO zapi_channels (name, instance_id, token, client_token, is_active, is_legacy, description)
                VALUES (:name, :instance_id, :token, :client_token, TRUE, TRUE,
                        'Canal principal configurado via variáveis de ambiente')
                ON CONFLICT DO NOTHING
            """),
            {
                "name": "Canal Principal (Legado)",
                "instance_id": instance_id,
                "token": token,
                "client_token": client_token or None,
            }
        )
        db.commit()
        print("[INIT] Canal legado Z-API criado em zapi_channels com is_legacy=TRUE")
    except Exception as exc:
        db.rollback()
        print(f"[INIT] Aviso: erro no bootstrap do canal legado: {exc}")
    finally:
        db.close()


def _cleanup_orphan_pre_analysis_materials():
    """
    Remove materiais 'pending' criados via pre-analyze-upload que foram abandonados
    pelo usuário (não confirmados) há mais de 24 horas e sem nenhum MaterialProductLink.
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text
    db = SessionLocal()
    try:
        result = db.execute(sql_text("""
            DELETE FROM materials
            WHERE processing_status = 'pending'
              AND product_id IS NULL
              AND created_at < NOW() - INTERVAL '24 hours'
              AND id NOT IN (
                  SELECT DISTINCT material_id FROM material_product_links
              )
        """))
        deleted = result.rowcount
        if deleted > 0:
            db.commit()
            print(f"[INIT] Cleanup: {deleted} material(is) de pré-análise abandonados removidos")
    except Exception as e:
        db.rollback()
        print(f"[INIT] Aviso: erro no cleanup de materiais orphans: {e}")
    finally:
        db.close()


def _backfill_cadence_events():
    """
    Task #221 — Backfill leve, idempotente, dos eventos de campanhas
    pré-existentes a partir das colunas que JÁ existiam no banco antes
    desta task. Evita timelines vazias para campanhas em curso.

    Eventos gerados:
    - campaign_created (a partir de created_at)
    - campaign_started (a partir de start_date / sent_at)
    - campaign_done (a partir de end_date e status terminal)
    - dispatch_failed (um por dispatch/contact com status 'failed', usando
      error_message ou last_error_message como mensagem). NÃO geramos
      dispatch_sent porque seriam dezenas/centenas por campanha — o motor
      passará a registrar isso a partir de agora.

    Idempotência: a UNIQUE (campaign_kind, campaign_id, event_type, occurred_at)
    impede duplicatas. Cada evento gerado leva is_backfill=true no payload
    para que a UI mostre como "evento reconstruído".
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text
    db = SessionLocal()
    inserted = 0
    try:
        # Task #221 — pré-passo: copiar `error_message` histórico para a nova
        # coluna `last_error_message` (idempotente: só atualiza onde está NULL).
        # Isso garante paridade total dos dados antigos com a nova UI.
        for upd in (
            "UPDATE campaign_dispatches SET last_error_message = LEFT(error_message, 500) "
            "WHERE last_error_message IS NULL AND error_message IS NOT NULL",
            # Para a tabela legacy não há coluna error_message histórica;
            # apenas garantimos que a coluna exista com NULL (já feito pela migration).
        ):
            try:
                r = db.execute(sql_text(upd))
                db.commit()
                if r.rowcount and r.rowcount > 0:
                    print(f"[INIT] Backfill last_error_message: {r.rowcount} linhas copiadas")
            except Exception as e:
                db.rollback()
                print(f"[INIT] Aviso: backfill last_error_message falhou: {e}")

        # Cada CTE roda como statement separado para evitar parsing de
        # parâmetros pelo SQLAlchemy (':true' no JSON literal seria
        # interpretado como bind). Usamos jsonb_build_object para construir
        # o payload de forma segura e idempotente.
        # V13: cada INSERT carrega `dedupe_key` único por linha de origem.
        # Lifecycle único por campanha: 'created'/'started'/'done'.
        # Falhas: 'contact:<id>'/'disp:<id>' — assim múltiplas falhas no mesmo
        # segundo NÃO colidem entre si (problema apontado pelo arquiteto).
        statements = [
            # Legacy — created
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'legacy', cc.id, 'campaign_created',
                      jsonb_build_object('is_backfill', true, 'name', cc.name)::text,
                      cc.created_at, NOW(), 'created'
               FROM cadence_campaigns cc
               WHERE cc.created_at IS NOT NULL
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Legacy — started
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'legacy', cc.id, 'campaign_started',
                      jsonb_build_object('is_backfill', true)::text,
                      cc.start_date, NOW(), 'started'
               FROM cadence_campaigns cc
               WHERE cc.start_date IS NOT NULL
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Legacy — done (legacy tem end_date confiável)
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'legacy', cc.id, 'campaign_done',
                      jsonb_build_object('is_backfill', true)::text,
                      cc.end_date, NOW(), 'done'
               FROM cadence_campaigns cc
               WHERE cc.end_date IS NOT NULL AND cc.status = 'done'
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Legacy — dispatch_failed (1 por contato falho, dedupe por contact_id)
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'legacy', ccc.campaign_id, 'dispatch_failed',
                      jsonb_build_object(
                          'is_backfill', true, 'is_final', true,
                          'phone', ccc.phone, 'contact_id', ccc.id,
                          'error', LEFT(COALESCE(ccc.last_error_message,''), 300)
                      )::text,
                      COALESCE(ccc.sent_at, ccc.scheduled_for), NOW(),
                      'contact:' || ccc.id::text
               FROM cadence_campaign_contacts ccc
               WHERE ccc.status = 'failed'
                 AND COALESCE(ccc.sent_at, ccc.scheduled_for) IS NOT NULL
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Unified — created
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'unified', c.id, 'campaign_created',
                      jsonb_build_object('is_backfill', true, 'name', c.name)::text,
                      c.created_at, NOW(), 'created'
               FROM campaigns c
               WHERE c.created_at IS NOT NULL
                 AND (c.delivery_mode = 'cadence'
                      OR c.status IN ('firing_cadence','paused_cadence','cadence_done'))
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Unified — started
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'unified', c.id, 'campaign_started',
                      jsonb_build_object('is_backfill', true)::text,
                      c.sent_at, NOW(), 'started'
               FROM campaigns c
               WHERE c.sent_at IS NOT NULL
                 AND (c.delivery_mode = 'cadence'
                      OR c.status IN ('firing_cadence','paused_cadence','cadence_done'))
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Unified — done. `campaigns` não tem end_date; usamos MAX(cd.sent_at)
            # como melhor proxy do término real, com fallback em c.sent_at e flag
            # `timestamp_proxy` no payload para sinalizar a aproximação.
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'unified', c.id, 'campaign_done',
                      jsonb_build_object(
                          'is_backfill', true,
                          'timestamp_proxy', CASE WHEN MAX(cd.sent_at) IS NOT NULL
                                                  THEN 'max_dispatch_sent_at'
                                                  ELSE 'campaign_sent_at_start' END
                      )::text,
                      COALESCE(MAX(cd.sent_at), c.sent_at), NOW(), 'done'
               FROM campaigns c
               LEFT JOIN campaign_dispatches cd ON cd.campaign_id = c.id
               WHERE c.status = 'cadence_done' AND c.sent_at IS NOT NULL
               GROUP BY c.id, c.sent_at
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
            # Unified — dispatch_failed (dedupe por dispatch_id)
            """INSERT INTO cadence_campaign_events
                  (campaign_kind, campaign_id, event_type, payload, occurred_at, created_at, dedupe_key)
               SELECT 'unified', cd.campaign_id, 'dispatch_failed',
                      jsonb_build_object(
                          'is_backfill', true, 'is_final', true,
                          'phone', COALESCE(cd.assessor_phone,''),
                          'dispatch_id', cd.id,
                          'error', LEFT(COALESCE(cd.error_message, cd.last_error_message, ''), 300)
                      )::text,
                      COALESCE(cd.sent_at, cd.scheduled_for), NOW(),
                      'disp:' || cd.id::text
               FROM campaign_dispatches cd
               JOIN campaigns c ON c.id = cd.campaign_id
               WHERE cd.status = 'failed'
                 AND COALESCE(cd.sent_at, cd.scheduled_for) IS NOT NULL
                 AND (c.delivery_mode = 'cadence'
                      OR c.status IN ('firing_cadence','paused_cadence','cadence_done'))
               ON CONFLICT ON CONSTRAINT uq_cadence_event_dedupe DO NOTHING""",
        ]
        for st in statements:
            try:
                r = db.execute(sql_text(st))
                inserted += int(r.rowcount or 0)
                db.commit()
            except Exception as inner:
                db.rollback()
                snippet = " ".join(st.split())[:120]
                print(f"[INIT] Aviso: backfill statement falhou (continuando): {inner} | SQL: {snippet}")
        if inserted > 0:
            print(f"[INIT] Backfill de eventos de cadência: {inserted} eventos sintéticos criados")
        else:
            print("[INIT] Backfill de eventos de cadência: nada a criar (já idempotente)")
    except Exception as e:
        db.rollback()
        print(f"[INIT] Aviso: backfill de eventos de cadência falhou: {e}")
    finally:
        db.close()


def _cleanup_old_cadence_events(retention_days: Optional[int] = None):
    """Task #221 — remove eventos antigos para evitar crescimento indefinido.

    Configurável via env `CADENCE_EVENTS_RETENTION_DAYS` (default 90).
    """
    import os
    from database.database import SessionLocal
    from services.cadence_events import cleanup_old_events
    if retention_days is None:
        try:
            retention_days = int(os.getenv("CADENCE_EVENTS_RETENTION_DAYS", "90"))
        except (TypeError, ValueError):
            retention_days = 90
    db = SessionLocal()
    try:
        n = cleanup_old_events(db, retention_days)
        if n > 0:
            print(f"[INIT] Cleanup de eventos de cadência > {retention_days}d: {n} removidos")
    except Exception as e:
        print(f"[INIT] Aviso: cleanup de eventos de cadência falhou: {e}")
    finally:
        db.close()


def _backfill_conversation_ticket_status():
    """Task #291 — migra conversas com ticket_status=NULL para 'new'.

    Conversas criadas antes desta task (via Z-API sync ou webhook outbound) ficavam
    com ticket_status=NULL e eram invisíveis no filtro padrão 'Novas' da Central.
    Idempotente: só atualiza rows com NULL, excluindo conversas já fechadas.
    """
    from database.database import SessionLocal
    from sqlalchemy import text as sql_text
    db = SessionLocal()
    try:
        result = db.execute(sql_text(
            "UPDATE conversations SET ticket_status = 'new' "
            "WHERE ticket_status IS NULL "
            "AND (status IS NULL OR status NOT IN ('closed', 'archived'))"
        ))
        updated = result.rowcount
        db.commit()
        if updated > 0:
            print(f"[INIT] Backfill ticket_status: {updated} conversa(s) migrada(s) para 'new'")
    except Exception as e:
        print(f"[INIT] Aviso: backfill de ticket_status falhou: {e}")
        db.rollback()
    finally:
        db.close()


def _sync_init_database():
    """Operações síncronas de inicialização do banco (roda em thread separada)."""
    import os
    from database.database import engine, Base, SessionLocal
    from database import crud
    from database.models import Product

    db_url_str = str(engine.url)
    is_sqlite = "sqlite" in db_url_str.lower()
    safe_url = db_url_str.split("@")[-1] if "@" in db_url_str else db_url_str
    print(f"[INIT] Database engine: {'SQLite' if is_sqlite else 'PostgreSQL'} ({safe_url})")
    if is_sqlite:
        print("[INIT] ALERTA CRÍTICO: App conectado a SQLite! Verifique DATABASE_URL.")

    Base.metadata.create_all(bind=engine)

    # MIGRATIONS INCREMENTAIS — colunas novas em tabelas existentes.
    # create_all não adiciona colunas a tabelas já existentes; fazemos aqui via IF NOT EXISTS.
    # Seguro para rodar múltiplas vezes: ADD COLUMN IF NOT EXISTS é idempotente no PostgreSQL.
    if not is_sqlite:
        _apply_incremental_migrations()
        _bootstrap_legacy_channel()
        _cleanup_orphan_pre_analysis_materials()
        _backfill_cadence_events()
        _cleanup_old_cadence_events()
        _backfill_conversation_ticket_status()

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")

    db = SessionLocal()
    try:
        import secrets as _secrets
        from core.security import get_password_hash as _hash
        from database.models import User as _User

        admin = crud.get_user_by_username(db, admin_username)
        if not admin:
            # Cria o usuário bootstrap com senha aleatória irrecuperável.
            # O login por senha é bloqueado (HTTP 410) — a senha nunca é usada.
            # O acesso real é feito via SSO Microsoft com o email cadastrado na tabela.
            crud.create_user(
                db,
                username=admin_username,
                email=admin_email,
                password=_secrets.token_hex(64),
                role="admin"
            )
            print(f"[INIT] Usuário bootstrap '{admin_username}' criado. Acesso via SSO Microsoft.")
        else:
            # Neutralizar credenciais bootstrap em qualquer banco (dev ou produção).
            # Se o email ainda for o placeholder genérico, troca por domínio inválido
            # para evitar que alguém crie admin@example.com no Azure AD e faça SSO.
            PLACEHOLDER_EMAILS = {"admin@example.com", "admin@localhost"}
            if admin.email in PLACEHOLDER_EMAILS:
                admin.email = "admin-bootstrap-disabled@invalid.local"
                admin.hashed_password = _hash(_secrets.token_hex(64))
                db.commit()
                print(f"[INIT] Usuário admin bootstrap neutralizado: email e senha tornados irrecuperáveis.")

        crud.init_default_integrations(db)
        crud.init_default_categories(db)
        crud.init_default_agent_config(db)
    finally:
        db.close()


def _resume_interrupted_uploads():
    from datetime import datetime
    from database.database import SessionLocal
    from database.models import Material, ProcessingStatus, PersistentQueueItem, QueueItemStatus
    from database.models import DocumentProcessingJob, ProcessingJobStatus
    db = SessionLocal()
    try:
        interrupted_materials = db.query(Material).filter(
            Material.processing_status.in_(["processing", "pending"])
        ).all()

        if not interrupted_materials:
            return

        print(f"[INIT] Encontrados {len(interrupted_materials)} materiais com processamento interrompido.")

        for mat in interrupted_materials:
            already_queued = db.query(PersistentQueueItem).filter(
                PersistentQueueItem.material_id == mat.id,
                PersistentQueueItem.status.in_(["queued", "processing"])
            ).first()
            if already_queued:
                print(f"[INIT] Material '{mat.name}' (id={mat.id}): já possui item na fila, pulando.")
                continue

            job = db.query(DocumentProcessingJob).filter(
                DocumentProcessingJob.material_id == mat.id,
                DocumentProcessingJob.status.in_(["processing", "pending"])
            ).first()

            # Resolve o caminho do arquivo — primeiro no disco, depois restaura do banco.
            resolved_file_path = None
            if job and job.file_path and os.path.exists(job.file_path):
                resolved_file_path = job.file_path
            elif mat.source_file_path and os.path.exists(mat.source_file_path):
                resolved_file_path = mat.source_file_path
            else:
                # Tenta restaurar o PDF do banco de dados (material_files).
                try:
                    from api.endpoints.products import _restore_pdf_from_db
                    restored = _restore_pdf_from_db(db, mat.id)
                    if restored:
                        resolved_file_path = restored
                        if job:
                            job.file_path = restored
                            db.commit()
                        print(f"[INIT] PDF de '{mat.name}' restaurado do banco: {restored}")
                except Exception as restore_err:
                    print(f"[INIT] Falha ao restaurar PDF do banco para material {mat.id}: {restore_err}")

            if resolved_file_path:
                resume_page = (job.last_processed_page or 0) if job else 0
                print(f"[INIT] Material '{mat.name}' (id={mat.id}): retomando da página {resume_page}/{getattr(job, 'total_pages', '?')}")

                mat.processing_status = "pending"
                if job:
                    job.status = ProcessingJobStatus.PENDING.value if hasattr(ProcessingJobStatus, 'PENDING') else "pending"
                db.commit()

                from services.upload_queue import upload_queue, UploadQueueItem
                queue_item = UploadQueueItem(
                    upload_id=f"resume_{mat.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    file_path=resolved_file_path,
                    filename=mat.source_filename or mat.name,
                    material_id=mat.id,
                    name=mat.name,
                    user_id=None,
                    is_resume=True,
                    resume_from_page=resume_page,
                    existing_job_id=job.id if job else None,
                )
                upload_queue.add(queue_item)
                print(f"[INIT] Material '{mat.name}' enfileirado para retomada.")
            else:
                mat.processing_status = "failed"
                mat.processing_error = "Arquivo PDF não encontrado no disco nem no banco — faça upload novamente."
                if job:
                    job.status = "failed"
                    job.error_message = mat.processing_error
                db.commit()
                print(f"[INIT] Material '{mat.name}' (id={mat.id}): marcado como falho (PDF indisponível).")
    finally:
        db.close()



async def check_and_reindex_embeddings():
    """
    Verifica blocos aprovados sem embedding no pgvector e indexa automaticamente.
    Roda uma vez na inicialização como tarefa em background.
    Inclui retry com backoff exponencial e para após falhas consecutivas.
    Aguarda 30s para garantir que o init do banco completou.
    """
    await asyncio.sleep(30)
    
    MAX_CONSECUTIVE_ERRORS = 3
    BASE_DELAY = 0.5
    
    try:
        from database.database import SessionLocal
        from database.models import ContentBlock, Material, Product
        from sqlalchemy import text as sql_text
        
        db = SessionLocal()
        try:
            existing_doc_ids = set()
            rows = db.execute(sql_text("SELECT doc_id FROM document_embeddings")).fetchall()
            for row in rows:
                existing_doc_ids.add(row[0])
            
            blocks = db.query(ContentBlock).filter(
                ContentBlock.status.in_(['auto_approved', 'approved'])
            ).all()
            
            missing_blocks = []
            for block in blocks:
                expected_doc_id = f"product_block_{block.id}"
                if expected_doc_id not in existing_doc_ids:
                    missing_blocks.append(block)
            
            if not missing_blocks:
                total = db.execute(sql_text("SELECT COUNT(*) FROM document_embeddings")).scalar()
                print(f"[REINDEX] Todos os blocos aprovados já possuem embedding. Total: {total}")
                return
            
            print(f"[REINDEX] Encontrados {len(missing_blocks)} blocos aprovados sem embedding. Indexando...")
            
            from services.vector_store import get_vector_store
            vs = get_vector_store()
            
            indexed = 0
            errors = 0
            consecutive_errors = 0
            
            for block in missing_blocks:
                try:
                    material = db.query(Material).filter(Material.id == block.material_id).first()
                    product = None
                    if material and material.product_id:
                        product = db.query(Product).filter(Product.id == material.product_id).first()
                    
                    content = block.content or ""
                    if not content.strip():
                        continue
                    
                    global_context = ""
                    if product:
                        global_context = f"Produto: {product.name}"
                        if product.ticker:
                            global_context += f" ({product.ticker})"
                        if product.manager:
                            global_context += f" | Gestora: {product.manager}"
                    
                    if global_context:
                        enriched_content = f"{global_context}\n---\n{content}"
                    else:
                        enriched_content = content
                    
                    metadata = {
                        'product_name': product.name if product else '',
                        'product_ticker': product.ticker if product else '',
                        'gestora': product.manager if product else '',
                        'category': product.category if product else '',
                        'block_type': block.block_type or 'text',
                        'material_type': material.material_type if material else '',
                        'publish_status': material.publish_status if material else 'publicado',
                        'block_id': str(block.id),
                        'material_id': str(material.id) if material else '',
                        'title': material.name if material else '',
                        'source': f"{product.name if product else 'Desconhecido'} - {material.name if material else ''}",
                    }
                    
                    if hasattr(block, 'topic') and block.topic:
                        metadata['topic'] = block.topic
                    if hasattr(block, 'concepts') and block.concepts:
                        metadata['concepts'] = block.concepts
                    if hasattr(block, 'keywords') and block.keywords:
                        metadata['keywords'] = block.keywords
                    
                    if material and material.valid_until:
                        metadata['valid_until'] = material.valid_until.isoformat()
                    
                    doc_id = f"product_block_{block.id}"
                    vs.add_document(doc_id, enriched_content, metadata)
                    indexed += 1
                    consecutive_errors = 0
                    
                    if indexed % 10 == 0:
                        print(f"[REINDEX] Progresso: {indexed}/{len(missing_blocks)}...")
                    
                    await asyncio.sleep(BASE_DELAY)
                    
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    errors += 1
                    consecutive_errors += 1
                    
                    error_str = str(e)
                    is_quota_error = '429' in error_str or 'insufficient_quota' in error_str or 'rate_limit' in error_str.lower()
                    
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        if is_quota_error:
                            print(f"[REINDEX] API sem cota/rate limit após {consecutive_errors} tentativas consecutivas. "
                                  f"Parando re-indexação. {indexed} indexados até agora. "
                                  f"Restam {len(missing_blocks) - indexed - errors} blocos pendentes (serão indexados no próximo reinício).")
                        else:
                            print(f"[REINDEX] {consecutive_errors} erros consecutivos. Parando. {indexed} indexados, {errors} erros.")
                        break
                    
                    if is_quota_error:
                        wait_time = BASE_DELAY * (2 ** consecutive_errors)
                        print(f"[REINDEX] Rate limit/cota - aguardando {wait_time:.0f}s antes de tentar novamente... ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"[REINDEX] Erro ao indexar bloco {block.id}: {e}")
                        await asyncio.sleep(BASE_DELAY)
            else:
                print(f"[REINDEX] Concluído: {indexed} indexados, {errors} erros")
            
        finally:
            db.close()
    except asyncio.CancelledError:
        print("[REINDEX] Tarefa cancelada")
    except Exception as e:
        print(f"[REINDEX] Erro na re-indexação: {e}")


async def confirmation_timeout_scheduler():
    """
    Scheduler que verifica conversas aguardando confirmação a cada minuto.
    Envia mensagem de confirmação após 5 minutos sem resposta do assessor.
    """
    from database.database import SessionLocal
    from services.conversation_flow import check_pending_confirmations
    from services.whatsapp_client import zapi_client
    
    while True:
        try:
            await asyncio.sleep(60)
            
            db = SessionLocal()
            try:
                await check_pending_confirmations(db, zapi_client, timeout_minutes=5)
            except Exception as e:
                print(f"[SCHEDULER] Erro no scheduler de confirmação: {e}")
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[SCHEDULER] Erro inesperado: {e}")
            await asyncio.sleep(60)


async def revoked_tokens_cleanup_scheduler():
    """
    Remove tokens expirados da blacklist a cada hora.
    Tokens expirados não representam risco e podem ser removidos com segurança.
    """
    while True:
        try:
            await asyncio.sleep(3600)
            from core.security import cleanup_revoked_tokens
            await asyncio.to_thread(cleanup_revoked_tokens)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[CLEANUP] Erro no cleanup de tokens revogados: {e}")
            await asyncio.sleep(3600)


# Inicializa a aplicação FastAPI
app = FastAPI(
    title="Assessor IA - API",
    description="API para agente de IA de assessores financeiros com integração WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if not is_production() else None,
    redoc_url="/redoc" if not is_production() else None,
    openapi_url="/openapi.json" if not is_production() else None,
)

from core.security_middleware import setup_security
setup_security(app)

# Task #270 — Faz o FastAPI confiar nos headers X-Forwarded-Proto / X-Forwarded-Host
# injetados pelo proxy reverso (Replit, Railway, Nginx, etc.), garantindo que
# `request.base_url` retorne a URL pública HTTPS correta em vez de http://0.0.0.0:5000/.
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path

    if "/assets/" in path and (path.endswith(".js") or path.endswith(".css")):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path.startswith("/static/") and (
        path.endswith(".js") or path.endswith(".css") or
        path.endswith(".png") or path.endswith(".ico") or
        path.endswith(".woff2") or path.endswith(".woff")
    ):
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    elif "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"

    return response


_QUIET_PATHS = {
    "/api/integrations/zapi/health",
    "/api/conversations/bot-health",
    "/api/health/openai-status",
    "/api/auth/sse-token",
}

@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    import time, sys
    path = request.url.path
    quiet = path in _QUIET_PATHS
    start = time.time()
    if not quiet:
        sys.stdout.write(
            f"[ACCESS] {request.method} {path} "
            f"from {request.client.host if request.client else 'unknown'}\n"
        )
        sys.stdout.flush()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    if quiet and response.status_code < 400:
        return response
    output = sys.stderr if response.status_code >= 400 else sys.stdout
    output.write(f"[ACCESS] → {response.status_code} ({duration:.0f}ms) {request.method} {path}\n")
    output.flush()
    return response

# Configura templates Jinja2 (auto_reload=True evita cache de templates)
templates = Jinja2Templates(directory="frontend/templates")
templates.env.auto_reload = True

from fastapi.responses import FileResponse, Response
import httpx

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("frontend/static/favicon.ico")

@app.api_route("/__mockup/{path:path}", methods=["GET", "HEAD", "OPTIONS"], include_in_schema=False)
async def mockup_proxy(request: Request, path: str):
    """Proxy reverso para o servidor de mockup (dev only)."""
    target_url = f"http://localhost:23636/__mockup/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )
    except Exception:
        return Response(content=b"Mockup server unavailable", status_code=503)

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/derivatives-diagrams", StaticFiles(directory="static/derivatives_diagrams"), name="derivatives-diagrams")

# ========== Health Check ==========

_VERSION_CACHE: dict[str, str] | None = None


def _read_version_info() -> dict[str, str]:
    """Lê /app/VERSION e /app/BUILD_TIMESTAMP gravados pelo Dockerfile.

    Em ordem de prioridade:
      1. Arquivos /app/VERSION e /app/BUILD_TIMESTAMP (gravados no build).
      2. Env vars RAILWAY_GIT_COMMIT_SHA / RAILWAY_DEPLOYMENT_ID (Railway runtime).
      3. Strings 'unknown' como fallback inofensivo.

    Resultado é cacheado em memória — esses valores não mudam dentro de um
    mesmo container.
    """
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE

    import os as _os

    def _read(path: str) -> str:
        """Lê arquivo e trata 'unknown' como ausência de informação.

        O Dockerfile grava 'unknown' no /app/VERSION quando o build não
        recebe nem ARG GIT_SHA nem env RAILWAY_GIT_COMMIT_SHA. Se tratássemos
        'unknown' como valor válido, o fallback para env runtime nunca seria
        usado mesmo quando o Railway tem RAILWAY_GIT_COMMIT_SHA disponível
        no runtime — situação que o Architect (Task #179) pegou como bug.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                return "" if value.lower() in ("", "unknown") else value
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    commit = (
        _read("/app/VERSION")
        or _os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
        or "unknown"
    )
    built_at = (
        _read("/app/BUILD_TIMESTAMP")
        or _os.environ.get("RAILWAY_DEPLOYMENT_ID", "")
        or "unknown"
    )

    # Apenas commit_short é exposto publicamente para reduzir a superfície
    # de information disclosure (branch/environment ficam só nos logs internos).
    info = {
        "commit_short": (commit[:7] if commit and commit != "unknown" else "unknown"),
        "built_at": built_at,
    }

    _VERSION_CACHE = info
    return info


@app.get("/health")
async def health_check():
    """Health check endpoint — responde 200 imediatamente sem dependência de banco.

    Inclui informação de versão (commit SHA e timestamp de build) para que seja
    possível confirmar EM PRODUÇÃO qual revisão do código está rodando, sem
    precisar acessar o dashboard do Railway. Isso elimina a ambiguidade
    "deploy entrou ou não?" — bastando rodar `curl /health` e comparar o
    `commit_short` com o `git rev-parse --short HEAD` local.
    """
    info = _read_version_info()
    return {"status": "ok", **info}


# ========== Rotas de Páginas HTML ==========

@app.get("/")
async def root(request: Request):
    """Página inicial - redireciona ao dashboard se autenticado, senão mostra login."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        token = request.cookies.get("access_token")
        if token:
            from core.security import decode_token
            payload = decode_token(token)
            if payload:
                return RedirectResponse(url="/conversas", status_code=302)
        return templates.TemplateResponse("login.html", {"request": request})
    return JSONResponse({"status": "ok"})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/logout")
async def logout_page(request: Request):
    from core.security import decode_token, revoke_token
    access_token = request.cookies.get("access_token")
    refresh_token = request.cookies.get("refresh_token")

    for token, expected_type in [(access_token, "access"), (refresh_token, "refresh")]:
        if token:
            try:
                payload = decode_token(token, expected_type=expected_type)
                if payload:
                    from datetime import datetime
                    jti = payload.get("jti")
                    exp = payload.get("exp")
                    if jti and exp:
                        revoke_token(jti, datetime.utcfromtimestamp(exp))
            except Exception:
                pass

    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """
    Página de administração de usuários.
    Requer autenticação como admin.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    if payload.get("role") != "admin":
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("admin.html", {"request": request, "user_role": "admin"})


@app.get("/admin/rag-evasive", response_class=HTMLResponse)
async def admin_rag_evasive_page(request: Request):
    """
    Task #190 — Painel admin para triagem de respostas evasivas do RAG.

    Lista paginada com filtros (padrão evasivo, completeness_mode,
    had_kb_results, status de triagem) e ações para marcar como
    'resolvida' ou 'falso positivo'. Restrita ao role admin.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")

    if not token:
        return RedirectResponse(url="/login")

    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")

    if payload.get("role") != "admin":
        return RedirectResponse(url="/login?error=permission")

    return templates.TemplateResponse(
        "rag_evasive.html",
        {"request": request, "user_role": "admin"},
    )


@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request):
    """
    Página de gerenciamento de integrações.
    Requer autenticação como admin.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    if payload.get("role") != "admin":
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("integrations.html", {"request": request, "user_role": "admin"})


@app.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    """
    Dashboard de Insights para gestão de Renda Variável.
    Versão React. Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    import os
    react_insights_index = os.path.join(os.path.dirname(__file__), "frontend", "react-insights", "dist", "index.html")
    if os.path.exists(react_insights_index):
        with open(react_insights_index, "r") as f:
            content = f.read()
        return HTMLResponse(content=content)
    else:
        return templates.TemplateResponse("insights.html", {"request": request, "user_role": user_role})


# Monta arquivos estáticos do React Insights
react_insights_assets_path = os.path.join(os.path.dirname(__file__), "frontend", "react-insights", "dist", "assets")
if os.path.exists(react_insights_assets_path):
    app.mount("/insights/assets", StaticFiles(directory=react_insights_assets_path), name="react-insights-assets")

# Serve arquivos estáticos do React Insights
react_insights_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "react-insights", "dist")
if os.path.exists(react_insights_dist_path):
    @app.get("/insights/{filename:path}")
    async def serve_react_insights_static(filename: str, request: Request):
        import os
        file_path = os.path.join(react_insights_dist_path, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(file_path)
        return HTMLResponse(content="Not Found", status_code=404)


# ==============================================================================
# CENTRAL DE CUSTOS REACT APP
# ==============================================================================
react_costs_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "react-costs", "dist")
react_costs_assets_path = os.path.join(os.path.dirname(__file__), "frontend", "react-costs", "dist", "assets")

@app.get("/custos", response_class=HTMLResponse)
async def custos_page(request: Request):
    """
    Central de Custos - Monitoramento de gastos com APIs e serviços.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    if os.path.exists(react_costs_dist_path):
        dist_assets = os.path.join(react_costs_dist_path, "assets")
        css_file = ""
        js_file = ""
        if os.path.exists(dist_assets):
            for f in os.listdir(dist_assets):
                if f.endswith('.css'):
                    css_file = f
                elif f.endswith('.js'):
                    js_file = f
        
        if css_file and js_file:
            return templates.TemplateResponse(
                "custos_react.html",
                {"request": request, "user_role": user_role, "css_file": css_file, "js_file": js_file}
            )
    
    return HTMLResponse(content="<h1>Central de Custos não disponível</h1>", status_code=500)

if os.path.exists(react_costs_dist_path):
    @app.get("/custos/{filename:path}")
    async def serve_react_costs_static(filename: str, request: Request):
        file_path = os.path.join(react_costs_dist_path, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(
                file_path,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
            )
        return HTMLResponse(content="Not Found", status_code=404)


# ==============================================================================
# BASE DE CONHECIMENTO REACT APP
# ==============================================================================
react_knowledge_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "react-knowledge", "dist")
react_knowledge_assets_path = os.path.join(os.path.dirname(__file__), "frontend", "react-knowledge", "dist", "assets")

if os.path.exists(react_knowledge_assets_path):
    app.mount("/base-conhecimento/assets", StaticFiles(directory=react_knowledge_assets_path), name="react-knowledge-assets")

@app.get("/base-conhecimento", response_class=HTMLResponse)
async def base_conhecimento_page(request: Request):
    """
    Base de Conhecimento em React - integrado com menu admin.
    Acesso restrito a admin, gestao_rv e broker.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv", "broker"]:
        return RedirectResponse(url="/login?error=permission")
    
    if os.path.exists(react_knowledge_assets_path):
        assets = os.listdir(react_knowledge_assets_path)
        js_file = next((f for f in assets if f.endswith('.js')), None)
        css_file = next((f for f in assets if f.endswith('.css')), None)
        
        if js_file and css_file:
            return templates.TemplateResponse(
                "base_conhecimento_react.html",
                {
                    "request": request,
                    "user_role": user_role,
                    "js_file": js_file,
                    "css_file": css_file
                }
            )
    
    return HTMLResponse(content="<h1>App não encontrado. Execute npm run build em frontend/react-knowledge/</h1>", status_code=404)

if os.path.exists(react_knowledge_dist_path):
    @app.get("/base-conhecimento/{path:path}")
    async def serve_react_knowledge(path: str, request: Request):
        from core.security import decode_token
        token = request.cookies.get("access_token")
        
        if not token:
            return RedirectResponse(url="/login")
        
        payload = decode_token(token)
        if not payload:
            return RedirectResponse(url="/login")
        
        user_role = payload.get("role")
        if user_role not in ["admin", "gestao_rv", "broker"]:
            return RedirectResponse(url="/login?error=permission")
        
        file_path = os.path.join(react_knowledge_dist_path, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(file_path)
        
        if os.path.exists(react_knowledge_assets_path):
            assets = os.listdir(react_knowledge_assets_path)
            js_file = next((f for f in assets if f.endswith('.js')), None)
            css_file = next((f for f in assets if f.endswith('.css')), None)
            
            if js_file and css_file:
                return templates.TemplateResponse(
                    "base_conhecimento_react.html",
                    {
                        "request": request,
                        "user_role": user_role,
                        "js_file": js_file,
                        "css_file": css_file
                    }
                )
        return HTMLResponse(content="Not Found", status_code=404)


@app.get("/agent-brain", response_class=HTMLResponse)
async def agent_brain_page(request: Request):
    """
    Painel de controle do cérebro do agente.
    Permite configurar personalidade, modelo e parâmetros da IA.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("agent_brain.html", {"request": request, "user_role": user_role})


@app.get("/upload-inteligente", response_class=HTMLResponse)
async def upload_inteligente_redirect():
    """Redireciona para versão React do Upload Inteligente."""
    return RedirectResponse(url="/base-conhecimento/upload", status_code=302)


@app.get("/fila-revisao", response_class=HTMLResponse)
async def fila_revisao_page(request: Request):
    """
    Fila de Revisão - aprovação de conteúdo de alto risco.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("fila_revisao.html", {"request": request, "user_role": user_role})


@app.get("/documentos", response_class=HTMLResponse)
async def documentos_page(request: Request):
    """
    Página de Documentos - gerenciamento de documentos da base de conhecimento.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("documentos.html", {"request": request, "user_role": user_role})


@app.get("/assessores", response_class=HTMLResponse)
async def assessores_page(request: Request):
    """
    Página de gerenciamento da Base de Assessores.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("assessores.html", {"request": request, "user_role": user_role})


@app.get("/campanhas", response_class=HTMLResponse)
async def campanhas_page(request: Request):
    """
    Página de Campanhas Ativas para disparo em massa.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("campanhas.html", {"request": request, "user_role": user_role})


@app.get("/cadence-campaigns")
async def cadence_campaigns_redirect(request: Request):
    return RedirectResponse(url="/campanhas")


@app.get("/estruturas-campanha")
async def estruturas_campanha_redirect():
    return RedirectResponse(url="/campanhas?tab=estruturas", status_code=302)


@app.get("/teste-agente", response_class=HTMLResponse)
async def teste_agente_page(request: Request):
    """
    Página para testar o agente de IA.
    Simula conversa WhatsApp sem disparar mensagens reais.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("teste_agente.html", {"request": request, "user_role": user_role})


react_conversations_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "react-conversations", "dist")
react_conversations_assets_path = os.path.join(react_conversations_dist_path, "assets")

if os.path.exists(react_conversations_assets_path):
    app.mount("/conversas/assets", StaticFiles(directory=react_conversations_assets_path), name="conversas-assets")

@app.get("/conversas", response_class=HTMLResponse)
async def conversas_page(request: Request):
    """
    Página de gerenciamento de Conversas (React).
    Mostra histórico de todas as conversas e permite intervenção humana.
    Requer autenticação como admin, gestao_rv ou broker.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv", "broker"]:
        return RedirectResponse(url="/login?error=permission")
    
    if os.path.exists(react_conversations_assets_path):
        assets = os.listdir(react_conversations_assets_path)
        js_file = next((f for f in assets if f.endswith('.js')), None)
        css_file = next((f for f in assets if f.endswith('.css')), None)
        
        if js_file and css_file:
            return templates.TemplateResponse(
                "conversas_react.html",
                {
                    "request": request,
                    "user_role": user_role,
                    "js_file": js_file,
                    "css_file": css_file
                }
            )
    
    return templates.TemplateResponse("conversas.html", {"request": request, "user_role": user_role})


@app.get("/produtos", response_class=HTMLResponse)
async def produtos_page(request: Request):
    """
    Redireciona para o CMS de Produtos em /base-conhecimento.
    """
    return RedirectResponse(url="/base-conhecimento", status_code=301)


@app.get("/revisao", response_class=HTMLResponse)
async def revisao_page(request: Request):
    """
    Central de Revisão de Conteúdos.
    Revisa e aprova conteúdos extraídos automaticamente de PDFs.
    Requer autenticação como admin ou gestao_rv.
    """
    from core.security import decode_token
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("revisao.html", {"request": request, "user_role": user_role})


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "5000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
