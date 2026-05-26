"""
Cliente HTTP assíncrono para a API pública do FNET/B3
(https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM).

Expõe dois métodos principais:
- `list_documents(cnpj, date_start, date_end, ...)` — DataTables-style search.
- `download_document(document_id)` — baixa o PDF do documento por id.

Não há autenticação (endpoint público). Usa um User-Agent realista e
`Referer` para evitar bloqueios anti-scraping. Retries automáticos para
falhas transitórias (5xx, timeouts).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


FNET_BASE = "https://fnet.bmfbovespa.com.br/fnet/publico"
FNET_SEARCH_URL = f"{FNET_BASE}/pesquisarGerenciadorDocumentosDados"
FNET_DOWNLOAD_URL = f"{FNET_BASE}/downloadDocumento"
FNET_REFERER = f"{FNET_BASE}/abrirGerenciadorDocumentosCVM"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": FNET_REFERER,
}


@dataclass
class FnetDocument:
    """Documento bruto retornado pelo FNET."""

    id: int
    descricao_fundo: str
    categoria_documento: str
    tipo_documento: str
    data_referencia: str  # FNET retorna "MM/YYYY" (mensal) ou "DD/MM/YYYY" (eventos)
    data_entrega: str
    cnpj_fundo: Optional[str]
    nome_pregao: Optional[str]
    versao: int
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "FnetDocument":
        return cls(
            id=int(payload.get("id") or 0),
            descricao_fundo=str(payload.get("descricaoFundo") or "").strip(),
            categoria_documento=str(payload.get("categoriaDocumento") or "").strip(),
            tipo_documento=str(payload.get("tipoDocumento") or "").strip(),
            data_referencia=str(payload.get("dataReferencia") or "").strip(),
            data_entrega=str(payload.get("dataEntrega") or "").strip(),
            cnpj_fundo=(str(payload.get("cnpjFundo")).strip() if payload.get("cnpjFundo") else None),
            nome_pregao=(str(payload.get("nomePregao")).strip() if payload.get("nomePregao") else None),
            versao=int(payload.get("versao") or 1),
            raw=payload,
        )

    def reference_month_ym(self) -> Optional[str]:
        """
        Normaliza `data_referencia` para "YYYY-MM" quando possível.
        Aceita formatos comuns do FNET:
        - "MM/YYYY"        → "YYYY-MM"
        - "DD/MM/YYYY"     → "YYYY-MM"
        - "YYYY-MM-DD"     → "YYYY-MM"
        Retorna None se não conseguir parsear.
        """
        s = (self.data_referencia or "").strip()
        if not s:
            return None
        for fmt in ("%m/%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m")
            except ValueError:
                continue
        return None


class FnetClient:
    """
    Cliente assíncrono para o FNET. Reutilizável; passe `client_factory`
    nos testes para injetar mock.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ):
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

    @staticmethod
    def _format_br_date(d: date) -> str:
        return d.strftime("%d/%m/%Y")

    async def list_documents(
        self,
        cnpj: str,
        date_start: date,
        date_end: date,
        tipo_fundo: int = 1,  # 1 = FII
        page_size: int = 200,
    ) -> list[FnetDocument]:
        """
        Lista todos os documentos do fundo `cnpj` entregues entre `date_start`
        e `date_end` (inclusive). Faz paginação automática se houver mais que
        `page_size` registros.

        Levanta `FnetClientError` em caso de falha persistente após retries.
        """
        # FNET espera POST com payload no formato DataTables-style:
        # d[i][name]=X & d[i][value]=Y (i é o índice do parâmetro).
        # Ordem dos parâmetros segue o site oficial:
        # cnpjFundo, tipoFundo, dataInicio, dataFim, draw (sequencial).
        base_fields: list[tuple[str, str]] = [
            ("cnpjFundo", cnpj),
            ("tipoFundo", str(tipo_fundo)),
            ("dataInicio", self._format_br_date(date_start)),
            ("dataFim", self._format_br_date(date_end)),
        ]

        all_docs: list[FnetDocument] = []
        start = 0
        draw = 1

        async with httpx.AsyncClient(
            timeout=self._timeout, headers=_DEFAULT_HEADERS
        ) as http:
            while True:
                form_data = self._build_datatables_payload(
                    base_fields=base_fields,
                    start=start,
                    length=page_size,
                    draw=draw,
                )
                payload = await self._post_with_retry(http, FNET_SEARCH_URL, form_data)
                data = payload.get("data") or []
                total = int(payload.get("recordsFiltered") or 0)

                for raw in data:
                    try:
                        all_docs.append(FnetDocument.from_api(raw))
                    except Exception as exc:
                        logger.warning(
                            "[FNET] Falha ao parsear documento: %s | raw=%s",
                            exc,
                            str(raw)[:200],
                        )

                start += len(data)
                draw += 1
                if not data or start >= total or len(data) < page_size:
                    break

        return all_docs

    async def download_document(self, document_id: int) -> tuple[bytes, str]:
        """
        Baixa o PDF do documento `document_id`. Retorna `(bytes, suggested_filename)`.
        `suggested_filename` é extraído de Content-Disposition quando disponível,
        ou cai para `fnet_{id}.pdf`.
        """
        url = FNET_DOWNLOAD_URL
        params = {"id": str(document_id)}

        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
        ) as http:
            response = await self._get_raw_with_retry(http, url, params)

        content = response.content
        if not content or content[:4] != b"%PDF":
            raise FnetClientError(
                f"Resposta de download inválida (não é PDF) para id={document_id}: "
                f"content_type={response.headers.get('content-type')!r}, "
                f"primeiros_bytes={content[:32]!r}"
            )

        filename = self._extract_filename(response.headers.get("content-disposition"))
        if not filename:
            filename = f"fnet_{document_id}.pdf"

        return content, filename

    @staticmethod
    def _extract_filename(content_disposition: Optional[str]) -> Optional[str]:
        if not content_disposition:
            return None
        # Padrão FNET: attachment; filename="CNPJ-CODIGO-NNNN.pdf"
        import re

        m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _build_datatables_payload(
        *,
        base_fields: list[tuple[str, str]],
        start: int,
        length: int,
        draw: int,
    ) -> list[tuple[str, str]]:
        """
        Constrói o body application/x-www-form-urlencoded no formato DataTables
        que o FNET aceita: cada parâmetro é codificado como dois pares
        d[i][name]=<nome> e d[i][value]=<valor>, mais 'start', 'length', 'draw'.

        Retorna lista de tuplas (não dict) para preservar a ordem dos índices
        — o backend FNET é sensível à ordem de d[0], d[1], ...
        """
        items: list[tuple[str, str]] = []
        for idx, (name, value) in enumerate(base_fields):
            items.append((f"d[{idx}][name]", name))
            items.append((f"d[{idx}][value]", value))
        items.append(("start", str(start)))
        items.append(("length", str(length)))
        items.append(("draw", str(draw)))
        return items

    async def _post_with_retry(
        self,
        http: httpx.AsyncClient,
        url: str,
        form_data: list[tuple[str, str]],
    ) -> dict[str, Any]:
        # NOTA (httpx 0.26.0 — RuntimeError "Attempted to send a sync request
        # with an AsyncClient instance"):
        # Passar `data=list[tuple]` para `AsyncClient.post` faz o httpx criar
        # um `IteratorByteStream` que implementa apenas `SyncByteStream`,
        # falhando o `isinstance(request.stream, AsyncByteStream)` em
        # `_send_single_request` (httpx/_client.py:1743). Solução: codificamos
        # nós mesmos o form-urlencoded e enviamos como `content=bytes`, que
        # gera um `ByteStream` (Sync + Async). Não muda o que o FNET recebe.
        body = urlencode(form_data).encode("utf-8")
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                r = await http.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if r.status_code in (500, 502, 503, 504, 520, 521, 522, 524):
                    raise FnetTransientError(
                        f"FNET {r.status_code} em POST {url} (tentativa {attempt})"
                    )
                r.raise_for_status()
                try:
                    return r.json()
                except ValueError as e:
                    raise FnetClientError(
                        f"Resposta não-JSON do FNET (POST {url}): "
                        f"content_type={r.headers.get('content-type')!r}, "
                        f"corpo[:200]={r.text[:200]!r}"
                    ) from e
            except (FnetTransientError, httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff ** attempt)
                continue
        raise FnetClientError(
            f"Falha persistente em POST {url} após {self._max_retries} tentativas: {last_exc}"
        ) from last_exc

    async def _get_raw_with_retry(
        self,
        http: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                r = await http.get(url, params=params)
                if r.status_code in (500, 502, 503, 504, 520, 521, 522, 524):
                    raise FnetTransientError(
                        f"FNET {r.status_code} em {url} (tentativa {attempt})"
                    )
                r.raise_for_status()
                return r
            except (FnetTransientError, httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff ** attempt)
                continue
        raise FnetClientError(
            f"Falha persistente em GET {url} após {self._max_retries} tentativas: {last_exc}"
        ) from last_exc


class FnetClientError(RuntimeError):
    """Erro de comunicação com o FNET após esgotar retries."""


class FnetTransientError(FnetClientError):
    """Erro transitório (5xx, timeout) — passível de retry."""
