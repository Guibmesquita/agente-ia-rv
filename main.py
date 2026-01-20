"""
Ponto de entrada da aplicação FastAPI.
Configura rotas, middleware e inicialização do banco de dados.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager

from database.database import engine, Base, SessionLocal
from database import crud
from api.endpoints import auth, users, tickets, whatsapp_webhook, integrations
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
    finally:
        db.close()
    
    yield
    
    # Cleanup (se necessário)


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

# Inclui routers da API
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tickets.router)
app.include_router(whatsapp_webhook.router)
app.include_router(integrations.router)


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
    Requer autenticação como admin ou broker.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")
    
    payload = decode_token(token)
    if not payload:
        return RedirectResponse(url="/login")
    
    if payload.get("role") not in ["admin", "broker"]:
        return RedirectResponse(url="/login?error=permission")
    
    return templates.TemplateResponse("kanban.html", {"request": request})


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
    
    return templates.TemplateResponse("admin.html", {"request": request})


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
    
    return templates.TemplateResponse("integrations.html", {"request": request})


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
