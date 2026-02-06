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

**PRINCÍPIO DE DESIGN FUNDAMENTAL (Compreensão Natural):**
Toda interação com o assessor na ponta final deve ser processada pelo OpenAI com contexto da conversa para compreensão natural da intenção. O OpenAI é o "cérebro" do Stevan — ele analisa, entende e decide. O sistema fornece "ferramentas" (enviar diagrama, buscar na web, buscar no RAG, escalar para humano) que o OpenAI pode acionar. Regras fixas pré-OpenAI existem apenas como otimização de custo/velocidade para casos triviais, nunca como substituto da compreensão natural. Quando o OpenAI identifica uma ação (ex: enviar diagrama), ele retorna uma marcação especial (ex: `[ENVIAR_DIAGRAMA:slug]`) e o sistema executa a ação real.

## Arquitetura do Sistema
A aplicação é construída usando FastAPI com arquitetura modular.

**Decisões de UI/UX:** O sistema de design apresenta uma barra lateral vertical minimizável, tema claro e fonte Inter. O CSS global centraliza a estilização, a navegação é dinâmica baseada em roles de usuário, e um sistema de notificações toast personalizado fornece feedback consistente. Telas modernas em React + Tailwind utilizam exclusivamente Tailwind Preflight e utilitários para espaçamento e estilização, garantindo uma experiência de usuário moderna estilo SaaS.

**Implementações Técnicas:**
- **Agente de IA (Stevan):** Integra OpenAI para chat e embeddings, configurável para personalidade, regras e parâmetros do modelo. Atua como um broker de suporte interno, explicando estratégias e produtos, e escalando para especialistas humanos.
- **Busca Semântica (RAG V3.1 Aprimorado):** Utiliza ChromaDB e OpenAI text-embedding-3-large com ranking híbrido (vetor, recência, correspondência_exata, topic_match). Chunks incluem contexto global e metadados semânticos (topic, concepts). Detecção inteligente de ticker com variações (ex: "mana 11" → MANA11). Glossário financeiro com 824 conceitos em 13 categorias (`services/financial_concepts.py`) expande queries automaticamente com termos relacionados. Categorias incluem: ESTRUTURA_FUNDO, PERFORMANCE, DISTRIBUICAO, COMPOSICAO, RISCO, MERCADO, DERIVATIVOS, OPERACIONAL, OPCOES_DERIVATIVOS, RENDA_FIXA, TRADING, ASSESSOR_JARGAO, GLOSSARIO_B3 (677 termos oficiais extraídos do glossário da B3/Bora Investir via script `scripts/extract_b3_glossary.py`). Enriquecimento semântico de chunks via GPT-4o-mini (`scripts/enrich_chunks.py`). Script de validação em `scripts/validate_glossary.py` verifica integridade (parênteses malformados, IDs duplicados, colisões de abreviações). Sistema de avaliação RAG (Nível 2) em `tests/rag_evaluation/` e testes de conversa em `tests/conversation_tests/`.
- **Desambiguação de Gestora:** Quando usuário menciona uma gestora (ex: "Manatí", "TG Core") sem ticker específico, o sistema detecta automaticamente, lista os produtos disponíveis dessa gestora e pergunta qual o usuário deseja. Suporta respostas ordinais ("o primeiro", "segundo") e por nome/ticker.
- **Resumos de Documentos por IA:** Geração automática de resumos conceituais e temas para cada documento usando GPT-4o-mini, armazenados no modelo de material.
- **Transformador Semântico (Arquitetura de 3 Camadas):** Processa conteúdo através de extração técnica (GPT-4 Vision), modelo semântico (normalização de dados) e geração de chunks narrativos para indexação RAG.
- **Sistema de Derivativos XPI (27 Estruturas):** Base de conhecimento completa de produtos estruturados com fluxo conversacional de desambiguação em 4 etapas. 20/27 estruturas enriquecidas com conteúdo extraído via GPT-4 Vision (descrição detalhada, componentes, riscos, cenários, exemplos numéricos, payoff). 20 diagramas de payoff extraídos de PDFs e servidos via `/derivatives-diagrams/`. Envio de diagramas via WhatsApp apenas sob pedido explícito do assessor, com detecção de keywords e confirmações contextuais. Dataset em `scripts/xpi_derivatives/`, cache enriquecido em `enriched_cache/`, diagramas em `static/derivatives_diagrams/`.
- **Consulta Externa de FIIs:** Busca automaticamente dados públicos de FIIs do FundsExplorer.com.br.
- **Integração WhatsApp:** Usa Z-API para vários tipos de mensagens, registra interações e fornece uma interface "Central de Mensagens" com atualizações em tempo real e identificação de conversas, incluindo suporte completo a mídia (transcrição de áudio com Whisper otimizado para vocabulário financeiro, análise de imagem, processamento de documentos). Transcrição de áudio inclui prompt contextual com ~200 termos financeiros para guiar o Whisper e pós-processamento automático de correção de termos (`normalize_financial_transcription` em `services/media_processor.py`).
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

## Métricas do Dashboard de Insights

O Dashboard de Insights apresenta métricas de gestão para acompanhar o desempenho do Stevan e da equipe. Todas as métricas podem ser filtradas por período (7d, 30d, 90d, 365d), macro área, unidade, broker e equipe.

### KPIs Principais (Cards)

| Métrica | Descrição | Cálculo |
|---------|-----------|---------|
| **Total de Interações** | Número total de conversas/mensagens processadas no período | `COUNT(ConversationInsight)` no período selecionado |
| **Assessores Ativos** | Quantidade de assessores únicos que interagiram com o Stevan | `COUNT(DISTINCT assessor_id)` onde assessor_id não é nulo |
| **Taxa de Resolução IA** | Percentual de conversas resolvidas pelo bot sem intervenção humana | `(resolved_by_ai=True AND escalated_to_human=False) / total * 100` |
| **Escalações** | Número de conversas transferidas para atendimento humano | `COUNT(escalated_to_human=True)` |
| **Tickets Criados** | Quantidade de tickets de atendimento gerados | `COUNT(ticket_created=True)` |
| **Campanhas Enviadas** | Total de campanhas de comunicação disparadas | `COUNT(Campaign)` no período |
| **Assessores Alcançados** | Assessores únicos que receberam campanhas | `COUNT(DISTINCT CampaignDispatch.assessor_id)` com status "sent" |

### Gráficos e Visualizações

| Gráfico | Descrição | Fonte de Dados |
|---------|-----------|----------------|
| **Atividade Diária** | Volume de interações por dia (linha temporal) | Agrupamento de `ConversationInsight.created_at` por data |
| **Categorias de Dúvidas** | Top 10 categorias mais frequentes (pizza/barras) | Agrupamento por `ConversationInsight.category`, excluindo "Saudação" |
| **Produtos/Tickers** | Top 10 tickers mais mencionados pelos assessores | Parsing do campo JSON `tickers_mentioned` e contagem |
| **Resolução IA vs Humano** | Proporção entre atendimentos automatizados e escalados | `resolved_by_ai` vs `escalated_to_human` |
| **Top 5 Unidades** | Ranking das unidades com mais interações | Agrupamento por `unidade` ordenado por volume |
| **Top 5 Assessores** | Ranking dos assessores mais ativos | Agrupamento por `assessor_id` ordenado por volume |

### Categorias de Classificação

Cada interação é classificada automaticamente pelo GPT em uma das seguintes categorias:

| Categoria | Descrição |
|-----------|-----------|
| **SAUDACAO** | Cumprimentos e saudações iniciais |
| **DOCUMENTAL** | Dúvidas sobre documentos, relatórios e materiais |
| **ESCOPO** | Perguntas sobre produtos e estratégias dentro do escopo do Stevan |
| **MERCADO** | Queries sobre dados de mercado em tempo real (ativa busca web) |
| **PITCH** | Solicitações de argumentos comerciais e textos de venda |
| **ATENDIMENTO_HUMANO** | Solicitação explícita de falar com humano |
| **FORA_ESCOPO** | Perguntas fora do conhecimento do Stevan |

### Modelo de Dados (ConversationInsight)

O modelo `ConversationInsight` armazena análises pós-conversa geradas pelo GPT:
- `category`: Classificação da intenção da mensagem
- `resolved_by_ai`: Se o bot conseguiu resolver a dúvida
- `escalated_to_human`: Se houve transferência para humano
- `ticket_created`: Se um ticket foi gerado
- `tickers_mentioned`: JSON com tickers/produtos mencionados
- `assessor_id`: Referência ao assessor da conversa
- `unidade`, `macro_area`, `equipe`, `broker_responsavel`: Campos de segmentação organizacional
