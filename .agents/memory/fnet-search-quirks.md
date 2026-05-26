---
name: FNET (B3) search endpoint quirks
description: Como falar com o gerenciador de documentos CVM da B3 (FNET) sem ser bloqueado nem trazer documentos de outros fundos.
---

# Contrato real do `pesquisarGerenciadorDocumentosCVMRequest`

- **Método é GET, não POST.** O JS oficial (`gerenciador-documentos-cvm.js`) usa DataTables com `serverSide: true`, que emite GET com querystring compacta `d=draw&s=start&l=length`.
- **Exige cookies de sessão + header `CSRFToken`.** Faça um GET de warm-up em `abrirGerenciadorDocumentosCVM` antes; o HTML traz `var csrf_token="..."` que precisa ir no header em todas as chamadas subsequentes (search, download, autocomplete).
- **Nomes de parâmetros de data são `dataInicial`/`dataFinal`** (sem acento, com "l" no final) — qualquer outra variante (dataInicio/dataFim) é silenciosamente ignorada.
- **Inclua `Origin: https://fnet.bmfbovespa.com.br`** nos headers junto com Referer; sem isso o servidor passa a devolver 403 intermitentes.

## Bug crítico: filtros server-side de fundo são ignorados

O endpoint aceita `idFundo` e `cnpj` na querystring sem reclamar (200 OK) mas **devolve documentos de TODOS os fundos do período** — verificado em 2026-05 com `idFundo=21346` retornando 359 docs onde o primeiro era de outro emissor.

Pior: `cnpjFundo` e `idFundo` voltam **null em cada item da resposta**, então não dá pra filtrar por CNPJ no cliente. O único identificador presente é `descricaoFundo` (string).

**Como filtrar:** resolva o CNPJ via `listarFundos?term=<DIGITS>` (formato com pontuação retorna 0 — só dígitos funciona), pegue o `text` do match (formato `"FII TICKER - NOME COMPLETO"`), faça `split(" - ", 1)[1]` para extrair o nome canônico, normalize (NFKD + casefold + collapse whitespace) e mantenha só itens cujo `descricaoFundo` normalizado contenha esse nome como substring.

**Por que:** sem essa salvaguarda, uma sync de 1 fundo planta centenas de Materiais de terceiros no CMS. O incidente que motivou: produção respondia 403 → quando destravamos para 200 corrigindo warm-up/CSRF, descobrimos que o filtro server-side já estava quebrado havia tempo, apenas mascarado pelo 403.

**Como aplicar:** sempre que adicionar um novo método que consome listagens do FNET, replicar o passo de resolução `_resolve_fund()` + filtro client-side por nome. Nunca confiar em `idFundo`/`cnpj` no params sozinhos.

## Autocomplete `listarFundos`

- `term` aceita apenas dígitos para CNPJ; formato XX.XXX.XXX/XXXX-XX → 0 resultados.
- Para um CNPJ pode voltar várias linhas (fundo-pai + classes). Prefira a entrada cujo `text` começa com `"FII "` — é o fundo-pai. Caso contrário, pega a primeira e correr o risco de bater em uma classe subsidiária.
- `idTipoFundo` (não `tipoFundo`) é o nome do param aqui — confuso porque no search é `tipoFundo`.

## 401/403 com sessão expirada

A sessão dura poucos minutos. Implementar retry com 1 re-warm "fora do budget" quando vier 401/403: não consome retry de transient, apenas refaz o warm e tenta de novo. Se ainda assim falhar, aí sim conta como falha real.
