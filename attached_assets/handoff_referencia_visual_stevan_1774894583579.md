# Handoff — Referência Visual Inteligente (Stevan)

## Contexto e decisões tomadas

Esta feature expande a capacidade do agente Stevan de enviar referências visuais (gráficos, tabelas visuais, histogramas) extraídas dos documentos da base de conhecimento, de forma análoga ao que já funciona para diagramas de payoff de derivativos. A diferença é que a extração ocorre sob demanda — no momento da resposta — e não durante a ingestão.

Toda a análise abaixo é baseada em auditoria direta do banco de produção e do código. Não há premissas não validadas.

---

## Estado atual confirmado em produção

- `content_blocks`: 1.407 registros, campo `source_page` (integer) 100% populado, sem nulos. Campo `block_type` populado com distribuição: 787 tabela, 514 texto, 106 gráfico.
- `material_files`: 89 de 90 materiais com PDF em coluna BYTEA. Função `_restore_pdf_from_db` já implementada e funcional.
- `document_embeddings`: 1.425 registros. Campos `has_diagram` e `diagram_image_path` existem no schema e estão referenciados no código (`openai_agent.py`, `vector_store.py`, `ingest_derivatives.py`, `update_and_reingest.py`), mas estão 100% vazios em produção porque o script de ingestão de derivativos nunca foi executado contra o banco de produção. Não são código morto — fazem parte de um fluxo funcional localmente mas inativo em produção. **Não remover esses campos.**
- O fluxo de diagramas de payoff que funciona hoje em produção usa caminho separado: `campaign_structures` + diretório estático `static/derivatives_diagrams`. Independente dos embeddings.
- Delay de envio sequencial no Z-API já existe no código de derivativos. Padrão a ser espelhado.

---

## Bloqueante — executar antes de qualquer código novo

**Teste de acurácia do Vision em documentos variados.**

O prompt atual de localização de bbox foi calibrado para payoff de derivativos: layout previsível, gráfico isolado, documento padronizado. Os 88 blocos de FII (83% dos 106 blocos gráficos) têm layouts completamente diferentes — múltiplos gráficos por página, texto sobre imagem, colunas duplas.

Executar o teste manualmente com 10 documentos variados da base, priorizando FIIs. Custo estimado: ~$0.30 de API Vision.

**Critério de aprovação:** acerto ≥ 70% com bbox cobrindo menos de 85% da área da página.

- Se aprovado: usar o prompt atual como base para `extract_visual_tool()`.
- Se reprovado: reescrever o prompt antes de qualquer integração. Não avançar sem esse resultado.

Reportar: taxa de acerto, casos de falha, amostras de bbox retornada vs esperada.

---

## Fase 1 — Migrações de schema

### Migração 1 — campo `visual_description` em `content_blocks`

```sql
ALTER TABLE content_blocks
ADD COLUMN visual_description TEXT;
```

Nullable. Aplicável a todos os blocos, mas relevante apenas onde `block_type = 'grafico'`.

**Não criar campo `has_visual_reference`** — `block_type = 'grafico'` já cumpre essa função de forma determinística.

### Migração 2 — tabela `visual_cache`

```sql
CREATE TABLE visual_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content_block_id UUID REFERENCES content_blocks(id) UNIQUE NOT NULL,
    image_data BYTEA NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'image/png',
    bbox JSONB,
    used_fallback BOOL NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_visual_cache_block ON visual_cache(content_block_id);
```

`BYTEA` direto, sem URL externa — consistente com o padrão `material_files` do projeto. Estimativa de volume: 106 blocos × 100–300KB = 10–30MB. Viável no PostgreSQL.

**Sem dependência dos campos `has_diagram`/`diagram_image_path` de `document_embeddings`.** Esses campos pertencem ao fluxo de derivativos e não são tocados.

---

## Fase 2 — Backfill de `visual_description`

O texto já extraído pelo Vision nos 106 blocos `block_type = 'grafico'` já contém descrição narrativa do conteúdo visual. Exemplos confirmados em produção:

- Bloco BTGLG11: "A página apresenta gráficos sobre a rentabilidade do fundo BTGLG11, incluindo cotação histórica, volume mensal, evolução do ADTV, evolução de cotistas e evolução de dividendos."
- Bloco MANA11: "A página apresenta gráficos sobre a carteira de estruturados e FII do Manatí Hedge Fund FII, destacando a exposição por setor, indexador e taxa média, duration remanescente..."

**O backfill não requer chamadas Vision adicionais.** Usar o campo `content` existente do bloco como `visual_description`. Script de backfill:

```python
UPDATE content_blocks
SET visual_description = content
WHERE block_type = 'grafico'
AND visual_description IS NULL;
```

Ou equivalente via SQLAlchemy. Executar em produção após a Migração 1. Verificar resultado com `SELECT COUNT(*) FROM content_blocks WHERE block_type = 'grafico' AND visual_description IS NOT NULL`.

---

## Fase 3 — `extract_visual_tool()`

Criar em `services/visual_extractor.py` (ou equivalente ao padrão de organização do projeto).

### Ponto crítico — cleanup do `_restore_pdf_from_db`

A função atual escreve o PDF em `uploads/materials/restored_{material_id}_{filename}` sem cleanup explícito. Isso é aceitável no fluxo atual (chamada rara). No fluxo novo, com extração frequente, o risco de acúmulo é real no Railway (filesystem efêmero, mas acumula entre deploys).

**Não modificar `_restore_pdf_from_db`.** O fluxo de extração visual usa `tempfile.NamedTemporaryFile` próprio:

```python
import tempfile
import contextlib

async def extract_visual_tool(content_block_id: str) -> bytes:
    # 1. Check cache
    cached = await db.fetch_one(
        "SELECT image_data, last_accessed_at FROM visual_cache WHERE content_block_id = :id",
        {"id": content_block_id}
    )
    if cached:
        await db.execute(
            "UPDATE visual_cache SET last_accessed_at = NOW() WHERE content_block_id = :id",
            {"id": content_block_id}
        )
        return cached["image_data"]

    # 2. Cache miss — busca bloco e PDF
    block = await db.fetch_one(
        "SELECT source_page, material_id FROM content_blocks WHERE id = :id",
        {"id": content_block_id}
    )
    pdf_bytes = await db.fetch_val(
        """SELECT mf.file_data FROM material_files mf
           JOIN materials m ON m.id = mf.material_id
           WHERE m.id = :mid""",
        {"mid": block["material_id"]}
    )

    # 3. Processamento com cleanup garantido
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        image_bytes, bbox, used_fallback = await _extract_and_crop(
            tmp.name, block["source_page"]
        )

    # 4. Salva cache
    await db.execute(
        """INSERT INTO visual_cache
           (content_block_id, image_data, bbox, used_fallback)
           VALUES (:block_id, :data, :bbox, :fallback)""",
        {
            "block_id": content_block_id,
            "data": image_bytes,
            "bbox": bbox,
            "fallback": used_fallback
        }
    )
    return image_bytes
```

### `_extract_and_crop()` — lógica interna

```python
async def _extract_and_crop(pdf_path: str, page_number: int):
    # Renderiza página (espelhar resolução do código de derivativos: 200 DPI)
    from pdf2image import convert_from_path
    pages = convert_from_path(pdf_path, dpi=200, first_page=page_number, last_page=page_number)
    page_img = pages[0]
    width, height = page_img.size

    # Chama Vision para localizar bbox (usar prompt resultado do teste — Fase 0)
    bbox_result = await _call_vision_bbox(page_img)

    # Critério de fallback: bbox cobre mais de 85% da área da página
    if bbox_result is None or _bbox_area_ratio(bbox_result, width, height) > 0.85:
        img_bytes = _image_to_bytes(page_img)
        return img_bytes, None, True  # used_fallback=True

    # Recorte com margem de 20px (espelhar padrão derivativos)
    cropped = _crop_with_margin(page_img, bbox_result, margin=20)
    img_bytes = _image_to_bytes(cropped)
    return img_bytes, bbox_result, False
```

Reportar após implementação: arquivo criado, função implementada, resultado de 5 testes com blocos gráficos reais em staging (block_id, usado fallback, tamanho da imagem gerada em KB).

---

## Fase 4 — `should_send_visual()` e integração no handler

### Regra determinística — sem LLM na decisão

```python
VISUAL_TRIGGERS = {
    "histórico", "performance", "distribuição", "rentabilidade",
    "comparativo", "evolução", "retorno", "dividendos", "rendimento",
    "dy", "yield", "vacância", "captação", "cotação", "adtv",
    "cota", "patrimônio", "nav"
}

CONCEPTUAL_BLOCKERS = {
    "o que é", "como funciona", "explica", "diferença entre",
    "conceito", "definição", "o que são"
}

def should_send_visual(block, query: str) -> bool:
    if block.block_type != 'grafico':
        return False
    q = query.lower()
    if any(kw in q for kw in CONCEPTUAL_BLOCKERS):
        return False
    description = (block.visual_description or "").lower()
    return any(t in q or t in description for t in VISUAL_TRIGGERS)
```

**Limite inicial: máximo 1 imagem por resposta.** Selecionar o bloco gráfico de maior score de relevância semântica entre os elegíveis.

### Integração no handler WhatsApp — espelhar padrão derivativos

```python
# 1. Envia resposta textual primeiro
await zapi.send_text(phone, text_response)

# 2. Verifica se algum bloco top-k tem visual elegível
top_visual_blocks = [b for b in retrieved_blocks if should_send_visual(b, query)]

if top_visual_blocks:
    block = top_visual_blocks[0]  # maior score semântico
    await asyncio.sleep(0.3)      # garante ordem de entrega no WhatsApp
    image_bytes = await extract_visual_tool(str(block.content_block_id))
    caption = f"📊 {block.visual_description} — {block.document_title}, p.{block.source_page}"
    await zapi.send_image_bytes(phone, image_bytes, caption=caption)
```

Reportar após integração: arquivo e linha onde a chamada foi inserida, exemplo de log de uma resposta que acionou o envio de imagem.

---

## Fase 5 — Observabilidade mínima

Três queries de monitoramento para executar após 1 semana em produção:

```sql
-- Fallback rate (meta: < 25%)
SELECT
    COUNT(*) FILTER (WHERE used_fallback) AS fallbacks,
    COUNT(*) AS total,
    ROUND(COUNT(*) FILTER (WHERE used_fallback)::numeric / COUNT(*) * 100, 1) AS fallback_pct
FROM visual_cache;

-- Cache hit rate (deve subir com o tempo)
SELECT
    SUM(CASE WHEN last_accessed_at > created_at THEN 1 ELSE 0 END) AS hits,
    COUNT(*) AS total
FROM visual_cache;

-- Distribuição por documento (quais materiais estão sendo mais consultados)
SELECT m.title, COUNT(*) as acessos
FROM visual_cache vc
JOIN content_blocks cb ON cb.id = vc.content_block_id
JOIN materials m ON m.id = cb.material_id
GROUP BY m.title
ORDER BY acessos DESC
LIMIT 20;
```

---

## Checklist de entrega

```
[ ] BLOQUEANTE — Fase 0
    [ ] Teste de acurácia Vision: 10 docs variados (priorizar FIIs)
    [ ] Reportar: taxa de acerto, casos de falha, decisão sobre prompt
    [ ] NÃO avançar para Fase 1 sem esse resultado

[ ] Fase 1 — Migrações
    [ ] ADD COLUMN visual_description em content_blocks
    [ ] CREATE TABLE visual_cache (schema acima)
    [ ] Reportar: nomes dos arquivos de migração, resultado do apply em staging

[ ] Fase 2 — Backfill
    [ ] Executar UPDATE visual_description = content WHERE block_type = 'grafico'
    [ ] Reportar: COUNT de blocos atualizados (esperado: 106)

[ ] Fase 3 — extract_visual_tool()
    [ ] Criar services/visual_extractor.py (ou equivalente)
    [ ] Implementar com tempfile context manager (sem modificar _restore_pdf_from_db)
    [ ] Testar com 5 block_ids reais de staging
    [ ] Reportar: arquivo criado, resultado dos 5 testes (fallback usado? tamanho da imagem?)

[ ] Fase 4 — Integração handler
    [ ] Implementar should_send_visual() com triggers explícitos
    [ ] Inserir no handler WhatsApp com delay 300ms e limite de 1 imagem
    [ ] Reportar: arquivo e linha da integração, exemplo de log de envio

[ ] Fase 5 — Pós-deploy (1 semana)
    [ ] Executar as 3 queries de monitoramento
    [ ] Reportar resultados para sessão de revisão e calibração dos triggers
```

---

## Pontos que permanecem abertos para calibração conjunta

- **Lista de `VISUAL_TRIGGERS`**: a versão acima cobre os casos óbvios de renda variável. Após os primeiros dias em produção, revisar com base no vocabulário real dos assessores — pode ter termos específicos de BDR, estruturadas e opções que não estão na lista.
- **Limite de 1 imagem por resposta**: conservador e correto para o início. Definir critério de escalonamento antes que vire inércia — sugestão: relaxar para 2 após fallback_rate < 20% por 2 semanas consecutivas.
- **Investigação paralela — embeddings de derivativos**: confirmar por que os campos `has_diagram`/`diagram_image_path` nunca foram populados em produção e se o fluxo `ingest_derivatives.py` precisa ser executado. Não bloqueia esta feature, mas é dívida técnica ativa no sistema de derivativos.
