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


def _extract_url_from_webhook_settings(settings: dict) -> tuple:
    """
    Task #272 — Helper compartilhado para extrair a URL de webhook de um dict de
    configurações do Z-API. Usado em _probe_webhook, sync-webhook verify e webhook-debug
    para garantir comportamento consistente.

    Testa campos planos em ordem de prioridade e, para dicts aninhados, percorre
    um nível de profundidade. Retorna (field_name, url) ou (None, "").
    """
    _candidates = (
        "webhookReceived", "webhookDelivery", "webhookUrl",
        "value", "webhook", "url",
    )
    for _k in _candidates:
        _v = settings.get(_k)
        if _v and isinstance(_v, str) and _v.startswith("http"):
            return _k, _v
        if _v and isinstance(_v, dict):
            for _nk, _nv in _v.items():
                if _nv and isinstance(_nv, str) and _nv.startswith("http"):
                    return f"{_k}.{_nk}", _nv
    return None, ""


def _build_webhook_url_suggested(request: Request, channel_id: int) -> str:
    """
    Monta a URL de webhook sugerida para o canal.

    Task #270 — Prioridade de resolução da base URL:
    1. `WEBHOOK_BASE_URL` (override máximo — específico para URL de webhooks).
    2. `APP_BASE_URL` / `REPLIT_DOMAINS` via `get_public_base_url()` (URL geral do app).
    3. `request.base_url` — fallback final; pode retornar URL interna
       (http://0.0.0.0:5000/) se o FastAPI não estiver atrás de
       ProxyHeadersMiddleware, mas ainda serve para ambientes com proxy correto.
    """
    from core.config import get_public_base_url, get_settings as _get_cfg
    _cfg = _get_cfg()
    if _cfg.WEBHOOK_BASE_URL:
        base = _cfg.WEBHOOK_BASE_URL.rstrip("/")
        source = "WEBHOOK_BASE_URL"
    else:
        public = get_public_base_url()
        base = public or str(request.base_url).rstrip("/")
        source = "get_public_base_url()" if public else "request.base_url"
    print(f"[WEBHOOK-URL] canal={channel_id} base={base!r} (fonte: {source})")
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
    include_webhook_status: bool = False,
):
    """
    Task #223 — Lista todos os canais Z-API configurados.

    Retorna para cada canal:
    - Credenciais mascaradas (nunca expõe tokens completos).
    - `connectivity_status`: sonda Z-API em tempo real ("connected" / "disconnected" / "unreachable").
    - `assessor_count`: quantidade de assessores vinculados ao canal.
    - `unidades_assigned`: lista de unidades mapeadas para o canal.
    - `webhook_registered` (Task #264): true | false | "unknown" — incluído APENAS
      quando `include_webhook_status=true` (sondagem opt-in para não degradar a listagem).

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
        Usa ZAPIClient.get_webhook_settings() com timeout agressivo de 4s para não degradar
        a listagem.
        Retorna: True (registrado e URL bate), False (registrado mas URL diferente ou vazio),
                 "unknown" (não foi possível obter a configuração remota).

        Task #272 — lógica defensiva de detecção de campo: percorre múltiplos campos
        possíveis pois o Z-API pode retornar a URL em campos diferentes dependendo da
        versão da instância. Loga qual campo foi encontrado para auditoria.
        Task #276 — quando GET /webhooks retorna endpoint_not_found (NOT_FOUND no Z-API),
        usa webhook_auto_registered do banco como fallback: True → "registered_no_verify",
        False → False. Isso evita badge vermelho quando o endpoint não é suportado.
        """
        try:
            client = ZAPIClient(
                instance_id=ch.instance_id,
                token=ch.token,
                client_token=ch.client_token,
            )
            result = await client.get_webhook_settings(timeout=4.0)
            if not result.get("success"):
                return "unknown"
            # Task #276 — endpoint GET /webhooks não existe para esta instância Z-API.
            # Usa flag do banco como fallback em vez de mostrar badge vermelho.
            if result.get("endpoint_not_found"):
                fallback = "registered_no_verify" if ch.webhook_auto_registered else False
                print(f"[WEBHOOK-PROBE] ch={ch.id} endpoint_not_found → fallback={fallback!r}")
                return fallback
            settings = result.get("settings") or {}
            # Task #272 — usa o helper compartilhado _extract_url_from_webhook_settings
            # para consistência com sync-verify e webhook-debug (inclui nested fields).
            found_key, remote_url = _extract_url_from_webhook_settings(settings)
            if found_key:
                print(f"[WEBHOOK-PROBE] ch={ch.id} campo={found_key!r} url={remote_url!r} expected={suggested_url!r}")
            else:
                print(f"[WEBHOOK-PROBE] ch={ch.id} nenhum campo URL HTTP encontrado — keys={list(settings.keys())} raw={settings}")
            return remote_url.rstrip("/") == suggested_url.rstrip("/")
        except Exception as _probe_exc:
            print(f"[WEBHOOK-PROBE] ch={ch.id} exceção: {_probe_exc}")
            return "unknown"

    if active_channels:
        conn_results = await asyncio.gather(*[_probe(ch) for ch in active_channels], return_exceptions=True)
        connectivity: Dict[int, str] = {}
        for ch, result in zip(active_channels, conn_results):
            connectivity[ch.id] = result if isinstance(result, str) else "unreachable"
    else:
        connectivity = {}

    # Task #264 — sonda webhook apenas quando explicitamente solicitado (opt-in).
    # Padrão (include_webhook_status=False): retorna "unknown" para todos sem chamada remota.
    webhook_status: Dict[int, object] = {}
    if include_webhook_status and probeable_channels:
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
# Task #265 — Sincronização em lote de webhooks
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/zapi/channels/sync-all-webhooks")
async def sync_all_zapi_webhooks(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #265 — Sincroniza webhooks de todos os canais ativos não-legados em paralelo.
    Retorna lista com status individual por canal (sucesso/falha).
    """
    _auth_zapi_channel(request)

    import asyncio
    from database.models import ZAPIChannel
    from services.whatsapp_client import ZAPIClient

    channels = (
        db.query(ZAPIChannel)
        .filter(
            ZAPIChannel.is_legacy.is_(False),
            ZAPIChannel.is_active.is_(True),
        )
        .all()
    )

    if not channels:
        return {"results": [], "synced": 0, "failed": 0, "message": "Nenhum canal elegível para sincronização."}

    async def _sync_one(ch: ZAPIChannel):
        webhook_url = _build_webhook_url_suggested(request, ch.id)
        try:
            client = ZAPIClient(
                instance_id=ch.instance_id,
                token=ch.token,
                client_token=ch.client_token,
            )
            result = await client.update_webhook(webhook_url)
        except Exception as exc:
            _exc_type = type(exc).__name__
            print(f"[Z-API Webhook] Batch sync canal {ch.id} — exceção {_exc_type}: {exc}")
            return {
                "channel_id": ch.id,
                "label": ch.label or ch.name,
                "success": False,
                "webhook_url": webhook_url,
                "error": f"{_exc_type}: {exc}",
            }

        success = result.get("success", False)
        if success:
            ch.webhook_auto_registered = True
            ch.webhook_url = webhook_url
            print(f"[Z-API Webhook] Batch sync canal {ch.id} OK: {webhook_url}")
        else:
            print(f"[Z-API Webhook] Batch sync canal {ch.id} falhou: {result}")

        return {
            "channel_id": ch.id,
            "label": ch.label or ch.name,
            "success": success,
            "webhook_url": webhook_url,
            "error": result.get("error") if not success else None,
        }

    results = await asyncio.gather(*[_sync_one(ch) for ch in channels])

    synced = sum(1 for r in results if r["success"])
    failed = len(results) - synced

    if synced > 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            _exc_type = type(exc).__name__
            print(f"[Z-API Webhook] Batch sync — erro ao persistir flags: {exc}")
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Webhooks registrados na Z-API ({synced} de {len(results)}), porém não foi possível "
                    f"persistir os flags no banco de dados ({_exc_type}). "
                    "Tente sincronizar novamente."
                ),
            )

    return {
        "results": list(results),
        "synced": synced,
        "failed": failed,
        "message": f"{synced} canal(is) sincronizado(s) com sucesso, {failed} com falha.",
    }


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
        _exc_type = type(exc).__name__
        raise HTTPException(
            status_code=502,
            detail=f"Erro de comunicação com a Z-API ({_exc_type}). Verifique se a instância está acessível.",
        )

    if result.get("success"):
        channel.webhook_auto_registered = True
        channel.webhook_url = webhook_url
        db.commit()
        print(f"[Z-API Webhook] Canal {channel_id} — sync-webhook manual OK: {webhook_url}")
    else:
        print(f"[Z-API Webhook] Canal {channel_id} — sync-webhook manual falhou: {result}")

    # Task #272 — verifica imediatamente pós-registro o que Z-API retorna em GET /webhooks.
    # Task #276 — propaga endpoint_not_found quando GET /webhooks não é suportado pela instância.
    verify_raw: Optional[dict] = None
    verify_field: Optional[str] = None
    verify_url: Optional[str] = None
    verify_endpoint_not_found: bool = False
    try:
        vresp = await client.get_webhook_settings(timeout=8.0)
        if vresp.get("success"):
            if vresp.get("endpoint_not_found"):
                # Task #276 — Z-API não suporta GET /webhooks — não é erro, apenas indisponível.
                verify_endpoint_not_found = True
                print(f"[Z-API Webhook] Canal {channel_id} — verify GET /webhooks: endpoint_not_found")
            else:
                vsettings = vresp.get("settings") or {}
                verify_raw = vsettings
                verify_field, verify_url = _extract_url_from_webhook_settings(vsettings)
                print(
                    f"[Z-API Webhook] Canal {channel_id} — verify GET /webhooks: "
                    f"campo={verify_field!r} url={verify_url!r}"
                )
    except Exception as _vexc:
        print(f"[Z-API Webhook] Canal {channel_id} — verify exceção: {_vexc}")

    return {
        "success": result.get("success", False),
        "webhook_url": webhook_url,
        "channel_id": channel_id,
        "raw_response": result.get("raw_response"),
        "body_error": result.get("body_error"),
        "verify_raw": verify_raw,
        "verify_field": verify_field,
        "verify_url": verify_url,
        "url_match": (verify_url.rstrip("/") == webhook_url.rstrip("/")) if verify_url else None,
        "endpoint_not_found": verify_endpoint_not_found,
        "error": result.get("error"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task #272 — Diagnóstico de webhook por canal
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/zapi/channels/{channel_id}/webhook-debug")
async def debug_zapi_channel_webhook(
    channel_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Task #272 — Endpoint de diagnóstico completo do webhook para um canal Z-API.

    Retorna:
    - URL que seria registrada (conforme a lógica de _build_webhook_url_suggested)
    - Raw JSON completo do GET /webhooks do Z-API para a instância do canal
    - Campo detectado para comparação de URL (com múltiplos candidatos)
    - URL atual registrada no Z-API
    - Se a URL atual bate com a URL sugerida

    Acesso restrito a admin/gestao_rv.
    """
    _auth_zapi_channel(request)

    from database.models import ZAPIChannel

    channel = db.query(ZAPIChannel).filter(ZAPIChannel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail=f"Canal {channel_id} não encontrado")

    webhook_url = _build_webhook_url_suggested(request, channel.id)

    # Task #272 — `client_token_source` é computado (ZAPIChannel não tem esse campo):
    # "own" quando o canal tem client_token próprio no banco, "global" quando NULL.
    _ct_source = "own" if channel.client_token else "global"

    diag: dict = {
        "channel_id": channel_id,
        "channel_name": channel.name,
        "is_legacy": channel.is_legacy,
        "is_active": channel.is_active,
        "webhook_url_suggested": webhook_url,
        "webhook_auto_registered": channel.webhook_auto_registered or False,
        "instance_id": channel.instance_id,
        "client_token_source": _ct_source,
        "zapi_raw_response": None,
        "endpoint_not_found": False,
        "detected_field": None,
        "detected_url": None,
        "url_match": None,
        "all_candidate_fields": {},
        "instance_status": None,
        "self_test": None,
        "error": None,
    }

    if channel.is_legacy:
        diag["error"] = "Canal legado — webhook gerenciado via variáveis de ambiente, não via API"
        return diag

    if not channel.is_active:
        diag["error"] = "Canal inativo"
        return diag

    import httpx as _httpx_diag
    import os as _os_diag

    # ── 0. GET /status — valida se a instância existe e está conectada ─────────
    # Task #276 — separado do GET /webhooks para que falhas neste não bloqueiem.
    try:
        from services.whatsapp_client import ZAPIClient as _ZC
        client = _ZC(
            instance_id=channel.instance_id,
            token=channel.token,
            client_token=channel.client_token,
        )
        _st_result = await client.check_connectivity(timeout=6.0)
        diag["instance_status"] = _st_result
    except Exception as _st_exc:
        diag["instance_status"] = f"erro: {type(_st_exc).__name__}: {_st_exc}"

    # ── 1. GET /webhooks do Z-API ──────────────────────────────────────────────
    try:
        ws_result = await client.get_webhook_settings(timeout=10.0)

        if not ws_result.get("success"):
            diag["error"] = ws_result.get("error", "Falha ao obter configurações de webhook")
        elif ws_result.get("endpoint_not_found"):
            # Task #276 — endpoint não suportado por esta instância. Não é erro fatal.
            diag["endpoint_not_found"] = True
            diag["error"] = (
                "GET /webhooks não suportado por esta instância Z-API. "
                "O registro é feito via PUT mas não pode ser verificado via API. "
                f"Banco de dados indica webhook_auto_registered={channel.webhook_auto_registered}."
            )
        else:
            settings = ws_result.get("settings") or {}
            diag["zapi_raw_response"] = settings

            _candidates = (
                "webhookReceived", "webhookDelivery", "webhookUrl",
                "value", "webhook", "url",
            )
            for _k in _candidates:
                _v = settings.get(_k)
                diag["all_candidate_fields"][_k] = _v

            # Usa o helper compartilhado para detecção consistente (inclui campos aninhados)
            _det_field, _det_url = _extract_url_from_webhook_settings(settings)
            if _det_field:
                diag["detected_field"] = _det_field
                diag["detected_url"] = _det_url
                diag["url_match"] = (_det_url.rstrip("/") == webhook_url.rstrip("/"))

    except Exception as exc:
        diag["error"] = f"{type(exc).__name__}: {exc}"

    # ── 2. Self-test: POST sintético ao próprio endpoint multichannel ──────────
    # Verifica acessibilidade da URL e se a validação de token passaria.
    # Usa type __webhook_diagnostic_test__ — o handler ignora sem processar.
    self_test: dict = {
        "attempted": False,
        "url_tested": webhook_url,
        "token_hint": None,
        "status_code": None,
        "result": None,
        "error": None,
    }
    try:
        from core.config import get_settings as _get_cfg_st
        _st_cfg = _get_cfg_st()
        # Token que o Z-API enviaria: client_token próprio ou ZAPI_CLIENT_TOKEN global
        _test_token = (
            channel.client_token
            or _os_diag.getenv("ZAPI_CLIENT_TOKEN", "")
            or _st_cfg.ZAPI_CLIENT_TOKEN
            or channel.token
        )
        self_test["attempted"] = True
        self_test["token_hint"] = (_test_token[:4] + "****") if len(_test_token) > 4 else "***"

        async with _httpx_diag.AsyncClient(timeout=8.0, verify=True) as _hc:
            _st_resp = await _hc.post(
                webhook_url,
                json={"type": "__webhook_diagnostic_test__", "instanceId": channel.instance_id},
                headers={
                    "client-token": _test_token,
                    "Content-Type": "application/json",
                },
            )
        self_test["status_code"] = _st_resp.status_code
        if _st_resp.status_code == 200:
            self_test["result"] = "reachable_and_token_valid"
        elif _st_resp.status_code == 401:
            self_test["result"] = "token_rejected"
        elif _st_resp.status_code == 404:
            self_test["result"] = "url_not_found"
        else:
            self_test["result"] = f"unexpected_http_{_st_resp.status_code}"

    except _httpx_diag.ConnectError as _ce:
        self_test["error"] = f"ConnectError: servidor inacessível — {_ce}"
        self_test["result"] = "unreachable"
    except _httpx_diag.TimeoutException:
        self_test["error"] = "Timeout ao tentar alcançar a URL de webhook"
        self_test["result"] = "timeout"
    except Exception as _ste:
        self_test["error"] = f"{type(_ste).__name__}: {_ste}"
        self_test["result"] = "error"

    diag["self_test"] = self_test

    print(
        f"[WEBHOOK-DEBUG] Canal {channel_id} — url_suggested={webhook_url!r} "
        f"detected_field={diag['detected_field']!r} detected_url={diag['detected_url']!r} "
        f"match={diag['url_match']} self_test={self_test['result']}"
    )
    return diag


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
