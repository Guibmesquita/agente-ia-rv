# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview

This project is a comprehensive FastAPI application designed as an AI agent for financial advisors. It aims to streamline communication, knowledge retrieval, and client management for financial advisory services. The system integrates with WhatsApp via WAHA API, leverages semantic search on a Notion-based knowledge base using ChromaDB and OpenAI embeddings, and features an administrative dashboard. This dashboard includes a Kanban ticket system, user management with JWT authentication, and analytics for performance tracking. The project vision is to enhance advisor efficiency, improve client interaction, and provide robust tools for managing advisory operations.

## User Preferences

I prefer detailed explanations.
I want an iterative development process.
Ask before making major architectural changes.
Ensure code is well-documented and readable.
Focus on security best practices.
I prefer a clean and minimalist UI design.
Ensure all user-facing texts are in grammatically correct Portuguese with proper accentuation.

## System Architecture

The application is built using FastAPI, leveraging a modular project structure.

**UI/UX Decisions:**
- **Design System:** A complete redesign incorporates a new system with a minimizable vertical sidebar, light theme, and the Inter font.
- **Global CSS:** `frontend/static/global.css` centralizes styling with CSS Custom Properties for colors (e.g., `--primary-color: #4f46e5`), typography, and reusable components like `.card`, `.btn`, and `.modal`.
- **Navigation:** A dynamic sidebar adjusts visibility based on user roles, and its state is persisted using `localStorage`.
- **Modals:** Standardized modal structures are used for consistent user experience.

**Technical Implementations:**
- **AI Agent:** Integrates OpenAI for embeddings and chat, allowing real-time configuration of personality, rules, restrictions, AI model (GPT-4o, GPT-4 Turbo, GPT-4, GPT-3.5 Turbo), temperature, and response length via the `/agent-brain` panel.
- **Semantic Search:** Utilizes ChromaDB for vector storage and OpenAI embeddings to enable semantic search over a Notion knowledge base. Documents are chunked and indexed in the background.
- **WhatsApp Integration:** Uses WAHA API for communication, processing various message types (text, audio, image, document, video) and logging all interactions in `whatsapp_messages` table.
- **Authentication & Authorization:** JWT-based authentication secures API endpoints. User roles (`admin`, `gestao_rv`, `broker`, `client`) define access levels, with dynamic menu adjustments.
- **Database:** PostgreSQL (or SQLite for development) managed with SQLAlchemy ORM, defining models for users, tickets, agent configurations, message templates, campaigns, and knowledge documents.
- **Admin Dashboard:** Provides comprehensive tools for:
    - **User Management:** CRUD operations for users.
    - **Integration Management:** Configure and test external API keys (OpenAI, Notion, WAHA) directly from the UI, with temporary in-memory storage and Replit Secrets persistence.
    - **Kanban Ticket System:** For managing client inquiries with statuses and categories.
    - **Analytics:** Dashboard displaying KPIs (Total Interactions, Open/Closed Tickets, Messages Sent, Assessors Impacted), categorized inquiries, and average resolution time per broker, with date filtering.
    - **Assessor Base:** CRUD operations for managing financial advisors, including custom fields and bulk import via Excel/CSV with flexible column mapping.
    - **Campaign Management:** A 4-step wizard for mass WhatsApp message campaigns with reusable templates, dynamic variables, intelligent grouping, and real-time dispatch progress via Server-Sent Events (SSE) with retry mechanisms.
    - **Knowledge Base Management:** Upload, index, categorize, and reindex documents (PDF, DOCX, TXT, images) for the AI agent to consult.

**Feature Specifications:**
- **Agent Configuration:** Dynamic control over AI behavior parameters.
- **Real-time Campaign Dispatch:** SSE for progress updates and retry logic during mass messaging.
- **Document Processing:** Background indexing of knowledge base documents with chunking and embedding generation.
- **Customizable Fields:** Dynamic custom fields for assessor profiles and campaign data.
- **Automated Bootstrap:** Admin user creation and configuration via environment variables.

## External Dependencies

- **OpenAI API:** Used for AI agent interactions (chat models) and generating text embeddings for semantic search.
- **Notion API:** For fetching and indexing content from a Notion database to build the knowledge base.
- **WAHA API:** Integrates WhatsApp messaging capabilities, handling inbound and outbound communications.
- **PostgreSQL:** Primary relational database for persistent storage (can default to SQLite for local development).
- **ChromaDB:** Vector database used for efficient semantic search on knowledge base embeddings.
- **Jinja2:** Templating engine for rendering HTML frontends.
- **Inter Font (Google Fonts):** Standardized typography across the application.