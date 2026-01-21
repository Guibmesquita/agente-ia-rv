"""
Endpoints para gerenciamento de integrações.
Permite configurar e testar conexões com serviços externos.
Apenas administradores podem acessar.

IMPORTANTE: Chaves de API sensíveis devem ser configuradas via Secrets do Replit,
não através desta interface. Esta API gerencia apenas configurações não-sensíveis.
"""
import os
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import httpx

from database.database import get_db
from database import crud
from core.security import decode_token

router = APIRouter(prefix="/api/integrations", tags=["Integrações"])


class SettingInput(BaseModel):
    """Schema para entrada de configuração."""
    key: str
    value: str
    is_secret: bool = False
    description: Optional[str] = None


class IntegrationCreate(BaseModel):
    """Schema para criação de integração."""
    name: str
    type: str
    is_active: bool = False


class IntegrationUpdate(BaseModel):
    """Schema para atualização de integração."""
    name: Optional[str] = None
    is_active: Optional[bool] = None


class SettingResponse(BaseModel):
    """Schema para resposta de configuração."""
    id: int
    key: str
    value: str
    is_secret: bool
    description: Optional[str]
    
    model_config = {"from_attributes": True}


class IntegrationResponse(BaseModel):
    """Schema para resposta de integração."""
    id: int
    name: str
    type: str
    is_active: bool
    settings: List[SettingResponse] = []
    
    model_config = {"from_attributes": True}


class IntegrationStatusResponse(BaseModel):
    """Schema para status de conexão."""
    integration_id: int
    name: str
    type: str
    is_connected: bool
    message: str
    env_vars_configured: Dict[str, bool]


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    """Verifica se o usuário atual é admin."""
    token = request.cookies.get("access_token")
    
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
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
    
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Apenas administradores."
        )
    
    return payload


def get_env_var_mapping():
    """
    Retorna o mapeamento de integrações para variáveis de ambiente.
    Chaves sensíveis devem ser configuradas via Secrets do Replit.
    """
    return {
        "openai": {
            "api_key": {"env": "OPENAI_API_KEY", "required": True, "is_secret": True},
            "model": {"env": "OPENAI_MODEL", "required": False, "default": "gpt-4"},
            "max_tokens": {"env": "OPENAI_MAX_TOKENS", "required": False, "default": "2000"},
            "temperature": {"env": "OPENAI_TEMPERATURE", "required": False, "default": "0.7"},
        },
        "notion": {
            "api_key": {"env": "NOTION_API_KEY", "required": True, "is_secret": True},
            "database_id": {"env": "NOTION_DATABASE_ID", "required": False},
            "parent_page_id": {"env": "NOTION_PARENT_PAGE_ID", "required": False},
        },
        "waha": {
            "api_url": {"env": "WAHA_API_URL", "required": True, "is_secret": False},
            "api_key": {"env": "WAHA_API_KEY", "required": False, "is_secret": True},
            "session_name": {"env": "WAHA_SESSION_NAME", "required": False, "default": "default"},
        },
    }


def check_env_vars(integration_type: str) -> Dict[str, bool]:
    """Verifica quais variáveis de ambiente estão configuradas."""
    mapping = get_env_var_mapping()
    
    if integration_type not in mapping:
        return {}
    
    result = {}
    for key, config in mapping[integration_type].items():
        env_name = config["env"]
        result[env_name] = bool(os.getenv(env_name))
    
    return result


@router.get("/", response_model=List[IntegrationResponse])
async def list_integrations(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Lista todas as integrações disponíveis."""
    integrations = crud.get_integrations(db)
    
    result = []
    for integration in integrations:
        settings = []
        for s in integration.settings:
            settings.append(SettingResponse(
                id=s.id,
                key=s.key,
                value="" if s.is_secret else s.value,
                is_secret=bool(s.is_secret),
                description=s.description
            ))
        
        result.append(IntegrationResponse(
            id=integration.id,
            name=integration.name,
            type=integration.type,
            is_active=bool(integration.is_active),
            settings=settings
        ))
    
    return result


@router.get("/env-mapping")
async def get_environment_mapping(
    current_user: dict = Depends(get_current_admin)
):
    """
    Retorna o mapeamento de variáveis de ambiente por tipo de integração.
    Indica quais variáveis estão configuradas.
    """
    mapping = get_env_var_mapping()
    result = {}
    
    for integration_type, settings in mapping.items():
        result[integration_type] = {
            "settings": {},
            "configured_count": 0,
            "required_count": 0
        }
        
        for key, config in settings.items():
            env_name = config["env"]
            is_configured = bool(os.getenv(env_name))
            
            result[integration_type]["settings"][key] = {
                "env_var": env_name,
                "is_configured": is_configured,
                "is_required": config.get("required", False),
                "is_secret": config.get("is_secret", False),
                "default": config.get("default"),
            }
            
            if is_configured:
                result[integration_type]["configured_count"] += 1
            if config.get("required", False):
                result[integration_type]["required_count"] += 1
    
    return result


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Busca uma integração pelo ID."""
    integration = crud.get_integration(db, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração não encontrada"
        )
    
    settings = []
    for s in integration.settings:
        settings.append(SettingResponse(
            id=s.id,
            key=s.key,
            value="" if s.is_secret else s.value,
            is_secret=bool(s.is_secret),
            description=s.description
        ))
    
    return IntegrationResponse(
        id=integration.id,
        name=integration.name,
        type=integration.type,
        is_active=bool(integration.is_active),
        settings=settings
    )


@router.put("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: int,
    data: IntegrationUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Atualiza uma integração (nome, status)."""
    integration = crud.update_integration(
        db, 
        integration_id, 
        **data.model_dump(exclude_unset=True)
    )
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração não encontrada"
        )
    
    settings = []
    for s in integration.settings:
        settings.append(SettingResponse(
            id=s.id,
            key=s.key,
            value="" if s.is_secret else s.value,
            is_secret=bool(s.is_secret),
            description=s.description
        ))
    
    return IntegrationResponse(
        id=integration.id,
        name=integration.name,
        type=integration.type,
        is_active=bool(integration.is_active),
        settings=settings
    )


@router.put("/{integration_id}/settings")
async def update_integration_settings(
    integration_id: int,
    settings: List[SettingInput],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """
    Atualiza configurações não-sensíveis de uma integração.
    Para chaves de API, configure via Secrets do Replit.
    """
    integration = crud.get_integration(db, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração não encontrada"
        )
    
    updated = []
    for setting in settings:
        if setting.is_secret:
            continue
        
        result = crud.create_or_update_setting(
            db,
            integration_id=integration_id,
            key=setting.key,
            value=setting.value,
            is_secret=False,
            description=setting.description
        )
        updated.append({
            "key": result.key,
            "updated": True
        })
    
    return {"updated_settings": updated}


@router.get("/{integration_id}/status", response_model=IntegrationStatusResponse)
async def check_integration_status(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Verifica o status de conexão de uma integração."""
    integration = crud.get_integration(db, integration_id)
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração não encontrada"
        )
    
    env_vars = check_env_vars(integration.type)
    is_connected = False
    message = "Verificando conexão..."
    
    try:
        if integration.type == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            org_id = os.getenv("OPENAI_ORG_ID")
            project_id = os.getenv("OPENAI_PROJECT_ID")
            if api_key:
                headers = {"Authorization": f"Bearer {api_key}"}
                if org_id:
                    headers["OpenAI-Organization"] = org_id
                if project_id:
                    headers["OpenAI-Project"] = project_id
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.openai.com/v1/models",
                        headers=headers,
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        model_count = len(data.get("data", []))
                        is_connected = True
                        message = f"Conexão estabelecida! {model_count} modelos disponíveis."
                    elif response.status_code == 401:
                        message = "Erro de autenticação. Verifique a OPENAI_API_KEY."
                    else:
                        message = f"Erro na API: {response.status_code}"
            else:
                message = "OPENAI_API_KEY não configurada. Configure em Secrets."
        
        elif integration.type == "notion":
            api_key = os.getenv("NOTION_API_KEY")
            if api_key:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "https://api.notion.com/v1/users/me",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Notion-Version": "2022-06-28"
                        },
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        is_connected = True
                        message = "Conexão estabelecida com sucesso!"
                    else:
                        message = f"Erro na API: {response.status_code}"
            else:
                message = "NOTION_API_KEY não configurada. Configure em Secrets."
        
        elif integration.type == "waha":
            api_url = os.getenv("WAHA_API_URL")
            api_key = os.getenv("WAHA_API_KEY")
            if api_url:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["X-Api-Key"] = api_key
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{api_url.rstrip('/')}/api/sessions",
                        headers=headers,
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        sessions = response.json()
                        session_count = len(sessions) if isinstance(sessions, list) else 0
                        is_connected = True
                        message = f"Conexão estabelecida! {session_count} sessão(ões) encontrada(s)."
                    elif response.status_code == 401:
                        message = "Erro de autenticação. Verifique a WAHA_API_KEY."
                    else:
                        message = f"Erro na API: {response.status_code}"
            else:
                message = "WAHA_API_URL não configurada."
        
        else:
            message = "Tipo de integração não suportado para teste."
    
    except httpx.TimeoutException:
        message = "Timeout na conexão. Verifique a URL."
    except httpx.RequestError as e:
        message = f"Erro de conexão: {str(e)}"
    except Exception as e:
        message = f"Erro: {str(e)}"
    
    return IntegrationStatusResponse(
        integration_id=integration.id,
        name=integration.name,
        type=integration.type,
        is_connected=is_connected,
        message=message,
        env_vars_configured=env_vars
    )


@router.post("/init-defaults")
async def init_default_integrations(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Inicializa as integrações padrão se não existirem."""
    crud.init_default_integrations(db)
    return {"message": "Integrações padrão inicializadas"}


class SecretInput(BaseModel):
    """Schema para entrada de secret."""
    env_var: str
    value: str


ALLOWED_SECRET_KEYS = {"OPENAI_API_KEY", "NOTION_API_KEY", "WAHA_API_URL", "NOTION_ROOT_PAGE_ID"}


@router.post("/save-secrets")
async def save_integration_secrets(
    secrets: List[SecretInput],
    current_user: dict = Depends(get_current_admin)
):
    """
    Salva secrets de integração como variáveis de ambiente.
    Apenas chaves específicas são permitidas por segurança.
    Os valores são armazenados em memória para a sessão atual.
    Para persistência permanente, configure em Tools > Secrets no Replit.
    """
    saved = []
    rejected = []
    
    for secret in secrets:
        if secret.env_var not in ALLOWED_SECRET_KEYS:
            rejected.append(secret.env_var)
            continue
        if secret.value and secret.value.strip():
            os.environ[secret.env_var] = secret.value.strip()
            saved.append(secret.env_var)
    
    message = f"{len(saved)} secret(s) configurado(s) com sucesso"
    if rejected:
        message += f". {len(rejected)} chave(s) não permitida(s) foram ignoradas"
    
    return {
        "message": message,
        "saved_keys": saved,
        "rejected_keys": rejected
    }
