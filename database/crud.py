"""
Funções CRUD (Create, Read, Update, Delete) para usuários e tickets.
"""
from sqlalchemy.orm import Session
from typing import List, Optional
from database.models import User, Ticket, TicketStatus, Integration, IntegrationSetting
from core.security import get_password_hash, verify_password


# ========== CRUD de Usuários ==========

def get_user(db: Session, user_id: int) -> Optional[User]:
    """Busca um usuário pelo ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Busca um usuário pelo nome de usuário."""
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Busca um usuário pelo email."""
    return db.query(User).filter(User.email == email).first()


def get_user_by_phone(db: Session, phone: str) -> Optional[User]:
    """Busca um usuário pelo número de telefone."""
    return db.query(User).filter(User.phone == phone).first()


def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[User]:
    """Lista todos os usuários com paginação."""
    return db.query(User).offset(skip).limit(limit).all()


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    phone: Optional[str] = None,
    role: str = "client"
) -> User:
    """Cria um novo usuário com senha hasheada."""
    hashed_password = get_password_hash(password)
    db_user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        phone=phone,
        role=role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def update_user(db: Session, user_id: int, **kwargs) -> Optional[User]:
    """Atualiza um usuário existente."""
    db_user = get_user(db, user_id)
    if not db_user:
        return None
    
    for key, value in kwargs.items():
        if hasattr(db_user, key) and value is not None:
            if key == "password":
                setattr(db_user, "hashed_password", get_password_hash(value))
            else:
                setattr(db_user, key, value)
    
    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    """Deleta um usuário pelo ID."""
    db_user = get_user(db, user_id)
    if not db_user:
        return False
    db.delete(db_user)
    db.commit()
    return True


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Autentica um usuário verificando username e senha."""
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


# ========== CRUD de Tickets ==========

def get_ticket(db: Session, ticket_id: int) -> Optional[Ticket]:
    """Busca um ticket pelo ID."""
    return db.query(Ticket).filter(Ticket.id == ticket_id).first()


def get_tickets(db: Session, skip: int = 0, limit: int = 100) -> List[Ticket]:
    """Lista todos os tickets com paginação."""
    return db.query(Ticket).offset(skip).limit(limit).all()


def get_tickets_by_status(db: Session, status: str) -> List[Ticket]:
    """Lista tickets por status."""
    return db.query(Ticket).filter(Ticket.status == status).all()


def get_tickets_by_broker(db: Session, broker_id: int) -> List[Ticket]:
    """Lista tickets atribuídos a um broker específico."""
    return db.query(Ticket).filter(Ticket.broker_id == broker_id).all()


def create_ticket(
    db: Session,
    title: str,
    description: Optional[str] = None,
    client_id: Optional[int] = None,
    client_phone: Optional[str] = None,
    broker_id: Optional[int] = None
) -> Ticket:
    """Cria um novo ticket."""
    db_ticket = Ticket(
        title=title,
        description=description,
        client_id=client_id,
        client_phone=client_phone,
        broker_id=broker_id,
        status=TicketStatus.OPEN.value
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def update_ticket_status(db: Session, ticket_id: int, status: str) -> Optional[Ticket]:
    """Atualiza o status de um ticket."""
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None
    db_ticket.status = status
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def update_ticket(db: Session, ticket_id: int, **kwargs) -> Optional[Ticket]:
    """Atualiza um ticket existente."""
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None
    
    for key, value in kwargs.items():
        if hasattr(db_ticket, key) and value is not None:
            setattr(db_ticket, key, value)
    
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def delete_ticket(db: Session, ticket_id: int) -> bool:
    """Deleta um ticket pelo ID."""
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return False
    db.delete(db_ticket)
    db.commit()
    return True


# ========== CRUD de Integrações ==========

def get_integration(db: Session, integration_id: int) -> Optional[Integration]:
    """Busca uma integração pelo ID."""
    return db.query(Integration).filter(Integration.id == integration_id).first()


def get_integration_by_name(db: Session, name: str) -> Optional[Integration]:
    """Busca uma integração pelo nome."""
    return db.query(Integration).filter(Integration.name == name).first()


def get_integration_by_type(db: Session, integration_type: str) -> Optional[Integration]:
    """Busca uma integração pelo tipo."""
    return db.query(Integration).filter(Integration.type == integration_type).first()


def get_integrations(db: Session, skip: int = 0, limit: int = 100) -> List[Integration]:
    """Lista todas as integrações com paginação."""
    return db.query(Integration).offset(skip).limit(limit).all()


def create_integration(
    db: Session,
    name: str,
    integration_type: str,
    is_active: bool = True
) -> Integration:
    """Cria uma nova integração."""
    db_integration = Integration(
        name=name,
        type=integration_type,
        is_active=1 if is_active else 0
    )
    db.add(db_integration)
    db.commit()
    db.refresh(db_integration)
    return db_integration


def update_integration(db: Session, integration_id: int, **kwargs) -> Optional[Integration]:
    """Atualiza uma integração existente."""
    db_integration = get_integration(db, integration_id)
    if not db_integration:
        return None
    
    for key, value in kwargs.items():
        if hasattr(db_integration, key) and value is not None:
            if key == "is_active":
                setattr(db_integration, key, 1 if value else 0)
            else:
                setattr(db_integration, key, value)
    
    db.commit()
    db.refresh(db_integration)
    return db_integration


def delete_integration(db: Session, integration_id: int) -> bool:
    """Deleta uma integração pelo ID."""
    db_integration = get_integration(db, integration_id)
    if not db_integration:
        return False
    db.delete(db_integration)
    db.commit()
    return True


# ========== CRUD de Configurações de Integração ==========

def get_integration_setting(db: Session, setting_id: int) -> Optional[IntegrationSetting]:
    """Busca uma configuração pelo ID."""
    return db.query(IntegrationSetting).filter(IntegrationSetting.id == setting_id).first()


def get_integration_settings(db: Session, integration_id: int) -> List[IntegrationSetting]:
    """Lista todas as configurações de uma integração."""
    return db.query(IntegrationSetting).filter(
        IntegrationSetting.integration_id == integration_id
    ).all()


def get_integration_setting_by_key(
    db: Session, 
    integration_id: int, 
    key: str
) -> Optional[IntegrationSetting]:
    """Busca uma configuração pelo nome da chave."""
    return db.query(IntegrationSetting).filter(
        IntegrationSetting.integration_id == integration_id,
        IntegrationSetting.key == key
    ).first()


def create_or_update_setting(
    db: Session,
    integration_id: int,
    key: str,
    value: str,
    is_secret: bool = False,
    description: Optional[str] = None
) -> IntegrationSetting:
    """Cria ou atualiza uma configuração de integração."""
    existing = get_integration_setting_by_key(db, integration_id, key)
    
    if existing:
        existing.value = value
        existing.is_secret = 1 if is_secret else 0
        if description:
            existing.description = description
        db.commit()
        db.refresh(existing)
        return existing
    
    db_setting = IntegrationSetting(
        integration_id=integration_id,
        key=key,
        value=value,
        is_secret=1 if is_secret else 0,
        description=description
    )
    db.add(db_setting)
    db.commit()
    db.refresh(db_setting)
    return db_setting


def delete_integration_setting(db: Session, setting_id: int) -> bool:
    """Deleta uma configuração pelo ID."""
    db_setting = get_integration_setting(db, setting_id)
    if not db_setting:
        return False
    db.delete(db_setting)
    db.commit()
    return True


def init_default_integrations(db: Session):
    """
    Inicializa as integrações padrão no banco de dados.
    Chamado na inicialização da aplicação.
    """
    default_integrations = [
        {
            "name": "OpenAI",
            "type": "openai",
            "settings": [
                {"key": "api_key", "description": "Chave da API OpenAI", "is_secret": True},
                {"key": "model", "description": "Modelo a ser usado (ex: gpt-4)", "is_secret": False},
                {"key": "max_tokens", "description": "Máximo de tokens por resposta", "is_secret": False},
                {"key": "temperature", "description": "Temperatura (criatividade) 0-1", "is_secret": False},
            ]
        },
        {
            "name": "Notion",
            "type": "notion",
            "settings": [
                {"key": "api_key", "description": "Token de integração do Notion", "is_secret": True},
                {"key": "database_id", "description": "ID do banco de dados do Notion", "is_secret": False},
                {"key": "parent_page_id", "description": "ID da página pai (opcional)", "is_secret": False},
            ]
        },
        {
            "name": "WhatsApp (WAHA)",
            "type": "waha",
            "settings": [
                {"key": "api_url", "description": "URL da API WAHA", "is_secret": False},
                {"key": "api_key", "description": "Chave de autenticação WAHA", "is_secret": True},
                {"key": "session_name", "description": "Nome da sessão WhatsApp", "is_secret": False},
                {"key": "webhook_url", "description": "URL do webhook para receber mensagens", "is_secret": False},
            ]
        },
    ]
    
    for integration_data in default_integrations:
        existing = get_integration_by_name(db, integration_data["name"])
        if not existing:
            integration = create_integration(
                db,
                name=integration_data["name"],
                integration_type=integration_data["type"],
                is_active=False
            )
            for setting in integration_data["settings"]:
                create_or_update_setting(
                    db,
                    integration_id=integration.id,
                    key=setting["key"],
                    value="",
                    is_secret=setting.get("is_secret", False),
                    description=setting.get("description")
                )
