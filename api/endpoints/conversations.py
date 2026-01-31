"""
API endpoints para gerenciamento de conversas.
Permite visualizar histórico, buscar por número e intervir humanamente.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
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
    ConversationStatus, ConversationState, SenderType, MessageDirection
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
    status: Optional[str] = Query(None, description="Filtrar por status"),
    skip: int = Query(0, ge=0),
    offset: int = Query(None, ge=0, description="Alias for skip"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lista todas as conversas com filtros e busca."""
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
            status=conv.status,
            assigned_to_name=assigned_user.username if assigned_user else None,
            last_message_at=conv.last_message_at,
            last_message_preview=conv.last_message_preview,
            unread_count=conv.unread_count,
            created_at=conv.created_at
        ))
    
    return result


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
