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

from database.database import engine, Base, SessionLocal
from database import crud
from api.endpoints import auth, users, tickets, whatsapp_webhook, integrations, analytics, agent_config, assessores, campaigns, knowledge, agent_test, conversations, central_mensagens, products, insights, search, trusted_sources
from core.security import decode_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gerencia o ciclo de vida da aplicação.
    Cria as tabelas do banco de dados na inicialização.
    """
    # Cria todas as tabelas
    Base.metadata.create_all(bind=engine)
    
    # Cria usuário admin padrão se não existir
    # Credenciais podem ser configuradas via variáveis de ambiente
    import os
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    
    db = SessionLocal()
    try:
        admin = crud.get_user_by_username(db, admin_username)
        if not admin:
            crud.create_user(
                db,
                username=admin_username,
                email=admin_email,
                password=admin_password,
                role="admin"
            )
            print(f"Usuário admin criado. Configure ADMIN_PASSWORD em produção!")
        
        crud.init_default_integrations(db)
        crud.init_default_categories(db)
        crud.init_default_agent_config(db)
        
        from database.models import Product
        system_product = db.query(Product).filter(Product.ticker == "__SYSTEM_UNASSIGNED__").first()
        if not system_product:
            system_product = Product(
                name="[Sistema] Documentos Não Vinculados",
                ticker="__SYSTEM_UNASSIGNED__",
                category="sistema",
                status="ativo",
                description="Produto de sistema para armazenar materiais sem produto vinculado. Não editar."
            )
            db.add(system_product)
            db.commit()
            print("Produto de sistema '__SYSTEM_UNASSIGNED__' criado.")
    finally:
        db.close()
    
    confirmation_task = asyncio.create_task(confirmation_timeout_scheduler())
    
    yield
    
    confirmation_task.cancel()
    try:
        await confirmation_task
    except asyncio.CancelledError:
        pass


async def confirmation_timeout_scheduler():
    """
    Scheduler que verifica conversas aguardando confirmação a cada minuto.
    Envia mensagem de confirmação após 5 minutos sem resposta do assessor.
    """
    from services.conversation_flow import check_pending_confirmations
    from integrations.zapi_client import get_zapi_client
    
    while True:
        try:
            await asyncio.sleep(60)
            
            db = SessionLocal()
            try:
                zapi_client = get_zapi_client()
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


# Inicializa a aplicação FastAPI
app = FastAPI(
    title="Assessor IA - API",
    description="API para agente de IA de assessores financeiros com integração WhatsApp",
    version="1.0.0",
    lifespan=lifespan
)

# Configura templates Jinja2
templates = Jinja2Templates(directory="frontend/templates")

# Monta arquivos estáticos
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/derivatives-diagrams", StaticFiles(directory="static/derivatives_diagrams"), name="derivatives-diagrams")

# Inclui routers da API
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tickets.router)
app.include_router(whatsapp_webhook.router)
app.include_router(integrations.router)
app.include_router(analytics.router)
app.include_router(agent_config.router)
app.include_router(assessores.router)
app.include_router(assessores.custom_fields_router)
app.include_router(assessores.upload_router)
app.include_router(campaigns.router)
app.include_router(knowledge.router)
app.include_router(agent_test.router)
app.include_router(conversations.router)
app.include_router(central_mensagens.router)
app.include_router(products.router)
app.include_router(insights.router)
app.include_router(search.router)
app.include_router(trusted_sources.router)


# ========== Rotas de Páginas HTML ==========

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redireciona para a página de login."""
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página de login."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/kanban", response_class=HTMLResponse)
async def kanban_page(request: Request):
    """
    Página do quadro Kanban.
    Requer autenticação como admin, broker ou gestao_rv.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "broker", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("kanban.html", {"request": request, "user_role": user_role})


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


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """
    Dashboard de analytics com indicadores de controle.
    Requer autenticação como admin, broker ou gestao_rv.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role not in ["admin", "broker", "gestao_rv"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("analytics.html", {"request": request, "user_role": user_role})


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


@app.get("/tailwind-test", response_class=HTMLResponse)
async def tailwind_test_page(request: Request):
    """
    Página de teste do Design System Tailwind.
    Acesso restrito a admins.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role != "admin":
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("tailwind_test.html", {"request": request, "user_role": user_role})


@app.get("/tailwind-test-knowledge", response_class=HTMLResponse)
async def tailwind_test_knowledge_page(request: Request):
    """
    POC de UX da Base de Conhecimento usando React + Tailwind.
    Acesso restrito a admins.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    user_role = payload.get("role")
    if user_role != "admin":
        return RedirectResponse(url="/login?error=permission")
    
    # Serve o build React
    import os
    react_build_path = os.path.join(os.path.dirname(__file__), "frontend", "react-poc", "dist", "index.html")
    if os.path.exists(react_build_path):
        with open(react_build_path, 'r') as f:
            content = f.read()
        return HTMLResponse(content=content)
    else:
        return HTMLResponse(content="<h1>POC não encontrada. Execute npm run build em frontend/react-poc/</h1>", status_code=404)


# Monta arquivos estáticos do React POC
import os
react_assets_path = os.path.join(os.path.dirname(__file__), "frontend", "react-poc", "dist", "assets")
if os.path.exists(react_assets_path):
    app.mount("/tailwind-test-knowledge/assets", StaticFiles(directory=react_assets_path), name="react-poc-assets")

# Serve vite.svg e outros arquivos na raiz do dist
react_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "react-poc", "dist")
if os.path.exists(react_dist_path):
    @app.get("/tailwind-test-knowledge/{filename:path}")
    async def serve_react_static(filename: str):
        import os
        file_path = os.path.join(react_dist_path, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            from fastapi.responses import FileResponse
            return FileResponse(file_path)
        return HTMLResponse(content="Not Found", status_code=404)


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


# ========== Health Check ==========

@app.get("/health")
async def health_check():
    """Endpoint de verificação de saúde da aplicação."""
    return {
        "status": "healthy",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
