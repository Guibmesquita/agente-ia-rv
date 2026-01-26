"""
API endpoints para gerenciamento de conversas.
Permite visualizar histórico, buscar por número e intervir humanamente.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import os
import httpx

from database.database import get_db
from database.models import (
    Conversation, WhatsAppMessage, Assessor, User,
    ConversationStatus, SenderType, MessageDirection
)
from api.endpoints.auth import get_current_user


router = APIRouter(prefix="/conversations", tags=["Conversations"])


class ConversationResponse(BaseModel):
    id: int
    phone: str
    contact_name: Optional[str] = None
    assessor_name: Optional[str] = None
    assessor_email: Optional[str] = None
    status: str
    assigned_to_name: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_preview: Optional[str] = None
    unread_count: int = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


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
    """Remove caracteres especiais do telefone."""
    if not phone:
        return ""
    return ''.join(c for c in phone if c.isdigit())


@router.get("/", response_model=List[ConversationResponse])
async def list_conversations(
    search: Optional[str] = Query(None, description="Buscar por número ou nome"),
    status: Optional[str] = Query(None, description="Filtrar por status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as conversas com filtros e busca."""
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
    
    conversations = query.order_by(desc(Conversation.last_message_at)).offset(skip).limit(limit).all()
    
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
            status=conv.status,
            assigned_to_name=assigned_user.username if assigned_user else None,
            last_message_at=conv.last_message_at,
            last_message_preview=conv.last_message_preview,
            unread_count=conv.unread_count,
            created_at=conv.created_at
        ))
    
    return result


@router.post("/start")
async def start_new_conversation(
    request: StartConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Inicia uma nova conversa com um número de telefone ou envia para conversa existente."""
    phone = normalize_phone(request.phone)
    
    if len(phone) < 10 or len(phone) > 15:
        raise HTTPException(status_code=400, detail="Número de telefone inválido")
    
    message_text = request.message.strip() if request.message else ""
    if not message_text:
        raise HTTPException(status_code=400, detail="A mensagem não pode estar vazia")
    
    waha_api_key = os.environ.get("WAHA_API_KEY", "")
    waha_base_url = os.environ.get("WAHA_API_URL", "https://waha-cvm7.onrender.com")
    
    if not waha_api_key:
        raise HTTPException(status_code=500, detail="WAHA API não configurada")
    
    existing_conv = db.query(Conversation).filter(Conversation.phone == phone).first()
    is_new_conversation = existing_conv is None
    
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
            assigned_to=current_user.id
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    
    chat_id = f"{phone}@c.us"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{waha_base_url}/api/sendText",
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": waha_api_key
                },
                json={
                    "session": "default",
                    "chatId": chat_id,
                    "text": message_text
                }
            )
            
            if response.status_code not in [200, 201]:
                raise HTTPException(
                    status_code=500,
                    detail=f"Erro ao enviar mensagem: {response.text}"
                )
            
            response_data = response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")
    
    message = WhatsAppMessage(
        waha_message_id=response_data.get("key", {}).get("id"),
        chat_id=chat_id,
        phone=phone,
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


@router.post("/{conversation_id}/send")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Envia uma mensagem manualmente (intervenção humana)."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    waha_api_key = os.environ.get("WAHA_API_KEY", "")
    waha_base_url = os.environ.get("WAHA_API_URL", "https://waha-cvm7.onrender.com")
    
    if not waha_api_key:
        raise HTTPException(status_code=500, detail="WAHA API não configurada")
    
    chat_id = f"{conv.phone}@c.us"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{waha_base_url}/api/sendText",
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": waha_api_key
                },
                json={
                    "session": "default",
                    "chatId": chat_id,
                    "text": request.message
                }
            )
            
            if response.status_code not in [200, 201]:
                raise HTTPException(
                    status_code=500,
                    detail=f"Erro ao enviar mensagem: {response.text}"
                )
            
            response_data = response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Erro de conexão: {str(e)}")
    
    message = WhatsAppMessage(
        waha_message_id=response_data.get("key", {}).get("id"),
        chat_id=chat_id,
        phone=conv.phone,
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
    """Assume ou libera uma conversa para atendimento humano."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    if request.action == "takeover":
        conv.status = ConversationStatus.HUMAN_TAKEOVER.value
        conv.assigned_to = current_user.id
        message = f"Conversa assumida por {current_user.username}"
    elif request.action == "release":
        conv.status = ConversationStatus.BOT_ACTIVE.value
        conv.assigned_to = None
        message = "Conversa devolvida ao agente"
    else:
        raise HTTPException(status_code=400, detail="Ação inválida")
    
    db.commit()
    
    return {"success": True, "message": message, "status": conv.status}


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
