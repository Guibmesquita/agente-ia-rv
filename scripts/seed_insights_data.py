"""
Script para gerar dados fictícios para o Dashboard de Insights.
NÃO inclui dados para a Base de Conhecimento (products, materials, blocks).

Gera:
- Assessores (40)
- Conversations (120)
- ConversationTickets (40)
- ConversationInsights (250)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database.database import SessionLocal
from database.models import (
    Assessor, Conversation, ConversationTicket, ConversationInsight,
    ConversationState, ConversationStatus, TicketStatusV2, EscalationLevel
)

UNIDADES = [
    "São Paulo - Faria Lima", "São Paulo - Paulista", "Rio de Janeiro - Centro",
    "Belo Horizonte", "Curitiba", "Porto Alegre"
]

EQUIPES = ["Equipe Alpha", "Equipe Beta", "Equipe Gamma", "Equipe Delta"]

MACRO_AREAS = ["Renda Variável", "Renda Fixa", "Multimercado"]

BROKERS = ["Carlos Silva", "Marina Santos", "Ricardo Oliveira", "Patrícia Lima"]

NOMES_MASCULINOS = [
    "João", "Pedro", "Lucas", "Gabriel", "Rafael", "Matheus", "Bruno", "Felipe",
    "Gustavo", "André", "Leonardo", "Thiago", "Ricardo", "Marcelo", "Fernando"
]
NOMES_FEMININOS = [
    "Ana", "Maria", "Juliana", "Fernanda", "Camila", "Carolina", "Beatriz",
    "Larissa", "Amanda", "Patrícia", "Mariana", "Gabriela", "Letícia", "Renata"
]
SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Almeida",
    "Pereira", "Lima", "Carvalho", "Ribeiro", "Costa", "Martins", "Gomes", "Rocha"
]

INSIGHT_CATEGORIES = [
    "consulta_produto", "duvida_operacional", "informacao_mercado",
    "cotacao_fii", "sugestao_alocacao", "documentacao", "prazo_resgate",
    "tributacao", "comparativo_fundos", "performance_carteira",
    "novos_produtos", "regulatorio"
]

PRODUCTS = [
    "MXRF11", "HGLG11", "XPML11", "VISC11", "KNRI11", "BTLG11",
    "TG Core FII", "Kinea Renda", "XP Malls", "BTG Pactual Logística"
]

ESCALATION_CATEGORIES = [
    "out_of_scope", "info_not_found", "technical_complexity",
    "commercial_request", "explicit_human_request", "emotional_friction",
    "stalled_conversation", "recurring_issue", "sensitive_topic",
    "investment_decision", "other"
]

USER_MESSAGES = [
    "Qual a rentabilidade do MXRF11 nos últimos 12 meses?",
    "Como funciona o prazo de resgate de FIIs?",
    "Quero entender melhor a tributação de fundos imobiliários",
    "O que acontece com dividendos de FII quando vendo a cota?",
    "Qual a diferença entre FII de tijolo e FII de papel?",
    "Preciso de um relatório de performance da minha carteira",
    "Quais são os melhores FIIs para investir agora?",
    "Como funciona a marcação a mercado em FIIs?",
    "Qual a taxa de administração do HGLG11?",
    "O fundo XPML11 está com preço bom para compra?",
    "Quero aumentar minha exposição em logística",
    "Existe algum FII novo para eu analisar?",
    "Preciso falar com meu assessor sobre minha carteira",
    "Não estou satisfeito com a performance dos meus investimentos",
    "Quero uma recomendação personalizada de alocação"
]

AGENT_RESPONSES = [
    "O MXRF11 apresentou rentabilidade de 12,5% nos últimos 12 meses, considerando dividendos reinvestidos.",
    "O prazo de resgate em FIIs é D+0, ou seja, você recebe o valor no mesmo dia da venda.",
    "FIIs são isentos de IR sobre dividendos para pessoa física. Ganho de capital é tributado em 20%.",
    "Dividendos são pagos proporcionalmente aos dias que você manteve a cota no mês.",
    "FIIs de tijolo investem em imóveis físicos, enquanto FIIs de papel investem em CRIs e LCIs.",
    "Vou preparar um relatório detalhado e enviar para seu e-mail cadastrado.",
    "Baseado no seu perfil, recomendo diversificar entre logística e shoppings.",
    "A marcação a mercado reflete o valor atual das cotas no mercado secundário.",
    "O HGLG11 tem taxa de administração de 0,6% ao ano sobre o patrimônio líquido.",
    "O XPML11 está negociando com desconto de 8% sobre o valor patrimonial."
]

TICKET_SUMMARIES = [
    "Assessor solicita análise detalhada de carteira de FIIs",
    "Dúvida sobre tributação não resolvida pelo bot",
    "Cliente insatisfeito com performance, precisa de atenção",
    "Solicitação de recomendação personalizada de alocação",
    "Questão técnica sobre subscrição de cotas",
    "Pedido de reunião com especialista de renda variável",
    "Reclamação sobre informação desatualizada no sistema",
    "Solicitação de comparativo entre fundos concorrentes"
]


def generate_phone():
    return f"5511{random.randint(900000000, 999999999)}"


def generate_codigo_ai():
    return f"AI{random.randint(10000, 99999)}"


def random_date(days_ago_max=60, days_ago_min=0):
    days = random.randint(days_ago_min, days_ago_max)
    hours = random.randint(8, 18)
    minutes = random.randint(0, 59)
    return datetime.utcnow() - timedelta(days=days, hours=random.randint(0, 23-hours), minutes=minutes)


def create_assessores(db: Session, count: int = 40):
    print(f"Criando {count} assessores...")
    assessores = []
    
    for i in range(count):
        is_female = random.random() < 0.4
        nome = random.choice(NOMES_FEMININOS if is_female else NOMES_MASCULINOS)
        sobrenome = random.choice(SOBRENOMES)
        full_name = f"{nome} {sobrenome}"
        
        email_base = f"{nome.lower()}.{sobrenome.lower()}"
        email = f"{email_base}{random.randint(1, 999)}@svn.com.br"
        
        assessor = Assessor(
            codigo_ai=generate_codigo_ai(),
            nome=full_name,
            email=email,
            telefone_whatsapp=generate_phone(),
            unidade=random.choice(UNIDADES),
            equipe=random.choice(EQUIPES),
            macro_area=random.choice(MACRO_AREAS),
            broker_responsavel=random.choice(BROKERS)
        )
        db.add(assessor)
        assessores.append(assessor)
    
    db.commit()
    for a in assessores:
        db.refresh(a)
    
    print(f"  ✓ {len(assessores)} assessores criados")
    return assessores


def create_conversations(db: Session, assessores: list, count: int = 120):
    print(f"Criando {count} conversas...")
    conversations = []
    
    statuses = [
        (ConversationStatus.BOT_ACTIVE.value, 0.35),
        (ConversationStatus.HUMAN_TAKEOVER.value, 0.30),
        (ConversationStatus.CLOSED.value, 0.35)
    ]
    
    states = [
        (ConversationState.IN_PROGRESS.value, 0.4),
        (ConversationState.HUMAN_TAKEOVER.value, 0.2),
        (ConversationState.COMPLETED.value, 0.3),
        (ConversationState.IDENTIFICATION_PENDING.value, 0.1)
    ]
    
    for i in range(count):
        assessor = random.choice(assessores)
        created = random_date(60, 1)
        
        status = random.choices([s[0] for s in statuses], weights=[s[1] for s in statuses])[0]
        state = random.choices([s[0] for s in states], weights=[s[1] for s in states])[0]
        
        conv = Conversation(
            phone=assessor.telefone_whatsapp,
            contact_name=assessor.nome,
            assessor_id=assessor.id,
            status=status,
            conversation_state=state,
            last_message_at=created + timedelta(hours=random.randint(0, 48)),
            last_message_preview=random.choice(USER_MESSAGES)[:100],
            unread_count=random.randint(0, 3) if status != ConversationStatus.CLOSED.value else 0,
            created_at=created
        )
        
        if status == ConversationStatus.HUMAN_TAKEOVER.value:
            conv.ticket_status = random.choice([TicketStatusV2.NEW.value, TicketStatusV2.OPEN.value])
            conv.escalation_level = EscalationLevel.T1_HUMAN.value
            conv.transferred_at = created + timedelta(minutes=random.randint(5, 30))
        elif status == ConversationStatus.CLOSED.value:
            conv.ticket_status = TicketStatusV2.SOLVED.value
            conv.solved_at = created + timedelta(hours=random.randint(1, 72))
        
        db.add(conv)
        conversations.append(conv)
    
    db.commit()
    for c in conversations:
        db.refresh(c)
    
    print(f"  ✓ {len(conversations)} conversas criadas")
    return conversations


def create_tickets(db: Session, conversations: list, count: int = 40):
    print(f"Criando {count} tickets...")
    tickets = []
    
    escalated_convs = [c for c in conversations if c.status in [
        ConversationStatus.HUMAN_TAKEOVER.value,
        ConversationStatus.CLOSED.value
    ]]
    
    selected_convs = random.sample(escalated_convs, min(count, len(escalated_convs)))
    
    for i, conv in enumerate(selected_convs):
        created = conv.created_at + timedelta(minutes=random.randint(5, 60))
        
        if conv.status == ConversationStatus.CLOSED.value:
            status = TicketStatusV2.SOLVED.value
            solved_at = created + timedelta(hours=random.randint(1, 48))
            resolution_time = int((solved_at - created).total_seconds())
        elif random.random() < 0.3:
            status = TicketStatusV2.NEW.value
            solved_at = None
            resolution_time = None
        else:
            status = TicketStatusV2.OPEN.value
            solved_at = None
            resolution_time = None
        
        ticket = ConversationTicket(
            conversation_id=conv.id,
            ticket_number=i + 1,
            status=status,
            escalation_level=EscalationLevel.T1_HUMAN.value,
            escalation_category=random.choice(ESCALATION_CATEGORIES),
            ticket_summary=random.choice(TICKET_SUMMARIES),
            conversation_topic=random.choice(INSIGHT_CATEGORIES),
            created_at=created,
            transferred_at=created,
            first_human_response_at=created + timedelta(minutes=random.randint(5, 120)) if status != TicketStatusV2.NEW.value else None,
            solved_at=solved_at,
            resolution_time_seconds=resolution_time,
            resolution_category=random.choice([
                "information_provided", "document_sent", "redirected_to_specialist",
                "issue_resolved", "client_satisfied"
            ]) if solved_at else None
        )
        
        db.add(ticket)
        tickets.append(ticket)
        
        conv.active_ticket_id = None
    
    db.commit()
    
    for t in tickets:
        db.refresh(t)
        if t.status != TicketStatusV2.SOLVED.value:
            t.conversation.active_ticket_id = t.id
    
    db.commit()
    
    print(f"  ✓ {len(tickets)} tickets criados")
    return tickets


def create_insights(db: Session, conversations: list, count: int = 250):
    print(f"Criando {count} insights...")
    insights = []
    
    for i in range(count):
        conv = random.choice(conversations)
        assessor = None
        if conv.assessor_id:
            assessor = db.query(Assessor).filter(Assessor.id == conv.assessor_id).first()
        
        resolved_by_ai = random.random() < 0.65
        escalated = not resolved_by_ai and random.random() < 0.7
        
        products = random.sample(PRODUCTS, k=random.randint(0, 3))
        tickers = [p for p in products if len(p) <= 6]
        
        created = random_date(60, 0)
        
        insight = ConversationInsight(
            conversation_id=str(conv.id),
            assessor_id=assessor.id if assessor else None,
            assessor_phone=conv.phone,
            assessor_name=assessor.nome if assessor else conv.contact_name,
            user_message=random.choice(USER_MESSAGES),
            agent_response=random.choice(AGENT_RESPONSES) if resolved_by_ai else None,
            category=random.choice(INSIGHT_CATEGORIES),
            products_mentioned=",".join(products) if products else None,
            tickers_mentioned=",".join(tickers) if tickers else None,
            resolved_by_ai=resolved_by_ai,
            escalated_to_human=escalated,
            ticket_created=escalated and random.random() < 0.8,
            sentiment=random.choice(["positive", "neutral", "negative"]),
            unidade=assessor.unidade if assessor else random.choice(UNIDADES),
            equipe=assessor.equipe if assessor else random.choice(EQUIPES),
            macro_area=assessor.macro_area if assessor else random.choice(MACRO_AREAS),
            broker_responsavel=assessor.broker_responsavel if assessor else random.choice(BROKERS),
            created_at=created
        )
        
        db.add(insight)
        insights.append(insight)
    
    db.commit()
    print(f"  ✓ {len(insights)} insights criados")
    return insights


def main():
    print("\n" + "="*60)
    print("SEED: Gerando dados fictícios para Insights Dashboard")
    print("="*60 + "\n")
    
    db = SessionLocal()
    
    try:
        existing_assessors = db.query(Assessor).count()
        if existing_assessors > 10:
            print(f"⚠️  Já existem {existing_assessors} assessores no banco.")
            response = input("Deseja continuar e adicionar mais dados? (s/N): ")
            if response.lower() != 's':
                print("Operação cancelada.")
                return
        
        assessores = create_assessores(db, count=40)
        conversations = create_conversations(db, assessores, count=120)
        tickets = create_tickets(db, conversations, count=40)
        insights = create_insights(db, conversations, count=250)
        
        print("\n" + "="*60)
        print("✅ SEED CONCLUÍDO COM SUCESSO!")
        print("="*60)
        print(f"\nResumo:")
        print(f"  • {len(assessores)} assessores")
        print(f"  • {len(conversations)} conversas")
        print(f"  • {len(tickets)} tickets")
        print(f"  • {len(insights)} insights")
        print(f"\nAgora você pode acessar /insights para ver o dashboard populado.")
        print("="*60 + "\n")
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ Erro: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
