"""
Endpoints para gerenciamento de fontes confiáveis da web.
Permite administradores configurarem os domínios permitidos para pesquisa.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from database.database import get_db
from database.models import TrustedSource, User, UserRole
from api.endpoints.auth import get_current_user

router = APIRouter(prefix="/api/trusted-sources", tags=["Trusted Sources"])


class TrustedSourceCreate(BaseModel):
    domain: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = "geral"
    priority: Optional[int] = 5


class TrustedSourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class TrustedSourceResponse(BaseModel):
    id: int
    domain: str
    name: str
    description: Optional[str]
    category: str
    is_active: bool
    priority: int
    
    class Config:
        from_attributes = True


def require_admin_or_gestao(current_user: User = Depends(get_current_user)):
    """Verifica se o usuário é admin ou gestao_rv."""
    if current_user.role not in [UserRole.ADMIN.value, UserRole.GESTOR.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores e gestão RV"
        )
    return current_user


@router.get("/", response_model=List[TrustedSourceResponse])
def list_trusted_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Lista todas as fontes confiáveis."""
    sources = db.query(TrustedSource).order_by(
        TrustedSource.priority.desc(),
        TrustedSource.name
    ).all()
    return sources


@router.post("/", response_model=TrustedSourceResponse)
def create_trusted_source(
    source: TrustedSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Adiciona uma nova fonte confiável."""
    domain = source.domain.lower().strip()
    domain = domain.replace("https://", "").replace("http://", "").replace("www.", "")
    domain = domain.rstrip("/")
    
    existing = db.query(TrustedSource).filter(TrustedSource.domain == domain).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este domínio já está cadastrado"
        )
    
    new_source = TrustedSource(
        domain=domain,
        name=source.name,
        description=source.description,
        category=source.category or "geral",
        priority=source.priority or 5
    )
    db.add(new_source)
    db.commit()
    db.refresh(new_source)
    
    return new_source


@router.put("/{source_id}", response_model=TrustedSourceResponse)
def update_trusted_source(
    source_id: int,
    update: TrustedSourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Atualiza uma fonte confiável."""
    source = db.query(TrustedSource).filter(TrustedSource.id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fonte não encontrada"
        )
    
    if update.name is not None:
        source.name = update.name
    if update.description is not None:
        source.description = update.description
    if update.category is not None:
        source.category = update.category
    if update.priority is not None:
        source.priority = update.priority
    if update.is_active is not None:
        source.is_active = update.is_active
    
    db.commit()
    db.refresh(source)
    
    return source


@router.delete("/{source_id}")
def delete_trusted_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """Remove uma fonte confiável."""
    source = db.query(TrustedSource).filter(TrustedSource.id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fonte não encontrada"
        )
    
    db.delete(source)
    db.commit()
    
    return {"message": "Fonte removida com sucesso"}


@router.post("/seed-defaults")
def seed_default_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """
    Popula o banco com as fontes padrão.
    Só adiciona fontes que ainda não existem.
    """
    default_sources = [
        {"domain": "infomoney.com.br", "name": "InfoMoney", "category": "noticias", "priority": 10},
        {"domain": "statusinvest.com.br", "name": "Status Invest", "category": "dados", "priority": 10},
        {"domain": "fundsexplorer.com.br", "name": "Funds Explorer", "category": "fiis", "priority": 10},
        {"domain": "valorinveste.globo.com", "name": "Valor Investe", "category": "noticias", "priority": 8},
        {"domain": "b3.com.br", "name": "B3", "category": "oficial", "priority": 10},
        {"domain": "investing.com", "name": "Investing.com", "category": "dados", "priority": 7},
        {"domain": "moneytimes.com.br", "name": "Money Times", "category": "noticias", "priority": 7},
        {"domain": "suno.com.br", "name": "Suno Research", "category": "analises", "priority": 8},
        {"domain": "trademap.com.br", "name": "TradeMap", "category": "dados", "priority": 8},
        {"domain": "clubefii.com.br", "name": "Clube FII", "category": "fiis", "priority": 8},
    ]
    
    added = 0
    for source_data in default_sources:
        existing = db.query(TrustedSource).filter(
            TrustedSource.domain == source_data["domain"]
        ).first()
        
        if not existing:
            new_source = TrustedSource(
                domain=source_data["domain"],
                name=source_data["name"],
                category=source_data["category"],
                priority=source_data["priority"],
                description=f"Fonte confiável para {source_data['category']}"
            )
            db.add(new_source)
            added += 1
    
    db.commit()
    
    return {"message": f"{added} fontes adicionadas com sucesso"}


@router.get("/test-search")
async def test_web_search(
    query: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_gestao)
):
    """
    Endpoint de teste para verificar a busca na web.
    """
    from services.web_search import get_web_search_service
    
    service = get_web_search_service()
    
    if not service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TAVILY_API_KEY não configurada. Adicione a chave nas configurações de ambiente."
        )
    
    result = service.search_sync(query, db=db)
    
    if result.get("success"):
        service.log_search(
            db=db,
            query=query,
            results=result,
            fallback_reason="Teste manual",
            user_id=current_user.id
        )
    
    return result
