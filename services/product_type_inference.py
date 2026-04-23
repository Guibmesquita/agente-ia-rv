"""
Helper centralizado para inferência e normalização de `Product.product_type`.

Compartilhado entre:
- `api/endpoints/products.py` (criação manual e fluxos de auto-criação)
- `scripts/backfill_product_types.py` (migração de dados)
- `scripts/audit_product_types.py` (auditoria)

Mantém uma única fonte de verdade para a heurística, evitando que o conjunto
canônico ou as regras divirjam entre o endpoint e os scripts.
"""

from __future__ import annotations

import re
from typing import Optional

VALID_PRODUCT_TYPES: set[str] = {
    "acao",
    "estruturada",
    "swap",
    "fundo",
    "fii",
    "etf",
    "debenture",
    "outro",
}

PRODUCT_TYPE_ALIASES: dict[str, str] = {
    "ação": "acao",
    "acao": "acao",
    "ações": "acao",
    "acoes": "acao",
    "stock": "acao",
    "equity": "acao",
    "fii": "fii",
    "fundo imobiliário": "fii",
    "fundo imobiliario": "fii",
    "imobiliário": "fii",
    "imobiliario": "fii",
    "etf": "etf",
    "index": "etf",
    "debênture": "debenture",
    "debenture": "debenture",
    "cri": "debenture",
    "cra": "debenture",
    "fundo": "fundo",
    "fundo de investimento": "fundo",
    "multimercado": "fundo",
    "estruturada": "estruturada",
    "estrutura": "estruturada",
    "estruturado": "estruturada",
    "derivativo": "estruturada",
    "pop": "estruturada",
    "collar": "estruturada",
    "coe": "estruturada",
    # Troca / swap / pair trade — categoria própria a partir da Task #170.
    # Antes era mapeada para 'estruturada', mas semanticamente é uma
    # recomendação tática (substituir A por B), não um derivativo.
    "swap": "swap",
    "troca": "swap",
    "trocar": "swap",
    "rotação": "swap",
    "rotacao": "swap",
    "substituição": "swap",
    "substituicao": "swap",
    "substituir": "swap",
    "pair trade": "swap",
    "pairs trade": "swap",
    "pairs trading": "swap",
    "long short": "swap",
    "long-short": "swap",
    "rebalanceamento": "swap",
    "outro": "outro",
    "outros": "outro",
}

_TICKER_FII_RE = re.compile(r"^[A-Z]{4}1[12]$")
_TICKER_ACAO_RE = re.compile(r"^[A-Z]{4}[3-6]$")
_TICKER_BDR_RE = re.compile(r"^[A-Z]{4}11B$")


def normalize_product_type(value: Optional[str]) -> Optional[str]:
    """Mapeia um valor livre para o conjunto canônico, ou retorna None se não reconhecido."""
    if not value:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if v in VALID_PRODUCT_TYPES:
        return v
    return PRODUCT_TYPE_ALIASES.get(v)


def infer_product_type(
    ticker: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Infere o `product_type` canônico a partir de ticker/nome/descrição.

    Sempre retorna um valor de `VALID_PRODUCT_TYPES` — recorre a 'outro' como
    fallback explícito quando nenhuma heurística casa.
    """
    t = (ticker or "").strip().upper()
    n = (name or "").strip().lower()
    d = (description or "").strip().lower()
    blob = f"{n} {d}"

    # Override óbvio por nome/descrição antes do padrão de ticker:
    # tickers terminando em 11/12 normalmente são FIIs, mas alguns ETFs
    # também usam esse sufixo (ex.: BOVA11). Confiamos no nome quando há
    # indicação explícita de ETF/Index.
    if re.search(r"\b(etf|index)\b", blob):
        return "etf"

    if t:
        if _TICKER_FII_RE.match(t):
            return "fii"
        if _TICKER_BDR_RE.match(t):
            return "acao"
        if _TICKER_ACAO_RE.match(t):
            return "acao"

    if re.search(r"\b(fii|fundo imobili[áa]rio|imobili[áa]rio)\b", blob):
        return "fii"
    if re.search(r"\b(deb[êe]nture|cra|cri)\b", blob):
        return "debenture"
    # Swap / troca / pair trade — checar ANTES de estruturada porque o termo
    # "swap" historicamente caía em estruturada e perdia a semântica de troca.
    if re.search(
        r"\b(swap|troca|trocar|rota[çc][ãa]o|substitui[çc][ãa]o|substituir|"
        r"pair[- ]?trad\w*|long[- ]?short|rebalanceamento)\b",
        blob,
    ):
        return "swap"
    if re.search(r"\b(pop|collar|coe|estruturad\w*|derivativo)\b", blob):
        return "estruturada"
    if re.search(r"\b(fundo|multimercado)\b", blob):
        return "fundo"

    return "outro"


def coerce_product_type(
    raw: Optional[str] = None,
    *,
    ticker: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Garante um `product_type` canônico para fluxos de auto-criação.

    1. Se `raw` já for válido (após normalização de alias), usa esse valor.
    2. Caso contrário, infere a partir de ticker/nome/descrição (fallback 'outro').
    """
    norm = normalize_product_type(raw)
    if norm:
        return norm
    return infer_product_type(ticker=ticker, name=name, description=description)
