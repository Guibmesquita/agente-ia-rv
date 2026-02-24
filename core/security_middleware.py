"""
Middleware de segurança centralizado.
Implementa: Security Headers, Rate Limiting, CORS, Auth Global, Error Handling, Logging.
"""
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
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "event": "%(message)s", "module": "%(module)s"}'
    ))
    security_logger.addHandler(handler)
    security_logger.setLevel(logging.INFO)
    security_logger.propagate = False


PUBLIC_PATHS: Set[str] = {
    "/",
    "/health",
    "/login",
    "/favicon.ico",
    "/robots.txt",
}

PUBLIC_PREFIXES = (
    "/static/",
    "/api/auth/",
    "/api/health/",
    "/api/whatsapp/",
    "/api/webhook/",
    "/docs",
    "/openapi.json",
    "/base-conhecimento",
    "/derivatives-diagrams/",
    "/custos",
    "/insights",
    "/conversas",
    "/documentos",
    "/central-mensagens",
    "/assessores",
    "/gestao-assessores",
    "/campanhas",
    "/configuracao",
    "/integracoes",
    "/knowledge/",
    "/agente",
    "/busca-web",
    "/fontes-confiaveis",
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


def record_successful_login(username: str, user_id: int, ip: str, method: str = "password"):
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
            f"script-src 'self' 'nonce-{nonce}' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: blob: https:",
            "connect-src 'self' https://api.openai.com",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives)

        return response


class GlobalAuthMiddleware(BaseHTTPMiddleware):
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
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Não autenticado"}
                )
            return Response(
                status_code=302,
                headers={"Location": "/login"}
            )

        payload = decode_token(token)
        if not payload:
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token inválido ou expirado"}
                )
            return Response(
                status_code=302,
                headers={"Location": "/login"}
            )

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
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )

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
