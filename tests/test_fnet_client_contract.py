"""
Testes de contrato mínimo para `FnetClient.list_documents`.

Trava a regressão da task #338: `list_documents` deve sempre retornar
uma 3-tupla `(documentos, idFundo, nome_canônico)` conforme a assinatura
e a docstring — e não apenas a lista de documentos.

A suíte mais ampla do client (warm-up 403 c/ headers Cloudflare, re-warm
após 401, fallback de cache stale etc.) é coberta pela task #337.
"""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import pytest

from services.fnet_client import (
    FnetClient,
    FnetClientError,
    FnetDocument,
    FnetFundNotFoundError,
)


WARMUP_HTML = """<!DOCTYPE html><html><head>
<script>var csrf_token="abcdef0123456789abcdef0123456789";</script>
</head><body>FNET</body></html>"""


def _build_handler(*, search_results: list[dict] | None = None,
                   autocomplete_results: list[dict] | None = None):
    """
    Mock dos 3 endpoints reais do FNET:
      - GET abrirGerenciadorDocumentosCVM → HTML com csrf_token (warm-up)
      - GET listarFundos                  → JSON com `results`
      - GET pesquisarGerenciadorDocumentosCVMRequest → JSON com `data`
    """
    auto = autocomplete_results if autocomplete_results is not None else [
        {"id": "21346", "text": "FII RZTR - FUNDO DE INVESTIMENTO IMOBILIÁRIO RIZA TERRAX"}
    ]
    search = search_results if search_results is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/abrirGerenciadorDocumentosCVM"):
            return httpx.Response(200, text=WARMUP_HTML,
                                  headers={"content-type": "text/html"})
        if path.endswith("/listarFundos"):
            return httpx.Response(200, json={"results": auto})
        if path.endswith("/pesquisarGerenciadorDocumentosDados"):
            return httpx.Response(200, json={
                "draw": 1, "recordsTotal": len(search),
                "recordsFiltered": len(search), "data": search,
            })
        return httpx.Response(404, text=f"unmocked {path}")

    return handler


class _MockedFnetClient(FnetClient):
    """Override do AsyncClient pra injetar MockTransport sem rede real."""

    def __init__(self, handler, **kw):
        super().__init__(**kw)
        self._handler = handler

    def _new_http(self):
        from services.fnet_client import _DEFAULT_HEADERS
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self._handler),
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
        )


async def _run_list(handler, **kw):
    """Helper: roda list_documents contra o handler mockado."""
    # Monkey-patch httpx.AsyncClient apenas no escopo desta chamada.
    import services.fnet_client as fc
    original = fc.httpx.AsyncClient

    def _patched_async_client(*_a, **_kw):
        return original(
            transport=httpx.MockTransport(handler),
            headers=fc._DEFAULT_HEADERS,
            follow_redirects=True,
        )

    fc.httpx.AsyncClient = _patched_async_client
    try:
        client = FnetClient(max_retries=2, retry_backoff=0.0)
        return await client.list_documents(
            cnpj="36501128000186",
            date_start=date(2025, 1, 1),
            date_end=date(2025, 12, 31),
            tipo_fundo=1,
            **kw,
        )
    finally:
        fc.httpx.AsyncClient = original


@pytest.mark.asyncio
async def test_list_documents_returns_three_tuple_when_empty():
    """0 docs no período → retorna ([], int, str), NÃO levanta ValueError."""
    handler = _build_handler(search_results=[])
    result = await _run_list(handler)

    assert isinstance(result, tuple), f"esperava tupla, veio {type(result).__name__}"
    assert len(result) == 3, f"esperava 3 elementos, veio {len(result)}"
    docs, id_fundo, canonical_name = result
    assert docs == []
    assert isinstance(id_fundo, int) and id_fundo == 21346
    assert isinstance(canonical_name, str) and "RIZA TERRAX" in canonical_name


@pytest.mark.asyncio
async def test_list_documents_returns_three_tuple_with_docs():
    """Docs presentes → tupla de 3 com lista de FnetDocument."""
    handler = _build_handler(search_results=[{
        "id": 12345,
        "descricaoFundo": "FUNDO DE INVESTIMENTO IMOBILIÁRIO RIZA TERRAX",
        "categoriaDocumento": "Aviso aos Cotistas",
        "tipoDocumento": "Aviso",
        "dataReferencia": "05/2026",
        "dataEntrega": "26/05/2026",
        "cnpjFundo": None,
        "nomePregao": "RZTR11",
        "versao": 1,
    }])
    docs, id_fundo, canonical_name = await _run_list(handler)

    assert len(docs) == 1
    assert isinstance(docs[0], FnetDocument)
    assert docs[0].id == 12345
    assert id_fundo == 21346
    assert "RIZA TERRAX" in canonical_name


@pytest.mark.asyncio
async def test_list_documents_uses_cache_and_still_returns_three_tuple():
    """Cache hit pula listarFundos mas o contrato continua 3-tupla."""
    handler = _build_handler(search_results=[])
    docs, id_fundo, canonical_name = await _run_list(
        handler,
        cached_internal_id=99999,
        cached_canonical_name="FII CACHED - FUNDO CACHED",
    )
    assert docs == []
    assert id_fundo == 99999
    assert canonical_name == "FII CACHED - FUNDO CACHED"


@pytest.mark.asyncio
async def test_list_documents_raises_fund_not_found_on_empty_autocomplete():
    """Comportamento legítimo de erro preservado: 0 hits no autocomplete."""
    handler = _build_handler(autocomplete_results=[])
    with pytest.raises(FnetFundNotFoundError):
        await _run_list(handler)
