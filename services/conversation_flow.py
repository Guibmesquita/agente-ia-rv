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
    TicketStatusV2, EscalationLevel, WhatsAppMessage
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


def conversation_phone_keys(phone: str) -> list:
    """
    Gera variantes seguras de um telefone para busca de conversas, preservando sempre o DDD.
    Ao contrário de normalize_phone_variants (usada para assessores), esta função
    NUNCA gera sufixos curtos (8/9 dígitos) que poderiam colidir entre diferentes DDDs.

    Variantes geradas (todas preservam o DDD):
    - 55DDXXXXXXXXX  (13 dígitos — com código do país e dígito 9)
    - 55DDXXXXXXXX   (12 dígitos — com código do país, sem dígito 9)
    - DDXXXXXXXXX    (11 dígitos — sem código do país, com dígito 9)
    - DDXXXXXXXX     (10 dígitos — sem código do país, sem dígito 9)
    """
    if not phone:
        return []

    clean = re.sub(r'\D', '', phone)
    if len(clean) < 10:
        return [clean] if clean else []

    variants = set()

    has_country_code = clean.startswith('55') and len(clean) >= 12
    if has_country_code:
        ddd = clean[2:4]
        rest = clean[4:]
    else:
        ddd = clean[0:2]
        rest = clean[2:]

    if len(rest) == 9 and rest.startswith('9'):
        # Ex: rest = '999021089' → número já tem o dígito 9 de celular; gerar com e sem.
        rest_without_9 = rest[1:]
        variants.add('55' + ddd + rest)
        variants.add('55' + ddd + rest_without_9)
        variants.add(ddd + rest)
        variants.add(ddd + rest_without_9)
    elif len(rest) == 8 and not rest.startswith('9'):
        # Ex: rest = '90210890' → número de 8 dígitos sem o dígito 9; gerar com 9 prefixado.
        rest_with_9 = '9' + rest
        variants.add('55' + ddd + rest_with_9)
        variants.add('55' + ddd + rest)
        variants.add(ddd + rest_with_9)
        variants.add(ddd + rest)
    elif len(rest) == 8 and rest.startswith('9'):
        # Task #318 — Bug: ex. entrada '554499021089' (12 dígitos, código 55 + DDD 44 +
        # local '99021089'). O else anterior só gerava '554499021089' e '4499021089',
        # faltando '44999021089' (11 dígitos) e '5544999021089' (13 dígitos).
        # Esses são os mesmos contatos que chegam como '44999021089' no Z-API em outros
        # momentos, causando criação de conversa duplicada.
        # Solução: inserir '9' entre DDD e rest para cobrir o formato de 9 dígitos.
        rest_with_extra_9 = '9' + rest  # '9' + '99021089' = '999021089' (9 dígitos)
        variants.add('55' + ddd + rest)           # '554499021089' (12 dígitos — original)
        variants.add(ddd + rest)                  # '4499021089'   (10 dígitos)
        variants.add('55' + ddd + rest_with_extra_9)  # '5544999021089' (13 dígitos)
        variants.add(ddd + rest_with_extra_9)         # '44999021089'   (11 dígitos) ← a chave
    else:
        variants.add('55' + ddd + rest)
        variants.add(ddd + rest)

    return list(variants)


def canonicalize_phone(phone: str) -> str:
    """
    Converte um número de telefone para o formato canônico brasileiro.
    Formato canônico: 55 + DDD(2 dígitos) + 9 + número(8 dígitos) = 13 dígitos.
    Quando o número não tem o dígito 9 após o DDD, ele é adicionado.
    Se não for possível determinar o formato completo, retorna apenas os dígitos limpos.
    """
    if not phone:
        return phone or ""

    clean = re.sub(r'\D', '', phone)
    if len(clean) < 8:
        return clean

    has_country_code = clean.startswith('55') and len(clean) >= 12
    if has_country_code:
        ddd = clean[2:4]
        rest = clean[4:]
    elif len(clean) >= 10:
        ddd = clean[0:2]
        rest = clean[2:]
    else:
        return '55' + clean if not clean.startswith('55') else clean

    if len(rest) == 8 and not rest.startswith('9'):
        # '12345678' → '912345678'
        rest = '9' + rest
    elif len(rest) == 8 and rest.startswith('9'):
        # Task #318 — '99021089' (8 dígitos, começa com 9) → '999021089' (9 dígitos).
        # Sem este branch, números como '554499021089' ficavam canônicos como
        # '5544 99021089' (12 dígitos) em vez de '55 44 999021089' (13 dígitos),
        # divergindo do padrão de 13 dígitos esperado.
        rest = '9' + rest

    return '55' + ddd + rest


def merge_duplicate_conversations(db: Session) -> int:
    """
    Task #318 — Funde conversas duplicadas causadas por variações de formato de telefone.

    Lógica:
      1. Carrega todas as conversas com phone preenchido.
      2. Para cada conversa, gera variantes via conversation_phone_keys.
      3. Detecta pares (A, B) onde phone_B é variante de phone_A e id_A < id_B
         (mantém A como principal — o mais antigo).
      4. Move mensagens de B para A (WhatsAppMessage.conversation_id = A.id).
      5. Atualiza A: last_message_at e last_message_preview do B se B for mais recente;
         preserva channel_id de A (não sobrescreve lógica de canal).
      6. Remove B.

    Retorna: número de pares fundidos.
    Idempotente: chamar múltiplas vezes não faz efeito caso não haja duplicatas.
    """
    from database.models import Conversation, WhatsAppMessage

    try:
        conversations = (
            db.query(Conversation)
            .filter(Conversation.phone.isnot(None), Conversation.phone != "")
            .order_by(Conversation.id)
            .all()
        )
    except Exception as exc:
        print(f"[MERGE-DUP] Erro ao carregar conversas: {exc}")
        return 0

    # Mapa canonical_phone → id da conversa mais antiga com aquele número.
    # Usa canonicalize_phone() como chave de agrupamento — é determinístico e cobre todos
    # os formatos (12/11/10 dígitos, com/sem 55, com/sem dígito 9 extra) que conversation_phone_keys
    # gera como variantes. Isso é mais robusto do que min(variants, key=len), que poderia colidir
    # para sequências numéricas atípicas onde a variante mais curta não é única por grupo.
    canonical_map: dict = {}  # canonical_key → conversation_id (o principal)
    duplicate_pairs: list = []  # list of (keeper_id, dup_id)

    for conv in conversations:
        key = canonicalize_phone(conv.phone) or conv.phone

        if key not in canonical_map:
            canonical_map[key] = conv.id
        else:
            keeper_id = canonical_map[key]
            if keeper_id != conv.id:
                duplicate_pairs.append((keeper_id, conv.id))

    if not duplicate_pairs:
        print("[MERGE-DUP] Nenhuma conversa duplicada encontrada.")
        return 0

    print(f"[MERGE-DUP] {len(duplicate_pairs)} par(es) duplicado(s) detectado(s). Iniciando fusão...")

    merged = 0
    for keeper_id, dup_id in duplicate_pairs:
        try:
            keeper = db.query(Conversation).filter(Conversation.id == keeper_id).first()
            dup = db.query(Conversation).filter(Conversation.id == dup_id).first()
            if not keeper or not dup:
                continue

            # 1. Transferir todos os registros filhos antes de deletar o duplicado.
            # WhatsAppMessage.conversation_id é nullable — sem risco de NOT NULL.
            # ConversationTicket.conversation_id e TicketHistory.conversation_id são NOT NULL:
            # sem esta transferência o SQLAlchemy tenta nulificar antes do DELETE e a DB rejeita.
            from database.models import WhatsAppMessage, ConversationTicket, TicketHistory

            db.query(WhatsAppMessage).filter(
                WhatsAppMessage.conversation_id == dup_id
            ).update({"conversation_id": keeper_id}, synchronize_session=False)

            db.query(ConversationTicket).filter(
                ConversationTicket.conversation_id == dup_id
            ).update({"conversation_id": keeper_id}, synchronize_session=False)

            db.query(TicketHistory).filter(
                TicketHistory.conversation_id == dup_id
            ).update({"conversation_id": keeper_id}, synchronize_session=False)

            # 2. Atualizar metadados do principal se o duplicado tiver atividade mais recente
            if dup.last_message_at and (
                not keeper.last_message_at or dup.last_message_at > keeper.last_message_at
            ):
                keeper.last_message_at = dup.last_message_at
                keeper.last_message_preview = dup.last_message_preview

            # 3. Garantir que o phone do keeper esteja em formato canônico (13 dígitos).
            # Antes da Task #318, conversas eram criadas com o phone como veio do Z-API
            # (podendo ser 10/11/12 dígitos). Após o merge, aproveitamos para normalizar.
            canonical = canonicalize_phone(keeper.phone or dup.phone or "")
            if canonical and canonical != keeper.phone:
                keeper.phone = canonical

            # 4. Remover duplicata
            db.delete(dup)
            db.commit()
            merged += 1
            print(f"[MERGE-DUP] Fundido: conv#{dup_id} ({dup.phone}) → conv#{keeper_id} ({keeper.phone})")

        except Exception as exc:
            db.rollback()
            print(f"[MERGE-DUP] Erro ao fundir conv#{dup_id} → conv#{keeper_id}: {exc}")

    print(f"[MERGE-DUP] Fusão concluída: {merged} par(es) fundido(s).")
    return merged


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
    Cria um novo ConversationTicket para cada escalação.
    Preserva histórico de tickets anteriores.
    Retorna também informações do broker responsável.
    """
    from services.openai_agent import OpenAIAgent
    from database.models import ConversationTicket
    
    conversation_id = conversation.id
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise ValueError(f"Conversation {conversation_id} not found")
    
    broker_name = None
    assessor_name = None
    
    try:
        if conversation.assessor_id:
            assessor = db.query(Assessor).filter(Assessor.id == conversation.assessor_id).first()
            if assessor:
                assessor_name = assessor.nome.split()[0] if assessor.nome else None
                broker_name = assessor.broker_responsavel
    except Exception as e:
        print(f"[ESCALATION] Erro ao buscar assessor/broker: {e}")
    
    messages = db.query(WhatsAppMessage).filter(
        WhatsAppMessage.conversation_id == conversation.id
    ).order_by(WhatsAppMessage.created_at.desc()).limit(15).all()
    
    history = []
    for msg in reversed(messages):
        role = "user" if msg.direction == "inbound" else "assistant"
        content = msg.body or msg.transcription or ""
        history.append({"role": role, "content": content})
    
    agent = OpenAIAgent()
    analysis = await agent.analyze_escalation(history, last_message)
    
    ticket_count = db.query(ConversationTicket).filter(
        ConversationTicket.conversation_id == conversation.id
    ).count()
    
    new_ticket = ConversationTicket(
        conversation_id=conversation.id,
        ticket_number=ticket_count + 1,
        status=TicketStatusV2.NEW.value,
        escalation_level=EscalationLevel.T1_HUMAN.value,
        escalation_category=analysis.get("category", "other"),
        escalation_reason_detail=analysis.get("reason_detail", ""),
        ticket_summary=analysis.get("summary", last_message[:200]),
        conversation_topic=analysis.get("topic", "Outro"),
        transfer_reason=transfer_reason,
        transferred_at=datetime.utcnow()
    )
    db.add(new_ticket)
    db.flush()
    
    conversation.active_ticket_id = new_ticket.id
    conversation.ticket_status = TicketStatusV2.NEW.value
    conversation.escalation_level = EscalationLevel.T1_HUMAN.value
    conversation.status = ConversationStatus.HUMAN_TAKEOVER.value
    conversation.conversation_state = ConversationState.HUMAN_TAKEOVER.value
    conversation.transfer_reason = transfer_reason
    conversation.transferred_at = datetime.utcnow()
    conversation.escalation_category = analysis.get("category", "other")
    conversation.ticket_summary = analysis.get("summary", last_message[:200])
    conversation.conversation_topic = analysis.get("topic", "Outro")
    
    db.commit()
    db.refresh(conversation)
    db.refresh(new_ticket)
    
    print(f"[ESCALATION] Ticket #{new_ticket.id} criado - conversation.active_ticket_id={conversation.active_ticket_id}, ticket_status={conversation.ticket_status}")
    
    return {
        "success": True,
        "ticket_id": new_ticket.id,
        "ticket_number": new_ticket.ticket_number,
        "category": analysis.get("category"),
        "summary": analysis.get("summary"),
        "topic": analysis.get("topic"),
        "broker_name": broker_name,
        "assessor_name": assessor_name
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




CLASSIFICATION_PROMPT_ADDITION = """
ESTILO DE COMUNICAÇÃO - REGRAS OBRIGATÓRIAS:
- Escreva como uma pessoa real no WhatsApp interno, não como um robô
- PROPORCIONALIDADE: adapte o tamanho da resposta à complexidade da pergunta
  • Saudação → 1 frase
  • Pergunta simples e direta → 2-3 frases
  • Pergunta técnica ou sobre um produto → resposta completa com bullet points
  • Comparação entre produtos, pitch ou análise → resposta detalhada e estruturada
- Comece SEMPRE pela resposta direta; contexto e detalhes vêm depois
- Use linguagem informal e natural do dia a dia entre colegas
- Evite frases feitas, clichês corporativos e formalidades
- Nunca use várias perguntas na mesma mensagem
- Nunca repita a mesma ideia com palavras diferentes
- Vá direto ao ponto, sem enrolação
- NUNCA repita na resposta textual algo que uma ação já fez (ex: se já enviou um PDF, não diga "segue o documento" de novo)

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
    r'^(👍|👌|✅|🙏|😊|🎉)$',
    r'^(por enquanto é isso|por agora sim|agora sim)$',
    r'^(massa|dahora|boa|boua|nice|show de bola)$',
    # "Só" como mensagem isolada = "só isso" / "era só isso"
    r'^(s[oó]|era s[oó]|[eé] isso|por hora [eé] isso|por enquanto s[oó])$',
]


NEGATIVE_CONFIRMATION_PATTERNS = [
    r'^(n[aã]o|nao|naum)$',
    r'^(n[aã]o preciso|nao preciso)$',
    r'^(n[aã]o,?\s*obrigad[oa])$',
    r'^(nada|nada mais|nada por enquanto|nada por agora)$',
    r'^(n[aã]o por enquanto|n[aã]o por agora|por agora n[aã]o)$',
    r'^(t[aá]\s*bom|t[oô]\s*bem|t[oô]\s*[oó]timo)$',
    r'^(pode encerrar|encerrando|encerrado)$',
    r'^(n[aã]o\s*mesmo)$',
]


def is_negative_confirmation(message: str) -> bool:
    """
    Detecta se a mensagem é uma resposta negativa/de encerramento após a
    pergunta de confirmação do bot (ex: "não", "nada", "não preciso").
    Quando o bot está aguardando confirmação, respostas negativas devem
    encerrar a conversa — não passar pelo pipeline de IA novamente.
    """
    if not message:
        return False
    text = message.strip().lower()
    text = re.sub(r'[!.,;:?]+$', '', text).strip()
    for pattern in NEGATIVE_CONFIRMATION_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE | re.UNICODE):
            return True
    return False


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


def _had_substantive_interaction(db: Session, conversation) -> bool:
    """Verifica se o bot respondeu algo substantivo (não apenas saudação) na sessão.
    Checks the most recent INBOUND message's ai_intent (which stores the query
    rewriter's categoria) to determine if the user asked a real question."""
    from database.models import WhatsAppMessage, MessageDirection
    
    NON_SUBSTANTIVE_INTENTS = {
        "unidentified_contact_greeting", "blocked_ticket_open",
        "SAUDACAO", "FORA_ESCOPO",
    }
    
    last_inbound_msg = (
        db.query(WhatsAppMessage)
        .filter(
            WhatsAppMessage.phone == conversation.phone,
            WhatsAppMessage.direction == MessageDirection.INBOUND.value,
            WhatsAppMessage.ai_intent.isnot(None),
        )
        .order_by(WhatsAppMessage.created_at.desc())
        .first()
    )
    
    if not last_inbound_msg:
        return False
    
    if last_inbound_msg.ai_intent in NON_SUBSTANTIVE_INTENTS:
        return False
    
    return True


async def check_pending_confirmations(db: Session, zapi_client, timeout_minutes: int = 5):
    """
    Verifica conversas que aguardam confirmação há mais de X minutos.
    Chamado periodicamente pelo scheduler.
    Só envia confirmação se o bot respondeu algo substantivo na sessão.
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
            if not _had_substantive_interaction(db, conv):
                print(f"[FLOW] Confirmação NÃO enviada para {conv.phone} — sem interação substantiva (apenas saudação)")
                continue
            await send_confirmation_request(db, conv, zapi_client)
            print(f"[FLOW] Confirmação enviada para {conv.phone}")
        except Exception as e:
            print(f"[FLOW] Erro ao processar confirmação para {conv.phone}: {e}")


# ---------------------------------------------------------------------------
# Task #223 — Resolução de canal WhatsApp para o pipeline de resposta
# ---------------------------------------------------------------------------

def resolve_channel_client_for_conversation(conversation: Optional[Conversation], db: Session):
    """
    Task #223/#261 — Ponto de integração central para resolução do canal WhatsApp.

    Dado uma Conversation, retorna o ZAPIClient correto para enviar a resposta
    do agente. Prioriza o canal ATRIBUÍDO ao assessor (canal de entrega), não o
    canal pelo qual a mensagem chegou (canal inbound).

    Cadeia de resolução (Task #261 — canal de ENTREGA):
    1. Se a conversa tiver assessor vinculado → resolve via get_zapi_client_for_assessor
       (canal explícito no Assessor.channel_id → mapeamento unidade → legado).
    2. Senão, se conversation.channel_id estiver preenchido → usa como fallback
       (preserva compatibilidade para conversas sem assessor identificado).
    3. Fallback final: cliente legado (env vars) — nunca lança exceção.
    """
    from services.whatsapp_client import get_zapi_client_for_channel, get_zapi_client_for_assessor, zapi_client

    if conversation is None:
        return zapi_client

    try:
        # Task #261 — Prioridade: canal atribuído ao assessor (entrega), não canal inbound.
        if conversation.assessor_id:
            from database.models import Assessor
            assessor = db.query(Assessor).filter(Assessor.id == conversation.assessor_id).first()
            if assessor:
                return get_zapi_client_for_assessor(
                    assessor.telefone_whatsapp,
                    assessor.unidade,
                    db,
                )

        # Fallback: conversation.channel_id (pode ser o canal inbound da criação,
        # mas é melhor do que o legado para conversas sem assessor identificado).
        if conversation.channel_id:
            return get_zapi_client_for_channel(conversation.channel_id, db)

        return zapi_client
    except Exception as exc:
        print(f"[FLOW] Aviso: erro ao resolver canal para conversa {getattr(conversation, 'id', '?')}: {exc} — usando legado")
        return zapi_client
