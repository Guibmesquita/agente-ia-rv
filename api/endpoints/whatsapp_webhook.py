"""
Webhook para receber mensagens do WhatsApp via Z-API.
Processa mensagens de texto, áudio, imagem, vídeo e documentos.
Registra todas as mensagens no banco de dados.
Documentação: https://developer.z-api.io/webhooks/on-message-received
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import json
import os
import re

from database.database import get_db, SessionLocal
from database.models import (
    WhatsAppMessage, MessageDirection, MessageType, MessageStatus,
    Conversation, ConversationStatus, SenderType, Assessor, RetrievalLog,
    EscalationLevel, TicketStatusV2, ConversationTicket
)
from database import crud
from services.whatsapp_client import zapi_client
from services.openai_agent import openai_agent
from services.sse_manager import get_sse_manager
from services.insight_analyzer import save_conversation_insight
from services.media_processor import media_processor
from services.conversation_memory import (
    get_history, update_history, append_to_history,
    handle_session_transition, build_context_with_summary,
    enqueue_message, schedule_task, _history_cache,
)
import asyncio

router = APIRouter(prefix="/api/webhook", tags=["WhatsApp Webhook"])

conversation_history = _history_cache


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


def _is_lid_not_phone(value: str) -> bool:
    """
    Detecta se um valor é um LID (Linked Identity) da Z-API, não um telefone real.
    LIDs são numéricos longos (>14 dígitos) sem formato de telefone brasileiro.
    Telefones BR: 55 + DDD(2) + número(8-9) = 12-13 dígitos.
    Também detecta valores com sufixo @lid.
    """
    if not value:
        return False
    if "@lid" in value:
        return True
    clean = ''.join(filter(str.isdigit, value))
    if len(clean) > 13:
        return True
    return False


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
    Busca por: 1) sender_lid, 2) phone, 3) chat_lid match (LID-aware), 4) cria nova.
    Quando o phone recebido é um LID (não telefone real), busca por chat_lid correspondente.
    """
    conv = None
    phone_is_lid = _is_lid_not_phone(phone) if phone else False
    real_phone = None if phone_is_lid else phone
    lid_from_phone = phone if phone_is_lid else None
    
    if sender_lid:
        conv = db.query(Conversation).filter(Conversation.lid == sender_lid).first()
    
    if not conv and real_phone:
        conv = db.query(Conversation).filter(Conversation.phone == real_phone).first()
    
    if not conv and phone:
        clean_val = phone.replace("@lid", "")
        conv = db.query(Conversation).filter(
            Conversation.chat_lid == clean_val + "@lid"
        ).first()
        if not conv:
            conv = db.query(Conversation).filter(
                Conversation.chat_lid == phone
            ).first()
    
    if not conv and lid_from_phone:
        normalized_lid = phone.replace("@lid", "")
        conv = db.query(Conversation).filter(Conversation.lid == normalized_lid).first()
        if not conv:
            conv = db.query(Conversation).filter(Conversation.lid == phone).first()
    
    from services.conversation_flow import identify_contact
    
    assessor = None
    if real_phone:
        assessor, _ = identify_contact(db, real_phone)
    
    if not conv:
        from database.models import ConversationState
        
        initial_state = ConversationState.READY.value if assessor else ConversationState.IDENTIFICATION_PENDING.value
        
        conv = Conversation(
            phone=real_phone,
            lid=sender_lid or lid_from_phone,
            chat_lid=chat_lid,
            contact_name=assessor.nome if assessor else None,
            assessor_id=assessor.id if assessor else None,
            status=ConversationStatus.BOT_ACTIVE.value,
            conversation_state=initial_state,
            lid_source="webhook" if (sender_lid or lid_from_phone) else None,
            lid_collected_at=datetime.utcnow() if (sender_lid or lid_from_phone) else None,
            escalation_level=EscalationLevel.T0_BOT.value,
            ticket_status=None
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        if phone_is_lid:
            print(f"[CONV] Nova conversa criada com LID (sem phone real): lid={lid_from_phone}")
    else:
        updated = False
        if sender_lid and not conv.lid:
            conv.lid = sender_lid
            conv.lid_source = "webhook"
            conv.lid_collected_at = datetime.utcnow()
            updated = True
        if lid_from_phone and not conv.lid:
            conv.lid = lid_from_phone
            conv.lid_source = "webhook_phone_as_lid"
            conv.lid_collected_at = datetime.utcnow()
            updated = True
        if chat_lid and not conv.chat_lid:
            conv.chat_lid = chat_lid
            updated = True
        if real_phone and not conv.phone:
            conv.phone = real_phone
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
        if phone_is_lid:
            print(f"[CONV] Conversa existente encontrada via LID match: conv_id={conv.id}, phone={conv.phone}")
    
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
    conversation_ticket_id: int = None,
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
    
    phone_is_lid = _is_lid_not_phone(clean_phone)
    effective_chat_id = clean_phone if clean_phone else (chat_lid or sender_lid or "unknown")
    effective_phone = (conversation.phone or clean_phone) if not phone_is_lid else (conversation.phone or None)
    
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
        conversation_ticket_id=conversation_ticket_id,
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




async def _send_diagram_for_slug(phone: str, slug: str, db: Session):
    import os
    from scripts.xpi_derivatives.derivatives_dataset import get_all_structures

    campaign_struct = None
    try:
        from database.models import CampaignStructure
        from datetime import datetime as _dt
        now = _dt.utcnow()
        campaign_struct = db.query(CampaignStructure).filter(
            CampaignStructure.campaign_slug == slug,
            CampaignStructure.is_active == 1,
            (CampaignStructure.valid_from.is_(None)) | (CampaignStructure.valid_from <= now),
            (CampaignStructure.valid_until.is_(None)) | (CampaignStructure.valid_until >= now),
        ).first()
    except Exception as e:
        print(f"[DIAGRAM] Erro ao buscar campanha para slug {slug}: {e}")

    if campaign_struct and campaign_struct.diagram_filename:
        diagram_path = os.path.join("static", "derivatives_diagrams", campaign_struct.diagram_filename)
        if os.path.exists(diagram_path):
            from core.config import get_public_domain
            domain = get_public_domain()
            diagram_url = f"https://{domain}/derivatives-diagrams/{campaign_struct.diagram_filename}"
            name = campaign_struct.name
            caption = f"📊 Diagrama de Payoff - {name}"
            print(f"[DIAGRAM] Usando diagrama de campanha ativa: {name} ({slug})")
        else:
            print(f"[DIAGRAM] Diagrama de campanha não encontrado: {diagram_path}, tentando padrão")
            campaign_struct = None

    if not campaign_struct or not (campaign_struct and campaign_struct.diagram_filename):
        structures = get_all_structures()
        lookup_slug = slug

        structure = None
        for s in structures:
            if s["slug"] == lookup_slug:
                structure = s
                break

        if not structure:
            try:
                from database.models import CampaignStructure as CS
                expired_cs = db.query(CS).filter(CS.campaign_slug == slug).first()
                if expired_cs and expired_cs.structure_type:
                    fallback_type = expired_cs.structure_type
                    print(f"[DIAGRAM] Slug '{slug}' expirado/inativo, tentando fallback via structure_type: {fallback_type}")
                    for s in structures:
                        if s["slug"] == fallback_type:
                            structure = s
                            lookup_slug = fallback_type
                            break
            except Exception as e:
                print(f"[DIAGRAM] Erro no fallback de campanha expirada: {e}")

        if not structure:
            print(f"[DIAGRAM] Estrutura não encontrada para slug: {slug}")
            return False

        diagram_path = os.path.join("static", "derivatives_diagrams", f"{lookup_slug}.png")
        if not os.path.exists(diagram_path):
            print(f"[DIAGRAM] Arquivo de diagrama não encontrado: {diagram_path}")
            return False

        from core.config import get_public_domain
        domain = get_public_domain()

        diagram_url = f"https://{domain}/derivatives-diagrams/{lookup_slug}.png"
        name = structure.get("name", lookup_slug)
        caption = f"📊 Diagrama de Payoff - {name}"

    print(f"[DIAGRAM] Enviando diagrama: {name} ({slug}) para {phone}")
    print(f"[DIAGRAM] URL: {diagram_url}")

    try:
        result = await zapi_client.send_image(
            to=phone,
            image_url=diagram_url,
            caption=caption
        )

        if result.get("success"):
            print(f"[DIAGRAM] Diagrama enviado com sucesso: {name}")
            save_message_zapi(
                db,
                message_id=result.get("message_id"),
                zaap_id=result.get("zaap_id"),
                phone=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=MessageType.IMAGE.value,
                from_me=True,
                body=caption,
                sender_type=SenderType.BOT.value
            )
            return True
        else:
            print(f"[DIAGRAM] Erro ao enviar diagrama {name}: {result}")
            return False
    except Exception as e:
        print(f"[DIAGRAM] Exceção ao enviar diagrama {name}: {e}")
        return False


DIAGRAM_MARKER_PATTERN = re.compile(r'\[ENVIAR_DIAGRAMA:([a-z0-9\-]+)\]')
MATERIAL_MARKER_PATTERN = re.compile(r'\[ENVIAR_MATERIAL:(\d+)\]')

def _extract_diagram_markers(response: str) -> Tuple[str, List[str]]:
    markers = DIAGRAM_MARKER_PATTERN.findall(response)
    clean_response = DIAGRAM_MARKER_PATTERN.sub('', response).strip()
    clean_response = re.sub(r'\n{3,}', '\n\n', clean_response)
    return clean_response, markers


def _extract_material_markers(response: str) -> Tuple[str, List[str]]:
    markers = MATERIAL_MARKER_PATTERN.findall(response)
    clean_response = MATERIAL_MARKER_PATTERN.sub('', response).strip()
    clean_response = re.sub(r'\n{3,}', '\n\n', clean_response)
    return clean_response, markers


async def _send_material_pdf(phone: str, material_id: str, db: Session) -> dict:
    """
    Tenta enviar um material PDF via WhatsApp.
    Retorna dict com:
      - success: bool
      - reason: str ("sent", "no_file", "no_material", "no_config", "send_error", "exception")
      - material_name: str (nome do material, se encontrado)
    """
    try:
        from database.models import Material, MaterialFile
        material = db.query(Material).filter(Material.id == int(material_id)).first()
        if not material:
            print(f"[MATERIAL] Material não encontrado: {material_id}")
            return {"success": False, "reason": "no_material", "material_name": ""}

        if getattr(material, 'publish_status', None) == 'arquivado':
            print(f"[MATERIAL] Material {material_id} está arquivado — envio bloqueado")
            return {"success": False, "reason": "archived", "material_name": material.name or ""}

        product = material.product
        product_name = product.name if product else material.name

        has_db_file = db.query(MaterialFile).filter(MaterialFile.material_id == int(material_id)).first() is not None

        if not has_db_file:
            print(f"[MATERIAL] Material {material_id} ({product_name}) não possui arquivo PDF em material_files")
            return {"success": False, "reason": "no_file", "material_name": product_name}

        from core.config import get_public_base_url
        base_url = get_public_base_url()

        if not base_url:
            print(f"[MATERIAL] Erro: domínio público não configurado (APP_BASE_URL)")
            return {"success": False, "reason": "no_config", "material_name": product_name}

        file_url = f"{base_url}/api/files/{material_id}/download"

        filename = f"{product_name} - {material.material_type}.pdf"
        filename = re.sub(r'[^\w\s\-\.]', '', filename).strip()

        caption = f"📄 {product_name}"
        if material.material_type:
            type_labels = {
                'one_page': 'One Pager',
                'apresentacao': 'Apresentação',
                'comite': 'Material do Comitê',
                'relatorio': 'Relatório',
                'lamina': 'Lâmina',
                'research': 'Research',
            }
            label = type_labels.get(material.material_type, material.material_type.replace('_', ' ').title())
            caption += f" | {label}"

        print(f"[MATERIAL] Enviando PDF: {filename} para {phone}")
        print(f"[MATERIAL] URL: {file_url}")

        from services.whatsapp_client import WhatsAppClient
        whatsapp = WhatsAppClient()
        result = await whatsapp.send_document(phone, file_url, filename, caption)

        if result.get("success"):
            print(f"[MATERIAL] PDF enviado com sucesso: {filename}")
            return {"success": True, "reason": "sent", "material_name": product_name}
        else:
            print(f"[MATERIAL] Erro ao enviar PDF {filename}: {result}")
            return {"success": False, "reason": "send_error", "material_name": product_name}
    except Exception as e:
        print(f"[MATERIAL] Exceção ao enviar material {material_id}: {e}")
        return {"success": False, "reason": "exception", "material_name": ""}


async def _send_materials_from_markers(phone: str, material_ids: List[str], db: Session) -> dict:
    """
    Retorna dict com:
      - sent: list de IDs enviados com sucesso
      - failed: list de dicts com detalhes da falha
    """
    sent_ids = []
    failed_details = []
    for mid in material_ids:
        result = await _send_material_pdf(phone, mid, db)
        if result.get("success"):
            sent_ids.append(mid)
        else:
            print(f"[MATERIAL-MARKER] Falha ao enviar material ID: {mid} — razão: {result.get('reason')}")
            failed_details.append({
                "material_id": mid,
                "reason": result.get("reason", "unknown"),
                "material_name": result.get("material_name", ""),
            })
    return {"sent": sent_ids, "failed": failed_details}


async def _send_diagrams_from_markers(phone: str, slugs: List[str], db: Session) -> List[str]:
    sent_slugs = []
    for slug in slugs:
        success = await _send_diagram_for_slug(phone, slug, db)
        if success:
            sent_slugs.append(slug)
        else:
            print(f"[DIAGRAM-MARKER] Falha ao enviar diagrama para slug: {slug}")
    return sent_slugs




def _is_farewell_or_emoji(text: str) -> bool:
    import re as _re
    cleaned = text.strip().lower()
    cleaned = _re.sub(r'[!.,;:?]+', '', cleaned).strip()
    if not cleaned:
        return True
    if _re.fullmatch(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F\U0000200D\U0001F1E0-\U0001F1FF\s]+', cleaned):
        return True
    farewell_terms = [
        "até", "ate", "tchau", "flw", "falou", "fui", "abraço", "abraco",
        "até mais", "ate mais", "até logo", "tmj", "tamo junto",
        "bom trabalho",
    ]
    for term in farewell_terms:
        if cleaned == term or cleaned.startswith(term + " "):
            return True
    if _re.fullmatch(r'(at[eé]|tchau|flw|falou|abra[cç]o|tmj)\s*(obrigad[oa])?[\s!]*', cleaned):
        return True
    return False


async def process_text_message(phone: str, message: str, db: Session, message_record: WhatsAppMessage = None, conversation: Conversation = None):
    """
    Processa uma mensagem de texto seguindo o framework de fluxo:
    Recebe mensagem → identifica remetente → verifica estado → classifica → 
    avalia transferência → responde ou transfere.
    """
    from services.conversation_flow import (
        normalize_message, extract_first_name, identify_contact,
        update_conversation_state,
        increment_stalled_counter, reset_stalled_counter, escalate_to_human_with_analysis,
        is_positive_confirmation, mark_bot_resolved
    )
    from database.models import ConversationState
    
    print(f"[WEBHOOK] Iniciando process_text_message para {phone}: {message[:50]}...")
    
    try:
        from services.cadence_controller import track_campaign_response
        track_campaign_response(phone, db)
    except Exception as track_err:
        print(f"[WEBHOOK] Erro ao rastrear resposta de campanha: {track_err}")
    
    response_sent_successfully = False
    
    try:
        normalized_message = normalize_message(message)
        print(f"[WEBHOOK] Mensagem normalizada: {normalized_message[:50]}...")
        
        import asyncio as _asyncio
        _asyncio.create_task(zapi_client.send_composing(phone))
        
        if not conversation:
            conversation = db.query(Conversation).filter(Conversation.phone == phone).first()
        
        if not conversation:
            print(f"[WEBHOOK] Conversa não encontrada para {phone}")
            return
        
        conv_state = conversation.conversation_state or ConversationState.IDENTIFICATION_PENDING.value
        
        # Bot NÃO responde apenas quando ticket_status = 'open' (atendimento humano ativo)
        is_human_active = conversation.ticket_status == TicketStatusV2.OPEN.value
        
        if is_human_active:
            print(f"[WEBHOOK] Ticket OPEN (atendimento humano ativo) - bot não responde")
            if message_record:
                message_record.ai_response = None
                message_record.ai_intent = "blocked_ticket_open"
                db.commit()
            return
        
        if conversation.ticket_status == TicketStatusV2.SOLVED.value:
            if is_positive_confirmation(normalized_message) or _is_farewell_or_emoji(normalized_message):
                print(f"[WEBHOOK] Ticket SOLVED + despedida/emoji/agradecimento — ignorando (sem loop): {phone}")
                if message_record:
                    message_record.ai_response = None
                    message_record.ai_intent = "solved_farewell_ignored"
                    db.commit()
                return
            conversation.ticket_status = None
            db.commit()
            print(f"[WEBHOOK] Ticket reaberto em process_text_message (era solved): {phone}")
        
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
                    response_sent_successfully = True
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
        
        stalled = conversation.stalled_interactions or 0
        if stalled >= 3:
            print(f"[WEBHOOK] Stalled interactions >= 3, escalando para humano")
            try:
                escalation_result = await escalate_to_human_with_analysis(
                    db, conversation, normalized_message, "no_progress"
                )
                created_ticket_id = escalation_result.get("ticket_id") if escalation_result else None
                broker_name = escalation_result.get("broker_name") if escalation_result else None
                assessor_first_name = escalation_result.get("assessor_name") if escalation_result else None
                
                if assessor_first_name and broker_name:
                    response = f"{assessor_first_name}, registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif broker_name:
                    response = f"Registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif assessor_first_name:
                    response = f"{assessor_first_name}, registrado! O broker que te acompanha já tá sendo avisado e responde em breve."
                else:
                    response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
                
                if created_ticket_id:
                    response += f"\n\nChamado #{created_ticket_id} criado com sucesso!"
                    
            except Exception as e:
                print(f"[WEBHOOK] Erro na escalação por stalled, usando fallback: {e}")
                import traceback
                traceback.print_exc()
                conversation.ticket_status = TicketStatusV2.NEW.value
                conversation.escalation_level = EscalationLevel.T1_HUMAN.value
                conversation.status = ConversationState.HUMAN_TAKEOVER.value
                conversation.conversation_state = ConversationState.HUMAN_TAKEOVER.value
                conversation.transfer_reason = "no_progress"
                conversation.transferred_at = datetime.utcnow()
                db.commit()
                response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
            
            if message_record:
                message_record.ai_response = response
                message_record.ai_intent = "transfer_to_human"
                db.commit()
            
            result = await zapi_client.send_text(phone, response, delay_typing=1)
            if result.get("success"):
                response_sent_successfully = True
                save_message_zapi(
                    db, message_id=result.get("message_id"), zaap_id=result.get("zaap_id"),
                    phone=phone, direction=MessageDirection.OUTBOUND.value,
                    message_type=MessageType.TEXT.value, from_me=True, body=response,
                    sender_type=SenderType.BOT.value
                )
            return
        
        if conv_state != ConversationState.IN_PROGRESS.value:
            update_conversation_state(db, conversation, ConversationState.IN_PROGRESS.value)
        
        await handle_session_transition(phone, db, conversation)
        
        history = get_history(phone, db)
        
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
                    response_sent_successfully = True
                    save_message_zapi(
                        db, message_id=result.get("message_id"), zaap_id=result.get("zaap_id"),
                        phone=phone, direction=MessageDirection.OUTBOUND.value,
                        message_type=MessageType.TEXT.value, from_me=True, body=response,
                        sender_type=SenderType.BOT.value
                    )
                return
            else:
                print(f"[WEBHOOK] awaiting_confirmation ativo, mensagem não reconhecida como confirmação - continuando atendimento")
                conversation.awaiting_confirmation = False
                conversation.confirmation_sent_at = None
                db.commit()
        
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
        
        history_with_summary = build_context_with_summary(history, conversation, None)
        
        print(f"[WEBHOOK] Chamando Pipeline V2 (agentic RAG)...")
        response, should_create_ticket, context = await openai_agent.generate_response_v2(
            user_message=normalized_message,
            conversation_history=history_with_summary,
            sender_phone=phone,
            identified_assessor=assessor_data,
            db=db,
            conversation_id=str(conversation.id) if conversation else None,
            allow_tools=True,
        )
        print(f"[WEBHOOK] V2 Resposta gerada: {response[:100] if response else 'VAZIA'} | iterations={context.get('iterations')} elapsed={context.get('elapsed_ms')}ms")
        
        if context and context.get("intent") == "error":
            print(f"[WEBHOOK] Erro interno na IA - suprimindo resposta ao usuário. Erro: {context.get('error', 'desconhecido')}")
            if message_record:
                message_record.ai_response = response
                message_record.ai_intent = "error_suppressed"
                error_detail = context.get('error', '')
                if error_detail:
                    message_record.ai_error_detail = str(error_detail)[:1000]
                db.commit()
            return
        
        diagram_slugs_from_ai = []
        material_ids_from_ai = []
        
        action_tool_calls = context.get("action_tool_calls") if context else None
        if action_tool_calls:
            for tc in action_tool_calls:
                if tc["name"] == "send_document":
                    mid = str(tc["arguments"].get("material_id", ""))
                    if mid:
                        material_ids_from_ai.append(mid)
                        print(f"[WEBHOOK] V2 Action: send_document(material_id={mid})")
                elif tc["name"] == "send_payoff_diagram":
                    slug = tc["arguments"].get("structure_slug", "")
                    if slug:
                        diagram_slugs_from_ai.append(slug)
                        print(f"[WEBHOOK] V2 Action: send_payoff_diagram(slug={slug})")
        
        if response:
            clean_response, text_diagram_slugs = _extract_diagram_markers(response)
            if text_diagram_slugs:
                for slug in text_diagram_slugs:
                    if slug not in diagram_slugs_from_ai:
                        diagram_slugs_from_ai.append(slug)
                print(f"[WEBHOOK] Marcações de diagrama (texto fallback): {text_diagram_slugs}")
                response = clean_response
            
            clean_response2, text_material_ids = _extract_material_markers(response)
            if text_material_ids:
                for mid in text_material_ids:
                    if mid not in material_ids_from_ai:
                        material_ids_from_ai.append(mid)
                print(f"[WEBHOOK] Marcações de material (texto fallback): {text_material_ids}")
                response = clean_response2
        
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
                
                if assessor_first_name and broker_name:
                    response = f"{assessor_first_name}, registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif broker_name:
                    response = f"Registrado! O {broker_name} já tá sendo avisado e responde em breve."
                elif assessor_first_name:
                    response = f"{assessor_first_name}, registrado! O broker que te acompanha já tá sendo avisado e responde em breve."
                else:
                    response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
                
                if created_ticket_id:
                    response += f"\n\nChamado #{created_ticket_id} criado com sucesso!"
            except Exception as e:
                print(f"[WEBHOOK] Erro na escalação via OpenAI, usando fallback: {e}")
                import traceback
                traceback.print_exc()
                
                fresh_conv = db.query(Conversation).filter(Conversation.id == conversation.id).first()
                if fresh_conv:
                    ticket_count = db.query(ConversationTicket).filter(
                        ConversationTicket.conversation_id == fresh_conv.id
                    ).count()
                    
                    fallback_ticket = ConversationTicket(
                        conversation_id=fresh_conv.id,
                        ticket_number=ticket_count + 1,
                        status=TicketStatusV2.NEW.value,
                        escalation_level=EscalationLevel.T1_HUMAN.value,
                        escalation_category="other",
                        escalation_reason_detail=str(transfer_reason) if transfer_reason else "Transferência automática",
                        ticket_summary=normalized_message[:200] if normalized_message else "Solicitação de atendimento",
                        conversation_topic="Geral",
                        transfer_reason=transfer_reason,
                        transferred_at=datetime.utcnow()
                    )
                    db.add(fallback_ticket)
                    db.flush()
                    
                    fresh_conv.active_ticket_id = fallback_ticket.id
                    fresh_conv.ticket_status = TicketStatusV2.NEW.value
                    fresh_conv.escalation_level = EscalationLevel.T1_HUMAN.value
                    fresh_conv.status = ConversationStatus.HUMAN_TAKEOVER.value
                    fresh_conv.conversation_state = ConversationState.HUMAN_TAKEOVER.value
                    fresh_conv.transfer_reason = transfer_reason
                    fresh_conv.transferred_at = datetime.utcnow()
                    fresh_conv.escalation_category = "other"
                    fresh_conv.ticket_summary = normalized_message[:200] if normalized_message else "Solicitação de atendimento"
                    fresh_conv.conversation_topic = "Geral"
                    db.commit()
                    
                    created_ticket_id = fallback_ticket.id
                    print(f"[WEBHOOK] Fallback ticket #{fallback_ticket.id} criado com sucesso")
                    response = f"Registrado! O broker responsável já tá sendo avisado e responde em breve.\n\nChamado #{fallback_ticket.id} criado com sucesso!"
                else:
                    response = "Registrado! O broker responsável já tá sendo avisado e responde em breve."
        
        append_to_history(phone, "user", normalized_message)
        
        if message_record:
            if response:
                message_record.ai_response = response
            message_record.ai_intent = context.get("intent") if context else None
            if created_ticket_id:
                message_record.conversation_ticket_id = created_ticket_id
            db.commit()
        
        try:
            import json as _json
            tool_calls_for_log = context.get("tool_calls", []) if context else []
            tools_used = [
                {"name": tc.get("name"), "iteration": tc.get("iteration")}
                for tc in (tool_calls_for_log or [])
            ]
            search_result_count = sum(
                1 for tc in (tool_calls_for_log or [])
                if tc.get("name") in ("search_knowledge_base", "search_web")
                and tc.get("result_preview", "").strip()
                and "erro" not in tc.get("result_preview", "").lower()[:50]
            )
            retrieval_log = RetrievalLog(
                query=normalized_message,
                query_type="v2_agentic",
                result_count=search_result_count,
                threshold_applied="v2_auto",
                human_transfer=is_human_transfer,
                transfer_reason=transfer_reason,
                conversation_id=str(conversation.id) if conversation else None,
                response_time_ms=context.get("elapsed_ms") if context else None,
                chunks_retrieved=_json.dumps(tools_used, ensure_ascii=False) if tools_used else None,
            )
            db.add(retrieval_log)
            db.commit()
        except Exception as log_err:
            print(f"[WEBHOOK] Erro ao salvar RetrievalLog: {log_err}")
        
        if response:
            print(f"[WEBHOOK] Enviando resposta via Z-API para {phone}...")
            send_result = await zapi_client.send_text(phone, response)
            print(f"[WEBHOOK] Resultado envio Z-API: {send_result}")
        else:
            print(f"[WEBHOOK] Resposta vazia - não enviando mensagem ao WhatsApp")
            send_result = {"success": False, "reason": "empty_response"}
        
        if send_result.get("success"):
            response_sent_successfully = True
            if response:
                metadata = context if context else None
                append_to_history(phone, "assistant", response, metadata)
            save_message_zapi(
                db,
                message_id=send_result.get("message_id"),
                zaap_id=send_result.get("zaap_id"),
                phone=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=MessageType.TEXT.value,
                from_me=True,
                body=response,
                conversation_ticket_id=created_ticket_id,
                sender_type=SenderType.BOT.value
            )
            
            if conversation:
                conv_id = conversation.id
                fresh_conversation = db.query(Conversation).filter(Conversation.id == conv_id).first()
                if fresh_conversation and fresh_conversation.escalation_level == EscalationLevel.T0_BOT.value:
                    print(f"[WEBHOOK] Atualizando last_bot_response_at para conversa {conv_id}")
                    fresh_conversation.last_bot_response_at = datetime.utcnow()
                    db.commit()
                    print(f"[WEBHOOK] last_bot_response_at atualizado: {fresh_conversation.last_bot_response_at}")
        
        if diagram_slugs_from_ai:
            try:
                sent = await _send_diagrams_from_markers(phone, diagram_slugs_from_ai, db)
                if sent:
                    print(f"[WEBHOOK] Diagramas enviados: {sent}")
                failed_slugs = [s for s in diagram_slugs_from_ai if s not in sent]
                if failed_slugs:
                    print(f"[WEBHOOK] Diagramas falharam: {failed_slugs}")
                    await zapi_client.send_text(
                        phone,
                        "Não consegui enviar o diagrama agora. Quer que eu descreva o payoff por texto?",
                        delay_typing=1
                    )
            except Exception as diag_err:
                print(f"[WEBHOOK] Erro ao enviar diagramas: {diag_err}")
                try:
                    await zapi_client.send_text(
                        phone,
                        "Não consegui enviar o diagrama agora. Quer que eu descreva o payoff por texto?",
                        delay_typing=1
                    )
                except Exception:
                    pass
        
        if material_ids_from_ai:
            try:
                materials_result = await _send_materials_from_markers(phone, material_ids_from_ai, db)
                sent_materials = materials_result.get("sent", [])
                failed_list = materials_result.get("failed", [])
                if sent_materials:
                    print(f"[WEBHOOK] Materiais enviados: {sent_materials}")
                if failed_list:
                    print(f"[WEBHOOK] Falha ao enviar materiais: {failed_list}")
                    response_was_empty = not response or len(response.strip()) < 20
                    
                    if response_was_empty:
                        print(f"[MATERIAL_FALLBACK] Resposta textual vazia/curta e envio de material falhou. Gerando fallback...")
                        try:
                            fallback_prompt = (
                                f"O assessor pediu: \"{normalized_message}\". "
                                f"Eu tentei enviar o PDF mas não consegui. "
                                f"Responda ao pedido do assessor da melhor forma possível usando o conhecimento disponível. "
                                f"Se ele pediu o material/PDF, informe que o arquivo não está disponível no momento e ofereça resumir o conteúdo. "
                                f"Se ele pediu outra coisa (texto comercial, resumo, análise, pitch), atenda ao pedido normalmente."
                            )
                            fallback_response, _, _ = await openai_agent.generate_response_v2(
                                user_message=fallback_prompt,
                                conversation_history=history_with_summary[-6:] if history_with_summary else [],
                                sender_phone=phone,
                                identified_assessor=assessor_data,
                                db=db,
                                allow_tools=False,
                            )
                            if fallback_response and len(fallback_response.strip()) > 10:
                                print(f"[MATERIAL_FALLBACK] Enviando resposta fallback: {fallback_response[:100]}...")
                                await zapi_client.send_text(phone, fallback_response, delay_typing=2)
                                append_to_history(phone, "assistant", fallback_response)
                            else:
                                no_file_failures = [f for f in failed_list if f["reason"] == "no_file"]
                                other_failures = [f for f in failed_list if f["reason"] != "no_file"]
                                if no_file_failures:
                                    names = ", ".join(f.get("material_name", "documento") for f in no_file_failures)
                                    await zapi_client.send_text(phone, f"O arquivo PDF de {names} não está disponível no momento. Posso te ajudar de outra forma — é só pedir!", delay_typing=1)
                                elif other_failures:
                                    await zapi_client.send_text(phone, "Não consegui enviar o documento agora. Tenta pedir novamente em instantes.", delay_typing=1)
                        except Exception as fallback_err:
                            print(f"[MATERIAL_FALLBACK] Erro no fallback: {fallback_err}")
                            await zapi_client.send_text(phone, "Não consegui enviar o documento agora. Tenta pedir novamente em instantes.", delay_typing=1)
                    else:
                        no_file_failures = [f for f in failed_list if f["reason"] == "no_file"]
                        other_failures = [f for f in failed_list if f["reason"] != "no_file"]
                        if no_file_failures:
                            names = ", ".join(f.get("material_name", "documento") for f in no_file_failures)
                            await zapi_client.send_text(
                                phone,
                                f"O arquivo PDF de {names} não está disponível no momento. O material precisa ser re-carregado no sistema pelo administrador.",
                                delay_typing=1
                            )
                        if other_failures:
                            await zapi_client.send_text(phone, "Não consegui enviar o documento agora. Tenta pedir novamente em instantes.", delay_typing=1)
            except Exception as mat_err:
                print(f"[WEBHOOK] Erro ao enviar materiais: {mat_err}")
                try:
                    await zapi_client.send_text(phone, "Tive um problema ao enviar o documento. Tenta novamente?", delay_typing=1)
                except:
                    pass
        
        visual_blocks = context.get("visual_blocks") if context else None
        print(f"[WEBHOOK] Visual blocks from context: {len(visual_blocks) if visual_blocks else 0}")
        if visual_blocks and response_sent_successfully:
            try:
                from services.visual_decision import select_best_visual_block, should_send_visual
                from services.visual_extractor import get_visual_base64
                for vb in visual_blocks:
                    trigger_match = should_send_visual(vb, normalized_message)
                    print(f"[WEBHOOK] Visual candidate block_id={vb.get('block_id')}, "
                          f"type={vb.get('block_type')}, trigger_match={trigger_match}")
                best_visual = select_best_visual_block(visual_blocks, normalized_message)
                if best_visual and best_visual.get("block_id"):
                    print(f"[WEBHOOK] Selected visual block_id={best_visual['block_id']}, extracting image...")
                    visual_result = get_visual_base64(best_visual["block_id"], db)
                    if visual_result:
                        import asyncio as _asyncio
                        await _asyncio.sleep(0.3)
                        caption_parts = []
                        if best_visual.get("visual_description"):
                            caption_parts.append(best_visual["visual_description"][:200])
                        if best_visual.get("material_name"):
                            caption_parts.append(f"Fonte: {best_visual['material_name']}")
                        if best_visual.get("source_page"):
                            caption_parts.append(f"Página {best_visual['source_page']}")
                        caption = " | ".join(caption_parts) if caption_parts else "Referência visual"

                        visual_send = await zapi_client.send_image(
                            phone,
                            visual_result["base64"],
                            caption
                        )
                        if visual_send.get("success"):
                            print(f"[WEBHOOK] Visual reference enviada: block_id={best_visual['block_id']}, "
                                  f"fallback={visual_result['used_fallback']}, cache={visual_result['from_cache']}, "
                                  f"size={visual_result['size_bytes']}B")
                        else:
                            print(f"[WEBHOOK] Falha ao enviar visual reference: {visual_send}")
                    else:
                        print(f"[WEBHOOK] Visual extraction returned None for block_id={best_visual['block_id']}")
                else:
                    print(f"[WEBHOOK] No visual block selected (triggers not matched or no eligible blocks)")
            except Exception as vis_err:
                print(f"[WEBHOOK] Erro ao enviar referência visual: {vis_err}")

        if not response_sent_successfully and not material_ids_from_ai and not diagram_slugs_from_ai:
            response_was_empty = not response or len(response.strip()) < 20
            if response_was_empty:
                print(f"[WEBHOOK] Resposta V2 vazia sem ações — gerando fallback sem tools...")
                try:
                    fallback_response, _, _ = await openai_agent.generate_response_v2(
                        user_message=normalized_message,
                        conversation_history=history_with_summary[-6:] if history_with_summary else [],
                        sender_phone=phone,
                        identified_assessor=assessor_data,
                        db=db,
                        allow_tools=False,
                    )
                    if fallback_response and len(fallback_response.strip()) > 10:
                        print(f"[WEBHOOK] Fallback V2 enviando: {fallback_response[:100]}...")
                        send_result = await zapi_client.send_text(phone, fallback_response, delay_typing=2)
                        if send_result.get("success"):
                            response_sent_successfully = True
                            append_to_history(phone, "assistant", fallback_response)
                    else:
                        print(f"[WEBHOOK] Fallback V2 também gerou resposta vazia")
                except Exception as fallback_err:
                    print(f"[WEBHOOK] Erro no fallback V2: {fallback_err}")
        
        if response_sent_successfully or material_ids_from_ai or diagram_slugs_from_ai:
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
            
            try:
                from services.conversation_memory import maybe_incremental_summary
                await maybe_incremental_summary(phone, db, conversation)
            except Exception as summ_err:
                print(f"[WEBHOOK] Erro no resumo incremental: {summ_err}")
        
    except Exception as e:
        print(f"[WEBHOOK] Erro ao processar mensagem: {e}")
        import traceback
        traceback.print_exc()


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
    request: Request,
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
    from core.config import get_settings as _get_settings
    _settings = _get_settings()
    incoming_token = request.headers.get("z-api-token", "") or request.headers.get("client-token", "")
    expected_token = os.getenv("ZAPI_TOKEN", "") or _settings.ZAPI_TOKEN
    if not expected_token or incoming_token != expected_token:
        expected_ct = os.getenv("ZAPI_CLIENT_TOKEN", "") or _settings.ZAPI_CLIENT_TOKEN
        if not expected_ct or incoming_token != expected_ct:
            print(f"[WEBHOOK] Token mismatch - incoming (first 5): '{incoming_token[:5] if incoming_token else 'EMPTY'}'")
            raise HTTPException(status_code=401, detail="Invalid or missing webhook token")

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
    
    # IDEMPOTÊNCIA: Verificar se a mensagem já foi processada ANTES de qualquer processamento
    if message_id:
        existing_inbound = db.query(WhatsAppMessage).filter(
            WhatsAppMessage.message_id == message_id,
            WhatsAppMessage.direction == MessageDirection.INBOUND.value
        ).first()
        
        if existing_inbound:
            print(f"[WEBHOOK] Mensagem inbound já processada (id={message_id}), ignorando duplicata")
            return {"status": "ignored", "reason": "duplicate message - already processed"}
    
    conversation = None
    phone_is_lid_precheck = _is_lid_not_phone(phone) if phone else False
    if sender_lid:
        conversation = db.query(Conversation).filter(Conversation.lid == sender_lid).first()
    if not conversation and phone and not phone_is_lid_precheck:
        conversation = db.query(Conversation).filter(Conversation.phone == phone).first()
    if not conversation and phone:
        clean_val = phone.replace("@lid", "")
        conversation = db.query(Conversation).filter(
            Conversation.chat_lid == clean_val + "@lid"
        ).first()
        if not conversation:
            conversation = db.query(Conversation).filter(
                Conversation.chat_lid == phone
            ).first()
    if not conversation and phone_is_lid_precheck:
        normalized_lid = phone.replace("@lid", "")
        conversation = db.query(Conversation).filter(Conversation.lid == normalized_lid).first()
        if not conversation:
            conversation = db.query(Conversation).filter(Conversation.lid == phone).first()
    
    is_human_active = conversation and conversation.ticket_status == TicketStatusV2.OPEN.value
    
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
    
    if is_human_active:
        print(f"[WEBHOOK] Ticket OPEN (atendimento humano ativo), não respondendo automaticamente: {phone}")
        return {
            "status": "received",
            "message_type": message_type,
            "message_id": message_record.id if message_record else None,
            "auto_response": False,
            "reason": "ticket_open_human_active"
        }
    
    if conversation and conversation.ticket_status == TicketStatusV2.SOLVED.value:
        incoming_text = body or ""
        from services.conversation_flow import is_positive_confirmation
        if incoming_text and (is_positive_confirmation(incoming_text) or _is_farewell_or_emoji(incoming_text)):
            print(f"[WEBHOOK] Ticket SOLVED + farewell/emoji/gratitude — ignorando (sem loop): {phone}")
            return {
                "status": "received",
                "message_type": message_type,
                "message_id": message_record.id if message_record else None,
                "auto_response": False,
                "reason": "solved_farewell_ignored"
            }
        conversation.ticket_status = None
        db.commit()
        print(f"[WEBHOOK] Ticket reaberto (era solved, nova mensagem recebida): {phone}")
        try:
            sse_manager = get_sse_manager()
            asyncio.create_task(sse_manager.notify_conversation_update(conversation.id))
        except Exception:
            pass
    
    if message_type == MessageType.TEXT.value:
        if body:
            schedule_task(enqueue_message(
                phone=phone,
                body=body,
                message_record_id=message_record.id if message_record else None,
                conversation_id=conversation.id if conversation else None,
                db_factory=SessionLocal,
                process_fn=process_text_message
            ))
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
