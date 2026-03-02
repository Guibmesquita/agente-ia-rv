"""
Configuração central da aplicação.
Carrega todas as variáveis de ambiente (secrets) necessárias.
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    SECRET_KEY: str = os.getenv("SESSION_SECRET", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ISSUER: str = "stevan-api"
    JWT_AUDIENCE: str = "stevan-frontend"
    
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "")
    
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    ZAPI_INSTANCE_ID: str = os.getenv("ZAPI_INSTANCE_ID", "")
    ZAPI_TOKEN: str = os.getenv("ZAPI_TOKEN", "")
    ZAPI_CLIENT_TOKEN: str = os.getenv("ZAPI_CLIENT_TOKEN", "")
    
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "")
    
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_db"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def is_production() -> bool:
    return bool(
        os.getenv("ENV") == "production"
        or os.getenv("REPL_DEPLOYMENT")
        or os.getenv("REPLIT_DEPLOYMENT")
    )


def get_public_domain() -> str:
    base_url = os.getenv("APP_BASE_URL", "")
    if base_url:
        return base_url.replace("https://", "").replace("http://", "").rstrip("/")
    domain = os.getenv("REPLIT_DOMAINS", os.getenv("REPLIT_DEV_DOMAIN", ""))
    if "," in domain:
        domain = domain.split(",")[0]
    return domain


def get_public_base_url() -> str:
    base_url = os.getenv("APP_BASE_URL", "")
    if base_url:
        return base_url.rstrip("/")
    domain = get_public_domain()
    if domain:
        return f"https://{domain}"
    return ""
