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


def _redact(text: str, sensitive_values) -> str:
    """
    Task #255 — Remove valores sensíveis (tokens/IDs) de mensagens de erro e
    tracebacks antes de logar ou expor via API. Mantém apenas substituições
    para strings com pelo menos 4 caracteres (evita corromper mensagens).
    """
    if not text:
        return text
    out = text
    for v in sensitive_values:
        if v and isinstance(v, str) and len(v) >= 4:
            out = out.replace(v, "***")
    return out


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

    # Sonda conectividade e status do webhook de cada canal ativo em paralelo.
    active_channels = [ch for ch in channels if ch.is_active]
    # Canais ativos e não-legados são os únicos que têm webhook auto-gerenciado.
    probeable_channels = [ch for ch in active_channels if not ch.is_legacy]

    async def _probe(ch: ZAPIChannel) -> str:
        client = ZAPIClient(
            instance_id=ch.instance_id,
            token=ch.token,
            client_token=ch.client_token,
        )
        return await client.check_connectivity(timeout=5.0)

    async def _probe_webhook(ch: ZAPIChannel, suggested_url: str):
        """
        Task #264 — Verifica em tempo real se o webhook está registrado na instância Z-API.
        Retorna: True (registrado e URL bate), False (registrado mas URL diferente ou vazio),
                 "unknown" (não foi possível obter a configuração remota).
        """
        try:
            client = ZAPIClient(
                instance_id=ch.instance_id,
                token=ch.token,
                client_token=ch.client_token,
            )
            result = await client.get_webhook_settings()
            if not result.get("success"):
                return "unknown"
            settings = result.get("settings") or {}
            # Z-API retorna {"webhookReceived": "https://..."} no campo settings.
            remote_url = settings.get("webhookReceived") or settings.get("value") or ""
            return remote_url.rstrip("/") == suggested_url.rstrip("/")
        except Exception:
            return "unknown"

    if active_channels:
        conn_results = await asyncio.gather(*[_probe(ch) for ch in active_channels], return_exceptions=True)
        connectivity: Dict[int, str] = {}
        for ch, result in zip(active_channels, conn_results):
            connectivity[ch.id] = result if isinstance(result, str) else "unreachable"
    else:
        connectivity = {}

    # Task #264 — sonda webhook de todos os canais ativos não-legados em paralelo.
    webhook_status: Dict[int, object] = {}
    if probeable_channels:
        wh_suggested_by_id = {
            ch.id: _build_webhook_url_suggested(request, ch.id)
            for ch in probeable_channels
        }
        wh_results = await asyncio.gather(
            *[_probe_webhook(ch, wh_suggested_by_id[ch.id]) for ch in probeable_channels],
            return_exceptions=True,
        )
        for ch, wh_result in zip(probeable_channels, wh_results):
            status = wh_result if not isinstance(wh_result, Exception) else "unknown"
            webhook_status[ch.id] = status
            # Sincroniza o flag histórico no banco se o estado real difere (sem travar).
            if status is True and not ch.webhook_auto_registered:
                try:
                    ch.webhook_auto_registered = True
                    db.commit()
                except Exception:
                    db.rollback()
            elif status is False and ch.webhook_auto_registered:
                try:
                    ch.webhook_auto_registered = False
                    db.commit()
                except Exception:
                    db.rollback()

    def _wh_registered(ch: ZAPIChannel) -> object:
        """Retorna True, False ou 'unknown' para uso pela UI."""
        if ch.is_legacy or not ch.is_active:
            return "unknown"
        return webhook_status.get(ch.id, "unknown")

    return {
        "channels": [
            {
                "id": ch.id,
                "name": ch.name,
                "label": ch.label,
                "phone_number": ch.phone_number,
                "instance_id": _mask(ch.instance_id),
                "token_masked": _mask(ch.token),
                # Task #255: indica se o canal usa Client-Token próprio ou o global
                # ("own" = client_token salvo no canal; "global" = usa ZAPI_CLIENT_TOKEN).
                "client_token_source": "own" if ch.client_token else "global",
                "client_token_configured": bool(ch.client_token),  # alias legado
                "is_legacy": ch.is_legacy,
                "is_active": ch.is_active,
                "webhook_url": ch.webhook_url,
                # Task #264 — estado computado em tempo real (True/False/"unknown").
                "webhook_registered": _wh_registered(ch),
                "webhook_auto_registered": ch.webhook_auto_registered or False,
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

    Task #255: client_token é OPCIONAL — quando omitido, o canal usa o
    ZAPI_CLIENT_TOKEN global como fallback (mesmo Security Token da conta Z-API).
    Erros de criação são logados com traceback e retornados com detail informativo.
    """
    import traceback

    _auth_zapi_channel(request)

    from database.models import ZAPIChannel
    from services.whatsapp_client import ZAPIClient

    # Normaliza client_token vazio → None (semântica: NULL = usa global)
    client_token = (data.client_token or "").strip() or None

    try:
        client = ZAPIClient(
            instance_id=data.instance_id,
            token=data.token,
            client_token=client_token,
        )
        connectivity = await client.check_connectivity(timeout=8.0)

        channel = ZAPIChannel(
            name=data.name,
            label=data.label or data.name,
            instance_id=data.instance_id,
            token=data.token,
            client_token=client_token,
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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        sensitive_values = (data.token or "", data.instance_id or "", client_token or "")
        safe_msg = _redact(str(e), sensitive_values)
        safe_tb = _redact(traceback.format_exc(), sensitive_values)
        print(f"[Z-API Channel Create] Falha ao criar canal: {type(e).__name__}: {safe_msg}\n{safe_tb}")
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao criar canal ({type(e).__name__}): {safe_msg}",
        )

    # Task #264 — registra automaticamente o webhook na instância Z-API.
    # Não bloqueia a criação em caso de falha (instância pode estar desconectada).
    webhook_registration: dict = {"success": False, "skipped": True}
    try:
        webhook_registration = await client.update_webhook(webhook_url)
        if webhook_registration.get("success"):
            channel.webhook_auto_registered = True
            db.commit()
            print(f"[Z-API Webhook] Canal {channel.id} — webhook auto-registrado: {webhook_url}")
        else:
            print(f"[Z-API Webhook] Canal {channel.id} — auto-registro falhou (instância pode estar desconectada): {webhook_registration}")
    except Exception as _whe:
        webhook_registration = {"success": False, "error": str(_whe)}
        print(f"[Z-API Webhook] Canal {channel.id} — erro no auto-registro: {_whe}")

    return {
        "id": channel.id,
        "name": channel.name,
        "label": channel.label,
        "phone_number": channel.phone_number,
        "instance_id": data.instance_id[:4] + "****" if len(data.instance_id) >= 8 else "****",
        "is_legacy": channel.is_legacy,
        "is_active": channel.is_active,
        "client_token_source": "own" if client_token else "global",
        "connectivity_status": connectivity,
        "webhook_url_suggested": webhook_url,
        "webhook_registration": webhook_registration,
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
    import traceback

    _auth_zapi_channel(request)

    from database.models import ZAPIChannel

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    try:
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
            # Task #255: distingue "campo não enviado" (no-op) de "campo enviado
            # como null/empty" (limpa → NULL, usa fallback global). Usa
            # model_fields_set para detectar presença explícita do campo.
            if "client_token" in data.model_fields_set:
                raw = data.client_token
                channel.client_token = (raw.strip() or None) if isinstance(raw, str) else None
            if data.phone_number is not None:
                channel.phone_number = data.phone_number
            if data.description is not None:
                channel.description = data.description
            if data.is_active is not None:
                channel.is_active = data.is_active

        db.commit()
        db.refresh(channel)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        sensitive_values = (
            data.token or "",
            data.instance_id or "",
            data.client_token or "",
        )
        safe_msg = _redact(str(e), sensitive_values)
        safe_tb = _redact(traceback.format_exc(), sensitive_values)
        print(f"[Z-API Channel Update] Falha ao atualizar canal {channel_id}: {type(e).__name__}: {safe_msg}\n{safe_tb}")
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao atualizar canal ({type(e).__name__}): {safe_msg}",
        )

    # Task #264 — re-registra webhook quando canal é ativado ou credenciais mudam.
    _credentials_changed = not channel.is_legacy and (
        data.instance_id is not None or data.token is not None or "client_token" in data.model_fields_set
    )
    _being_activated = not channel.is_legacy and data.is_active is True
    if channel.is_active and (_being_activated or _credentials_changed):
        try:
            from services.whatsapp_client import ZAPIClient as _ZC
            _wh_url = _build_webhook_url_suggested(request, channel.id)
            _wh_client = _ZC(
                instance_id=channel.instance_id,
                token=channel.token,
                client_token=channel.client_token,
            )
            _wr = await _wh_client.update_webhook(_wh_url)
            if _wr.get("success"):
                channel.webhook_auto_registered = True
                channel.webhook_url = _wh_url
                db.commit()
                print(f"[Z-API Webhook] Canal {channel_id} — webhook re-registrado: {_wh_url}")
            else:
                print(f"[Z-API Webhook] Canal {channel_id} — re-registro falhou: {_wr}")
        except Exception as _whe:
            print(f"[Z-API Webhook] Canal {channel_id} — erro no re-registro: {_whe}")

    webhook_url_suggested = _build_webhook_url_suggested(request, channel.id)
    return {
        "id": channel.id,
        "name": channel.name,
        "label": channel.label,
        "phone_number": channel.phone_number,
        "is_legacy": channel.is_legacy,
        "is_active": channel.is_active,
        "client_token_source": "own" if channel.client_token else "global",
        "webhook_url_suggested": webhook_url_suggested,
        "webhook_auto_registered": channel.webhook_auto_registered or False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task #234 — Reatribuição de assessores por canal
# ─────────────────────────────────────────────────────────────────────────────

class AssessoresPatchInput(BaseModel):
    assign: Optional[List[int]] = None
    unassign: Optional[List[int]] = None


class AssignarUnidadeInput(BaseModel):
    unidade: str


@router.get("/zapi/assessores/unidades")
async def list_assessor_unidades(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #238 — Retorna a lista de unidades distintas cadastradas nos assessores.
    Usada para popular o dropdown de reatribuição em lote por unidade.
    """
    _auth_zapi_channel(request)

    from database.models import Assessor
    from sqlalchemy import distinct

    rows = (
        db.query(distinct(Assessor.unidade))
        .filter(Assessor.unidade.isnot(None), Assessor.unidade != "")
        .order_by(Assessor.unidade)
        .all()
    )
    unidades = [r[0] for r in rows]
    return {"unidades": unidades}


@router.post("/zapi/channels/{channel_id}/assignar-unidade")
async def assignar_unidade(
    channel_id: int,
    data: AssignarUnidadeInput,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #238 — Move todos os assessores de uma unidade para este canal.
    Assessores que já estão no canal não são recontados.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel, Assessor

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    unidade = data.unidade.strip()
    if not unidade:
        raise HTTPException(status_code=422, detail="O campo 'unidade' não pode ser vazio.")

    assessores = (
        db.query(Assessor)
        .filter(
            Assessor.unidade == unidade,
            (Assessor.channel_id != channel_id) | Assessor.channel_id.is_(None),
        )
        .all()
    )

    moved_count = 0
    for a in assessores:
        a.channel_id = channel_id
        moved_count += 1

    db.commit()

    return {
        "channel_id": channel_id,
        "unidade": unidade,
        "moved": moved_count,
        "message": (
            f"{moved_count} assessor(es) da unidade '{unidade}' movido(s) para este canal."
            if moved_count
            else f"Nenhum assessor novo da unidade '{unidade}' para mover."
        ),
    }


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


# ─────────────────────────────────────────────────────────────────────────────
# Task #264 — Sincronização manual de webhook por canal
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/zapi/channels/{channel_id}/sync-webhook")
async def sync_zapi_channel_webhook(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #264 — Registra (ou re-registra) a URL de webhook na instância Z-API do canal.
    Idempotente: pode ser chamado múltiplas vezes sem efeitos colaterais.
    Canais legados não são suportados (webhook gerenciado via env vars).
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel
    from services.whatsapp_client import ZAPIClient

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    if channel.is_legacy:
        raise HTTPException(
            status_code=400,
            detail="Canais legados não suportam registro automático de webhook (configurado via variáveis de ambiente).",
        )

    if not channel.is_active:
        raise HTTPException(
            status_code=400,
            detail="Canal inativo. Ative o canal antes de sincronizar o webhook.",
        )

    webhook_url = _build_webhook_url_suggested(request, channel.id)

    try:
        client = ZAPIClient(
            instance_id=channel.instance_id,
            token=channel.token,
            client_token=channel.client_token,
        )
        result = await client.update_webhook(webhook_url)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao comunicar com a Z-API: {str(exc)}",
        )

    if result.get("success"):
        channel.webhook_auto_registered = True
        channel.webhook_url = webhook_url
        db.commit()
        print(f"[Z-API Webhook] Canal {channel_id} — sync-webhook manual OK: {webhook_url}")
    else:
        print(f"[Z-API Webhook] Canal {channel_id} — sync-webhook manual falhou: {result}")

    return {
        "success": result.get("success", False),
        "webhook_url": webhook_url,
        "channel_id": channel_id,
        "raw_response": result.get("raw_response"),
        "error": result.get("error"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task #233 — Mapeamento de Unidades por Canal Z-API
# ─────────────────────────────────────────────────────────────────────────────

class UnidadeMapCreate(BaseModel):
    unidade: str


@router.get("/zapi/unidades")
async def list_all_unidades(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #233 — Lista todas as unidades únicas registradas nos assessores.
    Usado para popular o dropdown de adição de mapeamento.
    """
    _auth_zapi_channel(request)

    from database.models import Assessor
    from sqlalchemy import distinct

    rows = (
        db.query(distinct(Assessor.unidade))
        .filter(Assessor.unidade.isnot(None), Assessor.unidade != "")
        .order_by(Assessor.unidade)
        .all()
    )
    unidades = [r[0] for r in rows if r[0]]
    return {"unidades": unidades}


@router.post("/zapi/channels/{channel_id}/unidades", status_code=201)
async def add_unidade_mapping(
    channel_id: int,
    data: UnidadeMapCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #233 — Associa uma unidade a um canal Z-API.
    A unidade deve existir na base de assessores e não pode estar
    mapeada para outro canal (restrição UNIQUE em `unidade`).
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel, UnidadeChannelMapping, Assessor

    unidade = data.unidade.strip()
    if not unidade:
        raise HTTPException(status_code=422, detail="O campo 'unidade' não pode ser vazio.")

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado.")

    # Validate that the unidade exists in at least one Assessor record
    assessor_exists = (
        db.query(Assessor.id)
        .filter(Assessor.unidade == unidade)
        .first()
    )
    if not assessor_exists:
        raise HTTPException(
            status_code=422,
            detail=f"A unidade '{unidade}' não foi encontrada na base de assessores. Verifique o nome exato da unidade."
        )

    existing = (
        db.query(UnidadeChannelMapping)
        .filter(UnidadeChannelMapping.unidade == unidade)
        .first()
    )
    if existing:
        if existing.channel_id == channel_id:
            raise HTTPException(
                status_code=409,
                detail=f"A unidade '{unidade}' já está mapeada para este canal."
            )
        raise HTTPException(
            status_code=409,
            detail=f"A unidade '{unidade}' já está mapeada para outro canal (id={existing.channel_id}). Remova o mapeamento anterior antes de reatribuir."
        )

    mapping = UnidadeChannelMapping(unidade=unidade, channel_id=channel_id)
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    return {
        "id": mapping.id,
        "unidade": mapping.unidade,
        "channel_id": mapping.channel_id,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
    }


@router.delete("/zapi/channels/{channel_id}/unidades/{unidade}")
async def remove_unidade_mapping(
    channel_id: int,
    unidade: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #233 — Remove o mapeamento de uma unidade de um canal Z-API.
    """
    _auth_zapi_channel(request)

    from database.models import UnidadeChannelMapping

    mapping = (
        db.query(UnidadeChannelMapping)
        .filter(
            UnidadeChannelMapping.unidade == unidade,
            UnidadeChannelMapping.channel_id == channel_id,
        )
        .first()
    )
    if not mapping:
        raise HTTPException(
            status_code=404,
            detail=f"Mapeamento da unidade '{unidade}' para o canal {channel_id} não encontrado."
        )

    db.delete(mapping)
    db.commit()

    return {"message": f"Unidade '{unidade}' desvinculada do canal com sucesso."}
