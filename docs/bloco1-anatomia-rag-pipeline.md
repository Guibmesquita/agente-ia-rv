# Bloco 1 — Anatomia do Pipeline RAG

> Documentação técnica extraída do código-fonte do projeto Stevan.
> Arquivos de referência: `services/document_processor.py`, `services/product_ingestor.py`, `services/vector_store.py`, `services/chunk_enrichment.py`, `services/semantic_search.py`, `services/financial_concepts.py`

---

## 1. Como os PDFs são divididos em chunks?

**Não há divisão por tamanho fixo nem overlap.** O chunking é semântico, baseado em "fatos atômicos".

### Pipeline de chunking

1. **Upload do PDF** → o arquivo é processado pelo `DocumentProcessor`
2. **Extração via GPT-4o Vision** → cada página do PDF é convertida em imagem e enviada ao modelo `gpt-4o` com um prompt estruturado que pede extração de fatos atômicos
3. **Cada fato = 1 chunk** → o modelo retorna uma lista de fatos independentes (ex: "Taxa de administração: 1,20% a.a."), e cada um se torna um chunk individual
4. **Content Blocks do CMS** → conteúdos criados manualmente na base de conhecimento são indexados integralmente como um único chunk, com prefixo `[CONTEXTO GLOBAL]`

### Prompt de extração (estrutura)

O prompt do GPT-4o Vision instrui o modelo a:
- Extrair informações-chave organizadas por categorias: **Estratégia/Tese**, **Dados Quantitativos**, **Momento de Mercado**
- Cada informação extraída deve ser um fato autocontido
- Manter precisão numérica (taxas, rentabilidades, prazos)

### Código de referência

```
services/document_processor.py → class DocumentProcessor
  - process_pdf_pages() → converte páginas em imagens
  - extract_with_vision() → envia ao GPT-4o Vision
  - parse_extraction_response() → separa fatos atômicos
```

**Resultado:** Não existe `chunk_size` ou `chunk_overlap` configurável. A granularidade depende da extração semântica do GPT-4o Vision.

---

## 2. Embeddings: modelo e dimensões

| Parâmetro | Valor |
|-----------|-------|
| **Modelo** | `text-embedding-3-large` (OpenAI) |
| **Dimensões** | 3072 |
| **Armazenamento** | PostgreSQL com extensão `pgvector` |
| **Tipo da coluna** | `vector(3072)` |

### Geração de embeddings

```python
# services/vector_store.py
def _generate_embedding(self, text: str) -> List[float]:
    response = self.openai_client.embeddings.create(
        model="text-embedding-3-large",
        input=text
    )
    return response.data[0].embedding  # lista de 3072 floats
```

### Estado atual da base

- **262 documentos publicados** (publish_status = 'publicado')
- **431 embeddings** indexados no pgvector
- **169 rascunhos** (documentos ingeridos não vinculados a produtos — mantidos propositalmente)

---

## 3. Armazenamento no pgvector

### Tabela principal: `document_embeddings`

Os embeddings ficam na tabela `document_embeddings` do PostgreSQL. Os metadados são **colunas flat** (não JSONB):

```python
# database/models.py → class DocumentEmbedding
__tablename__ = "document_embeddings"
```

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | `serial` | PK |
| `doc_id` | `varchar(500)` | Identificador único do documento (unique, indexed) |
| `content` | `text` | Texto do chunk |
| `embedding` | `vector(3072)` | Vetor de embedding |
| `product_name` | `varchar(500)` | Nome do produto (ex: "GARE11") |
| `product_ticker` | `varchar(50)` | Ticker do produto (indexed) |
| `gestora` | `varchar(200)` | Nome da gestora |
| `category` | `varchar(200)` | Categoria (FII, CRI, etc.) |
| `source` | `varchar(500)` | Origem do chunk |
| `title` | `varchar(500)` | Título do documento |
| `block_type` | `varchar(100)` | Tipo do bloco |
| `material_type` | `varchar(100)` | Tipo de material (relatorio_gerencial, etc.) |
| `publish_status` | `varchar(50)` | 'publicado', 'rascunho', 'arquivado' (default: 'publicado') |
| `topic` | `varchar(200)` | Tema do chunk (estrategia, composicao, etc.) |
| `concepts` | `text` | Conceitos detectados (JSON serializado) |
| `keywords` | `text` | Keywords associadas |
| `strategy` | `varchar(500)` | Estratégia do fundo |
| `valid_until` | `varchar(100)` | Data de validade |
| `created_at_source` | `varchar(100)` | Data de criação na fonte |
| `block_id` | `varchar(100)` | ID do bloco no CMS (indexed) |
| `material_id` | `varchar(100)` | ID do material |
| `structure_slug` | `varchar(200)` | Slug de estrutura de derivativos |
| `tab` | `varchar(200)` | Aba de derivativos |
| `doc_type` | `varchar(100)` | Tipo do documento |
| `has_diagram` | `varchar(10)` | Se tem diagrama de payoff |
| `diagram_image_path` | `varchar(500)` | Caminho da imagem do diagrama |
| `extra_metadata` | `text` | Metadados adicionais (JSON) |

### Índice vetorial

O pgvector usa busca por **distância cosseno** (`<=>` operator). A query SQL ordena por distância (menor = mais similar):

```sql
SELECT *, (embedding <=> :query_vec) as distance
FROM document_embeddings
WHERE 1=1 AND publish_status NOT IN ('rascunho', 'arquivado')
ORDER BY embedding <=> :query_vec
LIMIT :fetch_count
```

### Filtro de publicação (dupla camada)

O filtro opera em **duas camadas**:

**Camada 1 — SQL WHERE** (constante global):
```python
PUBLISH_STATUS_FILTER = "AND publish_status NOT IN ('rascunho', 'arquivado')"
```

**Camada 2 — Pós-processamento Python** (safety net):
```python
publish_status = metadata.get("publish_status", "publicado")
if publish_status in ["rascunho", "arquivado"]:
    continue
```

Ambas são aplicadas. A SQL filtra na consulta, e o Python verifica novamente no loop de resultados como camada de segurança.

---

## 4. Glossário financeiro: o que é e onde atua

O **glossário financeiro** é implementado no módulo `services/financial_concepts.py` e contém definições estruturadas de conceitos do mercado financeiro. Ele atua em **duas frentes**:

### 4.1 Expansão conceitual (antes da busca)

A função `expand_query()` analisa a mensagem do usuário e detecta conceitos financeiros mencionados. Para cada conceito detectado, injeta um contexto explicativo que é passado ao GPT junto com os chunks RAG.

**Estrutura de cada conceito:**
```python
{
    "id": "dividend_yield",
    "categoria": "INDICADORES",
    "termos_busca": ["dividend yield", "dy", "rendimento", ...],
    "aliases": ["DY", "yield", "rendimento por cota", ...],
    "descricao": "Dividend Yield é o rendimento...",
    "temas_relacionados": ["cotacao", "patrimonio_liquido"]
}
```

### 4.2 Categorias cobertas

O glossário cobre **centenas de conceitos** organizados em categorias:
- **INDICADORES**: DY, P/VP, Cap Rate, TIR, etc.
- **ESTRUTURA**: Cota, Patrimônio Líquido, Vacância, etc.
- **RISCO**: Risco de crédito, Duration, Spread, etc.
- **MERCADO**: Liquidez, Cotação, Spread bid/ask, etc.
- **INSTRUMENTOS**: CRI, CRA, LCI, Debêntures, etc.
- **DERIVATIVOS**: 27 estruturas (Collar, Put Spread, Booster, etc.)
- **GLOSSÁRIO GERAL**: Bull Market, Bear Market, VIX, etc.

### 4.3 Onde atua no pipeline

1. Mensagem chega → `expand_query(user_message)` é chamada
2. Se conceitos são detectados, o `contexto_agente` é gerado (texto explicativo)
3. Esse contexto é **adicionado ao prompt do GPT** como bloco separado (não altera a busca vetorial)
4. A busca vetorial usa o `SynonymLookup` (módulo separado) para expansão de sinônimos

---

## 5. Enriquecimento semântico dos chunks

O módulo `services/chunk_enrichment.py` define o **Semantic Transformer**, uma arquitetura de 3 camadas para enriquecer o conteúdo antes da indexação:

### Camada 1: Extração Técnica
- GPT-4o Vision extrai fatos brutos do PDF
- Categoriza por temas: estratégia, dados quantitativos, momento de mercado, risco, operacional, perspectivas

### Camada 2: Modelagem Semântica
- Os fatos são organizados em uma estrutura semântica
- Associação com produtos, gestoras, tickers

### Camada 3: Geração de Chunks Narrativos
- Chunks finais são gerados com contexto enriquecido
- Cada chunk recebe metadados completos para rastreabilidade

### Metadados associados a cada chunk

```python
metadata = {
    "title": "Nome do documento",
    "material_id": 123,
    "product_name": "GARE11",
    "product_id": 45,
    "material_type": "relatorio_gerencial",
    "ticker": "GARE11",
    "manager": "Guardian",
    "category": "FII",
    "block_id": "blk_xxx",
    "source": "pdf_vision",
    "publish_status": "publicado"
}
```

---

## Resumo Visual do Pipeline de Ingestão

```
PDF Upload
    │
    ▼
┌──────────────────┐
│  GPT-4o Vision   │  ← Cada página → imagem → extração
│  (Camada 1)      │
└────────┬─────────┘
         │ Lista de fatos atômicos
         ▼
┌──────────────────┐
│  Modelagem       │  ← Organização semântica
│  Semântica       │
│  (Camada 2)      │
└────────┬─────────┘
         │ Fatos categorizados
         ▼
┌──────────────────┐
│  Chunk Narrativo │  ← 1 fato = 1 chunk
│  + Metadados     │
│  (Camada 3)      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Embedding       │  ← text-embedding-3-large (3072d)
│  (OpenAI)        │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  PostgreSQL      │  ← pgvector, publish_status filter
│  (pgvector)      │
└──────────────────┘
```
