"""
Modelos SQLAlchemy para o banco de dados.
Define as tabelas User, Ticket, Interaction, TicketCategory e Integration.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.database import Base
import enum


class UserRole(str, enum.Enum):
    """Roles disponíveis para usuários."""
    ADMIN = "admin"
    BROKER = "broker"
    CLIENT = "client"


class TicketStatus(str, enum.Enum):
    """Status possíveis para tickets."""
    OPEN = "Aberto"
    IN_PROGRESS = "Em Andamento"
    CLOSED = "Concluído"


class TicketCategory(Base):
    """
    Categorias de tickets para classificação de dúvidas.
    Permite análise por tipo de demanda.
    """
    __tablename__ = "ticket_categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    color = Column(String(7), default="#6366f1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    tickets = relationship("Ticket", back_populates="category")


class Interaction(Base):
    """
    Registro de interações/atendimentos.
    Cada mensagem ou contato gera uma interação.
    """
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    broker_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    client_phone = Column(String(20), nullable=True)
    channel = Column(String(50), default="whatsapp")
    direction = Column(String(20), default="inbound")
    message_preview = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    ticket = relationship("Ticket", back_populates="interactions")
    client = relationship("User", foreign_keys=[client_id])
    broker = relationship("User", foreign_keys=[broker_id])


class User(Base):
    """
    Modelo de usuário.
    Pode ser admin, broker ou cliente.
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    role = Column(String(20), default=UserRole.CLIENT.value)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relacionamento com tickets (como cliente)
    tickets = relationship("Ticket", back_populates="client", foreign_keys="Ticket.client_id")
    # Tickets atribuídos (como broker)
    assigned_tickets = relationship("Ticket", back_populates="broker", foreign_keys="Ticket.broker_id")


class Ticket(Base):
    """
    Modelo de ticket/chamado.
    Representa uma solicitação de suporte do cliente.
    """
    __tablename__ = "tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default=TicketStatus.OPEN.value)
    
    # Relacionamento com cliente
    client_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    client = relationship("User", back_populates="tickets", foreign_keys=[client_id])
    
    # Relacionamento com broker responsável
    broker_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    broker = relationship("User", back_populates="assigned_tickets", foreign_keys=[broker_id])
    
    # Categoria do ticket para análise
    category_id = Column(Integer, ForeignKey("ticket_categories.id"), nullable=True)
    category = relationship("TicketCategory", back_populates="tickets")
    
    # Número do WhatsApp do cliente (caso não tenha cadastro)
    client_phone = Column(String(20), nullable=True)
    
    # Flag de interesse identificado
    interest_identified = Column(Boolean, default=False)
    interest_identified_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Interações relacionadas
    interactions = relationship("Interaction", back_populates="ticket")


class IntegrationType(str, enum.Enum):
    """Tipos de integração disponíveis."""
    OPENAI = "openai"
    NOTION = "notion"
    WAHA = "waha"
    CUSTOM = "custom"


class Integration(Base):
    """
    Modelo para armazenar configurações de integrações.
    Cada integração pode ter múltiplas configurações (chaves, URLs, etc).
    """
    __tablename__ = "integrations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    type = Column(String(50), nullable=False)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    settings = relationship("IntegrationSetting", back_populates="integration", cascade="all, delete-orphan")


class IntegrationSetting(Base):
    """
    Configurações individuais de uma integração.
    Cada integração pode ter múltiplas configurações.
    """
    __tablename__ = "integration_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)
    is_secret = Column(Integer, default=0)
    description = Column(String(255), nullable=True)
    
    integration = relationship("Integration", back_populates="settings")


class AgentConfig(Base):
    """
    Configuração do agente de IA.
    Armazena personalidade, modelo, temperatura e outras configurações.
    Apenas um registro ativo por vez (singleton pattern).
    """
    __tablename__ = "agent_config"
    
    id = Column(Integer, primary_key=True, index=True)
    personality = Column(Text, nullable=False, default="")
    restrictions = Column(Text, nullable=True, default="")
    model = Column(String(50), default="gpt-4o")
    temperature = Column(String(10), default="0.7")
    max_tokens = Column(Integer, default=500)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
