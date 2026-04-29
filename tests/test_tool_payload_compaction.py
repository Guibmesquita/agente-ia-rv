"""Testes do truncamento semanticamente seguro do payload das tools.

Cobertura:
  - Payload pequeno passa intacto (sem marcas de truncamento).
  - Payload com 30 linhas de carteira (`portfolio_row`) passa intacto:
    nenhum bloco é descartado e os tickers permanecem todos presentes.
  - Quando precisa cortar, blocos não-prioritários são removidos primeiro.
  - Quando precisa cortar, `has_more`/`next_offset`/`count` são atualizados
    honestamente para o agente conseguir paginar o resto.
"""

import json

from services.openai_agent import (
    _TOOL_PAYLOAD_MAX_CHARS,
    _compact_tool_payload,
)


def _make_portfolio_row(idx: int, material_name: str = "Carteira Recomendada FII Q1 2026") -> dict:
    ticker = f"TICK{idx:02d}11"
    content = (
        f"[CARTEIRA {material_name}] {ticker}: Ticker={ticker}; "
        f"Peso={idx + 1}.5%; Setor=Logística; Preço=85.50; Variação=2.5%"
    )
    return {
        "title": f"Linha de carteira — {ticker} (Página 5)",
        "material_name": material_name,
        "material_type": "recomendacao",
        "comite_tag": "[COMITÊ-FII]",
        "product_type": "fii",
        "product": ticker,
        "ticker": ticker,
        "content": content,
        "content_truncated": False,
        "score": 0.85,
        "material_id": 42,
        "block_id": 12345 + idx,
        "block_type": "portfolio_row",
        "source_page": 5,
        "visual_description": "",
        "source_note": (
            f"TAG: [COMITÊ-FII] | Ao citar, inclua: (Fonte: {material_name}, pág. 5). "
            f"Este material é uma recomendação formal do Comitê de Investimentos da SVN — "
            f"use framing de recomendação oficial na resposta. Tipo do produto: FII."
        ),
    }


def _make_text_block(idx: int) -> dict:
    """Bloco de texto solto, NÃO prioritário."""
    return {
        "title": f"Comentário {idx}",
        "material_name": "Research Mensal",
        "material_type": "research",
        "comite_tag": "[NÃO-COMITÊ]",
        "product_type": "outro",
        "product": "",
        "ticker": "",
        "content": ("Comentário de mercado bastante longo. " * 30).strip(),
        "content_truncated": False,
        "score": 0.3,
        "material_id": 99,
        "block_id": 55000 + idx,
        "block_type": "texto",
        "source_page": idx,
        "visual_description": "",
        "source_note": (
            "TAG: [NÃO-COMITÊ] | Ao citar, inclua: (Fonte: Research Mensal). "
            "Este material é INFORMATIVO — NÃO é uma recomendação formal da SVN."
        ),
    }


def _wrap(results: list, *, offset: int = 0, page_size: int = 30) -> dict:
    return {
        "results": list(results),
        "count": len(results),
        "total_results": len(results),
        "offset": offset,
        "page_size": page_size,
        "completeness_mode": True,
        "content_truncated_in_window": False,
        "has_more": False,
    }


def test_small_payload_passes_through_untouched():
    payload = _wrap([_make_portfolio_row(0)])
    out, was_truncated = _compact_tool_payload(payload)
    assert was_truncated is False
    parsed = json.loads(out)
    assert parsed == payload, "payload pequeno deve passar intacto, sem compressão"


def test_thirty_portfolio_rows_stay_intact():
    """Caso central: 30 linhas de carteira não podem ser descartadas pelo
    truncamento. Pode haver compressão de campos verbosos (source_note,
    metadata redundante), mas todos os tickers devem chegar ao agente.
    """
    rows = [_make_portfolio_row(i) for i in range(30)]
    payload = _wrap(rows)

    raw = json.dumps(payload, ensure_ascii=False)
    assert len(raw) > _TOOL_PAYLOAD_MAX_CHARS, (
        "Pré-condição do teste: payload bruto precisa estar acima do cap "
        "para que o truncamento seja exercitado de fato."
    )

    out, was_truncated = _compact_tool_payload(payload)
    parsed = json.loads(out)

    assert len(parsed["results"]) == 30, (
        "Nenhuma linha de carteira pode ser descartada — perderíamos completude "
        "da carteira que o V3.6 acabou de garantir."
    )
    assert "_truncated_results_count" not in parsed, (
        "Compressão deve resolver sem precisar podar resultados."
    )
    assert parsed.get("has_more") is False, (
        "Não houve poda; has_more deve continuar False."
    )

    expected_tickers = {f"TICK{i:02d}11" for i in range(30)}
    actual_tickers = {r["ticker"] for r in parsed["results"]}
    assert actual_tickers == expected_tickers, (
        f"Faltam tickers após compressão: {expected_tickers - actual_tickers}"
    )

    assert len(out) <= _TOOL_PAYLOAD_MAX_CHARS, (
        f"Payload comprimido deve respeitar o cap; len={len(out)}"
    )


def test_priority_blocks_kept_when_dropping_non_priority():
    """Mistura 5 portfolio_row + muitos blocos de texto grandes. Quando
    precisar podar, os blocos de texto devem cair antes dos portfolio_row.
    """
    rows = [_make_portfolio_row(i) for i in range(5)]
    texts = [_make_text_block(i) for i in range(20)]
    payload = _wrap(rows + texts)

    out, _ = _compact_tool_payload(payload)
    parsed = json.loads(out)

    portfolio_kept = [r for r in parsed["results"] if r.get("block_type") == "portfolio_row"]
    assert len(portfolio_kept) == 5, (
        "Todas as 5 linhas de portfolio_row devem ser preservadas mesmo após poda agressiva."
    )

    assert len(out) <= _TOOL_PAYLOAD_MAX_CHARS


def test_drop_pass_updates_has_more_and_next_offset():
    """Quando blocos são realmente descartados, o agente precisa receber
    `has_more=True` e um `next_offset` correto para paginar o resto.
    """
    texts = [_make_text_block(i) for i in range(60)]
    payload = _wrap(texts, offset=0)

    out, was_truncated = _compact_tool_payload(payload)
    assert was_truncated is True
    parsed = json.loads(out)

    kept = len(parsed["results"])
    assert kept < 60, "Pré-condição: payload tinha que estourar o cap."
    assert parsed["count"] == kept, "count deve refletir o que de fato sobrou."
    assert parsed["has_more"] is True, "has_more precisa sinalizar que existe mais."
    assert parsed["next_offset"] == kept, (
        "next_offset deve apontar para o primeiro bloco que ficou de fora."
    )
    assert parsed["total_results"] == 60, (
        "total_results deve preservar o tamanho real do conjunto original."
    )
    assert parsed["_truncated_results_count"] == 60 - kept


def test_unknown_structure_fallback_returns_valid_json_envelope():
    """Se a tool retornar algo sem `results`, o fallback embrulha o
    conteúdo bruto num envelope JSON válido — assim o parser do modelo
    consegue interpretar e o agente sabe que houve perda."""
    big_blob = "x" * (_TOOL_PAYLOAD_MAX_CHARS + 500)
    out, was_truncated = _compact_tool_payload({"foo": big_blob})
    assert was_truncated is True
    assert len(out) <= _TOOL_PAYLOAD_MAX_CHARS
    # Tem que ser JSON válido (não corte cego no meio da string).
    parsed = json.loads(out)
    assert parsed["_truncated"] is True
    assert parsed["_truncated_reason"] == "unknown_payload_structure"
    assert isinstance(parsed["raw_preview"], str)
    assert len(parsed["raw_preview"]) > 0
