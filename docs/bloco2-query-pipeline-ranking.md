Scorer e retorna top 8

### Buscas adicionais por produto

Quando produtos são detectados na classificação, buscas separadas são feitas:
- `search_by_product(product, n_results=10)` — busca por ticker no metadata
- `search_by_product(product, n_results=15)` — para categoria PITCH
- `search_comite_vigent(n_results=20)` — para consultas de Comitê

---

## 8. Hybrid ranking: como funciona

O "hybrid ranking" **NÃO é BM25 + vetorial**. É uma combinação de **busca vetorial + matching por metadata + fuzzy matching**, com reranking por **lógica Python** (sem modelo separado de reranking).

Existem **dois níveis de scoring composto**, um dentro do VectorStore e outro no EnhancedSearch:

### Nível 1: VectorStore composite score

Calculado dentro do `VectorStore.search()` para cada resultado retornado pelo SQL:

```python
# services/vector_store.py (linhas 649-664)
vector_score = 1.0 - min(original_distance, 1.0)   # Converte distância → similaridade

composite_score = (
    vector_score    × 0.70    # Similaridade semântica
    + recency_score × 0.20    # Documentos mais recentes ganham bonus
    + exact_match   × 0.10    # Ticker/produto exato na query
)
```

Adicionalmente, se conceitos financeiros foram detectados e o chunk tem `topic`/`concepts` compatíveis, um **bonus de até +0.15** é adicionado.

### Nível 2: EnhancedSearch CompositeScorer

Após coletar resultados de múltiplas fontes (vetorial, ticker, fuzzy, database fallback), o `CompositeScorer` recalcula:

```python
# services/semantic_search.py → SearchResult.calculate_composite_score()

composite_score = (
    vector_score × 0.40          # Score vetorial (distância cosseno convertida)
    + fuzzy_score × 0.25         # Levenshtein fuzzy matching
    + ticker_match × 0.15        # Bonus se ticker bate exatamente
    + gestora_match × 0.10       # Bonus se gestora bate
    + context_match × 0.10       # Bonus se produto está no contexto da conversa
)
```

### Níveis de confiança (EnhancedSearch)

| Score composto | Nível |
|----------------|-------|
| >= 0.7 | `high` |
| >= 0.4 | `medium` |
| < 0.4 | `low` |

### Pipeline do EnhancedSearch

```
1. Para cada query expandida (máx 3):
   └→ VectorStore.search(query, n_results * 2, threshold=0.85)
   └→ VectorStore aplica scoring Nível 1 (70/20/10)
   └→ Deduplicação por block_id

2. Para cada ticker detectado (máx 2):
   └→ VectorStore.search_by_product(ticker, n_results=5)

3. Se < 2 resultados:
   └→ Database fallback: search_product_in_database()

4. Se ainda < 2 resultados E tem tickers:
   └→ FuzzyMatcher: Levenshtein contra todos os produtos
   └→ threshold de fuzzy: 0.6

5. CompositeScorer (Nível 2): recalcula score de todos os resultados (40/25/15/10/10)
6. Ordena por composite_score decrescente
7. Retorna top n_results (8)
```

### Quem faz o reranking?

**Lógica Python pura em dois estágios:**
1. **VectorStore** (Nível 1): scoring 70% vetor + 20% recência + 10% match exato + bonus conceitual
2. **CompositeScorer** (Nível 2): scoring 40% vetor + 25% fuzzy + 15% ticker + 10% gestora + 10% contexto

Não há modelo de reranking dedicado (como Cohere Rerank ou cross-encoder).

---

## 9. O que é passado para o GPT como contexto

### Construção do contexto

Os chunks recuperados são processados pela função `_build_context()`:

```python
# services/openai_agent.py → _build_context()

# Para cada documento:
header = "[{title}]"
if material_id: header += " (material_id: {material_id})"
if product_name: header += " | Produto: {product_name}"
if material_type: header += " | Tipo: {material_type}"

context_part = f"{header}\n{content}"

# Chunks são concatenados com separador:
context = "\n\n---\n\n".join(context_parts)
```

### Estrutura da mensagem enviada ao GPT

```
messages = [
    {"role": "system", "content": system_prompt},           # Identidade + regras
    ...conversation_history[-6:],                           # Últimas 6 msgs do histórico
    {"role": "user", "content": """
        CONTEXTO DA BASE DE CONHECIMENTO:
        [título] | Produto: GARE11 | Tipo: relatorio_gerencial
        Taxa de administração: 1,20% a.a. ...

        ---

        [título 2] | Produto: GARE11
        Dividend Yield: 9,5% nos últimos 12 meses ...

        {conceito financeiro expandido, se houver}

        {contexto web do Tavily, se houver}

        ---

        PERGUNTA DO ASSESSOR/CLIENTE:
        {mensagem original}

        INSTRUÇÕES IMPORTANTES:
        1. SEMPRE use as informações do CONTEXTO acima...
        2. Se o contexto contém informações sobre produtos similares...
        3. Responda de forma clara e objetiva...
    """}
]
```

### Tratamento especial por categoria

| Categoria | Montagem do contexto |
|-----------|---------------------|
| `MERCADO` | Web context prioritário + prompt de extração de fatos |
| `PITCH` | Contexto do produto + instruções para texto de venda |
| `Default` | Contexto RAG + conceitos + web (se houver) |

### Limite de tokens do contexto

**Não há limite explícito de tokens no contexto RAG enviado.** O limite é indireto:
- `max_tokens` da resposta: **500** (default, configurável no admin)
- O modelo usado (`gpt-4o`) aceita até **128K tokens** de input
- Na prática, 8 chunks + metadados + system prompt + histórico ficam bem abaixo do limite

### Há compressão ou filtragem?

- **Não há compressão** dos chunks antes de enviar
- **Não há resumo** intermediário
- Os chunks são passados **integralmente** como foram indexados
- A única "filtragem" é o top-K da busca (8 resultados) e a deduplicação

---

## 10. Fallback para Tavily: critério exato

### Função de decisão

```python
# services/openai_agent.py → _should_web_search()

def _should_web_search(self, context_documents, query):
    # Critério 1: Nenhum documento encontrado
    if not context_documents:
        return True, "Nenhum documento encontrado na base interna"

    # Critério 2: Documentos com baixa relevância
    high_score_docs = [d for d in context_documents if d.get('composite_score', 0) > 0.3]
    if not high_score_docs:
        return True, "Documentos encontrados têm baixa relevância"

    # Critério 3: Keywords de mercado/tempo real
    market_keywords = ['cotação', 'cotacao', 'preço', 'preco', 'hoje', 'agora',
                       'atual', 'últimos dias', 'esta semana', 'notícia', 'noticia',
                       'fato relevante']
    if any(kw in query.lower() for kw in market_keywords):
        return True, "Consulta sobre dados de mercado em tempo real"

    return False, ""
```

### Resumo dos critérios

| # | Critério | Trigger |
|---|----------|---------|
| 1 | `context_documents` vazio | Lista vazia após todas as buscas |
| 2 | Todos os docs com `composite_score ≤ 0.3` | Baixa relevância semântica |
| 3 | Presença de keywords de mercado | "cotação", "preço", "hoje", "agora", etc. |

### Caso especial: categoria MERCADO

Quando o classificador retorna `MERCADO`, o Tavily é chamado **diretamente**, **sem consulta à base interna**:

```python
elif categoria == "MERCADO":
    print("[OpenAI] Categoria MERCADO - priorizando busca na web (sem consulta interna)")
    # Pula direto para web search — não faz busca vetorial
```

### Implementação do Tavily

```python
# services/web_search.py → WebSearchService
- API: Tavily Search API
- Configuração: TAVILY_API_KEY (env var)
- Custo rastreado via cost_tracker.track_tavily_search()
- Resultados formatados com citações de fontes
```

---

## Resumo Visual do Pipeline de Query

```
Mensagem WhatsApp
    │
    ▼
┌──────────────────────┐
│  1. Normalização     │  ← Remove ruído, padroniza
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│  2. Classificação    │  ← gpt-4o-mini (temp=0.1)
│     de Intent        │     Retorna: categoria + produtos
└────────┬─────────────┘
         │
    ┌────┴────────────────────┐
    │                         │
    ▼                         ▼
 MERCADO?              Outras categorias
    │                         │
    ▼                         ▼
 Tavily              ┌────────────────┐
 direto              │ 3. Follow-up?  │
                     │    Enriquecer  │
                     │    query       │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 4. Glossário   │  ← contexto_agente (para GPT)
                     │    Financeiro  │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 5. Synonym     │  ← queries expandidas
                     │    Lookup      │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 6. Token       │  ← tickers, gestoras, keywords
                     │    Extractor   │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 7. Enhanced    │  ← Vetorial + ticker + fuzzy
                     │    Search      │     + DB fallback
                     │    (top-8)     │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 8. Composite   │  ← Scoring multi-fator
                     │    Scorer      │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 9. Tavily?     │  ← Se score < 0.3 ou vazio
                     │    (fallback)  │
                     └───────┬────────┘
                             │
                             ▼
                     ┌────────────────┐
                     │ 10. GPT-4o     │  ← context + history + prompt
                     │     Response   │
                     └────────────────┘
```
