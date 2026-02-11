"""
Modelos SQLAlchemy para o banco de dados.
Define as tabelas User, Ticket, Interaction, TicketCategory e Integration.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.database import Base
from datetime import datetime
import enum


class UserRole(str, enum.Enum):
    """Roles disponíveis para usuários."""
    ADMIN = "admin"
    GESTOR = "gestao_rv"
    BROKER = "broker"


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
    Pode ser admin, gestor ou broker.
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    first_name = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    role = Column(String(20), default=UserRole.BROKER.value)
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


class TrustedSource(Base):
    """
    Fontes confiáveis para busca na web.
    Define os domínios permitidos para o agente pesquisar.
    """
    __tablename__ = "trusted_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), default="geral")
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WebSearchLog(Base):
    """
    Log de buscas na web realizadas pelo agente.
    Auditoria completa de pesquisas externas.
    """
    __tablename__ = "web_search_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    sources_searched = Column(Text, nullable=True)
    results_count = Column(Integer, default=0)
    facts_extracted = Column(Text, nullable=True)
    citations = Column(Text, nullable=True)
    fallback_reason = Column(String(255), nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    conversation_id = Column(String(100), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", foreign_keys=[user_id])


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
    macro_area = Column(String(255), nullable=True, index=True)
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
    COMPLETED = "completed"


class ConversationStatus(str, enum.Enum):
    """Status de atendimento da conversa."""
    BOT_ACTIVE = "bot_active"
    HUMAN_TAKEOVER = "human_takeover"
    CLOSED = "closed"


# ==================== ZENDESK-LIKE TICKET SYSTEM ====================

class TicketStatusV2(str, enum.Enum):
    """Status de ticket estilo Zendesk para a V2."""
    NEW = "new"                    # Mensagem nova, ainda não processada
    OPEN = "open"                  # Bot tentando resolver
    IN_PROGRESS = "in_progress"    # Humano ou bot trabalhando
    SOLVED = "solved"              # Resolvido


class EscalationLevel(str, enum.Enum):
    """Nível de escalonamento do atendimento."""
    T0_BOT = "t0"      # Tier 0 - Bot (autoatendimento)
    T1_HUMAN = "t1"    # Tier 1 - Humano


class TicketHistoryActionType(str, enum.Enum):
    """Tipos de ação para histórico de ticket."""
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    ESCALATED = "escalated"
    REOPENED = "reopened"
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    SLA_BREACHED = "sla_breached"


class TransferReason(str, enum.Enum):
    """Motivos de transferência para humano."""
    EXCESSIVE_SPECIFICITY = "excessive_specificity"
    PERSISTENT_AMBIGUITY = "persistent_ambiguity"
    EXPLICIT_REQUEST = "explicit_request"
    EMOTIONAL_FRICTION = "emotional_friction"
    NO_PROGRESS = "no_progress"
    OTHER = "other"


class EscalationCategory(str, enum.Enum):
    """Categoria do motivo de escalação para humano."""
    OUT_OF_SCOPE = "out_of_scope"
    INFO_NOT_FOUND = "info_not_found"
    TECHNICAL_COMPLEXITY = "technical_complexity"
    OUTDATED_DATA = "outdated_data"
    COMMERCIAL_REQUEST = "commercial_request"
    DECLARED_URGENCY = "declared_urgency"
    EXPLICIT_HUMAN_REQUEST = "explicit_human_request"
    COMPLAINT = "complaint"
    OPERATION_CONFIRMATION = "operation_confirmation"
    MULTIPLE_FAILED_ATTEMPTS = "multiple_failed_attempts"
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


class ResolutionCategory(str, enum.Enum):
    """Categorias de resolução de tickets."""
    INFORMATION_PROVIDED = "information_provided"
    DOCUMENT_SENT = "document_sent"
    REDIRECTED_TO_SPECIALIST = "redirected_to_specialist"
    ISSUE_RESOLVED = "issue_resolved"
    CLIENT_SATISFIED = "client_satisfied"
    NO_FURTHER_ACTION = "no_further_action"
    ESCALATED_INTERNALLY = "escalated_internally"
    OTHER = "other"


class ConversationTicket(Base):
    """
    Representa cada instância de atendimento humano.
    Uma Conversation pode ter múltiplos tickets ao longo do tempo.
    Preserva histórico de cada chamado separadamente.
    """
    __tablename__ = "conversation_tickets"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    ticket_number = Column(Integer, nullable=False)
    
    status = Column(String(20), default=TicketStatusV2.NEW.value, index=True)
    escalation_level = Column(String(10), default=EscalationLevel.T1_HUMAN.value)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    escalation_category = Column(String(50), nullable=True, index=True)
    escalation_reason_detail = Column(Text, nullable=True)
    ticket_summary = Column(Text, nullable=True)
    conversation_topic = Column(String(100), nullable=True)
    transfer_reason = Column(String(50), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    transferred_at = Column(DateTime(timezone=True), nullable=True)
    first_response_at = Column(DateTime(timezone=True), nullable=True)
    first_human_response_at = Column(DateTime(timezone=True), nullable=True)
    solved_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    resolution_time_seconds = Column(Integer, nullable=True)
    resolution_category = Column(String(50), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    contributed_to_kb = Column(Boolean, default=False)
    kb_contribution_id = Column(Integer, nullable=True)
    
    conversation = relationship("Conversation", back_populates="tickets", foreign_keys=[conversation_id])
    assigned_user = relationship("User", foreign_keys=[assigned_to])


class Conversation(Base):
    """
    Agrupa mensagens de uma conversa por número de telefone ou LID.
    Permite controle de takeover humano e histórico.
    O LID é o identificador preferencial do WhatsApp para privacidade.
    Inclui máquina de estados para fluxo de identificação e atendimento.
    V2: Inclui campos de ticket estilo Zendesk para fila de atendimento.
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
    
    # V2 Zendesk-like ticket fields (campos opcionais para compatibilidade)
    # ticket_status=None para conversas com bot, NEW apenas quando escalado para humano
    ticket_status = Column(String(20), nullable=True, index=True)
    escalation_level = Column(String(10), default=EscalationLevel.T0_BOT.value, index=True)
    first_response_at = Column(DateTime(timezone=True), nullable=True)
    solved_at = Column(DateTime(timezone=True), nullable=True)
    sla_due_at = Column(DateTime(timezone=True), nullable=True)
    reopened_count = Column(Integer, default=0)
    last_assigned_at = Column(DateTime(timezone=True), nullable=True)
    
    # V2.1 Escalation intelligence fields
    escalation_category = Column(String(50), nullable=True, index=True)
    escalation_reason_detail = Column(Text, nullable=True)
    ticket_summary = Column(Text, nullable=True)
    conversation_topic = Column(String(100), nullable=True)
    first_human_response_at = Column(DateTime(timezone=True), nullable=True)
    
    # V2.2 Bot resolution tracking fields
    bot_resolved_at = Column(DateTime(timezone=True), nullable=True)
    awaiting_confirmation = Column(Boolean, default=False)
    last_bot_response_at = Column(DateTime(timezone=True), nullable=True)
    confirmation_sent_at = Column(DateTime(timezone=True), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    active_ticket_id = Column(Integer, ForeignKey("conversation_tickets.id"), nullable=True)
    
    assessor = relationship("Assessor", foreign_keys=[assessor_id])
    assigned_user = relationship("User", foreign_keys=[assigned_to])
    messages = relationship("WhatsAppMessage", back_populates="conversation", order_by="WhatsAppMessage.created_at")
    ticket_history = relationship("TicketHistory", back_populates="conversation", order_by="TicketHistory.created_at")
    tickets = relationship("ConversationTicket", back_populates="conversation", foreign_keys="ConversationTicket.conversation_id", order_by="ConversationTicket.created_at")
    active_ticket = relationship("ConversationTicket", foreign_keys=[active_ticket_id], post_update=True)


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
    conversation_ticket_id = Column(Integer, ForeignKey("conversation_tickets.id"), nullable=True)
    is_from_campaign = Column(Boolean, default=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    ticket = relationship("Ticket", foreign_keys=[ticket_id])
    conversation_ticket = relationship("ConversationTicket", foreign_keys=[conversation_ticket_id])
    campaign = relationship("Campaign", foreign_keys=[campaign_id])
    conversation = relationship("Conversation", back_populates="messages")


class TicketHistory(Base):
    """
    Histórico de ações no ticket para auditoria e cálculo de SLA.
    Registra todas as transições de status, atribuições e eventos importantes.
    """
    __tablename__ = "ticket_history"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False, index=True)
    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=True)
    from_escalation = Column(String(10), nullable=True)
    to_escalation = Column(String(10), nullable=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    extra_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    conversation = relationship("Conversation", back_populates="ticket_history")
    actor = relationship("User", foreign_keys=[actor_user_id])
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])


# ==================== CMS DE PRODUTOS ====================

class ProductStatus(str, enum.Enum):
    """Status do produto."""
    ACTIVE = "ativo"
    INACTIVE = "inativo"


class MaterialStatus(str, enum.Enum):
    """Status de publicação do material."""
    DRAFT = "rascunho"
    PUBLISHED = "publicado"
    ARCHIVED = "arquivado"


class ProcessingStatus(str, enum.Enum):
    """Status de processamento do material."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    PENDING_PRODUCT_MATCH = "pending_product_match"


class MaterialType(str, enum.Enum):
    """Tipos de material de produto."""
    COMITE = "comite"                    # Decisões e teses de comitê de investimentos
    RESEARCH = "research"                # Análises de mercado, setoriais, cenários
    ONE_PAGE = "one_page"                # Resumo comercial de produto (1 página)
    APRESENTACAO = "apresentacao"        # Decks para reuniões com clientes
    TAXAS = "taxas"                      # Tabelas de taxas, rendimentos (dados "vivos")
    CAMPANHA = "campanha"                # Materiais promocionais com prazo
    TREINAMENTO = "treinamento"          # Capacitação interna, playbooks
    FAQ = "faq"                          # Perguntas frequentes, objeções
    REGULATORIO = "regulatorio"          # Disclaimers, compliance, regras
    SCRIPT = "script"                    # Roteiros de abordagem WhatsApp/reunião
    OTHER = "outro"                      # Outros materiais


class ContentBlockType(str, enum.Enum):
    """Tipos de bloco de conteúdo."""
    TEXT = "texto"
    TABLE = "tabela"
    SCRIPT = "script"
    CHART = "grafico"
    IMAGE = "imagem"


class ContentBlockStatus(str, enum.Enum):
    """Status de aprovação do bloco."""
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContentSourceType(str, enum.Enum):
    """Origem do conteúdo."""
    PDF_UPLOAD = "pdf"
    MANUAL_INPUT = "manual"
    SPREADSHEET = "spreadsheet"
    AI_GENERATED = "ai_generated"


class Product(Base):
    """
    Produto financeiro no CMS.
    Centro da navegação - o broker pensa em produto, não em documento.
    """
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    ticker = Column(String(50), nullable=True, index=True)
    manager = Column(String(255), nullable=True)  # Gestora/Corretora
    category = Column(String(100), nullable=True, index=True)
    status = Column(String(20), default=ProductStatus.ACTIVE.value)
    description = Column(Text, nullable=True)
    name_aliases = Column(Text, default="[]")
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    creator = relationship("User", foreign_keys=[created_by])
    materials = relationship("Material", back_populates="product", cascade="all, delete-orphan")
    scripts = relationship("WhatsAppScript", back_populates="product", cascade="all, delete-orphan")

    def get_aliases(self):
        import json
        try:
            return json.loads(self.name_aliases or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def add_alias(self, alias_name):
        import json
        aliases = self.get_aliases()
        normalized = alias_name.strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
            self.name_aliases = json.dumps(aliases, ensure_ascii=False)
            return True
        return False


class Material(Base):
    """
    Material agrupa conteúdos por finalidade.
    Ex: One-page, Apresentação, Taxas, etc.
    """
    __tablename__ = "materials"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    material_type = Column(String(50), default=MaterialType.ONE_PAGE.value)
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    publish_status = Column(String(30), default=MaterialStatus.DRAFT.value)  # rascunho/publicado/arquivado
    valid_from = Column(DateTime(timezone=True), nullable=True)  # Data de início da vigência
    valid_until = Column(DateTime(timezone=True), nullable=True)  # Data de expiração
    published_at = Column(DateTime(timezone=True), nullable=True)  # Data da última publicação
    current_version = Column(Integer, default=1)
    is_indexed = Column(Boolean, default=False)
    source_file_path = Column(String(500), nullable=True)
    source_filename = Column(String(255), nullable=True)
    tags = Column(Text, default="[]")  # JSON array de tags estruturadas
    material_categories = Column(Text, default="[]")  # JSON array de categorias selecionadas
    auto_generated_tags = Column(Text, default="[]")  # Tags geradas automaticamente pelo GPT-4 Vision
    processing_status = Column(String(30), default=ProcessingStatus.PENDING.value)
    processing_error = Column(Text, nullable=True)
    extracted_metadata = Column(Text, nullable=True)  # JSON com metadados extraídos (fund_name, ticker, gestora, confidence)
    ai_summary = Column(Text, nullable=True)  # Resumo conceitual do documento gerado por GPT
    ai_themes = Column(Text, default="[]")  # JSON array de temas principais identificados por GPT
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    product = relationship("Product", back_populates="materials")
    creator = relationship("User", foreign_keys=[created_by])
    blocks = relationship("ContentBlock", back_populates="material", cascade="all, delete-orphan", order_by="ContentBlock.order")


class ContentBlock(Base):
    """
    Menor unidade semântica indexável.
    Cada bloco é editável independentemente.
    """
    __tablename__ = "content_blocks"
    
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    block_type = Column(String(30), default=ContentBlockType.TEXT.value)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)  # Texto ou JSON para tabelas
    content_hash = Column(String(64), nullable=True)  # Para detectar mudanças
    source_type = Column(String(30), default=ContentSourceType.MANUAL_INPUT.value)
    source_page = Column(Integer, nullable=True)  # Página de origem no PDF
    status = Column(String(30), default=ContentBlockStatus.AUTO_APPROVED.value)
    confidence_score = Column(Integer, default=100)  # 0-100
    is_high_risk = Column(Boolean, default=False)  # Contém taxas, custos, etc.
    semantic_tags = Column(Text, default="[]")  # JSON array de tags
    order = Column(Integer, default=0)
    current_version = Column(Integer, default=1)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    material = relationship("Material", back_populates="blocks")
    creator = relationship("User", foreign_keys=[created_by])
    editor = relationship("User", foreign_keys=[updated_by])
    versions = relationship("BlockVersion", back_populates="block", cascade="all, delete-orphan", order_by="BlockVersion.version.desc()")


class BlockVersion(Base):
    """
    Histórico de versões de um bloco.
    Permite rollback e auditoria.
    """
    __tablename__ = "block_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    block_id = Column(Integer, ForeignKey("content_blocks.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    change_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    block = relationship("ContentBlock", back_populates="versions")
    author = relationship("User", foreign_keys=[author_id])


class ProcessingJobStatus(str, enum.Enum):
    """Status do job de processamento de documento."""
    PENDING = "pending"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class PageProcessingStatus(str, enum.Enum):
    """Status do processamento de cada página."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class DocumentProcessingJob(Base):
    """
    Rastreia o estado geral do processamento de cada documento.
    Permite retomar processamentos interrompidos.
    """
    __tablename__ = "document_processing_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=True)
    total_pages = Column(Integer, nullable=False, default=0)
    processed_pages = Column(Integer, default=0)
    last_processed_page = Column(Integer, default=0)
    status = Column(String(30), default=ProcessingJobStatus.PENDING.value, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    material = relationship("Material", backref="processing_jobs")
    page_results = relationship("DocumentPageResult", back_populates="job", cascade="all, delete-orphan", order_by="DocumentPageResult.page_number")


class DocumentPageResult(Base):
    """
    Rastreia o resultado do processamento de cada página individualmente.
    Permite retomar processamentos de onde pararam.
    """
    __tablename__ = "document_page_results"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("document_processing_jobs.id"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    status = Column(String(30), default=PageProcessingStatus.PENDING.value)
    content_type = Column(String(50), nullable=True)
    raw_data = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    products_found = Column(Text, default="[]")
    facts_extracted = Column(Text, default="[]")
    created_block_ids = Column(Text, default="[]")
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    job = relationship("DocumentProcessingJob", back_populates="page_results")
    
    __table_args__ = (
        Index('ix_page_job_page', 'job_id', 'page_number', unique=True),
    )


class WhatsAppScript(Base):
    """
    Scripts de WhatsApp estruturados.
    Texto curto, copiável, indexável.
    """
    __tablename__ = "whatsapp_scripts"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    usage_type = Column(String(50), default="whatsapp")  # whatsapp, reuniao, email
    publish_status = Column(String(30), default=MaterialStatus.DRAFT.value)  # rascunho/publicado
    published_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    current_version = Column(Integer, default=1)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    product = relationship("Product", back_populates="scripts")
    creator = relationship("User", foreign_keys=[created_by])
    versions = relationship("ScriptVersion", back_populates="script", cascade="all, delete-orphan", order_by="ScriptVersion.version.desc()")


class PendingReviewItem(Base):
    """
    Itens aguardando revisão humana.
    Apenas para High-Risk (tabelas com taxas, custos, etc.)
    """
    __tablename__ = "pending_review_items"
    
    id = Column(Integer, primary_key=True, index=True)
    block_id = Column(Integer, ForeignKey("content_blocks.id"), nullable=False, index=True)
    original_content = Column(Text, nullable=False)
    extracted_content = Column(Text, nullable=False)  # O que a IA extraiu
    confidence_score = Column(Integer, default=0)
    risk_reason = Column(String(255), nullable=True)  # "Contém taxas", "Contém percentuais"
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_action = Column(String(30), nullable=True)  # approved, edited, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    block = relationship("ContentBlock", foreign_keys=[block_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])


class ScriptVersion(Base):
    """
    Histórico de versões de scripts WhatsApp.
    Permite rollback e auditoria.
    """
    __tablename__ = "script_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    script_id = Column(Integer, ForeignKey("whatsapp_scripts.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    change_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    script = relationship("WhatsAppScript", back_populates="versions")
    author = relationship("User", foreign_keys=[author_id])


class RetrievalLog(Base):
    """
    Log de auditoria para buscas semânticas.
    Permite rastrear quais chunks foram usados em cada resposta.
    """
    __tablename__ = "retrieval_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    query_type = Column(String(50), nullable=True)  # numeric, conceptual, ticker, etc.
    chunks_retrieved = Column(Text, nullable=True)  # JSON array de chunk IDs
    chunks_used = Column(Text, nullable=True)  # JSON array de chunks efetivamente usados
    chunk_versions = Column(Text, nullable=True)  # JSON dict {chunk_id: version}
    product_filter = Column(String(100), nullable=True)
    result_count = Column(Integer, default=0)
    min_distance = Column(String(20), nullable=True)  # Menor distância encontrada
    max_distance = Column(String(20), nullable=True)  # Maior distância usada
    threshold_applied = Column(String(20), nullable=True)  # Threshold de similaridade aplicado
    human_transfer = Column(Boolean, default=False)  # Se resultou em transferência humana
    transfer_reason = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    conversation_id = Column(String(100), nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", foreign_keys=[user_id])


class IngestionLog(Base):
    """
    Log estruturado de ingestão de documentos.
    Auditoria completa do pipeline de processamento.
    """
    __tablename__ = "ingestion_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True, index=True)
    document_name = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=True)  # pdf, manual, etc.
    total_pages = Column(Integer, nullable=True)
    blocks_created = Column(Integer, default=0)
    blocks_auto_approved = Column(Integer, default=0)
    blocks_pending_review = Column(Integer, default=0)
    blocks_rejected = Column(Integer, default=0)
    tables_detected = Column(Integer, default=0)
    charts_detected = Column(Integer, default=0)
    processing_time_ms = Column(Integer, nullable=True)
    status = Column(String(30), default="success")  # success, partial, failed
    error_message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)  # JSON com detalhes completos
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    material = relationship("Material", foreign_keys=[material_id])
    user = relationship("User", foreign_keys=[user_id])


class ConversationInsight(Base):
    """
    Diário de bordo das conversas com insights extraídos pela IA.
    Armazena categoria, produtos mencionados, se foi resolvido pela IA, e feedbacks.
    """
    __tablename__ = "conversation_insights"
    
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(100), nullable=False, index=True)
    assessor_id = Column(Integer, ForeignKey("assessores.id"), nullable=True, index=True)
    assessor_phone = Column(String(50), nullable=True, index=True)
    assessor_name = Column(String(255), nullable=True)
    
    user_message = Column(Text, nullable=False)
    agent_response = Column(Text, nullable=True)
    
    category = Column(String(100), nullable=True, index=True)
    products_mentioned = Column(Text, nullable=True)
    tickers_mentioned = Column(Text, nullable=True)
    
    resolved_by_ai = Column(Boolean, default=True)
    escalated_to_human = Column(Boolean, default=False)
    ticket_created = Column(Boolean, default=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    
    feedback_text = Column(Text, nullable=True)
    feedback_type = Column(String(50), nullable=True)
    sentiment = Column(String(20), nullable=True)
    
    unidade = Column(String(255), nullable=True, index=True)
    equipe = Column(String(255), nullable=True, index=True)
    macro_area = Column(String(255), nullable=True, index=True)
    broker_responsavel = Column(String(255), nullable=True, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    assessor = relationship("Assessor", foreign_keys=[assessor_id])
    ticket = relationship("Ticket", foreign_keys=[ticket_id])


class QueueItemStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PersistentQueueItem(Base):
    __tablename__ = "upload_queue_items"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(String(100), unique=True, nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    filename = Column(String(255), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    material_type = Column(String(50), default="outro")
    categories = Column(Text, default="[]")
    tags = Column(Text, default="[]")
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    selected_product_id = Column(Integer, nullable=True)
    is_resume = Column(Boolean, default=False)
    resume_from_page = Column(Integer, default=0)
    existing_job_id = Column(Integer, nullable=True)
    status = Column(String(30), default=QueueItemStatus.QUEUED.value, index=True)
    progress = Column(Integer, default=0)
    current_page = Column(Integer, default=0)
    total_pages = Column(Integer, default=0)
    logs = Column(Text, default="[]")
    error = Column(Text, nullable=True)
    stats = Column(Text, nullable=True)
    product_name = Column(String(255), nullable=True)
    product_ticker = Column(String(50), nullable=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    material = relationship("Material", foreign_keys=[material_id])
    user = relationship("User", foreign_keys=[user_id])


class CostTracking(Base):
    """Rastreamento de custos de APIs por consumo."""
    __tablename__ = "cost_tracking"
    
    id = Column(Integer, primary_key=True, index=True)
    service = Column(String(50), nullable=False, index=True)
    operation = Column(String(100), nullable=False)
    model = Column(String(50), nullable=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    audio_duration_seconds = Column(Float, nullable=True)
    cost_usd = Column(Float, default=0.0)
    cost_brl = Column(Float, default=0.0)
    exchange_rate = Column(Float, default=5.5)
    context = Column(String(200), nullable=True)
    conversation_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class FixedCost(Base):
    """Custos fixos mensais cadastrados pelo admin."""
    __tablename__ = "fixed_costs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    monthly_cost_brl = Column(Float, nullable=False)
    category = Column(String(50), default='infrastructure')
    is_active = Column(Boolean, default=True)
    plan_details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
