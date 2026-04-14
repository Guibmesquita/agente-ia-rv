"""
Endpoints para o dashboard de Insights.
Métricas e gráficos para gestão de Renda Variável.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, case, and_, or_, extract, text, String
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import json

from database.database import get_db
from database.models import (
    ConversationInsight, Assessor, Campaign, CampaignDispatch,
    Ticket, User, UserRole, Conversation, TicketStatusV2, EscalationLevel,
    ConversationTicket, WhatsAppMessage, SenderType
)
from api.endpoints.auth import get_current_user

router = APIRouter(prefix="/api/insights", tags=["Insights"])


def require_gestao_or_admin(current_user: User = Depends(get_current_user)):
    """Verifica se o usuário é admin ou gestao_rv."""
    if current_user.role not in [UserRole.ADMIN.value, UserRole.GESTOR.value]:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito a administradores e gestão RV"
        )
    return current_user


def parse_date_filter(period: str, start_date: Optional[str], end_date: Optional[str]):
    """Converte filtro de período em datas."""
    now = datetime.utcnow()
    
    if start_date and end_date:
        return datetime.fromisoformat(start_date), datetime.fromisoformat(end_date)
    
    if period == "7d":
        return now - timedelta(days=7), now
    elif period == "30d":
        return now - timedelta(days=30), now
    elif period == "90d":
        return now - timedelta(days=90), now
    elif period == "365d":
        return now - timedelta(days=365), now
    else:
        return now - timedelta(days=30), now


@router.get("/metrics")
async def get_metrics(
    period: str = Query("30d", description="Período: 7d, 30d, 90d, 365d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    equipe: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna métricas principais do dashboard."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(ConversationInsight).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    if equipe:
        query = query.filter(ConversationInsight.equipe == equipe)
    
    WINDOW_SECS = 43200  # 12 horas

    assessor_identity = func.coalesce(
        ConversationInsight.assessor_phone,
        func.cast(ConversationInsight.assessor_id, String)
    )
    active_assessors = db.query(
        func.count(distinct(assessor_identity))
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        or_(
            ConversationInsight.assessor_phone.isnot(None),
            ConversationInsight.assessor_id.isnot(None),
        ),
        *([ConversationInsight.macro_area == macro_area] if macro_area else []),
        *([ConversationInsight.unidade == unidade] if unidade else []),
        *([ConversationInsight.broker_responsavel == broker] if broker else []),
        *([ConversationInsight.equipe == equipe] if equipe else []),
    ).scalar() or 0

    window_col = func.floor(
        func.extract('epoch', WhatsAppMessage.created_at) / WINDOW_SECS
    )
    has_human_col = func.max(
        case(
            (WhatsAppMessage.sender_type == SenderType.HUMAN.value, 1),
            else_=0
        )
    )

    win_q = db.query(
        WhatsAppMessage.conversation_id,
        window_col.label('wid'),
        has_human_col.label('has_human')
    ).filter(
        WhatsAppMessage.created_at >= date_start,
        WhatsAppMessage.created_at <= date_end,
        WhatsAppMessage.conversation_id.isnot(None)
    )

    if any([macro_area, unidade, broker, equipe]):
        win_q = win_q.join(
            Conversation, WhatsAppMessage.conversation_id == Conversation.id
        ).join(
            Assessor, Conversation.assessor_id == Assessor.id
        )
        if macro_area:
            win_q = win_q.filter(Assessor.macro_area == macro_area)
        if unidade:
            win_q = win_q.filter(Assessor.unidade == unidade)
        if broker:
            win_q = win_q.filter(Assessor.broker_responsavel == broker)
        if equipe:
            win_q = win_q.filter(Assessor.equipe == equipe)

    win_q = win_q.group_by(WhatsAppMessage.conversation_id, window_col)
    win_sq = win_q.subquery()

    total_windows = db.query(func.count()).select_from(win_sq).scalar() or 0
    human_windows = db.query(func.count()).select_from(win_sq).filter(
        win_sq.c.has_human == 1
    ).scalar() or 0
    ai_windows = total_windows - human_windows
    ai_resolution_rate = (ai_windows / total_windows * 100) if total_windows > 0 else 0

    campaign_query = db.query(Campaign).filter(
        Campaign.created_at >= date_start,
        Campaign.created_at <= date_end
    )
    total_campaigns = campaign_query.count()

    dispatch_query = db.query(CampaignDispatch).join(Campaign).filter(
        Campaign.created_at >= date_start,
        Campaign.created_at <= date_end,
        CampaignDispatch.status == "sent"
    )
    total_assessors_reached = dispatch_query.with_entities(
        func.count(distinct(CampaignDispatch.assessor_id))
    ).scalar() or 0

    return {
        "total_interactions": total_windows,
        "active_assessors": active_assessors,
        "ai_resolution_rate": round(ai_resolution_rate, 1),
        "total_campaigns": total_campaigns,
        "total_assessors_reached": total_assessors_reached
    }


@router.get("/activity")
async def get_activity_chart(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    equipe: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna dados para gráfico de atividade diária."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(
        func.date(ConversationInsight.created_at).label('date'),
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    if equipe:
        query = query.filter(ConversationInsight.equipe == equipe)
    
    results = query.group_by(func.date(ConversationInsight.created_at)).order_by('date').all()
    
    return {
        "labels": [str(r.date) for r in results],
        "data": [r.count for r in results]
    }


@router.get("/categories")
async def get_categories_chart(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    equipe: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna distribuição por categoria de dúvidas."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(
        ConversationInsight.category,
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.category.isnot(None),
        ConversationInsight.category != "Saudação"
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    if equipe:
        query = query.filter(ConversationInsight.equipe == equipe)
    
    results = query.group_by(ConversationInsight.category).order_by(func.count(ConversationInsight.id).desc()).limit(10).all()
    
    return {
        "labels": [r.category or "Outro" for r in results],
        "data": [r.count for r in results]
    }


@router.get("/products")
async def get_products_chart(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    equipe: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna ranking de produtos/tickers mais mencionados."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(ConversationInsight).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    if equipe:
        query = query.filter(ConversationInsight.equipe == equipe)
    
    insights = query.all()
    
    ticker_counts = {}
    for insight in insights:
        if insight.tickers_mentioned:
            try:
                tickers = json.loads(insight.tickers_mentioned)
                for ticker in tickers:
                    ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
            except:
                pass
    
    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return {
        "labels": [t[0] for t in sorted_tickers],
        "data": [t[1] for t in sorted_tickers]
    }


@router.get("/resolution")
async def get_resolution_chart(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    equipe: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna proporção IA vs Humanos baseada em janelas de 12h de mensagens reais."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    WINDOW_SECS = 43200

    window_col = func.floor(
        func.extract('epoch', WhatsAppMessage.created_at) / WINDOW_SECS
    )
    has_human_col = func.max(
        case(
            (WhatsAppMessage.sender_type == SenderType.HUMAN.value, 1),
            else_=0
        )
    )

    win_q = db.query(
        WhatsAppMessage.conversation_id,
        window_col.label('wid'),
        has_human_col.label('has_human')
    ).filter(
        WhatsAppMessage.created_at >= date_start,
        WhatsAppMessage.created_at <= date_end,
        WhatsAppMessage.conversation_id.isnot(None)
    )

    if any([macro_area, unidade, broker, equipe]):
        win_q = win_q.join(
            Conversation, WhatsAppMessage.conversation_id == Conversation.id
        ).join(
            Assessor, Conversation.assessor_id == Assessor.id
        )
        if macro_area:
            win_q = win_q.filter(Assessor.macro_area == macro_area)
        if unidade:
            win_q = win_q.filter(Assessor.unidade == unidade)
        if broker:
            win_q = win_q.filter(Assessor.broker_responsavel == broker)
        if equipe:
            win_q = win_q.filter(Assessor.equipe == equipe)

    win_q = win_q.group_by(WhatsAppMessage.conversation_id, window_col)
    win_sq = win_q.subquery()

    total_windows = db.query(func.count()).select_from(win_sq).scalar() or 0
    human_windows = db.query(func.count()).select_from(win_sq).filter(
        win_sq.c.has_human == 1
    ).scalar() or 0
    ai_windows = total_windows - human_windows

    return {
        "labels": ["Resolvido pela IA", "Intervenção Humana"],
        "data": [ai_windows, human_windows]
    }


@router.get("/top-units")
async def get_top_units(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    broker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna Top 5 Unidades mais ativas."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(
        ConversationInsight.unidade,
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.unidade.isnot(None)
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    
    results = query.group_by(ConversationInsight.unidade).order_by(func.count(ConversationInsight.id).desc()).all()
    
    return [{"unidade": r.unidade, "count": r.count} for r in results]


@router.get("/top-assessors")
async def get_top_assessors(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna Top 10 Assessores mais ativos."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    identity_expr = func.coalesce(
        ConversationInsight.assessor_phone,
        func.cast(ConversationInsight.assessor_id, String)
    )
    display_name_expr = func.coalesce(
        ConversationInsight.assessor_name,
        ConversationInsight.assessor_phone,
        func.cast(ConversationInsight.assessor_id, String)
    )

    base_filters = [
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        or_(
            ConversationInsight.assessor_phone.isnot(None),
            ConversationInsight.assessor_id.isnot(None),
        ),
    ]

    if macro_area:
        base_filters.append(ConversationInsight.macro_area == macro_area)
    if unidade:
        base_filters.append(ConversationInsight.unidade == unidade)
    if broker:
        base_filters.append(ConversationInsight.broker_responsavel == broker)

    top_rows = db.query(
        identity_expr.label('identity'),
        func.max(display_name_expr).label('display_name'),
        func.count(ConversationInsight.id).label('total_count')
    ).filter(*base_filters).group_by(
        identity_expr
    ).order_by(func.count(ConversationInsight.id).desc()).limit(10).all()

    if not top_rows:
        return []

    identities = [r.identity for r in top_rows if r.identity]

    unidade_rows = db.query(
        identity_expr.label('identity'),
        ConversationInsight.unidade,
        func.count(ConversationInsight.id).label('cnt')
    ).filter(
        *base_filters,
        identity_expr.in_(identities),
        ConversationInsight.unidade.isnot(None),
    ).group_by(
        identity_expr,
        ConversationInsight.unidade
    ).all()

    best_unidade: dict = {}
    for row in unidade_rows:
        key = row.identity
        if key not in best_unidade or row.cnt > best_unidade[key][1]:
            best_unidade[key] = (row.unidade, row.cnt)

    output = []
    for r in top_rows:
        if r.total_count > 0:
            unidade_val = best_unidade.get(r.identity, (None, 0))[0] if r.identity else None
            output.append({
                "nome": r.display_name,
                "unidade": unidade_val or "Sem unidade",
                "count": r.total_count
            })

    return output


@router.get("/complexity-map")
async def get_complexity_map(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    broker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna volume de chamados por unidade (mapa de complexidade)."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(
        ConversationInsight.unidade,
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.escalated_to_human == True,
        ConversationInsight.unidade.isnot(None)
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    
    results = query.group_by(ConversationInsight.unidade).order_by(func.count(ConversationInsight.id).desc()).limit(10).all()
    
    return {
        "labels": [r.unidade for r in results],
        "data": [r.count for r in results]
    }


@router.get("/tickets-by-unit")
async def get_tickets_by_unit(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    broker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna volume de chamados/escalacoes criados por unidade (Mapa de Complexidade)."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(
        ConversationInsight.unidade,
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.unidade.isnot(None),
        ConversationInsight.escalated_to_human == True
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    
    results = query.group_by(ConversationInsight.unidade).order_by(func.count(ConversationInsight.id).desc()).all()
    
    return [{"unidade": r.unidade, "count": r.count} for r in results]


@router.get("/feedbacks")
async def get_feedbacks(
    period: str = Query("30d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    macro_area: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna feedbacks extraídos das conversas."""
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    query = db.query(ConversationInsight).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.feedback_text.isnot(None)
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    
    feedbacks = query.order_by(ConversationInsight.created_at.desc()).limit(limit).all()
    
    return [{
        "id": f.id,
        "assessor_name": f.assessor_name,
        "unidade": f.unidade,
        "feedback_text": f.feedback_text,
        "feedback_type": f.feedback_type,
        "sentiment": f.sentiment,
        "created_at": f.created_at.isoformat() if f.created_at else None
    } for f in feedbacks]


@router.get("/filters")
async def get_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """Retorna opções disponíveis para os filtros."""
    
    macro_areas = db.query(distinct(Assessor.macro_area)).filter(
        Assessor.macro_area.isnot(None)
    ).all()
    
    unidades = db.query(distinct(Assessor.unidade)).filter(
        Assessor.unidade.isnot(None)
    ).all()
    
    brokers = db.query(distinct(Assessor.broker_responsavel)).filter(
        Assessor.broker_responsavel.isnot(None)
    ).all()
    
    equipes = db.query(distinct(Assessor.equipe)).filter(
        Assessor.equipe.isnot(None)
    ).all()
    
    return {
        "macro_areas": [m[0] for m in macro_areas if m[0]],
        "unidades": [u[0] for u in unidades if u[0]],
        "brokers": [b[0] for b in brokers if b[0]],
        "equipes": [e[0] for e in equipes if e[0]]
    }


@router.get("/tickets")
async def get_ticket_metrics(
    period: str = Query("30d", description="Período: 7d, 30d, 90d, 365d"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    unidade: Optional[str] = None,
    broker: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_gestao_or_admin)
):
    """
    Métricas de chamados/tickets para o dashboard de Insights.
    Inclui volume por status, unidade, broker, tempo de atendimento.
    """
    date_start, date_end = parse_date_filter(period, start_date, end_date)
    
    base_filters = [
        Conversation.escalation_level == EscalationLevel.T1_HUMAN.value,
        Conversation.created_at >= date_start,
        Conversation.created_at <= date_end
    ]
    
    assessor_join_needed = unidade or broker
    assessor_filters = []
    if unidade:
        assessor_filters.append(Assessor.unidade == unidade)
    if broker:
        assessor_filters.append(Assessor.broker_responsavel == broker)
    
    if assessor_join_needed:
        total_tickets = db.query(func.count(Conversation.id)).join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*base_filters, *assessor_filters).scalar() or 0
        
        status_counts = db.query(
            Conversation.ticket_status,
            func.count(Conversation.id)
        ).join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*base_filters, *assessor_filters).group_by(Conversation.ticket_status).all()
    else:
        total_tickets = db.query(func.count(Conversation.id)).filter(*base_filters).scalar() or 0
        
        status_counts = db.query(
            Conversation.ticket_status,
            func.count(Conversation.id)
        ).filter(*base_filters).group_by(Conversation.ticket_status).all()
    
    status_dict = {s[0]: s[1] for s in status_counts}
    
    by_unidade_query = db.query(
        Assessor.unidade,
        func.count(Conversation.id)
    ).join(
        Conversation, Conversation.assessor_id == Assessor.id
    ).filter(*base_filters, Assessor.unidade.isnot(None))
    if broker:
        by_unidade_query = by_unidade_query.filter(Assessor.broker_responsavel == broker)
    by_unidade = by_unidade_query.group_by(Assessor.unidade).order_by(func.count(Conversation.id).desc()).limit(10).all()
    
    by_broker_query = db.query(
        Assessor.broker_responsavel,
        func.count(Conversation.id)
    ).join(
        Conversation, Conversation.assessor_id == Assessor.id
    ).filter(*base_filters, Assessor.broker_responsavel.isnot(None))
    if unidade:
        by_broker_query = by_broker_query.filter(Assessor.unidade == unidade)
    by_broker = by_broker_query.group_by(Assessor.broker_responsavel).order_by(func.count(Conversation.id).desc()).limit(10).all()
    
    by_category_query = db.query(
        Conversation.escalation_category,
        func.count(Conversation.id)
    ).filter(*base_filters, Conversation.escalation_category.isnot(None))
    if assessor_join_needed:
        by_category_query = by_category_query.join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*assessor_filters)
    by_category = by_category_query.group_by(Conversation.escalation_category).order_by(func.count(Conversation.id).desc()).all()
    
    resolved_filters = base_filters + [
        Conversation.ticket_status == TicketStatusV2.SOLVED.value,
        Conversation.solved_at.isnot(None),
        Conversation.first_human_response_at.isnot(None)
    ]
    if assessor_join_needed:
        resolved_tickets = db.query(Conversation).join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*resolved_filters, *assessor_filters).all()
    else:
        resolved_tickets = db.query(Conversation).filter(*resolved_filters).all()
    
    avg_response_time = 0
    avg_resolution_time = 0
    if resolved_tickets:
        response_times = []
        resolution_times = []
        for t in resolved_tickets:
            if t.transferred_at and t.first_human_response_at:
                diff = (t.first_human_response_at - t.transferred_at).total_seconds()
                if diff > 0:
                    response_times.append(diff)
            if t.transferred_at and t.solved_at:
                diff = (t.solved_at - t.transferred_at).total_seconds()
                if diff > 0:
                    resolution_times.append(diff)
        
        if response_times:
            avg_response_time = sum(response_times) / len(response_times) / 60
        if resolution_times:
            avg_resolution_time = sum(resolution_times) / len(resolution_times) / 60
    
    solved_count = status_dict.get(TicketStatusV2.SOLVED.value, 0)
    resolution_rate = (solved_count / total_tickets * 100) if total_tickets > 0 else 0
    
    bot_resolved_filters = [
        Conversation.escalation_level == EscalationLevel.T0_BOT.value,
        Conversation.bot_resolved_at.isnot(None),
        Conversation.created_at >= date_start,
        Conversation.created_at <= date_end
    ]
    if assessor_join_needed:
        bot_resolved = db.query(Conversation).join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*bot_resolved_filters, *assessor_filters).all()
    else:
        bot_resolved = db.query(Conversation).filter(*bot_resolved_filters).all()
    
    bot_resolved_count = len(bot_resolved)
    avg_time_saved = 0
    if bot_resolved:
        time_saved_list = []
        for conv in bot_resolved:
            if conv.created_at and conv.bot_resolved_at:
                diff = (conv.bot_resolved_at - conv.created_at).total_seconds()
                if diff > 0:
                    time_saved_list.append(diff)
        if time_saved_list:
            avg_time_saved = sum(time_saved_list) / len(time_saved_list) / 60
    
    total_conversations_period = db.query(func.count(Conversation.id)).filter(
        Conversation.created_at >= date_start,
        Conversation.created_at <= date_end
    ).scalar() or 0
    
    bot_resolution_rate = (bot_resolved_count / total_conversations_period * 100) if total_conversations_period > 0 else 0
    
    daily_volume_query = db.query(
        func.date(Conversation.created_at).label('date'),
        func.count(Conversation.id)
    ).filter(*base_filters)
    if assessor_join_needed:
        daily_volume_query = daily_volume_query.join(
            Assessor, Conversation.assessor_id == Assessor.id
        ).filter(*assessor_filters)
    daily_volume = daily_volume_query.group_by(func.date(Conversation.created_at)).order_by(func.date(Conversation.created_at)).all()
    
    result = {
        "summary": {
            "total_tickets": total_tickets,
            "new": status_dict.get(TicketStatusV2.NEW.value, 0),
            "open": status_dict.get(TicketStatusV2.OPEN.value, 0),
            "in_progress": status_dict.get(TicketStatusV2.IN_PROGRESS.value, 0),
            "solved": solved_count,
            "resolution_rate": round(resolution_rate, 1),
            "avg_response_time_minutes": round(avg_response_time, 1),
            "avg_resolution_time_minutes": round(avg_resolution_time, 1)
        },
        "bot_metrics": {
            "bot_resolved_count": bot_resolved_count,
            "bot_resolution_rate": round(bot_resolution_rate, 1),
            "avg_time_saved_minutes": round(avg_time_saved, 1),
            "total_conversations": total_conversations_period
        },
        "by_status": [{"status": s[0], "count": s[1]} for s in status_counts],
        "by_unidade": [{"unidade": u[0], "count": u[1]} for u in by_unidade],
        "by_broker": [{"broker": b[0], "count": b[1]} for b in by_broker],
        "by_category": [{"category": c[0], "count": c[1]} for c in by_category],
        "daily_volume": [{"date": str(d[0]), "count": d[1]} for d in daily_volume]
    }
    
    return result
