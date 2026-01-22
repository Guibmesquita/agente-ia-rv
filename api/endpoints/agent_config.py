"""
Endpoints para configuração do agente de IA.
Permite administradores configurarem personalidade, modelo e parâmetros.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database.database import get_db
from database.crud import get_agent_config, create_or_update_agent_config
from api.endpoints.auth import get_current_user
from database.models import User, UserRole

router = APIRouter(prefix="/api/agent-config", tags=["Agent Config"])


class AgentConfigResponse(BaseModel):
    id: int
    personality: str
    restrictions: str
    model: str
    temperature: str
    max_tokens: int
    allowed_phones: Optional[str] = ""
    filter_mode: Optional[str] = "all"
    
    class Config:
        from_attributes = True


class AgentConfigUpdate(BaseModel):
    personality: str
    restrictions: Optional[str] = ""
    model: str = "gpt-4o"
    temperature: str = "0.7"
    max_tokens: int = 500
    allowed_phones: Optional[str] = ""
    filter_mode: Optional[str] = "all"


def require_admin_or_gestao(current_user: User = Depends(get_current_user)):
    """Verifica se o usuário é admin ou gestao_rv."""
    if current_user.role not in [UserRole.ADMIN.value, UserRole.GESTAO_RV.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores e gestão RV"
        )
    return current_user


@router.get("/", response_model=AgentConfigResponse)
async def get_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Retorna a configuração atual do agente."""
    config = get_agent_config(db)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuração do agente não encontrada"
        )
    return config


@router.put("/", response_model=AgentConfigResponse)
async def update_config(
    config_data: AgentConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Atualiza a configuração do agente."""
    config = create_or_update_agent_config(
        db,
        personality=config_data.personality,
        restrictions=config_data.restrictions or "",
        model=config_data.model,
        temperature=config_data.temperature,
        max_tokens=config_data.max_tokens,
        allowed_phones=config_data.allowed_phones or "",
        filter_mode=config_data.filter_mode or "all"
    )
    return config


@router.get("/models")
async def get_available_models(
    current_user: User = Depends(require_admin_or_gestao)
):
    """Retorna os modelos de IA disponíveis."""
    return {
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "description": "Modelo mais recente e eficiente"},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "description": "Alta inteligência, respostas detalhadas"},
            {"id": "gpt-4", "name": "GPT-4", "description": "Modelo padrão GPT-4"},
            {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "description": "Mais rápido e econômico"},
        ]
    }
