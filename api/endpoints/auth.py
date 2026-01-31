"""
Endpoints de autenticação.
Gerencia login, logout e validação de tokens JWT.
"""
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
    
    user = crud.get_user_by_username(db, payload.get("sub"))
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
    
    user = crud.get_user_by_username(db, payload.get("sub"))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )
    
    return user
