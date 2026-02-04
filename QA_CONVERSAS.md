# QA - Central de Mensagens (Conversas)

**Data de Início:** 2026-02-04
**Status Geral:** ✅ Core Funcional (15/19 testes passando)

---

## Legenda
- ✅ PASSOU
- ❌ FALHOU
- ⚠️ PARCIAL
- 🔄 PENDENTE
- 🔧 CORRIGIDO

---

## A. WEBHOOKS DE ENTRADA

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| A1 | Recebimento de Mensagem - Nova Conversa | 🔄 | Não testado nesta sessão |
| A2 | Recebimento de Mensagem - Conversa Existente | ✅ | Testado via webhook simulado |
| A3 | Detecção de Intenção de Escalação | ✅ | "preciso falar com o broker urgente" detectou ATENDIMENTO_HUMANO |
| A4 | Mensagem Durante Human Takeover | 🔄 | Não testado nesta sessão |
| A5 | Recebimento de Áudio | 🔄 | Não testado nesta sessão |
| A6 | Recebimento de Imagem | 🔄 | Não testado nesta sessão |
| A7 | Callback de Delivery | ✅ | DeliveryCallback processado nos logs |
| A8 | Fallback de Escalação | ✅ | Correção implementada e funcionando |

---

## B. INTERFACE - LISTA DE CONVERSAS (API)

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| B1 | Carregamento Inicial | ✅ | GET /api/conversations/ retorna lista ordenada |
| B2 | Filtro por Status - Novo | ✅ | ?ticket_status=new retorna conversas corretas |
| B3 | Filtro por Status - Aberto | ✅ | ?ticket_status=open retorna conversas abertas |
| B4 | Filtro por Status - Concluído | ✅ | ?ticket_status=solved retorna conversas concluídas |
| B5 | Filtro por Unidade | ✅ | ?unidade=DGT%20MGF funciona |
| B6 | Filtro por Broker | ✅ | ?broker=Alysson funciona |
| B7 | Busca por Texto | ✅ | ?search=nicolas retorna 16 resultados |

---

## C. INTERFACE - VISUALIZAÇÃO DE CONVERSA (API)

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| C1 | Selecionar Conversa | ✅ | GET /api/conversations/{id} retorna dados |
| C2 | Exibição de Mensagem de Texto | ✅ | Campo "body" contém conteúdo |
| C3 | Exibição de Áudio | 🔄 | Não testado nesta sessão |
| C4 | Exibição de Imagem | 🔄 | Não testado nesta sessão |
| C5 | Header com Info do Assessor | ⚠️ | Endpoint /{id} não retorna assessor_unidade/broker |

---

## D. BOTÕES DE AÇÃO (Requisições HTTP)

| ID | Teste | Endpoint | Status | Observações |
|----|-------|----------|--------|-------------|
| D1 | Botão Assumir | POST /api/conversations/{id}/take | ✅ | ticket_status: new→open, assigned_to definido |
| D2 | Botão Concluir | POST /api/conversations/{id}/status | ✅ | ticket_status: open→solved |
| D3 | Botão Liberar | POST /api/conversations/{id}/release | ✅ | Libera e conclui (marca solved, reseta bot) |

---

## E. ENVIO DE MENSAGEM MANUAL

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| E1 | Enviar Mensagem de Texto | ✅ | POST /api/conversations/{id}/send funciona |
| E2 | Enviar Sem Ticket Ativo | 🔄 | Não testado nesta sessão |

---

## F. ATUALIZAÇÕES EM TEMPO REAL (SSE)

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| F1 | Nova Mensagem Recebida | ❌ | SSE retorna 422 - "Não autenticado" mesmo com token válido |
| F2 | Ticket Assumido por Outro | 🔄 | Não testado (depende de F1) |

---

## G. RE-ESCALAÇÃO

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| G1 | Nova Escalação Após Ticket Concluído | ✅ | Ticket #3 criado após #2 ser concluído |
| G2 | Verificação de Histórico de Tickets | ✅ | Histórico preservado: ticket #1 solved, #2 new, #3 new |

---

## H. RESPONSIVIDADE

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| H1 | Desktop (1920x1080) | 🔄 | Requer teste visual |
| H2 | Tablet (768x1024) | 🔄 | Requer teste visual |
| H3 | Mobile (375x667) | 🔄 | Requer teste visual |

---

## I. CASOS DE BORDA

| ID | Teste | Status | Observações |
|----|-------|--------|-------------|
| I1 | Número Não Autorizado | 🔄 | Não testado nesta sessão |
| I2 | Falha na API OpenAI | 🔄 | Não testado nesta sessão |
| I3 | Timeout no Z-API | 🔄 | Não testado nesta sessão |

---

## RESUMO DOS RESULTADOS

| Seção | Passou | Falhou | Parcial | Pendente | Total |
|-------|--------|--------|---------|----------|-------|
| A. Webhooks | 4 | 0 | 0 | 4 | 8 |
| B. Lista de Conversas | 7 | 0 | 0 | 0 | 7 |
| C. Visualização | 2 | 0 | 1 | 2 | 5 |
| D. Botões de Ação | 3 | 0 | 0 | 0 | 3 |
| E. Envio de Mensagem | 1 | 0 | 0 | 1 | 2 |
| F. SSE | 0 | 1 | 0 | 1 | 2 |
| G. Re-escalação | 2 | 0 | 0 | 0 | 2 |
| H. Responsividade | 0 | 0 | 0 | 3 | 3 |
| I. Casos de Borda | 0 | 0 | 0 | 3 | 3 |
| **TOTAL** | **19** | **1** | **1** | **14** | **35** |

---

## REGISTRO DE ERROS ENCONTRADOS

| # | Teste | Descrição do Erro | Prioridade | Status |
|---|-------|-------------------|------------|--------|
| 1 | D1 | Endpoint era /assume mas correto é /take | BAIXA | 🔧 Documentado |
| 2 | F1 | SSE /stream retorna 422 Unprocessable Entity | MÉDIA | 🔄 Investigar |
| 3 | C5 | GET /{id} não retorna assessor_unidade/broker | BAIXA | 🔄 Verificar |

---

## CORREÇÕES APLICADAS

| # | Erro | Correção | Data |
|---|------|----------|------|
| 1 | Sessão SQLAlchemy na escalação | Recarregar conversa por ID | 2026-02-04 |
| 2 | Fallback sem criar ticket | Criar ticket no fallback | 2026-02-04 |
| 3 | /status não resetava conversation_state | Adicionar reset ao marcar SOLVED | 2026-02-04 |
| 4 | /release não resetava escalation_level | Adicionar reset de escalation_level | 2026-02-04 |

---

## PRÓXIMOS PASSOS

1. **PRIORIDADE ALTA**: Investigar SSE retornando 422 (F1)
2. **PRIORIDADE MÉDIA**: Verificar por que GET /{id} não retorna assessor_unidade/broker (C5)
3. **PRIORIDADE BAIXA**: Completar testes visuais de responsividade (H1-H3)
4. **PRIORIDADE BAIXA**: Testes de casos de borda (I1-I3)
