---
name: FNET deploy/diagnose checklist
description: Como destravar bug no pipeline FNET quando código local difere do que está rodando em produção (Railway).
---

# Pipeline FNET — checklist de diagnóstico

Quando o usuário relatar erro persistente em produção mesmo após deploy
(ex.: "ainda dá `not enough values to unpack` no card RIZA TERRAX"),
**não** assuma que o bytecode foi atualizado.

## Ordem de verificação

1. **Comparar bytecode**: `GET /api/fnet/version` em produção devolve SHA-256
   dos módulos críticos. Se o hash diferir do `git show HEAD:services/fnet_sync.py | sha256sum`
   local, o deploy não pegou — invalidar cache do Railway antes de qualquer
   nova mudança de código.
2. **Auto-diagnóstico por fundo**: `POST /api/fnet/diagnose/{fund_id}` faz
   dry-run completo (warm-up → autocomplete → search → download) sem
   persistir. Timeline em pt-BR identifica em qual etapa o pipeline cai
   para aquele CNPJ específico — separa "B3 indisponível" de "bug no
   nosso código" de "Cloudflare bloqueando IP".
3. **Histórico técnico**: cada `FnetSyncLog` com `status='failed'` carrega
   `error_traceback` (Python `traceback.format_exc()` truncado a 8KB).
   Exibido sob demanda no `<details>` "Ver detalhe técnico" do histórico
   por fundo. Útil quando a mensagem curta (`error_message`) não basta.
4. **Separar última tentativa do histórico**: `FnetSyncLog.run_id`
   (UUID por execução do `run_sync`) permite à UI destacar a "última
   tentativa" do "histórico antigo" — evita o usuário ler ruído de
   tentativas falhas de semanas atrás como se fosse o problema atual.

## Idempotência conhecida do pipeline

- `_create_material_and_enqueue` reusa `Material` existente quando o
  `file_hash` do PDF já está no banco. Fecha a janela em que `_mark_log_failed`
  cobria erros transitórios mas o `Material` já tinha sido criado num
  run anterior — sem esta proteção, retries criavam "phantom materials"
  duplicados que poluíam a base de conhecimento.
- UPSERT do `_persist_fund_level_failure` usa `COALESCE(EXCLUDED.x, fnet_sync_logs.x)`
  para `error_traceback` e `run_id` — uma falha posterior sem traceback
  detalhado NÃO apaga o diagnóstico útil da primeira ocorrência do mês.

## O que NÃO refatorar sem novo planning

- Não trocar o lock global `pg_advisory_lock` do FNET por Redis ou
  scheduler distribuído — escopo atual é single-replica; multi-replica
  é trabalho futuro de plataforma.
- O proxy `FNET_HTTP_PROXY` é opcional e seguro: sem ele, conexão direta
  da Railway funciona para a maioria dos fundos. Falha geográfica do
  FNET é cara visível na timeline do diagnóstico (etapa `listar_documentos`
  com HTTP 401/403). Antes de configurar proxy, sempre confirmar via
  diagnose que o problema é realmente de geo-block.

## Limpeza de histórico

- `DELETE /api/fnet/sync-log?fund_id=X&status=failed[&before=ISO]` é a
  ÚNICA forma de remover logs FNET via API. Apenas `status='failed'` é
  aceito por segurança — sucesso/pulado/pendente nunca podem ser
  apagados (preservam dedup e auditoria).
