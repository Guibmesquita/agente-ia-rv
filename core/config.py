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
    # Railway sempre injeta RAILWAY_ENVIRONMENT ou RAILWAY_SERVICE_NAME em produção real
    is_railway = bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("RAILWAY_SERVICE_NAME")
        or os.getenv("RAILWAY_STATIC_URL")
    )
    # ENV=production deve ser setado explicitamente apenas em produção
    is_explicit_prod = os.getenv("ENV") == "production"
    # REPL_DEPLOYMENT/REPLIT_DEPLOYMENT eram usados antes mas eram setados
    # pelo workflow runner do Replit mesmo em dev, causando falsos positivos
    return is_railway or is_explicit_prod


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


def build_attachment_public_url(attachment_url: str) -> str | None:
    """
    Constrói a URL pública absoluta de um anexo de campanha para que o
    Z-API consiga baixá-lo.

    - Se `attachment_url` já for absoluta (http/https), devolve como está.
    - Se for relativa (ex.: "/uploads/attachments/xxx.pdf"), prefixa com a
      base pública (`APP_BASE_URL` ou `REPLIT_DOMAINS`/`REPLIT_DEV_DOMAIN`).
    - Se não houver `attachment_url` ou não for possível montar uma URL
      absoluta (sem domínio público configurado), devolve `None` para que
      o caller possa marcar o disparo como FALHADO em vez de tentar enviar
      um caminho inválido para o Z-API (que faz o disparo travar
      eternamente em "pendente").

    Esta função é a fonte única da verdade para a URL de anexo enviada à
    Z-API. Usada pelos 3 caminhos de disparo (SSE imediato, base de
    assessores, motor de cadência).
    """
    if not attachment_url:
        return None

    url = attachment_url.strip()
    if not url:
        return None

    if url.startswith(("http://", "https://", "data:")):
        return url

    if not url.startswith("/"):
        url = "/" + url

    base = get_public_base_url()
    if not base:
        return None

    return f"{base.rstrip('/')}{url}"


def resolve_attachment_for_send(attachment_url: str) -> str | None:
    """
    Resolve o anexo de campanha para envio via Z-API usando estratégia em cascata:

    1. Se já for URL absoluta (http/https/data:) → retorna como está.
    2. Se for caminho relativo E o arquivo existir no filesystem local
       → lê o arquivo, codifica em base64, retorna data: URI.
       (Z-API aceita base64 nativamente; elimina o problema de o Z-API
       não conseguir baixar de domínios internos como janeway.replit.dev.)
    3. Se o arquivo não existir localmente → tenta build_attachment_public_url.
    4. Se nenhuma estratégia funcionar → retorna None.
       (O caller deve marcar o disparo como failed imediatamente.)

    Por que base64?
    - O Z-API aceita data: URI nos campos document/image/video/audio.
    - O servidor que recebe o upload é o mesmo que processa o disparo,
      então o arquivo está sempre disponível no filesystem no momento imediato.
    - Para cadência (disparo diferido), o Railway Volume garante persistência.
    - Elimina a dependência de URL publicamente acessível: funciona em dev
      (Replit) e em Railway prod sem exigir APP_BASE_URL configurado.
    """
    import os
    import mimetypes
    import base64
    import logging

    _log = logging.getLogger(__name__)

    if not attachment_url:
        return None

    url = attachment_url.strip()
    if not url:
        return None

    if url.startswith(("http://", "https://", "data:")):
        return url

    if not url.startswith("/"):
        url = "/" + url

    local_path = url.lstrip("/")
    if os.path.isfile(local_path):
        try:
            mime_type, _ = mimetypes.guess_type(local_path)
            if not mime_type:
                ext = local_path.rsplit(".", 1)[-1].lower() if "." in local_path else ""
                mime_type = {
                    "pdf": "application/pdf",
                    "png": "image/png",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "gif": "image/gif",
                    "webp": "image/webp",
                    "mp4": "video/mp4",
                    "mp3": "audio/mpeg",
                    "ogg": "audio/ogg",
                }.get(ext, "application/octet-stream")
            with open(local_path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("ascii")
            _log.info(
                f"[ATTACHMENT] Arquivo '{local_path}' codificado em base64 "
                f"({mime_type}) para envio via Z-API."
            )
            return f"data:{mime_type};base64,{encoded}"
        except (OSError, IOError) as exc:
            _log.warning(
                f"[ATTACHMENT] Não foi possível ler '{local_path}' para base64: {exc}. "
                "Tentando URL pública como fallback."
            )

    return build_attachment_public_url(url)
