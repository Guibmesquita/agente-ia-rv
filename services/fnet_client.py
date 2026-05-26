"""
Cliente HTTP assíncrono para a API pública do FNET/B3
(https://fnet.bmfbovespa.com.br/fnet/publico/abrirGerenciadorDocumentosCVM).

Expõe dois métodos principais:
- `list_documents(cnpj, date_start, date_end, ...)` — busca documentos do fundo.
- `download_document(document_id)` — baixa o PDF do documento por id.

Fluxo obrigatório (descoberto via gerenciador-documentos-cvm.js da própria B3):
1. **Warm-up de sessão**: GET em `abrirGerenciadorDocumentosCVM` para receber
   cookies (`JSESSIONID`, `ROUTEID_FNET`, `F051234a800`) e raspar o token CSRF
   declarado como `var csrf_token = "..."` no HTML.
2. **Lookup CNPJ → idFundo**: GET em `listarFundos?term=<CNPJ>` (autocomplete
   select2 da página). O filtro real do search é por `idFundo` numérico — passar
   só `cnpj`/`cnpjFundo` ignora silenciosamente e devolve TODOS os documentos
   do tipo, sem filtrar.
3. **Search**: GET em `pesquisarGerenciadorDocumentosDados` com header
   `CSRFToken`, params compactos DataTables (`d`/`s`/`l`), nomes de data
   `dataInicial`/`dataFinal` (não `dataInicio`/`dataFim`) e `idFundo` resolvido.

Sem esses passos o FNET responde 403 Forbidden (Cloudflare na frente) ou 404,
ou — pior — devolve 200 com dados de OUTROS fundos. Antes desta task o cliente
fazia POST direto com payload `d[i][name]=...&d[i][value]=...` sem warmup nem
CSRF, e parou de funcionar quando a B3 passou a exigir GET+CSRF/session.

Não há autenticação por API (endpoint público); a sessão é apenas anti-bot.
Retries automáticos para falhas transitórias (5xx, timeouts). Se um GET de
busca/download voltar 401/403 (sessão expirada), o cliente refaz o warm-up
**uma vez** dentro da mesma chamada antes de desistir.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


FNET_BASE = "https://fnet.bmfbovespa.com.br/fnet/publico"
FNET_WARMUP_URL = f"{FNET_BASE}/abrirGerenciadorDocumentosCVM"
FNET_LIST_FUNDS_URL = f"{FNET_BASE}/listarFundos"
FNET_SEARCH_URL = f"{FNET_BASE}/pesquisarGerenciadorDocumentosDados"
FNET_DOWNLOAD_URL = f"{FNET_BASE}/downloadDocumento"

# Token CSRF é declarado inline no HTML do gerenciador como
# `var csrf_token = "<uuid>";` — extraímos com regex.
_CSRF_REGEX = re.compile(
    r"""var\s+csrf_token\s*=\s*["']([0-9a-fA-F-]{16,})["']""",
)

# Headers compartilhados por todas as chamadas. Adicionamos sinais que o
# Cloudflare/anti-bot da B3 usa pra distinguir browser real de scraper
# (`sec-ch-ua*`, `Accept-Encoding`, `Connection: keep-alive`). Sem isso,
# IPs fora do Brasil (Railway) recebem 403 já no warm-up. Veja o set
# `_WARMUP_HEADERS` abaixo para os Sec-Fetch específicos de navegação.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_SEC_CH_UA = '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"'

_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://fnet.bmfbovespa.com.br",
    "Referer": FNET_WARMUP_URL,
    # Sec-* p/ XHR same-origin (search, autocomplete, download).
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "sec-ch-ua": _SEC_CH_UA,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# Headers específicos para o warm-up (GET HTML top-level navigation).
# `Sec-Fetch-Site: none` é o que um browser real envia quando o usuário
# digita a URL na barra — sem isso o Cloudflare desconfia. `Origin` e
# `X-Requested-With` saem porque navegação top-level não emite eles.
_WARMUP_HEADERS_OVERRIDE = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
    # Remove headers de XHR — usamos sentinela None para drop no merge.
    "Origin": None,
    "Referer": None,
    "X-Requested-With": None,
}


def _warmup_headers() -> dict[str, str]:
    """Merge _DEFAULT_HEADERS com overrides de navegação, removendo None."""
    merged = {**_DEFAULT_HEADERS, **_WARMUP_HEADERS_OVERRIDE}
    return {k: v for k, v in merged.items() if v is not None}


# Headers de resposta que ajudam a diagnosticar bloqueios de Cloudflare/AWS
# na frente do FNET. Logados em falhas 4xx pra confirmar/descartar a
# hipótese de geo-block sem expor segredos.
_DIAG_RESPONSE_HEADERS = (
    "Server",
    "CF-Ray",
    "cf-mitigated",
    "cf-cache-status",
    "x-amzn-trace-id",
)


def _extract_diag_headers(response: httpx.Response) -> dict[str, str]:
    """Pega os headers de diagnóstico que estiverem presentes na resposta."""
    return {
        name: response.headers[name]
        for name in _DIAG_RESPONSE_HEADERS
        if name in response.headers
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
    Cliente assíncrono para o FNET. Cada operação pública (`list_documents`,
    `download_document`) abre seu próprio `httpx.AsyncClient` para isolar o
    cookie jar — o warm-up é barato (1 GET) e evita carregar estado entre
    chamadas de fundos diferentes.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
        proxy: Optional[str] = None,
    ):
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        # Proxy URL (ex.: "http://user:pass@br-proxy.example.com:8080") usado
        # para rotear toda chamada FNET por um IP brasileiro quando o Railway
        # estiver geo-bloqueado pelo Cloudflare da B3. Quando None, conexão
        # direta (comportamento histórico). Aceita schemes http/https/socks5.
        self._proxy = proxy or None

    @staticmethod
    def _format_br_date(d: date) -> str:
        return d.strftime("%d/%m/%Y")

    @staticmethod
    def _digits_only(cnpj: str) -> str:
        return re.sub(r"\D", "", cnpj or "")

    async def list_documents(
        self,
        cnpj: str,
        date_start: date,
        date_end: date,
        tipo_fundo: int = 1,  # 1 = FII
        page_size: int = 200,
        *,
        cached_internal_id: Optional[int] = None,
        cached_canonical_name: Optional[str] = None,
    ) -> tuple[list[FnetDocument], int, str]:
        """
        Lista todos os documentos do fundo `cnpj` entregues entre `date_start`
        e `date_end` (inclusive). Faz paginação automática se houver mais que
        `page_size` registros.

        Quando `cached_internal_id` e `cached_canonical_name` são informados,
        o autocomplete `listarFundos` é PULADO (economia de 1 round-trip por
        fundo na sync diária). Em caso de 4xx no search com os valores
        cacheados (raro — search ignora idFundo/cnpj e devolve dados
        independente), cai automaticamente no autocomplete para revalidar.

        Retorna `(documentos, idFundo_resolvido, nome_canônico_resolvido)` —
        o caller (sync) deve persistir os dois últimos quando diferirem dos
        cacheados, para refresh automático em mudanças de cadastro da B3.

        Levanta `FnetClientError` em caso de falha persistente após retries,
        ou `FnetFundNotFoundError` se o CNPJ não for encontrado no FNET.
        """
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            proxy=self._proxy,
        ) as http:
            csrf = await self._warm_session(http)

            # Resolve CNPJ → (idFundo, nome_canônico). Mandamos idFundo no
            # search (o backend ACEITA o param sem reclamar) e usamos o nome
            # canônico para filtrar client-side — porque a B3 ignora idFundo
            # e cnpjFundo na resposta vem `null`, então a única forma de
            # garantir que não trazemos doc de outro fundo é match por nome.
            if cached_internal_id and cached_canonical_name:
                id_fundo = int(cached_internal_id)
                canonical_name = cached_canonical_name
                logger.debug(
                    "[FNET] Cache hit para CNPJ %s → idFundo=%d (%s) — "
                    "pulando autocomplete listarFundos",
                    cnpj,
                    id_fundo,
                    canonical_name[:60],
                )
            else:
                resolved = await self._resolve_fund(
                    http, csrf=csrf, cnpj=cnpj, tipo_fundo=tipo_fundo
                )
                if resolved is None:
                    raise FnetFundNotFoundError(
                        f"CNPJ {cnpj} (tipoFundo={tipo_fundo}) não encontrado no "
                        f"autocomplete do FNET (listarFundos). Verifique o cadastro."
                    )
                id_fundo, canonical_name = resolved

            try:
                all_docs = await self._fetch_documents_paged(
                    http,
                    csrf=csrf,
                    cnpj=cnpj,
                    id_fundo=id_fundo,
                    tipo_fundo=tipo_fundo,
                    date_start=date_start,
                    date_end=date_end,
                    page_size=page_size,
                )
            except FnetClientError as exc:
                # Fallback: se o search bateu 4xx usando valores cacheados,
                # talvez o idFundo tenha sido recriado na B3. Re-resolve e
                # tenta de novo uma única vez.
                used_cache = bool(cached_internal_id and cached_canonical_name)
                is_4xx = isinstance(exc, FnetClientError) and " HTTP 4" in str(exc)
                if used_cache and is_4xx:
                    logger.warning(
                        "[FNET] 4xx no search com cache (idFundo=%d) — "
                        "revalidando via listarFundos: %s",
                        id_fundo,
                        exc,
                    )
                    resolved = await self._resolve_fund(
                        http, csrf=csrf, cnpj=cnpj, tipo_fundo=tipo_fundo
                    )
                    if resolved is None:
                        raise FnetFundNotFoundError(
                            f"CNPJ {cnpj} (tipoFundo={tipo_fundo}) não encontrado "
                            f"no autocomplete do FNET após 4xx com cache."
                        ) from exc
                    id_fundo, canonical_name = resolved
                    all_docs = await self._fetch_documents_paged(
                        http,
                        csrf=csrf,
                        cnpj=cnpj,
                        id_fundo=id_fundo,
                        tipo_fundo=tipo_fundo,
                        date_start=date_start,
                        date_end=date_end,
                        page_size=page_size,
                    )
                else:
                    raise

            name_needle = self._normalize_for_match(
                self._strip_listar_prefix(canonical_name)
            )

        # Salvaguarda obrigatória: o search da B3 ignora `idFundo`/`cnpj` e
        # devolve documentos de QUALQUER fundo do período. Sem este filtro,
        # uma sync de 1 fundo plantaria centenas de Materiais de terceiros.
        # Match por substring normalizada do nome canônico vindo do
        # autocomplete contra `descricao_fundo` da resposta — é o único
        # campo identificador presente (cnpjFundo/idFundo vêm `null`).
        filtered = [
            d for d in all_docs
            if name_needle
            and name_needle in self._normalize_for_match(d.descricao_fundo)
        ]
        dropped = len(all_docs) - len(filtered)
        if dropped:
            logger.info(
                "[FNET] Filtro client-side por nome '%s' descartou %d/%d "
                "documento(s) de outros fundos (idFundo=%d).",
                canonical_name[:60],
                dropped,
                len(all_docs),
                id_fundo,
            )
        return filtered

    async def download_document(self, document_id: int) -> tuple[bytes, str]:
        """
        Baixa o PDF do documento `document_id`. Retorna `(bytes, suggested_filename)`.
        `suggested_filename` é extraído de Content-Disposition quando disponível,
        ou cai para `fnet_{id}.pdf`.

        O download também passa pelo warm-up — sem cookies de sessão a B3
        responde 403 (Cloudflare bloqueia o "deep link" direto ao PDF).
        """
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
            proxy=self._proxy,
        ) as http:
            csrf = await self._warm_session(http)
            response = await self._raw_get_with_retry(
                http,
                FNET_DOWNLOAD_URL,
                params={"id": str(document_id)},
                csrf_token=csrf,
                rewarm_callback=self._warm_session,
            )

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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _fetch_documents_paged(
        self,
        http: httpx.AsyncClient,
        *,
        csrf: str,
        cnpj: str,
        id_fundo: int,
        tipo_fundo: int,
        date_start: date,
        date_end: date,
        page_size: int,
    ) -> list[FnetDocument]:
        """
        Pagina o `pesquisarGerenciadorDocumentosCVMRequest` e devolve a lista
        bruta de documentos (sem o filtro client-side por nome). Extraído de
        `list_documents` para permitir retry com revalidação do idFundo na
        rota de fallback após 4xx com cache.
        """
        all_docs: list[FnetDocument] = []
        start = 0
        draw = 1

        while True:
            # Formato compacto exigido pelo `prepararRequisicaoDataTables`
            # do JS oficial: d=draw, s=start, l=length. Junto com os
            # filtros que a página manda quando o usuário busca por CNPJ.
            params = {
                "d": draw,
                "s": start,
                "l": page_size,
                "tipoFundo": tipo_fundo,
                "idFundo": id_fundo,
                "cnpj": cnpj,
                "cnpjFundo": cnpj,
                "dataInicial": self._format_br_date(date_start),
                "dataFinal": self._format_br_date(date_end),
                "paginaCertificados": "false",
                "isSession": "true",
            }
            payload = await self._json_get_with_retry(
                http,
                FNET_SEARCH_URL,
                params=params,
                csrf_token=csrf,
                # On 401/403/expired session, warm one more time and reuse.
                rewarm_callback=self._warm_session,
            )
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

    async def _warm_session(self, http: httpx.AsyncClient) -> str:
        """
        Faz o GET em `abrirGerenciadorDocumentosCVM` e devolve o `csrf_token`
        extraído do HTML. Cookies emitidos vão direto para o jar do `http`.

        Usa headers de navegação top-level (Sec-Fetch-Site: none, sem Origin/
        XHR-flags) — sem isso o Cloudflare na frente do FNET trata como bot
        e devolve 403 já aqui, sequer chega ao app da B3.

        Levanta `FnetClientError` (com `status_code` quando aplicável) em
        qualquer falha — nada de `httpx.HTTPStatusError` escapa pra cima.
        """
        last_exc: Optional[Exception] = None
        warm_headers = _warmup_headers()
        for attempt in range(1, self._max_retries + 1):
            try:
                r = await http.get(FNET_WARMUP_URL, headers=warm_headers)
                if r.status_code in (500, 502, 503, 504, 520, 521, 522, 524):
                    raise FnetTransientError(
                        f"FNET warmup HTTP {r.status_code} (tentativa {attempt})",
                        status_code=r.status_code,
                    )
                # 4xx no warm-up = anti-bot/geo-block do Cloudflare. Embrulha
                # explicitamente em FnetClientError (com diag headers) — antes
                # `r.raise_for_status()` lançava httpx.HTTPStatusError cru que
                # escapava do client inteiro até o `except Exception` do sync.
                if r.status_code >= 400:
                    diag = _extract_diag_headers(r)
                    raise FnetClientError(
                        f"FNET warmup HTTP {r.status_code} em {FNET_WARMUP_URL} "
                        f"(tentativa {attempt}) diag={diag} "
                        f"body[:200]={r.text[:200]!r}",
                        status_code=r.status_code,
                    )
                m = _CSRF_REGEX.search(r.text)
                if not m:
                    raise FnetClientError(
                        "Warmup FNET veio sem csrf_token — formato da página "
                        f"pode ter mudado (HTTP {r.status_code}, "
                        f"len={len(r.text)})",
                        status_code=r.status_code,
                    )
                token = m.group(1)
                logger.debug(
                    "[FNET] warm-up OK (cookies=%s, csrf=%s...)",
                    list(http.cookies.keys()),
                    token[:8],
                )
                return token
            except (FnetTransientError, httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff ** attempt)
                continue
        raise FnetClientError(
            f"Falha persistente no warm-up FNET após {self._max_retries} "
            f"tentativas: {last_exc}",
            status_code=getattr(last_exc, "status_code", None),
        ) from last_exc

    async def _resolve_fund(
        self,
        http: httpx.AsyncClient,
        *,
        csrf: str,
        cnpj: str,
        tipo_fundo: int,
    ) -> Optional[tuple[int, str]]:
        """
        Resolve CNPJ → (idFundo, nome_canônico) via o autocomplete
        `listarFundos`. Empiricamente o FNET aceita o CNPJ no campo `term`
        APENAS no formato só-dígitos (ex.: "36501128000186") — a versão
        formatada ("XX.XXX.XXX/XXXX-XX") retorna sempre 0 resultados.
        Tentamos só-dígitos primeiro e caímos para o que veio do cadastro
        como fallback.

        Quando vários candidatos voltam (classes e o fundo-pai), preferimos
        a entrada cujo `text` começa com o prefixo correspondente ao tipo
        (ex.: "FII ", "FIDC ", "FIP " — a B3 prefixa o ticker do fundo-pai
        assim no autocomplete). Sem essa desambiguação, um CNPJ de FIDC
        poderia ser resolvido para uma classe subsidiária listada antes,
        fazendo o sync baixar documentos do fundo errado.

        Retorna o tuple ou None se nenhum match (CNPJ inexistente ou
        cadastrado em outra `idTipoFundo`).
        """
        # Import tardio para evitar ciclo (este módulo é genérico do FNET,
        # o mapa fica em services/fnet_fund_types.py).
        from services.fnet_fund_types import prefix_for

        prefix = prefix_for(tipo_fundo)

        candidates: list[str] = []
        digits = self._digits_only(cnpj)
        if digits:
            candidates.append(digits)
        if cnpj and cnpj != digits:
            candidates.append(cnpj)

        for term in candidates:
            payload = await self._json_get_with_retry(
                http,
                FNET_LIST_FUNDS_URL,
                params={
                    "term": term,
                    "page": 1,
                    "idTipoFundo": tipo_fundo,
                    "idAdm": 0,
                    "paraCerts": "false",
                },
                csrf_token=csrf,
                rewarm_callback=self._warm_session,
            )

            results = payload.get("results") or []
            if not results:
                continue

            # Prefere o fundo-pai cujo `text` começa com o prefixo do tipo
            # (ex.: "FIDC ..." quando tipo_fundo=3). Se nenhum bate, cai
            # para o primeiro resultado (comportamento histórico).
            preferred = None
            if prefix:
                preferred = next(
                    (r for r in results if str(r.get("text", "")).startswith(prefix)),
                    None,
                )
            if preferred is None:
                preferred = results[0]
            try:
                fund_id = int(preferred.get("id"))
            except (TypeError, ValueError):
                continue
            text = str(preferred.get("text") or "").strip()
            logger.debug(
                "[FNET] CNPJ %s (tipo=%d) → idFundo=%d (%s)",
                cnpj,
                tipo_fundo,
                fund_id,
                text[:60],
            )
            return fund_id, text
        return None

    @staticmethod
    def _strip_listar_prefix(text: str) -> str:
        """
        O `listarFundos` devolve nomes como
            "FII RZTR - FUNDO DE INVESTIMENTO IMOBILIÁRIO RIZA TERRAX"
        e o search devolve só "FUNDO DE INVESTIMENTO IMOBILIÁRIO RIZA TERRAX"
        em `descricaoFundo`. Removemos o prefixo "PREFIX - " quando presente
        para que o match client-side encontre o nome no campo do search.
        """
        if " - " in text:
            return text.split(" - ", 1)[1].strip()
        return text.strip()

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """
        Normaliza string para match insensível a caixa, acentos e espaços
        em excesso. Usado só na comparação interna — não muta o que vai
        para o banco.
        """
        import unicodedata

        if not text:
            return ""
        # Remove acentos (NFKD) e baixa case
        no_accents = "".join(
            ch for ch in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(ch)
        ).lower()
        # Colapsa whitespace
        return re.sub(r"\s+", " ", no_accents).strip()

    async def _json_get_with_retry(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any],
        csrf_token: str,
        rewarm_callback: Optional[Any] = None,
    ) -> dict[str, Any]:
        """
        GET que espera resposta JSON. Trata 5xx como transitório (backoff),
        e 401/403 como "sessão expirada": tenta refazer o warm-up uma vez
        antes de desistir (re-warm não conta como retry transitório).
        """
        r = await self._raw_get_with_retry(
            http,
            url,
            params=params,
            csrf_token=csrf_token,
            rewarm_callback=rewarm_callback,
        )
        try:
            return r.json()
        except ValueError as e:
            raise FnetClientError(
                f"Resposta não-JSON do FNET (GET {url}): "
                f"status={r.status_code}, "
                f"content_type={r.headers.get('content-type')!r}, "
                f"corpo[:200]={r.text[:200]!r}"
            ) from e

    async def _raw_get_with_retry(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any],
        csrf_token: str,
        rewarm_callback: Optional[Any] = None,
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        rewarmed = False
        attempt = 0
        token = csrf_token
        while attempt < self._max_retries:
            attempt += 1
            try:
                r = await http.get(
                    url,
                    params=params,
                    headers={"CSRFToken": token},
                )
                # 5xx → transitório (com backoff).
                if r.status_code in (500, 502, 503, 504, 520, 521, 522, 524):
                    raise FnetTransientError(
                        f"FNET {r.status_code} em GET {url} (tentativa {attempt})",
                        status_code=r.status_code,
                    )
                # 401/403 → sessão expirada/derrubada pela B3. Tenta um único
                # re-warm; se ainda falhar, propaga como FnetClientError. Não
                # conta como retry transitório (sem backoff exponencial).
                if r.status_code in (401, 403) and rewarm_callback and not rewarmed:
                    logger.info(
                        "[FNET] HTTP %s em %s — sessão expirada, refazendo warm-up",
                        r.status_code,
                        url,
                    )
                    token = await rewarm_callback(http)
                    rewarmed = True
                    # Recompensa essa tentativa para que o re-warm não consuma
                    # o budget — efetivamente "uma chance extra" pós-re-warm.
                    attempt -= 1
                    continue
                # 4xx residual (incluindo 401/403 após re-warm) — não é
                # transitório, mas precisa virar FnetClientError para o
                # caller (fnet_sync) tratar via except FnetClientError em
                # vez de deixar httpx.HTTPStatusError escapar e poluir o
                # log com "pending" sem mark_failed.
                if r.status_code >= 400:
                    diag = _extract_diag_headers(r)
                    raise FnetClientError(
                        f"FNET HTTP {r.status_code} em GET {url} "
                        f"(rewarmed={rewarmed}) diag={diag} "
                        f"body[:200]={r.text[:200]!r}",
                        status_code=r.status_code,
                    )
                return r
            except (FnetTransientError, httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(self._retry_backoff ** attempt)
                continue
        raise FnetClientError(
            f"Falha persistente em GET {url} após {self._max_retries} "
            f"tentativas: {last_exc}",
            status_code=getattr(last_exc, "status_code", None),
        ) from last_exc

    @staticmethod
    def _extract_filename(content_disposition: Optional[str]) -> Optional[str]:
        if not content_disposition:
            return None
        # Padrão FNET: attachment; filename="CNPJ-CODIGO-NNNN.pdf"
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', content_disposition)
        if m:
            return m.group(1).strip()
        return None


class FnetClientError(RuntimeError):
    """
    Erro de comunicação com o FNET após esgotar retries.

    `status_code` é preenchido quando o erro tem origem numa resposta HTTP
    do servidor (4xx/5xx); fica `None` para erros de transporte/parse.
    Callers (ex.: fnet_sync) usam isso pra distinguir 401/403 — que merecem
    mensagem amigável de "FNET bloqueou a sessão" — de outros erros.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class FnetTransientError(FnetClientError):
    """Erro transitório (5xx, timeout) — passível de retry."""


class FnetFundNotFoundError(FnetClientError):
    """CNPJ não encontrado no autocomplete `listarFundos` do FNET."""
