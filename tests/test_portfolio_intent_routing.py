"""Task #204 — testes do roteamento de intenção de portfólio.

Cobertura:
  1. `TokenExtractor.detect_portfolio_intent` — positivos e negativos.
  2. `vector_store.search_by_portfolio` — exaustividade dos `portfolio_row`
     mesmo quando `n_results < N` (sem cap em linhas de carteira).
  3. `_compact_tool_payload` — modo de preservação:
     `_portfolio_preserve_mode=True` impede descarte de `portfolio_row`
     mesmo sob pressão de cap, descartando apenas auxiliares.

Os testes usam fixtures sintéticas (sem dependência de OpenAI/DB) e
mockam o `SessionLocal` apenas onde necessário.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from services.semantic_search import TokenExtractor
from services.openai_agent import _compact_tool_payload


# ---------------------------------------------------------------------------
# 1) detect_portfolio_intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query,expected",
    [
        # Positivos: variações comuns
        ("liste os FIIs da carteira Seven", True),
        ("qual a composição da carteira recomendada", True),
        ("composicao da carteira", True),
        ("quais ativos estão na carteira do mês", True),
        ("mostre o portfólio recomendado", True),
        ("alocação dos FIIs da carteira", True),
        ("rebalanceamento da carteira de abril", True),
        # Negativos: queries pontuais sobre 1 ticker, sem keyword de carteira
        ("me fale sobre TVRI11", False),
        ("qual o preço atual de PETR4?", False),
        ("o que é dividend yield", False),
        ("explique o que é um FII", False),
    ],
)
def test_detect_portfolio_intent(query: str, expected: bool) -> None:
    assert TokenExtractor.detect_portfolio_intent(query) is expected


# ---------------------------------------------------------------------------
# 2) search_by_portfolio — exaustividade dos portfolio_row
# ---------------------------------------------------------------------------

class _FakeBlock:
    """Stub mínimo de ContentBlock para mockar a query do search_by_portfolio."""
    def __init__(self, bid, mid, block_type, content, page=3, title=""):
        self.id = bid
        self.material_id = mid
        self.block_type = block_type
        self.content = content
        self.source_page = page
        self.title = title
        self.status = "publicado"


class _FakeMaterial:
    def __init__(self, mid, name, product_id, product=None):
        self.id = mid
        self.name = name
        self.product_id = product_id
        self.material_type = "carteira"
        self.publish_status = "publicado"
        self.source_file_path = "/tmp/x.pdf"
        # Relacionamento ORM: vector_store acessa `mat.product.name` no
        # texto descritivo do material (linha ~1444).
        self.product = product


class _FakeProduct:
    def __init__(self, pid, name, product_type="carteira", ticker=None):
        self.id = pid
        self.name = name
        self.product_type = product_type
        self.ticker = ticker


def _make_search_by_portfolio_db(num_rows: int):
    """Cria um db mock que devolve 1 carteira com `num_rows` portfolio_row +
    1 financial_table + 5 textos auxiliares."""
    prod = _FakeProduct(pid=47, name="Carteira Seven FII's", product_type="carteira")
    mat = _FakeMaterial(mid=47, name="Carteira Seven FIIs Abril", product_id=47, product=prod)
    blocks = []
    # portfolio_rows
    for i in range(num_rows):
        ticker = f"FII{i:02d}11"
        blocks.append(_FakeBlock(
            bid=1000 + i, mid=47, block_type="portfolio_row",
            content=(f"[CARTEIRA Seven] {ticker}: Ticker={ticker}; "
                     f"Peso={(100 / num_rows):.2f}%; Setor=Logística"),
            title=f"Linha de carteira — {ticker} (Página 3)",
        ))
    # 1 financial_table
    blocks.append(_FakeBlock(
        bid=2000, mid=47, block_type="financial_table",
        content='{"headers":["Ticker","Peso"],"rows":[["FII0011","8%"]]}',
        page=3, title="Tabela - Página 3",
    ))
    # 5 textos auxiliares
    for i in range(5):
        blocks.append(_FakeBlock(
            bid=3000 + i, mid=47, block_type="texto",
            content=f"Comentário narrativo {i} sobre a carteira.",
            page=i, title=f"Conteúdo - Página {i}",
        ))
    return mat, prod, blocks


def test_search_by_portfolio_exhaustive_portfolio_rows():
    """Mesmo com n_results=20, search_by_portfolio devolve TODAS as 30
    `portfolio_row` (cap só vale para auxiliares)."""
    from services import vector_store as vs_mod

    mat, prod, blocks = _make_search_by_portfolio_db(num_rows=30)

    db = MagicMock()
    # 1ª query: candidatos (Mat outerjoin Prod)
    candidates_q = MagicMock()
    candidates_q.outerjoin.return_value = candidates_q
    candidates_q.filter.return_value = candidates_q
    candidates_q.all.return_value = [(mat, prod)]
    # 2ª query: produtos batched (Prod IN ids)
    prod_q = MagicMock()
    prod_q.filter.return_value = prod_q
    prod_q.all.return_value = [prod]
    # 3ª query: blocos
    blocks_q = MagicMock()
    blocks_q.join.return_value = blocks_q
    blocks_q.filter.return_value = blocks_q
    blocks_q.order_by.return_value = blocks_q
    blocks_q.all.return_value = [(b, mat) for b in blocks]

    # ORDEM importa: o código faz db.query() na ordem
    # (1) candidates [_Mat,_Prod] → (2) blocks [_CB,_Mat] → (3) prods [_Prod].
    # Inverter quebra a hidratação de _prod_by_id (vira lista de tuplas).
    db.query.side_effect = [candidates_q, blocks_q, prod_q]

    vs = vs_mod.VectorStore.__new__(vs_mod.VectorStore)
    docs = vs.search_by_portfolio(
        query="liste os FIIs da carteira Seven",
        n_results=20,
        db=db,
    )

    portfolio_rows = [d for d in docs if d["metadata"]["block_type"] == "portfolio_row"]
    other = [d for d in docs if d["metadata"]["block_type"] != "portfolio_row"]
    # Todas as 30 linhas devem vir (cap=20 NÃO se aplica a portfolio_row).
    assert len(portfolio_rows) == 30, (
        f"Esperava 30 portfolio_row exaustivos, recebi {len(portfolio_rows)}"
    )
    # Auxiliares limitados a no mínimo 5 (`max(5, n_results - len(portfolio_rows))`).
    # Nesse caso n_results=20, len(portfolio_rows)=30 → max(5, -10) = 5.
    assert len(other) <= 6, (  # 1 financial_table + até 5 textos
        f"Esperava ≤6 auxiliares, recebi {len(other)}"
    )


def test_search_by_portfolio_tags_strong_match_when_distinctive_hits():
    """Quando token distintivo casa o nome da carteira, todos os blocos
    saem com `portfolio_match_strength='strong'` no metadata — sinal para
    o agent_tools liberar o bypass do guard de baixa confiança."""
    from services import vector_store as vs_mod

    mat, prod, blocks = _make_search_by_portfolio_db(num_rows=3)

    db = MagicMock()
    candidates_q = MagicMock()
    candidates_q.outerjoin.return_value = candidates_q
    candidates_q.filter.return_value = candidates_q
    candidates_q.all.return_value = [(mat, prod)]
    blocks_q = MagicMock()
    blocks_q.join.return_value = blocks_q
    blocks_q.filter.return_value = blocks_q
    blocks_q.order_by.return_value = blocks_q
    blocks_q.all.return_value = [(b, mat) for b in blocks]
    prod_q = MagicMock()
    prod_q.filter.return_value = prod_q
    prod_q.all.return_value = [prod]
    db.query.side_effect = [candidates_q, blocks_q, prod_q]

    vs = vs_mod.VectorStore.__new__(vs_mod.VectorStore)
    docs = vs.search_by_portfolio(
        query="liste os FIIs da carteira Seven",  # 'seven' é distintivo
        n_results=20, db=db,
    )
    assert len(docs) > 0
    # Como o nome do material é "Carteira Seven FIIs Abril", o token "seven"
    # casa → todos os blocos devem sair tagueados como STRONG.
    strengths = {d["metadata"].get("portfolio_match_strength") for d in docs}
    assert strengths == {"strong"}, (
        f"Esperava todos os blocos com strength='strong', recebi {strengths}"
    )


def test_search_by_portfolio_tags_weak_match_when_no_distinctive():
    """Quando a query é genérica ("liste as carteiras") e nenhum token
    distintivo casa, o fallback devolve TODAS como contexto exploratório
    com `portfolio_match_strength='weak'` — agent_tools NÃO deve bypassar
    o guard nesse caso (evita mistura de carteiras não relacionadas)."""
    from services import vector_store as vs_mod

    mat, prod, blocks = _make_search_by_portfolio_db(num_rows=3)

    db = MagicMock()
    candidates_q = MagicMock()
    candidates_q.outerjoin.return_value = candidates_q
    candidates_q.filter.return_value = candidates_q
    candidates_q.all.return_value = [(mat, prod)]
    blocks_q = MagicMock()
    blocks_q.join.return_value = blocks_q
    blocks_q.filter.return_value = blocks_q
    blocks_q.order_by.return_value = blocks_q
    blocks_q.all.return_value = [(b, mat) for b in blocks]
    prod_q = MagicMock()
    prod_q.filter.return_value = prod_q
    prod_q.all.return_value = [prod]
    db.query.side_effect = [candidates_q, blocks_q, prod_q]

    vs = vs_mod.VectorStore.__new__(vs_mod.VectorStore)
    # Query SEM nome específico → nenhum token distintivo casa "Carteira
    # Seven FIIs Abril" → fallback devolve a única carteira candidata como
    # WEAK (mantém comportamento exploratório).
    docs = vs.search_by_portfolio(
        query="liste as carteiras",
        n_results=20, db=db,
    )
    assert len(docs) > 0
    strengths = {d["metadata"].get("portfolio_match_strength") for d in docs}
    assert strengths == {"weak"}, (
        f"Esperava todos os blocos com strength='weak', recebi {strengths}"
    )


def test_agent_tools_bypass_only_with_strong_match(monkeypatch):
    """Integration test: simula o `_execute_search_knowledge_base` recebendo
    resultados com `portfolio_match_strength` STRONG vs WEAK e verifica que
    o bypass do guard de baixa confiança só dispara no STRONG."""
    import asyncio
    from services import agent_tools as at_mod
    from services.semantic_search import SearchResult

    def _mk_result(strength: str, score: float = 0.10) -> SearchResult:
        return SearchResult(
            content="[CARTEIRA Seven] BTLG11: Peso=6%; DY=0,78%",
            metadata={
                "block_id": "1001", "material_id": "47",
                "material_name": "Carteira Seven FIIs Abril",
                "block_type": "portfolio_row", "page": "3",
                "product_name": "Carteira Seven", "product_type": "carteira",
                "portfolio_match_strength": strength,
                "portfolio_lookup_source": True,
            },
            vector_distance=0.05, vector_score=0.95,
            composite_score=score, source="portfolio_lookup",
        )

    async def _run(strong: bool):
        # Mocka EnhancedSearch dentro do módulo `services.semantic_search`
        # (importado lazily por agent_tools no início da função). A
        # instância retornada tem `.search()` SÍNCRONO que devolve apenas 1
        # portfolio_row com a strength desejada (agent_tools chama sem await).
        results = [_mk_result("strong" if strong else "weak", score=0.10)]
        def _fake_search(*a, **kw):
            return results
        fake_instance = MagicMock()
        fake_instance.search = _fake_search
        from services import semantic_search as ss_mod
        monkeypatch.setattr(
            ss_mod, "EnhancedSearch", lambda *a, **kw: fake_instance,
        )
        # Mocka também o vector_store getter para evitar conexão real.
        from services import vector_store as vs_mod
        monkeypatch.setattr(
            vs_mod, "get_vector_store", lambda: MagicMock(),
        )
        monkeypatch.setattr(
            vs_mod, "filter_expired_results", lambda items, *a, **kw: items,
            raising=False,
        )
        return await at_mod._execute_search_knowledge_base(
            {"query": "liste os FIIs da carteira Seven com seus pesos"},
            db=MagicMock(), conversation_id="t",
        )

    # STRONG: bypass deve disparar → resposta tem `results` populado
    out_strong = asyncio.run(_run(strong=True))
    assert out_strong.get("count", 0) > 0, (
        "STRONG match deveria bypassar o guard e retornar resultados"
    )
    assert out_strong.get("no_results") is not True

    # WEAK: bypass NÃO dispara → guard de baixa confiança barra → no_results
    out_weak = asyncio.run(_run(strong=False))
    assert out_weak.get("no_results") is True, (
        "WEAK match NÃO deveria bypassar o guard — guard semântico continua "
        "valendo (sem autoridade relacional)"
    )


def test_search_by_portfolio_returns_empty_when_no_carteira():
    """Quando não existe nenhum material-carteira, devolve []."""
    from services import vector_store as vs_mod

    db = MagicMock()
    candidates_q = MagicMock()
    candidates_q.outerjoin.return_value = candidates_q
    candidates_q.filter.return_value = candidates_q
    candidates_q.all.return_value = []  # nenhuma carteira no banco
    db.query.return_value = candidates_q

    vs = vs_mod.VectorStore.__new__(vs_mod.VectorStore)
    docs = vs.search_by_portfolio(query="liste os FIIs", n_results=20, db=db)
    assert docs == []


# ---------------------------------------------------------------------------
# 3) Compactor — modo portfolio-preserve
# ---------------------------------------------------------------------------

def _make_portfolio_row_dict(idx: int) -> dict:
    """Linha de carteira (`portfolio_row`) — bloco prioritário e
    INTOCÁVEL em modo preserve."""
    ticker = f"FII{idx:02d}11"
    content = f"[CARTEIRA Seven] {ticker}: Ticker={ticker}; Peso={5.0}%; Setor=X"
    return {
        "title": f"Linha de carteira — {ticker} (p.3)",
        "material_name": "Carteira Seven FIIs Abril",
        "block_type": "portfolio_row",
        "content": content,
        "block_id": 1000 + idx,
        "material_id": 47,
        "source_page": 3,
        "score": 0.9,
        "ticker": ticker,
        "product_type": "carteira",
        # Campo "fofo" — compactor remove em pass 1 (vazios) ou pass 2.
        "visual_description": "",
    }


def _make_text_dict(idx: int, padding_chars: int = 800) -> dict:
    """Bloco texto NÃO-prioritário, longo o bastante para forçar pressure."""
    return {
        "title": f"Comentário {idx}",
        "material_name": "Research Mensal",
        "block_type": "texto",
        "content": ("Comentário muito longo de mercado. " * (padding_chars // 35)).strip(),
        "block_id": 9000 + idx,
        "material_id": 99,
        "source_page": idx,
        "score": 0.3,
        "ticker": "",
        "product_type": "outro",
    }


def _wrap_payload(results, *, preserve: bool, page_size: int = 30) -> dict:
    p = {
        "results": list(results),
        "count": len(results),
        "total_results": len(results),
        "offset": 0,
        "page_size": page_size,
        "completeness_mode": True,
    }
    if preserve:
        p["_portfolio_preserve_mode"] = True
    return p


def test_compactor_preserves_all_portfolio_rows_under_pressure():
    """Mesmo com cap MUITO apertado, em modo preserve NENHUM `portfolio_row`
    é descartado — apenas auxiliares (`texto`) caem no pass 3a."""
    portfolio = [_make_portfolio_row_dict(i) for i in range(20)]
    # Muitos textos para que mesmo após o pass 2 trim (200 chars cada) ainda
    # haja pressão real sobre o cap, forçando pass 3a a podá-los.
    texts = [_make_text_dict(i, padding_chars=1500) for i in range(40)]
    payload = _wrap_payload(portfolio + texts, preserve=True)

    raw_size = len(json.dumps(payload, ensure_ascii=False))
    # Cap apertado, mas com folga para os 20 portfolio_row (~5KB).
    tight_cap = 7000
    assert raw_size > tight_cap, "fixture precisa estourar o cap para o teste fazer sentido"

    out_str, was_truncated = _compact_tool_payload(payload, max_chars=tight_cap)
    out = json.loads(out_str)

    # Truncamento aconteceu (era esperado).
    assert was_truncated is True

    # TODOS os 20 portfolio_row preservados.
    out_portfolio = [r for r in out["results"] if r.get("block_type") == "portfolio_row"]
    assert len(out_portfolio) == 20, (
        f"Esperava 20 portfolio_row preservados, recebi {len(out_portfolio)}"
    )
    # Tickers todos presentes (nada foi mutilado).
    out_tickers = {r["ticker"] for r in out_portfolio}
    assert out_tickers == {f"FII{i:02d}11" for i in range(20)}

    # Auxiliares foram descartados (pass 3a com cap apertado).
    out_text = [r for r in out["results"] if r.get("block_type") == "texto"]
    assert len(out_text) < len(texts), (
        f"auxiliares deveriam ter sofrido poda no pass 3a "
        f"(esperava < {len(texts)}, recebi {len(out_text)})"
    )


def test_compactor_without_preserve_can_drop_portfolio_rows():
    """SEM `_portfolio_preserve_mode`, o compactor segue o comportamento
    legado (pass 3b descarta priority blocks como último recurso)."""
    portfolio = [_make_portfolio_row_dict(i) for i in range(20)]
    texts = [_make_text_dict(i, padding_chars=1500) for i in range(8)]
    payload = _wrap_payload(portfolio + texts, preserve=False)

    tight_cap = 4000  # bem mais apertado para realmente forçar 3b
    out_str, was_truncated = _compact_tool_payload(payload, max_chars=tight_cap)
    out = json.loads(out_str)

    out_portfolio = [r for r in out["results"] if r.get("block_type") == "portfolio_row"]
    # No legado, COM cap muito apertado, alguns portfolio_row caem.
    assert len(out_portfolio) < 20, (
        "Sem preserve, espera-se que pass 3b descarte parte dos portfolio_row "
        "para caber no cap apertado — comportamento histórico do compactor."
    )
    assert was_truncated is True


def test_compactor_preserve_marks_envelope_when_over_cap_with_only_portfolio():
    """Se mesmo após podar TODOS auxiliares ainda passa do cap (carteira
    gigantesca), marca `_portfolio_preserved_over_cap` no envelope para
    o agente saber que o payload ficou propositadamente acima do cap."""
    # 50 portfolio_rows = ~10000 chars + envelope
    portfolio = [_make_portfolio_row_dict(i) for i in range(50)]
    payload = _wrap_payload(portfolio, preserve=True)

    out_str, was_truncated = _compact_tool_payload(payload, max_chars=3000)
    out = json.loads(out_str)

    # Todos 50 preservados.
    out_portfolio = [r for r in out["results"] if r.get("block_type") == "portfolio_row"]
    assert len(out_portfolio) == 50

    # Marca de transbordamento controlado deve estar presente.
    assert out.get("_portfolio_preserved_over_cap") is True
