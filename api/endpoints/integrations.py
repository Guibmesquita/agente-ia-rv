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
        "zapi": {
            "instance_id": {"env": "ZAPI_INSTANCE_ID", "required": True, "is_secret": False},
            "token": {"env": "ZAPI_TOKEN", "required": True, "is_secret": True},
            "client_token": {"env": "ZAPI_CLIENT_TOKEN", "required": True, "is_secret": True},
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
        if integration.type == "zapi":
            instance_id = os.getenv("ZAPI_INSTANCE_ID")
            token = os.getenv("ZAPI_TOKEN")
            client_token = os.getenv("ZAPI_CLIENT_TOKEN")
            if instance_id and token and client_token:
                headers = {
                    "Content-Type": "application/json",
                    "Client-Token": client_token
                }
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://api.z-api.io/instances/{instance_id}/token/{token}/status",
                        headers=headers,
                        timeout=10.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        connected = data.get("connected", False)
                        if connected:
                            is_connected = True
                            message = f"Conexão estabelecida! WhatsApp conectado."
                        else:
                            message = f"Instância encontrada mas WhatsApp desconectado. Status: {data.get('error', 'desconhecido')}"
                    elif response.status_code == 401:
                        message = "Erro de autenticação. Verifique o Token ou Client-Token."
                    else:
                        message = f"Erro na API: {response.status_code}"
            else:
                missing = []
                if not instance_id: missing.append("ZAPI_INSTANCE_ID")
                if not token: missing.append("ZAPI_TOKEN")
                if not client_token: missing.append("ZAPI_CLIENT_TOKEN")
                message = f"Variáveis não configuradas: {', '.join(missing)}"
        
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


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin)
):
    """Exclui uma integração e seus settings associados (cascade)."""
    from database.models import Integration
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integração não encontrada"
        )

    name = integration.name
    db.delete(integration)
    db.commit()

    return {"message": f"Integração '{name}' excluída com sucesso", "deleted_id": integration_id}


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


ALLOWED_SECRET_KEYS = {"ZAPI_INSTANCE_ID", "ZAPI_TOKEN", "ZAPI_CLIENT_TOKEN"}


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


# ─────────────────────────────────────────────────────────────────────────────
# Task #232 — Helpers e Pydantic models para CRUD de canais Z-API
# ─────────────────────────────────────────────────────────────────────────────

class ZAPIChannelCreate(BaseModel):
    name: str
    label: Optional[str] = None
    instance_id: str
    token: str
    client_token: Optional[str] = None
    phone_number: Optional[str] = None
    description: Optional[str] = None


class ZAPIChannelUpdate(BaseModel):
    name: Optional[str] = None
    label: Optional[str] = None
    instance_id: Optional[str] = None
    token: Optional[str] = None
    client_token: Optional[str] = None
    phone_number: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _build_webhook_url_suggested(request: Request, channel_id: int) -> str:
    """Monta a URL de webhook sugerida para o canal a partir do host da requisição."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/whatsapp/webhook/{channel_id}"


def _auth_zapi_channel(request: Request) -> dict:
    """Valida autenticação (admin/gestao_rv) e retorna user_data."""
    token_data = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token_data:
        token_data = request.cookies.get("access_token", "")
    user_data = decode_token(token_data)
    if not user_data or user_data.get("role") not in ("admin", "gestao_rv"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    return user_data


@router.get("/zapi/health")
async def zapi_health_check(request: Request):
    """
    Retorna o estado em cache da Z-API (atualizado em background a cada 5 minutos).
    Nunca faz chamada HTTP direta à Z-API neste endpoint.
    """
    from services.dependency_check import get_zapi_status_cache

    cached = get_zapi_status_cache()
    return cached


@router.get("/zapi/channels")
async def list_zapi_channels(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #223 — Lista todos os canais Z-API configurados.

    Retorna para cada canal:
    - Credenciais mascaradas (nunca expõe tokens completos).
    - `connectivity_status`: sonda Z-API em tempo real ("connected" / "disconnected" / "unreachable").
    - `assessor_count`: quantidade de assessores vinculados ao canal.
    - `unidades_assigned`: lista de unidades mapeadas para o canal.

    Acesso restrito a admin e gestão RV.
    """
    import asyncio
    from database.models import ZAPIChannel, UnidadeChannelMapping, Assessor
    from services.whatsapp_client import ZAPIClient
    from sqlalchemy import func

    token_data = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token_data:
        token_data = request.cookies.get("access_token", "")
    user_data = decode_token(token_data)
    if not user_data or user_data.get("role") not in ("admin", "gestao_rv"):
        raise HTTPException(status_code=403, detail="Acesso negado")

    channels = db.query(ZAPIChannel).order_by(ZAPIChannel.id).all()
    mappings = db.query(UnidadeChannelMapping).all()

    mapping_by_channel: Dict[int, List[str]] = {}
    for m in mappings:
        mapping_by_channel.setdefault(m.channel_id, []).append(m.unidade)

    # Contagem de assessores por canal (uma query agregada)
    assessor_counts_rows = (
        db.query(Assessor.channel_id, func.count(Assessor.id))
        .filter(Assessor.channel_id.isnot(None))
        .group_by(Assessor.channel_id)
        .all()
    )
    assessor_count_by_channel: Dict[int, int] = {row[0]: row[1] for row in assessor_counts_rows}

    def _mask(value: Optional[str]) -> Optional[str]:
        if not value or len(value) < 8:
            return None
        return value[:4] + "****" + value[-4:]

    # Sonda conectividade de cada canal ativo em paralelo (timeout 5s por canal)
    active_channels = [ch for ch in channels if ch.is_active]

    async def _probe(ch: ZAPIChannel) -> str:
        client = ZAPIClient(
            instance_id=ch.instance_id,
            token=ch.token,
            client_token=ch.client_token,
        )
        return await client.check_connectivity(timeout=5.0)

    if active_channels:
        statuses = await asyncio.gather(*[_probe(ch) for ch in active_channels], return_exceptions=True)
        connectivity: Dict[int, str] = {}
        for ch, result in zip(active_channels, statuses):
            connectivity[ch.id] = result if isinstance(result, str) else "unreachable"
    else:
        connectivity = {}

    return {
        "channels": [
            {
                "id": ch.id,
                "name": ch.name,
                "label": ch.label,
                "phone_number": ch.phone_number,
                "instance_id": _mask(ch.instance_id),
                "token_masked": _mask(ch.token),
                "client_token_configured": bool(ch.client_token),
                "is_legacy": ch.is_legacy,
                "is_active": ch.is_active,
                "webhook_url": ch.webhook_url,
                "description": ch.description,
                "connectivity_status": connectivity.get(ch.id, "unknown"),
                "assessor_count": assessor_count_by_channel.get(ch.id, 0),
                "unidades_assigned": mapping_by_channel.get(ch.id, []),
                "unidades_mapeadas": mapping_by_channel.get(ch.id, []),  # alias para compatibilidade
                "webhook_url_suggested": _build_webhook_url_suggested(request, ch.id),
                "created_at": ch.created_at.isoformat() if ch.created_at else None,
                "updated_at": ch.updated_at.isoformat() if ch.updated_at else None,
            }
            for ch in channels
        ],
        "total": len(channels),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task #232 — CRUD de canais Z-API
# ─────────────────────────────────────────────────────────────────────────────

class ZAPICredentialsTest(BaseModel):
    instance_id: str
    token: str
    client_token: Optional[str] = None


@router.post("/zapi/channels/test-credentials")
async def test_zapi_channel_credentials(
    data: ZAPICredentialsTest,
    request: Request,
):
    """
    Task #232 — Testa credenciais Z-API sem persistir canal.
    Útil para validação no modal de criação antes de salvar.
    """
    _auth_zapi_channel(request)

    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient(
        instance_id=data.instance_id,
        token=data.token,
        client_token=data.client_token,
    )
    connectivity = await client.check_connectivity(timeout=8.0)

    messages = {
        "connected": "Instância conectada e autenticada com sucesso.",
        "disconnected": "Instância respondeu, mas não está autenticada. Escaneie o QR Code no painel Z-API.",
        "unreachable": "Instância inacessível. Verifique as credenciais e se a instância está ativa no Z-API.",
    }
    return {
        "connectivity_status": connectivity,
        "message": messages.get(connectivity, "Status desconhecido."),
    }


@router.post("/zapi/channels", status_code=201)
async def create_zapi_channel(
    data: ZAPIChannelCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #232 — Cria um novo canal Z-API.
    Testa conectividade das credenciais antes de persistir (não bloqueia em caso de
    instância ainda não conectada — apenas informa o status).
    Retorna o canal criado com webhook_url_suggested.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel
    from services.whatsapp_client import ZAPIClient

    client = ZAPIClient(
        instance_id=data.instance_id,
        token=data.token,
        client_token=data.client_token,
    )
    connectivity = await client.check_connectivity(timeout=8.0)

    channel = ZAPIChannel(
        name=data.name,
        label=data.label or data.name,
        instance_id=data.instance_id,
        token=data.token,
        client_token=data.client_token,
        phone_number=data.phone_number,
        description=data.description,
        is_legacy=False,
        is_active=True,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)

    webhook_url = _build_webhook_url_suggested(request, channel.id)
    channel.webhook_url = webhook_url
    db.commit()

    return {
        "id": channel.id,
        "name": channel.name,
        "label": channel.label,
        "phone_number": channel.phone_number,
        "instance_id": data.instance_id[:4] + "****" if len(data.instance_id) >= 8 else "****",
        "is_legacy": channel.is_legacy,
        "is_active": channel.is_active,
        "connectivity_status": connectivity,
        "webhook_url_suggested": webhook_url,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


@router.patch("/zapi/channels/{channel_id}")
async def update_zapi_channel(
    channel_id: int,
    data: ZAPIChannelUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #232 — Atualiza um canal Z-API.
    Canais legados: apenas label, phone_number, description e is_active.
    Canais normais: todos os campos.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    if channel.is_legacy:
        # Credenciais do canal legado são gerenciadas via variáveis de ambiente
        if data.label is not None:
            channel.label = data.label
        if data.phone_number is not None:
            channel.phone_number = data.phone_number
        if data.description is not None:
            channel.description = data.description
        if data.is_active is not None:
            channel.is_active = data.is_active
    else:
        if data.name is not None:
            channel.name = data.name
        if data.label is not None:
            channel.label = data.label
        if data.instance_id is not None:
            channel.instance_id = data.instance_id
        if data.token is not None:
            channel.token = data.token
        if data.client_token is not None:
            channel.client_token = data.client_token
        if data.phone_number is not None:
            channel.phone_number = data.phone_number
        if data.description is not None:
            channel.description = data.description
        if data.is_active is not None:
            channel.is_active = data.is_active

    db.commit()
    db.refresh(channel)

    return {
        "id": channel.id,
        "name": channel.name,
        "label": channel.label,
        "phone_number": channel.phone_number,
        "is_legacy": channel.is_legacy,
        "is_active": channel.is_active,
        "webhook_url_suggested": _build_webhook_url_suggested(request, channel.id),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task #234 — Reatribuição de assessores por canal
# ─────────────────────────────────────────────────────────────────────────────

class AssessoresPatchInput(BaseModel):
    assign: Optional[List[int]] = None
    unassign: Optional[List[int]] = None


@router.get("/zapi/channels/{channel_id}/assessores")
async def list_channel_assessores(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    q: Optional[str] = None,
):
    """
    Task #234 — Lista os assessores vinculados ao canal.
    Suporta busca por nome, código (codigo_ai) ou e-mail via ?q=.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel, Assessor
    from sqlalchemy import or_

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    query = db.query(Assessor).filter(Assessor.channel_id == channel_id)
    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Assessor.nome.ilike(term),
                Assessor.codigo_ai.ilike(term),
                Assessor.email.ilike(term),
            )
        )

    assessores = query.order_by(Assessor.nome).all()
    return {
        "channel_id": channel_id,
        "assessores": [
            {
                "id": a.id,
                "nome": a.nome,
                "codigo_ai": a.codigo_ai,
                "email": a.email,
                "unidade": a.unidade,
                "telefone_whatsapp": a.telefone_whatsapp,
            }
            for a in assessores
        ],
        "total": len(assessores),
    }


@router.get("/zapi/assessores/search")
async def search_assessores(
    request: Request,
    db: Session = Depends(get_db),
    q: Optional[str] = None,
    exclude_channel: Optional[int] = None,
    limit: int = 20,
):
    """
    Task #234 — Busca assessores por nome, código ou e-mail.
    Usado para encontrar assessores a mover para um canal.
    Parâmetro exclude_channel omite assessores já vinculados a esse canal.
    limit é limitado a no máximo 50 para proteger performance.
    """
    _auth_zapi_channel(request)
    limit = max(1, min(limit, 50))

    from database.models import Assessor
    from sqlalchemy import or_

    query = db.query(Assessor)

    if q:
        term = f"%{q}%"
        query = query.filter(
            or_(
                Assessor.nome.ilike(term),
                Assessor.codigo_ai.ilike(term),
                Assessor.email.ilike(term),
            )
        )

    if exclude_channel is not None:
        query = query.filter(
            (Assessor.channel_id != exclude_channel) | Assessor.channel_id.is_(None)
        )

    assessores = query.order_by(Assessor.nome).limit(limit).all()
    return {
        "assessores": [
            {
                "id": a.id,
                "nome": a.nome,
                "codigo_ai": a.codigo_ai,
                "email": a.email,
                "unidade": a.unidade,
                "channel_id": a.channel_id,
            }
            for a in assessores
        ],
        "total": len(assessores),
    }


@router.patch("/zapi/channels/{channel_id}/assessores")
async def patch_channel_assessores(
    channel_id: int,
    data: AssessoresPatchInput,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #234 — Reatribui assessores ao canal em lote.
    - assign: lista de IDs a vincular a este canal.
    - unassign: lista de IDs a desvincular (channel_id → null).
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel, Assessor

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    assigned_count = 0
    unassigned_count = 0

    if data.assign:
        rows = db.query(Assessor).filter(Assessor.id.in_(data.assign)).all()
        for a in rows:
            a.channel_id = channel_id
        assigned_count = len(rows)

    if data.unassign:
        rows = db.query(Assessor).filter(
            Assessor.id.in_(data.unassign),
            Assessor.channel_id == channel_id,
        ).all()
        for a in rows:
            a.channel_id = None
        unassigned_count = len(rows)

    db.commit()

    return {
        "channel_id": channel_id,
        "assigned": assigned_count,
        "unassigned": unassigned_count,
        "message": f"{assigned_count} assessor(es) vinculado(s), {unassigned_count} desvinculado(s).",
    }


@router.delete("/zapi/channels/{channel_id}")
async def delete_zapi_channel(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #232 — Remove um canal Z-API.
    Bloqueado para: canais legados e canais com assessores vinculados.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel, Assessor
    from sqlalchemy import func as _func

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    if channel.is_legacy:
        raise HTTPException(
            status_code=400,
            detail="Canais legados não podem ser excluídos pois são gerenciados via variáveis de ambiente."
        )

    assessor_count = (
        db.query(_func.count(Assessor.id))
        .filter(Assessor.channel_id == channel_id)
        .scalar()
    ) or 0

    if assessor_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Canal possui {assessor_count} assessor(es) vinculado(s). Desvincule-os antes de excluir o canal."
        )

    label = channel.label or channel.name
    db.delete(channel)
    db.commit()

    return {"message": f"Canal '{label}' removido com sucesso"}
