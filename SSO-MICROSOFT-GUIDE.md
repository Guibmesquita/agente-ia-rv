# Guia Completo: SSO Microsoft (Azure AD) para Aplicações Replit

> **Objetivo**: Implementar autenticação exclusiva via Microsoft SSO (OAuth 2.0 Authorization Code Flow) com MFA corporativo, JWT hardening, e conformidade OWASP Top 10 — pronto para produção no Replit.
>
> **Público-alvo**: Agentes IA Replit ou desenvolvedores implementando SSO Microsoft em projetos FastAPI hospedados no Replit.
>
> **Baseado em**: Implementação real em produção do projeto "Agente IA - RV" (Stevan), com todas as lições aprendidas após múltiplos deploys.

---

## Dois Cenários de Uso

Este guia cobre **dois cenários distintos**. Identifique o seu antes de começar:

| | Cenário A — Acesso Restrito | Cenário B — Ferramenta Interna |
|---|---|---|
| **Quem acessa?** | Apenas usuários pré-cadastrados por um admin | Qualquer pessoa com email corporativo do tenant |
| **Autorização** | Verificação de role (admin, user, etc.) | Pertencer ao tenant = acesso total |
| **Tabela de usuários** | Obrigatória, com roles e status | Opcional (para auditoria/tracking) |
| **Auto-criar usuário no login?** | NÃO — rejeita se não cadastrado | SIM — cria registro automaticamente |
| **Exemplo de uso** | Painel admin, CRM com permissões | Dashboard interno, ferramenta de equipe |

O código é marcado com **`[Cenário A]`** ou **`[Cenário B]`** onde diferem. Seções sem marcação se aplicam a ambos.

---

## Índice

1. [Visão Geral da Arquitetura](#1-visão-geral-da-arquitetura)
2. [Pré-requisitos: Azure AD App Registration](#2-pré-requisitos-azure-ad-app-registration)
3. [Variáveis de Ambiente (Secrets)](#3-variáveis-de-ambiente-secrets)
4. [Dependências Python](#4-dependências-python)
5. [Estrutura de Arquivos](#5-estrutura-de-arquivos)
6. [Implementação Passo a Passo](#6-implementação-passo-a-passo)
   - 6.1 [Configuração Central (`core/config.py`)](#61-configuração-central)
   - 6.2 [Modelos de Banco de Dados](#62-modelos-de-banco-de-dados)
   - 6.3 [Segurança e JWT (`core/security.py`)](#63-segurança-e-jwt)
   - 6.4 [Middleware de Segurança (`core/security_middleware.py`)](#64-middleware-de-segurança)
   - 6.5 [Endpoints de Autenticação (`api/endpoints/auth.py`)](#65-endpoints-de-autenticação)
   - 6.6 [Página de Login (Frontend)](#66-página-de-login-frontend)
   - 6.7 [Rota de Logout (`main.py`)](#67-rota-de-logout)
   - 6.8 [Registro de Middlewares (`main.py`)](#68-registro-de-middlewares)
7. [Token Management: Access + Refresh](#7-token-management-access--refresh)
8. [Segurança OWASP Top 10](#8-segurança-owasp-top-10)
9. [NÃO FAÇA — Anti-padrões e Erros Conhecidos](#9-não-faça--anti-padrões-e-erros-conhecidos)
10. [Deploy no Replit (Produção)](#10-deploy-no-replit-produção)
11. [Checklist de Produção](#11-checklist-de-produção)

---

## 1. Visão Geral da Arquitetura

```
┌──────────┐     1. GET /api/auth/microsoft/login     ┌──────────────┐
│          │ ────────────────────────────────────────▶ │              │
│  Browser │     2. Redirect para Azure AD            │  Sua App     │
│          │ ◀──────────────────────────────────────── │  (FastAPI)   │
└──────────┘                                          └──────────────┘
     │                                                       ▲
     │  3. Usuário autentica                                 │
     │     (+ MFA se configurado no tenant)                  │
     ▼                                                       │
┌──────────────────┐                                         │
│                  │  4. Redirect com authorization_code      │
│  Azure AD        │ ────────────────────────────────────────▶│
│  (Microsoft)     │                                         │
│                  │  5. App troca code por tokens (MSAL)     │
└──────────────────┘                                         │
                                                             │
     ┌───────────────────────────────────────────────────────┘
     │
     │  6. App extrai email do id_token_claims
     │
     │  [Cenário A] Busca usuário no banco local → rejeita se não encontrado
     │  [Cenário B] Aceita qualquer email do tenant → auto-cria se novo
     │
     │  7. Gera JWT interno (access_token + refresh_token)
     │  8. Seta cookies HttpOnly e redireciona para dashboard
     ▼
┌──────────┐
│ Sessão   │  access_token: 60min (cookie HttpOnly)
│ ativa    │  refresh_token: 7 dias (cookie HttpOnly)
│          │  Auto-refresh transparente via middleware
└──────────┘
```

**Fluxo**: OAuth 2.0 Authorization Code Flow

**Decisão arquitetural**: O token da Microsoft é usado **apenas para identificar o usuário**. Após o callback, a aplicação emite seus próprios JWTs internos. Isso desacopla a sessão da aplicação do token Microsoft e permite controle total sobre expiração, revogação e claims.

**Segurança do Cenário B**: No cenário de ferramenta interna, a proteção de acesso vem do **Azure AD configurado como Single Tenant**. Somente emails do diretório corporativo conseguem autenticar. Isso é validado no nível do provedor de identidade (Microsoft), não na aplicação. Nenhum email pessoal (gmail, outlook.com) passa.

---

## 2. Pré-requisitos: Azure AD App Registration

> **Aplica-se a ambos os cenários.** A configuração no Azure AD é idêntica. A escolha "Single tenant" é o que garante segurança no Cenário B.

### Passo a passo no Portal Azure

1. Acesse [portal.azure.com](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**

2. Configure o registro:
   - **Name**: Nome da sua aplicação (ex: "Minha App - SSO")
   - **Supported account types**: **"Accounts in this organizational directory only" (Single tenant)**
     > **CRÍTICO para Cenário B**: Esta configuração é o que garante que apenas emails corporativos do seu tenant acessem a aplicação. Se escolher "Multi-tenant" ou "Personal accounts", qualquer pessoa com conta Microsoft poderá se autenticar.
   - **Redirect URI**: Selecione "Web" e adicione:
     ```
     https://SEU-DOMINIO-REPLIT.replit.app/api/auth/microsoft/callback
     ```

3. Após criar, anote:
   - **Application (client) ID** → será `MICROSOFT_CLIENT_ID`
   - **Directory (tenant) ID** → será `MICROSOFT_TENANT_ID`

4. Vá em **Certificates & secrets** → **New client secret**:
   - **Description**: "Replit App Secret"
   - **Expires**: 24 months (máximo recomendado)
   - Copie o **Value** imediatamente → será `MICROSOFT_CLIENT_SECRET`
   - **ATENÇÃO**: Este valor só é exibido uma vez. Se perder, crie um novo.

5. Vá em **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - Marque: `User.Read`, `email`
   - Clique em **Grant admin consent** (requer admin do tenant)

6. Vá em **Authentication** → Verifique:
   - Redirect URI está correto
   - **ID tokens** está marcado em "Implicit grant and hybrid flows"
   - **Access tokens** NÃO precisa estar marcado (usamos Authorization Code Flow)

### Redirect URIs necessárias

Adicione **duas** URIs de redirect para funcionar tanto em desenvolvimento quanto em produção:

```
https://SEU-REPL-ID.replit.dev/api/auth/microsoft/callback     (desenvolvimento)
https://SEU-DOMINIO.replit.app/api/auth/microsoft/callback      (produção)
```

> **IMPORTANTE**: O domínio de desenvolvimento no Replit muda conforme o Repl. Verifique o domínio exato na aba "Webview" do Replit e adicione-o no Azure.

---

## 3. Variáveis de Ambiente (Secrets)

> **Aplica-se a ambos os cenários.** As mesmas 5 variáveis são necessárias.

Configure estas variáveis nos **Secrets** do Replit (Tools → Secrets):

| Variável | Descrição | Exemplo | Obrigatória |
|---|---|---|---|
| `MICROSOFT_CLIENT_ID` | Application ID do App Registration | `a1b2c3d4-e5f6-...` | Sim |
| `MICROSOFT_CLIENT_SECRET` | Client Secret gerado no passo 4 | `abc123~...` | Sim |
| `MICROSOFT_TENANT_ID` | Directory ID do Azure AD | `f1e2d3c4-...` | Sim |
| `SESSION_SECRET` | Chave para assinar JWTs (64+ chars hex) | Gerar com comando abaixo | Sim (produção) |
| `DATABASE_URL` | URL de conexão PostgreSQL | `postgresql://...` | Sim |

### Gerar SESSION_SECRET seguro

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

> **CRÍTICO**: Em produção, a aplicação **recusa iniciar** se `SESSION_SECRET` não estiver configurada ou usar valor padrão. Este é um comportamento intencional de segurança (fail-closed).

---

## 4. Dependências Python

> **Aplica-se a ambos os cenários.** As dependências são as mesmas.

```
# requirements.txt — dependências de autenticação e segurança
fastapi>=0.100.0
uvicorn>=0.23.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
msal>=1.24.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
slowapi>=0.1.9
pydantic-settings>=2.0.0
jinja2>=3.1.0
python-multipart>=0.0.6
```

Instale via Replit (menu Packages) ou via shell:
```bash
pip install msal python-jose[cryptography] passlib[bcrypt] slowapi pydantic-settings
```

---

## 5. Estrutura de Arquivos

> **Aplica-se a ambos os cenários.** A estrutura é idêntica — a diferença está no conteúdo dos arquivos.

```
projeto/
├── main.py                          # Entrypoint FastAPI + rotas de página
├── core/
│   ├── config.py                    # Settings centralizadas (Pydantic)
│   ├── security.py                  # JWT: criação, validação, revogação
│   └── security_middleware.py       # Middlewares: auth global, CSP, rate limit
├── api/
│   └── endpoints/
│       └── auth.py                  # Endpoints SSO Microsoft
├── database/
│   ├── database.py                  # Engine SQLAlchemy + get_db
│   ├── models.py                    # User, RevokedToken
│   └── crud.py                      # Operações CRUD de usuário
└── frontend/
    └── templates/
        └── login.html               # Página de login com botão Microsoft
```

---

## 6. Implementação Passo a Passo

### 6.1 Configuração Central

**Arquivo: `core/config.py`**

```python
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    SECRET_KEY: str = os.getenv("SESSION_SECRET", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "minha-app-api"
    JWT_AUDIENCE: str = "minha-app-frontend"

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

**Pontos-chave**:
- `SECRET_KEY` vem da variável `SESSION_SECRET` (não `SECRET_KEY` para evitar conflito com frameworks)
- `JWT_ISSUER` e `JWT_AUDIENCE` são verificados na decodificação do token — adiciona camada de validação
- `lru_cache` garante uma única instância de settings durante toda a vida da aplicação

---

### 6.2 Modelos de Banco de Dados

**No seu arquivo de models (ex: `database/models.py`)**:

#### [Cenário A] Modelo completo com roles e controle de acesso

```python
from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.sql import func
from database.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    first_name = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    role = Column(String(20), default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
```

> **Sobre o `hashed_password`**: Mesmo usando SSO exclusivo, mantemos o campo como `NOT NULL` com um valor placeholder (hash de string aleatória). Isso simplifica o modelo e permite reativar login local em emergências sem migração de schema.

#### [Cenário B] Modelo simplificado para ferramenta interna

```python
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from database.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    first_login_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

> **Cenário B — Por que ter tabela de usuários?** Não é obrigatória para autenticação (o Azure AD já garante que é da empresa), mas é útil para: (1) auditoria de quem acessou e quando; (2) associar dados ao usuário (preferências, ações); (3) analytics de uso. Se não precisa de nada disso, pode pular a tabela e colocar apenas o email no JWT.

#### Modelo RevokedToken (ambos os cenários)

```python
class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now())
```

**CRUD necessário** (`database/crud.py`):

```python
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func
from database.models import User
from typing import Optional


def get_user_by_email_icase(db: Session, email: str) -> Optional[User]:
    """Busca usuário por email (case-insensitive)."""
    return db.query(User).filter(
        sa_func.lower(User.email) == email.lower()
    ).first()


def get_user_by_username_icase(db: Session, username: str) -> Optional[User]:
    """[Cenário A] Busca por username (case-insensitive). Fallback quando email não encontra."""
    return db.query(User).filter(
        sa_func.lower(User.username) == username.lower()
    ).first()


def get_or_create_user(db: Session, email: str, name: str = "") -> User:
    """[Cenário B] Busca por email. Se não existe, cria automaticamente."""
    user = db.query(User).filter(
        sa_func.lower(User.email) == email.lower()
    ).first()

    if not user:
        user = User(email=email.lower(), name=name)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user
```

> **Por que busca case-insensitive?** O Azure AD pode retornar `joao.silva@empresa.com` ou `Joao.Silva@Empresa.com` dependendo de como o email foi cadastrado. A busca case-insensitive evita falhas de login por diferença de capitalização.

---

### 6.3 Segurança e JWT

**Arquivo: `core/security.py`**

```python
import os
import uuid
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import get_settings

security_logger = logging.getLogger("security")

settings = get_settings()

UNSAFE_KEYS = {"dev-secret-key-change-in-production", "change-me", "secret", ""}
IS_PRODUCTION = bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT"))

if settings.SECRET_KEY in UNSAFE_KEYS:
    if IS_PRODUCTION:
        raise RuntimeError(
            "FATAL: SECRET_KEY não está configurada ou usa valor padrão inseguro. "
            "Defina SESSION_SECRET nas Secrets do Replit com: "
            'python -c "import secrets; print(secrets.token_hex(64))"'
        )
    else:
        import warnings
        settings.SECRET_KEY = secrets.token_hex(32)
        warnings.warn(
            "SECRET_KEY usando valor gerado automaticamente para desenvolvimento. "
            "Configure SESSION_SECRET para produção.",
            stacklevel=2
        )

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Cria access token JWT com claims de segurança."""
    to_encode = data.copy()
    now = datetime.utcnow()
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "access",
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Cria refresh token JWT (apenas sub e user_id — mínimo de claims)."""
    to_encode = {
        "sub": data.get("sub"),
        "user_id": data.get("user_id"),
        "type": "refresh",
    }
    now = datetime.utcnow()
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def is_token_revoked(jti: str) -> bool:
    """
    Verifica se um token está na blacklist (revogado).
    FAIL-CLOSED: se a verificação falhar (DB offline), o token é tratado como revogado.
    Isso é intencional — preferimos negar acesso a permitir token potencialmente revogado.
    """
    if not jti:
        return False
    try:
        from database.database import SessionLocal
        from database.models import RevokedToken
        db = SessionLocal()
        try:
            revoked = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
            return revoked is not None
        finally:
            db.close()
    except Exception as e:
        security_logger.error(f"Erro ao verificar blacklist (fail-closed): {e}")
        return True


def revoke_token(jti: str, expires_at: datetime):
    """Insere um token na blacklist (usado no logout e rotação)."""
    try:
        from database.database import SessionLocal
        from database.models import RevokedToken
        db = SessionLocal()
        try:
            existing = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
            if not existing:
                db.add(RevokedToken(jti=jti, expires_at=expires_at))
                db.commit()
        finally:
            db.close()
    except Exception as e:
        security_logger.error(f"Erro ao revogar token: {e}")


def cleanup_revoked_tokens():
    """Remove tokens expirados da blacklist (housekeeping — rodar periodicamente)."""
    try:
        from database.database import SessionLocal
        from database.models import RevokedToken
        db = SessionLocal()
        try:
            deleted = db.query(RevokedToken).filter(
                RevokedToken.expires_at < datetime.utcnow()
            ).delete()
            db.commit()
            if deleted:
                security_logger.info(f"Cleanup: {deleted} tokens expirados removidos da blacklist")
        finally:
            db.close()
    except Exception as e:
        security_logger.error(f"Erro no cleanup de tokens revogados: {e}")


def decode_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """
    Decodifica e valida um JWT.
    Verifica: assinatura, expiração, issuer, audience, tipo, e blacklist.
    Retorna payload dict ou None se inválido.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            return None
        jti = payload.get("jti")
        if jti and is_token_revoked(jti):
            security_logger.warning(f"Token revogado usado: jti={jti}")
            return None
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    return decode_token(token, expected_type="refresh")
```

---

### 6.4 Middleware de Segurança

**Arquivo: `core/security_middleware.py`**

Este é o arquivo mais crítico. Ele implementa:
- **GlobalAuthMiddleware**: Intercepta todas as requests e verifica autenticação
- **SecurityHeadersMiddleware**: Injeta CSP, X-Frame-Options, etc.
- **Rate Limiting**: Previne brute-force
- **Account Lockout**: Bloqueia após tentativas excessivas
- **Auto-refresh de token**: Renova access_token transparentemente usando refresh_token

> **Cenário B**: O middleware funciona de forma idêntica em ambos os cenários. A diferença está no callback SSO (seção 6.5), não no middleware. Se o usuário tem um JWT válido, ele passa — independente de ter role ou não. No Cenário A, a verificação de role é feita nos endpoints específicos (não no middleware global).

```python
import os
import time
import json
import logging
import secrets
import traceback
from datetime import datetime
from collections import defaultdict
from typing import Set

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

from core.config import get_settings

settings = get_settings()

IS_PRODUCTION = bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT"))

security_logger = logging.getLogger("security")
if not security_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
        '"event": "%(message)s", "module": "%(module)s"}'
    ))
    security_logger.addHandler(handler)
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False


PUBLIC_PATHS: Set[str] = {
    "/",
    "/health",
    "/login",
    "/logout",
    "/favicon.ico",
    "/robots.txt",
}

PUBLIC_PREFIXES = (
    "/static/",
    "/api/auth/",
    "/api/health/",
    "/docs",
    "/openapi.json",
)

login_attempts = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 10
LOGIN_LOCKOUT_SECONDS = 900


def is_account_locked(identifier: str) -> bool:
    now = time.time()
    attempts = login_attempts.get(identifier, [])
    recent = [t for t in attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    login_attempts[identifier] = recent
    return len(recent) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(identifier: str, ip: str):
    login_attempts[identifier].append(time.time())
    security_logger.warning(json.dumps({
        "event": "login_failed",
        "identifier": identifier,
        "ip": ip,
        "attempts": len(login_attempts[identifier]),
        "timestamp": datetime.utcnow().isoformat(),
    }))


def record_successful_login(username: str, user_id: int, ip: str, method: str = "sso"):
    login_attempts.pop(username, None)
    security_logger.info(json.dumps({
        "event": "login_success",
        "username": username,
        "user_id": user_id,
        "ip": ip,
        "method": method,
        "timestamp": datetime.utcnow().isoformat(),
    }))


def record_security_event(event: str, **kwargs):
    """Registra evento de segurança com mascaramento automático de dados sensíveis."""
    data = {"event": event, "timestamp": datetime.utcnow().isoformat()}
    data.update(kwargs)
    for sensitive_key in ("password", "token", "secret", "secret_key", "api_key"):
        data.pop(sensitive_key, None)
    security_logger.info(json.dumps(data))


limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"

        csp_directives = [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: blob: https:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        return response


class GlobalAuthMiddleware(BaseHTTPMiddleware):
    """
    Intercepta todas as requests e verifica autenticação via JWT.
    
    Funciona igual nos Cenários A e B:
    - Se tem JWT válido → passa
    - Se não tem → redireciona para /login
    
    A diferença entre cenários está em COMO o JWT é gerado (callback SSO),
    não em como é verificado aqui.
    """
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS:
            return await call_next(request)

        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        from core.security import decode_token

        token = request.cookies.get("access_token")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            if path.startswith("/api/"):
                return JSONResponse(status_code=401, content={"detail": "Não autenticado"})
            return Response(status_code=302, headers={"Location": "/login"})

        payload = decode_token(token)
        if not payload:
            refresh_token = request.cookies.get("refresh_token")
            if refresh_token:
                refresh_payload = decode_token(refresh_token, expected_type="refresh")
                if refresh_payload:
                    try:
                        from core.security import create_access_token, revoke_token

                        new_access_token = create_access_token({
                            "sub": refresh_payload.get("sub"),
                            "user_id": refresh_payload.get("user_id"),
                        })

                        try:
                            from jose import jwt as jwt_lib
                            old_payload = jwt_lib.decode(
                                token,
                                options={"verify_signature": False, "verify_exp": False}
                            )
                            old_jti = old_payload.get("jti")
                            if old_jti:
                                old_exp = old_payload.get("exp")
                                if old_exp:
                                    revoke_token(old_jti, datetime.utcfromtimestamp(old_exp))
                        except Exception:
                            pass

                        response = await call_next(request)

                        is_prod = bool(
                            os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT")
                        )
                        response.set_cookie(
                            key="access_token",
                            value=new_access_token,
                            httponly=True,
                            secure=is_prod,
                            samesite="lax",
                            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                        )
                        return response
                    except Exception as e:
                        security_logger.error(f"Token refresh failed: {e}")

            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token inválido ou expirado"}
                )
            return Response(status_code=302, headers={"Location": "/login"})

        return await call_next(request)


def setup_security(app: FastAPI):
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        ip = get_remote_address(request)
        security_logger.warning(json.dumps({
            "event": "rate_limit_exceeded",
            "ip": ip,
            "path": str(request.url.path),
            "timestamp": datetime.utcnow().isoformat(),
        }))
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas requisições. Tente novamente em alguns minutos."},
            headers={"Retry-After": "60"}
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        security_logger.error(f"Database error on {request.url.path}: {type(exc).__name__}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor. Tente novamente."}
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_id = f"ERR-{int(time.time())}"
        security_logger.error(
            f"Unhandled exception [{error_id}] on {request.url.path}: "
            f"{type(exc).__name__}: {str(exc)[:200]}"
        )
        if not IS_PRODUCTION:
            traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Ocorreu um erro interno. Por favor, tente novamente.",
                "error_id": error_id
            }
        )

    allowed_origins = []
    if settings.ALLOWED_ORIGINS:
        allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]

    if not allowed_origins:
        repl_slug = os.getenv("REPL_SLUG", "")
        repl_owner = os.getenv("REPL_OWNER", "")
        if repl_slug and repl_owner:
            allowed_origins = [
                f"https://{repl_slug}-{repl_owner.lower()}.replit.app",
                f"https://{repl_slug}.{repl_owner.lower()}.repl.co",
            ]
        if not IS_PRODUCTION:
            allowed_origins.append("http://localhost:5000")
            allowed_origins.append("http://0.0.0.0:5000")

    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GlobalAuthMiddleware)
```

---

### 6.5 Endpoints de Autenticação

**Arquivo: `api/endpoints/auth.py`**

Este é onde os cenários A e B **mais diferem**. O fluxo SSO (login → Azure → callback) é idêntico, mas o **processamento do callback** muda:

```python
import os
import secrets
import logging
import msal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database.database import get_db
from database import crud
from core.security import (
    create_access_token, decode_token,
    create_refresh_token, decode_refresh_token, revoke_token
)
from core.security_middleware import (
    limiter, record_successful_login, record_security_event
)
from slowapi.util import get_remote_address

security_logger = logging.getLogger("security")

IS_PRODUCTION = bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT"))

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])

MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")
MICROSOFT_AUTHORITY = (
    f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}"
    if MICROSOFT_TENANT_ID else None
)
MICROSOFT_SCOPES = ["User.Read", "email"]

_pending_oauth_states = {}


def get_msal_app():
    """Retorna instância do app MSAL se as credenciais estiverem configuradas."""
    if not all([MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT_ID]):
        return None
    return msal.ConfidentialClientApplication(
        MICROSOFT_CLIENT_ID,
        authority=MICROSOFT_AUTHORITY,
        client_credential=MICROSOFT_CLIENT_SECRET
    )


def generate_oauth_state() -> str:
    """Gera state parameter único para proteção CSRF."""
    state = secrets.token_urlsafe(32)
    _pending_oauth_states[state] = True
    return state


def validate_oauth_state(state: str) -> bool:
    """Valida e consome um state parameter (uso único)."""
    if state and state in _pending_oauth_states:
        del _pending_oauth_states[state]
        return True
    return False


def get_redirect_uri(request: Request) -> str:
    """
    Constrói a URI de redirecionamento considerando proxy headers.
    No Replit, o proxy (metasidecar) encaminha com X-Forwarded-Proto e Host.
    """
    proto = request.headers.get("X-Forwarded-Proto", "https")
    host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or str(request.base_url.hostname)
    )
    if ":" in host:
        return f"{proto}://{host}/api/auth/microsoft/callback"
    port = request.url.port
    if port and port not in (80, 443):
        return f"{proto}://{host}:{port}/api/auth/microsoft/callback"
    return f"{proto}://{host}/api/auth/microsoft/callback"


@router.get("/microsoft/enabled")
async def microsoft_sso_enabled():
    enabled = all([MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT_ID])
    return {"enabled": enabled}


@router.get("/microsoft/login")
@limiter.limit("10/minute")
async def microsoft_login(request: Request):
    """Redireciona o usuário para a tela de login da Microsoft."""
    msal_app = get_msal_app()

    if not msal_app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO Microsoft não configurado. Configure MICROSOFT_CLIENT_ID, "
                   "MICROSOFT_CLIENT_SECRET e MICROSOFT_TENANT_ID."
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
@limiter.limit("10/minute")
async def microsoft_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    db: Session = Depends(get_db)
):
    """Processa o retorno da Microsoft após autenticação."""
    ip = get_remote_address(request)

    if error:
        record_security_event("sso_error", ip=ip, error=error)
        return RedirectResponse(
            url=f"/login?error=microsoft&detail={error_description or error}",
            status_code=status.HTTP_302_FOUND
        )

    if not validate_oauth_state(state):
        record_security_event("sso_invalid_state", ip=ip)
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
            record_security_event("sso_token_error", ip=ip, error=result.get("error"))
            return RedirectResponse(
                url=f"/login?error=microsoft&detail="
                    f"{result.get('error_description', result.get('error'))}",
                status_code=status.HTTP_302_FOUND
            )

        id_token_claims = result.get("id_token_claims", {})
        email = (
            id_token_claims.get("preferred_username")
            or id_token_claims.get("email")
        )
        name = id_token_claims.get("name", "")

        if not email:
            return RedirectResponse(
                url="/login?error=microsoft&detail=Email não encontrado na conta Microsoft",
                status_code=status.HTTP_302_FOUND
            )

        # ══════════════════════════════════════════════════════
        # AQUI OS CENÁRIOS DIVERGEM
        # Escolha UM dos blocos abaixo e delete o outro.
        # ══════════════════════════════════════════════════════

        # ──────────────────────────────────────────────────────
        # [CENÁRIO A] Acesso restrito — exige pré-cadastro
        # ──────────────────────────────────────────────────────
        user = crud.get_user_by_email_icase(db, email)

        if not user:
            user = crud.get_user_by_username_icase(db, email)

        if not user:
            record_security_event("sso_user_not_found", ip=ip, email=email)
            return RedirectResponse(
                url="/login?error=microsoft&detail="
                    "Usuário não encontrado. Solicite cadastro ao administrador.",
                status_code=status.HTTP_302_FOUND
            )

        allowed_roles = ["admin", "user"]
        if user.role not in allowed_roles:
            record_security_event(
                "sso_permission_denied", ip=ip,
                username=user.username, role=user.role
            )
            return RedirectResponse(
                url="/login?error=permission",
                status_code=status.HTTP_302_FOUND
            )

        token_data = {
            "sub": user.username,
            "user_id": user.id,
            "role": user.role,
            "auth_method": "microsoft_sso"
        }
        # ──────────────────────────────────────────────────────
        # FIM CENÁRIO A
        # ──────────────────────────────────────────────────────

        # ──────────────────────────────────────────────────────
        # [CENÁRIO B] Ferramenta interna — qualquer email do tenant
        # ──────────────────────────────────────────────────────
        # Descomente este bloco e comente/delete o Cenário A acima
        #
        # user = crud.get_or_create_user(db, email=email, name=name)
        #
        # token_data = {
        #     "sub": email.lower(),
        #     "user_id": user.id,
        #     "name": name,
        #     "auth_method": "microsoft_sso"
        # }
        #
        # security_logger.info(f"SSO login: {email} (user_id={user.id})")
        # ──────────────────────────────────────────────────────
        # FIM CENÁRIO B
        # ──────────────────────────────────────────────────────

        access_token = create_access_token(data=token_data)
        refresh_token = create_refresh_token(data=token_data)

        record_successful_login(
            token_data.get("sub", email),
            token_data.get("user_id", 0),
            ip,
            "microsoft_sso"
        )

        redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

        redirect.delete_cookie(key="access_token", path="/api/auth")
        redirect.delete_cookie(key="access_token", path="/api")

        redirect.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="lax",
            max_age=86400,
            path="/"
        )
        redirect.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            max_age=7 * 86400,
            samesite="lax",
            path="/api/auth",
            secure=IS_PRODUCTION
        )
        return redirect

    except Exception as e:
        record_security_event("sso_exception", ip=ip)
        return RedirectResponse(
            url="/login?error=microsoft&detail=Erro na autenticação. Tente novamente.",
            status_code=status.HTTP_302_FOUND
        )


@router.post("/logout")
async def api_logout(request: Request, response: Response):
    """Logout via API — revoga tokens e limpa cookies."""
    for cookie_name, token_type in [
        ("access_token", "access"),
        ("refresh_token", "refresh")
    ]:
        token = request.cookies.get(cookie_name)
        if token:
            try:
                payload = decode_token(token, expected_type=token_type)
                if payload:
                    jti = payload.get("jti")
                    exp = payload.get("exp")
                    if jti and exp:
                        revoke_token(jti, datetime.utcfromtimestamp(exp))
            except Exception:
                pass

    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    return {"message": "Logout realizado com sucesso"}


@router.post("/refresh")
async def refresh_access_token(request: Request, response: Response):
    """Gera novo access_token usando refresh_token válido."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token não encontrado")

    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Refresh token inválido ou expirado")

    new_access_token = create_access_token({
        "sub": payload.get("sub"),
        "user_id": payload.get("user_id"),
    })

    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=86400,
        path="/"
    )
    return {"message": "Token renovado com sucesso"}
```

---

### 6.6 Página de Login (Frontend)

**Arquivo: `frontend/templates/login.html`**

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Minha App</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #faf5f0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .login-container {
            background: white;
            padding: 48px 40px;
            border-radius: 16px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08);
            max-width: 440px;
            width: 100%;
            text-align: center;
        }
        h1 { font-size: 1.5rem; margin-bottom: 8px; }
        .subtitle {
            color: #888;
            font-size: 0.95rem;
            margin-bottom: 32px;
        }
        .btn-microsoft {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            width: 100%;
            padding: 14px;
            font-size: 1rem;
            background: #fff;
            border: 1px solid #8c8c8c;
            border-radius: 8px;
            color: #5e5e5e;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        .btn-microsoft:hover {
            background: #f3f3f3;
            border-color: #666;
        }
        .error-msg {
            background: #fef2f2;
            color: #dc2626;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 0.9rem;
        }
        .footer-text {
            margin-top: 24px;
            font-size: 0.85rem;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Minha Aplicação</h1>
        <p class="subtitle">Painel Administrativo</p>

        <div id="error-container" style="display: none;">
            <div class="error-msg" id="error-message"></div>
        </div>

        <a href="/api/auth/microsoft/login" class="btn-microsoft">
            <svg xmlns="http://www.w3.org/2000/svg" width="21" height="21" viewBox="0 0 21 21">
                <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
                <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
                <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
                <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
            </svg>
            Entrar com Microsoft
        </a>

        <p class="footer-text">Acesso restrito a usuários autorizados</p>
    </div>

    <script nonce="{{ request.state.csp_nonce }}">
        const params = new URLSearchParams(window.location.search);
        const errorType = params.get('error');
        const detail = params.get('detail');

        if (errorType) {
            const container = document.getElementById('error-container');
            const message = document.getElementById('error-message');
            container.style.display = 'block';

            if (errorType === 'permission') {
                message.textContent = 'Você não tem permissão para acessar esta aplicação.';
            } else if (errorType === 'microsoft') {
                message.textContent = detail || 'Erro na autenticação com Microsoft.';
            } else {
                message.textContent = 'Erro ao fazer login. Tente novamente.';
            }
        }
    </script>
</body>
</html>
```

**Pontos críticos**:
- O `<script>` usa `nonce="{{ request.state.csp_nonce }}"` — **obrigatório** para passar na CSP
- O link aponta diretamente para `/api/auth/microsoft/login` (GET)
- Erros do callback são exibidos via query params (`?error=...&detail=...`)

---

### 6.7 Rota de Logout

**No `main.py`** (rota GET — para funcionar como link na sidebar/navbar):

```python
@app.get("/logout")
async def logout_page(request: Request):
    """Logout via GET — para uso como link em sidebar/navbar."""
    from core.security import decode_token, revoke_token
    from datetime import datetime

    response = RedirectResponse(url="/login", status_code=302)

    for cookie_name, token_type, cookie_path in [
        ("access_token", "access", "/"),
        ("refresh_token", "refresh", "/api/auth"),
    ]:
        token = request.cookies.get(cookie_name)
        if token:
            try:
                payload = decode_token(token, expected_type=token_type)
                if payload:
                    jti = payload.get("jti")
                    exp = payload.get("exp")
                    if jti and exp:
                        revoke_token(jti, datetime.utcfromtimestamp(exp))
            except Exception:
                pass
        response.delete_cookie(key=cookie_name, path=cookie_path)

    return response
```

> **Por que GET e não POST?** O botão "Sair" na sidebar é um `<a href="/logout">`. Usar POST exigiria JavaScript para fazer fetch + redirect, adicionando complexidade desnecessária. O logout via GET é seguro porque: (1) não altera dados do usuário, apenas revoga sessão; (2) tokens são single-use via JTI; (3) a rota é idempotente.

---

### 6.8 Montagem Final do `main.py`

> **Aplica-se a ambos os cenários.** O `main.py` é idêntico — a diferença entre cenários está no callback SSO (seção 6.5).

**Arquivo: `main.py`** — copie este arquivo inteiro:

```python
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

templates = Jinja2Templates(directory="frontend/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.security_middleware import setup_security
    setup_security(app)

    from api.endpoints import auth
    app.include_router(auth.router)

    from database.database import init_database
    init_database()

    yield


app = FastAPI(title="Minha App", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/health")
async def health():
    """Health check — sem dependências, responde antes do lifespan completar."""
    return {"status": "ok"}


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/logout")
async def logout(request: Request):
    """Logout via GET — ver seção 6.7 para explicação."""
    from core.security import decode_token, revoke_token
    from datetime import datetime

    response = RedirectResponse(url="/login", status_code=302)
    for cookie_name, token_type, cookie_path in [
        ("access_token", "access", "/"),
        ("refresh_token", "refresh", "/api/auth"),
    ]:
        token = request.cookies.get(cookie_name)
        if token:
            try:
                payload = decode_token(token, expected_type=token_type)
                if payload:
                    jti = payload.get("jti")
                    exp = payload.get("exp")
                    if jti and exp:
                        revoke_token(jti, datetime.utcfromtimestamp(exp))
            except Exception:
                pass
        response.delete_cookie(key=cookie_name, path=cookie_path)
    return response


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
```

**Pontos críticos sobre a ordem**:
1. `/health` é registrado como rota do `app` — responde imediatamente, mesmo durante o lifespan
2. `setup_security(app)` dentro do lifespan registra os middlewares na ordem correta: `SecurityHeaders` antes de `GlobalAuth`
3. Routers (`auth.router`) são incluídos **depois** dos middlewares
4. `uvicorn.run()` sem `SO_REUSEPORT`, sem socket pré-criado — simples e compatível com o proxy Replit

---

## 7. Token Management: Access + Refresh

> **Aplica-se a ambos os cenários.** O mecanismo de tokens é idêntico. A única diferença é que no Cenário A o access_token contém `role`, enquanto no Cenário B não.

### Estratégia de Dois Tokens

| Token | Duração | Cookie Path | Contém | Propósito |
|---|---|---|---|---|
| `access_token` | 60 min | `/` | sub, user_id, role*, auth_method, jti | Autenticação de cada request |
| `refresh_token` | 7 dias | `/api/auth` | sub, user_id, jti | Gerar novos access_tokens |

> *`role` presente apenas no Cenário A

### Por que dois tokens?

1. **Segurança**: Se o access_token vazar, a janela de exposição é de 60 minutos
2. **UX**: O usuário não precisa refazer login SSO a cada hora — o middleware renova automaticamente
3. **Controle**: Podemos revogar access_tokens sem invalidar toda a sessão

### Fluxo de Auto-Refresh (Transparente)

```
Request chega → access_token expirado?
   ├─ Não → processa normalmente
   └─ Sim → refresh_token válido?
       ├─ Sim → gera novo access_token, seta cookie, processa request
       └─ Não → redireciona para /login (sessão expirada de verdade)
```

O usuário **nunca vê** o refresh acontecer. A request é processada normalmente e o novo cookie é setado na response.

### Revogação (Blacklist)

Quando o usuário faz logout:
1. O `jti` (UUID único) de ambos os tokens é inserido na tabela `revoked_tokens`
2. Cada `decode_token()` verifica a blacklist antes de aceitar o token
3. Se a verificação falhar (DB offline), o token é **rejeitado** (fail-closed)

### Limpeza automática

Tokens na blacklist têm `expires_at`. Após essa data, podem ser removidos com segurança via `cleanup_revoked_tokens()`. Recomenda-se rodar periodicamente (cron ou scheduler).

---

## 8. Segurança OWASP Top 10

Mapeamento de cada item do OWASP Top 10 (2021) e como está implementado:

### A01:2021 — Broken Access Control

**[Cenário A]**:
- **RBAC**: Verificação de `user.role` no callback SSO antes de permitir acesso
- Endpoints críticos podem ter decorators adicionais verificando role

**[Cenário B]**:
- **Tenant-level access control**: A autorização é delegada ao Azure AD. Configurar o App Registration como **Single Tenant** garante que apenas emails do diretório corporativo acessem. Isso é mais seguro que validar domínios de email no código, pois é gerenciado centralmente pelo provedor de identidade.
- Se precisar restringir ainda mais (ex: só certos departamentos), use **Azure AD Groups** e verifique a claim `groups` no `id_token_claims`.

**Ambos**:
- **Cookie Path restrito**: `refresh_token` só é enviado para `/api/auth` (mínimo privilégio)
- **CORS**: Origins explicitamente configuradas — não usa `*`

### A02:2021 — Cryptographic Failures
- **JWT assinado com HS256**: Usando `python-jose` com chave de 128+ chars hex
- **SECRET_KEY validada no startup**: Aplicação **recusa iniciar** em produção com chave insegura
- **Cookies Secure**: Flag `secure=True` em produção — tokens só trafegam via HTTPS
- **HttpOnly**: Tokens inacessíveis via JavaScript (previne XSS roubando sessão)

### A03:2021 — Injection
- **ORM (SQLAlchemy)**: Todas as queries via ORM com parâmetros vinculados — sem SQL raw
- **Jinja2 auto-escaping**: Templates escapam HTML automaticamente (previne XSS stored)

### A04:2021 — Insecure Design
- **Fail-closed**: Se a blacklist de tokens estiver indisponível, tokens são rejeitados (não aceitos)
- **State parameter**: OAuth flow usa `state` CSRF token de uso único
- **Token de uso único**: State é consumido e deletado após validação — replay impossível

### A05:2021 — Security Misconfiguration
- **Security Headers completos**:
  - `Content-Security-Policy` com nonce dinâmico
  - `X-Frame-Options: DENY` (anti-clickjacking)
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), microphone=(), camera=()`
  - `X-XSS-Protection: 1; mode=block`
- **CSP nonce**: Cada request gera nonce único — scripts inline sem nonce são bloqueados

### A06:2021 — Vulnerable and Outdated Components
- **Dependências específicas**: Versões mínimas definidas no `requirements.txt`
- **Auditoria periódica**: Rodar `pip audit` regularmente

### A07:2021 — Identification and Authentication Failures
- **SSO exclusivo**: Login interno desabilitado — não há senhas para atacar
- **MFA delegado**: A Microsoft gerencia MFA — se o tenant exige, é aplicado
- **Rate limiting**: 10 tentativas/minuto nos endpoints de login
- **Account lockout**: 10 falhas → bloqueio de 15 minutos
- **Busca case-insensitive**: Previne bypass por capitalização de email

### A08:2021 — Software and Data Integrity Failures
- **JWT com claims de integridade**: `iss`, `aud`, `type` são verificados na decodificação
- **Token type validation**: Access token não aceito como refresh (e vice-versa)
- **JTI único (UUIDv4)**: Impossível forjar um JTI que passe na blacklist

### A09:2021 — Security Logging and Monitoring Failures
- **Security logger dedicado**: Formato JSON estruturado para ingestão por SIEM
- **Eventos registrados**: `login_success`, `login_failed`, `sso_error`, `sso_user_not_found`, `sso_permission_denied`, `rate_limit_exceeded`, `token_revoked`
- **Mascaramento automático**: Campos como `password`, `token`, `api_key` são removidos antes de logar
- **Error ID**: Exceções não tratadas geram `error_id` único para rastreamento

### A10:2021 — Server-Side Request Forgery (SSRF)
- **Redirect URI construída internamente**: Não aceita redirect_uri do cliente — sempre calcula a partir dos headers do request
- **Azure AD como único destino externo**: Nenhuma request do servidor para URL fornecida pelo usuário

---

## 9. NÃO FAÇA — Anti-padrões e Erros Conhecidos

Estes são erros reais que cometemos e que custaram horas de debug:

### 9.1 Deploy

| NÃO FAÇA | POR QUÊ | FAÇA ISSO |
|---|---|---|
| Usar `deploymentTarget = "cloudrun"` (autoscale) se tiver processamento background | Containers escalam para zero após o response HTTP, matando workers em background | Use `deploymentTarget = "vm"` (Reserved VM) |
| Usar `SO_REUSEPORT` no uvicorn | Interfere com o proxy interno do Replit (metasidecar) e impede health checks. Confirmado após 6 deploys falhados | Use `uvicorn.run(app, host="0.0.0.0", port=5000)` simples |
| Criar socket pré-bound para uvicorn | Mesmo problema do `SO_REUSEPORT` — o metasidecar precisa ser o único listener | Deixe o uvicorn criar seu próprio socket |
| Confiar que `/health` responde durante startup pesado | Se o startup demora > 5s, o health check falha e o deploy é marcado como broken | Registre `/health` ANTES do lifespan, sem dependências |
| Logar para stdout em produção | Replit deployment logs capturam apenas stderr | Use `logging` com handler para stderr, ou `sys.stderr.write()` |

### 9.2 Autenticação

| NÃO FAÇA | POR QUÊ | FAÇA ISSO |
|---|---|---|
| **[Cenário A]** Auto-criar usuários no callback SSO | Qualquer pessoa com conta Microsoft do tenant poderia acessar — pode não ser desejado se há controle de acesso por role | Exija pré-cadastro por admin. SSO apenas identifica, não autoriza |
| **[Cenário B]** Exigir pré-cadastro para ferramenta interna | Cria atrito desnecessário — se é interno e qualquer funcionário pode usar, bloquear por falta de cadastro é UX ruim | Use `get_or_create_user()` no callback para auto-criar no primeiro login |
| Comparar emails com `==` (case-sensitive) | Azure AD pode retornar capitalização diferente | Use `LOWER()` no SQL ou `.lower()` no Python |
| Guardar o token Microsoft como sessão | Você perde controle sobre expiração e revogação | Emita seus próprios JWTs internos após validar o token Microsoft |
| Usar `REPLIT_DEV_DOMAIN` para URLs em produção | Esta variável só existe em desenvolvimento — em produção é vazia | Use `REPLIT_DOMAINS` (produção) com fallback para `REPLIT_DEV_DOMAIN` (dev) |
| Armazenar state OAuth em banco de dados | Adiciona latência e complexidade desnecessária | Use dict em memória (`_pending_oauth_states`). States expiram naturalmente em minutos |
| Esquecer de deletar cookies de paths antigos no callback | Cookies legados de paths diferentes (`/api`, `/api/auth`) ficam orphan e causam conflitos | Limpe cookies de paths antigos antes de setar novos |
| **[Cenário B]** Validar domínio do email no código (ex: `if not email.endswith("@empresa.com")`) | Frágil — domínios mudam, subdomínios são esquecidos, manutenção permanente | Configure **Single Tenant** no Azure AD. O provedor de identidade garante que só emails corporativos passam — zero manutenção no código |

### 9.3 Segurança

| NÃO FAÇA | POR QUÊ | FAÇA ISSO |
|---|---|---|
| Usar `SECRET_KEY` padrão em produção | Qualquer pessoa que leia o código pode forjar tokens válidos | Gere com `secrets.token_hex(64)` e guarde nos Secrets do Replit |
| Usar `fail-open` na blacklist de tokens | Se o banco cair, tokens revogados seriam aceitos | Use `fail-closed`: se a verificação falhar, rejeite o token |
| Colocar role/permissões no access_token sem re-validar | Se o admin revogar a role do usuário, o token antigo ainda teria a role antiga | Para operações críticas, re-busque o usuário no banco |
| Esquecer `httponly=True` nos cookies | JavaScript malicioso (XSS) poderia roubar os tokens | Sempre `httponly=True` — tokens não devem ser acessíveis via JS |
| Usar `samesite="none"` | Tokens seriam enviados em requests cross-site (CSRF) | Use `samesite="lax"` — permite redirects top-level mas bloqueia requests embedded |
| Adicionar `<script>` inline sem nonce | CSP bloqueia scripts inline sem nonce — a página quebra | Sempre adicione `nonce="{{ request.state.csp_nonce }}"` nos `<script>` |
| Retornar detalhes de exceção ao usuário | Expõe stack traces e informações internas | Retorne mensagens genéricas + error_id para rastreamento interno |
| Logar tokens, senhas ou API keys | Qualquer pessoa com acesso aos logs vê credenciais | Use `record_security_event()` com mascaramento automático de campos sensíveis |

### 9.4 Frontend

| NÃO FAÇA | POR QUÊ | FAÇA ISSO |
|---|---|---|
| Fazer o botão de logout usar `fetch()` + redirect manual | Adiciona complexidade, pode falhar silenciosamente, e não limpa estado do browser | Use `<a href="/logout">` simples — rota GET que faz tudo server-side |
| Confiar no `window.location.href` para detectar erros SSO | Query params podem ser encodados de formas inesperadas | Use `URLSearchParams` para parsing robusto |
| Esquecer de verificar se SSO está configurado antes de mostrar botão | O botão fica quebrado se as variáveis não existem | Chame `/api/auth/microsoft/enabled` e esconda o botão se não configurado |

---

## 10. Deploy no Replit (Produção)

> **Aplica-se a ambos os cenários.** A configuração de deploy é idêntica.

### Configuração do `.replit`

```toml
[deployment]
deploymentTarget = "vm"
run = ["python", "main.py"]
healthcheckPath = "/health"
```

### Health Check

O Replit faz health check com timeout de **5 segundos** no startup. Sua rota `/health` deve:
1. Estar registrada **fora do lifespan** (disponível imediatamente)
2. Retornar `{"status": "ok"}` sem dependências (sem DB, sem Redis, sem nada)
3. Estar na lista de `PUBLIC_PATHS` do middleware (sem autenticação)

### Lazy Loading (Se o startup for pesado)

Se sua aplicação demora para inicializar (migrações, imports pesados), use lazy loading:

```python
@app.get("/health")
async def health():
    return {"status": "ok"}

async def load_heavy_routers():
    import asyncio
    await asyncio.sleep(1)
    from api.endpoints import heavy_module
    app.include_router(heavy_module.router)
```

### Variáveis de Ambiente em Produção

O Replit usa variáveis de ambiente diferentes em desenvolvimento e produção:

| Variável | Desenvolvimento | Produção |
|---|---|---|
| `REPL_DEPLOYMENT` | Não existe | `"1"` |
| `REPLIT_DEPLOYMENT` | Não existe | `"1"` |
| `REPLIT_DEV_DOMAIN` | `"abc123.replit.dev"` | Não existe |
| `REPLIT_DOMAINS` | Não existe | `"meuapp.replit.app"` |

Use `IS_PRODUCTION = bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT"))` para detectar o ambiente.

### Redirect URI em Produção

Após o deploy, a URL muda. Certifique-se de adicionar a URI de produção no Azure AD App Registration:

```
https://SEU-APP.replit.app/api/auth/microsoft/callback
```

---

## 11. Checklist de Produção

Execute esta checklist antes de publicar:

### Secrets (Replit → Tools → Secrets)
- [ ] `SESSION_SECRET` configurada com valor seguro (64+ chars hex)
- [ ] `MICROSOFT_CLIENT_ID` configurada
- [ ] `MICROSOFT_CLIENT_SECRET` configurada
- [ ] `MICROSOFT_TENANT_ID` configurada
- [ ] `DATABASE_URL` apontando para PostgreSQL

### Azure AD
- [ ] Redirect URI de produção adicionada (`https://SEU-APP.replit.app/api/auth/microsoft/callback`)
- [ ] **Supported account types** = "Single tenant" (especialmente crítico no Cenário B)
- [ ] Permissões `User.Read` e `email` com admin consent
- [ ] Client Secret não expirado

### Código
- [ ] `/health` retorna 200 sem dependências
- [ ] `/health` está em `PUBLIC_PATHS` (sem auth)
- [ ] `deploymentTarget = "vm"` no `.replit`
- [ ] Todos os `<script>` têm `nonce="{{ request.state.csp_nonce }}"`
- [ ] Cookies usam `secure=IS_PRODUCTION`
- [ ] `SECRET_KEY` bloqueia startup se insegura em produção
- [ ] **[Cenário A]** Pelo menos um usuário admin pré-cadastrado no banco
- [ ] **[Cenário B]** `get_or_create_user()` implementado e testado

### Banco de Dados
- [ ] Tabela `users` existe
- [ ] Tabela `revoked_tokens` existe
- [ ] Busca de usuário é case-insensitive

### Teste Final
- [ ] Acessar `/` redireciona para `/login`
- [ ] Clicar "Entrar com Microsoft" abre tela da Microsoft
- [ ] Autenticar redireciona para a aplicação
- [ ] **[Cenário A]** Usuário não cadastrado mostra mensagem clara
- [ ] **[Cenário B]** Primeiro login de novo usuário cria registro automaticamente
- [ ] Botão "Sair" redireciona para `/login`
- [ ] Após logout, acessar `/` redireciona para `/login` (sessão destruída)
- [ ] **[Cenário B]** Testar com email de fora do tenant — deve ser bloqueado pelo Azure AD

---

## Referências

- [MSAL Python Documentation](https://learn.microsoft.com/en-us/entra/msal/python/)
- [OAuth 2.0 Authorization Code Flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- [OWASP Top 10 (2021)](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [python-jose](https://python-jose.readthedocs.io/)
- [Replit Deployments](https://docs.replit.com/hosting/deployments/about-deployments)
