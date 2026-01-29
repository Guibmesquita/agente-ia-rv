"""
Endpoints para o dashboard de Insights.
Métricas e gráficos para gestão de Renda Variável.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct, case, and_, extract
from datetime import datetime, timedelta
from typing import Optional, List
import json

from database.database import get_db
from database.models import (
    ConversationInsight, Assessor, Campaign, CampaignDispatch,
    Ticket, User, UserRole
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
    
    total_interactions = query.count()
    
    active_assessors = query.filter(
        ConversationInsight.assessor_id.isnot(None)
    ).with_entities(
        func.count(distinct(ConversationInsight.assessor_id))
    ).scalar() or 0
    
    resolved_by_ai = query.filter(
        ConversationInsight.resolved_by_ai == True,
        ConversationInsight.escalated_to_human == False
    ).count()
    
    ai_resolution_rate = (resolved_by_ai / total_interactions * 100) if total_interactions > 0 else 0
    
    escalated_count = query.filter(
        ConversationInsight.escalated_to_human == True
    ).count()
    
    tickets_created = query.filter(
        ConversationInsight.ticket_created == True
    ).count()
    
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
        "total_interactions": total_interactions,
        "active_assessors": active_assessors,
        "ai_resolution_rate": round(ai_resolution_rate, 1),
        "escalated_count": escalated_count,
        "tickets_created": tickets_created,
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
    """Retorna proporção IA vs Humanos."""
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
    
    total = query.count()
    resolved_ai = query.filter(
        ConversationInsight.resolved_by_ai == True,
        ConversationInsight.escalated_to_human == False
    ).count()
    escalated = query.filter(ConversationInsight.escalated_to_human == True).count()
    
    return {
        "labels": ["Resolvido pela IA", "Escalado para Humano"],
        "data": [resolved_ai, escalated]
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
    
    query = db.query(
        ConversationInsight.assessor_name,
        ConversationInsight.unidade,
        func.count(ConversationInsight.id).label('count')
    ).filter(
        ConversationInsight.created_at >= date_start,
        ConversationInsight.created_at <= date_end,
        ConversationInsight.assessor_name.isnot(None)
    )
    
    if macro_area:
        query = query.filter(ConversationInsight.macro_area == macro_area)
    if unidade:
        query = query.filter(ConversationInsight.unidade == unidade)
    if broker:
        query = query.filter(ConversationInsight.broker_responsavel == broker)
    
    results = query.group_by(
        ConversationInsight.assessor_name,
        ConversationInsight.unidade
    ).order_by(func.count(ConversationInsight.id).desc()).limit(10).all()
    
    return [{"nome": r.assessor_name, "unidade": r.unidade, "count": r.count} for r in results]


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
        ConversationInsight.ticket_created == True,
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
