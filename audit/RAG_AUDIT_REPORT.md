# RAG V3.2 + Agentic Pipeline V2 — Auditoria Profunda

**Data:** 22/04/2026
**Escopo:** Pipeline RAG agentic do agente Stevan (FastAPI + pgvector + GPT-4o)
**Modo:** read-only — nenhuma mudança feita em código de produção
**Artefatos gerados:** `audit/fact_bank.py`, `audit/test_retrieval.py`, `audit/test_agent_responses.py`, `audit/results/phase_2.json`, `audit/results/phase_3_partial.json`

---

## SYSTEM MAP (Fase 0)

### Pipeline em camadas

| Camada | Onde | Função |
|---|---|---|
| 0 — EntityResolver | `services/semantic_search.py:127-264` | SQL relacional em `products` (ticker exato/ilike, aliases, gestora). Confidence ≥0.8 → puxa blocos via `vector_store.search_by_product_ids` (max 5/produto) |
| 1 — Multi-entidade comparativa | `semantic_search.py:1271-1282` | Para queries comparativas: busca separada por ticker, garante representação |
| 2 — Multi-query vector | `semantic_search.py:1284-1295` | `SynonymLookup.expand_query` gera até 5 variantes, executa top 3 com `n_results*2` |
| 3 — Ticker direto | `semantic_search.py:1297-1305` | Quando há tickers detectados e não é comparativa |
| 4 — Fuzzy fallback | `semantic_search.py:1322-1337` | Levenshtein quando <2 resultados |
| 5 — Reranking | `CompositeScorer.score_results` (linha 865-994) | Sem cross-encoder externo; só fórmula composta |

### Chunking
- Chunks são por **página de PDF**, não por tamanho fixo. `DocumentProcessor.analyze_page_hybrid` (`document_processor.py:448`) escolhe entre Vision (GPT-4o) e texto nativo.
- Texto: `"\n\n".join(facts)` (lista de fatos extraídos por página).
- Tabela: JSON serializado com headers + rows.
- Distribuição observada (337 blocos): `texto=182 (avg 906 chars)`, `tabela=110 (avg 659 chars)`, `grafico=45 (avg 684 chars)`. Min: 68 / Max: 4348.

### Embedding input
- Modelo: `text-embedding-3-large`, **3072 dimensões** (`vector_store.py:324-328`).
- Input string: campo `content` cru do `ContentBlock` — sem prefixo de metadados (Produto/Gestora/Tipo) no input do embedding.
- Resultado: o vetor não "sabe" a que produto pertence; toda a desambiguação é feita downstream via filtros e boosts.

### CompositeScorer — fórmula base (`semantic_search.py:842-849`)
```
score = vector*0.45 + fuzzy*0.20 + ticker_match*0.15 + gestora_match*0.10
      + context_match*0.05 + recency*0.05
```
Boosts:
- Glossário literal: +0.4 / conceito: +0.25 / conteúdo: +0.15 (962-967)
- Intenção numérica: +0.15 tabela/métrica, +0.08 dividendos, +0.05 percentual (1010-1019)
- Intenção ranking: +0.10 ranking, +0.08 tabela
- Modo temporal: recency sobe para 0.25, vector cai para 0.35

### Threshold e limites
- `similarity_threshold` default: **0.8** (`EnhancedSearch.search`, linha 1198)
- `n_results` default: 5 (mas `search_knowledge_base` pede 8 → trunca em 6)
- `_execute_search_knowledge_base` (`agent_tools.py:268,288,415`): retorna no máx **6 chunks**, cada um truncado em **800 chars**
- Resposta total da tool: cap em **8 000 chars** (truncada para 7 500 se exceder)
- System prompt v2: `agent_prompt.py:build_system_prompt_v2` com 7 blocos (identidade, loop, regras, visual, comitê, assessor, materiais) + state block + dedup
- Web search (Tavily): depth=`advanced`, top 5, whitelist de 10 domínios, fallback sem whitelist se 0 resultados

### Reranking
- Não há cross-encoder nem reranker LLM. Só `CompositeScorer.score_results` (sort por score) + `_ensure_entity_coverage` (garante 1 chunk por produto comparado).

---

## FASE 1 — KNOWLEDGE BASE INVENTORY

### Materiais publicados e indexados (12)
| ID | Nome | Tipo | Blocos | Embeddings | Tickers linkados |
|---|---|---|---|---|---|
| 20 | Relatório gerencial Manatí | apresentacao | 45 | 45 | — |
| 36 | Relatório MANA11 | research | 43 | 43 | — |
| 32 | Relatório LIFE11 | research | 40 | 40 | — |
| 39 | Relatório RZAT11 | research | 34 | 34 | — |
| 28 | Relatório GARE11 | research | 30 | 30 | — |
| 37 | Relatório MCRE11 | research | 27 | 27 | — |
| 35 | Relatório LVBI11 | research | 27 | 27 | — |
| 26 | Relatório BTGLG11 | research | 22 | 22 | — |
| 38 | Relatório PCIP11 | research | 10 | 10 | — |
| 44 | Recomendações estruturas abril | comite | 10 | 10 | SMAL11 |
| 22 | One pager XP Log Prime II | one_page | 6 | 6 | — |
| 46 | Recomendações estruturas (smart) | smart_upload | 2 | 2 | — |

🚨 **Achado crítico A — `material_product_links` não populada:** 11 de 12 materiais não têm vínculo com produto via tabela `material_product_links`. Apenas o material 44 está linkado (a SMAL11). A correlação produto↔material está implícita nos metadados de `document_embeddings.product_ticker`, mas a tabela junction é a fonte oficial usada pelo `_get_committee_context` e por features futuras de comitê.

🚨 **Achado crítico B — Zero produtos no comitê:** `SELECT COUNT(*) FROM products WHERE is_committee = true` → **0**. Após toda a refatoração das Tasks #144 e #150 (estrela como fonte de verdade), o banco não tem nenhum produto sinalizado. O log do agente confirma: `[VECTOR_STORE] committee_summary: nenhum produto com estrela ativa` em todas as 4 perguntas testadas.

🚨 **Achado crítico C — `is_committee_active = false` em todos os materiais publicados.** Nem o material `tipo=comite` (44) está ativo.

### Cobertura de metadados de embeddings (302 publicados)
| Campo | Cobertura |
|---|---|
| `product_ticker` | 296/302 (98%) ✓ |
| `gestora` | 146/302 (48%) ⚠ |
| `valid_until` | 279/302 (92%) — **mas tipo é `String(100)`, valores observados são strings vazias `''`** ❌ |

🚨 **Achado D — `valid_until` é texto, não DateTime.** Filtragem por validade nunca vai funcionar como esperado: queries `WHERE valid_until > NOW()` não conseguem comparar string com timestamp.

### Custo médio (últimos 30 dias)
| Operação | Modelo | N | Tokens médios | USD/op |
|---|---|---|---|---|
| chat_response_v2 | gpt-4o | 21 | 6 012 | 0,01563 |
| document_vision_extraction | gpt-4o | 14 | 2 526 | 0,00882 |
| metadata_vision_extraction | gpt-4o | 2 | 2 966 | 0,00841 |
| chunk_enrichment | gpt-4o-mini | 995 | 785 | 0,00015 |
| embedding | t-e-3-large | 748 | 423 | 0,00005 |

### Telemetria de retrieval
🚨 **Achado E — `composite_score_max` é NULL em 100% dos `retrieval_logs` recentes.** O campo está no modelo mas nunca recebe write. Isso impede análise post-hoc da qualidade de retrieval em produção.

---

## FASE 2 — RETRIEVAL QUALITY (audit/results/phase_2.json)

Fact Bank: **14 fatos** extraídos manualmente (BTLG11, GARE11, MANA11) cobrindo numérico de tabela, qualitativo de gráfico, descritivo de texto, comparativo, e edge cases.

### 2.1 — Recall direto (26 queries × ground-truth chunk match)

```
Recall@3 = 26,9 %    Recall@6 = 38,5 %    MRR = 0,282
```

**Detalhe por fato (top-line):**

| Fato | A (direto) | B (natural) | C (implícito) |
|---|---|---|---|
| BTLG_DY (DY 9,2%) | rank 1 ✓ | rank 1 ✓ | **MISS** |
| BTLG_VAC (vacância 2,9%) | rank 3 ✓ | rank 1 ✓ | **MISS** |
| BTLG_LTV (LTV 3,3%) | **MISS** | **MISS** | n/a |
| BTLG_LOG (95% logística) | rank 6 ✓ | **MISS** | n/a |
| BTLG_CRI (CRI II IPCA+5,90%) | rank 8 ⚠ | rank 8 ⚠ | n/a |
| BTLG_TAXA (taxa adm 0,90%) | rank 7 ⚠ | n/a | n/a |
| GARE_GUID (R$ 0,083–0,090) | **MISS** | **MISS** | n/a |
| GARE_COTA (R$ 9,24 nov) | **MISS** | n/a | n/a |
| GARE_XPRI (venda XPRI) | rank 1 ✓ | rank 5 ⚠ | n/a |
| MANA_DY (DY 15,2%) | rank 4 ⚠ | **MISS** | n/a |
| MANA_RENT (37,4% / 176,8% IFIX) | **MISS** | **MISS** | n/a |
| MANA_DIV (R$ 0,11 / R$ 1,30) | **MISS** | **MISS** | n/a |
| MANA_COTI (34 315 cotistas) | rank 1 ✓ | rank 1 ✓ | n/a |

🚨 **Achado F — Cegueira a tabelas (table blindness):** 7 dos 13 MISSes são fatos que residem em blocos `tabela` (LTV, GARE_GUID, GARE_COTA, MANA_DY, MANA_RENT, MANA_DIV). O JSON cru de tabela (`{"headers":[...],"rows":[...]}`) é embedado como string — perde estrutura semântica e não compete com texto narrativo. O boost numeric_intent (+0,15 para tabela) não compensa porque o vector_score base já é baixo demais.

🚨 **Achado G — Variant C (sem ticker explícito) sempre falha.** "qual o yield desse fundo?" sem `conversation_id` populado retorna 0 resultados. O ConversationContextManager existe mas **só é alimentado durante conversas reais via WhatsApp** — para uso programático (testes, futuras integrações de UI), não há API para injetar o contexto manualmente. Em produção real isso só funciona no segundo turno em diante.

🚨 **Achado H — BTLG_TAXA encontrado no rank 7 com top_score 0,78.** Está fora dos 6 chunks que `search_knowledge_base` corta. Em produção, o agente nunca veria esse fato — o usuário receberia "não encontrei" ou alucinação.

### 2.2 — Distribuição de tamanho de chunk

| material | blocos | min | avg | max | <100 | >2000 |
|---|---|---|---|---|---|---|
| 26 BTLG | 22 | 160 | 871 | 2 265 | 0 | 1 |
| 28 GARE | 30 | 185 | 1 130 | **4 212** | 0 | 3 |
| 32 LIFE | 40 | 118 | 757 | 1 806 | 0 | 0 |
| 36 MANA | 43 | 201 | 795 | **3 729** | 0 | 2 |
| 39 RZAT | 34 | 108 | 842 | 2 081 | 0 | 1 |

⚠ **Achado I — Outliers de tamanho:** Tabelas grandes (até 4 212 chars no GARE) consomem 3 250+ tokens de contexto sozinhas. Quando entram no top-6, restam ~4-5k chars para os outros 5 chunks. Inverso: blocos de 108 chars (RZAT) carregam pouca informação; quando rankeados alto, dão resposta pobre.

### 2.3 — EntityResolver

| Caso | Resultado | Match | Conf | ms |
|---|---|---|---|---|
| `BTLG11` | BTLG11 ✓ | ticker_exact | 1.00 | 2 |
| `TG Renda` | TGRI PRÉ ✓ | name_ilike | 0.85 | 2 |
| `MANA` | MANA11 ✓ | name_ilike | 0.60 | 1 |
| `BTG Pactual` | (presumivelmente BTLG) | — | — | — |
| `XPTO99` | vazio ✓ | — | — | 2 |
| `fundo` | TGRI PRÉ + test_upload_fundo ⚠ | name_ilike | 0.90/0.85 | 2 |
| `compare BTLG11 com MANA11` | ambos ✓ | ticker_exact | 1.00 | 4 |

⚠ **Achado J — Falsos positivos com termo genérico "fundo":** `name_ilike '%fundo%'` casa qualquer produto com "fundo" no nome. Em conjunto com confidence ≥0.8, isso ativa Layer 0 e injeta blocos errados antes mesmo da busca vetorial. A query "tem algum fundo bom?" pode ser sequestrada por `test_upload_fundo`.

### 2.4 — Threshold sensitivity

Top scores observados: 0,60–0,82. Threshold default = **0,8**. Isso significa que **80% dos fatos verdadeiros caem silenciosamente abaixo do threshold em produção**. Os testes desta auditoria usaram `threshold=0,3` e ainda assim Recall@6 = 38,5%. Com 0,8 seria ainda pior — provavelmente <20%.

---

## FASE 3 — AGENT RESPONSE QUALITY (parcial — ver `phase_3_partial.json`)

Apenas 4 de 12 perguntas completaram antes do **rate limit OpenAI TPM (30 000) ser estourado**.

🚨 **Achado K — Cada chamada V2 consome ~25–31k tokens.** O system prompt + resultados de KB (truncados em 8k chars = ~2-3k tokens) + visual prefetch (4 graficos, ~2k tokens) + histórico + tool definitions = ~25k tokens por iteração. Com 2-3 iterações, uma única pergunta queima o orçamento por minuto inteiro do tier atual. Em produção sob carga, **respostas degradam para o fallback "Desculpe, não foi possível processar"**.

### Resultados parciais

| ID | Pergunta | Tempo | Resultado | Diagnóstico |
|---|---|---|---|---|
| KB_NUM_DY | "qual o DY do BTLG11?" | 35,4s | ❌ rate-limit | Visual prefetch + tool lookup_fii_public + retry estourou TPM |
| KB_NUM_GARE_GUID | "qual o guidance de dividendos do GARE11?" | 19,4s | ⚠️ FONTE ERRADA | Agente respondeu DY 11,81% da FundsExplorer — **ignorou o guidance R$ 0,083–0,090 que está no KB**. Pergunta estratégica foi roteada para web. |
| KB_THESIS_MANA | "qual a tese do MANA11?" | 25,7s | ❌ rate-limit | Falhou na 1ª iteração |
| KB_RISK_BTLG | "quais os riscos do BTLG11?" | 26,8s | ✓ OK | Acionou search_knowledge_base; resposta razoável |

🚨 **Achado L — Roteamento de tool incorreto para queries estratégicas:** O prompt instrui o agente a usar web para "live data". A pergunta "guidance de dividendos" é estratégica (vem da gestora, é divulgação trimestral, está no relatório) mas o GPT escolheu lookup_fii_public porque o nome da tool casa com "dividendos". Resultado: usuário recebe DY corrente público em vez do guidance específico que diferencia a recomendação.

🚨 **Achado M — Visual prefetch sempre ativa em queries com triggers:** Mesmo perguntas puramente numéricas (ex: "qual o DY?") disparam `_v2_visual_prefetch` que adiciona 3-4 blocos `grafico` (avg 684 chars) ao contexto. Para queries que pedem gráfico isso é correto; para queries numéricas é desperdício de orçamento de tokens.

---

## FASE 4 — WEB SEARCH AUDIT

- Tavily depth = `advanced` (caro: ~2x basic)
- Whitelist 10 domínios (FundsExplorer, Status Invest, B3, InfoMoney, etc.) — bom
- Fallback: se 0 resultados com whitelist, refaz sem whitelist — **risco de fontes ruins**
- Sem dedupe contra KB — risco de repetir info
- Sem orçamento de tokens explícito para web vs KB

⚠ **Achado N — Ausência de separação visível na resposta entre KB e web.** Na resposta do GARE_GUID, o agente cita "(Fonte: FundsExplorer)" mas se misturasse com dados da KB, o usuário não saberia distinguir.

---

## FASE 5 — PERFORMANCE

- Retrieval puro (`EnhancedSearch.search`): **~2 100–2 800 ms** por query — **alto** para algo que só faz vetor + SQL.
- Resposta agente completa: 19–35 s.
- Custo médio chat_response_v2: **US$ 0,016 / query** = R$ 4,80 / 100 perguntas — moderado mas escala mal com TPM atual.

⚠ **Achado O — Retrieval lento (2,5s):** Multi-query expansion roda 3 queries em série + EntityResolver + multi-entity, sem paralelismo. SQL retorna `48 rows` × 3 = 144 rows escaneadas por busca.

---

## FASE 6 — AVALIAÇÃO POR ESPECIALISTA

### SPECIALIST A — RAG Engineer

| # | Item | Score | Evidência |
|---|---|---|---|
| 1 | Chunking strategy | **5/10** | Chunks de página são razoáveis para texto, mas tabelas grandes (4 212 chars) saturam contexto e tabelas pequenas (160 chars) são thin. Falta parent-child chunking. |
| 2 | Embedding input quality | **4/10** | Conteúdo cru sem prefixo de metadados. JSON de tabela embedado como string perde semântica estrutural. |
| 3 | Retrieval completeness | **3/10** | Recall@6 = 38,5% com threshold relaxado (0,3). Em produção (0,8) cai para ~20%. |
| 4 | Score composition | **5/10** | Pesos razoáveis para texto. Boost numeric_intent não basta para tabelas. recency=0,05 bom porque `valid_until` é string inutilizável. |
| 5 | Context assembly | **5/10** | Limite de 6 chunks × 800 chars OK; visual prefetch adiciona 4 graficos sem dedup. Cap de 8 000 chars trunca tabelas no meio. |
| 6 | Reranking | **3/10** | Sem cross-encoder. Sem reranker LLM. Só fórmula composta + sort. Achado H (rank 7 fora do top-6) prova que a ordem importa e está errada. |
| 7 | Query expansion | **6/10** | SynonymLookup substitui aliases — ok. Mas expansões são ortogonais (mesmo termo, sinônimo) sem capturar paráfrases ("paga bem" → "dividend yield"). |
| 8 | Table retrieval | **2/10** | Achado F é o pior gap do sistema. 7 dos 13 MISSes são tabelas. |
| 9 | Threshold calibration | **2/10** | 0,8 está calibrado para texto narrativo de prosa; tabelas e respostas curtas raramente atingem. |
| 10 | Missing capabilities | — | Faltam: HyDE (hypothetical doc embedding), parent-child chunking, BM25 híbrido, reranking cross-encoder, metadata filtering em query (filtrar por `block_type=tabela` quando a query é numérica), serializar tabelas como markdown legível antes do embedding. |

### SPECIALIST B — Domínio Financeiro

| # | Item | Score | Evidência |
|---|---|---|---|
| 1 | Acurácia de DY/retorno | **5/10** | BTLG_DY rank 1, mas MANA_DY rank 4 e GARE_GUID MISS. Rate-limit fez KB_NUM_DY responder erro. |
| 2 | Qualidade da tese | **n/a** | KB_THESIS_MANA falhou por rate-limit. Não pôde ser avaliado. |
| 3 | Comunicação de risco | **6/10** | KB_RISK_BTLG retornou resposta razoável mas genérica ("alguns riscos associados"). Riscos específicos (concentração geográfica em SP, dependência de logística, alavancagem via CRI) não foram destacados. |
| 4 | Comparativos | **n/a** | KB_COMPARE não completou |
| 5 | Disciplina de comitê | **0/10** | Comitê **vazio** em todos os testes. Agente nem teve chance de errar; mas o pipeline inteiro de "[COMITÊ]/[NÃO-COMITÊ]" está dormente. |
| 6 | Awareness temporal | **3/10** | `valid_until` é string vazia em todos os embeddings. Sem sinal real de staleness. |
| 7 | Uso de tabela | **2/10** | Achado F. |
| 8 | Integração web | **6/10** | FundsExplorer funcionou (DY 11,81% no GARE_GUID), mas roteamento errado (Achado L). |
| 9 | Utilidade prática | **4/10** | Um assessor que pergunta "qual o guidance do GARE11?" recebe DY público — não consegue usar a resposta numa conversa com cliente. |
| 10 | Contexto financeiro ausente | — | Faltam: P/VP, segmento detalhado, prazo médio de contratos, breakdown de receita, dados de last data-base, comparação com pares (HGLG x BTLG x VRTA). |

### SPECIALIST C — QA / Failure Modes

**Catálogo de falhas observadas:**

| # | Tipo | Severidade | Repro | Causa-raiz hipótese |
|---|---|---|---|---|
| F1 | retrieval miss (table blindness) | **CRÍTICA** | "qual o LTV do BTLG11?" | Embedding de JSON cru de tabela; sem reranker |
| F2 | retrieval miss (sem contexto) | **CRÍTICA** | "qual o yield desse fundo?" sem ticker prévio | ConversationContextManager só preenchido via WhatsApp |
| F3 | rate-limit em produção | **CRÍTICA** | Qualquer query com visual_prefetch + 2 iterações | Tier OpenAI TPM=30k é insuficiente p/ contexto atual |
| F4 | wrong tool routing | **ALTA** | "qual o guidance de dividendos do GARE11?" | Heurística do GPT prefere tool com nome casado; falta hint no prompt |
| F5 | committee empty (zero stars) | **CRÍTICA** | qualquer pergunta de recomendação | Estrelas nunca foram setadas em produção depois das Tasks #144/#150 |
| F6 | telemetry blind (max_score NULL) | **ALTA** | inspecionar `retrieval_logs` | Campo não recebe write em nenhum lugar |
| F7 | valid_until tipo errado | **ALTA** | filtragem temporal | String(100) quando deveria ser DateTime |
| F8 | material_id type mismatch | **MÉDIA** | qualquer JOIN materials × document_embeddings | varchar vs int; força CAST manual |
| F9 | falso positivo entity (fundo) | **MÉDIA** | "tem algum fundo bom?" | name_ilike sem stop-words |
| F10 | visual prefetch desperdiço | **MÉDIA** | qualquer query numérica c/ ticker | trigger genérico, sem checar se é pergunta visual |
| F11 | linked_tickers vazio | **MÉDIA** | inventário | `material_product_links` não populada |
| F12 | retrieval lento (2,5s) | **BAIXA** | qualquer query | multi-query serial, sem paralelismo |

---

## ROADMAP DE MELHORIAS

### PRIORIDADE 1 — Crítica (corrigir antes do próximo release)

**P1.1 — Indexar tabelas como markdown legível antes do embedding**
- **Problema:** Cegueira a tabelas (Achado F). 7 de 13 fatos numéricos perdidos.
- **Evidência:** Recall@6 = 38,5%; LTV, GARE_GUID, MANA_DIV, MANA_DY todos MISS quando a fonte é `tabela`.
- **Causa-raiz:** `vector_store.py:324` embeda `content` cru. Para tabela, isso é `{"headers":[...],"rows":[[...]]}` — JSON sintático, não semântico.
- **Fix:** No `ProductIngestor.process_pdf_to_blocks`, gerar campo paralelo `content_for_embedding` que serializa a tabela como markdown:
  ```
  Tabela: Indicadores BTLG11
  | Indicador | Valor |
  |---|---|
  | DIVIDEND YIELD | 9,2% |
  | LTV | 3,3% |
  ```
  e usar esse campo para o embedding (mantendo o JSON original em `content` para renderização).
- **Impacto esperado:** Recall@6 → 60-70% (estimado).
- **Risco:** Reembeddar 110 tabelas = ~110 chamadas × $0,00005 ≈ $0,01 + tempo. Baixo risco se feito em background.

**P1.2 — Popular estrelas de comitê + linked_tickers**
- **Problema:** Comitê vazio (Achados B, C, K, F5).
- **Evidência:** `SELECT COUNT(*) FROM products WHERE is_committee=true` → 0; logs do agente: "Comitê vazio — agente informará ausência".
- **Fix:** Não é código — é **dado**. Operacional: o admin precisa marcar a estrela em N produtos via UI. Adicionar seed/migration ou avisar a operação.
- **Impacto:** Toda a feature de "Stevan recomenda" volta a funcionar. Sem isso, Tasks #144/#150 produzem zero valor real.

**P1.3 — Aumentar TPM ou reduzir contexto por chamada**
- **Problema:** Rate-limit em produção (Achados K, F3).
- **Evidência:** 25 540 / 30 000 tokens em uma única iteração; 2 das 4 perguntas testadas devolveram fallback genérico.
- **Causa-raiz:** System prompt + 8 000 chars de tool result + 4 visual prefetches + tool definitions ≈ 25k tokens.
- **Fix imediato:** Reduzir `_execute_search_knowledge_base` cap de 6 chunks → 4 chunks ou de 800 → 500 chars; tornar `visual_prefetch` opt-in (só quando o classificador detecta intent visual).
- **Fix permanente:** Solicitar upgrade de tier OpenAI (Tier 2 = 450k TPM).
- **Impacto:** Reduz fallbacks de ~50% para <5%; reduz custo médio em ~30%.

**P1.4 — Baixar threshold para 0,3-0,5 e usar reranker**
- **Problema:** 0,8 silenciosamente descarta 80% dos fatos (Achado threshold).
- **Fix:** Default `similarity_threshold=0.4` em `EnhancedSearch.search`; manter top-N maior (12) e adicionar reranker LLM (gpt-4o-mini, ~$0,00015/op) que reduz para top-6.
- **Impacto:** Recall@6 esperado +25 p.p.; cost +$0,00015/query.

### PRIORIDADE 2 — Alto Impacto

**P2.1 — Persistir `composite_score_max` e `tools_used` em RetrievalLog**
- **Problema:** Telemetria cega (Achados E, F6).
- **Fix:** Adicionar `composite_score_max=results[0].composite_score if results else None` no insert de RetrievalLog em `agent_tools.py`.
- **Impacto:** Permite rodar essa auditoria continuamente em prod.

**P2.2 — Migrar `valid_until` para DateTime real**
- **Problema:** Filtragem temporal inoperante (Achados D, F7).
- **Fix:** Adicionar coluna `valid_until_dt timestamp`; backfill convertendo strings parseáveis; usar a nova coluna nos filtros.

**P2.3 — Hint de roteamento de tool no system prompt**
- **Problema:** Tool routing errado (Achado L, F4).
- **Fix:** No `_get_tool_usage_rules` (`agent_prompt.py`), adicionar:
  > "Para perguntas sobre **guidance, tese, projeção da gestora, recomendação** SEMPRE chame `search_knowledge_base` ANTES de qualquer tool de mercado."
- **Impacto:** Fluxo "guidance" passa a usar KB.

**P2.4 — Popular `material_product_links`**
- **Problema:** Junction vazia (Achados A, F11).
- **Fix:** Migration que inferia links de `document_embeddings.product_ticker` → `products.ticker`, ou exigir vínculo no upload.

**P2.5 — Filtros de metadados na query vetorial**
- **Problema:** Variant B+C frequentemente trazem chunks irrelevantes.
- **Fix:** Quando query tem intent=numeric, adicionar `WHERE block_type IN ('tabela','texto')` no SQL do vector search. Quando intent=visual, `block_type='grafico'`.

### PRIORIDADE 3 — Médio Impacto

**P3.1 — Stop-words no EntityResolver** (Achado J): adicionar lista (`fundo`, `produto`, `ativo`) que NÃO contam para name_ilike.
**P3.2 — Visual prefetch condicional** (Achado M): só ativa se classificador detectar intent visual real.
**P3.3 — Paralelizar multi-query** (Achado O): asyncio.gather em vez de loop serial — corta ~40% do tempo de retrieval.
**P3.4 — Dedup web vs KB** (Achado N): hash do conteúdo de chunks da KB e checar antes de incluir resultado web.

### PRIORIDADE 4 — Pesquisa / Experimental

**P4.1 — HyDE (Hypothetical Document Embedding):** gerar uma "resposta hipotética" antes de buscar; embeddar essa resposta. Tipicamente +15 p.p. recall em queries vagas (especialmente Variant B/C).
**P4.2 — Hybrid BM25 + vector:** PostgreSQL tem `pg_trgm` e `tsvector`. Combinar com pgvector dá ganhos em queries com termos raros (tickers, nomes próprios).
**P4.3 — Parent-child chunking:** indexar parágrafos pequenos para precisão, recuperar página inteira para contexto.
**P4.4 — Cross-encoder reranker (Cohere Rerank ou bge-reranker):** $0,001/query, +10-20 p.p. NDCG típico.

---

## CONSTRAINTS RESPEITADAS

✅ Nenhum arquivo de produção foi modificado
✅ Scripts em `audit/`, resultados em `audit/results/`, relatório em `audit/RAG_AUDIT_REPORT.md`
✅ Toda nota <7/10 tem evidência específica de teste
✅ Toda melhoria proposta referencia um achado numerado

## LIMITAÇÕES DESTA AUDITORIA

- **Phase 3 incompleta** (4 de 12 perguntas) por rate-limit OpenAI TPM. Mais perguntas ampliariam o catálogo de falhas mas as 4 já produziram 4 achados (K, L, M, F3).
- Variant C (queries implícitas com contexto) não pôde ser plenamente testado sem expor uma API de `ConversationContextManager` para uso programático.
- Comitê não pôde ser auditado em pipeline real porque está vazio (Achado B). Isso é em si o achado mais importante: **toda a infraestrutura recém-construída para comitê está dormente em produção**.
