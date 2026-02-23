# Bloco 2 — Pipeline de Query, Ranking e Fallback

> Documentação técnica extraída do código-fonte do projeto Stevan.
> Arquivos de referência: `services/openai_agent.py`, `services/semantic_search.py`, `services/vector_store.py`, `services/web_search.py`, `services/financial_concepts.py`

---

## 6. Pipeline completo antes de chamar o VectorStore

Quando uma mensagem chega via WhatsApp, o pipeline segue esta sequência **antes** da busca vetorial:

### Passo 1: Normalização da mensagem
```python
# services/conversation_flow.py → normalize_message()
- Remove espaços duplicados
- Remove pontuação repetida (!!!, ???)
- Remove caracteres especiais das extremidades
- Strip final
```

### Passo 2: Classificação de intent (GPT-4o-mini)
```python
# services/openai_agent.py → classify_message()
# Modelo: gpt-4o-mini | Temperature: 0.1 | Max tokens: 150
```

A mensagem é classificada em **uma** das categorias:

| Categoria | Descrição | Consulta documentos? |
|-----------|-----------|---------------------|
| `SAUDACAO` | "oi", "bom dia" | Não |
| `DOCUMENTAL` | Perguntas sobre produtos/fundos específicos | Sim |
| `ESCOPO` | Perguntas técnicas gerais | Sim |
| `MERCADO` | Cotações, notícias em tempo real | Não (vai direto para Tavily) |
| `PITCH` | Pedido de texto de venda | Sim (busca extensa) |
| `ATENDIMENTO_HUMANO` | Pedido explícito de falar com humano | Não (escalação) |
| `FORA_ESCOPO` | Fora do domínio financeiro | Não |

Junto com a categoria, o classificador **extrai produtos mencionados** (ex: `["GARE11", "TG Core"]`).

### Passo 3: Detecção de follow-up
```python
# Se é follow-up E não tem produtos explícitos:
# - Extrai entidades das últimas 6 mensagens do histórico
# - Enriquece a query: "GARE11 MANA11 {mensagem_original}"
enriched_query = f"{' '.join(recent_entities)} {user_message}"
```

### Passo 4: Expansão via glossário financeiro
```python
# services/financial_concepts.py → expand_query()
# Detecta conceitos financeiros na mensagem
# Gera contexto explicativo para o GPT (não altera a query de busca)
concept_context = concept_expansion.get("contexto_agente", "")
```

### Passo 5: Expansão via SynonymLookup (para busca vetorial)
```python
# services/semantic_search.py → SynonymLookup.expand_query()
# Substitui aliases por nomes oficiais:
# "kinea credito" → "Kinea Crédito Privado"
# "tg pre" → "TGRI PRÉ"
# "fii" → "FII" (categoria)
```

### Passo 6: Extração de tokens
```python
# services/semantic_search.py → TokenExtractor.extract()
# Extrai: tickers, gestoras, keywords financeiras
# Padrão de ticker: r'\b([A-Z]{4,5}(?:11|12|13)?)\b'
```

### Exemplo completo: "rendimento do GARE11"

```
Entrada: "rendimento do GARE11"
    │
    ▼ Normalização
"rendimento do GARE11"
    │
    ▼ Classificação (gpt-4o-mini)
categoria = "DOCUMENTAL", produtos = ["GARE11"]
    │
    ▼ Follow-up check
Não é follow-up → enriched_query = "rendimento do GARE11"
    │
    ▼ Glossário financeiro
conceitos_detectados = ["dividend_yield", "rendimento"]
contexto_agente = "Rendimento de FII refere-se à distribuição periódica..."
(contexto vai para o GPT, não para a busca)
    │
    ▼ SynonymLookup.expand_query()
queries = ["rendimento do GARE11"]  (sem aliases aplicáveis)
    │
    ▼ TokenExtractor.extract()
tokens = {
    possible_tickers: ["GARE11"],
    possible_gestoras: [],
    financial_keywords: ["rendimento"]
}
    │
    ▼ VectorStore.search() + search_by_product("GARE11")
```

---

## 7. Top-K e threshold de score mínimo

### Dois níveis de busca com parâmetros diferentes

O sistema tem **duas camadas de busca** com parâmetros distintos:

#### Nível 1: VectorStore.search() (camada baixa)

| Parâmetro | Valor default | Onde é definido |
|-----------|---------------|-----------------|
| **n_results** | `3` (default), recebe `n_results*2` do EnhancedSearch | `vector_store.py:465` |
| **similarity_threshold** | `1.5` (distância cosseno máxima) | `vector_store.py:466` |
| **fetch_count** (SQL) | `n_results * 3` | `vector_store.py:540` |

**Atenção:** O threshold `1.5` é de **distância** (não similaridade). Distância cosseno vai de 0 (idêntico) a 2 (oposto). Resultados com `distance > 1.5` são descartados.

#### Nível 2: EnhancedSearch.search() (orquestrador)

| Parâmetro | Valor | Onde é definido |
|-----------|-------|-----------------|
| **n_results** | `8` | `openai_agent.py:1918` |
| **similarity_threshold** | `0.85` | `openai_agent.py:1920` (passado ao VectorStore) |

Quando o EnhancedSearch chama `VectorStore.search()`, passa `n_results*2=16` e `similarity_threshold=0.85`. Ou seja, **o threshold efetivo na chamada principal é 0.85** (distância), não 1.5.

### Como funciona o fluxo

1. EnhancedSearch chama `VectorStore.search(query, n_results=16, threshold=0.85)`
2. O SQL busca `fetch_count = 16 * 3 = 48` rows do pgvector ordenados por distância cosseno
3. Filtro de `valid_until` (docs expirados são descartados)
4. Filtro de `publish_status` (rascunho/arquivado descartados)
5. Filtro de `distance > 0.85` (docs pouco similares descartados)
6. VectorStore calcula seu **próprio composite score** (ver seção 8)
7. Deduplicação por similaridade de conteúdo
8. Retorna no máximo 16 resultados ao EnhancedSearch
9. EnhancedSearch aplica o CompositeScorer e retorna top 8

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
