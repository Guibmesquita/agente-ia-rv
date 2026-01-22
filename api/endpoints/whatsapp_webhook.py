"""
Webhook para receber mensagens do WhatsApp via WAHA.
Processa mensagens de texto, áudio, imagem, vídeo e documentos.
Registra todas as mensagens no banco de dados.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import json

from database.database import get_db, SessionLocal
from database.models import WhatsAppMessage, MessageDirection, MessageType
from database import crud
from services.whatsapp_client import whatsapp_client
from services.openai_agent import openai_agent
from services.vector_store import get_vector_store

router = APIRouter(prefix="/api/webhook", tags=["WhatsApp Webhook"])


def is_phone_allowed(phone: str, db: Session) -> bool:
    """Verifica se o telefone está autorizado a receber respostas."""
    config = crud.get_agent_config(db)
    if not config:
        return True
    
    filter_mode = getattr(config, 'filter_mode', 'all') or 'all'
    
    if filter_mode == "all":
        return True
    
    allowed_phones = getattr(config, 'allowed_phones', '') or ''
    if not allowed_phones.strip():
        return True
    
    clean_phone = phone.replace("@c.us", "").replace("@s.whatsapp.net", "")
    clean_phone = clean_phone.replace("+", "").replace("-", "").replace(" ", "")
    
    allowed_list = [p.strip().replace("+", "").replace("-", "").replace(" ", "") 
                    for p in allowed_phones.split(",") if p.strip()]
    
    for allowed in allowed_list:
        if clean_phone.endswith(allowed) or allowed.endswith(clean_phone) or clean_phone == allowed:
            return True
    
    return False

conversation_history: Dict[str, list] = {}


def get_message_type(payload: Dict[str, Any]) -> str:
    """
    Determina o tipo de mensagem baseado no payload do WAHA.
    """
    if payload.get("hasMedia"):
        mimetype = payload.get("media", {}).get("mimetype", "")
        
        if mimetype.startswith("audio/"):
            return MessageType.AUDIO.value
        elif mimetype.startswith("image/"):
            return MessageType.IMAGE.value
        elif mimetype.startswith("video/"):
            return MessageType.VIDEO.value
        elif mimetype.startswith("application/"):
            return MessageType.DOCUMENT.value
        elif "sticker" in mimetype or payload.get("type") == "sticker":
            return MessageType.STICKER.value
        else:
            return MessageType.UNKNOWN.value
    
    if payload.get("type") == "location":
        return MessageType.LOCATION.value
    
    if payload.get("type") == "vcard" or payload.get("type") == "contact":
        return MessageType.CONTACT.value
    
    return MessageType.TEXT.value


def save_message(
    db: Session,
    waha_message_id: str,
    chat_id: str,
    direction: str,
    message_type: str,
    body: str = None,
    media_url: str = None,
    media_mimetype: str = None,
    media_filename: str = None,
    ai_response: str = None,
    ai_intent: str = None,
    ticket_id: int = None
) -> WhatsAppMessage:
    """
    Salva uma mensagem no banco de dados.
    """
    phone = chat_id.replace("@c.us", "").replace("@s.whatsapp.net", "")
    
    message = WhatsAppMessage(
        waha_message_id=waha_message_id,
        chat_id=chat_id,
        phone=phone,
        direction=direction,
        message_type=message_type,
        body=body,
        media_url=media_url,
        media_mimetype=media_mimetype,
        media_filename=media_filename,
        ai_response=ai_response,
        ai_intent=ai_intent,
        ticket_id=ticket_id
    )
    
    db.add(message)
    db.commit()
    db.refresh(message)
    
    return message


async def process_text_message(phone: str, message: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa uma mensagem de texto e gera resposta usando IA.
    Busca na base de conhecimento para enriquecer o contexto.
    """
    try:
        await whatsapp_client.start_typing(phone)
        
        history = conversation_history.get(phone, [])
        
        knowledge_context = ""
        try:
            vector_store = get_vector_store()
            search_results = vector_store.search(message, n_results=3)
            
            if search_results:
                knowledge_context = "\n\n--- Informações da Base de Conhecimento ---\n"
                for i, result in enumerate(search_results, 1):
                    title = result.get("metadata", {}).get("document_title", "Documento")
                    content = result.get("content", "")[:500]
                    knowledge_context += f"\n[{i}] {title}:\n{content}\n"
        except Exception as e:
            print(f"[WEBHOOK] Erro ao buscar na base de conhecimento: {e}")
        
        response, should_create_ticket, context = await openai_agent.generate_response(
            message,
            history,
            extra_context=knowledge_context
        )
        
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        conversation_history[phone] = history[-10:]
        
        ticket = None
        if should_create_ticket:
            user = crud.get_user_by_phone(db, phone.replace("@c.us", ""))
            
            ticket = crud.create_ticket(
                db,
                title=f"Chamado via WhatsApp - {phone}",
                description=f"Cliente solicitou atendimento.\n\nÚltima mensagem: {message}",
                client_id=user.id if user else None,
                client_phone=phone.replace("@c.us", "")
            )
            
            response += f"\n\nChamado #{ticket.id} criado com sucesso!"
        
        if message_record:
            message_record.ai_response = response
            message_record.ai_intent = context.get("intent") if context else None
            if ticket:
                message_record.ticket_id = ticket.id
            db.commit()
        
        await whatsapp_client.stop_typing(phone)
        
        result = await whatsapp_client.send_message(phone, response)
        
        if result.get("success"):
            save_message(
                db,
                waha_message_id=result.get("message_id"),
                chat_id=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=MessageType.TEXT.value,
                body=response,
                ticket_id=ticket.id if ticket else None
            )
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar mensagem: {e}")
        error_msg = (
            "Desculpe, ocorreu um erro ao processar sua mensagem. "
            "Por favor, tente novamente mais tarde ou entre em contato com seu assessor."
        )
        await whatsapp_client.send_message(phone, error_msg)


async def process_audio_message(phone: str, media_url: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa mensagem de áudio.
    Por enquanto, informa ao usuário que áudio foi recebido.
    Futuramente: transcrever usando Whisper API.
    """
    try:
        await whatsapp_client.start_typing(phone)
        
        response = (
            "Recebi seu áudio! 🎙️\n\n"
            "No momento, estou processando apenas mensagens de texto. "
            "Por favor, digite sua dúvida ou solicitação para que eu possa te ajudar."
        )
        
        if message_record:
            message_record.ai_response = response
            db.commit()
        
        await whatsapp_client.stop_typing(phone)
        await whatsapp_client.send_message(phone, response)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar áudio: {e}")


async def process_image_message(phone: str, media_url: str, caption: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa mensagem de imagem.
    Se tiver legenda, processa como texto.
    """
    try:
        if caption:
            await process_text_message(phone, caption, db, message_record)
        else:
            await whatsapp_client.start_typing(phone)
            
            response = (
                "Recebi sua imagem! 📷\n\n"
                "Se precisar de ajuda com algo específico relacionado a esta imagem, "
                "por favor descreva sua dúvida em texto."
            )
            
            if message_record:
                message_record.ai_response = response
                db.commit()
            
            await whatsapp_client.stop_typing(phone)
            await whatsapp_client.send_message(phone, response)
            
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar imagem: {e}")


async def process_document_message(phone: str, media_url: str, filename: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa mensagem de documento.
    Informa ao usuário que o documento foi recebido.
    """
    try:
        await whatsapp_client.start_typing(phone)
        
        response = (
            f"Recebi o documento '{filename}' 📄\n\n"
            "Obrigado pelo envio! Se precisar de ajuda com algo relacionado "
            "a este documento, por favor me informe."
        )
        
        if message_record:
            message_record.ai_response = response
            db.commit()
        
        await whatsapp_client.stop_typing(phone)
        await whatsapp_client.send_message(phone, response)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar documento: {e}")


@router.post("/whatsapp")
async def whatsapp_webhook(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Endpoint que recebe mensagens do WAHA.
    Processa mensagens de texto, áudio, imagem, vídeo e documentos.
    Registra todas as mensagens no banco de dados.
    """
    event = payload.get("event", "")
    
    if event != "message":
        return {"status": "ignored", "reason": "not a message event"}
    
    message_payload = payload.get("payload", {})
    
    if message_payload.get("fromMe", False):
        return {"status": "ignored", "reason": "message from self"}
    
    chat_id = message_payload.get("from", "")
    waha_message_id = message_payload.get("id", "")
    body = message_payload.get("body", "")
    has_media = message_payload.get("hasMedia", False)
    media_info = message_payload.get("media", {})
    
    if "@g.us" in chat_id:
        return {"status": "ignored", "reason": "group message"}
    
    if not is_phone_allowed(chat_id, db):
        print(f"[WEBHOOK] Número não autorizado: {chat_id}")
        return {"status": "ignored", "reason": "phone not allowed"}
    
    message_type = get_message_type(message_payload)
    
    try:
        message_record = save_message(
            db,
            waha_message_id=waha_message_id,
            chat_id=chat_id,
            direction=MessageDirection.INBOUND.value,
            message_type=message_type,
            body=body if body else None,
            media_url=media_info.get("url") if has_media else None,
            media_mimetype=media_info.get("mimetype") if has_media else None,
            media_filename=media_info.get("filename") if has_media else None
        )
    except Exception as e:
        print(f"[WEBHOOK] Erro ao salvar mensagem: {e}")
        message_record = None
    
    try:
        await whatsapp_client.send_seen(chat_id)
    except Exception as e:
        print(f"[WEBHOOK] Erro ao marcar como visto: {e}")
    
    if message_type == MessageType.TEXT.value:
        if body:
            background_tasks.add_task(process_text_message, chat_id, body, db, message_record)
        else:
            return {"status": "ignored", "reason": "empty text message"}
            
    elif message_type == MessageType.AUDIO.value:
        background_tasks.add_task(
            process_audio_message, 
            chat_id, 
            media_info.get("url"), 
            db, 
            message_record
        )
        
    elif message_type == MessageType.IMAGE.value:
        background_tasks.add_task(
            process_image_message, 
            chat_id, 
            media_info.get("url"),
            body,
            db, 
            message_record
        )
        
    elif message_type == MessageType.DOCUMENT.value:
        background_tasks.add_task(
            process_document_message, 
            chat_id, 
            media_info.get("url"),
            media_info.get("filename", "documento"),
            db, 
            message_record
        )
        
    elif message_type == MessageType.VIDEO.value:
        response = "Recebi seu vídeo! 🎥 Por favor, descreva sua dúvida em texto."
        if message_record:
            message_record.ai_response = response
            db.commit()
        background_tasks.add_task(whatsapp_client.send_message, chat_id, response)
        
    elif message_type == MessageType.STICKER.value:
        return {"status": "ignored", "reason": "sticker message"}
        
    else:
        return {"status": "ignored", "reason": f"unsupported message type: {message_type}"}
    
    return {
        "status": "processing",
        "message_type": message_type,
        "message_id": message_record.id if message_record else None
    }


@router.get("/health")
async def health_check():
    """Endpoint de verificação de saúde do webhook."""
    return {
        "status": "ok",
        "ai_available": openai_agent.is_available()
    }


@router.get("/messages")
async def list_messages(
    phone: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Lista mensagens registradas.
    Útil para debugging e verificação.
    """
    query = db.query(WhatsAppMessage)
    
    if phone:
        query = query.filter(WhatsAppMessage.phone.like(f"%{phone}%"))
    
    messages = query.order_by(WhatsAppMessage.created_at.desc()).limit(limit).all()
    
    return {
        "total": len(messages),
        "messages": [
            {
                "id": m.id,
                "phone": m.phone,
                "direction": m.direction,
                "type": m.message_type,
                "body": m.body[:100] if m.body else None,
                "ai_response": m.ai_response[:100] if m.ai_response else None,
                "created_at": m.created_at.isoformat() if m.created_at else None
            }
            for m in messages
        ]
    }
