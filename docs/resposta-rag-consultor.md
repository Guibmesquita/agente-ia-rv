# Resposta ao Questionário Técnico — Estratégia RAG

**Data:** 25/02/2026  
**Responsável técnico:** Equipe de desenvolvimento Stevan (Agente IA - RV)  
**Documento de referência:** Questionário de 5 blocos sobre Retrieval, Embeddings, Contexto, Prompt Engineering e Casos Limite

---

## Avaliação Geral Antecipada

Antes de responder bloco a bloco, a avaliação sintética contra os critérios do consultor:

| Critério | Status | Detalhe |
|---|---|---|
| Resolve produto antes de buscar | ✅ | `ProductResolver` 3 camadas antes do search |
| Filtra embeddings por `product_id` | ✅ | Filtro SQL por `product_ticker` quando ticker detectado |
| Busca híbrida vetor + keyword | ✅ | `EnhancedSearch` com 10 camadas + fallback SQL ILIKE |
| Chunks 300–800 tokens | ⚠️ | Chunking semântico/estrutural, sem controle fixo de tokens |
| Re-ranking | ✅ | Composite scoring com 6 dimensões |
| Threshold mínimo | ✅ | Múltiplos thresholds em camadas diferentes |
| Prompt com proibição de extrapolação | ⚠️ | Parcial — instruído a não improvisar, mas sem proibição explícita rígida |

---

# BLOCO 1 — Estratégia de Retrieval

## 1.1 A busca vetorial é feita globalmente ou há filtro prévio por `product_id` antes do similarity search?

**Resposta: Filtro prévio quando possível — estratégia adaptativa.**

O sistema usa três estratégias dependendo da query:

**Estratégia A — Ticker detectado na query:**
Se a query contém um ticker explícito (ex: "MANA11", "BTLG11"), o sistema executa `search_by_ticker()` — uma busca SQL filtrada por `product_ticker = :ticker` **antes** do similarity search. Isso garante que apenas embeddings daquele produto participem do ranking vetorial.

```sql
-- Filtro aplicado em services/vector_store.py
WHERE product_ticker = :product_filter
  AND publish_status NOT IN ('rascunho', 'arquivado')
ORDER BY embedding <=> :query_vec
LIMIT :n_results
```

**Estratégia B — Nome/alias detectado (sem ticker):**
`ProductResolver` resolve o nome para um produto via alias ou fuzzy match (ver 1.2). Se resolver com confiança ≥ 0.85, executa `search_by_product()` filtrado por `product_id`.

**Estratégia C — Query ambígua sem produto identificado:**
Busca global sem filtro de produto, retornando os top-k mais relevantes de toda a base. O re-ranking posterior (ver 1.4) penaliza ou prioriza resultados por correspondência contextual.

**Avaliação:** ✅ Enterprise — filtro por produto é executado antes do similarity search quando o produto é identificável.

---

## 1.2 Se o usuário menciona explicitamente um fundo, o sistema resolve o produto antes de buscar embeddings?

**Resposta: Sim. `ProductResolver` com 3 camadas de resolução.**

**Camada 1 — Ticker exato:**
Match direto de padrões como "MANA11", "BTLG11". Resolução instantânea, confiança 1.0.

**Camada 2 — Alias e nome exato:**
Dicionário de aliases pré-definidos: `"Manatí"` → `MANA11`, `"TG Core"` → produto correspondente, `"Eurogarden"` → produto Eurogarden. Match de nome exato na tabela de produtos também entra aqui.

**Camada 3 — Fuzzy match com Gestora Boost:**
Distância de Levenshtein + similaridade de tokens. Aplica bônus de até 0.10 quando o nome da gestora mencionada corresponde à gestora do produto candidato. Requer confiança ≥ 0.85 para auto-resolver; abaixo disso, retorna lista de candidatos para **disambiguation** (o agente pergunta ao usuário qual produto deseja).

**Avaliação:** ✅ Enterprise — resolução de produto acontece antes da busca vetorial, não depois.

---

## 1.3 Qual é o valor de `top_k` atualmente usado?

**Resposta: Variável por camada — não é valor fixo.**

| Camada | Candidatos Buscados | Retornados ao Agente |
|---|---|---|
| `VectorStore.search` (padrão) | `n_results × 3` = **9** | `n_results` = **3** |
| `EnhancedSearch.search` (entrada principal) | `n_results × 2` = **10** | `n_results` = **5** |
| `search_by_ticker` / `search_by_product` | **10** fixo | até 10 |

O `EnhancedSearch` busca **10 candidatos**, aplica composite scoring/re-ranking, e retorna os **5 melhores** ao agente. O `VectorStore` base busca **9**, re-ranqueia e retorna **3**.

**Avaliação:** ⚠️ Atenção — `top_k=3` no nível base é conservador. O nível `EnhancedSearch` com `top_k=5` é adequado para a maioria dos casos. Para perguntas comparativas entre fundos, pode ser insuficiente.

---

## 1.4 Existe re-ranking após a busca vetorial?

**Resposta: Sim. Composite Scoring com 6 dimensões.**

Implementado em `services/semantic_search.py` como "Level 2 Ranking":

| Dimensão | Peso | O que mede |
|---|---|---|
| Vector Score | **45%** | Similaridade semântica pura (pgvector `<=>`) |
| Fuzzy Score | **20%** | Correspondência de keywords específicas da query |
| Ticker Match | **15%** | Match exato do ticker do produto nos metadados |
| Gestora Match | **10%** | Nome da gestora mencionada vs gestora do embedding |
| Context Match | **5%** | Produto em discussão na conversa atual |
| Recency Score | **5%** | Prioriza documentos mais recentes (`created_at`, `valid_until`) |

A fórmula resulta em `composite_score ∈ [0, 1]`. Apenas blocos com `composite_score > 0.3` são usados para decidir se busca web é necessária.

**Avaliação:** ✅ Enterprise — re-ranking multidimensional com pesos configuráveis.

---

## 1.5 A busca combina keyword search + vetor (híbrida) ou é apenas vetorial?

**Resposta: Híbrida com múltiplas camadas.**

O `EnhancedSearch` executa uma pipeline de 10 camadas:

1. **Query expansion:** Expansão com glossário financeiro (`services/financial_concepts.py`) — ex: "dividend" → "rendimento", "DY", "distribuição"
2. **Ticker detection:** Extração de tickers via regex antes de qualquer busca
3. **Product resolution:** `ProductResolver` antes do search
4. **Vector search filtrado:** pgvector `<=>` com filtro SQL de produto (quando aplicável)
5. **Vector search global:** Como complemento ao search filtrado
6. **Multi-query fusion:** Múltiplas variações da query original são buscadas e fundidas
7. **Keyword/metadata search:** Filtro SQL por `product_ticker` e `gestora` como segundo sinal
8. **Composite scoring:** Re-ranking das dimensões descritas em 1.4
9. **Deduplicação:** Remoção de blocos com conteúdo repetido
10. **Fallback SQL ILIKE:** Se vetor retornar menos de 2 resultados, busca direta no PostgreSQL com `ILIKE`

**Avaliação:** ✅ Enterprise — pipeline híbrida genuína, não apenas vetor.

---

# BLOCO 2 — Estrutura dos Embeddings

## 2.1 Cada chunk contém explicitamente o nome do produto dentro do texto antes de gerar embedding?

**Resposta: Sim. Prefixo `[CONTEXTO GLOBAL]` obrigatório.**

Antes de gerar o embedding, o método `_build_global_context()` em `services/product_ingestor.py` cria um cabeçalho estruturado que é **concatenado ao início do chunk**:

```text
[CONTEXTO GLOBAL]
Produto: {product_name} ({product_ticker})
Gestora: {gestora}
Categoria: {category}
Documento: {material_name}
Tipo: {material_type}
Data: {date}
Resumo: {ai_summary}
Temas: {themes}

{conteúdo_do_bloco}
```

A indexação é feita com `content_with_context = f"{global_context}\n\n{content_for_indexing}"`. O embedding captura tanto o contexto do produto quanto o conteúdo específico do bloco.

**Avaliação:** ✅ Enterprise — nome, ticker, gestora e categoria estão no texto que gera o embedding.

---

## 2.2 Qual é o tamanho médio dos chunks (em tokens)?

**Resposta: Sem controle fixo de tokens — chunking semântico/estrutural.**

O sistema não usa estratégia de chunking baseada em contagem de tokens (ex: "máximo 512 tokens por chunk"). Em vez disso, cada chunk corresponde a **um elemento estrutural extraído por GPT-4 Vision**:

- **Tabela:** 1 tabela = 1 chunk (independente do tamanho)
- **Texto:** Conjunto de fatos extraídos de uma página = 1 chunk
- **Infográfico/Chart:** 1 elemento visual = 1 chunk

O tamanho real varia amplamente:
- Tabelas simples: ~100–300 tokens
- Tabelas densas (carteira, série histórica): ~400–1000 tokens
- Blocos de texto (teses de investimento, estratégias): ~200–600 tokens

O modelo de embedding usado é `text-embedding-3-large` (OpenAI), que suporta até **8192 tokens** por input. Truncamento pode ocorrer silenciosamente em tabelas muito grandes.

**Avaliação:** ⚠️ Atenção — chunking semântico é mais preciso que sliding window, mas a ausência de controle de tokens pode gerar chunks excessivamente grandes em tabelas complexas. Recomendação: adicionar validação de token count antes de enviar ao modelo de embedding.

---

## 2.3 O chunking é por página inteira ou por parágrafo/seção?

**Resposta: Por elemento estrutural dentro de cada página — não por página inteira nem por parágrafo.**

O `DocumentProcessor` em `services/document_processor.py` processa cada página individualmente via PyMuPDF + GPT-4 Vision:

1. **Pré-classificação de página** (DPI adaptativo): A página é classificada como `text`, `table`, `infographic`, `mixed` ou `image_only`. Páginas classificadas como `structural_only` (apenas header/footer/logo) são ignoradas.

2. **Extração estruturada**: GPT-4 Vision extrai elementos separados:
   - `tables[]` → cada tabela vira um bloco separado
   - `facts[]` → conjunto de fatos de texto vira um bloco
   - `infographics[]` → cada infográfico vira um bloco

3. **Resultado por página**: Uma página pode gerar **0, 1 ou múltiplos chunks** dependendo de sua densidade de conteúdo.

**Avaliação:** ✅ Enterprise — chunking por elemento estrutural é superior a sliding window e captura semântica de tabelas sem quebras artificiais.

---

## 2.4 Existe metadado estruturado salvo junto ao embedding?

**Resposta: Sim. Modelo `DocumentEmbedding` com 15+ campos de metadado.**

A tabela `document_embeddings` armazena:

| Campo | Tipo | Descrição |
|---|---|---|
| `product_id` | integer | ID do produto associado |
| `product_name` | text | Nome completo do fundo |
| `product_ticker` | text | Ticker (ex: "MANA11") |
| `gestora` | text | Nome da gestora |
| `category` | text | Categoria do produto |
| `source` | text | Nome/título do documento (material) |
| `material_id` | integer | ID do material (para rastreabilidade) |
| `material_type` | text | Tipo do documento (one_pager, carta, etc.) |
| `publish_status` | text | Status de publicação |
| `valid_until` | date | Data de validade do documento |
| `block_id` | integer | ID do bloco de conteúdo |
| `block_type` | text | text / table / chart |
| `page` | integer | Página de origem no PDF |
| `topic` | text | Tópico gerado por IA |
| `concepts` | JSON | Lista de conceitos (ex: ["DY", "duration"]) |
| `keywords` | text | Keywords para busca |
| `strategy` | text | Estratégia do fundo |
| `extra_metadata` | JSON | Campo extensível |

**Avaliação:** ✅ Enterprise — metadados extensivos permitem filtragem precisa.

---

## 2.5 A busca utiliza filtros por metadado no pgvector?

**Resposta: Sim. Filtros SQL em múltiplos campos.**

O pgvector no PostgreSQL permite combinar filtros SQL com busca vetorial. O sistema usa:

**Filtro obrigatório em todas as buscas:**
```sql
WHERE publish_status NOT IN ('rascunho', 'arquivado')
```

**Filtro por ticker (quando detectado):**
```sql
AND product_ticker = :ticker
```

**Filtro por produto (quando resolvido):**
```sql
AND product_id = :product_id
```

**Ordenação híbrida:**
```sql
ORDER BY embedding <=> :query_vec  -- similaridade coseno
LIMIT :n_results
```

O re-ranking posterior (composite scoring) usa os campos de metadado (`product_ticker`, `gestora`) para calcular os pesos adicionais sobre o score vetorial.

**Avaliação:** ✅ Enterprise — filtros por metadado são aplicados no SQL, não apenas no pós-processamento.

---

# BLOCO 3 — Construção do Contexto

## 3.1 Após recuperar os top_k resultados, o sistema apenas concatena os textos ou organiza por relevância?

**Resposta: Organiza com estrutura + priorização por produto identificado.**

O método `_build_context()` em `services/openai_agent.py` organiza os blocos recuperados da seguinte forma:

1. **Priorização:** Se um produto específico foi identificado, a busca dedicada para esse produto é executada e seus resultados são **inseridos primeiro** no contexto, antes dos resultados da busca global.

2. **Estruturação por bloco:** Cada bloco recebe um cabeçalho:
   ```
   [Título do Documento] | Material #{id} | {product_name} | {material_type}
   {conteúdo do bloco}
   ```

3. **Ordenação:** Blocos são ordenados por `composite_score` decrescente (os mais relevantes aparecem primeiro no contexto, o que é importante para modelos com attention degradando no meio do contexto).

4. **Deduplicação:** Ver seção 3.2.

**Avaliação:** ✅ Enterprise — contexto estruturado com metadado, não dump de texto cru.

---

## 3.2 Existe deduplicação de blocos semelhantes?

**Resposta: Sim. Deduplicação por prefixo de conteúdo.**

Em `services/openai_agent.py` (método `generate_response`), antes de adicionar cada bloco ao contexto:

```python
seen_contents = set()
# Para cada bloco recuperado:
prefix = content[:100]  # primeiros 100 caracteres
if prefix in seen_contents:
    continue  # pula bloco duplicado
seen_contents.add(prefix)
```

**Avaliação:** ⚠️ Atenção — deduplicação por prefixo de 100 caracteres é simples e eficaz para duplicatas exatas (mesmo documento buscado duas vezes), mas **não detecta paráfrases ou blocos com mesmo conteúdo e cabeçalhos diferentes**. Para base pequena (~300 blocos), o risco é baixo. Em escala maior, deduplicação por similarity (ex: cosine > 0.95) seria mais robusta.

---

## 3.3 Existe limite máximo de tokens enviados ao modelo?

**Resposta: Controle pelo número de blocos, não por contagem de tokens.**

O sistema não mede tokens do contexto explicitamente antes de enviar ao LLM. O controle é indireto:
- O número de blocos recuperados é limitado (`n_results = 5`)
- Cada bloco tem tamanho variável (ver seção 2.2)
- O modelo usado (GPT-4o) suporta 128k tokens de contexto, tornando overflow improvável com a base atual

**O que existe:**
- `max_tokens` da **resposta** é adaptativo por categoria: `DOCUMENTAL` = 900, `PITCH` = 800, `SAUDACAO` = 150, etc.
- O prompt do sistema tem tamanho fixo estimado em ~2000–3000 tokens

**Avaliação:** ⚠️ Atenção — sem contagem explícita de tokens do contexto. Com base pequena (~300 blocos) e GPT-4o (128k context), não é um problema hoje. Para escala maior (5000+ blocos com fundos novos), pode virar gargalo. Recomendação: adicionar contagem de tokens com `tiktoken` e truncar se necessário.

---

## 3.4 O sistema prioriza blocos mais recentes?

**Resposta: Sim, como um dos 6 critérios do composite score (peso 5%).**

O `Recency Score` no re-ranking usa `created_at` e `valid_until` do metadado do embedding. Documentos mais recentes recebem score levemente maior.

**Avaliação:** ⚠️ Atenção — peso de 5% para recência é conservador. Para produtos financeiros, onde dados de DY, P/VP e vacância mudam trimestralmente, documentos mais recentes deveriam ter peso maior (10–20%). O risco atual é o agente responder com dados de um one_pager antigo quando existe carta mensal mais recente indexada.

---

## 3.5 Como o sistema lida quando encontra blocos de múltiplos fundos na mesma busca?

**Resposta: Dois mecanismos de controle, mas há risco em perguntas comparativas.**

**Mecanismo 1 — Filtro de produto antes da busca:**
Se o produto é identificado, a busca é filtrada por `product_id` ou `product_ticker`. Blocos de outros fundos não entram na busca.

**Mecanismo 2 — Cabeçalho de produto no contexto:**
Cada bloco é rotulado com `{product_name}` no contexto enviado ao LLM, permitindo que o modelo associe informações ao fundo correto.

**Risco não mitigado — Perguntas comparativas:**
Se o usuário pergunta "compare MANA11 com LIFE11", a busca global retorna blocos de ambos os fundos misturados. O sistema não executa buscas separadas por produto e consolida — ele faz uma busca global com ambos os nomes na query. O LLM precisa inferir qual informação pertence a qual fundo com base nos cabeçalhos.

**Avaliação:** ⚠️ Atenção — para perguntas de um produto, controle é sólido. Para comparativas, há risco de o LLM misturar dados se os cabeçalhos não forem suficientemente claros. Recomendação: para perguntas comparativas detectadas, executar buscas separadas por produto e construir contexto em seções isoladas.

---

# BLOCO 4 — Prompt Engineering

## 4.1 O prompt obriga o agente a usar apenas informações recuperadas?

**Resposta: Parcialmente — há instrução, mas não é proibição rígida.**

O system prompt instrui o agente:
- *"Use SOMENTE as informações do contexto fornecido para responder perguntas sobre produtos específicos"*
- *"Se não houver informação relevante no contexto, ofereça busca na internet (para FIIs) ou sugira abertura de ticket"*
- Para dados externos (FundsExplorer, web search), usa disclaimer explícito de que não é recomendação oficial

**O que falta:**
Não há instrução do tipo *"É PROIBIDO inventar dados como DY, P/VP, rentabilidade. Se não estiver no contexto, diga 'não tenho essa informação'"*. A instrução atual deixa margem para o modelo extrapolar com dados de treinamento.

**Avaliação:** ⚠️ Atenção — instrução existe mas não é rígida o suficiente para dados numéricos específicos. Risco de alucinação de DY ou P/VP se o bloco relevante não for recuperado.

---

## 4.2 O agente é instruído a dizer explicitamente quando não encontra a informação?

**Resposta: Sim, com fallback estruturado.**

Cadeia de fallback implementada:

```
1. Busca semântica interna → se insuficiente:
2. Busca direta por produto/ticker no banco → se não encontrar:
3. (Para FIIs) Busca pública FundsExplorer.com.br → se falhar:
4. (Para mercado) Web search Tavily AI → se falhar:
5. Sugerir abertura de ticket para broker humano
```

O agente tem instrução explícita: *"SOMENTE se realmente não houver nenhuma informação relevante no contexto E nem dados externos, pergunte se deseja abrir um chamado"*.

Para tickers similares (ex: usuário escreve "LVIB11" querendo "LVBI11"), o agente **deve apenas perguntar** "Você quis dizer X ou Y?" e **parar** — sem fornecer informação enquanto a disambiguação não é feita.

**Avaliação:** ✅ Enterprise — fallback estruturado com instrução de não inventar e escalonamento para humano.

---

## 4.3 Existe separação entre pergunta factual, comparativa e aberta?

**Resposta: Parcialmente — via classificação de intent, não de tipo de pergunta.**

O sistema classifica cada mensagem em categorias de **intent**:

| Categoria | Significado |
|---|---|
| `DOCUMENTAL` | Pergunta sobre produto/documento específico |
| `PITCH` | Geração de argumento de venda |
| `MERCADO` | Dados de mercado em tempo real |
| `ESCOPO` | Pergunta fora do escopo de RV |
| `SAUDACAO` | Cumprimento/saudação |
| `ATENDIMENTO_HUMANO` | Pedido de atendimento humano |
| `FORA_ESCOPO` | Pergunta irrelevante |

A categoria `DOCUMENTAL` cobre tanto perguntas factuais quanto comparativas. **Não há separação formal entre factual e comparativa** dentro do intent. O comportamento de busca para ambas é idêntico.

**Avaliação:** ⚠️ Atenção — a classificação de intent guia `max_tokens` e comportamento de fallback, mas não diferencia factual de comparativa para fins de estratégia de busca. Recomendação: detectar perguntas comparativas (presença de dois ou mais produtos na query) e executar estratégia de busca dupla.

---

## 4.4 O prompt força citação interna ou apenas resposta natural?

**Resposta: Resposta natural, sem citação formal de fonte.**

O agente responde de forma conversacional, sem referenciar explicitamente "Fonte: one_pager_MANA11_2025.pdf, página 3". Para dados de fontes externas (FundsExplorer, web search), há disclaimer genérico.

**Avaliação:** ⚠️ Atenção — ausência de citação de fonte torna difícil para o assessor validar a informação recebida. Para uso profissional com clientes, citação da fonte (nome do documento, data) aumentaria confiabilidade. Recomendação: adicionar ao final das respostas `DOCUMENTAL` uma linha como "Fonte: {nome_material} ({data})".

---

## 4.5 Existe sistema de score/confiança da resposta?

**Resposta: Sim, internamente — mas não exposto ao usuário.**

O `composite_score` calculado no re-ranking é disponível internamente:
- `composite_score < 0.3` → dispara avaliação se deve buscar na web (`_should_web_search`)
- Score influencia se o contexto é considerado suficiente para responder

O score **não é exibido** na resposta ao usuário nem logado de forma estruturada para análise posterior de qualidade.

**Avaliação:** ⚠️ Atenção — o score existe mas não é aproveitado para observabilidade. Recomendação: logar `composite_score` máximo por query no `RetrievalLog` para análise de qualidade e detecção de perguntas mal atendidas.

---

# BLOCO 5 — Casos Limite

## 5.1 Se similarity search retorna vazio, qual é o comportamento?

**Resposta: Cadeia de fallback em 4 etapas.**

```
1. Busca semântica retorna vazio
   ↓
2. Busca direta por produto no banco (SQL por nome/ticker)
   ↓ (se ainda vazio)
3. Para FIIs: busca pública em FundsExplorer.com.br
   Para mercado: web search via Tavily AI (se threshold não atingido)
   ↓ (se ainda vazio)
4. Agente informa que não tem a informação e oferece abertura de ticket
```

**Avaliação:** ✅ Enterprise — nenhum resultado não gera resposta inventada; há cadeia de fallback com escalação.

---

## 5.2 Se o top_k contém blocos irrelevantes, há filtro posterior?

**Resposta: Sim. Threshold de composite_score e deduplicação.**

Após o re-ranking:
- Blocos com `composite_score` muito baixo são filtrados antes de entrar no contexto
- O threshold `composite_score > 0.3` é o critério para considerar contexto "suficiente"
- A deduplicação remove blocos repetidos

**Avaliação:** ⚠️ Atenção — o threshold de 0.3 pode ser permissivo. Um bloco com composite_score 0.35 pode ser marginalmente relevante e ainda assim poluir o contexto. Recomendação: aumentar threshold para 0.5 e medir impacto na qualidade das respostas.

---

## 5.3 Existe fallback para busca por keyword quando vetor falha?

**Resposta: Sim. Fallback SQL ILIKE explícito.**

Se a busca vetorial retornar menos de 2 resultados, o sistema executa busca direta no PostgreSQL:

```sql
SELECT * FROM document_embeddings
WHERE content ILIKE :keyword_pattern
   OR product_name ILIKE :keyword_pattern
   OR product_ticker ILIKE :keyword_pattern
```

**Avaliação:** ✅ Enterprise — fallback keyword implementado como última linha de defesa antes de "não encontrado".

---

## 5.4 Existe threshold mínimo de similaridade?

**Resposta: Sim. Múltiplos thresholds em camadas diferentes.**

| Camada | Threshold | Tipo | Significado |
|---|---|---|---|
| `VectorStore.search` | **1.5** | Distância (menor = melhor) | Filtra resultados com distância coseno > 1.5 |
| `EnhancedSearch.search` | **0.85** | Score (maior = melhor) | Threshold de confiança para composite score |
| `_should_web_search` | **0.3** | Composite score | Abaixo disso, considera busca web |

**Avaliação:** ✅ Enterprise — thresholds em múltiplas camadas. O threshold de 1.5 no pgvector é amplo (escala 0–2 para distância coseno), mas o composite score de 0.85 no `EnhancedSearch` é mais restritivo e eficaz.

---

## 5.5 Como o sistema evita misturar fundos em perguntas comparativas?

**Resposta: Controle parcial — seguro para perguntas de produto único, risco em comparativas.**

**Para produto único (maioria das perguntas):**
O `ProductResolver` identifica o produto → busca é filtrada por `product_id`/`product_ticker` → apenas blocos daquele produto entram no contexto. Mistura é virtualmente impossível.

**Para perguntas comparativas (ex: "diferença entre MANA11 e LIFE11"):**
- A busca é global (sem filtro de produto único)
- Blocos de ambos os fundos são recuperados e misturados no contexto
- O LLM os distingue pelos cabeçalhos `[product_name]` em cada bloco
- **Não há execução de buscas separadas e consolidação estruturada**

**Cenário de risco:**
Query: "qual tem maior DY, MANA11 ou LIFE11?"
- Sistema busca globalmente por "DY MANA11 LIFE11"
- Recupera blocos de ambos, sem garantia de equilíbrio (pode trazer 4 blocos de MANA11 e 1 de LIFE11)
- LLM responde com informações desproporcionais

**Avaliação:** ⚠️ Atenção — risco real em perguntas comparativas. Recomendação: detectar presença de múltiplos tickers na query e executar `search_by_ticker` separado para cada um, construindo contexto com seções isoladas por produto.

---

# Resumo Executivo — Avaliação contra Critérios do Consultor

## Itens com ✅ Enterprise

| Item | Evidência no Código |
|---|---|
| Resolve produto antes de buscar | `ProductResolver` 3 camadas → `search_by_ticker/product` |
| Filtra embeddings por `product_id` | Filtro SQL antes do pgvector `<=>` |
| Busca híbrida vetor + keyword | `EnhancedSearch` 10 camadas + ILIKE fallback |
| Re-ranking | Composite scoring 6 dimensões, peso 45/20/15/10/5/5 |
| Threshold mínimo | 3 thresholds em camadas diferentes (1.5 dist, 0.85 score, 0.3 web) |
| Comportamento com resultado vazio | Cadeia de 4 fallbacks, sem invenção |
| Metadados estruturados | 15+ campos no `DocumentEmbedding` |
| Nome do produto no embedding | Prefixo `[CONTEXTO GLOBAL]` em todos os chunks |
| Chunking por elemento estrutural | GPT-4 Vision extrai tabelas, texto, infográficos separados |
| Instrução de "não encontrado" | Fallback explícito para ticket humano |

## Itens com ⚠️ Atenção (melhorias recomendadas)

| Item | Risco | Recomendação |
|---|---|---|
| Tamanho de chunks sem controle de tokens | Tabelas grandes podem truncar no embedding | Validar token count com `tiktoken` antes de enviar |
| Deduplicação por prefixo 100 chars | Não detecta paráfrases | Deduplicação por similarity (cosene > 0.95) |
| Sem contagem de tokens do contexto | Risco teórico com base grande | Contar tokens com `tiktoken`, truncar se > 6000 tokens |
| Recência com peso 5% | Dados antigos podem prevalecer sobre recentes | Aumentar para 10–15% |
| Proibição de extrapolação não é rígida | Risco de alucinação em dados numéricos | Adicionar instrução explícita: "NUNCA invente dados numéricos" |
| Sem separação factual/comparativa | Busca global em perguntas comparativas | Detectar múltiplos tickers e executar buscas separadas |
| Sem citação de fonte na resposta | Assessor não sabe origem do dado | Adicionar "Fonte: {documento} ({data})" no final |
| Score não logado para observabilidade | Impossível auditar qualidade | Logar `composite_score` no `RetrievalLog` |
| Threshold composite_score = 0.3 permissivo | Blocos irrelevantes podem entrar no contexto | Testar threshold 0.5 |
| Mix de fundos em perguntas comparativas | Resposta desbalanceada | Buscas separadas por produto + contexto em seções |

## Itens sem ❌ Risco Alto

Nenhum item se enquadra nos critérios de risco alto listados pelo consultor:
- ✅ Não há "busca global, depois o modelo entende" para produto único
- ✅ Filtro por `product_id` existe (não é ausente)
- ✅ Threshold mínimo existe (não é ausente)
- ✅ Não é chunk por página inteira (é por elemento estrutural)
- ✅ `top_k=5` no EnhancedSearch (não `top_k=3` fixo)
- ✅ Re-ranking existe (não é ausente)
- ✅ Busca híbrida existe (não é apenas vetorial)

---

## Ordem de Prioridade para Melhorias RAG

Considerando impacto vs. esforço de implementação:

| # | Melhoria | Impacto | Esforço |
|---|---|---|---|
| 1 | Buscas separadas por produto em perguntas comparativas | Alto | Médio |
| 2 | Instrução rígida: "NUNCA invente dados numéricos" no prompt | Alto | Baixo |
| 3 | Citação de fonte no final de respostas `DOCUMENTAL` | Alto | Baixo |
| 4 | Logar `composite_score` no `RetrievalLog` para observabilidade | Médio | Baixo |
| 5 | Aumentar peso de recência de 5% para 15% | Médio | Baixo |
| 6 | Validação de token count nos chunks antes de indexar | Médio | Médio |
| 7 | Aumentar threshold composite_score de 0.3 para 0.5 | Médio | Baixo |
| 8 | Deduplicação por similarity em vez de prefixo | Baixo | Médio |

---

**Conclusão:** O sistema atual está no caminho enterprise nos fundamentos (resolução de produto, filtro por `product_id`, re-ranking multidimensional, busca híbrida, thresholds). As melhorias pendentes são de refinamento — não de redesign arquitetural. A correção mais crítica antes de testes de qualidade intensivos é o item #2 (instrução rígida sobre dados numéricos no prompt) e o item #1 (busca separada para comparativas).
