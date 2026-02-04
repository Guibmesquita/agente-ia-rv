"""
API endpoints para gerenciamento de conversas.
Permite visualizar histórico, buscar por número e intervir humanamente.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import httpx
import asyncio
import json

from database.database import get_db
from database.models import (
    Conversation, WhatsAppMessage, Assessor, User,
    ConversationStatus, ConversationState, SenderType, MessageDirection,
    TicketStatusV2, EscalationLevel, TicketHistory, TicketHistoryActionType
)
from api.endpoints.auth import get_current_user, get_current_user_sse
from services.sse_manager import get_sse_manager


router = APIRouter(prefix="/api/conversations", tags=["Conversations"])


class ConversationResponse(BaseModel):
    id: int
    phone: str
    contact_name: Optional[str] = None
    assessor_name: Optional[str] = None
    assessor_email: Optional[str] = None
    assessor_unidade: Optional[str] = None
    assessor_broker: Optional[str] = None
    status: str
    assigned_to_id: Optional[int] = None
    assigned_to_name: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread_count: int = 0
    created_at: Optional[datetime] = None
    # V2 Zendesk-like fields
    ticket_status: Optional[str] = None
    escalation_level: Optional[str] = None
    escalation_category: Optional[str] = None
    ticket_summary: Optional[str] = None
    conversation_topic: Optional[str] = None
    first_response_at: Optional[datetime] = None
    first_human_response_at: Optional[datetime] = None
    solved_at: Optional[datetime] = None
    sla_due_at: Optional[datetime] = None
    reopened_count: int = 0

    class Config:
        from_attributes = True


class TicketStatusRequest(BaseModel):
    status: str  # new, open, in_progress, solved


class FilterCountsResponse(BaseModel):
    all: int = 0
    escalated: int = 0
    my_tickets: int = 0
    open: int = 0
    solved_today: int = 0
    new: int = 0
    in_progress: int = 0


class FilterOptionsResponse(BaseModel):
    units: list = []
    brokers: list = []
    categories: list = []


class TicketMetricsResponse(BaseModel):
    total_tickets: int = 0
    bot_resolved: int = 0
    human_resolved: int = 0
    escalated: int = 0
    avg_first_response_minutes: Optional[float] = None
    avg_resolution_minutes: Optional[float] = None
    escalation_rate: Optional[float] = None
    bot_resolution_rate: Optional[float] = None


class MessageResponse(BaseModel):
    id: int
    direction: str
    message_type: str
    sender_type: str
    body: Optional[str] = None
    transcription: Optional[str] = None
    ai_response: Optional[str] = None
    is_from_campaign: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    message: str


class TakeoverRequest(BaseModel):
    action: str  # "takeover" ou "release"


class StartConversationRequest(BaseModel):
    phone: str
    message: str


def normalize_phone(phone: str) -> str:
    """
    Normaliza número de telefone para formato brasileiro completo.
    Remove caracteres especiais e garante código do país (55).
    """
    if not phone:
        return ""
    
    if "@lid" in phone:
        return phone
    
    digits = ''.join(c for c in phone if c.isdigit())
    
    if not digits:
        return ""
    
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits
    
    return digits


@router.get("/", response_model=List[ConversationResponse])
async def list_conversations(
    search: Optional[str] = Query(None, description="Buscar por número ou nome"),
    status: Optional[str] = Query(None, description="Filtrar por status legado"),
    ticket_status: Optional[str] = Query(None, description="Filtrar por ticket_status V2 (new, open, in_progress, solved)"),
    escalation_level: Optional[str] = Query(None, description="Filtrar por nível de escalonamento (t0, t1)"),
    assigned_to_me: Optional[bool] = Query(None, description="Filtrar meus tickets"),
    unidade: Optional[str] = Query(None, description="Filtrar por unidade do assessor"),
    broker: Optional[str] = Query(None, description="Filtrar por broker do assessor"),
    escalation_category: Optional[str] = Query(None, description="Filtrar por categoria de escalação"),
    date_range: Optional[str] = Query(None, description="Filtrar por período (today, 7d, 30d)"),
    skip: int = Query(0, ge=0),
    offset: int = Query(None, ge=0, description="Alias for skip"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as conversas com filtros e busca. Suporta filtros V2 Zendesk-like."""
    from datetime import date, timedelta
    
    actual_offset = offset if offset is not None else skip
    query = db.query(Conversation)
    
    if search:
        search_normalized = normalize_phone(search)
        query = query.outerjoin(Assessor, Conversation.assessor_id == Assessor.id)
        query = query.filter(
            or_(
                Conversation.phone.contains(search_normalized),
                Conversation.contact_name.ilike(f"%{search}%"),
                Assessor.nome.ilike(f"%{search}%")
            )
        )
    
    if status:
        query = query.filter(Conversation.status == status)
    
    # V2 Zendesk-like filters
    if ticket_status:
        query = query.filter(Conversation.ticket_status == ticket_status)
    
    if escalation_level:
        query = query.filter(Conversation.escalation_level == escalation_level)
    
    if assigned_to_me:
        query = query.filter(Conversation.assigned_to == current_user.id)
    
    # Filtros avançados
    if unidade or broker:
        query = query.outerjoin(Assessor, Conversation.assessor_id == Assessor.id)
        if unidade:
            query = query.filter(Assessor.unidade == unidade)
        if broker:
            query = query.filter(Assessor.broker_responsavel == broker)
    
    if escalation_category:
        query = query.filter(Conversation.escalation_category == escalation_category)
    
    if date_range:
        today = date.today()
        if date_range == 'today':
            start_date = datetime.combine(today, datetime.min.time())
        elif date_range == '7d':
            start_date = datetime.combine(today - timedelta(days=7), datetime.min.time())
        elif date_range == '30d':
            start_date = datetime.combine(today - timedelta(days=30), datetime.min.time())
        else:
            start_date = None
        
        if start_date:
            query = query.filter(Conversation.last_message_at >= start_date)
    
    conversations = query.order_by(desc(Conversation.last_message_at)).offset(actual_offset).limit(limit).all()
    
    result = []
    for conv in conversations:
        assessor = db.query(Assessor).filter(Assessor.id == conv.assessor_id).first() if conv.assessor_id else None
        assigned_user = db.query(User).filter(User.id == conv.assigned_to).first() if conv.assigned_to else None
        
        result.append(ConversationResponse(
            id=conv.id,
            phone=conv.phone,
            contact_name=conv.contact_name,
            assessor_name=assessor.nome if assessor else None,
            assessor_email=assessor.email if assessor else None,
            assessor_unidade=assessor.unidade if assessor else None,
            assessor_broker=assessor.broker_responsavel if assessor else None,
            status=conv.status,
            assigned_to_id=conv.assigned_to,
            assigned_to_name=assigned_user.username if assigned_user else None,
            last_message_at=conv.last_message_at,
            last_message_preview=conv.last_message_preview,
            unread_count=conv.unread_count,
            created_at=conv.created_at,
            # V2 fields
            ticket_status=conv.ticket_status,
            escalation_level=conv.escalation_level,
            escalation_category=conv.escalation_category,
            ticket_summary=conv.ticket_summary,
            conversation_topic=conv.conversation_topic,
            first_response_at=conv.first_response_at,
            first_human_response_at=conv.first_human_response_at,
            solved_at=conv.solved_at,
            sla_due_at=conv.sla_due_at,
            reopened_count=conv.reopened_count or 0
        ))
    
    return result


# ==================== ROTAS ESTÁTICAS (devem vir ANTES de rotas com {conversation_id}) ====================

@router.get("/filter-options", response_model=FilterOptionsResponse)
async def get_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna opções disponíveis para os filtros avançados."""
    from sqlalchemy import func, distinct
    
    units = db.query(distinct(Assessor.unidade)).filter(
        Assessor.unidade.isnot(None),
        Assessor.unidade != ''
    ).all()
    
    brokers = db.query(distinct(Assessor.broker_responsavel)).filter(
        Assessor.broker_responsavel.isnot(None),
        Assessor.broker_responsavel != ''
    ).all()
    
    categories = db.query(distinct(Conversation.escalation_category)).filter(
        Conversation.escalation_category.isnot(None),
        Conversation.escalation_category != ''
    ).all()
    
    return FilterOptionsResponse(
        units=sorted([u[0] for u in units if u[0]]),
        brokers=sorted([b[0] for b in brokers if b[0]]),
        categories=sorted([c[0] for c in categories if c[0]])
    )


@router.get("/filters", response_model=FilterCountsResponse)
async def get_filter_counts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna contadores para os filtros da fila de tickets."""
    from sqlalchemy import func
    from datetime import date
    
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    all_count = db.query(func.count(Conversation.id)).scalar() or 0
    escalated = db.query(func.count(Conversation.id)).filter(
        Conversation.escalation_level == EscalationLevel.T1_HUMAN.value
    ).scalar() or 0
    my_tickets = db.query(func.count(Conversation.id)).filter(
        Conversation.assigned_to == current_user.id
    ).scalar() or 0
    new_count = db.query(func.count(Conversation.id)).filter(
        Conversation.ticket_status == TicketStatusV2.NEW.value,
        Conversation.assigned_to.is_(None)
    ).scalar() or 0
    open_count = db.query(func.count(Conversation.id)).filter(
        Conversation.ticket_status == TicketStatusV2.OPEN.value,
        Conversation.assigned_to.isnot(None)
    ).scalar() or 0
    solved_today = db.query(func.count(Conversation.id)).filter(
        Conversation.ticket_status == TicketStatusV2.SOLVED.value,
        Conversation.solved_at >= today_start
    ).scalar() or 0
    in_progress_count = db.query(func.count(Conversation.id)).filter(
        Conversation.ticket_status == TicketStatusV2.IN_PROGRESS.value
    ).scalar() or 0
    
    return FilterCountsResponse(
        all=all_count,
        escalated=escalated,
        my_tickets=my_tickets,
        open=open_count,
        solved_today=solved_today,
        new=new_count,
        in_progress=in_progress_count
    )


@router.post("/sync")
async def sync_chats_from_zapi(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sincroniza chats da Z-API com o banco de dados.
    Chamado automaticamente ao abrir a página de Conversas.
    """
    from services.whatsapp_client import zapi_client
    
    if not zapi_client.instance_id or not zapi_client.token:
        return {"success": False, "error": "Z-API não configurada", "synced": 0}
    
    result = await zapi_client.get_all_chats(max_pages=5)
    
    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Erro ao buscar chats"), "synced": 0}
    
    chats = result.get("chats", [])
    synced_count = 0
    
    for chat in chats:
        if chat.get("isGroup"):
            continue
        
        phone = chat.get("phone", "")
        lid = chat.get("lid", "")
        
        if phone and "@lid" in phone:
            phone = ""
        
        if not phone and lid:
            phone = lid
        
        if not phone:
            continue
        
        phone = normalize_phone(phone) if "@lid" not in phone else phone
        
        existing = db.query(Conversation).filter(Conversation.phone == phone).first()
        
        if existing:
            if chat.get("name") and not existing.contact_name:
                existing.contact_name = chat.get("name")
            if chat.get("profileThumbnail"):
                existing.contact_photo = chat.get("profileThumbnail")
            if chat.get("lastMessageTime"):
                try:
                    last_msg_ts = int(chat.get("lastMessageTime"))
                    last_msg_dt = datetime.fromtimestamp(last_msg_ts / 1000) if last_msg_ts > 9999999999 else datetime.fromtimestamp(last_msg_ts)
                    if not existing.last_message_at or last_msg_dt > existing.last_message_at:
                        existing.last_message_at = last_msg_dt
                except (ValueError, TypeError):
                    pass
        else:
            phone_for_assessor = phone if "@lid" not in phone else None
            assessor = None
            if phone_for_assessor:
                assessor = db.query(Assessor).filter(
                    Assessor.telefone_whatsapp.contains(phone_for_assessor)
                ).first()
            
            last_msg_at = None
            if chat.get("lastMessageTime"):
                try:
                    ts = int(chat.get("lastMessageTime"))
                    last_msg_at = datetime.fromtimestamp(ts / 1000) if ts > 9999999999 else datetime.fromtimestamp(ts)
                except (ValueError, TypeError):
                    last_msg_at = datetime.utcnow()
            
            new_conv = Conversation(
                phone=phone,
                contact_name=chat.get("name"),
                contact_photo=chat.get("profileThumbnail"),
                assessor_id=assessor.id if assessor else None,
                status=ConversationStatus.BOT_ACTIVE.value,
                conversation_state=ConversationState.IDENTIFICATION_PENDING.value if not assessor else ConversationState.READY.value,
                last_message_at=last_msg_at,
                unread_count=int(chat.get("unread", 0)) if chat.get("unread") else 0
            )
            db.add(new_conv)
            synced_count += 1
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e), "synced": 0}
    
    return {
        "success": True,
        "message": f"Sincronização concluída",
        "synced": synced_count,
        "total_chats": len(chats)
    }


@router.post("/enable-sent-notifications")
async def enable_sent_by_me_notifications(
    enable: bool = True,
    current_user: User = Depends(get_current_user)
):
    """
    Habilita notificações de mensagens enviadas pelo próprio celular.
    Quando habilitado, todas as mensagens enviadas pelo app WhatsApp também
    aparecem no sistema.
    """
    from services.whatsapp_client import zapi_client
    
    if not zapi_client.instance_id or not zapi_client.token:
        raise HTTPException(status_code=500, detail="Z-API não configurada")
    
    result = await zapi_client.enable_notify_sent_by_me(enable)
    return result


@router.get("/webhook-settings")
async def get_webhook_settings(
    current_user: User = Depends(get_current_user)
):
    """
    Retorna as configurações atuais dos webhooks da instância Z-API.
    """
    from services.whatsapp_client import zapi_client
    
    if not zapi_client.instance_id or not zapi_client.token:
        raise HTTPException(status_code=500, detail="Z-API não configurada")
    
    result = await zapi_client.get_webhook_settings()
    return result


@router.post("/start")
async def start_new_conversation(
    request: StartConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Inicia uma nova conversa com um número de telefone ou envia para conversa existente."""
    from services.whatsapp_client import zapi_client
    
    phone = normalize_phone(request.phone)
    
    if len(phone) < 10 or len(phone) > 15:
        raise HTTPException(status_code=400, detail="Número de telefone inválido")
    
    message_text = request.message.strip() if request.message else ""
    if not message_text:
        raise HTTPException(status_code=400, detail="A mensagem não pode estar vazia")
    
    if not zapi_client.instance_id or not zapi_client.token:
        raise HTTPException(status_code=500, detail="Z-API não configurada. Configure em Integrações.")
    
    existing_conv = db.query(Conversation).filter(Conversation.phone == phone).first()
    
    if existing_conv:
        conv = existing_conv
    else:
        assessor = db.query(Assessor).filter(
            Assessor.telefone_whatsapp.contains(phone)
        ).first()
        
        conv = Conversation(
            phone=phone,
            contact_name=assessor.nome if assessor else None,
            assessor_id=assessor.id if assessor else None,
            status=ConversationStatus.HUMAN_TAKEOVER.value,
            conversation_state=ConversationState.HUMAN_TAKEOVER.value,
            assigned_to=current_user.id
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    
    result = await zapi_client.send_text(phone, message_text)
    
    if not result.get("success"):
        error_msg = result.get("error", "Erro desconhecido ao enviar mensagem")
        raise HTTPException(status_code=500, detail=f"Erro Z-API: {error_msg}")
    
    message = WhatsAppMessage(
        message_id=result.get("message_id"),
        zaap_id=result.get("zaap_id"),
        chat_id=phone,
        phone=phone,
        from_me=True,
        direction=MessageDirection.OUTBOUND.value,
        message_type="text",
        sender_type=SenderType.HUMAN.value,
        body=message_text,
        conversation_id=conv.id
    )
    db.add(message)
    
    conv.last_message_at = datetime.utcnow()
    conv.last_message_preview = message_text[:100] if len(message_text) > 100 else message_text
    conv.status = ConversationStatus.HUMAN_TAKEOVER.value
    conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
    conv.assigned_to = current_user.id
    
    db.commit()
    
    return {
        "success": True, 
        "message": "Conversa iniciada com sucesso", 
        "conversation_id": conv.id
    }


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém detalhes de uma conversa específica."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    assessor = db.query(Assessor).filter(Assessor.id == conv.assessor_id).first() if conv.assessor_id else None
    assigned_user = db.query(User).filter(User.id == conv.assigned_to).first() if conv.assigned_to else None
    
    return ConversationResponse(
        id=conv.id,
        phone=conv.phone,
        contact_name=conv.contact_name,
        assessor_name=assessor.nome if assessor else None,
        assessor_email=assessor.email if assessor else None,
        status=conv.status,
        assigned_to_name=assigned_user.username if assigned_user else None,
        last_message_at=conv.last_message_at,
        last_message_preview=conv.last_message_preview,
        unread_count=conv.unread_count,
        created_at=conv.created_at
    )


@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista mensagens de uma conversa."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    conv.unread_count = 0
    db.commit()
    
    messages = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.conversation_id == conversation_id
    ).order_by(WhatsAppMessage.created_at).offset(skip).limit(limit).all()
    
    return [
        MessageResponse(
            id=msg.id,
            direction=msg.direction,
            message_type=msg.message_type,
            sender_type=msg.sender_type or "contact",
            body=msg.body,
            transcription=msg.transcription,
            ai_response=msg.ai_response,
            is_from_campaign=msg.is_from_campaign or False,
            created_at=msg.created_at
        )
        for msg in messages
    ]


@router.post("/{conversation_id}/sync-messages")
async def sync_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sincroniza mensagens do chat via Z-API.
    Busca mensagens mais recentes e importa para o banco de dados.
    """
    from services.whatsapp_client import zapi_client
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    if not zapi_client.instance_id or not zapi_client.token:
        raise HTTPException(status_code=500, detail="Z-API não configurada")
    
    result = await zapi_client.get_chat_messages(conv.phone, amount=100)
    
    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Erro ao buscar mensagens"),
            "imported": 0
        }
    
    imported_count = 0
    messages = result.get("messages", [])
    
    for msg_data in messages:
        msg_id = msg_data.get("messageId") or msg_data.get("id")
        if not msg_id:
            continue
        
        existing = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.message_id == msg_id
        ).first()
        
        if existing:
            continue
        
        is_from_me = msg_data.get("fromMe", False)
        direction = "outbound" if is_from_me else "inbound"
        
        body = ""
        msg_type = "text"
        
        if msg_data.get("text"):
            body = msg_data["text"].get("message", "") if isinstance(msg_data["text"], dict) else str(msg_data["text"])
        elif msg_data.get("audio"):
            msg_type = "audio"
            body = "[Áudio]"
        elif msg_data.get("image"):
            msg_type = "image"
            body = msg_data["image"].get("caption", "[Imagem]")
        elif msg_data.get("document"):
            msg_type = "document"
            body = msg_data["document"].get("fileName", "[Documento]")
        elif msg_data.get("video"):
            msg_type = "video"
            body = msg_data["video"].get("caption", "[Vídeo]")
        
        timestamp = msg_data.get("momment") or msg_data.get("timestamp")
        created_at = datetime.utcnow()
        if timestamp:
            try:
                if timestamp > 10000000000:
                    timestamp = timestamp / 1000
                created_at = datetime.fromtimestamp(timestamp)
            except:
                pass
        
        phone_from_msg = msg_data.get("phone", "")
        chat_id_from_msg = msg_data.get("chatLid") or msg_data.get("phone", conv.phone)
        
        new_msg = WhatsAppMessage(
            conversation_id=conv.id,
            message_id=msg_id,
            zaap_id=msg_data.get("zaapId"),
            chat_id=chat_id_from_msg,
            phone=phone_from_msg or conv.phone,
            from_me=is_from_me,
            direction=direction,
            message_type=msg_type,
            sender_type="human" if is_from_me else "contact",
            body=body,
            created_at=created_at
        )
        db.add(new_msg)
        imported_count += 1
    
    if imported_count > 0:
        db.commit()
        
        last_msg = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.conversation_id == conv.id
        ).order_by(WhatsAppMessage.created_at.desc()).first()
        
        if last_msg:
            conv.last_message_at = last_msg.created_at
            conv.last_message_preview = last_msg.body[:100] if last_msg.body else ""
            db.commit()
    
    return {
        "success": True,
        "imported": imported_count,
        "total_fetched": len(messages)
    }


@router.post("/{conversation_id}/send")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Envia uma mensagem manualmente (intervenção humana)."""
    from services.whatsapp_client import zapi_client
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    if not zapi_client.instance_id or not zapi_client.token:
        raise HTTPException(status_code=500, detail="Z-API não configurada. Configure em Integrações.")
    
    result = await zapi_client.send_text(conv.phone, request.message)
    
    if not result.get("success"):
        error_msg = result.get("error", "Erro desconhecido ao enviar mensagem")
        raise HTTPException(status_code=500, detail=f"Erro Z-API: {error_msg}")
    
    message = WhatsAppMessage(
        message_id=result.get("message_id"),
        zaap_id=result.get("zaap_id"),
        chat_id=conv.phone,
        phone=conv.phone,
        from_me=True,
        direction=MessageDirection.OUTBOUND.value,
        message_type="text",
        sender_type=SenderType.HUMAN.value,
        body=request.message,
        conversation_id=conversation_id
    )
    db.add(message)
    
    conv.last_message_at = datetime.utcnow()
    conv.last_message_preview = request.message[:100] if len(request.message) > 100 else request.message
    
    db.commit()
    
    return {"success": True, "message": "Mensagem enviada com sucesso"}


@router.post("/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: int,
    request: TakeoverRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Assume ou libera uma conversa para atendimento humano.
    Atualiza tanto o status quanto o conversation_state conforme framework.
    """
    from database.models import ConversationState
    from datetime import datetime
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    if request.action == "takeover":
        conv.status = ConversationStatus.HUMAN_TAKEOVER.value
        conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
        conv.assigned_to = current_user.id
        conv.transferred_at = datetime.utcnow()
        message = f"Conversa assumida por {current_user.username}"
    elif request.action == "release":
        conv.status = ConversationStatus.BOT_ACTIVE.value
        conv.conversation_state = ConversationState.IN_PROGRESS.value
        conv.assigned_to = None
        conv.transfer_reason = None
        conv.transfer_notes = None
        conv.stalled_interactions = 0
        message = "Conversa devolvida ao agente"
    else:
        raise HTTPException(status_code=400, detail="Ação inválida")
    
    db.commit()
    
    return {"success": True, "message": message, "status": conv.status, "conversation_state": conv.conversation_state}


class ResolveTicketRequest(BaseModel):
    summary: Optional[str] = None
    save_to_knowledge: bool = False
    knowledge_title: Optional[str] = None
    tags: List[str] = []


@router.post("/{conversation_id}/resolve")
async def resolve_conversation(
    conversation_id: int,
    request: ResolveTicketRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Resolve um ticket/conversa, marcando como solucionado.
    Opcionalmente salva a resolução na base de conhecimento para uso futuro pelo agente.
    """
    from database.models import ConversationState
    from datetime import datetime
    from services.vector_store import VectorStore
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    conv.status = ConversationStatus.BOT_ACTIVE.value
    conv.conversation_state = ConversationState.COMPLETED.value
    conv.ticket_status = TicketStatusV2.SOLVED.value
    conv.solved_at = datetime.utcnow()
    conv.assigned_to = None
    
    if request.summary:
        conv.resolution_notes = request.summary
    
    previous_status = conv.ticket_status or TicketStatusV2.OPEN.value
    history_entry = TicketHistory(
        conversation_id=conv.id,
        user_id=current_user.id,
        action_type=TicketHistoryActionType.STATUS_CHANGE.value,
        from_value=previous_status,
        to_value=TicketStatusV2.SOLVED.value,
        notes=request.summary or "Ticket resolvido"
    )
    db.add(history_entry)
    
    knowledge_created = False
    
    if request.save_to_knowledge and request.summary:
        try:
            title = request.knowledge_title or f"Resolução: {conv.contact_name or conv.phone}"
            
            content = f"Pergunta/Problema: {conv.conversation_topic or 'Não categorizado'}\n\n"
            content += f"Resolução: {request.summary}\n\n"
            if request.tags:
                content += f"Tags: {', '.join(request.tags)}"
            
            vector_store = VectorStore()
            doc_id = f"ticket_resolution_{conv.id}_{datetime.utcnow().timestamp()}"
            
            tags_text = ""
            if request.tags:
                tags_text = f"\n\n[Tags: {', '.join(request.tags)}]"
            
            vector_store.add_document(
                doc_id=doc_id,
                text=content + tags_text,
                metadata={
                    "source": f"Resolução de Ticket #{conv.id}",
                    "title": title,
                    "type": "ticket_resolution",
                    "category": "resolucao_ticket",
                    "conversation_id": str(conv.id),
                    "resolved_by": current_user.username,
                    "tags": ",".join(request.tags) if request.tags else ""
                }
            )
            
            knowledge_created = True
            
        except Exception as e:
            print(f"[RESOLVE] Erro ao criar conhecimento: {e}")
    
    db.commit()
    
    return {
        "success": True,
        "message": "Ticket resolvido com sucesso",
        "knowledge_created": knowledge_created
    }


@router.get("/by-phone/{phone}")
async def get_conversation_by_phone(
    phone: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Busca uma conversa pelo número de telefone."""
    phone_normalized = normalize_phone(phone)
    
    conv = db.query(Conversation).filter(
        Conversation.phone.contains(phone_normalized)
    ).first()
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    assessor = db.query(Assessor).filter(Assessor.id == conv.assessor_id).first() if conv.assessor_id else None
    assigned_user = db.query(User).filter(User.id == conv.assigned_to).first() if conv.assigned_to else None
    
    return ConversationResponse(
        id=conv.id,
        phone=conv.phone,
        contact_name=conv.contact_name,
        assessor_name=assessor.nome if assessor else None,
        assessor_email=assessor.email if assessor else None,
        status=conv.status,
        assigned_to_name=assigned_user.username if assigned_user else None,
        last_message_at=conv.last_message_at,
        last_message_preview=conv.last_message_preview,
        unread_count=conv.unread_count,
        created_at=conv.created_at
    )


def get_or_create_conversation(db: Session, phone: str, contact_name: str = None) -> Conversation:
    """Obtém ou cria uma conversa para um número de telefone."""
    phone_normalized = normalize_phone(phone)
    
    conv = db.query(Conversation).filter(Conversation.phone == phone_normalized).first()
    
    if not conv:
        assessor = db.query(Assessor).filter(
            Assessor.telefone_whatsapp.contains(phone_normalized)
        ).first()
        
        conv = Conversation(
            phone=phone_normalized,
            contact_name=contact_name or (assessor.nome if assessor else None),
            assessor_id=assessor.id if assessor else None,
            status=ConversationStatus.BOT_ACTIVE.value
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    
    return conv


def update_conversation_from_message(
    db: Session,
    conversation: Conversation,
    message_body: str,
    is_inbound: bool = True
):
    """Atualiza metadados da conversa após nova mensagem."""
    conversation.last_message_at = datetime.utcnow()
    conversation.last_message_preview = message_body[:100] if message_body and len(message_body) > 100 else message_body
    
    if is_inbound:
        conversation.unread_count = (conversation.unread_count or 0) + 1
    
    db.commit()


def record_ticket_history(
    db: Session,
    conversation_id: int,
    action_type: str,
    actor_user_id: int = None,
    from_status: str = None,
    to_status: str = None,
    from_escalation: str = None,
    to_escalation: str = None,
    assigned_user_id: int = None,
    notes: str = None
):
    """Registra uma ação no histórico do ticket para auditoria e SLA."""
    history = TicketHistory(
        conversation_id=conversation_id,
        action_type=action_type,
        from_status=from_status,
        to_status=to_status,
        from_escalation=from_escalation,
        to_escalation=to_escalation,
        actor_user_id=actor_user_id,
        assigned_user_id=assigned_user_id,
        notes=notes
    )
    db.add(history)
    db.commit()


# ==================== V2 ZENDESK-LIKE ENDPOINTS ====================

def get_takeover_greeting(user_name: str) -> str:
    """Retorna variações de mensagem de boas-vindas ao assumir."""
    import random
    greetings = [
        f"Olha, o {user_name} vai te ajudar agora! Pode seguir com ele.",
        f"Pronto! O {user_name} assumiu o atendimento. Pode falar com ele.",
        f"Assessor, o {user_name} está aqui pra te ajudar agora.",
        f"Beleza! Passei o bastão pro {user_name}. Ele vai cuidar de você.",
        f"Opa! O {user_name} entrou na conversa pra te dar suporte.",
        f"Tudo certo! O {user_name} assumiu. Pode continuar com ele.",
    ]
    return random.choice(greetings)


@router.post("/{conversation_id}/take")
async def take_ticket(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Assume um ticket (Zendesk-like 'Assumir'). Envia mensagem automática ao contato."""
    from services.whatsapp_client import zapi_client
    from database.models import ConversationTicket
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    old_status = conv.ticket_status
    old_escalation = conv.escalation_level
    now = datetime.utcnow()
    
    if conv.active_ticket_id:
        active_ticket = db.query(ConversationTicket).filter(
            ConversationTicket.id == conv.active_ticket_id
        ).first()
        
        if active_ticket:
            active_ticket.status = TicketStatusV2.OPEN.value
            active_ticket.assigned_to = current_user.id
            if not active_ticket.first_response_at:
                active_ticket.first_response_at = now
            if not active_ticket.first_human_response_at:
                active_ticket.first_human_response_at = now
    
    conv.assigned_to = current_user.id
    conv.last_assigned_at = now
    conv.ticket_status = TicketStatusV2.OPEN.value
    conv.escalation_level = EscalationLevel.T1_HUMAN.value
    conv.status = ConversationStatus.HUMAN_TAKEOVER.value
    conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
    conv.transferred_at = now
    
    if not conv.first_response_at:
        conv.first_response_at = now
    
    if not conv.first_human_response_at:
        conv.first_human_response_at = now
    
    db.commit()
    
    record_ticket_history(
        db, conversation_id,
        TicketHistoryActionType.ASSIGNED.value,
        actor_user_id=current_user.id,
        from_status=old_status,
        to_status=conv.ticket_status,
        from_escalation=old_escalation,
        to_escalation=conv.escalation_level,
        assigned_user_id=current_user.id,
        notes=f"Ticket assumido por {current_user.username}"
    )
    
    return {
        "success": True,
        "message": f"Ticket assumido por {current_user.username}",
        "ticket_status": conv.ticket_status,
        "escalation_level": conv.escalation_level,
        "assigned_to_id": current_user.id,
        "assigned_to_name": current_user.username
    }


class TicketResolutionRequest(BaseModel):
    resolution_category: Optional[str] = None
    resolution_notes: Optional[str] = None
    contribute_to_kb: bool = False
    kb_content: Optional[str] = None


@router.post("/{conversation_id}/release")
async def release_ticket(
    conversation_id: int,
    resolution: Optional[TicketResolutionRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Libera um ticket (devolve para o bot e conclui o chamado)."""
    from database.models import ConversationTicket
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    old_status = conv.ticket_status
    old_escalation = conv.escalation_level
    old_assigned = conv.assigned_to
    now = datetime.utcnow()
    
    active_ticket = None
    resolution_time = None
    if conv.active_ticket_id:
        active_ticket = db.query(ConversationTicket).filter(
            ConversationTicket.id == conv.active_ticket_id
        ).first()
        
        if active_ticket:
            active_ticket.status = TicketStatusV2.SOLVED.value
            active_ticket.solved_at = now
            
            if active_ticket.transferred_at:
                resolution_time = int((now - active_ticket.transferred_at).total_seconds())
                active_ticket.resolution_time_seconds = resolution_time
            
            if resolution:
                active_ticket.resolution_category = resolution.resolution_category
                active_ticket.resolution_notes = resolution.resolution_notes
                active_ticket.contributed_to_kb = resolution.contribute_to_kb
    
    conv.assigned_to = None
    conv.ticket_status = TicketStatusV2.SOLVED.value
    conv.solved_at = now
    conv.escalation_level = EscalationLevel.T0_BOT.value
    conv.status = ConversationStatus.BOT_ACTIVE.value
    conv.conversation_state = ConversationState.IN_PROGRESS.value
    conv.stalled_interactions = 0
    conv.active_ticket_id = None
    
    db.commit()
    
    record_ticket_history(
        db, conversation_id,
        TicketHistoryActionType.STATUS_CHANGED.value,
        actor_user_id=current_user.id,
        from_status=old_status,
        to_status=conv.ticket_status,
        from_escalation=old_escalation,
        to_escalation=conv.escalation_level,
        notes=f"Ticket concluído e devolvido ao bot por {current_user.username}"
    )
    
    return {
        "success": True,
        "message": "Ticket concluído e devolvido ao bot",
        "ticket_status": conv.ticket_status,
        "escalation_level": conv.escalation_level,
        "ticket_id": active_ticket.id if active_ticket else None,
        "resolution_time_seconds": resolution_time
    }


@router.post("/{conversation_id}/status")
async def update_ticket_status(
    conversation_id: int,
    request: TicketStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Atualiza o status do ticket (new, open, in_progress, solved)."""
    from database.models import ConversationTicket
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    valid_statuses = [s.value for s in TicketStatusV2]
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status inválido. Use: {valid_statuses}")
    
    old_status = conv.ticket_status
    now = datetime.utcnow()
    
    if conv.active_ticket_id:
        active_ticket = db.query(ConversationTicket).filter(
            ConversationTicket.id == conv.active_ticket_id
        ).first()
        
        if active_ticket:
            active_ticket.status = request.status
            
            if request.status == TicketStatusV2.SOLVED.value:
                active_ticket.solved_at = now
                if active_ticket.transferred_at:
                    active_ticket.resolution_time_seconds = int((now - active_ticket.transferred_at).total_seconds())
    
    conv.ticket_status = request.status
    
    if request.status == TicketStatusV2.SOLVED.value:
        conv.solved_at = now
        conv.status = ConversationStatus.BOT_ACTIVE.value
        conv.assigned_to = None
        conv.active_ticket_id = None
    
    db.commit()
    
    record_ticket_history(
        db, conversation_id,
        TicketHistoryActionType.STATUS_CHANGED.value,
        actor_user_id=current_user.id,
        from_status=old_status,
        to_status=conv.ticket_status,
        notes=f"Status alterado de {old_status} para {request.status}"
    )
    
    return {
        "success": True,
        "message": f"Status atualizado para {request.status}",
        "ticket_status": conv.ticket_status
    }


@router.get("/metrics", response_model=TicketMetricsResponse)
async def get_ticket_metrics(
    days: int = Query(30, ge=1, le=365, description="Período em dias para calcular métricas"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retorna métricas de atendimento estilo Zendesk."""
    from sqlalchemy import func
    from datetime import timedelta
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    total = db.query(func.count(Conversation.id)).filter(
        Conversation.created_at >= start_date
    ).scalar() or 0
    
    solved = db.query(Conversation).filter(
        Conversation.ticket_status == TicketStatusV2.SOLVED.value,
        Conversation.solved_at >= start_date
    ).all()
    
    bot_resolved = len([c for c in solved if c.escalation_level == EscalationLevel.T0_BOT.value])
    human_resolved = len([c for c in solved if c.escalation_level == EscalationLevel.T1_HUMAN.value])
    
    escalated = db.query(func.count(Conversation.id)).filter(
        Conversation.escalation_level == EscalationLevel.T1_HUMAN.value,
        Conversation.created_at >= start_date
    ).scalar() or 0
    
    first_response_times = []
    resolution_times = []
    
    for conv in solved:
        if conv.first_response_at and conv.created_at:
            diff = (conv.first_response_at - conv.created_at).total_seconds() / 60
            first_response_times.append(diff)
        if conv.solved_at and conv.created_at:
            diff = (conv.solved_at - conv.created_at).total_seconds() / 60
            resolution_times.append(diff)
    
    avg_first_response = sum(first_response_times) / len(first_response_times) if first_response_times else None
    avg_resolution = sum(resolution_times) / len(resolution_times) if resolution_times else None
    escalation_rate = (escalated / total * 100) if total > 0 else None
    bot_rate = (bot_resolved / len(solved) * 100) if solved else None
    
    return TicketMetricsResponse(
        total_tickets=total,
        bot_resolved=bot_resolved,
        human_resolved=human_resolved,
        escalated=escalated,
        avg_first_response_minutes=round(avg_first_response, 1) if avg_first_response else None,
        avg_resolution_minutes=round(avg_resolution, 1) if avg_resolution else None,
        escalation_rate=round(escalation_rate, 1) if escalation_rate else None,
        bot_resolution_rate=round(bot_rate, 1) if bot_rate else None
    )


@router.get("/stream")
async def stream_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_sse)
):
    """
    SSE endpoint para receber notificações em tempo real sobre conversas.
    Requer autenticação via token SSE (query param, cookie ou header).
    Use /api/auth/sse-token para obter um token de curta duração para este endpoint.
    """
    sse_manager = get_sse_manager()
    queue = await sse_manager.subscribe("conversations")
    
    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'message': 'SSE conectado'})}\n\n"
            
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe("conversations", queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
