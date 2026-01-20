"""
Funções CRUD (Create, Read, Update, Delete) para usuários, tickets e analytics.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func, distinct
from typing import List, Optional
from datetime import datetime, date
from database.models import (
    User, Ticket, TicketStatus, Integration, IntegrationSetting,
    TicketCategory, Interaction, UserRole, AgentConfig
)
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
    """Atualiza o status de um ticket e registra resolved_at se concluído."""
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None
    db_ticket.status = status
    if status == TicketStatus.CLOSED.value and not db_ticket.resolved_at:
        db_ticket.resolved_at = datetime.utcnow()
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


# ========== CRUD de Categorias ==========

def get_category(db: Session, category_id: int) -> Optional[TicketCategory]:
    """Busca uma categoria pelo ID."""
    return db.query(TicketCategory).filter(TicketCategory.id == category_id).first()


def get_category_by_name(db: Session, name: str) -> Optional[TicketCategory]:
    """Busca uma categoria pelo nome."""
    return db.query(TicketCategory).filter(TicketCategory.name == name).first()


def get_categories(db: Session) -> List[TicketCategory]:
    """Lista todas as categorias."""
    return db.query(TicketCategory).all()


def create_category(db: Session, name: str, description: str = None, color: str = "#6366f1") -> TicketCategory:
    """Cria uma nova categoria."""
    db_category = TicketCategory(name=name, description=description, color=color)
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


def init_default_categories(db: Session):
    """Inicializa categorias padrão."""
    default_categories = [
        {"name": "Investimentos", "description": "Dúvidas sobre investimentos", "color": "#10b981"},
        {"name": "Conta", "description": "Problemas com conta", "color": "#3b82f6"},
        {"name": "Transferências", "description": "Transferências e PIX", "color": "#8b5cf6"},
        {"name": "Produtos", "description": "Informações sobre produtos", "color": "#f59e0b"},
        {"name": "Suporte Técnico", "description": "Problemas técnicos", "color": "#ef4444"},
        {"name": "Outros", "description": "Outros assuntos", "color": "#6b7280"},
    ]
    for cat_data in default_categories:
        if not get_category_by_name(db, cat_data["name"]):
            create_category(db, **cat_data)


# ========== CRUD de Interações ==========

def create_interaction(
    db: Session,
    ticket_id: int = None,
    client_id: int = None,
    broker_id: int = None,
    client_phone: str = None,
    channel: str = "whatsapp",
    direction: str = "inbound",
    message_preview: str = None
) -> Interaction:
    """Registra uma nova interação."""
    db_interaction = Interaction(
        ticket_id=ticket_id,
        client_id=client_id,
        broker_id=broker_id,
        client_phone=client_phone,
        channel=channel,
        direction=direction,
        message_preview=message_preview[:255] if message_preview else None
    )
    db.add(db_interaction)
    db.commit()
    db.refresh(db_interaction)
    return db_interaction


def get_interactions(
    db: Session,
    start_date: date = None,
    end_date: date = None
) -> List[Interaction]:
    """Lista interações com filtro de data."""
    query = db.query(Interaction)
    if start_date:
        query = query.filter(Interaction.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Interaction.created_at <= datetime.combine(end_date, datetime.max.time()))
    return query.all()


# ========== Analytics ==========

def get_analytics_summary(db: Session, start_date: date = None, end_date: date = None) -> dict:
    """
    Retorna métricas agregadas para o dashboard.
    """
    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None
    
    def date_filter(query, date_column):
        if start_dt:
            query = query.filter(date_column >= start_dt)
        if end_dt:
            query = query.filter(date_column <= end_dt)
        return query
    
    # 1. Quantidade de atendimentos (interações)
    interactions_query = db.query(sql_func.count(Interaction.id))
    interactions_query = date_filter(interactions_query, Interaction.created_at)
    total_atendimentos = interactions_query.scalar() or 0
    
    # 2. Tickets abertos
    open_tickets_query = db.query(sql_func.count(Ticket.id)).filter(
        Ticket.status.in_([TicketStatus.OPEN.value, TicketStatus.IN_PROGRESS.value])
    )
    open_tickets_query = date_filter(open_tickets_query, Ticket.created_at)
    chamados_abertos = open_tickets_query.scalar() or 0
    
    # 3. Tickets concluídos
    closed_tickets_query = db.query(sql_func.count(Ticket.id)).filter(
        Ticket.status == TicketStatus.CLOSED.value
    )
    closed_tickets_query = date_filter(closed_tickets_query, Ticket.resolved_at)
    chamados_concluidos = closed_tickets_query.scalar() or 0
    
    # 4. Assessores ativos (brokers com tickets atribuídos no período)
    active_brokers_query = db.query(sql_func.count(distinct(Ticket.broker_id))).filter(
        Ticket.broker_id.isnot(None)
    )
    active_brokers_query = date_filter(active_brokers_query, Ticket.created_at)
    assessores_ativos = active_brokers_query.scalar() or 0
    
    # 5. Clientes contactados (únicos por telefone ou ID)
    clients_by_id = db.query(sql_func.count(distinct(Interaction.client_id))).filter(
        Interaction.client_id.isnot(None)
    )
    clients_by_id = date_filter(clients_by_id, Interaction.created_at)
    
    clients_by_phone = db.query(sql_func.count(distinct(Interaction.client_phone))).filter(
        Interaction.client_phone.isnot(None),
        Interaction.client_id.is_(None)
    )
    clients_by_phone = date_filter(clients_by_phone, Interaction.created_at)
    
    clientes_contactados = (clients_by_id.scalar() or 0) + (clients_by_phone.scalar() or 0)
    
    # 6. Clientes com interesse identificado
    interest_query = db.query(sql_func.count(distinct(Ticket.client_id))).filter(
        Ticket.interest_identified == True
    )
    interest_query = date_filter(interest_query, Ticket.interest_identified_at)
    clientes_com_interesse = interest_query.scalar() or 0
    
    return {
        "total_atendimentos": total_atendimentos,
        "chamados_abertos": chamados_abertos,
        "chamados_concluidos": chamados_concluidos,
        "assessores_ativos": assessores_ativos,
        "clientes_contactados": clientes_contactados,
        "clientes_com_interesse": clientes_com_interesse,
    }


def get_resolution_time_by_broker(db: Session, start_date: date = None, end_date: date = None) -> List[dict]:
    """
    Calcula o tempo médio de resolução por assessor.
    """
    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None
    
    query = db.query(Ticket).filter(
        Ticket.resolved_at.isnot(None),
        Ticket.broker_id.isnot(None)
    )
    
    if start_dt:
        query = query.filter(Ticket.resolved_at >= start_dt)
    if end_dt:
        query = query.filter(Ticket.resolved_at <= end_dt)
    
    tickets = query.all()
    
    broker_stats = {}
    for ticket in tickets:
        broker_id = ticket.broker_id
        if broker_id not in broker_stats:
            broker = db.query(User).filter(User.id == broker_id).first()
            broker_stats[broker_id] = {
                "broker_id": broker_id,
                "broker_name": broker.username if broker else "Desconhecido",
                "total_tickets": 0,
                "total_hours": 0
            }
        
        if ticket.resolved_at and ticket.created_at:
            diff = ticket.resolved_at - ticket.created_at
            hours = diff.total_seconds() / 3600
            broker_stats[broker_id]["total_tickets"] += 1
            broker_stats[broker_id]["total_hours"] += hours
    
    result = []
    for broker_id, stats in broker_stats.items():
        avg_hours = stats["total_hours"] / stats["total_tickets"] if stats["total_tickets"] > 0 else 0
        result.append({
            "broker_id": stats["broker_id"],
            "broker_name": stats["broker_name"],
            "total_tickets": stats["total_tickets"],
            "avg_resolution_hours": round(avg_hours, 1)
        })
    
    return result


def get_tickets_by_category(db: Session, start_date: date = None, end_date: date = None) -> List[dict]:
    """
    Conta tickets por categoria.
    """
    start_dt = datetime.combine(start_date, datetime.min.time()) if start_date else None
    end_dt = datetime.combine(end_date, datetime.max.time()) if end_date else None
    
    query = db.query(
        TicketCategory.id,
        TicketCategory.name,
        TicketCategory.color,
        sql_func.count(Ticket.id).label('count')
    ).outerjoin(Ticket, Ticket.category_id == TicketCategory.id)
    
    if start_dt:
        query = query.filter((Ticket.created_at >= start_dt) | (Ticket.created_at.is_(None)))
    if end_dt:
        query = query.filter((Ticket.created_at <= end_dt) | (Ticket.created_at.is_(None)))
    
    query = query.group_by(TicketCategory.id, TicketCategory.name, TicketCategory.color)
    
    results = query.all()
    
    # Adiciona tickets sem categoria
    uncategorized_query = db.query(sql_func.count(Ticket.id)).filter(
        Ticket.category_id.is_(None)
    )
    if start_dt:
        uncategorized_query = uncategorized_query.filter(Ticket.created_at >= start_dt)
    if end_dt:
        uncategorized_query = uncategorized_query.filter(Ticket.created_at <= end_dt)
    
    uncategorized_count = uncategorized_query.scalar() or 0
    
    category_list = [
        {
            "category_id": r.id,
            "category_name": r.name,
            "color": r.color,
            "count": r.count
        }
        for r in results
    ]
    
    if uncategorized_count > 0:
        category_list.append({
            "category_id": None,
            "category_name": "Sem Categoria",
            "color": "#9ca3af",
            "count": uncategorized_count
        })
    
    return category_list


# ========== CRUD de Configuração do Agente ==========

def get_agent_config(db: Session) -> Optional[AgentConfig]:
    """Busca a configuração ativa do agente."""
    return db.query(AgentConfig).filter(AgentConfig.is_active == 1).first()


def create_or_update_agent_config(
    db: Session,
    personality: str,
    restrictions: str = "",
    model: str = "gpt-4o",
    temperature: str = "0.7",
    max_tokens: int = 500
) -> AgentConfig:
    """Cria ou atualiza a configuração do agente."""
    existing = get_agent_config(db)
    
    if existing:
        existing.personality = personality
        existing.restrictions = restrictions
        existing.model = model
        existing.temperature = temperature
        existing.max_tokens = max_tokens
        db.commit()
        db.refresh(existing)
        return existing
    
    config = AgentConfig(
        personality=personality,
        restrictions=restrictions,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        is_active=1
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def init_default_agent_config(db: Session):
    """Inicializa configuração padrão do agente se não existir."""
    existing = get_agent_config(db)
    if not existing:
        default_personality = """Você é um assistente virtual especializado em assessoria financeira.
Seu papel é ajudar clientes com dúvidas sobre investimentos, produtos financeiros e serviços.

REGRAS IMPORTANTES:
1. Responda sempre de forma educada e profissional.
2. Use o contexto fornecido para basear suas respostas.
3. Se a informação não estiver disponível no contexto, seja honesto e diga que não tem essa informação.
4. Quando não puder ajudar adequadamente, pergunte se o cliente deseja abrir um chamado para falar com um assessor.
5. Mantenha as respostas concisas e objetivas, adequadas para WhatsApp.
6. Nunca invente informações sobre produtos, taxas ou valores.

Para abrir um chamado, o usuário deve responder "SIM" ou "sim" quando perguntado."""
        
        default_restrictions = """- Nunca forneça conselhos financeiros específicos ou recomendações de investimento.
- Não mencione valores ou taxas a menos que estejam documentados na base de conhecimento.
- Não prometa resultados ou retornos financeiros.
- Não compartilhe informações de outros clientes.
- Não faça operações financeiras em nome do cliente."""
        
        create_or_update_agent_config(
            db,
            personality=default_personality,
            restrictions=default_restrictions,
            model="gpt-4o",
            temperature="0.7",
            max_tokens=500
        )
