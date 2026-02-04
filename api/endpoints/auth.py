"""
Endpoints de autenticação.
Gerencia login, logout, validação de tokens JWT e SSO Microsoft.
"""
import os
import secrets
import hashlib
import msal
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database.database import get_db
from database import crud
from core.security import create_access_token, decode_token

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")
MICROSOFT_AUTHORITY = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}" if MICROSOFT_TENANT_ID else None
MICROSOFT_SCOPES = ["User.Read", "email"]

_pending_oauth_states = {}

def get_msal_app():
    """Retorna uma instância do app MSAL se as credenciais estiverem configuradas."""
    if not all([MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT_ID]):
        return None
    return msal.ConfidentialClientApplication(
        MICROSOFT_CLIENT_ID,
        authority=MICROSOFT_AUTHORITY,
        client_credential=MICROSOFT_CLIENT_SECRET
    )

def generate_oauth_state() -> str:
    """Gera um state parameter único para proteção CSRF."""
    state = secrets.token_urlsafe(32)
    _pending_oauth_states[state] = True
    return state

def validate_oauth_state(state: str) -> bool:
    """Valida e consome um state parameter."""
    if state and state in _pending_oauth_states:
        del _pending_oauth_states[state]
        return True
    return False

def get_redirect_uri(request: Request) -> str:
    """Obtém a URI de redirecionamento considerando proxy headers."""
    proto = request.headers.get("X-Forwarded-Proto", "https")
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host") or str(request.base_url.hostname)
    if ":" in host:
        return f"{proto}://{host}/api/auth/microsoft/callback"
    port = request.url.port
    if port and port not in (80, 443):
        return f"{proto}://{host}:{port}/api/auth/microsoft/callback"
    return f"{proto}://{host}/api/auth/microsoft/callback"


class Token(BaseModel):
    """Schema para resposta de token."""
    access_token: str
    token_type: str


class LoginRequest(BaseModel):
    """Schema para requisição de login."""
    username: str
    password: str


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Endpoint de login.
    Recebe username e password, retorna um token JWT.
    """
    user = crud.authenticate_user(db, form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Cria o token JWT com informações do usuário
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": user.role
        }
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login-form")
async def login_form(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Endpoint de login via formulário HTML.
    Define um cookie com o token e redireciona para o painel.
    """
    form_data = await request.form()
    username = form_data.get("username")
    password = form_data.get("password")
    
    user = crud.authenticate_user(db, username, password)
    
    if not user:
        return RedirectResponse(
            url="/login?error=1",
            status_code=status.HTTP_302_FOUND
        )
    
    # Verifica se o usuário tem permissão para acessar o painel
    if user.role not in ["admin", "broker", "gestao_rv"]:
        return RedirectResponse(
            url="/login?error=permission",
            status_code=status.HTTP_302_FOUND
        )
    
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "role": user.role
        }
    )
    
    # Redireciona para o dashboard de insights
    redirect = RedirectResponse(url="/insights", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=86400,  # 24 horas
        samesite="lax"
    )
    return redirect


@router.post("/logout")
async def logout(response: Response):
    """Remove o cookie de autenticação."""
    redirect = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(key="access_token")
    return redirect


@router.get("/me")
async def get_current_user_endpoint(request: Request, db: Session = Depends(get_db)):
    """Retorna informações do usuário logado."""
    token = request.cookies.get("access_token")
    
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    user = crud.get_user_by_username(db, payload.get("sub"))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role
    }


@router.get("/sse-token")
async def get_sse_token(request: Request, db: Session = Depends(get_db)):
    """
    Retorna um token SSE de curta duração (5 minutos) para uso em conexões EventSource.
    Este token é separado do JWT principal e tem escopo limitado apenas para SSE.
    """
    from datetime import timedelta
    
    token = request.cookies.get("access_token")
    
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    sse_token = create_access_token(
        data={
            "sub": payload.get("sub"),
            "user_id": payload.get("user_id"),
            "role": payload.get("role"),
            "purpose": "sse"
        },
        expires_delta=timedelta(minutes=5)
    )
    
    return {"token": sse_token, "expires_in": 300}


async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Dependência que retorna o usuário autenticado."""
    from database.models import User
    token = request.cookies.get("access_token")
    
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )
    
    sub = payload.get("sub")
    user = crud.get_user_by_username_icase(db, sub)
    if not user and "@" in sub:
        user = crud.get_user_by_email_icase(db, sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    
    return user


def require_role(allowed_roles: list):
    """Factory para criar dependência que verifica se o usuário tem uma role permitida."""
    async def role_checker(
        request: Request,
        db: Session = Depends(get_db)
    ):
        user = await get_current_user(request, db)
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso negado"
            )
        return user
    return role_checker


async def get_current_user_sse(request: Request, db: Session = Depends(get_db)):
    """
    Dependência de autenticação específica para endpoints SSE.
    APENAS aceita token via query string com purpose='sse'.
    O token deve ser de curta duração, gerado por /api/auth/sse-token.
    """
    from database.models import User
    
    token = request.query_params.get("token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token SSE obrigatório. Use /api/auth/sse-token para obter um token."
        )
    
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )
    
    if payload.get("purpose") != "sse":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido para SSE. Use /api/auth/sse-token para obter o token correto."
        )
    
    sub = payload.get("sub")
    user = crud.get_user_by_username_icase(db, sub)
    if not user and "@" in sub:
        user = crud.get_user_by_email_icase(db, sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    
    return user


@router.get("/microsoft/enabled")
async def microsoft_sso_enabled():
    """Verifica se o SSO Microsoft está configurado."""
    enabled = all([MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT_ID])
    return {"enabled": enabled}


@router.get("/microsoft/login")
async def microsoft_login(request: Request):
    """Inicia o fluxo de login com Microsoft SSO."""
    msal_app = get_msal_app()
    
    if not msal_app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO Microsoft não configurado. Configure MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET e MICROSOFT_TENANT_ID."
        )
    
    redirect_uri = get_redirect_uri(request)
    state = generate_oauth_state()
    nonce = secrets.token_urlsafe(16)
    
    auth_url = msal_app.get_authorization_request_url(
        scopes=MICROSOFT_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
        prompt="select_account"
    )
    
    return RedirectResponse(url=auth_url)


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db)
):
    """Callback do SSO Microsoft após autenticação."""
    if error:
        return RedirectResponse(
            url=f"/login?error=microsoft&detail={error_description or error}",
            status_code=status.HTTP_302_FOUND
        )
    
    if not validate_oauth_state(state):
        return RedirectResponse(
            url="/login?error=microsoft&detail=Requisição inválida. Tente novamente.",
            status_code=status.HTTP_302_FOUND
        )
    
    if not code:
        return RedirectResponse(
            url="/login?error=microsoft&detail=Código de autorização não recebido",
            status_code=status.HTTP_302_FOUND
        )
    
    msal_app = get_msal_app()
    if not msal_app:
        return RedirectResponse(
            url="/login?error=microsoft&detail=SSO não configurado",
            status_code=status.HTTP_302_FOUND
        )
    
    redirect_uri = get_redirect_uri(request)
    
    try:
        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=MICROSOFT_SCOPES,
            redirect_uri=redirect_uri
        )
        
        if "error" in result:
            return RedirectResponse(
                url=f"/login?error=microsoft&detail={result.get('error_description', result.get('error'))}",
                status_code=status.HTTP_302_FOUND
            )
        
        id_token_claims = result.get("id_token_claims", {})
        email = id_token_claims.get("preferred_username") or id_token_claims.get("email")
        name = id_token_claims.get("name", "")
        
        if not email:
            return RedirectResponse(
                url="/login?error=microsoft&detail=Email não encontrado na conta Microsoft",
                status_code=status.HTTP_302_FOUND
            )
        
        print(f"[Microsoft SSO] Email retornado pela Microsoft: {email}")
        
        user = crud.get_user_by_email_icase(db, email)
        
        if not user:
            user = crud.get_user_by_username_icase(db, email)
        
        if not user:
            print(f"[Microsoft SSO] Usuário não encontrado para email: {email}")
            return RedirectResponse(
                url=f"/login?error=microsoft&detail=Usuário não encontrado. Solicite cadastro ao administrador.",
                status_code=status.HTTP_302_FOUND
            )
        
        print(f"[Microsoft SSO] Usuário encontrado: {user.username} (ID: {user.id})")
        
        if user.role not in ["admin", "broker", "gestao_rv"]:
            return RedirectResponse(
                url="/login?error=permission",
                status_code=status.HTTP_302_FOUND
            )
        
        access_token = create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id,
                "role": user.role,
                "auth_method": "microsoft_sso"
            }
        )
        
        redirect = RedirectResponse(url="/insights", status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=86400,
            samesite="lax"
        )
        return redirect
        
    except Exception as e:
        return RedirectResponse(
            url=f"/login?error=microsoft&detail=Erro na autenticação: {str(e)[:100]}",
            status_code=status.HTTP_302_FOUND
        )
