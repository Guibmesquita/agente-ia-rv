"""
Webhook para receber mensagens do WhatsApp via Z-API.
Processa mensagens de texto, áudio, imagem, vídeo e documentos.
Registra todas as mensagens no banco de dados.
Documentação: https://developer.z-api.io/webhooks/on-message-received
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import json

from database.database import get_db, SessionLocal
from database.models import (
    WhatsAppMessage, MessageDirection, MessageType, MessageStatus,
    Conversation, ConversationStatus, SenderType, Assessor
)
from database import crud
from services.whatsapp_client import zapi_client
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
    
    clean_phone = ''.join(filter(str.isdigit, phone))
    
    allowed_list = [p.strip().replace("+", "").replace("-", "").replace(" ", "") 
                    for p in allowed_phones.split(",") if p.strip()]
    
    for allowed in allowed_list:
        if clean_phone.endswith(allowed) or allowed.endswith(clean_phone) or clean_phone == allowed:
            return True
    
    return False

conversation_history: Dict[str, list] = {}


def get_message_type_zapi(payload: Dict[str, Any]) -> str:
    """
    Determina o tipo de mensagem baseado no payload do Z-API.
    """
    if payload.get("image"):
        return MessageType.IMAGE.value
    elif payload.get("audio"):
        return MessageType.AUDIO.value
    elif payload.get("video"):
        return MessageType.VIDEO.value
    elif payload.get("document"):
        return MessageType.DOCUMENT.value
    elif payload.get("sticker"):
        return MessageType.STICKER.value
    elif payload.get("location"):
        return MessageType.LOCATION.value
    elif payload.get("contact"):
        return MessageType.CONTACT.value
    elif payload.get("text"):
        return MessageType.TEXT.value
    
    return MessageType.TEXT.value


def get_or_create_conversation(
    db: Session, 
    phone: str, 
    sender_name: str = None, 
    sender_photo: str = None,
    sender_lid: str = None,
    chat_lid: str = None
) -> Conversation:
    """
    Obtém ou cria uma conversa.
    Busca primeiro por LID, depois por phone (seguindo recomendação Z-API).
    """
    conv = None
    
    if sender_lid:
        conv = db.query(Conversation).filter(Conversation.lid == sender_lid).first()
    
    if not conv and phone:
        conv = db.query(Conversation).filter(Conversation.phone == phone).first()
    
    if not conv:
        from database.models import ConversationState
        
        assessor = None
        if phone:
            assessor = db.query(Assessor).filter(
                Assessor.telefone_whatsapp.contains(phone)
            ).first()
        
        initial_state = ConversationState.READY.value if assessor else ConversationState.IDENTIFICATION_PENDING.value
        
        conv = Conversation(
            phone=phone if phone else None,
            lid=sender_lid,
            chat_lid=chat_lid,
            contact_name=sender_name or (assessor.nome if assessor else None),
            assessor_id=assessor.id if assessor else None,
            status=ConversationStatus.BOT_ACTIVE.value,
            conversation_state=initial_state,
            lid_source="webhook" if sender_lid else None,
            lid_collected_at=datetime.utcnow() if sender_lid else None
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    else:
        updated = False
        if sender_lid and not conv.lid:
            conv.lid = sender_lid
            conv.lid_source = "webhook"
            conv.lid_collected_at = datetime.utcnow()
            updated = True
        if chat_lid and not conv.chat_lid:
            conv.chat_lid = chat_lid
            updated = True
        if phone and not conv.phone:
            conv.phone = phone
            updated = True
        if sender_name and not conv.contact_name:
            conv.contact_name = sender_name
            updated = True
        if updated:
            db.commit()
    
    return conv


def update_conversation_metadata(db: Session, conversation: Conversation, message_body: str, is_inbound: bool = True):
    """Atualiza metadados da conversa após nova mensagem."""
    conversation.last_message_at = datetime.utcnow()
    if message_body:
        conversation.last_message_preview = message_body[:100] if len(message_body) > 100 else message_body
    
    if is_inbound:
        conversation.unread_count = (conversation.unread_count or 0) + 1
    
    db.commit()


def save_message_zapi(
    db: Session,
    message_id: str,
    zaap_id: str,
    phone: str,
    direction: str,
    message_type: str,
    from_me: bool = False,
    message_status: str = None,
    body: str = None,
    media_url: str = None,
    media_mimetype: str = None,
    media_filename: str = None,
    thumbnail_url: str = None,
    sender_name: str = None,
    sender_photo: str = None,
    ai_response: str = None,
    ai_intent: str = None,
    ticket_id: int = None,
    sender_type: str = None,
    sender_lid: str = None,
    chat_lid: str = None
) -> WhatsAppMessage:
    """
    Salva uma mensagem no banco de dados e atualiza a conversa (formato Z-API).
    Agora com suporte a LID (identificador privado do WhatsApp).
    """
    clean_phone = ''.join(filter(str.isdigit, phone)) if phone else ""
    
    conversation = get_or_create_conversation(
        db, 
        clean_phone if clean_phone else None, 
        sender_name, 
        sender_photo,
        sender_lid=sender_lid,
        chat_lid=chat_lid
    )
    
    if sender_type is None:
        sender_type = SenderType.CONTACT.value if direction == MessageDirection.INBOUND.value else SenderType.BOT.value
    
    if not message_status:
        message_status = MessageStatus.RECEIVED.value if direction == MessageDirection.INBOUND.value else MessageStatus.SENT.value
    
    effective_chat_id = clean_phone if clean_phone else (chat_lid or sender_lid or "unknown")
    effective_phone = clean_phone if clean_phone else None
    
    message = WhatsAppMessage(
        message_id=message_id,
        zaap_id=zaap_id,
        chat_id=effective_chat_id,
        phone=effective_phone,
        from_me=from_me,
        direction=direction,
        message_type=message_type,
        message_status=message_status,
        sender_type=sender_type,
        sender_name=sender_name,
        sender_photo=sender_photo,
        body=body,
        media_url=media_url,
        media_mimetype=media_mimetype,
        media_filename=media_filename,
        thumbnail_url=thumbnail_url,
        ai_response=ai_response,
        ai_intent=ai_intent,
        ticket_id=ticket_id,
        conversation_id=conversation.id
    )
    
    db.add(message)
    db.commit()
    db.refresh(message)
    
    is_inbound = direction == MessageDirection.INBOUND.value
    update_conversation_metadata(db, conversation, body, is_inbound)
    
    return message


async def process_text_message(phone: str, message: str, db: Session, message_record: WhatsAppMessage = None, conversation: Conversation = None):
    """
    Processa uma mensagem de texto seguindo o framework de fluxo:
    Recebe mensagem → identifica remetente → verifica estado → classifica → 
    avalia transferência → responde ou transfere.
    """
    from services.conversation_flow import (
        normalize_message, extract_first_name, identify_contact,
        get_transfer_message, should_transfer_to_human, update_conversation_state,
        increment_stalled_counter, reset_stalled_counter
    )
    from database.models import ConversationState, TransferReason
    
    try:
        normalized_message = normalize_message(message)
        
        if not conversation:
            conversation = db.query(Conversation).filter(Conversation.phone == phone).first()
        
        if not conversation:
            print(f"[WEBHOOK] Conversa não encontrada para {phone}")
            return
        
        conv_state = conversation.conversation_state or ConversationState.IDENTIFICATION_PENDING.value
        
        is_human_mode = (
            conv_state == ConversationState.HUMAN_TAKEOVER.value or 
            conversation.status == ConversationStatus.HUMAN_TAKEOVER.value
        )
        if is_human_mode:
            print(f"[WEBHOOK] Conversa em HUMAN_TAKEOVER - bot não responde, aguardando humano")
            if message_record:
                message_record.ai_response = None
                message_record.ai_intent = "blocked_human_takeover"
                db.commit()
            return
        
        assessor, is_known = identify_contact(db, phone)
        
        if not is_known:
            if conv_state == ConversationState.IDENTIFICATION_PENDING.value:
                update_conversation_state(db, conversation, ConversationState.READY.value)
                conv_state = ConversationState.READY.value
                
                extracted_name = extract_first_name(normalized_message)
                if extracted_name:
                    conversation.contact_name = extracted_name
                    db.commit()
                    
                    response = f"Oi, {extracted_name}! Sou o Stevan, suporte de RV. Nao encontrei seu cadastro na base, mas posso ajudar com duvidas sobre renda variavel. O que precisa?"
                else:
                    response = "Oi! Sou o Stevan, suporte de RV. Nao encontrei seu cadastro na nossa base, mas posso ajudar com duvidas sobre renda variavel. Como posso ajudar?"
                
                if message_record:
                    message_record.ai_response = response
                    message_record.ai_intent = "unidentified_contact_greeting"
                    db.commit()
                
                result = await zapi_client.send_text(phone, response, delay_typing=1)
                if result.get("success"):
                    save_message_zapi(
                        db, message_id=result.get("message_id"), zaap_id=result.get("zaap_id"),
                        phone=phone, direction=MessageDirection.OUTBOUND.value,
                        message_type=MessageType.TEXT.value, from_me=True, body=response,
                        sender_type=SenderType.BOT.value
                    )
                return
        else:
            if conv_state == ConversationState.IDENTIFICATION_PENDING.value:
                update_conversation_state(db, conversation, ConversationState.READY.value)
                conv_state = ConversationState.READY.value
            
            if not conversation.assessor_id and assessor:
                conversation.assessor_id = assessor.id
                conversation.contact_name = assessor.nome
                db.commit()
        
        should_transfer, transfer_reason = should_transfer_to_human(normalized_message, conversation)
        
        if should_transfer:
            response = get_transfer_message(transfer_reason)
            update_conversation_state(
                db, conversation, ConversationState.HUMAN_TAKEOVER.value,
                transfer_reason=transfer_reason,
                transfer_notes=f"Última mensagem: {normalized_message[:200]}"
            )
            
            if message_record:
                message_record.ai_response = response
                message_record.ai_intent = "transfer_to_human"
                db.commit()
            
            result = await zapi_client.send_text(phone, response, delay_typing=1)
            if result.get("success"):
                save_message_zapi(
                    db, message_id=result.get("message_id"), zaap_id=result.get("zaap_id"),
                    phone=phone, direction=MessageDirection.OUTBOUND.value,
                    message_type=MessageType.TEXT.value, from_me=True, body=response,
                    sender_type=SenderType.BOT.value
                )
            return
        
        if conv_state != ConversationState.IN_PROGRESS.value:
            update_conversation_state(db, conversation, ConversationState.IN_PROGRESS.value)
        
        history = conversation_history.get(phone, [])
        
        knowledge_context = ""
        try:
            vector_store = get_vector_store()
            search_results = vector_store.search(normalized_message, n_results=3)
            
            if search_results:
                knowledge_context = "\n\n--- Informações da Base de Conhecimento ---\n"
                for i, result in enumerate(search_results, 1):
                    title = result.get("metadata", {}).get("document_title", "Documento")
                    content = result.get("content", "")[:500]
                    knowledge_context += f"\n[{i}] {title}:\n{content}\n"
        except Exception as e:
            print(f"[WEBHOOK] Erro ao buscar na base de conhecimento: {e}")
        
        assessor_data = None
        if assessor:
            assessor_data = {
                "id": assessor.id,
                "nome": assessor.nome,
                "telefone": assessor.telefone_whatsapp,
                "unidade": assessor.unidade,
                "equipe": assessor.equipe,
                "broker": assessor.broker_responsavel
            }
        
        response, should_create_ticket, context = await openai_agent.generate_response(
            normalized_message,
            history,
            extra_context=knowledge_context,
            sender_phone=phone,
            identified_assessor=assessor_data
        )
        
        history.append({"role": "user", "content": normalized_message})
        history.append({"role": "assistant", "content": response})
        conversation_history[phone] = history[-10:]
        
        reset_stalled_counter(db, conversation)
        
        ticket = None
        if should_create_ticket:
            user = crud.get_user_by_phone(db, phone)
            
            ticket = crud.create_ticket(
                db,
                title=f"Chamado via WhatsApp - {phone}",
                description=f"Cliente solicitou atendimento.\n\nÚltima mensagem: {normalized_message}",
                client_id=user.id if user else None,
                client_phone=phone
            )
            
            response += f"\n\nChamado #{ticket.id} criado com sucesso!"
        
        if message_record:
            message_record.ai_response = response
            message_record.ai_intent = context.get("intent") if context else None
            if ticket:
                message_record.ticket_id = ticket.id
            db.commit()
        
        send_result = await zapi_client.send_text(phone, response, delay_typing=2)
        
        if send_result.get("success"):
            save_message_zapi(
                db,
                message_id=send_result.get("message_id"),
                zaap_id=send_result.get("zaap_id"),
                phone=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=MessageType.TEXT.value,
                from_me=True,
                body=response,
                ticket_id=ticket.id if ticket else None,
                sender_type=SenderType.BOT.value
            )
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar mensagem: {e}")
        import traceback
        traceback.print_exc()
        error_msg = (
            "Desculpe, ocorreu um erro ao processar sua mensagem. "
            "Por favor, tente novamente mais tarde ou entre em contato com seu assessor."
        )
        await zapi_client.send_text(phone, error_msg)


async def process_audio_message(phone: str, media_url: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa mensagem de áudio.
    Por enquanto, informa ao usuário que áudio foi recebido.
    """
    try:
        response = (
            "Recebi seu áudio! 🎙️\n\n"
            "No momento, estou processando apenas mensagens de texto. "
            "Por favor, digite sua dúvida ou solicitação para que eu possa te ajudar."
        )
        
        if message_record:
            message_record.ai_response = response
            db.commit()
        
        await zapi_client.send_text(phone, response, delay_typing=1)
        
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
            response = (
                "Recebi sua imagem! 📷\n\n"
                "Se precisar de ajuda com algo específico relacionado a esta imagem, "
                "por favor descreva sua dúvida em texto."
            )
            
            if message_record:
                message_record.ai_response = response
                db.commit()
            
            await zapi_client.send_text(phone, response, delay_typing=1)
            
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar imagem: {e}")


async def process_document_message(phone: str, media_url: str, filename: str, db: Session, message_record: WhatsAppMessage = None):
    """
    Processa mensagem de documento.
    Informa ao usuário que o documento foi recebido.
    """
    try:
        response = (
            f"Recebi o documento '{filename}' 📄\n\n"
            "Obrigado pelo envio! Se precisar de ajuda com algo relacionado "
            "a este documento, por favor me informe."
        )
        
        if message_record:
            message_record.ai_response = response
            db.commit()
        
        await zapi_client.send_text(phone, response, delay_typing=1)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar documento: {e}")


@router.post("/zapi")
async def zapi_webhook(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Endpoint que recebe mensagens do Z-API.
    Formatos suportados:
    - ReceivedCallback: Mensagens recebidas (e enviadas se "Notificar enviadas por mim" estiver ativo)
    - DeliveryCallback: Confirmação de mensagens enviadas via API
    Documentação: https://developer.z-api.io/webhooks/on-message-received
    """
    event_type = payload.get("type", "")
    
    if event_type == "DeliveryCallback":
        phone = payload.get("phone", "")
        message_id = payload.get("messageId", "")
        zaap_id = payload.get("zaapId", "")
        
        print(f"[WEBHOOK] DeliveryCallback recebido - phone: {phone}, messageId: {message_id}")
        
        if message_id:
            existing = db.query(WhatsAppMessage).filter(
                WhatsAppMessage.message_id == message_id
            ).first()
            
            if existing:
                existing.message_status = "SENT"
                db.commit()
                return {"status": "updated", "reason": "message status updated to SENT"}
        
        return {"status": "ignored", "reason": "DeliveryCallback - no action needed"}
    
    if event_type != "ReceivedCallback":
        return {"status": "ignored", "reason": f"event type: {event_type}"}
    
    from_me = payload.get("fromMe", False)
    phone = payload.get("phone", "")
    message_id = payload.get("messageId", "")
    is_group = payload.get("isGroup", False)
    sender_name = payload.get("senderName") or payload.get("chatName")
    sender_photo = payload.get("senderPhoto") or payload.get("photo")
    status = payload.get("status", "RECEIVED")
    
    sender_lid = payload.get("senderLid")
    chat_lid = payload.get("chatLid")
    
    if is_group:
        return {"status": "ignored", "reason": "group message"}
    
    if from_me:
        try:
            existing_message = db.query(WhatsAppMessage).filter(
                WhatsAppMessage.message_id == message_id
            ).first()
            
            if existing_message:
                print(f"[WEBHOOK] Mensagem já existe (id={message_id}), atualizando status")
                if status:
                    existing_message.message_status = status
                    db.commit()
                return {"status": "updated", "reason": "message already exists"}
            
            outbound_body = None
            outbound_media_url = None
            outbound_media_mimetype = None
            outbound_media_filename = None
            
            if payload.get("text"):
                text_data = payload["text"]
                outbound_body = text_data.get("message", "") if isinstance(text_data, dict) else str(text_data)
            elif payload.get("image"):
                outbound_body = payload["image"].get("caption", "[Imagem]")
                outbound_media_url = payload["image"].get("imageUrl")
                outbound_media_mimetype = payload["image"].get("mimeType")
            elif payload.get("audio"):
                outbound_body = "[Áudio]"
                outbound_media_url = payload["audio"].get("audioUrl")
                outbound_media_mimetype = payload["audio"].get("mimeType")
            elif payload.get("video"):
                outbound_body = payload["video"].get("caption", "[Vídeo]")
                outbound_media_url = payload["video"].get("videoUrl")
                outbound_media_mimetype = payload["video"].get("mimeType")
            elif payload.get("document"):
                outbound_body = payload["document"].get("fileName", "[Documento]")
                outbound_media_url = payload["document"].get("documentUrl")
                outbound_media_mimetype = payload["document"].get("mimeType")
                outbound_media_filename = payload["document"].get("fileName")
            elif payload.get("sticker"):
                outbound_body = "[Sticker]"
                outbound_media_url = payload["sticker"].get("stickerUrl")
            
            save_message_zapi(
                db,
                message_id=message_id,
                zaap_id=None,
                phone=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=get_message_type_zapi(payload),
                from_me=True,
                message_status=status,
                body=outbound_body,
                media_url=outbound_media_url,
                media_mimetype=outbound_media_mimetype,
                media_filename=outbound_media_filename,
                sender_type=SenderType.HUMAN.value,
                sender_lid=sender_lid,
                chat_lid=chat_lid
            )
        except Exception as e:
            print(f"[WEBHOOK] Erro ao salvar mensagem enviada: {e}")
            import traceback
            traceback.print_exc()
        return {"status": "saved", "reason": "message from self"}
    
    if not is_phone_allowed(phone, db):
        print(f"[WEBHOOK] Número não autorizado: {phone}")
        return {"status": "ignored", "reason": "phone not allowed"}
    
    conversation = None
    if sender_lid:
        conversation = db.query(Conversation).filter(Conversation.lid == sender_lid).first()
    if not conversation and phone:
        conversation = db.query(Conversation).filter(Conversation.phone == phone).first()
    is_human_takeover = conversation and conversation.status == ConversationStatus.HUMAN_TAKEOVER.value
    
    message_type = get_message_type_zapi(payload)
    
    body = None
    media_url = None
    media_mimetype = None
    media_filename = None
    thumbnail_url = None
    
    if payload.get("text"):
        body = payload["text"].get("message", "")
    elif payload.get("image"):
        media_url = payload["image"].get("imageUrl")
        media_mimetype = payload["image"].get("mimeType")
        thumbnail_url = payload["image"].get("thumbnailUrl")
        body = payload["image"].get("caption", "")
    elif payload.get("audio"):
        media_url = payload["audio"].get("audioUrl")
        media_mimetype = payload["audio"].get("mimeType")
    elif payload.get("video"):
        media_url = payload["video"].get("videoUrl")
        media_mimetype = payload["video"].get("mimeType")
        body = payload["video"].get("caption", "")
    elif payload.get("document"):
        media_url = payload["document"].get("documentUrl")
        media_mimetype = payload["document"].get("mimeType")
        media_filename = payload["document"].get("fileName")
        thumbnail_url = payload["document"].get("thumbnailUrl")
    elif payload.get("sticker"):
        media_url = payload["sticker"].get("stickerUrl")
        media_mimetype = payload["sticker"].get("mimeType")
    
    try:
        message_record = save_message_zapi(
            db,
            message_id=message_id,
            zaap_id=None,
            phone=phone,
            direction=MessageDirection.INBOUND.value,
            message_type=message_type,
            from_me=False,
            message_status=status,
            body=body,
            media_url=media_url,
            media_mimetype=media_mimetype,
            media_filename=media_filename,
            thumbnail_url=thumbnail_url,
            sender_name=sender_name,
            sender_photo=sender_photo,
            sender_lid=sender_lid,
            chat_lid=chat_lid
        )
    except Exception as e:
        print(f"[WEBHOOK] Erro ao salvar mensagem: {e}")
        message_record = None
    
    if is_human_takeover:
        print(f"[WEBHOOK] Conversa em modo humano, não respondendo automaticamente: {phone}")
        return {
            "status": "received",
            "message_type": message_type,
            "message_id": message_record.id if message_record else None,
            "auto_response": False,
            "reason": "human_takeover"
        }
    
    if message_type == MessageType.TEXT.value:
        if body:
            background_tasks.add_task(process_text_message, phone, body, db, message_record)
        else:
            return {"status": "ignored", "reason": "empty text message"}
            
    elif message_type == MessageType.AUDIO.value:
        background_tasks.add_task(
            process_audio_message, 
            phone, 
            media_url, 
            db, 
            message_record
        )
        
    elif message_type == MessageType.IMAGE.value:
        background_tasks.add_task(
            process_image_message, 
            phone, 
            media_url,
            body,
            db, 
            message_record
        )
        
    elif message_type == MessageType.DOCUMENT.value:
        background_tasks.add_task(
            process_document_message, 
            phone, 
            media_url,
            media_filename or "documento",
            db, 
            message_record
        )
        
    elif message_type == MessageType.VIDEO.value:
        response = "Recebi seu vídeo! 🎥 Por favor, descreva sua dúvida em texto."
        if message_record:
            message_record.ai_response = response
            db.commit()
        background_tasks.add_task(zapi_client.send_text, phone, response)
        
    elif message_type == MessageType.STICKER.value:
        return {"status": "ignored", "reason": "sticker message"}
        
    else:
        return {"status": "ignored", "reason": f"unsupported message type: {message_type}"}
    
    return {
        "status": "processing",
        "message_type": message_type,
        "message_id": message_record.id if message_record else None
    }


@router.post("/whatsapp")
async def whatsapp_webhook_legacy(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Endpoint legado para WAHA. Redireciona para o novo formato se detectar Z-API.
    """
    if payload.get("type") == "ReceivedCallback":
        return await zapi_webhook(payload, background_tasks, db)
    
    return {"status": "ignored", "reason": "legacy endpoint - use /api/webhook/zapi"}


@router.post("/status")
async def status_webhook(
    payload: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Webhook para atualizações de status de mensagens (Z-API).
    Atualiza o status da mensagem no banco de dados.
    """
    message_id = payload.get("messageId")
    status = payload.get("status")
    
    if message_id and status:
        message = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.message_id == message_id
        ).first()
        
        if message:
            message.message_status = status
            db.commit()
            return {"status": "updated", "message_id": message_id, "new_status": status}
    
    return {"status": "ignored"}


@router.get("/health")
async def health_check():
    """Endpoint de verificação de saúde do webhook."""
    return {
        "status": "ok",
        "ai_available": openai_agent.is_available(),
        "api": "z-api"
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
                "message_id": m.message_id,
                "phone": m.phone,
                "from_me": m.from_me,
                "direction": m.direction,
                "type": m.message_type,
                "status": m.message_status,
                "body": m.body[:100] if m.body else None,
                "ai_response": m.ai_response[:100] if m.ai_response else None,
                "created_at": m.created_at.isoformat() if m.created_at else None
            }
            for m in messages
        ]
    }
