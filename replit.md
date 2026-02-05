# Agente IA - RV - Agente de IA para Assessores Financeiros

## Visão Geral
Este projeto é uma aplicação FastAPI abrangente chamada Stevan, um agente de IA projetado para assessores financeiros. Seu objetivo principal é aumentar a eficiência nos serviços de assessoria financeira, centralizando informações, automatizando tarefas rotineiras e melhorando a interação com clientes. As principais capacidades incluem integração com WhatsApp, busca semântica em uma base de conhecimento de produtos (CMS), e um painel administrativo com analytics, gestão de usuários e ferramentas de campanhas.

## Preferências do Usuário
Prefiro explicações detalhadas.
Quero um processo de desenvolvimento iterativo.
Pergunte antes de fazer mudanças arquiteturais significativas.
Garanta que o código seja bem documentado e legível.
Foque em boas práticas de segurança.
Prefiro um design de UI limpo e minimalista.
Garanta que todos os textos voltados ao usuário estejam em português gramaticalmente correto com acentuação adequada.
**CRÍTICO: NUNCA perca funcionalidades existentes ao fazer mudanças.** Sempre verifique se as funcionalidades implementadas anteriormente permanecem intactas. Antes de modificar qualquer componente, revise quais funcionalidades existem e garanta que sejam preservadas. Chame o architect para validar mudanças de UX.

## Arquitetura do Sistema
A aplicação é construída usando FastAPI com arquitetura modular.

**Decisões de UI/UX:** O sistema de design apresenta uma barra lateral vertical minimizável, tema claro e fonte Inter. O CSS global centraliza a estilização, a navegação é dinâmica baseada em roles de usuário, e um sistema de notificações toast personalizado fornece feedback consistente. Telas modernas em React + Tailwind utilizam exclusivamente Tailwind Preflight e utilitários para espaçamento e estilização, garantindo uma experiência de usuário moderna estilo SaaS.

**Implementações Técnicas:**
- **Agente de IA (Stevan):** Integra OpenAI para chat e embeddings, configurável para personalidade, regras e parâmetros do modelo. Atua como um broker de suporte interno, explicando estratégias e produtos, e escalando para especialistas humanos.
- **Busca Semântica (RAG V3.0 Aprimorado):** Utiliza ChromaDB e OpenAI text-embedding-3-large com ranking híbrido (vetor, recência, correspondência_exata). Chunks incluem contexto global.
- **Resumos de Documentos por IA:** Geração automática de resumos conceituais e temas para cada documento usando GPT-4o-mini, armazenados no modelo de material.
- **Transformador Semântico (Arquitetura de 3 Camadas):** Processa conteúdo através de extração técnica (GPT-4 Vision), modelo semântico (normalização de dados) e geração de chunks narrativos para indexação RAG.
- **Consulta Externa de FIIs:** Busca automaticamente dados públicos de FIIs do FundsExplorer.com.br.
- **Integração WhatsApp:** Usa Z-API para vários tipos de mensagens, registra interações e fornece uma interface "Central de Mensagens" com atualizações em tempo real e identificação de conversas, incluindo suporte completo a mídia (transcrição de áudio, análise de imagem, processamento de documentos).
- **Autenticação e Autorização:** Baseada em JWT com controle de acesso por roles.
- **Banco de Dados:** PostgreSQL (ou SQLite para desenvolvimento) com SQLAlchemy ORM.
- **Painel Administrativo:** Fornece ferramentas para gestão de usuários, integrações, assessores e campanhas, uma "Central de Mensagens" e gestão da base de conhecimento.
- **CMS de Produtos:** Gerencia produtos, materiais e blocos de conteúdo, apresentando upload de PDF com extração via GPT-4 Vision, sistema de aprovação, indexação semântica, scripts para WhatsApp, versionamento e controle de validade.
- **Upload Inteligente com Extração de Metadados:** O serviço `DocumentMetadataExtractor` usa GPT-4 Vision para analisar PDFs, extraindo metadados como nome_do_fundo, ticker, gestora e tipo_de_documento, com correspondência ou criação automatizada de produtos.
- **Observabilidade e Auditoria:** Inclui `RetrievalLog` para buscas RAG, `IngestionLog` para ingestão de documentos, analytics de RAG, re-ranking inteligente e rastreamento de blocos de conteúdo.
- **Framework de Resposta do Agente de IA:** Utiliza uma máquina de `ConversationState`, normalização de mensagens, identificação de contato e classificação de intenção por IA para transferência humana.
- **Inteligência de Escalação V2.1:** Análise por GPT em cada escalação com 11 categorias, gerando automaticamente resumos de tickets e tópicos de conversa, e rastreando timestamps importantes.
- **Rastreamento de Resolução pelo Bot V2.2:** Rastreia conversas resolvidas pelo bot, inclui campos `bot_resolved_at` e `awaiting_confirmation`, um agendador em background para mensagens de confirmação, e métricas de resolução pelo bot.
- **Arquitetura de Tickets Separados V2.3:** `Conversation` e `ConversationTicket` são modelos separados, permitindo sessões de chat contínuas com dados históricos distintos para cada intervenção humana, rastreando métricas de resolução por ticket.
- **Dashboard de Insights:** Um painel de gestão para Renda Variável com modelo `ConversationInsight`, análise pós-conversa por GPT, 12 categorias de classificação, filtros dinâmicos, cards de KPI, gráficos Chart.js, rankings e resumos de campanhas.
- **Busca Web (Tavily AI):** Fallback para dados de mercado em tempo real quando o conhecimento interno é insuficiente. Inclui whitelist de fontes confiáveis, log de auditoria `WebSearchLog` e UI de administração.
- **Categorias de Classificação:** SAUDACAO, DOCUMENTAL, ESCOPO, MERCADO (queries de mercado em tempo real), PITCH (geração de argumentos de venda), ATENDIMENTO_HUMANO, FORA_ESCOPO.

**Especificações de Funcionalidades:** Controle dinâmico sobre parâmetros de comportamento da IA, envio de campanhas em tempo real com SSE, processamento de documentos em background, campos customizáveis e criação automática de usuário admin.

## Dependências Externas
- **API OpenAI:** Interações do agente de IA e embeddings de texto.
- **Z-API:** Integração de mensagens WhatsApp.
- **Tavily AI:** Busca web para dados de mercado em tempo real.
- **PostgreSQL:** Banco de dados relacional principal.
- **ChromaDB:** Banco de dados vetorial para busca semântica.
- **Jinja2:** Motor de templates.
- **Fonte Inter (Google Fonts):** Tipografia.
- **Tailwind CSS:** Framework CSS utility-first.
- **React 18 + Vite + React Router DOM:** UI moderna da Base de Conhecimento.
- **Radix UI:** Componentes de UI (Dialog, Tabs, Select, Tooltip).
- **Framer Motion:** Animações e transições.
- **Lucide React:** Ícones.
- **react-dropzone:** Upload de arquivos.

## Regras de Negócio Importantes
- **Resposta do Bot:** O bot responde automaticamente EXCETO quando `ticket_status = 'open'` (atendimento humano ativo).
- **Escalação:** Quando há transferência para humano, um ticket é criado e o status muda para 'new'.
- **Tickets:** Status possíveis são `new`, `open`, `solved`, `closed`. Bot só é bloqueado em `open`.
