# Bloco 4 — Pipeline de Ingestão de Documentos

Documentação técnica do pipeline de upload e processamento de PDFs, desde a extração via GPT-4o Vision até a indexação no vector store.

---

## Arquitetura Geral

```
PDF Upload
  │
  ├→ upload_validator.py: Valida extensão, MIME, tamanho (≤50MB), gera SHA-256
  │
  ├→ upload_queue.py: Enfileira job com metadados, prioridade, suporte a retomada
  │
  ├→ document_processor.py: Converte PDF → imagens (150 DPI) → GPT-4o Vision por página
  │     └→ analyze_page(): Prompt estruturado → JSON com facts, tables, products, auto_tags
  │
  ├→ product_ingestor.py: Cria ContentBlocks no banco + sistema de Lanes
  │     ├→ Fast Lane: Texto e tabelas → auto-aprovados
  │     └→ High-Risk Lane: Gráficos e imagens → revisão humana
  │
  ├→ document_processor.py: generate_document_summary_and_themes() via GPT-4o-mini
  │
  ├→ chunk_enrichment.py: Classifica topic + concepts via GPT-4o-mini
  │
  └→ vector_store.py: Gera embedding (text-embedding-3-large, 3072d) e salva no pgvector
```

---

## BLOCO A — Extração via GPT-4o Vision

### 1. Prompt exato enviado ao GPT-4o Vision

Arquivo: `services/document_processor.py`, método `analyze_page()`.

Cada página do PDF é convertida para imagem PNG a 150 DPI via `pdf2image` e enviada como base64 inline ao GPT-4o.

```python
prompt = f"""Analise esta página do documento "{document_title}" e extraia as informações de forma estruturada.

INSTRUÇÕES:
1. Primeiro, identifique o TIPO de conteúdo principal:
   - "table": Se contém tabelas com dados estruturados
   - "infographic": Se contém gráficos, diagramas ou visualizações
   - "text": Se é principalmente texto corrido
   - "mixed": Se combina vários tipos
   - "image_only": Se é apenas uma imagem sem texto significativo

2. Para TABELAS (MUITO IMPORTANTE - EXTRAIA TODAS AS LINHAS):
   - Identifique os cabeçalhos das colunas EXATAMENTE como estão escritos
   - EXTRAIA ABSOLUTAMENTE TODAS AS LINHAS da tabela, sem pular nenhuma
   - NÃO resuma, NÃO omita, NÃO agrupe linhas - cada linha da tabela deve virar uma linha no JSON
   - Se a tabela tem 10 linhas, o array "rows" DEVE ter 10 elementos
   - Se a tabela tem 50 linhas, o array "rows" DEVE ter 50 elementos
   - Isso é dados financeiros sensíveis - omitir linhas causa prejuízo ao usuário
   - Para cada linha, crie um "fato" completo que associe o item principal com todos os seus atributos
   - Exemplo: Se a tabela tem colunas "Produto | Preço | Categoria" e uma linha "iPhone | R$ 5.000 | Eletrônicos"
   - O fato seria: "iPhone: Preço é R$ 5.000, Categoria é Eletrônicos"

3. Para INFOGRÁFICOS:
   - Descreva o que o gráfico/diagrama representa
   - Extraia números, percentuais e dados chave
   - Crie fatos descritivos sobre as informações visuais

4. Para TEXTO:
   - Extraia os pontos principais como fatos independentes
   - Mantenha o contexto necessário para cada fato

5. EXTRAÇÃO DE PRODUTOS/ENTIDADES (MUITO IMPORTANTE):
   - Identifique TODOS os nomes de produtos, fundos, ativos ou siglas mencionados na página
   - Inclua variações do nome (ex: "TG Core", "TGRI", "TG RI", etc.)
   - Liste cada produto/entidade único que aparece no conteúdo

6. EXTRAÇÃO AUTOMÁTICA DE TAGS (IMPORTANTE):
   Analise o conteúdo e identifique tags nas 4 categorias abaixo:

   a) CONTEXTO DE USO - quando o broker usaria este material:
      Opções: abordagem, fechamento, objecao, follow-up, renovacao, rebalanceamento

   b) PERFIL DO CLIENTE - para qual perfil de investidor:
      Opções: conservador, moderado, arrojado, institucional, pf, pj

   c) MOMENTO DE MERCADO - em qual cenário é mais relevante:
      Opções: alta, baixa, volatilidade, selic-alta, selic-baixa, dolar-forte

   d) TIPO DE INFORMAÇÃO - que tipo de dado contém:
      Opções: indicadores, historico, comparativo, projecao, risco, estrategia

   Selecione APENAS as tags que se aplicam claramente ao conteúdo.
   Se não houver evidência clara, deixe a categoria vazia.

FORMATO DE RESPOSTA (JSON):
{{
    "content_type": "table|infographic|text|mixed|image_only",
    "summary": "Resumo breve do conteúdo da página",
    "products_mentioned": ["TGRI", "TG Core", "BTG Pactual", ...],
    "auto_tags": {{
        "contexto": ["abordagem", "objecao"],
        "perfil": ["conservador"],
        "momento": ["selic-alta"],
        "informacao": ["indicadores", "comparativo"]
    }},
    "facts": [
        "Fato 1 completo e auto-contido",
        "Fato 2 completo e auto-contido",
        ...
    ],
    "raw_data": {{
        "tables": [
            {{
                "headers": ["col1", "col2"],
                "rows": [["val1", "val2"]]
            }}
        ],
        "key_values": {{"chave": "valor"}}
    }}
}}

Responda APENAS com o JSON, sem markdown ou explicações."""
```

Parâmetros da chamada:

```python
response = self.client.chat.completions.create(
    model="gpt-4o",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{base64_image}",
                    "detail": "high"
                }
            }
        ]
    }],
    max_tokens=8192,
    temperature=0.1
)
```

---

### 2. Tratamento de casos especiais por tipo de conteúdo

#### Tabelas com dados financeiros (DRE, carteira)

O prompt tem instruções enfáticas para extrair TODAS as linhas. O JSON retornado inclui `raw_data.tables` com `headers` e `rows`. No `product_ingestor.py`, tabelas são salvas como blocos separados do tipo `TABLE`, cada uma com JSON completo:

```python
if content_type == "table" or raw_data.get("tables"):
    tables = raw_data.get("tables", [])
    for i, table in enumerate(tables):
        table_json = json.dumps(table, ensure_ascii=False)
        block, was_created = self._create_block(
            block_type=ContentBlockType.TABLE.value,
            title=f"Tabela - Página {page_num}" + (f" ({i+1})" if len(tables) > 1 else ""),
            content=table_json,
            ...
        )
```

#### Gráficos e infográficos

Classificados como `content_type: "infographic"`. O prompt pede para "descrever o que o gráfico representa" e "extrair números, percentuais". Esses blocos **sempre vão para revisão humana** (nunca auto-aprovados):

```python
if content_type == "infographic":
    block, was_created = self._create_block(
        block_type=ContentBlockType.CHART.value,
        title=f"Gráfico - Página {page_num}",
        content=summary + ("\n\n" + "\n".join(facts) if facts else ""),
        ...
    )
    stats["pending_review"] += 1
```

#### Imagens sem texto (image_only)

Classificadas como `image_only` pelo GPT-4o. Sempre vão para revisão humana via `detect_high_risk()`:

```python
if content_type in ["image_only", "image", "imagem"]:
    if image_quality in ["poor", "uncertain", "low", "baixa"]:
        return True, "Imagem com qualidade duvidosa", 50
    return True, "Página com predominância de imagens", 65
```

#### Cabeçalhos/rodapés repetidos

**Não há tratamento especial.** O prompt não instrui a ignorar cabeçalhos/rodapés. Se o GPT-4o os extrair como fatos, eles serão incluídos. Não existe deduplicação cross-page de texto repetitivo.

---

### 3. Formato do retorno do GPT-4o Vision

**JSON estruturado.** O prompt pede explicitamente "Responda APENAS com o JSON". O parsing remove markdown fences se existirem:

```python
result_text = response.choices[0].message.content.strip()

if result_text.startswith("```"):
    result_text = result_text.split("```")[1]
    if result_text.startswith("json"):
        result_text = result_text[4:]

return json.loads(result_text)
```

Exemplo real de retorno:

```json
{
    "content_type": "table",
    "summary": "Carteira do fundo GARE11 por classe de ativo em janeiro 2024",
    "products_mentioned": ["GARE11", "Guardian Real Estate"],
    "auto_tags": {
        "contexto": ["abordagem"],
        "perfil": ["moderado"],
        "momento": [],
        "informacao": ["composicao", "indicadores"]
    },
    "facts": [
        "GARE11 possui 45% alocado em CRIs com rating AA",
        "O fundo tem exposição de 30% ao setor logístico",
        "Vacância física do portfólio é de 2,3%"
    ],
    "raw_data": {
        "tables": [{
            "headers": ["Classe", "% Carteira", "Rating"],
            "rows": [
                ["CRI", "45%", "AA"],
                ["Imóveis Logísticos", "30%", "-"],
                ["Imóveis Corporativos", "25%", "-"]
            ]
        }],
        "key_values": {"Vacância": "2,3%"}
    }
}
```

---

### 4. Retry e fallback

**Não há retry automático.** Se o Vision retorna JSON malformado, cai no `JSONDecodeError` e retorna um resultado vazio:

```python
except json.JSONDecodeError as e:
    print(f"[DOC_PROCESSOR] Erro ao parsear JSON: {e}")
    return {
        "content_type": "text",
        "summary": "Erro ao processar página",
        "facts": [],
        "raw_data": {}
    }
```

Na versão resumível (`process_pdf_resumable`), se qualquer exceção ocorre em uma página, o processamento **interrompe** e retorna com dados de retomada:

```python
except Exception as e:
    return {
        "title": document_title,
        "total_pages": total_pages,
        "pages": pages_data,
        "last_successful_page": last_successful_page,
        "error": f"Falha na página {i + 1}: {str(e)}",
        "interrupted": True
    }
```

O `UploadQueueItem` suporta retomada via `start_page` e `resume_from_page`, permitindo continuar da última página bem-sucedida.

---

### 5. PDFs protegidos, escaneados e corrompidos

| Cenário | Comportamento |
|---------|---------------|
| **PDF com senha** | `pdf2image.convert_from_path()` falha (usa poppler). Retorna erro "Não foi possível converter o PDF em imagens". |
| **PDF escaneado (imagem pura)** | **Funciona perfeitamente.** Cada página é convertida para imagem e enviada ao Vision, que faz OCR nativo. |
| **PDF corrompido** | Validação em `upload_validator.py` verifica MIME type real via `python-magic` e rejeita na hora. |

Validações em `core/upload_validator.py`:

```python
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# 1. Extensão permitida (.pdf)
if ext not in allowed_extensions:
    raise HTTPException(status_code=400, detail="Tipo de arquivo não permitido...")

# 2. Tamanho máximo
if len(content) > MAX_FILE_SIZE_BYTES:
    raise HTTPException(status_code=400, detail=f"Arquivo muito grande. Máximo: {MAX_FILE_SIZE_MB}MB")

# 3. Conteúdo mínimo (>4 bytes)
if len(content) < 4:
    raise HTTPException(status_code=400, detail="Arquivo vazio ou corrompido")

# 4. MIME type real via python-magic (verifica magic bytes %PDF)
detected_mime = _detect_mime(content)
if expected_mimes and detected_mime not in expected_mimes:
    raise HTTPException(status_code=400, detail="Conteúdo do arquivo não corresponde à extensão...")

# 5. Hash SHA-256 de integridade
file_hash = hashlib.sha256(content).hexdigest()
```

---

## BLOCO B — Do fato atômico ao chunk final

### 6. Agrupamento de fatos em blocos

**Cada tipo de conteúdo vira um bloco separado por página**, não um fato por chunk:

| Tipo de conteúdo | Agrupamento | Bloco resultante |
|------------------|-------------|------------------|
| `table` | Cada tabela individual → 1 bloco | `ContentBlockType.TABLE` (JSON com headers + rows) |
| `infographic` | 1 bloco por página infográfica | `ContentBlockType.CHART` (summary + facts concatenados) |
| `text` / `mixed` | Todos os fatos da página concatenados | `ContentBlockType.TEXT` |

Para texto:

```python
if facts and content_type not in ["table", "infographic"]:
    text_content = "\n\n".join(facts)     # Todos os fatos da página juntos
    if summary:
        text_content = f"{summary}\n\n{text_content}"  # Summary no topo
```

**Não há agrupamento por tema/seção.** O agrupamento é estritamente por tipo de conteúdo por página.

---

### 7. Texto exato que recebe o embedding

O embedding é gerado no momento da **indexação** (não na criação do bloco). O método `index_approved_blocks()` monta o texto final em 4 etapas:

```python
# 1. Conteúdo base do bloco
content_for_indexing = block.content

# 2. Se tabela, converte JSON para texto narrativo
if block.block_type == ContentBlockType.TABLE.value:
    table_data = json.loads(block.content)
    text_repr = self._table_to_text(table_data)
    content_for_indexing = f"Tabela: {block.title}\n{text_repr}"

# 3. Prefixo semântico global
content_with_context = f"{global_context}\n\n{content_for_indexing}"

# 4. Esse texto final vai para add_document → _generate_embedding()
self.vector_store.add_document(
    doc_id=chunk_id,
    text=content_with_context,    # ← ESTE TEXTO RECEBE O EMBEDDING
    metadata=metadata
)
```

#### Prefixo semântico global

Construído por `_build_global_context()`:

```
[CONTEXTO GLOBAL]
Produto: FII Guardian Real Estate (GARE11)
Gestora: Guardian Gestora
Categoria: FII
Documento: Relatório Gerencial Janeiro 2024
Tipo: relatório gerencial
Data: 2024-01-15
Resumo: Este documento apresenta a carteira atual do fundo...
Temas: renda imobiliária, logística, CRI
```

Código da construção:

```python
parts = ["[CONTEXTO GLOBAL]"]

ticker_info = f" ({product_ticker})" if product_ticker else ""
parts.append(f"Produto: {product_name}{ticker_info}")

if gestora:
    parts.append(f"Gestora: {gestora}")
if category:
    parts.append(f"Categoria: {category}")
if material_name:
    parts.append(f"Documento: {material_name}")

type_label = type_labels.get(material_type, material_type)
parts.append(f"Tipo: {type_label}")

if created_at:
    parts.append(f"Data: {created_at.strftime('%Y-%m-%d')}")
if ai_summary:
    parts.append(f"Resumo: {ai_summary}")

all_themes = (ai_themes or []) + material_tags + material_categories
unique_themes = list(dict.fromkeys(all_themes))
if unique_themes:
    parts.append(f"Temas: {', '.join(unique_themes)}")

return "\n".join(parts)
```

#### Conversão de tabela para texto narrativo

`_table_to_text()` converte JSON de tabela em linhas legíveis:

```python
# Input:  {"headers": ["Classe", "% Carteira"], "rows": [["CRI", "45%"], ["Logístico", "30%"]]}
# Output:
#   Classe: CRI, % Carteira: 45%
#   Classe: Logístico, % Carteira: 30%

def _table_to_text(self, table_data: Dict) -> str:
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])
    lines = []
    for row in rows:
        facts = []
        for i, cell in enumerate(row):
            if i < len(headers) and cell:
                facts.append(f"{headers[i]}: {cell}")
        if facts:
            lines.append(", ".join(facts))
    return "\n".join(lines)
```

#### Modelo de embedding

```python
response = self.openai_client.embeddings.create(
    model="text-embedding-3-large",
    input=text,
    dimensions=3072
)
```

---

### 8. Limite de tamanho do chunk

**Não há truncamento explícito.** O texto que vai para o embedding não tem limite de caracteres no código. A API da OpenAI aceita até 8191 tokens por input de embedding para `text-embedding-3-large`.

O `max_tokens=8192` no prompt do Vision limita o tamanho da resposta da extração, o que indiretamente limita o tamanho dos fatos — mas não há guardrail no pipeline de embedding.

Se um fato extraído for muito longo (ex: tabela grande transcrita), ele é passado inteiro ao embedding sem truncamento.

---

### 9. Summaries conceituais (GPT-4o-mini)

#### Quando são gerados

**Depois** de criar todos os blocos, **antes** da indexação:

```python
# product_ingestor.py → process_pdf_to_blocks()
# Após todos os blocos criados:
summary_result = self.doc_processor.generate_document_summary_and_themes(
    processed_data=processed,
    document_title=document_title,
    product_name=product_name,
    gestora=gestora
)
material.ai_summary = summary_result["summary"]
material.ai_themes = json.dumps(summary_result["themes"])
```

#### São indexados como chunks separados?

**Não.** O `ai_summary` e `ai_themes` são armazenados como campos do `Material` e depois incluídos no **prefixo semântico** de cada chunk quando indexados:

```python
if ai_summary:
    parts.append(f"Resumo: {ai_summary}")

all_themes = (ai_themes or []) + material_tags + material_categories
if unique_themes:
    parts.append(f"Temas: {', '.join(unique_themes)}")
```

O resumo não tem chunk próprio — ele é **diluído em todos os chunks** daquele material via prefixo `[CONTEXTO GLOBAL]`.

#### Prompt do summary

```python
prompt = """Analise o conteúdo do documento abaixo e gere:

1. RESUMO CONCEITUAL (2-3 frases): Explique o propósito e conteúdo principal do documento
   de forma clara e objetiva. Foque no que é mais importante para um assessor financeiro
   entender rapidamente.

2. TEMAS PRINCIPAIS (1-3 temas): Liste os principais tópicos abordados no documento.
   Cada tema deve ser uma palavra ou frase curta (ex: "rentabilidade", "alocação de ativos",
   "taxas de administração").

Responda APENAS em JSON no formato:
{
  "summary": "Resumo conceitual aqui...",
  "themes": ["tema1", "tema2", "tema3"]
}
"""
```

Parâmetros:
- **Modelo:** `gpt-4o-mini`
- **Temperature:** 0.3
- **Max tokens:** 500
- **System message:** "Você é um analista de documentos financeiros. Gere resumos concisos e identifique temas relevantes para assessores de investimentos."
- **Contexto recebido:** Resumos de cada página + até 20 fatos extraídos

---

## BLOCO C — Qualidade e rastreabilidade

### 10. Detecção de re-upload / duplicatas

**Deduplicação por hash de conteúdo no nível do bloco.** No `_create_block()`:

```python
content_hash = compute_hash(content)  # SHA-256 do conteúdo

existing_block = db.query(ContentBlock).filter(
    ContentBlock.material_id == material_id,
    ContentBlock.content_hash == content_hash
).first()

if existing_block:
    return (existing_block, False)  # was_created=False, pula sem duplicar
```

| Cenário | Comportamento |
|---------|---------------|
| Mesmo PDF re-uploaded para o **mesmo material** | Blocos com conteúdo idêntico não são duplicados (match por `material_id` + `content_hash`) |
| Mesmo PDF uploaded como **novo material** | Todos os blocos são criados novamente (`material_id` diferente = sem match) |

**Limitação:** Não há detecção de duplicata no nível do arquivo (hash do PDF inteiro). A validação em `upload_validator.py` gera `file_hash = hashlib.sha256(content).hexdigest()` mas esse hash não é comparado contra uploads anteriores.

---

### 11. Falha na extração de uma página

| Modo | Comportamento em caso de erro |
|------|-------------------------------|
| `process_pdf()` (simples) | Exceção em `analyze_page()` não é capturada no loop → **documento inteiro falha** |
| `process_pdf_resumable()` (streaming) | Processamento **interrompe** e retorna com dados de retomada |

Na versão resumível:

```python
except Exception as e:
    return {
        "title": document_title,
        "total_pages": total_pages,
        "pages": pages_data,              # Páginas processadas até aqui
        "last_successful_page": last_successful_page,
        "error": f"Falha na página {i + 1}: {str(e)}",
        "interrupted": True
    }
```

O `UploadQueueItem` suporta retomada via `start_page` e `resume_from_page`, permitindo continuar da última página bem-sucedida.

**Em nenhum dos modos uma página com falha é "pulada" para continuar com as demais.** A abordagem é "para tudo e retoma depois".

---

### 12. Validação de qualidade pós-indexação

**Não há validação de qualidade automatizada.** O sistema não verifica:
- Se o número de chunks é razoável para o tamanho do PDF
- Se os embeddings foram corretamente armazenados
- Se o conteúdo extraído faz sentido semântico

O que existe é o **sistema de Lanes** que classifica blocos por risco:

| Tipo de conteúdo | Lane | Confidence | Ação |
|------------------|------|------------|------|
| `table`, `tabela` | Fast Lane | 95 | Auto-aprovado |
| `text`, `texto`, `mixed` | Fast Lane | 95 | Auto-aprovado |
| `infographic`, `grafico`, `chart` | High-Risk | 60 | Revisão humana |
| `image_only` (qualidade boa) | High-Risk | 65 | Revisão humana |
| `image_only` (qualidade ruim) | High-Risk | 50 | Revisão humana |

```python
def detect_high_risk(content, content_type, image_quality="good"):
    if content_type in ["table", "tabela"]:
        return False, "", 95                    # Auto-aprovado
    if content_type in ["text", "texto", "mixed"]:
        return False, "", 95                    # Auto-aprovado
    if content_type in ["infographic", "grafico", "chart"]:
        return True, "Gráfico/infográfico requer validação visual", 60
    if content_type in ["image_only", "image", "imagem"]:
        if image_quality in ["poor", "uncertain", "low", "baixa"]:
            return True, "Imagem com qualidade duvidosa", 50
        return True, "Página com predominância de imagens", 65
    return False, "", 90
```

---

### 13. Modelo do IngestionLog

Definido em `database/models.py`:

```python
class IngestionLog(Base):
    """Log estruturado de ingestão de documentos. Auditoria completa do pipeline."""
    __tablename__ = "ingestion_logs"

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=True, index=True)
    document_name = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=True)           # pdf, manual, etc.
    total_pages = Column(Integer, nullable=True)
    blocks_created = Column(Integer, default=0)
    blocks_auto_approved = Column(Integer, default=0)
    blocks_pending_review = Column(Integer, default=0)
    blocks_rejected = Column(Integer, default=0)
    tables_detected = Column(Integer, default=0)
    charts_detected = Column(Integer, default=0)
    processing_time_ms = Column(Integer, nullable=True)
    status = Column(String(30), default="success")              # success, partial, failed
    error_message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)                  # JSON com detalhes completos
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    material = relationship("Material", foreign_keys=[material_id])
    user = relationship("User", foreign_keys=[user_id])
```

#### Campos do details_json

Upload padrão:
```json
{
    "products_detected": ["GARE11"],
    "pages_processed": 12
}
```

Smart Upload (com detecção automática de produtos):
```json
{
    "products_matched": ["GARE11", "MANA11"],
    "smart_upload": true,
    "streaming": true
}
```

#### Rastreabilidade: o que é possível reconstruir?

| Pergunta | Resposta via IngestionLog? |
|----------|---------------------------|
| Quantas páginas tinha o PDF? | Sim (`total_pages`) |
| Quantos blocos foram criados? | Sim (`blocks_created`) |
| Quantos foram auto-aprovados vs. revisão? | Sim (`blocks_auto_approved`, `blocks_pending_review`) |
| Quantas tabelas/gráficos foram detectados? | Sim (`tables_detected`, `charts_detected`) |
| Quem fez o upload e quando? | Sim (`user_id`, `created_at`) |
| O que foi extraído de cada página? | **Não** — é preciso consultar os `ContentBlock` do material e seus `BlockVersion` |
| Qual era o conteúdo original do PDF? | **Não** — o PDF não é armazenado permanentemente após processamento |

---

## Enriquecimento semântico (chunk_enrichment.py)

Após a criação dos blocos e antes da indexação, cada chunk passa por classificação via GPT-4o-mini:

```python
TOPIC_CLASSIFICATION_PROMPT = """Analise o conteúdo abaixo de um documento financeiro e classifique-o.

CONTEÚDO: {content}

METADADOS EXISTENTES:
- Produto: {product_name} ({product_ticker})
- Tipo de bloco: {block_type}
- Tipo de material: {material_type}

Retorne um JSON com:
1. "topic": O tema principal (estrategia, composicao, performance, dividendos,
   risco, mercado, operacional, perspectivas, derivativos, geral)

2. "concepts": Lista de até 5 conceitos financeiros presentes
   (ex: ["dividend_yield", "cota", "rentabilidade"])

3. "summary": Resumo de 1 frase do conteúdo (max 100 caracteres)
"""
```

O `topic` e `concepts` são adicionados como metadados no embedding, melhorando a filtragem na busca.

---

## Transformação semântica (semantic_transformer.py)

Serviço agnóstico à estrutura da tabela que implementa 3 camadas:

1. **Extração Técnica:** JSON bruto do GPT-4 Vision (`{"headers": [...], "rows": [[...]]}`)
2. **Modelo Semântico Normalizado:** `parse_table_to_semantic()` converte para dicts por linha
3. **Camada Vetorial:** `semantic_to_narrative_chunks()` gera texto narrativo para RAG

```python
# Input:  {"headers": ["Classe", "%"], "rows": [["CRI", "45%"]]}
# Semântico: {"type": "table", "rows": [{"Classe": "CRI", "%": "45%"}], "row_count": 1, "col_count": 2}
# Narrativo: "Linha 1:\n  • Classe: CRI\n  • %: 45%"
```

---

## Fluxo completo resumido

```
1. Upload do PDF
   → upload_validator.py: Valida extensão, MIME, tamanho, gera hash

2. Enfileiramento
   → upload_queue.py: Cria UploadQueueItem com metadados e prioridade

3. Conversão para imagens
   → document_processor.py: pdf2image a 150 DPI

4. Extração por página (GPT-4o Vision)
   → analyze_page(): Prompt estruturado → JSON com facts/tables/products/tags
   → max_tokens=8192, temperature=0.1, detail=high

5. Criação de blocos no banco
   → product_ingestor.py: _create_block() com hash SHA-256 para deduplicação
   → Sistema de Lanes: auto-aprovação (texto/tabelas) ou revisão (gráficos/imagens)
   → Versionamento: BlockVersion para cada bloco criado

6. Geração de resumo/temas (GPT-4o-mini)
   → generate_document_summary_and_themes()
   → Armazenados no Material (ai_summary, ai_themes)

7. Indexação no vector store (apenas blocos aprovados)
   → Prefixo semântico [CONTEXTO GLOBAL] + conteúdo do bloco
   → Enriquecimento semântico (topic + concepts via GPT-4o-mini)
   → Embedding: text-embedding-3-large (3072 dimensões)
   → Armazenamento: pgvector (PostgreSQL)

8. Registro de auditoria
   → IngestionLog com estatísticas completas
```

---

## Melhorias implementadas (2026-02-23)

### Melhoria 4 — Detecção de duplicata por hash de arquivo

Campo `file_hash` (SHA-256) adicionado à tabela `materials` com índice parcial. Durante o upload, o hash é calculado e comparado contra materials existentes. Se duplicata encontrada, um aviso é emitido ao usuário (não bloqueia). Backfill automático feito via `document_processing_jobs`.

```sql
ALTER TABLE materials ADD COLUMN file_hash VARCHAR(64);
ALTER TABLE materials ADD COLUMN file_hash_checked_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX idx_materials_file_hash ON materials(file_hash) WHERE file_hash IS NOT NULL;
```

### Melhoria 2 — Filtro de elementos estruturais

Instrução 7 adicionada ao prompt do GPT-4o Vision para ignorar cabeçalhos, rodapés, logos, disclaimers e numeração de página. Novo `content_type: "structural_only"` retornado quando página contém apenas elementos estruturais. No `product_ingestor.py`, páginas `structural_only` são puladas e registradas no `IngestionLog.details_json` como `skipped_structural`.

### Melhoria 1 — Logging explícito em fallback de tabelas

O `except: pass` no `index_approved_blocks()` foi substituído por tratamento granular:
- `json.JSONDecodeError`: Loga aviso com ID do bloco e detalhes do erro
- `Exception`: Loga erro genérico com ID do bloco

Em ambos os casos, o conteúdo bruto é indexado como fallback (comportamento preservado), mas agora com visibilidade total nos logs.
