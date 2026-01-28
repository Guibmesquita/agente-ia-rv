# Agente IA - RV - Agente de IA para Assessores Financeiros

## Overview

This project is a comprehensive FastAPI application designed as an AI agent for financial advisors. It aims to streamline communication, knowledge retrieval, and client management for financial advisory services. The system integrates with WhatsApp via Z-API (migrated from WAHA API), leverages semantic search on a Notion-based knowledge base using ChromaDB and OpenAI embeddings, and features an administrative dashboard. This dashboard includes a Kanban ticket system, user management with JWT authentication, and analytics for performance tracking. The project vision is to enhance advisor efficiency, improve client interaction, and provide robust tools for managing advisory operations.

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
- **FII External Lookup (services/fii_lookup.py):** When a user asks about a FII that is NOT in the knowledge base, the agent automatically fetches public data from FundsExplorer.com.br and responds with a disclaimer that it's not an official SVN recommendation. 
  - **Ativos Suportados:** FIIs de Tijolo, FIIs de Papel, FIIs Híbridos, e FOFs (Fundos de Fundos)
  - **Padrão de Ticker:** 4 letras + "11" (regex: ^[A-Z]{4}11$) - ex: HABT11, XPLG11, MXRF11
  - **Informações Disponíveis:** Cotação, DY, P/VP, valor patrimonial, patrimônio, último dividendo, liquidez, rentabilidade
  - **Ativos NÃO Suportados:** Ações (PETR4), ETFs (BOVA11, IVVB11), BDRs (AAPL34), Tesouro Direto, Criptomoedas
  - **Lista de ETFs Excluídos:** BOVA11, IVVB11, SMAL11, HASH11, QBTC11, etc. (apesar de terminar em 11, não são FIIs)
  - **Features Técnicas:** Sessão persistente, cache de 5 minutos, rate limiting (1-2s entre requests), retry logic (3 tentativas), scraping seletivo por tipo de informação
- **WhatsApp Integration:** Uses Z-API for communication, processing various message types (text, audio, image, document, video) and logging all interactions in `whatsapp_messages` table. Features a "Central de Mensagens" interface styled like WhatsApp Web with real-time polling updates. Implements full LID (WhatsApp privacy identifier) support: stores senderLid and chatLid from webhooks, prioritizes LID lookups over phone numbers, and uses fallback chain (phone → chat_lid → sender_lid) for conversation identification.
- **Authentication & Authorization:** JWT-based authentication secures API endpoints. User roles (`admin`, `gestao_rv`, `broker`, `client`) define access levels, with dynamic menu adjustments.
- **Database:** PostgreSQL (or SQLite for development) managed with SQLAlchemy ORM, defining models for users, tickets, agent configurations, message templates, campaigns, and knowledge documents.
- **Admin Dashboard:** Provides comprehensive tools for:
    - **User Management:** CRUD operations for users.
    - **Integration Management:** Configure and test external API keys (OpenAI, Notion, Z-API) directly from the UI, with temporary in-memory storage and Replit Secrets persistence. Z-API requires instance_id, token, and client_token.
    - **Kanban Ticket System:** For managing client inquiries with statuses and categories.
    - **Analytics:** Dashboard displaying KPIs (Total Interactions, Open/Closed Tickets, Messages Sent, Assessors Impacted), categorized inquiries, and average resolution time per broker, with date filtering.
    - **Assessor Base:** CRUD operations for managing financial advisors, with email as required unique identifier, custom fields, and bulk import via Excel/CSV with flexible column mapping. Email is used as the primary key for cross-referencing between campaigns and the assessor database.
    - **Campaign Management:** A 4-step wizard for mass WhatsApp message campaigns with two origin modes:
        - **Upload Mode:** Import CSV/Excel with data for personalized messages with variable mapping
        - **Base Selection Mode:** Select assessors directly from the database with filters (unidade, equipe) and checkboxes for quick informational broadcasts
        - **Step 3 Message Composer:** Blank message by default, dynamic variable panel showing available fields from data source, click-to-insert variables, attachment upload (images, videos, audio, documents up to 50MB), real-time variable validation with warnings for unavailable variables
        - **Template System:** Create, edit, and reuse message templates with attachments, automatic variable detection, and usage tracking
        - Features: Reusable templates, dynamic variables, intelligent grouping, attachment support via Z-API, and real-time dispatch progress via Server-Sent Events (SSE) with retry mechanisms. Supports delayMessage (1-15 seconds) for natural sending rhythm.
    - **Central de Mensagens:** WhatsApp Web-style interface for managing all conversations. Features real-time updates via SSE (Server-Sent Events), message history grouped by phone number, human takeover capability, and ability to start new conversations with any phone number via modal.
    - **Knowledge Base Management:** Upload, index, categorize, and reindex documents (PDF, DOCX, TXT, images) for the AI agent to consult.

**Feature Specifications:**
- **Agent Configuration:** Dynamic control over AI behavior parameters.
- **Real-time Campaign Dispatch:** SSE for progress updates and retry logic during mass messaging.
- **Document Processing:** Background indexing of knowledge base documents with chunking and embedding generation.
- **Customizable Fields:** Dynamic custom fields for assessor profiles and campaign data.
- **Automated Bootstrap:** Admin user creation and configuration via environment variables.

**AI Agent Identity - Stevan:**
O agente de IA se chama **Stevan** e possui identidade bem definida:
- **Papel:** Broker de suporte e assistente técnico interno da SVN, área de Renda Variável
- **Público-alvo:** Brokers e assessores de investimentos (uso interno apenas)
- **Função:** Traduz, organiza e esclarece estratégias e produtos definidos pela área de RV
- **Competências:**
  - Estratégias de renda variável da SVN
  - Produtos recomendados pela área
  - Racional técnico das estratégias
  - Enquadramentos e diretrizes internas
  - Esclarecimento técnico inicial
- **Limites operacionais:**
  - NÃO cria estratégias novas ou improvisa recomendações
  - NÃO participa de reuniões com clientes
  - NÃO personaliza alocação para clientes finais
  - NÃO explica regras internas ou funcionamento do sistema
- **Comunicação:** Profissional e próxima, objetiva, informal adequada ao WhatsApp
- **Escalação:** Quando necessário, encaminha para especialista humano com naturalidade

**AI Agent Response Framework (services/conversation_flow.py):**
- **Conversation State Machine:** Uses `ConversationState` enum with 3 states:
  - `IDENTIFICATION_PENDING`: Contato desconhecido, aguardando identificação
  - `READY`: Contato identificado, pronto para processar mensagens
  - `IN_PROGRESS`: Conversa em andamento com contexto ativo
- **Message Normalization:** `normalize_message()` remove ruídos, emojis, espaços extras antes de processar
- **Contact Identification Flow:**
  - `identify_contact()` busca por telefone na tabela Assessor usando normalização flexível (com/sem 9 após DDD)
  - Função `normalize_phone_variants()` gera múltiplas variantes do número para busca flexível
  - **NUNCA cria novos assessores automaticamente** - apenas identifica assessores existentes
  - Contatos não identificados podem conversar normalmente, mas sem vínculo a assessor
- **Integrated Classification:** Prompt do agente classifica internamente em 4 categorias:
  - SAUDAÇÃO: Cumprimentos e mensagens iniciais
  - ESCOPO: Perguntas dentro do domínio do agente (RV)
  - DOCUMENTAL: Questões que requerem consulta à base de conhecimento
  - FORA_ESCOPO: Perguntas fora do domínio do agente
- **Human Transfer Criteria:** `should_transfer_to_human()` avalia:
  - Solicitação explícita do usuário
  - Fricção emocional (frustração, reclamações)
  - Contador de interações sem progresso (stalled_interactions)
- **Response Variations:** Funções para evitar respostas mecânicas:
  - `get_identification_prompt()`: Stevan se apresenta e pede identificação
  - `get_transfer_message()`: Variações para comunicar transferência ao time
  - `get_out_of_scope_redirect()`: Redireciona para foco em RV
- **Conversation Context Accumulation (services/openai_agent.py):**
  - `_extract_entities_from_history()`: Extrai produtos/tickers/fundos mencionados ao longo de toda a conversa, iterando do mais recente para o mais antigo
  - `_is_followup_question()`: Detecta perguntas de follow-up através de padrões linguísticos:
    - Pronomes anafóricos: "dele", "dessa", "desse", "disso", "nele"
    - Conectivos de continuidade: "e o", "e a", "e qual", "e como"
    - Perguntas curtas sem entidade: "qual a data?", "quanto é?"
  - **Fluxo de Contexto Acumulado:** Quando uma pergunta é detectada como follow-up e não contém entidade própria, o sistema extrai as entidades do histórico da conversa e enriquece a busca semântica com esse contexto
  - **Exemplo:** Usuário pergunta "TG Core" → depois "e a data de liquidação?" → Sistema busca documentos sobre "TG CORE data de liquidação"
- **Ticker Search with AI Intent Classification (services/openai_agent.py + services/vector_store.py):**
  - `levenshtein_distance()`: Calcula distância de edição entre strings para encontrar tickers similares
  - `find_exact_ticker()`: Verifica se ticker existe EXATAMENTE na base
  - `find_similar_tickers()`: Busca tickers/produtos similares usando Levenshtein e prefixo comum
  - `_classify_intent_with_ai()`: **USA GPT PARA INTERPRETAR A INTENÇÃO DO USUÁRIO** - não usa regex patterns
  - `_extract_suggestion_context()`: Extrai ticker original e sugestões do histórico da conversa
  - `_detect_ticker_confirmation_async()`: Detecta confirmação/negação usando classificação inteligente com IA
  - **Classificação de Intenção com IA:**
    - `CONFIRMA_ORIGINAL`: Usuário quer o ticker que perguntou originalmente (ex: "TGRE11 mesmo", "não, era esse")
    - `ACEITA_SUGESTAO`: Usuário aceita uma sugestão oferecida (ex: "sim", "o primeiro", mencionar o ticker sugerido)
    - `NEGA_TODOS`: Usuário não quer nenhum (ex: "nenhum desses", "deixa pra lá")
    - `NOVA_PERGUNTA`: É uma pergunta diferente ou mudança de assunto
  - **Fluxo de Confirmação:**
    1. Ticker não encontrado exatamente → busca similares
    2. Se há similares → pergunta "Você quis dizer X, Y?"
    3. **IA interpreta a resposta** e classifica a intenção
    4. CONFIRMA_ORIGINAL + FII (XXXX11) → busca no FundsExplorer
    5. CONFIRMA_ORIGINAL + não-FII → busca na base de conhecimento
    6. ACEITA_SUGESTAO → busca o ticker sugerido na base
    7. NEGA_TODOS → encerra fluxo de confirmação
  - **NUNCA assume** que o usuário quis dizer outro ativo sem confirmação explícita
  - **Vantagem da IA:** Interpreta linguagem natural sem depender de padrões regex fixos
- **Communication Style Improvements:**
  - Stevan NUNCA termina respostas com "Se precisar de mais alguma coisa" ou frases repetitivas similares
  - Respostas são diretas e naturais, encerrando após entregar a informação

## External Dependencies

- **OpenAI API:** Used for AI agent interactions (chat models) and generating text embeddings for semantic search.
- **Notion API:** For fetching and indexing content from a Notion database to build the knowledge base.
- **Z-API:** Integrates WhatsApp messaging capabilities via `https://api.z-api.io/instances/{ID}/token/{TOKEN}/` with Client-Token header authentication. Handles inbound (ReceivedCallback webhook) and outbound communications.
- **PostgreSQL:** Primary relational database for persistent storage (can default to SQLite for local development).
- **ChromaDB:** Vector database used for efficient semantic search on knowledge base embeddings.
- **Jinja2:** Templating engine for rendering HTML frontends.
- **Inter Font (Google Fonts):** Standardized typography across the application.