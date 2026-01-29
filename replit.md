# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview

This project is a comprehensive FastAPI application designed as an AI agent for financial advisors, named Stevan. Its primary purpose is to streamline communication, knowledge retrieval, and client management within financial advisory services. The system integrates WhatsApp, leverages semantic search on a Notion-based knowledge base, and features an administrative dashboard with a Kanban ticket system, user management, and analytics. The vision is to enhance advisor efficiency, improve client interaction, and provide robust tools for managing advisory operations by centralizing information and automating routine tasks.

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
- **Semantic Search:** Utilizes ChromaDB and OpenAI embeddings for semantic search over a Notion knowledge base, with background document chunking and indexing.
- **FII External Lookup:** Automatically fetches public data for FIIs not in the knowledge base from FundsExplorer.com.br, supporting various FII types and providing a disclaimer.
- **WhatsApp Integration:** Uses Z-API for communication, supporting various message types, logging interactions, and featuring a "Central de Mensagens" interface with real-time updates and full LID support for conversation identification.
- **Authentication & Authorization:** JWT-based authentication with role-based access control (`admin`, `gestao_rv`, `broker`, `client`).
- **Database:** PostgreSQL (or SQLite for development) with SQLAlchemy ORM for models including users, tickets, agent configurations, message templates, campaigns, and knowledge documents.
- **Admin Dashboard:** Provides comprehensive tools for:
    - **User Management:** CRUD operations.
    - **Integration Management:** UI-based configuration and testing of API keys (OpenAI, Notion, Z-API).
    - **Kanban Ticket System:** For client inquiry management.
    - **Analytics:** KPIs, categorized inquiries, and resolution times with filtering.
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
- **AI Agent Response Framework:** Employs a `ConversationState` machine, message normalization, and flexible contact identification. It integrates AI for classifying user intent (Greeting, Scope, Documental, Out of Scope) and determining human transfer criteria. It also features conversation context accumulation for follow-up questions and AI-driven ticker search with intelligent confirmation flows, ensuring natural language interpretation over fixed regex patterns.

**Feature Specifications:**
- Dynamic control over AI behavior parameters.
- Real-time campaign dispatch with SSE.
- Background document processing for the knowledge base.
- Customizable fields for profiles and campaigns.
- Automated admin user creation via environment variables.

## External Dependencies

- **OpenAI API:** For AI agent interactions and text embeddings.
- **Notion API:** For knowledge base content retrieval and indexing.
- **Z-API:** For WhatsApp messaging integration (inbound and outbound).
- **PostgreSQL:** Primary relational database.
- **ChromaDB:** Vector database for semantic search.
- **Jinja2:** Templating engine for frontend rendering.
- **Inter Font (Google Fonts):** Standardized typography.