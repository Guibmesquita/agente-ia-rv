"""Fonte única da verdade para palavras-chave que indicam que um material/produto
é uma estrutura de Renda Variável (POP, Collar, Fence, etc.).

Antes desta unificação havia duas listas divergentes:
  - `_STRUCTURE_KEYWORDS` em `services/upload_queue.py` (worker)
  - `_STRUCTURE_KEYWORDS_AI` / `_STRUCTURE_KEYWORDS_CONFIRM` em
    `api/endpoints/products.py` (link-and-queue / confirm)

Termos como "booster", "seagull", "reverse convertible", "knock-out" estavam
apenas nos endpoints, fazendo com que o worker e o endpoint discordassem sobre
o tipo do mesmo material. Esta lista é o conjunto unificado consumido por
todos os pontos de detecção.

Keywords são propositalmente ESPECÍFICAS — termos genéricos como
"estrutura"/"estruturado" sem qualificador foram evitados para não casar com
"estrutura de capital", "estrutura a termo de juros" etc. A busca sempre é
feita com `\\b...\\b` (palavra inteira) e case-insensitive.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

STRUCTURE_KEYWORDS: Tuple[str, ...] = (
    # Siglas / nomes específicos de estruturas
    "pop", "collar", "fence", "booster", "seagull",
    "put spread", "call spread", "put/call spread",
    "worst of", "worst-of", "worst/of",
    "coe", "strangle", "straddle",
    "borboleta", "butterfly",
    "trava de alta", "trava de baixa",
    "reverse convertible", "knock-out", "knock out",
    # Termos qualificados (sempre acompanhados de substantivo) — seguros
    "estruturada", "estruturado",
    "operação estruturada", "produto estruturado", "nota estruturada",
)


def find_structure_keyword(*texts: Optional[str],
                           keywords: Iterable[str] = STRUCTURE_KEYWORDS) -> Optional[str]:
    """Retorna a primeira keyword de estrutura encontrada nos textos (case-insensitive,
    palavra inteira), ou None se nenhuma casar.

    Aceita múltiplos textos (filename, material.name, fund_name, document_type, ...)
    e os concatena antes da busca.
    """
    raw = " ".join(t for t in texts if t).lower()
    if not raw:
        return None
    # Normaliza underscores → espaços antes do regex com \b, pois "_" é
    # caractere de palavra e impede \b de separar "pop" em "pop_mypk3".
    joined = raw.replace("_", " ")
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", joined):
            return kw
    return None


__all__ = ["STRUCTURE_KEYWORDS", "find_structure_keyword"]
