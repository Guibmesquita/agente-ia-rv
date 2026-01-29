# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview

This project is a comprehensive FastAPI application designed as an AI agent for financial advisors, named Stevan. Its primary purpose is to streamline communication, knowledge retrieval, and client management within financial advisory services. The system integrates WhatsApp, leverages semantic search on an internal Product CMS knowledge base, and features an administrative dashboard with Insights analytics, user management, and campaign tools. The vision is to enhance advisor efficiency, improve client interaction, and provide robust tools for managing advisory operations by centralizing information and automating routine tasks.

## User Preferences

I prefer detailed explanations.
I want an iterative development process.
Ask before making major architectural changes.
Ensure code is well-documented and readable.
Focus on security best practices.
I prefer a clean and minimalist UI design.
Ensure all user-facing texts are in grammatically correct Portuguese with proper accentuation.

## System Architecture

The application is built using FastAPI with a modular structure.

**UI/UX Decisions:**
A new design system features a minimizable vertical sidebar, light theme, and the Inter font. Global CSS centralizes styling. Navigation is dynamic based on user roles, and a custom toast notification system provides consistent feedback.

**Technical Implementations:**
- **AI Agent (Stevan):** Integrates OpenAI for chat and embeddings, offering real-time configuration of personality, rules, and model parameters. Stevan acts as an internal support broker for SVN's Variable Income area, focusing on explaining strategies and products. Its communication is professional yet approachable, and it escalates to human specialists when necessary.
- **Semantic Search:** Utilizes ChromaDB and OpenAI embeddings for semantic search over the internal Product CMS knowledge base, with background document chunking and indexing.
- **FII External Lookup:** Automatically fetches public data for FIIs not in the knowledge base from FundsExplorer.com.br, supporting various FII types and providing a disclaimer.
- **WhatsApp Integration:** Uses Z-API for communication, supporting various message types, logging interactions, and featuring a "Central de Mensagens" interface with real-time updates and full LID support for conversation identification.
- **Authentication & Authorization:** JWT-based authentication with role-based access control (`admin`, `gestao_rv`, `broker`, `client`).
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM for models including users, tickets, agent configurations, message templates, campaigns, and knowledge documents.
- **Admin Dashboard:** Provides comprehensive tools for:
    - **User Management:** CRUD operations.
    - **Integration Management:** UI-based configuration and testing of API keys (OpenAI, Z-API).
    - **Assessor Base:** CRUD operations for financial advisors, with bulk import functionality.
    - **Campaign Management:** A 4-step wizard for mass WhatsApp messages with personalized variables, template system, attachment support, and real-time dispatch progress via SSE.
    - **Central de Mensagens:** WhatsApp Web-style interface for conversation management, real-time updates, human takeover, and new conversation initiation.
    - **Knowledge Base Management:** Upload, index, categorize, and reindex various document types.
    - **CMS de Produtos:** Product-centric content management system with:
        - Products, Materials, and ContentBlocks hierarchy
        - PDF upload with GPT-4 Vision for automatic block extraction
        - Fast Lane / High-Risk Lane approval system (auto-approve text, review tables/charts with financial keywords)
        - Semantic indexing of approved blocks to ChromaDB
        - WhatsApp scripts per product for commercial use
        - Versionamento automático de blocos de conteúdo
        - **Vigência e Governança:** Campos valid_from/valid_until para controle de validade de produtos e materiais
        - **Status de Publicação:** Draft/Published/Archived status para materiais, com workflow de publicação que indexa conteúdo automaticamente
        - **Filtro de Expiração:** VectorStore filtra automaticamente conteúdo expirado e não-publicado
        - **Badges Visuais:** Indicadores de "Rascunho", "Publicado", "Expirando em X dias", "Expirado"
        - **Rollback de Versões:** UI para visualizar histórico de versões de blocos e restaurar versões anteriores
        - **Priorização de Materiais Vivos:** Busca prioriza one-pages e tabelas de taxas sobre conteúdo de PDF
        - **Alertas de Expiração:** Endpoint /api/products/expiring para consultar materiais expirando
    - **Observabilidade e Auditoria:**
        - RetrievalLog: Auditoria de todas as buscas RAG (query, chunks usados, versões, distâncias, tempo de resposta)
        - IngestionLog: Log estruturado de ingestão de documentos (blocos criados, tabelas/gráficos detectados)
        - Analytics RAG: Endpoint /api/analytics/rag-metrics com taxa de transferência humana, tipos de query, tempo médio
        - Re-ranking inteligente: Perguntas numéricas priorizam tabelas, conceituais priorizam texto
        - Threshold de similaridade: Filtro com distância máxima de 0.8 para garantir relevância
        - ContentBlock tracking: Campos created_by e updated_by para rastrear autoria
- **AI Agent Response Framework:** Employs a `ConversationState` machine, message normalization, and flexible contact identification. It integrates AI for classifying user intent (Greeting, Scope, Documental, Out of Scope) and determining human transfer criteria. It also features conversation context accumulation for follow-up questions and AI-driven ticker search with intelligent confirmation flows, ensuring natural language interpretation over fixed regex patterns.
    - **Insights Dashboard:** Dashboard de gestão para Renda Variável com:
        - ConversationInsight: Modelo para armazenar insights de conversas (categoria, produtos, tickers, resolução, feedback)
        - Autoanálise automática via GPT após cada conversa no webhook WhatsApp
        - 12 categorias de classificação (Dúvida sobre Produto, Análise de Mercado, Estratégia de Investimento, etc.)
        - Filtros dinâmicos: Período (7/30/90/365 dias, personalizado), Macro Área, Unidade, Broker, Equipe
        - 3 KPI cards: Total de Interações, Assessores Ativos, Taxa de Resolução IA
        - 5 gráficos Chart.js: Atividade Diária (linha), Categorias (pizza), Produtos em Alta (barras), IA vs Humanos (pizza), Volume por Unidade (barras horizontal)
        - Rankings: Top 5 Unidades, Top 10 Assessores
        - Resumo de Campanhas e Feedbacks expansíveis
        - Acesso restrito a admin e gestao_rv
        - 10 endpoints em /api/insights/*

**Feature Specifications:**
- Dynamic control over AI behavior parameters.
- Real-time campaign dispatch with SSE.
- Background document processing for the knowledge base.
- Customizable fields for profiles and campaigns.
- Automated admin user creation via environment variables.

## External Dependencies

- **OpenAI API:** For AI agent interactions and text embeddings.
- **Z-API:** For WhatsApp messaging integration (inbound and outbound).
- **PostgreSQL:** Primary relational database.
- **ChromaDB:** Vector database for semantic search.
- **Jinja2:** Templating engine for frontend rendering.
- **Inter Font (Google Fonts):** Standardized typography.
- **Tailwind CSS:** Utility-first CSS framework (CDN mode for gradual migration).

## Tailwind CSS Migration

**Status:** Fase 1 - Setup concluído (CDN mode)

**Arquivos de configuração:**
- `frontend/static/tailwind.config.js` - Tokens do Design System SVN
- `frontend/templates/tailwind_test.html` - Página de referência de componentes

**Mapeamento CSS → Tailwind:**

| Classe CSS Original | Classe Tailwind Equivalente |
|---------------------|----------------------------|
| `.btn.btn-primary` | `px-4 py-2 bg-primary text-white rounded-btn font-medium hover:bg-primary-dark` |
| `.btn.btn-secondary` | `px-4 py-2 bg-card text-foreground border border-border rounded-btn font-medium` |
| `.form-input` | `w-full px-3 py-2 bg-card border border-border rounded-input text-foreground` |
| `.form-label` | `block text-sm font-medium text-foreground mb-1` |
| `.card` | `bg-card rounded-card border border-border p-6 shadow-card` |
| `.alert.alert-success` | `p-4 bg-success/10 border border-success/20 rounded-card text-success` |
| `.page-title` | `text-2xl font-bold text-foreground` |
| `.page-subtitle` | `text-muted` |

**Cores personalizadas (tailwind.config.js):**
- `primary` (#772B21), `primary-dark` (#381811), `primary-light` (#CFE3DA)
- `background` (#FFF8F3), `card` (#ffffff), `foreground` (#221B19)
- `muted` (#5a4f4c), `border` (#e5dcd7)
- `success` (#10b981), `warning` (#f59e0b), `danger` (#AC3631)
- `svn-brown` (#8b4513), `svn-orange` (#dc7f37), `svn-green` (#6b8e23)

**Acesso à página de teste:** `/tailwind-test` (apenas admin)

## React POC - Base de Conhecimento UX

**Status:** POC implementada para validação de UX

**Objetivo:** Testar UX moderna tipo SaaS para a Base de Conhecimento, comparando com a tela atual. A pergunta central: "É mais rápido, mais claro e mais natural atualizar um produto aqui do que na tela atual?"

**Stack:**
- React 18 + Vite (build estático servido pelo FastAPI)
- Tailwind CSS (mesmos tokens do Design System SVN)
- Radix UI (Dialog, Select)
- Framer Motion (microinterações)

**Localização:** `frontend/react-poc/`

**Componentes criados:**
- `StatusBadge` - Badge com cores e indicador de ponto
- `Button` - 5 variantes com animações
- `SearchBar` - Busca com ícone
- `SkeletonLoader` - Estado de loading
- `FilterSelect` - Radix UI Select para filtros
- `ProductCard` - Card com info, tickers, barra de confiança, hover effects
- `InlineEditField` - Edição inline com estados (idle, editing, saving, success, error)
- `ProductDrawer` - Painel lateral com Radix Dialog + Framer Motion

**Features:**
- Grid de cards de produtos (6 FIIs como mock dinâmico)
- Busca por nome/ticker em tempo real
- Filtros por categoria, status, ticker
- Drawer com edição inline de taxa, one-page, script WhatsApp
- Estados visuais claros (loading, salvando, sucesso, erro)
- Microinterações (hover, animação de save)

**Acesso:** `/tailwind-test-knowledge` (apenas admin)

**Build:** `cd frontend/react-poc && npm run build`