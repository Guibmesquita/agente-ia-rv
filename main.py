"""
Ponto de entrada da aplicação FastAPI.
Configura rotas, middleware e inicialização do banco de dados.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager
import asyncio
import os

from database.database import engine, Base, SessionLocal
from database import crud
from core.security import decode_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação.
    Yield imediato para responder health checks rápido.
    Inicialização pesada (check_critical_dependencies, banco, seed, queue) roda em background.
    """
    background_tasks = []

    init_task = asyncio.create_task(run_init_background())
    background_tasks.append(init_task)
    
    reindex_task = asyncio.create_task(check_and_reindex_embeddings())
    background_tasks.append(reindex_task)
    
    confirmation_task = asyncio.create_task(confirmation_timeout_scheduler())
    background_tasks.append(confirmation_task)
    
    token_cleanup_task = asyncio.create_task(revoked_tokens_cleanup_scheduler())
    background_tasks.append(token_cleanup_task)
    
    yield
    
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def run_init_background():
    """Inicialização pesada em background: routers, dependency check, tabelas, admin, seed, upload queue."""
    def _import_endpoint_modules():
        from api.endpoints import (
            auth, users, tickets, whatsapp_webhook, integrations, agent_config,
            assessores, campaigns, knowledge, agent_test, conversations, products,
            insights, search, trusted_sources, costs, health
        )
        return (auth, users, tickets, whatsapp_webhook, integrations, agent_config,
                assessores, campaigns, knowledge, agent_test, conversations, products,
                insights, search, trusted_sources, costs, health)

    try:
        (auth, users, tickets, whatsapp_webhook, integrations, agent_config,
         assessores, campaigns, knowledge, agent_test, conversations, products,
         insights, search, trusted_sources, costs, health) = await asyncio.to_thread(_import_endpoint_modules)
        app.include_router(auth.router)
        app.include_router(users.router)
        app.include_router(tickets.router)
        app.include_router(whatsapp_webhook.router)
        app.include_router(integrations.router)
        app.include_router(agent_config.router)
        app.include_router(assessores.router)
        app.include_router(assessores.custom_fields_router)
        app.include_router(assessores.upload_router)
        app.include_router(campaigns.router)
        app.include_router(knowledge.router)
        app.include_router(agent_test.router)
        app.include_router(conversations.router)
        app.include_router(products.router)
        app.include_router(insights.router)
        app.include_router(search.router)
        app.include_router(trusted_sources.router)
        app.include_router(costs.router)
        app.include_router(health.router)
        print("[INIT] Routers registrados com sucesso.")
    except Exception as e:
        print(f"[INIT] Erro ao registrar routers: {e}")
        import traceback
        traceback.print_exc()

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
        from scripts.seed_production import run_seed
        await asyncio.to_thread(run_seed)
    except Exception as e:
        print(f"[SEED] Aviso: {e}")


def _apply_incremental_migrations():
    """
    Aplica migrações incrementais de schema que o create_all não cobre.
    Usa ADD COLUMN IF NOT EXISTS (idempotente no PostgreSQL) — seguro para rodar
    no startup de dev e produção quantas vezes for necessário.
    """
    from sqlalchemy import text as sql_text
    migrations = [
        # RetrievalLog — campos de observabilidade RAG (adicionados na sprint de melhorias RAG)
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS intent_detected VARCHAR(50)",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS entities_detected TEXT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS composite_score_max FLOAT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS web_search_used BOOLEAN DEFAULT FALSE",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS blocks_with_scores TEXT",
        "ALTER TABLE retrieval_logs ADD COLUMN IF NOT EXISTS is_comparative BOOLEAN DEFAULT FALSE",
    ]
    db = SessionLocal()
    try:
        for sql in migrations:
            db.execute(sql_text(sql))
        db.commit()
        print(f"[INIT] Migrações incrementais aplicadas: {len(migrations)} instruções")
    except Exception as e:
        db.rollback()
        print(f"[INIT] Aviso: erro em migração incremental: {e}")
    finally:
        db.close()


def _sync_init_database():
    """Operações síncronas de inicialização do banco (roda em thread separada)."""
    import os
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

        _resolve_orphan_materials(db)
    finally:
        db.close()


def _resume_interrupted_uploads():
    from datetime import datetime
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

            if job and job.file_path and os.path.exists(job.file_path):
                resume_page = job.last_processed_page or 0
                print(f"[INIT] Material '{mat.name}' (id={mat.id}): retomando da página {resume_page}/{job.total_pages}")

                mat.processing_status = "pending"
                job.status = ProcessingJobStatus.PENDING.value if hasattr(ProcessingJobStatus, 'PENDING') else "pending"
                db.commit()

                from services.upload_queue import upload_queue, UploadQueueItem
                queue_item = UploadQueueItem(
                    upload_id=f"resume_{mat.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    file_path=job.file_path,
                    filename=mat.source_filename or mat.name,
                    material_id=mat.id,
                    name=mat.name,
                    user_id=None,
                    is_resume=True,
                    resume_from_page=resume_page,
                    existing_job_id=job.id,
                )
                upload_queue.add(queue_item)
                print(f"[INIT] Material '{mat.name}' enfileirado para retomada.")
            else:
                mat.processing_status = "failed"
                mat.processing_error = "Processamento interrompido e arquivo não disponível para retomada"
                if job:
                    job.status = "failed"
                    job.error_message = mat.processing_error
                db.commit()
                print(f"[INIT] Material '{mat.name}' (id={mat.id}): marcado como falho (arquivo não disponível).")
    finally:
        db.close()



def _resolve_orphan_materials(db):
    import re as _re
    from database.models import Product, Material
    from services.document_metadata_extractor import TICKER_PATTERN, normalize_text

    placeholder_products = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").all()
    if not placeholder_products:
        return

    placeholder_ids = [p.id for p in placeholder_products]
    orphans = db.query(Material).filter(Material.product_id.in_(placeholder_ids)).all()

    if not orphans:
        for ph in placeholder_products:
            db.delete(ph)
        db.commit()
        print(f"[INIT] Removidos {len(placeholder_products)} produtos __SYSTEM_UNASSIGNED__ sem materiais.")
        return

    resolved = 0
    for mat in orphans:
        material_name = mat.name or ""
        ticker_match = TICKER_PATTERN.search(material_name.upper())
        ticker = f"{ticker_match.group(1)}{ticker_match.group(2)}" if ticker_match else None

        fund_name = material_name
        for pfx in ["Relatório gerencial ", "Relatório Gerencial ", "MP ", "Material Publicitário "]:
            if fund_name.startswith(pfx):
                fund_name = fund_name[len(pfx):]
                break
        fund_name = _re.sub(r'\s*\(\d+\)\s*$', '', fund_name).strip()
        fund_name = _re.sub(r'\s*\(vf\)\s*', ' ', fund_name, flags=_re.IGNORECASE).strip()

        target = None
        if ticker:
            target = db.query(Product).filter(
                Product.ticker == ticker,
                ~Product.id.in_(placeholder_ids)
            ).first()

        if not target and fund_name:
            norm = normalize_text(fund_name)
            for p in db.query(Product).filter(~Product.id.in_(placeholder_ids)).all():
                if normalize_text(p.name) == norm:
                    target = p
                    break

        if not target:
            target = Product(
                name=fund_name or material_name,
                ticker=ticker,
                category="fii",
                status="ativo",
                description="Produto criado automaticamente a partir de material órfão",
            )
            db.add(target)
            try:
                db.commit()
                db.refresh(target)
            except Exception:
                db.rollback()
                if ticker:
                    target = db.query(Product).filter(Product.ticker == ticker).first()
                if not target:
                    print(f"[INIT] Não foi possível criar produto para material '{material_name}' (id={mat.id})")
                    continue

        mat.product_id = target.id
        db.commit()
        resolved += 1
        print(f"[INIT] Material '{mat.name}' (id={mat.id}) → produto '{target.name}' (id={target.id})")

    for ph in placeholder_products:
        remaining = db.query(Material).filter(Material.product_id == ph.id).count()
        if remaining == 0:
            db.delete(ph)
            db.commit()

    if resolved > 0:
        from sqlalchemy import text as sql_text
        try:
            fix_result = db.execute(sql_text("""
                UPDATE document_embeddings de
                SET
                    product_ticker = p.ticker,
                    product_name   = p.name,
                    gestora        = COALESCE(p.manager, de.gestora),
                    category       = COALESCE(p.category, de.category)
                FROM content_blocks cb
                JOIN materials m ON cb.material_id = m.id
                JOIN products p ON m.product_id = p.id
                WHERE de.doc_id = 'product_block_' || cb.id::text
                  AND de.product_ticker = '__SYSTEM_UNASSIGNED__'
            """))
            embeddings_fixed = fix_result.rowcount
            db.commit()
            if embeddings_fixed > 0:
                print(f"[INIT] Corrigidos {embeddings_fixed} embeddings órfãos no vector store.")
            else:
                print(f"[INIT] Nenhum embedding órfão encontrado no vector store.")
        except Exception as e:
            db.rollback()
            print(f"[INIT] Erro ao corrigir embeddings órfãos: {e}")

    print(f"[INIT] Resolvidos {resolved}/{len(orphans)} materiais órfãos.")


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
    docs_url="/docs" if not bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT")) else None,
    redoc_url="/redoc" if not bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT")) else None,
    openapi_url="/openapi.json" if not bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT")) else None,
)

from core.security_middleware import setup_security
setup_security(app)

@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    import time, sys
    start = time.time()
    sys.stderr.write(
        f"[ACCESS] {request.method} {request.url.path} "
        f"from {request.client.host if request.client else 'unknown'} "
        f"headers={dict(request.headers)}\n"
    )
    sys.stderr.flush()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    sys.stderr.write(f"[ACCESS] → {response.status_code} ({duration:.0f}ms)\n")
    sys.stderr.flush()
    return response

# Configura templates Jinja2 (auto_reload=True evita cache de templates)
templates = Jinja2Templates(directory="frontend/templates")
templates.env.auto_reload = True

from fastapi.responses import FileResponse

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("frontend/static/favicon.ico")

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/derivatives-diagrams", StaticFiles(directory="static/derivatives_diagrams"), name="derivatives-diagrams")

# ========== Health Check ==========

@app.get("/health")
async def health_check():
    """Health check endpoint - responde 200 imediatamente sem dependência de banco."""
    return {"status": "ok"}


# ========== Rotas de Páginas HTML ==========

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Página inicial - serve a página de login diretamente."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """
    Página de administração de usuários.
    Requer autenticação como admin.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    if payload.get("role") != "admin":
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("admin.html", {"request": request, "user_role": "admin"})


@app.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request):
    """
    Página de gerenciamento de integrações.
    Requer autenticação como admin.
    """
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


@app.get("/teste-agente", response_class=HTMLResponse)
async def teste_agente_page(request: Request):
    """
    Página para testar o agente de IA.
    Simula conversa WhatsApp sem disparar mensagens reais.
    Requer autenticação como admin ou gestao_rv.
    """
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
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
