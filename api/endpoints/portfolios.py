"""
Endpoints para gestão de Carteiras Recomendadas (Task #206).

Uma Carteira Recomendada é um objeto de primeiro nível, hierarquicamente
acima dos produtos. Ela tem nome único, tipo informativo, descrição e
membros (produtos financeiros). Seus materiais são indexados no RAG com
metadados de portfólio (portfolio_id, portfolio_name).
"""
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func as _sa_func
from typing import Optional
import json

from database.database import get_db
from database.models import Portfolio, PortfolioProduct, Product, Material, User
from api.endpoints.auth import get_current_user


router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _require_role(current_user: User) -> None:
    if current_user.role not in ("admin", "gestao_rv", "broker"):
        raise HTTPException(status_code=403, detail="Acesso negado")


def _portfolio_to_dict(portfolio: Portfolio, db: Session, include_members: bool = True) -> dict:
    """Serializa um Portfolio com contagem de membros e materiais."""
    members_count = db.query(_sa_func.count(PortfolioProduct.id)).filter(
        PortfolioProduct.portfolio_id == portfolio.id
    ).scalar() or 0

    materials_count = db.query(_sa_func.count(Material.id)).filter(
        Material.portfolio_id == portfolio.id
    ).scalar() or 0

    payload = {
        "id": portfolio.id,
        "name": portfolio.name,
        "portfolio_type": portfolio.portfolio_type,
        "description": portfolio.description,
        "is_active": portfolio.is_active,
        "members_count": int(members_count),
        "materials_count": int(materials_count),
        "created_at": portfolio.created_at.isoformat() if portfolio.created_at else None,
        "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None,
    }

    if include_members:
        members = (
            db.query(PortfolioProduct, Product)
            .join(Product, Product.id == PortfolioProduct.product_id)
            .filter(PortfolioProduct.portfolio_id == portfolio.id)
            .all()
        )
        payload["members"] = [
            {
                "product_id": pp.product_id,
                "name": prod.name,
                "ticker": prod.ticker,
                "product_type": prod.product_type,
                "added_at": pp.added_at.isoformat() if pp.added_at else None,
            }
            for pp, prod in members
        ]

    return payload


# ─── LIST ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_portfolios(
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista todas as Carteiras Recomendadas."""
    q = db.query(Portfolio)
    if active_only:
        q = q.filter(Portfolio.is_active == True)
    portfolios = q.order_by(Portfolio.name).all()
    return {
        "portfolios": [_portfolio_to_dict(p, db, include_members=False) for p in portfolios],
        "count": len(portfolios),
    }


# ─── CREATE ──────────────────────────────────────────────────────────────────

@router.post("")
async def create_portfolio(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria uma nova Carteira Recomendada."""
    _require_role(current_user)
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nome da carteira é obrigatório")

    existing = db.query(Portfolio).filter(Portfolio.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Já existe uma carteira com o nome '{name}'")

    portfolio = Portfolio(
        name=name,
        portfolio_type=body.get("portfolio_type") or None,
        description=body.get("description") or None,
        is_active=bool(body.get("is_active", True)),
        created_by=current_user.id,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return _portfolio_to_dict(portfolio, db)


# ─── GET ─────────────────────────────────────────────────────────────────────

@router.get("/{portfolio_id}")
async def get_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna uma Carteira Recomendada com membros e materiais."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    result = _portfolio_to_dict(portfolio, db, include_members=True)

    # Materiais da carteira com status de indexação
    mats = (
        db.query(Material)
        .filter(Material.portfolio_id == portfolio_id)
        .order_by(Material.created_at.desc())
        .all()
    )
    result["materials"] = [
        {
            "id": m.id,
            "name": m.name,
            "material_type": m.material_type,
            "publish_status": m.publish_status,
            "is_indexed": m.is_indexed,
            "source_filename": m.source_filename,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in mats
    ]

    return result


# ─── UPDATE ──────────────────────────────────────────────────────────────────

@router.put("/{portfolio_id}")
async def update_portfolio(
    portfolio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza nome, tipo ou descrição de uma Carteira Recomendada."""
    _require_role(current_user)
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    body = await request.json()
    if "name" in body:
        new_name = (body["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Nome não pode ser vazio")
        if new_name != portfolio.name:
            dup = db.query(Portfolio).filter(Portfolio.name == new_name).first()
            if dup:
                raise HTTPException(status_code=409, detail=f"Já existe uma carteira com o nome '{new_name}'")
        portfolio.name = new_name

    if "portfolio_type" in body:
        portfolio.portfolio_type = body["portfolio_type"] or None
    if "description" in body:
        portfolio.description = body["description"] or None
    if "is_active" in body:
        portfolio.is_active = bool(body["is_active"])

    db.commit()
    db.refresh(portfolio)
    return _portfolio_to_dict(portfolio, db)


# ─── DELETE (soft delete) ─────────────────────────────────────────────────────

@router.delete("/{portfolio_id}")
async def delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Desativa uma Carteira Recomendada (soft delete: is_active=False).

    Os membros e materiais são preservados no banco; a carteira fica invisível
    na listagem padrão e o agente não a detecta via detect_portfolio_name_in_query
    (que filtra apenas carteiras ativas).

    Para exclusão física (hard delete), use o endpoint de manutenção
    POST /api/portfolios/{id}/hard-delete — restrito a admin.
    """
    _require_role(current_user)
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    portfolio.is_active = False
    from datetime import datetime, timezone
    portfolio.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(portfolio)
    return {"ok": True, "deactivated_id": portfolio_id, "is_active": False}


@router.post("/{portfolio_id}/hard-delete")
async def hard_delete_portfolio(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Exclusão física permanente de uma Carteira Recomendada (somente admin).

    Remove membros, desvincula materiais (portfolio_id → NULL), limpa
    embeddings com portfolio_id desta carteira, e apaga o registro.
    Operação irreversível.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Somente administradores podem excluir carteiras permanentemente")

    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    # 1) Desvincular materiais (não excluir — materiais são independentes)
    db.query(Material).filter(Material.portfolio_id == portfolio_id).update(
        {"portfolio_id": None}, synchronize_session=False
    )

    # 2) Limpar embeddings com portfolio_id desta carteira usando a sessão atual
    from sqlalchemy import text as _sql_text
    db.execute(
        _sql_text(
            "UPDATE document_embeddings SET portfolio_id = NULL, portfolio_name = NULL "
            "WHERE portfolio_id = :pid"
        ),
        {"pid": portfolio_id},
    )

    # 3) Remover membros (ON DELETE CASCADE cobre isso, mas explicitamos)
    db.query(PortfolioProduct).filter(
        PortfolioProduct.portfolio_id == portfolio_id
    ).delete(synchronize_session=False)

    # 4) Excluir a carteira
    db.delete(portfolio)
    db.commit()
    return {"ok": True, "hard_deleted_id": portfolio_id}


# ─── MEMBERS ─────────────────────────────────────────────────────────────────

@router.post("/{portfolio_id}/members")
async def add_member(
    portfolio_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Adiciona um produto como membro da carteira."""
    _require_role(current_user)
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    body = await request.json()
    product_id = body.get("product_id")
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id é obrigatório")

    product = db.query(Product).filter(Product.id == int(product_id)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    existing = db.query(PortfolioProduct).filter(
        PortfolioProduct.portfolio_id == portfolio_id,
        PortfolioProduct.product_id == int(product_id),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Produto já é membro desta carteira")

    pp = PortfolioProduct(portfolio_id=portfolio_id, product_id=int(product_id))
    db.add(pp)
    db.commit()
    return _portfolio_to_dict(portfolio, db)


@router.delete("/{portfolio_id}/members/{product_id}")
async def remove_member(
    portfolio_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove um produto da carteira."""
    _require_role(current_user)
    pp = db.query(PortfolioProduct).filter(
        PortfolioProduct.portfolio_id == portfolio_id,
        PortfolioProduct.product_id == product_id,
    ).first()
    if not pp:
        raise HTTPException(status_code=404, detail="Membro não encontrado nesta carteira")

    db.delete(pp)
    db.commit()
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    return _portfolio_to_dict(portfolio, db)


# ─── PRODUCTS SEARCH (para picker de membros) ─────────────────────────────────

@router.get("/{portfolio_id}/available-products")
async def available_products(
    portfolio_id: int,
    q: str = "",
    limit: int = 40,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista produtos disponíveis para adicionar como membros (exclui já-membros)."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    existing_ids = [pp.product_id for pp in db.query(PortfolioProduct).filter(
        PortfolioProduct.portfolio_id == portfolio_id
    ).all()]

    query = db.query(Product).filter(Product.status == "ativo")
    if existing_ids:
        query = query.filter(Product.id.notin_(existing_ids))
    if q:
        query = query.filter(
            (Product.name.ilike(f"%{q}%")) | (Product.ticker.ilike(f"%{q}%"))
        )

    products = query.order_by(Product.name).limit(limit).all()
    return {
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker,
                "product_type": p.product_type,
            }
            for p in products
        ]
    }


# ─── REINDEX ─────────────────────────────────────────────────────────────────

@router.post("/{portfolio_id}/reindex")
async def reindex_portfolio(
    portfolio_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dispara a reindexação de todos os materiais da carteira no vector store."""
    _require_role(current_user)
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    mats = db.query(Material).filter(
        Material.portfolio_id == portfolio_id,
        Material.publish_status == "publicado",
    ).all()

    material_ids = [m.id for m in mats]
    if not material_ids:
        return {"ok": True, "reindexed": 0, "message": "Nenhum material publicado para reindexar"}

    def _do_reindex():
        try:
            from services.product_ingestor import ProductIngestor
            from database.database import SessionLocal
            _db = SessionLocal()
            try:
                for mid in material_ids:
                    try:
                        ingestor = ProductIngestor(_db)
                        ingestor.index_material(mid)
                    except Exception as e:
                        print(f"[portfolio reindex] Erro no material {mid}: {e}")
            finally:
                _db.close()
        except Exception as e:
            print(f"[portfolio reindex] Erro geral: {e}")

    background_tasks.add_task(_do_reindex)
    return {"ok": True, "reindexed": len(material_ids), "queued": True}


# ─── PORTFOLIO SUMMARY (para agent) ──────────────────────────────────────────

@router.get("/{portfolio_id}/summary")
async def portfolio_summary(
    portfolio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resumo estruturado da carteira para uso pelo agente/sistema."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Carteira não encontrada")

    members = (
        db.query(PortfolioProduct, Product)
        .join(Product, Product.id == PortfolioProduct.product_id)
        .filter(PortfolioProduct.portfolio_id == portfolio_id)
        .all()
    )

    member_list = []
    for pp, prod in members:
        key_info = {}
        if prod.key_info:
            try:
                key_info = json.loads(prod.key_info)
            except Exception:
                pass
        member_list.append({
            "product_id": prod.id,
            "name": prod.name,
            "ticker": prod.ticker,
            "product_type": prod.product_type,
            "key_info": key_info,
        })

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "portfolio_type": portfolio.portfolio_type,
        "description": portfolio.description,
        "is_active": portfolio.is_active,
        "members": member_list,
        "members_count": len(member_list),
    }
