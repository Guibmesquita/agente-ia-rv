"""
RAG V3.6 — Testes do content_formatter.

Cobertura:
  - TABLE_BLOCK_TYPES inclui o valor "tabela" (canônico do enum) — esse era
    o bug central da V3.5 que rodou em produção sem ativar o caminho rico
    para 100% dos blocos.
  - JSON malformado, vazio, sem headers, etc. — degrade graceful.
  - Tabela 12+ linhas (caso real "Seven FIIs") — todas as linhas presentes.
  - Truncamento por linha — nunca corta no meio (evita "MANA1" em vez de
    "MANA11") e adiciona marcador de truncamento.
"""

import json

from services.content_formatter import (
    DEFAULT_MAX_CHARS_TABLE,
    DEFAULT_MAX_CHARS_TEXT,
    TABLE_BLOCK_TYPES,
    format_tabular_content,
    format_tabular_content_rich,
    get_rich_content,
    truncate_at_line_boundary,
)


def test_table_block_types_contains_tabela():
    """Bug-fix V3.6: o valor canônico do enum é 'tabela' (pt), não 'table'."""
    assert "tabela" in TABLE_BLOCK_TYPES
    assert "financial_table" in TABLE_BLOCK_TYPES
    assert "table" in TABLE_BLOCK_TYPES


def test_format_tabular_content_rich_returns_none_for_invalid_json():
    assert format_tabular_content_rich("not json") is None
    assert format_tabular_content_rich("") is None
    assert format_tabular_content_rich("{invalid}") is None


def test_format_tabular_content_rich_returns_none_for_empty_rows():
    payload = json.dumps({"headers": ["A", "B"], "rows": []})
    assert format_tabular_content_rich(payload) is None


def test_format_tabular_content_rich_handles_missing_headers():
    payload = json.dumps({"rows": [["MXRF11", "5%"], ["KNRI11", "8%"]]})
    out = format_tabular_content_rich(payload)
    assert out is not None
    assert "MXRF11" in out
    assert "KNRI11" in out


def test_format_tabular_content_rich_emits_markdown_and_facts():
    payload = json.dumps(
        {
            "headers": ["Ticker", "Peso (%)"],
            "rows": [["MANA11", "9.0"], ["MXRF11", "8.5"]],
        }
    )
    out = format_tabular_content_rich(payload)
    assert out is not None
    # Markdown table header + separator
    assert "| Ticker | Peso (%) |" in out
    assert "| --- | --- |" in out
    # Fatos por linha section
    assert "Fatos por linha:" in out
    assert "Ticker=MANA11; Peso (%)=9.0" in out
    assert "Ticker=MXRF11; Peso (%)=8.5" in out


def _seven_fiis_payload(n_rows: int = 12) -> str:
    """Carteira sintética com N linhas, simulando o caso real Seven FIIs."""
    headers = ["Ticker", "Setor", "Peso (%)"]
    base_tickers = [
        "MANA11", "MXRF11", "KNRI11", "HGLG11", "VISC11", "XPLG11",
        "BRCO11", "RECR11", "VINO11", "RBRR11", "BCFF11", "HFOF11",
    ]
    rows = [[base_tickers[i], "Logística" if i % 2 == 0 else "Shoppings", f"{8.0 + i * 0.1:.1f}"]
            for i in range(n_rows)]
    return json.dumps({"headers": headers, "rows": rows})


def test_format_tabular_content_rich_keeps_all_rows_for_12_fii_table():
    out = format_tabular_content_rich(_seven_fiis_payload(12))
    assert out is not None
    for ticker in [
        "MANA11", "MXRF11", "KNRI11", "HGLG11", "VISC11", "XPLG11",
        "BRCO11", "RECR11", "VINO11", "RBRR11", "BCFF11", "HFOF11",
    ]:
        assert ticker in out, f"Ticker {ticker} ausente da saída rica"


def test_truncate_at_line_boundary_never_cuts_inside_a_line():
    content = "linha1: MANA11=9.0\nlinha2: MXRF11=8.5\nlinha3: KNRI11=7.2"
    # Cap propositalmente baixo, no meio da linha2
    truncated = truncate_at_line_boundary(content, max_chars=22)
    # Não deve ter "MXRF1" (corte no meio) nem "linha3"
    assert "MXRF1" not in truncated or "MXRF11" in truncated
    assert "linha3" not in truncated
    # Sempre deve haver marcador de truncamento
    assert "truncado" in truncated


def test_truncate_at_line_boundary_passthrough_when_within_limit():
    content = "curto"
    assert truncate_at_line_boundary(content, max_chars=100) == "curto"


def test_truncate_at_line_boundary_announces_omitted_count():
    content = "a\nb\nc\nd\ne\nf"
    truncated = truncate_at_line_boundary(content, max_chars=4)
    assert "truncado" in truncated
    # Deve haver um número de linhas omitidas mencionado
    assert "linha" in truncated


def test_get_rich_content_uses_table_path_for_tabela_block_type():
    """Regressão V3.6: block_type='tabela' (não 'table') deve ativar o
    caminho rico com cap de 4000 chars."""
    payload = _seven_fiis_payload(12)
    out = get_rich_content(payload, fallback_content="", max_chars=600, block_type="tabela")
    # Caminho rico deve produzir Markdown + Fatos por linha
    assert "Fatos por linha:" in out
    # Cap default de tabela (4000) deve permitir todas as 12 linhas
    assert "MANA11" in out and "HFOF11" in out


def test_get_rich_content_uses_table_path_for_financial_table_block_type():
    payload = _seven_fiis_payload(12)
    out = get_rich_content(
        payload,
        fallback_content="",
        max_chars=600,
        block_type="financial_table",
    )
    assert "Fatos por linha:" in out
    assert "HFOF11" in out


def test_get_rich_content_text_block_keeps_small_cap():
    """Para block_type não-tabela, mantém cap conservador de 600 chars."""
    long_text = "palavra " * 200  # ~1600 chars
    out = get_rich_content(long_text, fallback_content="", max_chars=DEFAULT_MAX_CHARS_TEXT,
                           block_type="texto")
    assert len(out) <= DEFAULT_MAX_CHARS_TEXT


def test_get_rich_content_falls_back_to_legacy_when_block_type_missing():
    """Heurística: mesmo sem block_type, JSON tabular deve ser detectado."""
    payload = _seven_fiis_payload(12)
    out = get_rich_content(payload, fallback_content="")
    assert "MANA11" in out
    assert "HFOF11" in out


def test_format_tabular_content_legacy_pipe_format():
    """A função legada continua funcionando para chamadores externos."""
    payload = json.dumps({"headers": ["A", "B"], "rows": [["1", "2"]]})
    out = format_tabular_content(payload)
    assert out == "A: 1 | B: 2"
