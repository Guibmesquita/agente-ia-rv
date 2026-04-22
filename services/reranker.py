"""
LLM Reranker (Task #152) — re-ordena top-K candidatos do RAG usando GPT-4o-mini.

Atrás de feature flag `RAG_USE_RERANKER` (default desligado para preservar latência).
Quando ligado, recebe a query e até K candidatos (com snippet de conteúdo + metadados
mínimos) e retorna a permutação de IDs ordenada por relevância. O reranker faz uma
chamada única ao modelo, com prompt determinístico e temperature=0.

Falhas (timeout, JSON inválido, modelo indisponível) caem silenciosamente para a
ordenação composta original — nunca devem quebrar a busca.
"""
import json
import os
import time
from typing import Any, List, Optional

_DEFAULT_MODEL = os.getenv("RAG_RERANKER_MODEL", "gpt-4o-mini")
_DEFAULT_TIMEOUT = float(os.getenv("RAG_RERANKER_TIMEOUT", "8.0"))
_MAX_SNIPPET_CHARS = 480


def is_enabled() -> bool:
    """Retorna True se o reranker estiver ativado via env."""
    val = os.getenv("RAG_USE_RERANKER", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _result_id(r: Any) -> Optional[str]:
    try:
        if hasattr(r, "metadata"):
            md = r.metadata or {}
        elif isinstance(r, dict):
            md = r.get("metadata") or {}
        else:
            return None
        bid = md.get("block_id")
        return str(bid) if bid is not None else None
    except Exception:
        return None


def _result_snippet(r: Any) -> str:
    try:
        if hasattr(r, "content"):
            content = r.content or ""
        elif isinstance(r, dict):
            content = r.get("content") or ""
        else:
            content = ""
        snippet = content.strip().replace("\n", " ")
        if len(snippet) > _MAX_SNIPPET_CHARS:
            snippet = snippet[:_MAX_SNIPPET_CHARS] + "…"
        return snippet
    except Exception:
        return ""


def _result_meta_brief(r: Any) -> str:
    try:
        md = r.metadata if hasattr(r, "metadata") else (r.get("metadata") or {})
    except Exception:
        return ""
    parts: List[str] = []
    for key in ("product_ticker", "product_name", "block_type", "material_name"):
        v = md.get(key)
        if v:
            parts.append(f"{key}={v}")
    return " | ".join(parts)


def rerank(
    query: str,
    candidates: List[Any],
    top_k: Optional[int] = None,
    model: Optional[str] = None,
) -> List[Any]:
    """
    Reordena `candidates` por relevância à `query`. Retorna a mesma lista de
    objetos, na nova ordem. Se algo falhar, retorna `candidates` inalterado.
    """
    if not candidates or len(candidates) < 2:
        return candidates

    try:
        from openai import OpenAI
    except Exception:
        return candidates

    if not os.getenv("OPENAI_API_KEY"):
        return candidates

    items = []
    id_to_obj = {}
    for i, c in enumerate(candidates):
        rid = _result_id(c) or f"idx_{i}"
        if rid in id_to_obj:
            rid = f"{rid}#{i}"
        id_to_obj[rid] = c
        items.append({
            "id": rid,
            "meta": _result_meta_brief(c),
            "snippet": _result_snippet(c),
        })

    sys_prompt = (
        "Você é um reranker de RAG financeiro. Receberá uma consulta e uma lista de "
        "candidatos com snippet e metadados. Retorne APENAS um JSON com a chave "
        '"order" contendo a lista de ids ordenada do mais relevante ao menos '
        "relevante. Não inclua texto fora do JSON. Considere correspondência de "
        "ticker/produto, presença de números/tabelas pedidos pela consulta, e "
        "frescor do material quando explícito."
    )
    user_payload = {
        "query": query,
        "candidates": items,
    }

    try:
        client = OpenAI(timeout=_DEFAULT_TIMEOUT)
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model or _DEFAULT_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        elapsed = (time.time() - t0) * 1000
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        order = data.get("order") or []
        if not isinstance(order, list):
            return candidates

        ranked: List[Any] = []
        seen = set()
        for rid in order:
            srid = str(rid)
            if srid in id_to_obj and srid not in seen:
                ranked.append(id_to_obj[srid])
                seen.add(srid)
        for rid, obj in id_to_obj.items():
            if rid not in seen:
                ranked.append(obj)

        print(f"[RERANKER] {len(candidates)} candidatos reordenados em {elapsed:.0f}ms")
        if top_k:
            return ranked[:top_k]
        return ranked
    except Exception as e:
        print(f"[RERANKER] Falha (mantendo ordem original): {e}")
        return candidates
