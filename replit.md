# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview
This project, named Stevan, is a FastAPI-based AI agent designed to enhance efficiency for financial advisors. It centralizes information, automates routine tasks, and improves client interactions. Key capabilities include WhatsApp integration, semantic search within a product knowledge base (CMS), and an administrative panel featuring analytics, user management, and campaign tools. The core vision is to leverage AI for natural language understanding to empower financial advisors, providing them with intelligent support and streamlining their workflows.

## User Preferences
Prefiro explicações detalhadas.
Quero um processo de desenvolvimento iterativo.
Pergunte antes de fazer mudanças arquiteturais significativas.
Garanta que o código seja bem documentado e legível.
Foque em boas práticas de segurança.
Prefiro um design de UI limpo e minimalista.
Garanta que todos os textos voltados ao usuário estejam em português gramaticalmente correto com acentuação adequada.
**CRÍTICO: NUNCA perca funcionalidades existentes ao fazer mudanças.** Sempre verifique se as funcionalidades implementadas anteriormente permanecem intactas. Antes de modificar qualquer componente, revise quais funcionalidades existem e garanta que sejam preservadas. Chame o architect para validar mudanças de UX.

**GUIDELINES: Para mudanças em deploy, segurança, banco de dados, RAG, WhatsApp, upload, visual ou integrações externas, consulte a seção relevante do `GUIDELINES.md` antes de implementar.** Ele contém todas as regras, padrões, identidade visual, sistema de notificações, tech stack, workflows e lições aprendidas do projeto. Após concluir qualquer tarefa significativa, verifique se o `GUIDELINES.md` precisa ser atualizado.

## System Architecture
The application is built using FastAPI with a modular architecture.

**UI/UX Decisions:** The design system features a minimizable vertical sidebar, light theme, and Inter font. Global CSS centralizes styling, navigation is dynamic based on user roles, and a custom toast notification system provides consistent feedback. Modern React + Tailwind screens exclusively use Tailwind Preflight and utilities for spacing and styling, ensuring a modern SaaS-style user experience.

**Technical Implementations:**
- **AI Agent (Stevan):** Integrates OpenAI for chat and embeddings, configurable for personality, rules, and model parameters. It acts as an internal support broker, explaining strategies and products, and escalating to human experts.
- **Semantic Search (RAG V3.1 Enhanced):** Utilizes `pgvector (PostgreSQL)` and OpenAI `text-embedding-3-large` with hybrid ranking. It includes intelligent ticker detection, a financial glossary for query expansion, and semantic enrichment of content chunks.
- **Manager Disambiguation:** Automatically detects and clarifies financial manager mentions (e.g., "Manatí", "TG Core"), listing available products and allowing selection by ordinal or name.
- **AI Document Summaries:** Automatic conceptual summaries and theme generation for documents using GPT-4o-mini.
- **Semantic Transformer (3-Layer Architecture):** Processes content through technical extraction (GPT-4 Vision), semantic modeling, and narrative chunk generation for RAG indexing.
- **XPI Derivatives System (27 Structures):** A comprehensive knowledge base for structured products with a 4-step conversational disambiguation flow. It includes content extracted via GPT-4 Vision and payoff diagrams.
- **External FIIs Query:** Automatically fetches public FII data from FundsExplorer.com.br.
- **WhatsApp Integration:** Uses Z-API for various message types, logs interactions, and provides a "Message Center" interface with real-time updates. It supports full media processing, including optimized audio transcription (Whisper) and image/document analysis.
- **Authentication and Authorization:** JWT-based with role-based access control, JWT hardening, rate limiting, account lockout, and comprehensive security headers. Global auth middleware is implemented, and structured security event logging is used.
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM.
- **Admin Panel:** Provides tools for user, integration, advisor, and campaign management, a "Message Center," and knowledge base management.
- **Product CMS:** Manages products, materials, and content blocks, featuring PDF upload with GPT-4 Vision extraction, approval system, semantic indexing, WhatsApp scripts, versioning, and validity control.
- **Intelligent Upload with Metadata Extraction:** The `DocumentMetadataExtractor` service uses GPT-4 Vision to analyze PDFs and extract metadata like fund name, ticker, manager, and document type, enabling automated product matching or creation.
- **Adaptive DPI (Melhoria 3):** PDF pages are pre-classified via PyMuPDF native text analysis (text/table/infographic/mixed/image_only) and rendered at optimal DPI (150-250) before Vision extraction. Zero overhead — uses document already open in memory.
- **Dependency Health Check:** `services/dependency_check.py` validates critical dependencies (PyMuPDF, OpenAI, pgvector, python-magic, Pillow) on startup. `GET /api/health/detailed` returns real-time status of database, vector store, PDF processing, OpenAI, and Z-API with HTTP 503 on critical failures.
- **Observability and Auditing:** Includes `RetrievalLog` for RAG searches, `IngestionLog` for document ingestion, RAG analytics, intelligent re-ranking, and content block tracking.
- **AI Agent Response Framework:** Utilizes a `ConversationState` machine, message normalization, contact identification, and AI-based intent classification for human transfer.
- **Escalation Intelligence V2.1:** GPT analysis on each escalation with 11 categories, auto-generating ticket summaries and conversation topics, and tracking important timestamps.
- **Bot Resolution Tracking V2.2:** Tracks bot-resolved conversations, including `bot_resolved_at`, `awaiting_confirmation`, a background scheduler for confirmation messages, and bot resolution metrics.
- **Separate Ticket Architecture V2.3:** `Conversation` and `ConversationTicket` are separate models, allowing continuous chat sessions with distinct historical data for each human intervention, tracking resolution metrics per ticket.
- **Insights Dashboard:** A management dashboard for Variable Income with a `ConversationInsight` model, post-conversation GPT analysis, 12 classification categories, dynamic filters, KPI cards, Chart.js graphs, rankings, and campaign summaries.
- **Web Search (Tavily AI):** Fallback for real-time market data when internal knowledge is insufficient, including a whitelist of trusted sources and an audit log.
- **Classification Categories:** SAUDACAO, DOCUMENTAL, ESCOPO, MERCADO (real-time market queries), PITCH (sales argument generation), ATENDIMENTO_HUMANO, FORA_ESCOPO.

**Feature Specifications:** Dynamic control over AI behavior parameters, real-time campaign sending with SSE, background document processing, customizable fields, and automatic admin user creation.

## Database Environment (CRÍTICO)
**Desenvolvimento e produção usam bancos PostgreSQL SEPARADOS.** A ferramenta de SQL do agente executa contra o banco de desenvolvimento por padrão. O banco de produção aceita apenas consultas de leitura (SELECT) via ferramenta.

**Consequências práticas:**
- Alterações de dados (INSERT, UPDATE, DELETE) feitas pelo agente **NÃO refletem em produção**.
- Para alterar dados em produção, usar a interface do app em produção ou criar endpoints admin específicos.
- Migrações de schema (ALTER TABLE, CREATE INDEX) também precisam rodar em produção — isso acontece automaticamente no startup via `init_database()`, mas dados não são migrados.
- Ao republicar, apenas o **código** é atualizado. Os dados do banco de produção permanecem como estavam.

## Deployment (CRÍTICO)
**Deployment target: `vm` (always running).** Mudado de `cloudrun` (autoscale) para `vm` porque o upload de documentos requer processamento background em threads. Em autoscale, o container escalava para zero após o HTTP response, matando o worker de processamento antes de completar — causando uploads que pareciam bem-sucedidos mas nunca persistiam.

**Cold Start Optimization (3 Camadas — CRÍTICO):** O `main.py` usa 3 camadas para sobreviver ao health check de 5s do Replit VM:

1. **Pre-startup HTTP server (Camada 1):** No TOPO ABSOLUTO de `main.py`, antes de qualquer import pesado, um `http.server.HTTPServer` (stdlib) sobe em <100ms no port 5000 via daemon thread. Responde `{"status":"ok"}` a qualquer GET, satisfazendo o health check do Replit enquanto Python carrega o resto. É desligado antes de `uvicorn.run()`. **REGRA: O pre-startup server DEVE ser o primeiro código executável do arquivo.**

2. **Lazy Imports (Camada 2):** Imports pesados (`database.database`, `database.crud`, `core.security`) são feitos DENTRO das funções que os usam, NÃO no topo do módulo. **REGRA: NUNCA adicionar imports pesados no topo de main.py.**

3. **Lazy Router Registration (Camada 3):** Os 16 módulos de endpoint (`api/endpoints/*.py`) são importados em uma worker thread via `asyncio.to_thread()` dentro de `run_init_background()`, APÓS o uvicorn já estar respondendo. Rotas ficam disponíveis ~10-25s após o uvicorn subir.

4. **Rota `/health` no nível do app** (não via lazy router): Registrada antes do lifespan, retorna `{"status":"ok"}` instantaneamente sem dependências.

5. **Health check VM bate em `/`** (não em `/health`): Deploy VM ignora `healthcheckPath` e faz health check na homepage com timeout de 5s. A rota `/` detecta `Accept: text/html` — browsers recebem `login.html`, health checkers recebem JSON `{"status":"ok"}`. **Rota `/` NUNCA deve ser pesada.**

6. **Uvicorn bind padrão**: `uvicorn.run(app, host="0.0.0.0", port=5000)` — sem socket pré-criado, sem `SO_REUSEPORT`.

**Fluxo de startup:** pre-startup server (t<100ms) → Python imports (~5s) → pre-startup shutdown → uvicorn bind :5000 → lifespan → app ready (~10s total, mas health check já passou em t<100ms).

- Rotas `/`, `/health`, arquivos estáticos e middleware de segurança são configurados no top-level (instantâneos).
- `SESSION_SECRET` é obrigatória em produção: assina os JWTs emitidos após SSO Microsoft. Deve estar nos Secrets do Replit.
- **REGRA: `.replit` é ARQUIVO PROTEGIDO** — o agente IA NÃO consegue editar `.replit` nem `replit.nix`. A função `deployConfig()` pode não refletir no arquivo de texto. **Toda alteração necessária no `.replit` deve ser comunicada ao usuário com o texto exato antes/depois, e aguardar edição manual.**
- **IMPORTANTE: NÃO usar `SO_REUSEPORT`** — interfere com o proxy interno do Replit (metasidecar) e impede que o health check alcance a aplicação. Confirmado após 6 tentativas de deploy falhadas.

**Resiliência de upload:**
- `_resume_interrupted_uploads()` roda no startup: detecta materiais com `processing_status=processing/pending` e re-enfileira para retomada
- `_process_item` em `upload_queue.py` inclui logging diagnóstico: tipo do engine (PostgreSQL/SQLite), verificação pós-commit, contagem de blocos
- Detecção de duplicatas: uploads com `file_hash` idêntico a material com `processing_status=success` são **bloqueados** (não apenas avisados)

## External Dependencies
- **API OpenAI:** AI agent interactions and text embeddings.
- **Z-API:** WhatsApp messaging integration.
- **Tavily AI:** Web search for real-time market data.
- **PostgreSQL:** Primary relational database.
- **pgvector:** PostgreSQL extension for vector storage and search.
- **Jinja2:** Templating engine.
- **Inter (Google Fonts):** Typography.
- **Tailwind CSS:** Utility-first CSS framework.
- **React 18 + Vite + React Router DOM:** Modern Knowledge Base UI.
- **Radix UI:** UI components (Dialog, Tabs, Select, Tooltip).
- **Framer Motion:** Animations and transitions.
- **Lucide React:** Icons.
- **react-dropzone:** File uploads.