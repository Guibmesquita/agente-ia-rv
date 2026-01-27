"""
API endpoints para a Central de Mensagens.
Interface estilo WhatsApp Web para gerenciamento de conversas.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import asyncio
import os
import base64

from database.database import get_db
from database.models import (
    Conversation, WhatsAppMessage, Assessor, User,
    ConversationStatus, ConversationState, SenderType, MessageDirection, MessageType, MessageStatus
)
from api.endpoints.auth import get_current_user
from services.whatsapp_client import zapi_client

router = APIRouter(prefix="/api/central", tags=["Central de Mensagens"])


class ConversationListItem(BaseModel):
    id: int
    phone: str
    contact_name: Optional[str] = None
    photo: Optional[str] = None
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    unread_count: int = 0
    status: str
    from_me: bool = False

    class Config:
        from_attributes = True


class MessageItem(BaseModel):
    id: int
    message_id: Optional[str] = None
    direction: str
    message_type: str
    status: Optional[str] = None
    from_me: bool = False
    sender_type: str
    sender_name: Optional[str] = None
    body: Optional[str] = None
    media_url: Optional[str] = None
    media_filename: Optional[str] = None
    thumbnail_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SendTextRequest(BaseModel):
    phone: str
    message: str


class SendMediaRequest(BaseModel):
    phone: str
    media_url: str
    media_type: str
    caption: Optional[str] = None
    filename: Optional[str] = None


class StartConversationRequest(BaseModel):
    phone: str
    message: str


def normalize_phone(phone: str) -> str:
    """Remove caracteres especiais do telefone."""
    if not phone:
        return ""
    return ''.join(c for c in phone if c.isdigit())


@router.get("/conversations", response_model=List[ConversationListItem])
async def list_conversations(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as conversas para a Central de Mensagens."""
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
    
    conversations = query.order_by(desc(Conversation.last_message_at)).limit(limit).all()
    
    result = []
    for conv in conversations:
        last_msg = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.conversation_id == conv.id
        ).order_by(desc(WhatsAppMessage.created_at)).first()
        
        result.append(ConversationListItem(
            id=conv.id,
            phone=conv.phone,
            contact_name=conv.contact_name or conv.phone,
            photo=None,
            last_message=conv.last_message_preview,
            last_message_time=conv.last_message_at,
            unread_count=conv.unread_count or 0,
            status=conv.status,
            from_me=last_msg.from_me if last_msg else False
        ))
    
    return result


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageItem])
async def get_conversation_messages(
    conversation_id: int,
    before_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém mensagens de uma conversa específica."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.conversation_id == conversation_id
    )
    
    if before_id:
        query = query.filter(WhatsAppMessage.id < before_id)
    
    messages = query.order_by(desc(WhatsAppMessage.created_at)).limit(limit).all()
    
    messages.reverse()
    
    return [
        MessageItem(
            id=m.id,
            message_id=m.message_id,
            direction=m.direction,
            message_type=m.message_type,
            status=m.message_status,
            from_me=m.from_me or m.direction == MessageDirection.OUTBOUND.value,
            sender_type=m.sender_type,
            sender_name=m.sender_name,
            body=m.body,
            media_url=m.media_url,
            media_filename=m.media_filename,
            thumbnail_url=m.thumbnail_url,
            created_at=m.created_at
        )
        for m in messages
    ]


@router.get("/messages/{phone}", response_model=List[MessageItem])
async def get_messages_by_phone(
    phone: str,
    before_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém mensagens por número de telefone."""
    clean_phone = normalize_phone(phone)
    
    query = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.phone == clean_phone
    )
    
    if before_id:
        query = query.filter(WhatsAppMessage.id < before_id)
    
    messages = query.order_by(desc(WhatsAppMessage.created_at)).limit(limit).all()
    
    messages.reverse()
    
    return [
        MessageItem(
            id=m.id,
            message_id=m.message_id,
            direction=m.direction,
            message_type=m.message_type,
            status=m.message_status,
            from_me=m.from_me or m.direction == MessageDirection.OUTBOUND.value,
            sender_type=m.sender_type,
            sender_name=m.sender_name,
            body=m.body,
            media_url=m.media_url,
            media_filename=m.media_filename,
            thumbnail_url=m.thumbnail_url,
            created_at=m.created_at
        )
        for m in messages
    ]


@router.post("/conversations/{conversation_id}/read")
async def mark_as_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Marca uma conversa como lida."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    conv.unread_count = 0
    db.commit()
    
    return {"success": True}


@router.post("/send/text")
async def send_text_message(
    request: SendTextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Envia uma mensagem de texto."""
    phone = normalize_phone(request.phone)
    
    result = await zapi_client.send_text(phone, request.message)
    
    if result.get("success"):
        conv = db.query(Conversation).filter(Conversation.phone == phone).first()
        if not conv:
            conv = Conversation(
                phone=phone,
                status=ConversationStatus.HUMAN_TAKEOVER.value,
                conversation_state=ConversationState.HUMAN_TAKEOVER.value
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
        
        message = WhatsAppMessage(
            message_id=result.get("message_id"),
            zaap_id=result.get("zaap_id"),
            chat_id=phone,
            phone=phone,
            from_me=True,
            direction=MessageDirection.OUTBOUND.value,
            message_type=MessageType.TEXT.value,
            message_status=MessageStatus.SENT.value,
            sender_type=SenderType.HUMAN.value,
            body=request.message,
            conversation_id=conv.id
        )
        db.add(message)
        
        conv.last_message_at = datetime.utcnow()
        conv.last_message_preview = request.message[:100] if len(request.message) > 100 else request.message
        if conv.status != ConversationStatus.HUMAN_TAKEOVER.value:
            conv.status = ConversationStatus.HUMAN_TAKEOVER.value
            conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
        
        db.commit()
        db.refresh(message)
        
        return {
            "success": True,
            "message_id": result.get("message_id"),
            "zaap_id": result.get("zaap_id"),
            "db_id": message.id
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Erro ao enviar mensagem")
        )


@router.post("/send/media")
async def send_media_message(
    request: SendMediaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Envia uma mensagem com mídia (imagem, vídeo, áudio, documento)."""
    phone = normalize_phone(request.phone)
    
    if request.media_type == "image":
        result = await zapi_client.send_image(phone, request.media_url, request.caption or "")
    elif request.media_type == "video":
        result = await zapi_client.send_video(phone, request.media_url, request.caption or "")
    elif request.media_type == "audio":
        result = await zapi_client.send_audio(phone, request.media_url)
    elif request.media_type == "document":
        result = await zapi_client.send_document(phone, request.media_url, request.filename or "", request.caption or "")
    else:
        raise HTTPException(status_code=400, detail="Tipo de mídia inválido")
    
    if result.get("success"):
        conv = db.query(Conversation).filter(Conversation.phone == phone).first()
        if not conv:
            conv = Conversation(
                phone=phone,
                status=ConversationStatus.HUMAN_TAKEOVER.value,
                conversation_state=ConversationState.HUMAN_TAKEOVER.value
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
        
        message = WhatsAppMessage(
            message_id=result.get("message_id"),
            zaap_id=result.get("zaap_id"),
            chat_id=phone,
            phone=phone,
            from_me=True,
            direction=MessageDirection.OUTBOUND.value,
            message_type=request.media_type,
            message_status=MessageStatus.SENT.value,
            sender_type=SenderType.HUMAN.value,
            body=request.caption,
            media_url=request.media_url,
            media_filename=request.filename,
            conversation_id=conv.id
        )
        db.add(message)
        
        conv.last_message_at = datetime.utcnow()
        preview = f"📎 {request.filename or request.media_type}"
        if request.caption:
            preview += f": {request.caption[:50]}"
        conv.last_message_preview = preview
        
        db.commit()
        db.refresh(message)
        
        return {
            "success": True,
            "message_id": result.get("message_id"),
            "zaap_id": result.get("zaap_id"),
            "db_id": message.id
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Erro ao enviar mídia")
        )


@router.post("/start")
async def start_new_conversation(
    request: StartConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Inicia uma nova conversa com um número."""
    phone = normalize_phone(request.phone)
    
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Número de telefone inválido")
    
    result = await zapi_client.send_text(phone, request.message)
    
    if result.get("success"):
        conv = db.query(Conversation).filter(Conversation.phone == phone).first()
        if not conv:
            assessor = db.query(Assessor).filter(
                Assessor.telefone_whatsapp.contains(phone)
            ).first()
            
            conv = Conversation(
                phone=phone,
                contact_name=assessor.nome if assessor else None,
                assessor_id=assessor.id if assessor else None,
                status=ConversationStatus.HUMAN_TAKEOVER.value,
                conversation_state=ConversationState.HUMAN_TAKEOVER.value
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
        
        message = WhatsAppMessage(
            message_id=result.get("message_id"),
            zaap_id=result.get("zaap_id"),
            chat_id=phone,
            phone=phone,
            from_me=True,
            direction=MessageDirection.OUTBOUND.value,
            message_type=MessageType.TEXT.value,
            message_status=MessageStatus.SENT.value,
            sender_type=SenderType.HUMAN.value,
            body=request.message,
            conversation_id=conv.id
        )
        db.add(message)
        
        conv.last_message_at = datetime.utcnow()
        conv.last_message_preview = request.message[:100]
        conv.status = ConversationStatus.HUMAN_TAKEOVER.value
        conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
        
        db.commit()
        
        return {
            "success": True,
            "conversation_id": conv.id,
            "message_id": result.get("message_id")
        }
    else:
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Erro ao iniciar conversa")
        )


@router.post("/conversations/{conversation_id}/takeover")
async def toggle_takeover(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Alterna entre modo bot e modo humano.
    Atualiza conversation_state para bloquear respostas automáticas quando em HUMAN_TAKEOVER.
    """
    from database.models import ConversationState
    from datetime import datetime
    
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    if conv.status == ConversationStatus.HUMAN_TAKEOVER.value:
        conv.status = ConversationStatus.BOT_ACTIVE.value
        conv.conversation_state = ConversationState.IN_PROGRESS.value
        conv.assigned_to = None
        conv.transfer_reason = None
        conv.transfer_notes = None
        conv.stalled_interactions = 0
    else:
        conv.status = ConversationStatus.HUMAN_TAKEOVER.value
        conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
        conv.assigned_to = current_user.id
        conv.transferred_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "status": conv.status,
        "conversation_state": conv.conversation_state,
        "assigned_to": conv.assigned_to
    }


@router.get("/connection/status")
async def get_connection_status(
    current_user: User = Depends(get_current_user)
):
    """Verifica o status da conexão com o Z-API."""
    result = await zapi_client.check_connection()
    return result


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtém estatísticas da Central de Mensagens."""
    total_conversations = db.query(func.count(Conversation.id)).scalar()
    active_conversations = db.query(func.count(Conversation.id)).filter(
        Conversation.status == ConversationStatus.BOT_ACTIVE.value
    ).scalar()
    human_conversations = db.query(func.count(Conversation.id)).filter(
        Conversation.status == ConversationStatus.HUMAN_TAKEOVER.value
    ).scalar()
    total_messages = db.query(func.count(WhatsAppMessage.id)).scalar()
    unread_total = db.query(func.sum(Conversation.unread_count)).scalar() or 0
    
    return {
        "total_conversations": total_conversations,
        "active_conversations": active_conversations,
        "human_conversations": human_conversations,
        "total_messages": total_messages,
        "unread_total": unread_total
    }


async def message_stream(db: Session, last_id: int):
    """Generator para SSE de novas mensagens."""
    while True:
        messages = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.id > last_id
        ).order_by(WhatsAppMessage.id).all()
        
        for msg in messages:
            last_id = msg.id
            data = {
                "id": msg.id,
                "phone": msg.phone,
                "from_me": msg.from_me,
                "body": msg.body,
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            }
            yield f"data: {json.dumps(data)}\n\n"
        
        await asyncio.sleep(2)


@router.get("/stream")
async def stream_messages(
    last_id: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """SSE endpoint para receber mensagens em tempo real."""
    return StreamingResponse(
        message_stream(db, last_id),
        media_type="text/event-stream"
    )
