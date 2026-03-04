 Melhora accuracy 15-25%
3. **Glossário financeiro** — queries expandidas com sinônimos (CDB ↔ "Certificado de Depósito Bancário")
4. **Ticker detection** — detecção inteligente de tickers em queries (PETR4, VALE3, etc.)
5. **Queries temporais** ("último relatório") — peso de recência aumentado automaticamente

### Pipeline de Indexação
```
PDF → GPT-4 Vision (extração) → Semantic Modeling → Narrative Chunks → Embeddings → pgvector
```

### Semantic Transformer (3 camadas)
1. **Technical Extraction** — GPT-4 Vision extrai texto/tabelas do PDF
2. **Semantic Modeling** — estrutura dados em formato semântico
3. **Narrative Generation** — gera chunks narrativos para indexação

### XPI Derivatives (27 estruturas)
- Base de conhecimento especializada em produtos estruturados
- Fluxo de disambiguação conversacional em 4 etapas
- Diagramas de payoff em `static/derivatives_diagrams/`

---

## 10. WhatsApp (Z-API)

### Regras de Identificação
1. **Priorizar LID** (WhatsApp internal ID) sobre número de telefone — LID é estável, phone pode mudar
2. **Normalizar telefone** — remover caracteres especiais, garantir prefixo "55" (Brasil)
3. **Não responder imediatamente** a mensagens de saída do sistema — logar como `sent`

### Media Processing
| Tipo | Processamento |
|---|---|
| Áudio | Transcrição via Whisper (OpenAI) |
| Imagem | Análise via GPT-4 Vision |
| Documento/PDF | Análise via GPT-4 Vision |

### Conversation Flow
```
Webhook Z-API → Normalização → ConversationState Machine
  → SAUDACAO / DOCUMENTAL / ESCOPO / MERCADO / PITCH / FORA_ESCOPO → Bot responde
  → ATENDIMENTO_HUMANO → Escalation (ticket criado)
```

### Escalation Intelligence V2.1
- GPT analisa cada escalação com 11 categorias
- Auto-gera resumo do ticket e tópicos de conversa
- Tracking de timestamps importantes

### Bot Resolution V2.2
- `bot_resolved_at`, `awaiting_confirmation`
- Scheduler de background para mensagens de confirmação

### Ticket Architecture V2.3
- `Conversation` e `ConversationTicket` são modelos separados
- Sessão contínua de chat com tickets distintos por intervenção humana

---

## 11. Upload e Processamento de Documentos

### Adaptive DPI
Páginas pré-classificadas via PyMuPDF antes do GPT-4 Vision:
| Tipo de página | DPI |
|---|---|
| Texto | 150 |
| Tabela | 250 |
| Infográfico | 200 |
| Mixed | 200 |
| Image only | 250 |

### Metadata Extraction
`DocumentMetadataExtractor` usa GPT-4 Vision nas primeiras páginas para detectar automaticamente: nome do fundo, ticker, gestora, tipo de documento.

### Resumable Uploads
- `PersistentQueue` em `services/upload_queue.py`
- `_resume_interrupted_uploads()` no startup detecta `processing_status=processing/pending`
- Duplicate detection: uploads com `file_hash` idêntico a material `success` são bloqueados

### Pipeline Completo
```
Upload PDF → validate_upload() → Metadata Extraction (GPT-4V)
  → Match/Create Product → DPI Classification → Vision Extraction
  → Content Blocks → Review Queue → Aprovação → Embedding → pgvector
```

---

## 12. Frontend

### 4 React Apps
| App | Pasta | Rota | Descrição |
|---|---|---|---|
| Knowledge | `frontend/react-knowledge/` | `/base_conhecimento_react` | CMS de produtos, upload inteligente, review queue |
| Conversations | `frontend/react-conversations/` | `/conversas_react` | Central de mensagens estilo Zendesk, SSE real-time |
| Insights | `frontend/react-insights/` | `/insights` | Dashboard de insights com Chart.js/amCharts |
| Costs | `frontend/react-costs/` | `/custos_react` | Central de custos com gráficos |

### Comandos (dentro de cada pasta)
```bash
npm install        # Instalar dependências
npm run dev        # Dev server local
npm run build      # Build para produção
```

### Templates Jinja2 (páginas legado)
`login.html`, `assessores.html`, `campanhas.html`, `integrations.html`, `teste_agente.html`, `admin.html`, `users.html`

### Padrões de UI
- React apps montados em template container Jinja2
- Tailwind CSS em tudo (CDN em Jinja2, PostCSS em React)
- Ícones: Lucide (React e Jinja2)
- Componentes: Radix UI (Dialog, Tabs, Select, Tooltip)
- Animações: Framer Motion

---

## 13. Scripts e Comandos Úteis

| Script | Comando | Descrição |
|---|---|---|
| Seed produção | `python scripts/seed_production.py` | Popula banco de produção com dados do seed |
| Export dados dev | `python scripts/export_dev_data.py` | Exporta dados dev para seed JSON |
| Configurar webhooks | `python scripts/configure_zapi_webhooks.py` | Registra URL de deploy como webhook Z-API |
| Enriquecer chunks | `python scripts/enrich_chunks.py` | Adiciona metadata semântica a chunks existentes |
| Custos históricos | `python scripts/populate_historical_costs.py` | Gera dados históricos para dashboard de custos |
| Glossário B3 | `python scripts/extract_b3_glossary.py` | Extrai termos financeiros para expansão de query |
| Derivativos XPI | `python scripts/xpi_derivatives/process_pdfs_complete.py` | Pipeline completo de extração de derivativos |
| Re-ingest derivativos | `python scripts/xpi_derivatives/update_and_reingest.py` | Re-indexa base de derivativos |
| Testes de conversa | `python tests/conversation_tests/run_tests.py` | Testa fluxos de conversa do agente |
| Avaliação RAG | `python -m tests.rag_evaluation --evaluate [TICKER]` | Avalia accuracy do RAG para um produto |
| Comparar RAG | `python -m tests.rag_evaluation --compare [R1] [R2]` | Compara performance entre versões |

---

## 14. Workflows de Funcionalidades

### Conversa WhatsApp
```
1. Webhook Z-API recebe mensagem
2. Normalização (telefone, LID, media)
3. ConversationState machine classifica intent
4. Se ESCOPO/DOCUMENTAL → RAG busca semântica → GPT gera resposta → Z-API envia
5. Se MERCADO → Tavily busca web → GPT contextualiza → Z-API envia
6. Se ATENDIMENTO_HUMANO → Cria ticket → Notifica operador → Bot pausa
7. Se operador faz Takeover → Chat direto → Release → Bot retoma
```

### Upload de Documento
```
1. Usuário faz upload de PDF
2. validate_upload() — MIME, tamanho, hash
3. DocumentMetadataExtractor — GPT-4V analisa primeiras páginas
4. Match ou criação de produto
5. Classificação de DPI por tipo de página
6. GPT-4 Vision extrai conteúdo por página
7. Semantic Transformer gera content blocks
8. Blocks entram na Review Queue
9. Aprovação manual pelo gestor
10. Embedding e indexação no pgvector
```

### Campanha
```
1. Gestor define template com variáveis
2. Seleciona audiência (assessores/clientes)
3. Preview e confirmação
4. Bulk dispatch via Z-API com SSE para progress
5. Tracking de entrega e leitura
```

### Insights
```
1. Conversa encerrada/escalada
2. InsightAnalyzer (GPT) classifica: categoria, sentimento, tópicos
3. ConversationInsight salvo no banco
4. Dashboard agrega: KPIs, gráficos, rankings, filtros dinâmicos
```

---

## 15. Erros Conhecidos e Lições Aprendidas

### SO_REUSEPORT + Metasidecar do Replit
**Problema:** TCP Health Shim com `SO_REUSEPORT` impedia o proxy do Replit de rotear o health check para a porta 5000. 6 tentativas de deploy falharam.
**Causa:** `SO_REUSEPORT` permite múltiplos listeners na mesma porta. O kernel faz load-balancing, confundindo o metasidecar.
**Solução:** Remover todo uso de `SO_REUSEPORT` e sockets pré-criados. Usar uvicorn bind padrão.
**Regra:** NUNCA usar `SO_REUSEPORT` no Replit.

### Autoscale Matando Workers de Upload
**Problema:** Em Cloud Run (autoscale), o container escalava para zero após o HTTP response, matando o worker de processamento de PDF antes de completar.
**Solução:** Migrar para Reserved VM (always running).
**Regra:** Background processing requer VM, não autoscale.

### Logs stdout vs stderr em Produção
**Problema:** Shim TCP usava `print()` (stdout). Deployment logs do Replit capturam apenas stderr. Logs do shim ficaram invisíveis, impossibilitando diagnóstico.
**Solução:** Usar `sys.stderr.write()` para logs críticos em produção.
**Regra:** Logs de diagnóstico em produção = stderr.

### Senha Admin Hardcoded
**Problema:** Usuário admin com senha `admin123` em produção.
**Solução:** Senha gerada aleatoriamente (não recuperável), email placeholder neutralizado. Login apenas via SSO.
**Regra:** NUNCA criar credenciais padrão acessíveis.

### ChromaDB → pgvector
**Problema:** ChromaDB usado inicialmente para vetores, mas sem escalabilidade e persistência confiável.
**Solução:** Migração para pgvector (extensão PostgreSQL). Script legacy em `scripts/migrate_chroma_to_pgvector.py.legacy`.
**Regra:** Usar pgvector como storage de vetores. ChromaDB é legacy.

### Mudança de Modelo de Embeddings
**Problema:** Troca de `text-embedding-3-small` para `text-embedding-3-large` sem re-indexação.
**Solução:** Re-indexação total obrigatória via `reset_collection_for_migration()`.
**Regra:** Qualquer mudança no modelo de embeddings requer re-indexação completa.

---

## 16. Checklist Antes de Mudanças

### Antes de qualquer mudança
- [ ] Revisar quais funcionalidades existentes podem ser impactadas
- [ ] Consultar a seção relevante deste guia
- [ ] Testar em dev antes de deploy

### Antes de mudanças de deploy/startup
- [ ] Não usar `SO_REUSEPORT` ou sockets pré-criados
- [ ] Manter uvicorn bind padrão
- [ ] Rota `/health` continua top-level
- [ ] Logs críticos em stderr

### Antes de mudanças visuais
- [ ] Seguir paleta de cores (seção 4)
- [ ] Usar sistema de toast existente (seção 5)
- [ ] Manter tema claro, fonte Inter, spacing padrão

### Antes de novas rotas/endpoints
- [ ] Verificar checklist de segurança (seção 6.9)
- [ ] Adicionar a PUBLIC_PATHS se for rota pública

### Antes de mudanças no banco
- [ ] NUNCA alterar tipo de coluna ID
- [ ] Usar migrações incrementais (`ADD COLUMN IF NOT EXISTS`)
- [ ] Lembrar que mudanças de dados NÃO refletem em produção

### Antes de mudanças em RAG
- [ ] Se trocar modelo de embeddings, re-indexar tudo
- [ ] Usar narrative chunks (nunca tabelas raw)

---

*Última atualização: fevereiro de 2026. Atualizar este documento sempre que houver mudanças arquiteturais, novos aprendizados ou lições de erros.*
