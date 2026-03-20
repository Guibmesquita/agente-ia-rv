# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview
Stevan is a FastAPI-based AI agent designed to enhance efficiency for financial advisors. Its core purpose is to leverage AI for natural language understanding to centralize information, automate routine tasks, and improve client interactions. Key capabilities include WhatsApp integration, semantic search within a product knowledge base, and an administrative panel for analytics, user management, and campaign tools.

## User Preferences
Prefiro explicações detalhadas.
Quero um processo de desenvolvimento iterativo.
Pergunte antes de fazer mudanças arquiteturais significativas.
Garanta que o código seja bem documentado e legível.
Foque em boas práticas de segurança.
Prefiro um design de UI limpo e minimalista.
Garanta que todos os textos voltados ao usuário estejam em português gramaticalmente correto com acentuação adequada.
CRÍTICO: NUNCA perca funcionalidades existentes ao fazer mudanças. Sempre verifique se as funcionalidades implementadas anteriormente permanecem intactas. Antes de modificar qualquer componente, revise quais funcionalidades existem e garanta que sejam preservadas. Chame o architect para validar mudanças de UX.

## System Architecture
The application is built using FastAPI with a modular architecture.

**UI/UX Decisions:** The design system features a minimizable vertical sidebar, light theme, and Inter font. Global CSS centralizes styling, navigation is dynamic based on user roles, and a custom toast notification system provides consistent feedback. Modern React + Tailwind screens use Tailwind Preflight and utilities for spacing and styling, ensuring a modern SaaS-style user experience.

**Technical Implementations:**
- **AI Agent (Stevan) — Pipeline V2 Agentic RAG:** Uses OpenAI function calling for iterative tool use (MAX_ITERATIONS=3). GPT decides when to search, and tools include `search_knowledge_base`, `search_web`, `lookup_fii_public`, `send_document`, and `send_payoff_diagram`. Parallel tool execution is supported.
- **Semantic Search (RAG V3.2 Enhanced):** Utilizes `pgvector` and OpenAI `text-embedding-3-large` with hybrid ranking, intelligent ticker detection, a financial glossary for query expansion, and semantic enrichment. Content blocks with JSON tabular data are resolved at query time. Temporal Reference Enrichment enhances content blocks lacking temporal context.
- **Manager Disambiguation V2 (GPT-driven):** GPT-4o semantically determines if a user query refers to a financial manager, replacing substring matching to avoid false positives.
- **AI Document Summaries:** Automatic conceptual summaries and theme generation for documents using GPT-4o-mini.
- **Semantic Transformer:** A 3-layer architecture for technical extraction, semantic modeling, and narrative chunk generation for RAG indexing.
- **XPI Derivatives System:** A knowledge base for structured products with a 4-step conversational disambiguation flow, including content extracted via GPT-4 Vision and payoff diagrams.
- **External FIIs Query:** Fetches public FII data from FundsExplorer.com.br.
- **WhatsApp Integration:** Uses Z-API for various message types, logs interactions, and provides a "Message Center" interface. Supports full media processing (audio transcription with Whisper, image/document analysis). Includes message debounce, persistent conversation history, and hierarchical memory. The agent autonomously decides tool usage for actions like sending documents. Human handoff triggers ticket creation.
- **Testar Agente:** A testing environment that mirrors the WhatsApp integration's Pipeline V2, including `generate_response_v2` and in-memory session summaries.
- **Authentication and Authorization:** JWT-based with role-based access control, JWT hardening, rate limiting, account lockout, and comprehensive security headers.
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM.
- **Admin Panel:** Provides tools for user, integration, advisor, and campaign management, a "Message Center," and knowledge base management.
- **Product CMS:** Manages products, materials, and content blocks. Features include PDF upload with GPT-4 Vision extraction, approval system, semantic indexing, WhatsApp scripts, versioning, and validity control. PDFs are persistently stored in PostgreSQL. A public download endpoint is available. The "SmartUpload" interface unifies pending materials management, including duplicate detection and bulk re-upload.
- **Intelligent Upload with Metadata Extraction:** `DocumentMetadataExtractor` service uses GPT-4 Vision to analyze PDFs and extract metadata. Adaptive DPI is used for PDF rendering. Resume-upload functionality and startup cleanup for stale processing jobs are implemented.
- **Dependency Health Check:** Validates critical dependencies on startup and provides real-time status via `/api/health/detailed`. Z-API and OpenAI health are monitored with background loops and cached statuses.
- **Bot & Z-API Error Visibility:** The UI provides visual indicators and banners for bot errors (e.g., OpenAI quota exhausted) and Z-API disconnection, with an option to acknowledge critical alerts. Message status indicators track outbound message delivery.
- **OpenAI Health Monitoring:** Monitors OpenAI API status, particularly for quota exhaustion, with recovery checks and administrative acknowledgment options.
- **Observability and Auditing:** Includes `RetrievalLog` for RAG searches, `IngestionLog` for document ingestion, RAG analytics, and content block tracking.
- **AI Agent Response Framework:** Utilizes a `ConversationState` machine, message normalization, contact identification, and AI-based intent classification for human transfer.
- **Escalation Intelligence V2.1:** GPT analysis on escalations with categorization and automatic ticket summary generation.
- **Bot Resolution Tracking V2.2:** Tracks bot-resolved conversations and metrics.
- **Separate Ticket Architecture V2.3:** Separates `Conversation` and `ConversationTicket` models for distinct historical data.
- **Insights Dashboard:** A management dashboard for Variable Income with `ConversationInsight` model, post-conversation GPT analysis, classification categories, dynamic filters, KPI cards, Chart.js graphs, rankings, and campaign summaries.
- **Web Search:** Fallback for real-time market data using Tavily AI, with a whitelist of trusted sources and an audit log.
- **Deployment Strategy:** Migrated to Railway via GitHub, using a Dockerfile with `python:3.12-slim`. React frontend assets are pre-compiled and committed to the repository for deployment.
- **Campaign Structures with Temporal Validity:** Manages active derivative campaigns with temporal filtering, auto-injecting active campaigns into Stevan's system prompt. Campaign-specific diagrams override generic ones. A frontend management page provides CRUD interface.

**Feature Specifications:** Dynamic control over AI behavior parameters, real-time campaign sending with SSE, background document processing, customizable fields, and automatic admin user creation.

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