# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview
Stevan is a FastAPI-based AI agent designed to enhance efficiency for financial advisors by centralizing information, automating routine tasks, and improving client interactions. Its core purpose is to leverage AI for natural language understanding to provide intelligent support and streamline workflows for financial advisors. Key capabilities include WhatsApp integration, semantic search within a product knowledge base, and an administrative panel for analytics, user management, and campaign tools.

## User Preferences
Prefiro explicações detalhadas.
Quero um processo de desenvolvimento iterativo.
Pergunte antes de fazer mudanças arquiteturais significativas.
Garanta que o código seja bem documentado e legível.
Foque em boas práticas de segurança.
Prefiro um design de UI limpo e minimalista.
Garanta que todos os textos voltados ao usuário estejam em português gramaticalmente correto com acentuação adequada.
**CRÍTICO: NUNCA perca funcionalidades existentes ao fazer mudanças.** Sempre verifique se as funcionalidades implementadas anteriormente permanecem intactas. Antes de modificar qualquer componente, revise quais funcionalidades existem e garanta que sejam preservadas. Chame o architect para validar mudanças de UX.

## System Architecture
The application is built using FastAPI with a modular architecture.

**UI/UX Decisions:** The design system features a minimizable vertical sidebar, light theme, and Inter font. Global CSS centralizes styling, navigation is dynamic based on user roles, and a custom toast notification system provides consistent feedback. Modern React + Tailwind screens exclusively use Tailwind Preflight and utilities for spacing and styling, ensuring a modern SaaS-style user experience.

**Technical Implementations:**
- **AI Agent (Stevan):** Integrates OpenAI for chat and embeddings, configurable for personality, rules, and model parameters. It includes a Query Rewriter (`services/query_rewriter.py`) with GPT-4o-mini for context-aware query rewriting, topic switch detection, comparative query handling, and pronoun resolution from conversation history.
- **Semantic Search (RAG V3.1 Enhanced):** Utilizes `pgvector (PostgreSQL)` and OpenAI `text-embedding-3-large` with hybrid ranking, intelligent ticker detection, a financial glossary for query expansion, and semantic enrichment. Indexing uses `index_approved_blocks` only, and product/material deletion automatically cleans vector store embeddings. Includes Temporal Reference Enrichment (`services/temporal_enrichment.py`): at query time, content blocks with quantitative data but no temporal reference are enriched by inspecting ±2 neighbor blocks (by `order` within the same `material_id`) for dates/periods, prefixing the content with `[Ref.Temporal: ...]`. This is read-only (no DB writes) and non-blocking.
- **Manager Disambiguation:** Automatically detects and clarifies financial manager mentions, listing available products and allowing selection.
- **AI Document Summaries:** Automatic conceptual summaries and theme generation for documents using GPT-4o-mini.
- **Semantic Transformer:** A 3-layer architecture processes content through technical extraction (GPT-4 Vision), semantic modeling, and narrative chunk generation for RAG indexing.
- **XPI Derivatives System:** A comprehensive knowledge base for structured products with a 4-step conversational disambiguation flow, including content extracted via GPT-4 Vision and payoff diagrams.
- **External FIIs Query:** Automatically fetches public FII data from FundsExplorer.com.br.
- **WhatsApp Integration:** Uses Z-API for various message types, logs interactions, and provides a "Message Center" interface with real-time updates. Supports full media processing, including optimized audio transcription (Whisper) and image/document analysis.
- **Authentication and Authorization:** JWT-based with role-based access control, JWT hardening, rate limiting, account lockout, and comprehensive security headers. Global auth middleware is implemented, and structured security event logging is used.
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM.
- **Admin Panel:** Provides tools for user, integration, advisor, and campaign management, a "Message Center," and knowledge base management.
- **Product CMS:** Manages products, materials, and content blocks, featuring PDF upload with GPT-4 Vision extraction, approval system, semantic indexing, WhatsApp scripts, versioning, and validity control.
- **Intelligent Upload with Metadata Extraction:** `DocumentMetadataExtractor` service uses GPT-4 Vision to analyze PDFs and extract metadata for automated product matching or creation. Adaptive DPI is used for PDF rendering.
- **Dependency Health Check:** `services/dependency_check.py` validates critical dependencies on startup, and `/api/health/detailed` provides real-time status.
- **Observability and Auditing:** Includes `RetrievalLog` for RAG searches, `IngestionLog` for document ingestion, RAG analytics, and content block tracking.
- **AI Agent Response Framework:** Utilizes a `ConversationState` machine, message normalization, contact identification, and AI-based intent classification for human transfer.
- **Escalation Intelligence V2.1:** GPT analysis on each escalation with 11 categories, auto-generating ticket summaries.
- **Bot Resolution Tracking V2.2:** Tracks bot-resolved conversations, including resolution metrics.
- **Separate Ticket Architecture V2.3:** `Conversation` and `ConversationTicket` are separate models, allowing continuous chat sessions with distinct historical data.
- **Insights Dashboard:** A management dashboard for Variable Income with `ConversationInsight` model, post-conversation GPT analysis, classification categories, dynamic filters, KPI cards, Chart.js graphs, rankings, and campaign summaries.
- **Web Search (Tavily AI):** Fallback for real-time market data when internal knowledge is insufficient, including a whitelist of trusted sources and an audit log.
- **Deployment Strategy:** Migrated from Replit to Railway via GitHub. The Dockerfile uses `python:3.12-slim` with necessary system dependencies. React frontend builds are pre-compiled in Replit and committed to the repository, as the Dockerfile is Python-only.

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