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
    GESTAO_RV = "gestao_rv"
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
    ZAPI = "zapi"
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
    allowed_phones = Column(Text, nullable=True, default="")
    filter_mode = Column(String(20), default="all")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Assessor(Base):
    """
    Base de Assessores.
    Armazena informações dos assessores para disparo de mensagens e identificação.
    Suporta LID do WhatsApp para identificação por privacidade.
    O campo codigo_ai é obrigatório e usado para vincular campanhas à base de assessores.
    """
    __tablename__ = "assessores"
    
    id = Column(Integer, primary_key=True, index=True)
    codigo_ai = Column(String(50), nullable=False, unique=True, index=True)
    nome = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    telefone_whatsapp = Column(String(20), nullable=True, index=True)
    lid = Column(String(100), nullable=True, index=True)
    unidade = Column(String(255), nullable=True, index=True)
    equipe = Column(String(255), nullable=True, index=True)
    broker_responsavel = Column(String(255), nullable=True, index=True)
    custom_fields = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CustomFieldDefinition(Base):
    """
    Definições de campos customizados para assessores.
    Permite criar novos campos dinamicamente.
    """
    __tablename__ = "custom_field_definitions"
    
    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    field_type = Column(String(50), default="text")
    is_required = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    options = Column(Text, default="[]")
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CampaignStatus(str, enum.Enum):
    """Status possíveis para campanhas."""
    DRAFT = "rascunho"
    PROCESSING = "processando"
    SENT = "enviada"
    FAILED = "falha"


class MessageTemplate(Base):
    """
    Templates de mensagem reutilizáveis para campanhas.
    Suporta variáveis como {{nome_assessor}}, {{lista_clientes}}, etc.
    Pode incluir anexos (imagem, documento, vídeo, áudio).
    """
    __tablename__ = "message_templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    description = Column(String(500), nullable=True)
    is_active = Column(Integer, default=1)
    attachment_url = Column(String(1000), nullable=True)
    attachment_type = Column(String(50), nullable=True)
    attachment_filename = Column(String(255), nullable=True)
    variables_used = Column(Text, default="[]")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    creator = relationship("User", foreign_keys=[created_by])
    campaigns = relationship("Campaign", back_populates="template")


class Campaign(Base):
    """
    Campanha de disparo em massa de mensagens.
    Armazena dados do arquivo, mapeamento e status.
    Suporta estrutura de 3 blocos: cabeçalho, conteúdo repetível, rodapé.
    """
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    status = Column(String(50), default=CampaignStatus.DRAFT.value)
    source_type = Column(String(50), default="upload")
    template_id = Column(Integer, ForeignKey("message_templates.id"), nullable=True)
    custom_template_content = Column(Text, nullable=True)
    message_header = Column(Text, nullable=True)
    message_content_template = Column(Text, nullable=True)
    message_footer = Column(Text, nullable=True)
    group_by_client = Column(Integer, default=0)
    client_id_column = Column(String(255), nullable=True)
    attachment_url = Column(String(1000), nullable=True)
    attachment_type = Column(String(50), nullable=True)
    attachment_filename = Column(String(255), nullable=True)
    column_mapping = Column(Text, default="{}")
    custom_fields_mapping = Column(Text, default="{}")
    original_filename = Column(String(255), nullable=True)
    total_assessors = Column(Integer, default=0)
    total_recommendations = Column(Integer, default=0)
    messages_sent = Column(Integer, default=0)
    messages_failed = Column(Integer, default=0)
    processed_data = Column(Text, default="[]")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    template = relationship("MessageTemplate", back_populates="campaigns")
    creator = relationship("User", foreign_keys=[created_by])
    dispatches = relationship("CampaignDispatch", back_populates="campaign", cascade="all, delete-orphan")


class CampaignDispatch(Base):
    """
    Registro individual de disparo de mensagem para um assessor.
    Armazena a mensagem final e status do envio.
    """
    __tablename__ = "campaign_dispatches"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    assessor_id = Column(String(100), nullable=False)
    assessor_email = Column(String(255), nullable=True, index=True)
    assessor_phone = Column(String(20), nullable=True)
    assessor_name = Column(String(255), nullable=True)
    message_content = Column(Text, nullable=False)
    status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)
    api_response = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    campaign = relationship("Campaign", back_populates="dispatches")


class DocumentType(str, enum.Enum):
    """Tipos de documento na base de conhecimento."""
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    IMAGE = "image"
    OTHER = "other"


class KnowledgeDocument(Base):
    """
    Documentos da base de conhecimento.
    Armazena PDFs, DOCs e outros arquivos para busca semântica.
    """
    __tablename__ = "knowledge_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), default=DocumentType.PDF.value)
    file_size = Column(Integer, default=0)
    category = Column(String(100), nullable=True, index=True)
    chunks_count = Column(Integer, default=0)
    is_indexed = Column(Boolean, default=False)
    index_error = Column(Text, nullable=True)
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    uploader = relationship("User", foreign_keys=[uploaded_by])


class ConversationState(str, enum.Enum):
    """Estado do fluxo da conversa (máquina de estados)."""
    IDENTIFICATION_PENDING = "identification_pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    HUMAN_TAKEOVER = "human_takeover"


class ConversationStatus(str, enum.Enum):
    """Status de atendimento da conversa."""
    BOT_ACTIVE = "bot_active"
    HUMAN_TAKEOVER = "human_takeover"
    CLOSED = "closed"


class TransferReason(str, enum.Enum):
    """Motivos de transferência para humano."""
    EXCESSIVE_SPECIFICITY = "excessive_specificity"
    PERSISTENT_AMBIGUITY = "persistent_ambiguity"
    EXPLICIT_REQUEST = "explicit_request"
    EMOTIONAL_FRICTION = "emotional_friction"
    NO_PROGRESS = "no_progress"
    OTHER = "other"


class SenderType(str, enum.Enum):
    """Tipo de remetente da mensagem."""
    BOT = "bot"
    HUMAN = "human"
    CONTACT = "contact"


class MessageDirection(str, enum.Enum):
    """Direção da mensagem."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, enum.Enum):
    """Tipos de mensagem."""
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    LOCATION = "location"
    CONTACT = "contact"
    UNKNOWN = "unknown"


class Conversation(Base):
    """
    Agrupa mensagens de uma conversa por número de telefone ou LID.
    Permite controle de takeover humano e histórico.
    O LID é o identificador preferencial do WhatsApp para privacidade.
    Inclui máquina de estados para fluxo de identificação e atendimento.
    """
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(50), nullable=True, index=True)
    lid = Column(String(100), nullable=True, index=True)
    chat_lid = Column(String(100), nullable=True, index=True)
    contact_name = Column(String(255), nullable=True)
    contact_photo = Column(String(512), nullable=True)
    assessor_id = Column(Integer, ForeignKey("assessores.id"), nullable=True)
    status = Column(String(30), default=ConversationStatus.BOT_ACTIVE.value)
    conversation_state = Column(String(30), default=ConversationState.IDENTIFICATION_PENDING.value)
    transfer_reason = Column(String(50), nullable=True)
    transfer_notes = Column(Text, nullable=True)
    transferred_at = Column(DateTime(timezone=True), nullable=True)
    stalled_interactions = Column(Integer, default=0)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message_preview = Column(String(255), nullable=True)
    unread_count = Column(Integer, default=0)
    lid_source = Column(String(50), nullable=True)
    lid_collected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    assessor = relationship("Assessor", foreign_keys=[assessor_id])
    assigned_user = relationship("User", foreign_keys=[assigned_to])
    messages = relationship("WhatsAppMessage", back_populates="conversation", order_by="WhatsAppMessage.created_at")


class MessageStatus(str, enum.Enum):
    """Status da mensagem no WhatsApp."""
    PENDING = "PENDING"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    READ = "READ"
    PLAYED = "PLAYED"
    FAILED = "FAILED"


class WhatsAppMessage(Base):
    """
    Registro de mensagens do WhatsApp.
    Armazena todas as mensagens recebidas e enviadas.
    Compatível com Z-API.
    """
    __tablename__ = "whatsapp_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(255), unique=True, index=True, nullable=True)
    zaap_id = Column(String(255), index=True, nullable=True)
    chat_id = Column(String(100), nullable=False, index=True)
    phone = Column(String(20), nullable=True, index=True)
    from_me = Column(Boolean, default=False)
    direction = Column(String(20), default=MessageDirection.INBOUND.value)
    message_type = Column(String(20), default=MessageType.TEXT.value)
    message_status = Column(String(20), default=MessageStatus.PENDING.value)
    sender_type = Column(String(20), default=SenderType.CONTACT.value)
    sender_name = Column(String(255), nullable=True)
    sender_photo = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)
    media_url = Column(String(500), nullable=True)
    media_mimetype = Column(String(100), nullable=True)
    media_filename = Column(String(255), nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    transcription = Column(Text, nullable=True)
    ai_response = Column(Text, nullable=True)
    ai_intent = Column(String(100), nullable=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    is_from_campaign = Column(Boolean, default=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    ticket = relationship("Ticket", foreign_keys=[ticket_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    conversation = relationship("Conversation", back_populates="messages")
