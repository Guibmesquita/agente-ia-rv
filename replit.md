# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview
This project is a comprehensive FastAPI application serving as an AI agent named Stevan, designed for financial advisors. Its core purpose is to enhance efficiency in financial advisory services by streamlining communication, knowledge retrieval, and client management. Key capabilities include WhatsApp integration, semantic search on a Product CMS knowledge base, and an administrative dashboard with analytics, user management, and campaign tools. The project aims to centralize information, automate routine tasks, and improve client interaction within advisory operations.

## User Preferences
I prefer detailed explanations.
I want an iterative development process.
Ask before making major architectural changes.
Ensure code is well-documented and readable.
Focus on security best practices.
I prefer a clean and minimalist UI design.
Ensure all user-facing texts are in grammatically correct Portuguese with proper accentuation.

## System Architecture
The application is built using FastAPI with a modular architecture.

**UI/UX Decisions:** The design system features a minimizable vertical sidebar, a light theme, and the Inter font. Global CSS centralizes styling, navigation is dynamic based on user roles, and a custom toast notification system provides consistent feedback. Modern React + Tailwind screens follow strict isolation rules, utilizing Tailwind Preflight and utilities exclusively for spacing and styling to ensure a modern SaaS-like user experience.

**Technical Implementations:**
- **AI Agent (Stevan):** Integrates OpenAI for chat and embeddings, configurable for personality, rules, and model parameters. It acts as an internal support broker, explaining strategies and products, and escalating to human specialists when necessary.
- **Semantic Search:** Employs ChromaDB and OpenAI embeddings for semantic search across the internal Product CMS knowledge base, with background document chunking and indexing.
- **Semantic Transformer (3-Layer Architecture):** Implements a 3-layer content processing system: (1) Technical Extraction - GPT-4 Vision extracts raw JSON from PDFs; (2) Semantic Model - Normalizes table data into hierarchical structure (classe → gestora → fundo) with attribute standardization; (3) Narrative Chunks - Generates natural language text for RAG indexing (e.g., "O fundo ALIAR, da gestora TG Core, é um FII Cetip de prazo determinado..."). Review Queue displays human-readable hierarchical content instead of raw JSON.
- **FII External Lookup:** Automatically fetches public FII data from FundsExplorer.com.br when not available in the knowledge base.
- **WhatsApp Integration:** Uses Z-API for various message types, logs interactions, and provides a "Central de Mensagens" interface with real-time updates and conversation identification. Features full media support: audio transcription via Whisper, image analysis via GPT-4 Vision, document processing, and a modern UI with WhatsApp-style audio player (waveform visualization), image lightbox, and type indicators in conversation list.
- **Authentication & Authorization:** JWT-based with role-based access control (`admin`, `gestao_rv`, `broker`, `client`).
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM for models including users, tickets, agent configurations, message templates, campaigns, and knowledge documents.
- **Admin Dashboard:** Provides tools for user management, integration management, advisor base management (with bulk import), campaign management (4-step wizard for mass personalized WhatsApp messages, templates, attachments, SSE for progress), "Central de Mensagens" (WhatsApp Web-style interface with human takeover), and knowledge base management (upload, index, categorize documents).
- **Product CMS:** Manages products, materials, and content blocks. Features include PDF upload with GPT-4 Vision for block extraction, a Fast Lane/High-Risk Lane approval system, semantic indexing, WhatsApp scripts per product, versioning, validity control, publication statuses, expiration filtering, visual badges, and version rollback.
- **Observability and Auditing:** Includes `RetrievalLog` for RAG search audits, `IngestionLog` for document ingestion, RAG analytics metrics, intelligent re-ranking, similarity thresholds, and content block tracking.
- **AI Agent Response Framework:** Utilizes a `ConversationState` machine, message normalization, flexible contact identification, and AI-driven intent classification (Greeting, Scope, Documental, Out of Scope) to determine human transfer. Features conversation context accumulation and AI-driven ticker search.
- **V2.1 Escalation Intelligence:** GPT-powered analysis on every escalation with 11 categories (out_of_scope, info_not_found, technical_complexity, commercial_request, explicit_human_request, emotional_friction, stalled_conversation, recurring_issue, sensitive_topic, investment_decision, other). Auto-generates ticket_summary, conversation_topic. Records transferred_at, first_human_response_at, solved_at timestamps. Greeting variations when agent assumes ticket. Frontend shows needs_attention filter by default, header with assessor info (Name - Unit - Broker), amber sticky note for ticket summary.
- **V2.2 Bot Resolution Tracking:** Tracks conversations resolved by the bot without human escalation. New fields: `bot_resolved_at`, `awaiting_confirmation`, `last_bot_response_at`, `confirmation_sent_at`. Background scheduler checks every 60 seconds for pending confirmations. After 5 minutes without assessor response, sends confirmation message ("Seria só isso, {nome}?" with 7 variations). Detects 10+ positive confirmation patterns (sim, ok, obrigado, resolvido, thumbs up, etc.). On positive confirmation: marks `bot_resolved_at`, sends farewell message, calculates "time saved" metric. Insights endpoint includes `bot_metrics` section with `bot_resolved_count`, `bot_resolution_rate`, and `avg_time_saved_minutes`.
- **Insights Dashboard:** A management dashboard for Variable Income with `ConversationInsight` model, automatic GPT-based post-conversation analysis, 12 classification categories, dynamic filters, KPI cards (Total Interactions, Active Advisors, AI Resolution Rate), 5 Chart.js graphs (Daily Activity, Categories, Trending Products, AI vs. Humans, Volume by Unit), rankings (Top 5 Units, Top 10 Advisors), campaign summaries, and restricted access. New `/api/insights/tickets` endpoint provides ticket volume by status/unidade/broker/category, resolution rates, avg response/resolution times with consistent filter application.

**Feature Specifications:** Dynamic control over AI behavior parameters, real-time campaign dispatch with SSE, background document processing, customizable fields, and automated admin user creation.

## External Dependencies
- **OpenAI API:** For AI agent interactions and text embeddings.
- **Z-API:** For WhatsApp messaging integration.
- **PostgreSQL:** Primary relational database.
- **ChromaDB:** Vector database for semantic search.
- **Jinja2:** Templating engine for frontend rendering.
- **Inter Font (Google Fonts):** Standardized typography.
- **Tailwind CSS:** Utility-first CSS framework.
- **React 18 + Vite + React Router DOM:** For the modern Knowledge Base UI.
- **Radix UI:** For UI components (Dialog, Tabs, Select, Tooltip).
- **Framer Motion:** For animations and transitions.
- **Lucide React:** For icons.
- **react-dropzone:** For file uploads.

## Contrato Técnico de Front-End — SVN

**Padrão Oficial para Telas React + Tailwind**

Este documento define as regras obrigatórias para qualquer tela construída em React + Tailwind no projeto SVN.

**Objetivo:** Garantir UX moderna, consistência visual, isolamento de legado e evitar conflitos de CSS.

### 1. Isolamento Total de CSS (Regra Mais Importante)

**PROIBIDO - Nunca usar em telas React:**
```css
* { margin: 0; padding: 0; box-sizing: border-box; }
```

**Nunca carregar:**
- `global.css` legado
- `style.css` legado
- Classes genéricas: `.btn`, `.form-group`, `.page-*`, `.container`, `.sidebar-*`

**OBRIGATÓRIO:**
- Tailwind Preflight como único reset
- Spacing controlado EXCLUSIVAMENTE por Tailwind
- Exemplo correto: `<div className="p-4 space-y-4">`

### 2. Regra de Arquitetura por Rota

| Tipo | Exemplo |
|------|---------|
| Jinja legado | `/conversas` |
| React moderno | `/conversas-react` |
| React moderno | `/base-conhecimento` |

**Regras:**
- Nunca misturar Jinja + React no mesmo layout
- Cada rota React deve ter HTML base mínimo

### 3. Template HTML Base para React

O template que serve React deve conter SOMENTE:
- Sidebar (se necessário)
- `<div id="root"></div>`
- Nenhum reset CSS
- Nenhum global.css
- Nenhum style inline genérico

**Exemplo mínimo:**
```html
<body>
  <div id="root"></div>
  <script src="react-bundle.js"></script>
</body>
```

### 4. Design System (Fonte da Verdade)

**Fonte única de UI:**
- Tailwind tokens
- Variáveis no `tailwind.config.js` ou `@theme` no CSS

**Não duplicar cores no CSS legado. Não criar novo sistema paralelo.**

### 5. Componentes Obrigatórios (Padrão UX)

Toda tela React moderna deve usar:
- Cards com hover
- Skeleton loaders
- Drawer ou modal (Radix UI)
- Inline edit (sem reload)
- Search com debounce
- Filtros dinâmicos
- Empty states visuais

### 6. Spacing & Layout

**PROIBIDO - Margens no CSS:**
```css
.card { margin: 12px; }
```

**OBRIGATÓRIO - Tailwind utilities:**
```jsx
<div className="mt-3 px-4 gap-2 grid">
```

### 7. Animações e Feedback

Sempre que houver Load, Save, Open drawer, Hover, usar **Framer Motion** para:
- Fade
- Slide
- Microfeedback

**Objetivo:** Sensação de app moderno, não sistema legado.

### 8. Checklist Técnico para Nova Tela React

Antes de marcar como "pronto", validar:
- Não carrega global.css
- Não existe seletor `* {}`
- Nenhuma classe `.btn`, `.form-group`, `.page-*`
- Spacing 100% Tailwind
- Skeleton loaders implementados
- Empty state desenhado
- Drawer ou modal Radix funcional
- Search + filtro funcionando
- UX testado sem refresh de página

### 9. Regra de Ouro

> Se a tela parecer sistema legado, está errada.
> Se parecer SaaS moderno, está certa.
> **UX vem antes de "funcionar".**

### 10. Objetivo Estratégico

Esse padrão existe para:
- Evitar regressão visual
- Garantir evolução real de UX
- Evitar CSS fantasma
- Garantir que o usuário veja valor