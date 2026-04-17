"""
Indexador de key_info de produtos no vector store.

Cria um documento sintético por produto na tabela `document_embeddings` contendo
as informações estratégicas extraídas pelo SmartUpload (tese, retorno, prazo,
risco, gestor, rating, mínimo, liquidez, highlights). Esse documento é tratado
como uma "Ficha do Produto" e fica disponível para o agente Stevan via
`search_knowledge_base`, mesmo que o produto NÃO esteja no Comitê SVN ativo.

doc_id usado: `product_keyinfo_{product_id}`
block_type:   `product_key_info`
material_name: "Ficha do Produto"
"""
import json
from typing import Optional, Dict, Any

from database.models import Product
from services.vector_store import get_vector_store


KEY_INFO_TEXT_FIELDS = [
    ("investment_thesis", "Tese de investimento"),
    ("expected_return", "Retorno esperado"),
    ("investment_term", "Prazo / horizonte"),
    ("main_risk", "Principal risco"),
    ("issuer_or_manager", "Emissor / Gestor"),
    ("rating", "Rating"),
    ("minimum_investment", "Investimento mínimo"),
    ("liquidity", "Liquidez"),
]

KEY_INFO_IDENTITY_FIELDS = [
    ("cnpj", "CNPJ"),
    ("underlying_ticker", "Ativo subjacente"),
]


def _parse_key_info(raw) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _has_meaningful_content(key_info: Dict[str, Any]) -> bool:
    """Há ao menos um campo textual ou um highlight preenchido."""
    if not isinstance(key_info, dict):
        return False
    for field, _ in KEY_INFO_TEXT_FIELDS + KEY_INFO_IDENTITY_FIELDS:
        v = key_info.get(field)
        if isinstance(v, str) and v.strip():
            return True
    hl = key_info.get("additional_highlights")
    if isinstance(hl, list) and any(isinstance(x, str) and x.strip() for x in hl):
        return True
    return False


def build_key_info_narrative(product: Product, key_info: Dict[str, Any]) -> str:
    """
    Monta o texto narrativo que será embutido como documento na base vetorial.
    """
    name = product.name or ""
    ticker = (product.ticker or "").upper()
    header = f"Ficha do Produto — {name}"
    if ticker:
        header += f" ({ticker})"

    parts = [header]
    parts.append(
        "Resumo das informações estratégicas registradas internamente "
        "pela equipe da SVN sobre este produto. Estas informações foram "
        "extraídas dos materiais oficiais e/ou validadas manualmente por "
        "gestores e brokers."
    )

    for field, label in KEY_INFO_TEXT_FIELDS:
        val = key_info.get(field)
        if isinstance(val, str) and val.strip():
            parts.append(f"{label}: {val.strip()}")

    for field, label in KEY_INFO_IDENTITY_FIELDS:
        val = key_info.get(field)
        if isinstance(val, str) and val.strip():
            parts.append(f"{label}: {val.strip()}")

    highlights = key_info.get("additional_highlights")
    if isinstance(highlights, list):
        cleaned = [h.strip() for h in highlights if isinstance(h, str) and h.strip()]
        if cleaned:
            parts.append("Destaques adicionais:")
            for h in cleaned:
                parts.append(f"- {h}")

    return "\n".join(parts)


def index_product_key_info(product: Product) -> bool:
    """
    Indexa (ou atualiza) o documento sintético de key_info do produto.

    Returns:
        True se indexou; False se nada a indexar (key_info vazio) — nesse
        caso também REMOVE qualquer documento existente.
    """
    if not product or not getattr(product, "id", None):
        return False

    vs = get_vector_store()
    if not vs:
        return False

    key_info = _parse_key_info(getattr(product, "key_info", None))
    doc_id = f"product_keyinfo_{product.id}"

    if not _has_meaningful_content(key_info):
        try:
            vs.delete_document(doc_id)
        except Exception:
            pass
        return False

    text = build_key_info_narrative(product, key_info)
    ticker = (product.ticker or "").upper()
    name = product.name or ""

    metadata = {
        "doc_type": "product_key_info",
        "type": "product_key_info",
        "block_type": "product_key_info",
        "title": f"Ficha do Produto — {name}",
        "source": "Ficha do Produto (SVN)",
        "product_name": name,
        "product_ticker": ticker,
        "products": ticker or name.upper(),
        "product_id": product.id,
        "material_name": "Ficha do Produto",
        "material_type": "ficha_produto",
        "publish_status": "publicado",
        "is_committee": bool(getattr(product, "is_committee", False)),
        "gestora": product.manager or "",
    }

    try:
        vs.add_document(doc_id=doc_id, text=text, metadata=metadata)
        print(
            f"[KEY_INFO_INDEX] Produto id={product.id} ({ticker or name}) "
            f"indexado como {doc_id}"
        )
        return True
    except Exception as e:
        print(f"[KEY_INFO_INDEX] Erro ao indexar produto id={product.id}: {e}")
        return False


def delete_product_key_info_index(product_id: int) -> bool:
    """Remove o documento sintético de key_info do vector store."""
    if not product_id:
        return False
    vs = get_vector_store()
    if not vs:
        return False
    try:
        return vs.delete_document(f"product_keyinfo_{product_id}")
    except Exception:
        return False


def backfill_all(db) -> Dict[str, int]:
    """
    Reindexação idempotente para todos os produtos com key_info populado.
    """
    indexed = 0
    skipped = 0
    errors = 0
    products = db.query(Product).all()
    for p in products:
        try:
            ok = index_product_key_info(p)
            if ok:
                indexed += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            print(f"[KEY_INFO_INDEX][BACKFILL] Erro produto id={p.id}: {e}")
    print(
        f"[KEY_INFO_INDEX][BACKFILL] Concluído. "
        f"Indexados: {indexed} | Sem conteúdo: {skipped} | Erros: {errors}"
    )
    return {"indexed": indexed, "skipped": skipped, "errors": errors, "total": len(products)}
