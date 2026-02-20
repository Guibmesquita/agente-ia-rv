"""
Módulo de segurança.
Contém funções para hashing de senhas e gerenciamento de tokens JWT.
"""
import os
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from core.config import get_settings

security_logger = logging.getLogger("security")

settings = get_settings()

UNSAFE_KEYS = {"dev-secret-key-change-in-production", "change-me", "secret", ""}
IS_PRODUCTION = bool(os.getenv("REPL_DEPLOYMENT") or os.getenv("REPLIT_DEPLOYMENT"))

if settings.SECRET_KEY in UNSAFE_KEYS:
    if IS_PRODUCTION:
        raise RuntimeError(
            "FATAL: SECRET_KEY não está configurada ou usa valor padrão inseguro. "
            "Defina SESSION_SECRET nas Secrets do Replit com: python -c \"import secrets; print(secrets.token_hex(64))\""
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
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "type": "access",
    })
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
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
    })
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> Optional[dict]:
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
        return payload
    except JWTError:
        return None


def decode_refresh_token(token: str) -> Optional[dict]:
    return decode_token(token, expected_type="refresh")
