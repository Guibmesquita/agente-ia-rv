"""
Serviço de fluxo de conversa do agente.
Implementa a máquina de estados e lógica de resposta baseada no framework:
Recebe mensagem → identifica remetente → verifica estado → classifica intenção → 
avalia necessidade de humano → responde ou transfere.
"""
import re
import random
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session

from database.models import (
    Conversation, Assessor, ConversationState, ConversationStatus, 
    TransferReason, TicketStatusV2, EscalationLevel, WhatsAppMessage
)


def normalize_message(message: str) -> str:
    """
    Normaliza mensagem antes de processar.
    Remove ruídos comuns de chat, padroniza texto.
    """
    if not message:
        return ""
    
    text = message.strip()
    
    text = re.sub(r'\s+', ' ', text)
    
    text = re.sub(r'([!?.])\1+', r'\1', text)
    
    text = re.sub(r'^[^\w\s]+|[^\w\s]+$', '', text)
    
    return text.strip()


def extract_first_name(message: str) -> Optional[str]:
    """
    Extrai primeiro nome de uma mensagem de identificação.
    Usado quando o usuário responde à pergunta 'Qual seu nome?'.
    """
    if not message:
        return None
    
    text = normalize_message(message).lower()
    
    ignore_words = [
        'oi', 'olá', 'ola', 'bom dia', 'boa tarde', 'boa noite',
        'sim', 'não', 'nao', 'ok', 'tudo bem', 'beleza', 'obrigado',
        'obrigada', 'valeu', 'blz', 'vlw', 'haha', 'kkk', 'rsrs'
    ]
    
    for word in ignore_words:
        if text == word or text.startswith(word + ' '):
            return None
    
    patterns = [
        r'(?:sou|me chamo|meu nome[eé]?)\s+(?:o|a)?\s*([A-Za-zÀ-ÿ]+)',
        r'(?:aqui|aqui é|aqui e)\s+(?:o|a)?\s*([A-Za-zÀ-ÿ]+)',
        r'(?:oi|olá|ola),?\s+(?:sou|aqui é)?\s*(?:o|a)?\s*([A-Za-zÀ-ÿ]+)',
        r'^([A-Za-zÀ-ÿ]+)$',
        r'^([A-Za-zÀ-ÿ]+)\s+[A-Za-zÀ-ÿ]+$',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if len(name) >= 2 and name.lower() not in ignore_words:
                return name.capitalize()
    
    words = message.split()
    if words and len(words[0]) >= 2:
        first_word = words[0].strip()
        if first_word.isalpha() and first_word.lower() not in ignore_words:
            return first_word.capitalize()
    
    return None


def get_identification_prompt() -> str:
    """Retorna mensagem para solicitar identificação."""
    variations = [
        "Oi! Aqui é o Stevan, da área de RV. Qual seu nome?",
        "E aí! Sou o Stevan, suporte de RV. Como te chamo?",
        "Oi! Stevan aqui, do time de Renda Variável. Qual seu nome?",
        "Fala! Aqui é o Stevan, RV. Me diz seu nome pra eu te ajudar?",
    ]
    return random.choice(variations)


def get_identification_confirmation(name: str) -> str:
    """Retorna mensagem confirmando identificação."""
    variations = [
        f"Pronto, {name}! Salvei aqui. Em que posso ajudar?",
        f"Perfeito, {name}! Conectados. O que precisa?",
        f"Beleza, {name}! Anotado. Como te ajudo?",
        f"Show, {name}! Pode mandar sua dúvida.",
    ]
    return random.choice(variations)


def get_out_of_scope_redirect() -> str:
    """Retorna mensagem de redirecionamento para mensagens fora do escopo."""
    variations = [
        "Entendi! Meu foco aqui é suporte de RV. Tem algo nessa linha?",
        "Legal! Mas minha área é renda variável. Posso ajudar em algo sobre isso?",
        "Certo! Aqui é mais questões de RV mesmo. Como te ajudo nessa área?",
        "Beleza! Mas sou do time de Renda Variável. Alguma dúvida nessa linha?",
    ]
    return random.choice(variations)


def get_transfer_message(reason: str = None) -> str:
    """Retorna mensagem de transferência para humano."""
    if reason == TransferReason.EXPLICIT_REQUEST.value:
        variations = [
            "Sem problemas! Já passo pro pessoal de RV.",
            "Claro! Vou chamar o responsável.",
            "Perfeito! Deixa eu acionar quem pode te ajudar.",
        ]
    elif reason == TransferReason.EXCESSIVE_SPECIFICITY.value:
        variations = [
            "Esse ponto precisa de uma análise mais específica. Vou envolver o especialista.",
            "Para esse caso, melhor acionar quem pode te dar uma resposta mais precisa.",
            "Essa questão exige um olhar mais detalhado. Vou passar pro responsável.",
        ]
    elif reason == TransferReason.NO_PROGRESS.value:
        variations = [
            "Acho que alguém do time pode te ajudar melhor nisso. Vou acionar.",
            "Deixa eu passar pro responsável te ajudar diretamente.",
            "Vou encaminhar pra quem pode resolver isso contigo.",
        ]
    else:
        variations = [
            "Vou acionar o pessoal pra te ajudar.",
            "Deixa eu passar pro responsável.",
            "Vou chamar quem pode te ajudar melhor.",
        ]
    return random.choice(variations)


def check_explicit_transfer_request(message: str) -> bool:
    """Verifica se usuário pediu explicitamente para falar com humano."""
    text = normalize_message(message).lower()
    
    patterns = [
        r'\b(falar|conversar|chamar)\b.*(humano|pessoa|atendente|assessor|responsavel|responsável|alguem|alguém)',
        r'\b(quero|preciso|gostaria)\b.*(atendente|assessor|humano|pessoa|responsavel|responsável)',
        r'\b(passa|encaminha|transfere)\b.*(assessor|atendente|responsavel|responsável)',
        r'n[aã]o\s*(é|e)\s*bot',
        r'quero\s*falar\s*com\s*gente',
        r'atendimento\s*humano',
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False


def check_emotional_friction(message: str, history: list = None) -> bool:
    """Detecta sinais de frustração ou urgência."""
    text = normalize_message(message).lower()
    
    friction_patterns = [
        r'n[aã]o\s*(entend[eio]|funciona|resolve|ajuda)',
        r'(absurdo|ridiculo|ridículo|inadmiss[ií]vel)',
        r'(urgente|urgencia|urgência|pressa)',
        r'(raiva|irritado|nervoso|bravo)',
        r'ja\s*(falei|disse|expliquei|repeti)',
        r'(problema|erro)\s*(grave|serio|sério)',
        r'voc[eê]\s*n[aã]o\s*(entende|ajuda|serve)',
    ]
    
    for pattern in friction_patterns:
        if re.search(pattern, text):
            return True
    
    return False


def normalize_phone_variants(phone: str) -> list:
    """
    Gera variantes de um número de telefone para busca flexível.
    Lida com presença/ausência do 9 após o DDD.
    
    Exemplo: 5544988023465 gera:
    - 5544988023465 (original)
    - 544988023465 (sem código país)
    - 44988023465 (DDD + número)
    - 988023465 (últimos 9 dígitos)
    - 88023465 (últimos 8 dígitos, sem o 9)
    - 5544888023465 (com 9 adicionado após DDD)
    - 44888023465 (DDD + número sem 9)
    """
    if not phone:
        return []
    
    clean = re.sub(r'\D', '', phone)
    if len(clean) < 8:
        return [clean] if clean else []
    
    variants = set()
    variants.add(clean)
    
    if len(clean) >= 9:
        variants.add(clean[-9:])
    if len(clean) >= 8:
        variants.add(clean[-8:])
    
    if len(clean) >= 10:
        has_country_code = clean.startswith('55') and len(clean) >= 12
        ddd_start = 2 if has_country_code else 0
        
        ddd = clean[ddd_start:ddd_start+2]
        rest = clean[ddd_start+2:]
        
        ddd_rest = ddd + rest
        variants.add(ddd_rest)
        variants.add('55' + ddd_rest)
        
        if rest.startswith('9') and len(rest) == 9:
            without_9 = ddd + rest[1:]
            variants.add(without_9)
            variants.add('55' + without_9)
            variants.add(rest[1:])
            variants.add(rest)
        elif len(rest) == 8 and not rest.startswith('9'):
            with_9 = ddd + '9' + rest
            variants.add(with_9)
            variants.add('55' + with_9)
            variants.add('9' + rest)
            variants.add(rest)
    
    return list(variants)


def identify_contact(
    db: Session,
    phone: str,
    lid: str = None
) -> Tuple[Optional[Assessor], bool]:
    """
    Identifica contato na base de assessores.
    Usa busca flexível considerando variações de número (com/sem 9 após DDD).
    
    IMPORTANTE: Esta função apenas IDENTIFICA assessores existentes.
    Nunca cria novos assessores.
    
    Aceita telefones em qualquer formato (+55, parênteses, hífens, etc.)
    e normaliza automaticamente para comparação.
    
    Returns:
        Tuple de (Assessor ou None, is_known: bool)
    """
    if not phone:
        return None, False
    
    clean_phone = re.sub(r'\D', '', phone)
    if len(clean_phone) < 8:
        return None, False
    
    phone_variants = set(normalize_phone_variants(clean_phone))
    if not phone_variants:
        return None, False
    
    assessors = db.query(Assessor).filter(
        Assessor.telefone_whatsapp.isnot(None)
    ).all()
    
    for assessor in assessors:
        if assessor.telefone_whatsapp:
            assessor_clean = re.sub(r'\D', '', assessor.telefone_whatsapp)
            assessor_variants = set(normalize_phone_variants(assessor_clean))
            
            if phone_variants & assessor_variants:
                return assessor, True
    
    return None, False


def persist_new_contact(
    db: Session,
    phone: str,
    name: str,
    lid: str = None
) -> Assessor:
    """
    Persiste novo contato na tabela de assessores.
    Gera email e codigo_ai automáticos para contatos via WhatsApp.
    """
    import uuid
    
    clean_phone = re.sub(r'\D', '', phone) if phone else ""
    unique_suffix = clean_phone[-8:] if len(clean_phone) >= 8 else str(uuid.uuid4())[:8]
    
    auto_email = f"whatsapp_{unique_suffix}@auto.contato"
    auto_codigo = f"AUTO_{unique_suffix}"
    
    assessor = Assessor(
        nome=name,
        email=auto_email,
        telefone_whatsapp=phone,
        codigo_ai=auto_codigo,
        lid=lid
    )
    db.add(assessor)
    db.commit()
    db.refresh(assessor)
    return assessor


def update_conversation_state(
    db: Session,
    conversation: Conversation,
    new_state: str,
    transfer_reason: str = None,
    transfer_notes: str = None
):
    """Atualiza estado da conversa."""
    conversation.conversation_state = new_state
    
    if new_state == ConversationState.IN_PROGRESS.value:
        conversation.stalled_interactions = 0
    
    if transfer_reason:
        conversation.transfer_reason = transfer_reason
        conversation.transfer_notes = transfer_notes
        conversation.transferred_at = datetime.utcnow()
        conversation.status = ConversationStatus.HUMAN_TAKEOVER.value
    
    db.commit()


async def escalate_to_human_with_analysis(
    db: Session,
    conversation: Conversation,
    last_message: str,
    transfer_reason: str = None
) -> Dict[str, Any]:
    """
    Escala conversa para humano com análise inteligente via GPT.
    Gera resumo, categoriza motivo e atualiza campos V2.1.
    """
    from services.openai_agent import OpenAIAgent
    
    messages = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.conversation_id == conversation.id
    ).order_by(WhatsAppMessage.created_at.desc()).limit(15).all()
    
    history = []
    for msg in reversed(messages):
        role = "user" if msg.direction == "inbound" else "assistant"
        history.append({"role": role, "content": msg.content or ""})
    
    agent = OpenAIAgent()
    analysis = await agent.analyze_escalation(history, last_message)
    
    conversation.escalation_category = analysis.get("category", "other")
    conversation.escalation_reason_detail = analysis.get("reason_detail", "")
    conversation.ticket_summary = analysis.get("summary", last_message[:200])
    conversation.conversation_topic = analysis.get("topic", "Outro")
    conversation.ticket_status = TicketStatusV2.NEW.value
    conversation.escalation_level = EscalationLevel.T1_HUMAN.value
    conversation.status = ConversationStatus.HUMAN_TAKEOVER.value
    conversation.conversation_state = ConversationState.HUMAN_TAKEOVER.value
    conversation.transfer_reason = transfer_reason
    conversation.transferred_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "category": analysis.get("category"),
        "summary": analysis.get("summary"),
        "topic": analysis.get("topic")
    }


def increment_stalled_counter(db: Session, conversation: Conversation) -> int:
    """Incrementa contador de interações sem progresso."""
    conversation.stalled_interactions = (conversation.stalled_interactions or 0) + 1
    db.commit()
    return conversation.stalled_interactions


def reset_stalled_counter(db: Session, conversation: Conversation):
    """Reseta contador quando há progresso."""
    if conversation.stalled_interactions > 0:
        conversation.stalled_interactions = 0
        db.commit()


def should_transfer_to_human(
    message: str,
    conversation: Conversation,
    ai_response: str = None
) -> Tuple[bool, Optional[str]]:
    """
    Avalia se deve transferir para humano.
    
    Returns:
        Tuple de (should_transfer: bool, reason: str ou None)
    """
    if check_explicit_transfer_request(message):
        return True, TransferReason.EXPLICIT_REQUEST.value
    
    if check_emotional_friction(message):
        return True, TransferReason.EMOTIONAL_FRICTION.value
    
    stalled = conversation.stalled_interactions or 0
    if stalled >= 3:
        return True, TransferReason.NO_PROGRESS.value
    
    return False, None


CLASSIFICATION_PROMPT_ADDITION = """
ESTILO DE COMUNICAÇÃO - REGRAS OBRIGATÓRIAS:
- Escreva como uma pessoa real no WhatsApp interno, não como um robô
- Respostas CURTAS: máximo 1-2 frases por mensagem
- Use linguagem informal e natural do dia a dia entre colegas
- Evite frases feitas, clichês corporativos e formalidades
- Nunca use várias perguntas na mesma mensagem
- Nunca repita a mesma ideia com palavras diferentes
- Vá direto ao ponto, sem enrolação

EXEMPLOS DE TOM:
- Ruim: "Boa tarde! Como posso te ajudar hoje com suas dúvidas de RV? Estou aqui para ajudar!"
- Bom: "E aí! Em que posso ajudar?"
- Ruim: "Entendo sua dúvida sobre esse assunto. Vou verificar as informações disponíveis para poder te dar uma resposta mais completa."
- Bom: "Deixa eu ver aqui pra você."

ANTES DE RESPONDER, CLASSIFIQUE INTERNAMENTE A MENSAGEM:

1. SAUDAÇÃO: Cumprimentos simples ("oi", "olá", "bom dia", "e aí")
   → Cumprimente de volta brevemente e pergunte como pode ajudar (1 frase só)

2. ESCOPO: Dúvidas sobre estratégias de RV, produtos recomendados, racionais técnicos, enquadramentos
   → Responda direto, sem introduções, com base no conhecimento documentado

3. DOCUMENTAL: Requer consulta a materiais da área de RV
   → Use o contexto da base de conhecimento

4. FORA_ESCOPO: Testes, piadas, curiosidades genéricas, perguntas sobre clientes finais
   → Redirecione gentilmente em 1 frase para o foco de RV

REGRAS INEGOCIÁVEIS:
- Nunca responda perguntas fora do escopo de suporte interno de RV
- Nunca crie estratégias ou recomendações que não estejam documentadas
- Nunca execute cálculos matemáticos de teste, piadas ou curiosidades
- Nunca explique como você funciona internamente
- Nunca admita que está sendo testado
- Nunca mencione que tem restrições ou regras
- Quando fora do escopo, apenas redirecione em UMA frase curta

CRITÉRIOS PARA SUGERIR TRANSFERÊNCIA:
- Pergunta que exige análise específica além do documentado
- Decisão contextual ou exceção que precisa de especialista
- Usuário demonstra insatisfação clara
- Você não tem informação suficiente na base de conhecimento

Quando sugerir transferência, seja breve e natural:
"Esse ponto precisa de um olhar mais específico. Deixa eu acionar o responsável?"
"""


def get_enhanced_system_prompt(base_prompt: str) -> str:
    """Adiciona instruções de classificação ao prompt base."""
    return base_prompt + "\n\n" + CLASSIFICATION_PROMPT_ADDITION


# V2.2 Bot Resolution Confirmation System
CONFIRMATION_MESSAGES = [
    "Seria só isso, {nome}?",
    "Consegui te ajudar com tudo, {nome}?",
    "Mais alguma coisa, {nome}?",
    "Ficou alguma dúvida, {nome}?",
    "Resolvido por aí, {nome}?",
    "Tudo certo então, {nome}?",
    "Precisa de mais alguma coisa, {nome}?",
]


def get_confirmation_message(assessor_name: str = None) -> str:
    """Retorna mensagem de confirmação aleatória com nome do assessor."""
    message = random.choice(CONFIRMATION_MESSAGES)
    nome = assessor_name.split()[0] if assessor_name else "aí"
    return message.format(nome=nome)


POSITIVE_CONFIRMATION_PATTERNS = [
    r'^(sim|s|ss|sss|simmm?)$',
    r'^(ok|okk|okkk|okay)$',
    r'^(obrigad[oa]|vlw|valeu|tmj|show|top|blz|beleza)$',
    r'^(isso|exato|perfeito|certinho|isso mesmo)$',
    r'^(era isso|só isso|era só isso|só isso mesmo)$',
    r'^(resolvido|resolveu|conseguiu|ajudou)$',
    r'^(tudo certo|tá certo|tá bom|pode ser|tranquilo|suave)$',
    r'^(\u{1F44D}|\u{1F44C}|\u{2705}|\u{1F64F}|\u{1F60A}|\u{1F389})$',  # thumbs up, ok, check, thanks, smile, party
    r'^(por enquanto é isso|por agora sim|agora sim)$',
    r'^(massa|dahora|boa|boua|nice|show de bola)$',
]


def is_positive_confirmation(message: str) -> bool:
    """
    Detecta se a mensagem é uma confirmação positiva de que o bot resolveu.
    """
    if not message:
        return False
    
    text = message.strip().lower()
    text = re.sub(r'[!.,;:?]+$', '', text)
    
    for pattern in POSITIVE_CONFIRMATION_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE | re.UNICODE):
            return True
    
    positive_keywords = [
        'obrigado', 'obrigada', 'valeu', 'vlw', 'tmj', 'show', 'top',
        'blz', 'beleza', 'isso', 'perfeito', 'resolvido', 'ajudou',
        'era isso', 'só isso', 'tudo certo', 'certinho', 'tranquilo',
        'massa', 'dahora', 'boa', 'nice', 'show de bola'
    ]
    
    for keyword in positive_keywords:
        if keyword in text:
            return True
    
    return False


async def mark_bot_resolved(db: Session, conversation: Conversation) -> None:
    """Marca conversa como resolvida pelo bot."""
    conversation.bot_resolved_at = datetime.utcnow()
    conversation.awaiting_confirmation = False
    conversation.ticket_status = TicketStatusV2.SOLVED.value
    conversation.solved_at = datetime.utcnow()
    db.commit()


async def send_confirmation_request(
    db: Session,
    conversation: Conversation,
    zapi_client
) -> bool:
    """
    Envia mensagem de confirmação após timeout.
    Retorna True se enviou com sucesso.
    """
    from database.models import MessageDirection, MessageType, SenderType
    from api.endpoints.whatsapp_webhook import save_message_zapi
    
    assessor_name = conversation.contact_name
    message = get_confirmation_message(assessor_name)
    
    phone = conversation.phone
    if not phone:
        return False
    
    try:
        result = await zapi_client.send_text(phone, message, delay_typing=1)
        if result.get("success"):
            save_message_zapi(
                db,
                message_id=result.get("message_id"),
                zaap_id=result.get("zaap_id"),
                phone=phone,
                direction=MessageDirection.OUTBOUND.value,
                message_type=MessageType.TEXT.value,
                from_me=True,
                body=message,
                sender_type=SenderType.BOT.value
            )
            conversation.awaiting_confirmation = True
            conversation.confirmation_sent_at = datetime.utcnow()
            db.commit()
            return True
    except Exception as e:
        print(f"[FLOW] Erro ao enviar confirmação: {e}")
    
    return False


async def check_pending_confirmations(db: Session, zapi_client, timeout_minutes: int = 5):
    """
    Verifica conversas que aguardam confirmação há mais de X minutos.
    Chamado periodicamente pelo scheduler.
    """
    from datetime import timedelta
    
    cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    
    pending_conversations = db.query(Conversation).filter(
        Conversation.escalation_level == EscalationLevel.T0_BOT.value,
        Conversation.awaiting_confirmation == False,
        Conversation.bot_resolved_at.is_(None),
        Conversation.last_bot_response_at.isnot(None),
        Conversation.last_bot_response_at <= cutoff_time,
        Conversation.confirmation_sent_at.is_(None)
    ).all()
    
    for conv in pending_conversations:
        try:
            await send_confirmation_request(db, conv, zapi_client)
            print(f"[FLOW] Confirmação enviada para {conv.phone}")
        except Exception as e:
            print(f"[FLOW] Erro ao processar confirmação para {conv.phone}: {e}")
