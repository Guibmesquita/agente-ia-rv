"""
Configuração central da aplicação.
Carrega todas as variáveis de ambiente (secrets) necessárias.
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Chave secreta para JWT - obrigatória
    SECRET_KEY: str = os.getenv("SESSION_SECRET", "dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 horas
    
    # API Keys - serão carregadas das Secrets do Replit
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")
    NOTION_DATABASE_ID: str = os.getenv("NOTION_DATABASE_ID", "")
    
    # Configuração do Z-API (WhatsApp API)
    ZAPI_INSTANCE_ID: str = os.getenv("ZAPI_INSTANCE_ID", "")
    ZAPI_TOKEN: str = os.getenv("ZAPI_TOKEN", "")
    ZAPI_CLIENT_TOKEN: str = os.getenv("ZAPI_CLIENT_TOKEN", "")
    
    # Configuração do banco de dados (usa PostgreSQL do Replit ou SQLite local)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")
    
    # Configuração do ChromaDB
    CHROMA_PERSIST_DIRECTORY: str = "./chroma_db"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Retorna uma instância cacheada das configurações."""
    return Settings()
