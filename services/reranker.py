"""
LLM Reranker (Task #152) — re-ordena top-K candidatos do RAG usando GPT-4o-mini.

Atrás de feature flag `RAG_USE_RERANKER` (default desligado para preservar latência).
Quando ligado, recebe a query e até K candidatos (com snippet de conteúdo + metadados
mínimos) e retorna a permutação de IDs ordenada por relevância. O reranker faz uma
chamada única ao modelo, com prompt determinístico e temperature=0.

Falhas (timeout, JSON inválido, modelo indisponível) caem silenciosamente para a
ordenação composta original — nunca devem quebrar a busca.
"""
import hashlib
import json
import os
import time
from typing import Any, List, Optional, Tuple

_DEFAULT_MODEL = os.getenv("RAG_RERANKER_MODEL", "gpt-4o-mini")
_DEFAULT_TIMEOUT = float(os.getenv("RAG_RERANKER_TIMEOUT", "8.0"))
_MAX_SNIPPET_CHARS = 480

# Task #153 — cache em memória do reranker, chaveado por (query+ids).
# TTL curto (turno único) evita re-cobrar o LLM quando o agente roda múltiplas
# tools no mesmo loop e a busca volta pelo mesmo conjunto. Cap de 256 entradas.
_CACHE_TTL_SECONDS = float(os.getenv("RAG_RERANKER_CACHE_TTL", "120"))
_CACHE_MAX = 256
_RERANKER_CACHE: dict = {}


def _cache_key(query: str, candidate_ids: List[str], model: str) -> str:
    h = hashlib.sha256()
    h.update((model or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((query or "").strip().lower().encode("utf-8"))
    h.update(b"\x00")
    for cid in candidate_ids:
        h.update(str(cid).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


def _cache_get(key: str) -> Optional[List[str]]:
    item = _RERANKER_CACHE.get(key)
    if not item:
        return None
    ts, order = item
    if time.time() - ts > _CACHE_TTL_SECONDS:
        _RERANKER_CACHE.pop(key, None)
        return None
    return order


def _cache_set(key: str, order: List[str]) -> None:
    if len(_RERANKER_CACHE) >= _CACHE_MAX:
        oldest = min(_RERANKER_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _RERANKER_CACHE.pop(oldest, None)
    _RERANKER_CACHE[key] = (time.time(), order)


def is_enabled() -> bool:
    """
    Retorna True se o reranker estiver ativado via env.
    Default = ON (Task #152). Defina `RAG_USE_RERANKER=0` para desligar.
    """
    val = os.getenv("RAG_USE_RERANKER", "1").strip().lower()
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
    # Task #153 — product_type entra na metadata vista pelo reranker para
    # diferenciar ação x estruturada quando ambas pertencem ao mesmo underlying.
    for key in ("product_ticker", "product_name", "product_type", "block_type", "material_name"):
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
    ordered_ids: List[str] = []
    for i, c in enumerate(candidates):
        rid = _result_id(c) or f"idx_{i}"
        if rid in id_to_obj:
            rid = f"{rid}#{i}"
        id_to_obj[rid] = c
        ordered_ids.append(rid)
        items.append({
            "id": rid,
            "meta": _result_meta_brief(c),
            "snippet": _result_snippet(c),
        })

    # Task #153 — cache hit retorna sem chamar o LLM.
    model_name = model or _DEFAULT_MODEL
    ckey = _cache_key(query, ordered_ids, model_name)
    cached_order = _cache_get(ckey)
    if cached_order:
        ranked: List[Any] = []
        seen = set()
        for rid in cached_order:
            if rid in id_to_obj and rid not in seen:
                ranked.append(id_to_obj[rid])
                seen.add(rid)
        for rid, obj in id_to_obj.items():
            if rid not in seen:
                ranked.append(obj)
        print(f"[RERANKER] cache hit: {len(candidates)} candidatos reusados sem chamada LLM")
        if top_k:
            return ranked[:top_k]
        return ranked

    sys_prompt = (
        "Você é um reranker de RAG financeiro. Receberá uma consulta e uma lista de "
        "candidatos com snippet e metadados. Retorne APENAS um JSON com a chave "
        '"order" contendo a lista de ids ordenada do mais relevante ao menos '
        "relevante. Não inclua texto fora do JSON.\n\n"
        "REGRAS DE PRIORIZAÇÃO (em ordem):\n"
        "1) Match EXATO de ticker (ex.: query menciona 'GARE11' e o candidato tem "
        "product_ticker=GARE11) deve ficar acima de matches parciais ou semânticos.\n"
        "2) Quando a query pergunta por um número/métrica específico (DY, P/VP, taxa, "
        "preço-alvo, custo, prazo, valor de cota, AUM), candidatos com block_type que "
        "contém 'table' ou cujo snippet exibe a métrica numérica explicitamente "
        "DEVEM vir no topo.\n"
        "3) Se a query menciona um tipo de produto (ex.: 'estruturada', 'put spread', "
        "'call', 'fii', 'ação'), priorize candidatos com product_type compatível. "
        "Estrutura/derivativo e ativo subjacente NÃO são equivalentes — não os trate "
        "como sinônimos.\n"
        "4) Frescor do material quando a query for temporal ('última', 'recente', "
        "'agora').\n"
        "5) Em empate, mantenha a ordem original."
    )
    user_payload = {
        "query": query,
        "candidates": items,
    }

    try:
        client = OpenAI(timeout=_DEFAULT_TIMEOUT)
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model_name,
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

        ranked = []
        seen = set()
        normalized_order: List[str] = []
        for rid in order:
            srid = str(rid)
            if srid in id_to_obj and srid not in seen:
                ranked.append(id_to_obj[srid])
                seen.add(srid)
                normalized_order.append(srid)
        for rid, obj in id_to_obj.items():
            if rid not in seen:
                ranked.append(obj)
                normalized_order.append(rid)

        # Task #153 — guarda ordem completa para futuro cache hit.
        try:
            _cache_set(ckey, normalized_order)
        except Exception:
            pass

        print(f"[RERANKER] {len(candidates)} candidatos reordenados em {elapsed:.0f}ms")
        if top_k:
            return ranked[:top_k]
        return ranked
    except Exception as e:
        print(f"[RERANKER] Falha (mantendo ordem original): {e}")
        return candidates
