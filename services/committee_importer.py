"""
Serviço de extração GPT para importação automática de recomendações do Comitê a partir de materiais.
Lê ContentBlocks de um material e usa GPT-4o-mini para identificar produtos com rating,
preço-alvo, vigência e racional. Resolve cada produto contra a tabela products.
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """Você é um assistente especializado em extrair recomendações formais de investimento de documentos financeiros.

Dado o conteúdo de um relatório do Comitê de Investimentos, extraia TODAS as recomendações de produtos financeiros mencionadas.

Para cada produto recomendado, extraia:
- ticker: código do ativo (ex: MXRF11, PETR4, HGLG11). Se não houver ticker explícito, use null.
- nome: nome completo do fundo ou ativo (ex: "Maxi Renda FII", "Petrobras PN")
- rating: classificação da recomendação. Mapeie para exatamente um de: "Compra", "Manutenção", "Venda". Se não identificado, use null.
- preco_alvo: preço-alvo numérico (apenas o número, ex: 12.50). Se não mencionado, use null.
- vigencia: data de vigência no formato YYYY-MM-DD. Se não mencionada, use null.
- racional: justificativa ou tese de investimento resumida (máx 300 caracteres). Se não houver, use null.

Regras:
1. Inclua APENAS produtos com recomendação explícita (Compra/Manutenção/Venda ou equivalentes como "Adicionar", "Manter", "Reduzir").
2. Ignore menções informativas sem recomendação.
3. Se o mesmo produto aparecer múltiplas vezes, use a informação mais recente/completa.
4. Responda APENAS com um JSON válido no formato abaixo, sem texto adicional.

Formato de resposta:
{
  "recommendations": [
    {
      "ticker": "MXRF11",
      "nome": "Maxi Renda FII",
      "rating": "Compra",
      "preco_alvo": 12.50,
      "vigencia": "2025-12-31",
      "racional": "FII com DY consistente e gestão ativa..."
    }
  ]
}
"""


def _extract_text_from_blocks(blocks) -> str:
    """Concatena o conteúdo textual dos ContentBlocks para enviar ao GPT."""
    parts = []
    for block in blocks:
        if not block.content:
            continue
        content = block.content.strip()
        if not content:
            continue
        if block.block_type in ('table', 'tabular') or (content.startswith('{') and content.startswith('[')):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and 'headers' in parsed and 'rows' in parsed:
                    headers = parsed.get('headers', [])
                    rows = parsed.get('rows', [])
                    table_text = ' | '.join(str(h) for h in headers) + '\n'
                    for row in rows[:50]:
                        if isinstance(row, list):
                            table_text += ' | '.join(str(v) for v in row) + '\n'
                        elif isinstance(row, dict):
                            table_text += ' | '.join(str(v) for v in row.values()) + '\n'
                    content = table_text
            except (json.JSONDecodeError, TypeError):
                pass
        if block.title:
            parts.append(f"[{block.title}]\n{content}")
        else:
            parts.append(content)
    return '\n\n'.join(parts)


def _resolve_product(db: Session, ticker: Optional[str], nome: Optional[str]):
    """
    Resolve um produto identificado pelo GPT para um registro na tabela products.
    Estratégia: ticker exact → name ILIKE → alias.
    Retorna (product, match_type) ou (None, None).
    """
    from database.models import Product

    if ticker:
        ticker_clean = ticker.strip().upper()
        p = db.query(Product).filter(
            Product.ticker.ilike(ticker_clean),
            Product.status == 'ativo'
        ).first()
        if p:
            return p, 'ticker_exact'

    if nome and len(nome.strip()) >= 3:
        nome_clean = nome.strip()
        p = db.query(Product).filter(
            Product.name.ilike(f"%{nome_clean}%"),
            Product.status == 'ativo'
        ).first()
        if p:
            return p, 'name_ilike'

        all_products = db.query(Product).filter(Product.status == 'ativo').all()
        nome_lower = nome_clean.lower()
        for prod in all_products:
            try:
                aliases = json.loads(prod.name_aliases or "[]")
            except (json.JSONDecodeError, TypeError):
                aliases = []
            for alias in aliases:
                if nome_lower in alias.lower() or alias.lower() in nome_lower:
                    return prod, 'alias'

    return None, None


def extract_committee_from_material(db: Session, material_id: int) -> list:
    """
    Extrai recomendações do Comitê de um material pelo ID.

    Returns:
        Lista de dicts com:
        - ticker: ticker extraído pelo GPT
        - nome: nome extraído pelo GPT
        - rating: rating extraído (Compra/Manutenção/Venda ou None)
        - target_price: preço-alvo numérico ou None
        - valid_until: data de vigência (datetime) ou None
        - rationale: justificativa ou None
        - product_id: ID do produto no banco (se resolvido)
        - product_name: nome do produto no banco (se resolvido)
        - product_ticker: ticker do produto no banco (se resolvido)
        - unresolved: True se não foi possível mapear para um produto cadastrado
        - already_in_committee: True se o produto já tem recomendação ativa
        - match_type: tipo de match usado (ticker_exact/name_ilike/alias/null)
    """
    from database.models import Material, ContentBlock, RecommendationEntry
    from openai import OpenAI
    import os

    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise ValueError(f"Material id={material_id} não encontrado")

    blocks = db.query(ContentBlock).filter(
        ContentBlock.material_id == material_id
    ).order_by(ContentBlock.order, ContentBlock.id).all()

    if not blocks:
        logger.info(f"[committee_importer] Material {material_id} não tem ContentBlocks extraídos")
        return []

    full_text = _extract_text_from_blocks(blocks)

    MAX_CHARS = 30000
    if len(full_text) > MAX_CHARS:
        full_text = full_text[:MAX_CHARS] + "\n\n[... conteúdo truncado ...]"

    if not full_text.strip():
        return []

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada")

    client = OpenAI(api_key=api_key)

    logger.info(f"[committee_importer] Enviando {len(full_text)} chars para GPT extrair recomendações do material {material_id}")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Conteúdo do documento:\n\n{full_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4000,
        )
    except Exception as e:
        logger.error(f"[committee_importer] Erro na chamada GPT: {e}")
        raise RuntimeError(f"Erro ao chamar GPT: {str(e)}")

    raw_json = response.choices[0].message.content
    try:
        parsed = json.loads(raw_json)
        recommendations_raw = parsed.get("recommendations", [])
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"[committee_importer] Resposta GPT inválida: {raw_json[:200]}")
        raise RuntimeError("GPT retornou resposta malformada")

    now = datetime.utcnow()
    result = []
    seen_product_ids = set()

    for rec in recommendations_raw:
        ticker = rec.get("ticker") or None
        nome = rec.get("nome") or None
        rating = rec.get("rating") or None
        preco_alvo_raw = rec.get("preco_alvo")
        vigencia_raw = rec.get("vigencia")
        racional = rec.get("racional") or None

        if not ticker and not nome:
            continue

        if rating and rating not in ("Compra", "Manutenção", "Venda"):
            rating = None

        target_price = None
        if preco_alvo_raw is not None:
            try:
                target_price = float(preco_alvo_raw)
            except (ValueError, TypeError):
                pass

        valid_until = None
        if vigencia_raw:
            try:
                valid_until = datetime.strptime(str(vigencia_raw)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        product, match_type = _resolve_product(db, ticker, nome)

        if product and product.id in seen_product_ids:
            continue
        if product:
            seen_product_ids.add(product.id)

        already_in_committee = False
        if product:
            active_entry = db.query(RecommendationEntry).filter(
                RecommendationEntry.product_id == product.id,
                RecommendationEntry.is_active == True,
            ).filter(
                (RecommendationEntry.valid_until == None) |
                (RecommendationEntry.valid_until >= now)
            ).first()
            already_in_committee = active_entry is not None

        result.append({
            "ticker": ticker,
            "nome": nome,
            "rating": rating,
            "target_price": target_price,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "rationale": racional,
            "product_id": product.id if product else None,
            "product_name": product.name if product else None,
            "product_ticker": product.ticker if product else None,
            "unresolved": product is None,
            "already_in_committee": already_in_committee,
            "match_type": match_type,
        })

    logger.info(f"[committee_importer] Extraídas {len(result)} recomendações do material {material_id} ({sum(1 for r in result if not r['unresolved'])} resolvidas)")
    return result
