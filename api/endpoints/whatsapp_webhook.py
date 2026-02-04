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
    Conversation, ConversationStatus, SenderType, Assessor, RetrievalLog,
    EscalationLevel, TicketStatusV2
)
from database import crud
from services.whatsapp_client import zapi_client
from services.openai_agent import openai_agent
from services.vector_store import get_vector_store
from services.sse_manager import get_sse_manager
from services.insight_analyzer import save_conversation_insight
from services.media_processor import media_processor
import asyncio

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
    
    from services.conversation_flow import identify_contact
    
    assessor = None
    if phone:
        assessor, _ = identify_contact(db, phone)
    
    if not conv:
        from database.models import ConversationState
        
        initial_state = ConversationState.READY.value if assessor else ConversationState.IDENTIFICATION_PENDING.value
        
        conv = Conversation(
            phone=phone if phone else None,
            lid=sender_lid,
            chat_lid=chat_lid,
            contact_name=assessor.nome if assessor else None,
            assessor_id=assessor.id if assessor else None,
            status=ConversationStatus.BOT_ACTIVE.value,
            conversation_state=initial_state,
            lid_source="webhook" if sender_lid else None,
            lid_collected_at=datetime.utcnow() if sender_lid else None,
            # V2 Ticket: bot ativo = T0, sem ticket_status (só recebe NEW quando escalado)
            escalation_level=EscalationLevel.T0_BOT.value,
            ticket_status=None
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
        if assessor and not conv.assessor_id:
            conv.assessor_id = assessor.id
            conv.contact_name = assessor.nome
            updated = True
        elif assessor and not conv.contact_name:
            conv.contact_name = assessor.nome
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
    
    try:
        sse_manager = get_sse_manager()
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(sse_manager.notify_new_message(
                conversation.id,
                {
                    "id": message.id,
                    "direction": direction,
                    "body": body[:200] if body else None,
                    "sender_type": sender_type,
                    "phone": phone
                }
            ))
    except Exception as e:
        print(f"[SSE] Erro ao notificar nova mensagem: {e}")
    
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
        increment_stalled_counter, reset_stalled_counter, escalate_to_human_with_analysis,
        is_positive_confirmation, mark_bot_resolved
    )
    from database.models import ConversationState, TransferReason
    
    print(f"[WEBHOOK] Iniciando process_text_message para {phone}: {message[:50]}...")
    
    try:
        normalized_message = normalize_message(message)
        print(f"[WEBHOOK] Mensagem normalizada: {normalized_message[:50]}...")
        
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
        
        if conversation.awaiting_confirmation:
            if is_positive_confirmation(normalized_message):
                print(f"[WEBHOOK] Confirmação positiva detectada - marcando como resolvido pelo bot")
                await mark_bot_resolved(db, conversation)
                
                farewell_messages = [
                    "Boa! Qualquer coisa, é só chamar! 👋",
                    "Tranquilo! Precisando, estou por aqui!",
                    "Show! Fico à disposição! 🚀",
                    "Perfeito! Até mais!",
                    "Beleza! Qualquer dúvida, só chamar!",
                ]
                import random
                response = random.choice(farewell_messages)
                
                if message_record:
                    message_record.ai_response = response
                    message_record.ai_intent = "bot_resolution_confirmed"
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
                conversation.awaiting_confirmation = False
                conversation.confirmation_sent_at = None
                db.commit()
                print(f"[WEBHOOK] Nova dúvida após confirmação - continuando atendimento")
        
        assessor, is_known = identify_contact(db, phone)
        print(f"[WEBHOOK] Assessor identificado: {assessor.nome if assessor else 'Nenhum'}, conhecido: {is_known}")
        
        if not is_known:
            if conv_state == ConversationState.IDENTIFICATION_PENDING.value:
                update_conversation_state(db, conversation, ConversationState.READY.value)
                conv_state = ConversationState.READY.value
                
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
            try:
                escalation_result = await escalate_to_human_with_analysis(
                    db, conversation, normalized_message, transfer_reason
                )
                created_ticket_id = escalation_result.get("ticket_id") if escalation_result else None
                broker_name = escalation_result.get("broker_name") if escalation_result else None
                assessor_first_name = escalation_result.get("assessor_name") if escalation_result else None
                
                print(f"[WEBHOOK] Escalação V2.1 completa - categoria: {conversation.escalation_category}, ticket: {created_ticket_id}, broker: {broker_name}")
                
                if assessor_first_name and broker_name:
                    response = f"{assessor_first_name}, registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif broker_name:
                    response = f"Registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif assessor_first_name:
                    response = f"{assessor_first_name}, registrado! O broker que te acompanha já tá sendo avisado e responde em breve."
                else:
                    response = get_transfer_message(transfer_reason)
                
                if created_ticket_id:
                    response += f"\n\nChamado #{created_ticket_id} criado com sucesso!"
                    
            except Exception as e:
                print(f"[WEBHOOK] Erro na análise de escalação, usando fallback: {e}")
                import traceback
                traceback.print_exc()
                conversation.escalation_category = "other"
                conversation.escalation_reason_detail = str(transfer_reason) if transfer_reason else "Transferência automática"
                conversation.ticket_summary = normalized_message[:200] if normalized_message else "Solicitação de atendimento"
                conversation.conversation_topic = "Geral"
                conversation.ticket_status = TicketStatusV2.NEW.value
                conversation.escalation_level = EscalationLevel.T1_HUMAN.value
                conversation.status = ConversationState.HUMAN_TAKEOVER.value
                conversation.conversation_state = ConversationState.HUMAN_TAKEOVER.value
                conversation.transfer_reason = transfer_reason
                conversation.transferred_at = datetime.utcnow()
                db.commit()
                response = get_transfer_message(transfer_reason)
            
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
        retrieval_start = datetime.now()
        search_results = []
        try:
            vector_store = get_vector_store()
            from services.vector_store import filter_expired_results
            search_results = vector_store.search(normalized_message, n_results=6, similarity_threshold=0.8)
            
            search_results = filter_expired_results(search_results, db)[:3]
            
            if search_results:
                knowledge_context = "\n\n--- Informações da Base de Conhecimento ---\n"
                for i, result in enumerate(search_results, 1):
                    title = result.get("metadata", {}).get("document_title", "Documento")
                    content = result.get("content", "")[:500]
                    knowledge_context += f"\n[{i}] {title}:\n{content}\n"
        except Exception as e:
            print(f"[WEBHOOK] Erro ao buscar na base de conhecimento: {e}")
        
        retrieval_time = int((datetime.now() - retrieval_start).total_seconds() * 1000)
        chunks_retrieved = []
        chunk_versions = {}
        min_distance = None
        max_distance = None
        query_type = None
        
        if search_results:
            for r in search_results:
                meta = r.get("metadata", {})
                block_id = meta.get("block_id", "")
                if block_id:
                    chunks_retrieved.append(block_id)
                    chunk_versions[block_id] = meta.get("version", "1")
                
                dist = r.get("original_distance") or r.get("distance", 0)
                if min_distance is None or dist < min_distance:
                    min_distance = dist
                if max_distance is None or dist > max_distance:
                    max_distance = dist
                
                if not query_type:
                    query_type = r.get("query_type", "conceptual")
        
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
        
        print(f"[WEBHOOK] Chamando OpenAI para gerar resposta...")
        response, should_create_ticket, context = await openai_agent.generate_response(
            normalized_message,
            history,
            extra_context=knowledge_context,
            sender_phone=phone,
            identified_assessor=assessor_data
        )
        print(f"[WEBHOOK] Resposta gerada: {response[:100] if response else 'VAZIA'}...")
        
        history.append({"role": "user", "content": normalized_message})
        assistant_entry = {"role": "assistant", "content": response}
        if context:
            assistant_entry["metadata"] = context
        history.append(assistant_entry)
        conversation_history[phone] = history[-10:]
        
        reset_stalled_counter(db, conversation)
        
        is_human_transfer = should_create_ticket or (context and context.get("human_transfer"))
        transfer_reason = None
        created_ticket_id = None
        
        if is_human_transfer:
            transfer_reason = context.get("transfer_reason", "Solicitação de atendimento") if context else "Solicitação de atendimento"
            
            try:
                escalation_result = await escalate_to_human_with_analysis(
                    db, conversation, normalized_message, transfer_reason
                )
                created_ticket_id = escalation_result.get("ticket_id") if escalation_result else None
                broker_name = escalation_result.get("broker_name") if escalation_result else None
                assessor_first_name = escalation_result.get("assessor_name") if escalation_result else None
                
                print(f"[WEBHOOK] Escalação via OpenAI completa - ticket_status: {conversation.ticket_status}, ticket_id: {created_ticket_id}, broker: {broker_name}")
                
                if created_ticket_id:
                    if assessor_first_name and broker_name:
                        response = f"{assessor_first_name}, registrado! O {broker_name} já tá sendo avisado e responde em breve."
                    elif broker_name:
                        response = f"Registrado! O {broker_name} já tá sendo avisado e responde em breve."
                    elif assessor_first_name:
                        response = f"{assessor_first_name}, registrado! O broker que te acompanha já tá sendo avisado e responde em breve."
                    else:
                        response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
                    
                    response += f"\n\nChamado #{created_ticket_id} criado com sucesso!"
            except Exception as e:
                print(f"[WEBHOOK] Erro na escalação via OpenAI, usando fallback: {e}")
                import traceback
                traceback.print_exc()
                conversation.escalation_category = "other"
                conversation.escalation_reason_detail = str(transfer_reason) if transfer_reason else "Transferência automática"
                conversation.ticket_summary = normalized_message[:200] if normalized_message else "Solicitação de atendimento"
                conversation.conversation_topic = "Geral"
                conversation.ticket_status = TicketStatusV2.NEW.value
                conversation.escalation_level = EscalationLevel.T1_HUMAN.value
                conversation.status = ConversationStatus.HUMAN_TAKEOVER.value
                conversation.conversation_state = ConversationState.HUMAN_TAKEOVER.value
                conversation.transfer_reason = transfer_reason
                conversation.transferred_at = datetime.utcnow()
                db.commit()
                response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
        
        if message_record:
            message_record.ai_response = response
            message_record.ai_intent = context.get("intent") if context else None
            if created_ticket_id:
                message_record.ticket_id = created_ticket_id
            db.commit()
        
        try:
            retrieval_log = RetrievalLog(
                query=normalized_message,
                query_type=query_type,
                chunks_retrieved=json.dumps(chunks_retrieved) if chunks_retrieved else None,
                chunks_used=json.dumps(chunks_retrieved[:3]) if chunks_retrieved else None,
                chunk_versions=json.dumps(chunk_versions) if chunk_versions else None,
                result_count=len(search_results),
                min_distance=str(round(min_distance, 4)) if min_distance else None,
                max_distance=str(round(max_distance, 4)) if max_distance else None,
                threshold_applied="0.8",
                human_transfer=is_human_transfer,
                transfer_reason=transfer_reason,
                conversation_id=str(conversation.id) if conversation else None,
                response_time_ms=retrieval_time
            )
            db.add(retrieval_log)
            db.commit()
        except Exception as log_err:
            print(f"[WEBHOOK] Erro ao salvar RetrievalLog: {log_err}")
        
        print(f"[WEBHOOK] Enviando resposta via Z-API para {phone}...")
        send_result = await zapi_client.send_text(phone, response, delay_typing=2)
        print(f"[WEBHOOK] Resultado envio Z-API: {send_result}")
        
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
                ticket_id=created_ticket_id,
                sender_type=SenderType.BOT.value
            )
            
            if conversation and conversation.escalation_level == EscalationLevel.T0_BOT.value:
                conversation.last_bot_response_at = datetime.utcnow()
                db.commit()
            
            try:
                await save_conversation_insight(
                    db=db,
                    conversation_id=str(conversation.id) if conversation else None,
                    user_message=normalized_message,
                    agent_response=response,
                    resolved_by_ai=not is_human_transfer,
                    escalated_to_human=is_human_transfer,
                    ticket_id=created_ticket_id,
                    assessor_phone=phone
                )
            except Exception as insight_err:
                print(f"[WEBHOOK] Erro ao salvar insight: {insight_err}")
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar mensagem: {e}")
        import traceback
        traceback.print_exc()
        error_msg = (
            "Desculpe, ocorreu um erro ao processar sua mensagem. "
            "Por favor, tente novamente mais tarde ou entre em contato com seu assessor."
        )
        await zapi_client.send_text(phone, error_msg)


async def process_audio_message(phone: str, media_url: str, db: Session, message_record: WhatsAppMessage = None, conversation: Conversation = None):
    """
    Processa mensagem de áudio.
    Transcreve o áudio via Whisper e passa pelo pipeline completo da IA.
    """
    try:
        print(f"[WEBHOOK] Processando áudio de {phone}: {media_url[:50]}...")
        
        transcription, error = await media_processor.transcribe_audio(media_url)
        
        if error or not transcription:
            response = (
                "Recebi seu áudio! 🎙️\n\n"
                "Infelizmente não consegui transcrever o áudio. "
                "Por favor, tente enviar novamente ou digite sua mensagem."
            )
            
            if message_record:
                message_record.ai_response = response
                message_record.ai_intent = "audio_transcription_failed"
                db.commit()
            
            await zapi_client.send_text(phone, response, delay_typing=1)
            return
        
        if message_record:
            if hasattr(message_record, 'body') and not message_record.body:
                message_record.body = f"[Áudio transcrito]: {transcription}"
            db.commit()
        
        formatted_message = media_processor.format_transcription_for_ai(transcription, "áudio")
        print(f"[WEBHOOK] Áudio transcrito, processando via IA: {transcription[:100]}...")
        
        await process_text_message(phone, formatted_message, db, message_record, conversation)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar áudio: {e}")
        import traceback
        traceback.print_exc()
        
        response = (
            "Recebi seu áudio, mas ocorreu um erro no processamento. "
            "Por favor, tente enviar sua mensagem por texto."
        )
        await zapi_client.send_text(phone, response, delay_typing=1)


async def process_image_message(phone: str, media_url: str, caption: str, db: Session, message_record: WhatsAppMessage = None, conversation: Conversation = None):
    """
    Processa mensagem de imagem.
    Analisa a imagem via GPT-4 Vision e passa pelo pipeline completo da IA.
    """
    try:
        print(f"[WEBHOOK] Processando imagem de {phone}: {media_url[:50]}...")
        
        analysis, error = await media_processor.analyze_image(media_url, caption)
        
        if error or not analysis:
            if caption:
                await process_text_message(phone, caption, db, message_record, conversation)
            else:
                response = (
                    "Recebi sua imagem! 📷\n\n"
                    "Não consegui analisar a imagem no momento. "
                    "Se precisar de ajuda, por favor descreva sua dúvida em texto."
                )
                
                if message_record:
                    message_record.ai_response = response
                    message_record.ai_intent = "image_analysis_failed"
                    db.commit()
                
                await zapi_client.send_text(phone, response, delay_typing=1)
            return
        
        full_context = analysis
        if caption:
            full_context = f"{analysis}\n\nLegenda enviada pelo usuário: {caption}"
        
        if message_record:
            if hasattr(message_record, 'body') and not message_record.body:
                message_record.body = f"[Imagem]: {analysis[:200]}..."
            db.commit()
        
        formatted_message = media_processor.format_transcription_for_ai(full_context, "imagem")
        print(f"[WEBHOOK] Imagem analisada, processando via IA: {analysis[:100]}...")
        
        await process_text_message(phone, formatted_message, db, message_record, conversation)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar imagem: {e}")
        import traceback
        traceback.print_exc()
        
        if caption:
            await process_text_message(phone, caption, db, message_record, conversation)
        else:
            response = (
                "Recebi sua imagem, mas ocorreu um erro no processamento. "
                "Por favor, descreva sua dúvida em texto."
            )
            await zapi_client.send_text(phone, response, delay_typing=1)


async def process_document_message(phone: str, media_url: str, filename: str, db: Session, message_record: WhatsAppMessage = None, conversation: Conversation = None):
    """
    Processa mensagem de documento.
    Extrai informações do documento e passa pelo pipeline da IA.
    """
    try:
        print(f"[WEBHOOK] Processando documento de {phone}: {filename or media_url[:50]}...")
        
        extracted_text, error = await media_processor.extract_document_text(media_url, filename)
        
        if error or not extracted_text:
            response = (
                f"Recebi o documento '{filename or 'arquivo'}' 📄\n\n"
                "Obrigado pelo envio! Se precisar de ajuda com algo relacionado "
                "a este documento, por favor me descreva sua dúvida."
            )
            
            if message_record:
                message_record.ai_response = response
                message_record.ai_intent = "document_processing_failed"
                db.commit()
            
            await zapi_client.send_text(phone, response, delay_typing=1)
            return
        
        if message_record:
            if hasattr(message_record, 'body') and not message_record.body:
                message_record.body = f"[Documento: {filename}]: {extracted_text[:200]}..."
            db.commit()
        
        formatted_message = media_processor.format_transcription_for_ai(
            f"Arquivo: {filename or 'documento'}\n\n{extracted_text}", 
            "documento"
        )
        print(f"[WEBHOOK] Documento processado, enviando para IA: {extracted_text[:100]}...")
        
        await process_text_message(phone, formatted_message, db, message_record, conversation)
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar documento: {e}")
        import traceback
        traceback.print_exc()
        
        response = (
            f"Recebi o documento '{filename or 'arquivo'}' 📄\n\n"
            "Obrigado pelo envio! Se tiver alguma dúvida sobre ele, me fale."
        )
        await zapi_client.send_text(phone, response, delay_typing=1)


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
            background_tasks.add_task(process_text_message, phone, body, db, message_record, conversation)
        else:
            return {"status": "ignored", "reason": "empty text message"}
            
    elif message_type == MessageType.AUDIO.value:
        background_tasks.add_task(
            process_audio_message, 
            phone, 
            media_url, 
            db, 
            message_record,
            conversation
        )
        
    elif message_type == MessageType.IMAGE.value:
        background_tasks.add_task(
            process_image_message, 
            phone, 
            media_url,
            body,
            db, 
            message_record,
            conversation
        )
        
    elif message_type == MessageType.DOCUMENT.value:
        background_tasks.add_task(
            process_document_message, 
            phone, 
            media_url,
            media_filename or "documento",
            db, 
            message_record,
            conversation
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
