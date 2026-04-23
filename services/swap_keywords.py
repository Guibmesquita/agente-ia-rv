"""Fonte única da verdade para palavras-chave que indicam que um material/produto
descreve uma OPERAÇÃO DE TROCA / SWAP / ROTAÇÃO entre dois ou mais ativos.

Diferente de uma estrutura (POP/Collar/Fence — derivativo sobre 1 ativo),
uma "troca" é uma RECOMENDAÇÃO TÁTICA de substituir o ativo A pelo ativo B
(ou rebalancear de A→B). O material descreve a operação inteira como
PRODUTO próprio, e NÃO deve ser vinculado às fichas de A nem de B
individualmente — isso fragmenta a recomendação no RAG e o agente passa a
citar a troca como se fosse análise isolada de cada ativo.

Esta lista é consumida por:
  - `api/endpoints/products.py::_match_products_to_db` (pré-análise)
  - `api/endpoints/products.py::link_products_and_queue` (confirmação)
  - `services/upload_queue.py::UploadQueue._auto_create_product` (worker)
  - `frontend/react-knowledge/src/pages/SmartUpload.jsx` (UI badge)

Keywords são propositalmente ESPECÍFICAS — palavras genéricas como
"mudança" foram evitadas para não casar com "mudança de cenário",
"mudança de gestão" etc. A busca sempre é feita com `\\b...\\b`
(palavra inteira) e case-insensitive.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

SWAP_KEYWORDS: Tuple[str, ...] = (
    "swap",
    "troca",
    "trocar",
    "rotação",
    "rotacao",
    "substituição",
    "substituicao",
    "substituir",
    "pair trade",
    "pairs trade",
    "pairs trading",
    "long short",
    "long-short",
    "rebalanceamento",
)


def find_swap_keyword(*texts: Optional[str],
                      keywords: Iterable[str] = SWAP_KEYWORDS) -> Optional[str]:
    """Retorna a primeira keyword de swap encontrada nos textos
    (case-insensitive, palavra inteira), ou None se nenhuma casar.

    Aceita múltiplos textos (filename, material.name, fund_name,
    document_type, ai_product_type, ...) e os concatena antes da busca.

    Além das keywords diretas, detecta o padrão tático "VENDER … COMPRAR"
    (ambas as palavras presentes no mesmo texto), que indica claramente uma
    operação de troca entre dois ativos (e.g. "VENDER_MXRF11_COMPRAR_MCCE11").
    "vender" e "comprar" isoladamente são genéricas demais para entrar nos
    SWAP_KEYWORDS, mas a presença SIMULTÂNEA de ambas é diagnóstica.
    """
    raw = " ".join(t for t in texts if t).lower()
    if not raw:
        return None
    # Normaliza underscores → espaços antes do regex com \b, pois "_" é
    # caractere de palavra e impede \b de separar "troca" em "troca_petr4".
    joined = raw.replace("_", " ")
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", joined):
            return kw
    # Padrão especial: "vender" E "comprar" ambos presentes → troca tática
    if re.search(r"\bvender\b", joined) and re.search(r"\bcomprar\b", joined):
        return "vender+comprar"
    return None


__all__ = ["SWAP_KEYWORDS", "find_swap_keyword"]
