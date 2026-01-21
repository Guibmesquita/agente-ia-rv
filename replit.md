# Agente IA - RV - Agente de IA para Assessores Financeiros

## Visão Geral

Aplicação FastAPI completa para um agente de IA de assessores financeiros. O sistema comunica-se via WhatsApp usando WAHA API, realiza busca semântica em uma base de conhecimento do Notion usando ChromaDB e embeddings OpenAI, e inclui um painel administrativo com sistema de tickets Kanban e gerenciamento de usuários com autenticação JWT.

## Estrutura do Projeto

```
├── main.py                 # Ponto de entrada da aplicação
├── indexer.py              # Script para indexar conteúdo do Notion
├── core/
│   ├── config.py           # Configurações e variáveis de ambiente
│   └── security.py         # Funções de segurança (JWT, hash)
├── database/
│   ├── database.py         # Configuração SQLAlchemy
│   ├── models.py           # Modelos User e Ticket
│   └── crud.py             # Operações CRUD
├── services/
│   ├── openai_agent.py     # Agente de IA com OpenAI
│   ├── vector_store.py     # ChromaDB para busca semântica
│   └── whatsapp_service.py # Integração WAHA API
├── api/endpoints/
│   ├── auth.py             # Autenticação e login
│   ├── users.py            # Gerenciamento de usuários
│   ├── tickets.py          # Sistema de tickets Kanban
│   └── whatsapp_webhook.py # Webhook para mensagens WhatsApp
└── frontend/
    ├── templates/          # Templates HTML (Jinja2)
    └── static/             # CSS e assets
```

## Configuração de Secrets

### Obrigatórios para Produção
- `OPENAI_API_KEY` - Chave da API OpenAI para embeddings e chat
- `NOTION_API_KEY` - Chave da API Notion para indexar documentos
- `WAHA_API_URL` - URL da instância WAHA para WhatsApp

### Opcionais
- `DATABASE_URL` - URL PostgreSQL (usa SQLite local se não definido)
- `SESSION_SECRET` - Chave secreta para JWT
- `ADMIN_USERNAME` - Nome de usuário admin (padrão: admin)
- `ADMIN_PASSWORD` - Senha do admin (padrão: admin123 - ALTERAR EM PRODUÇÃO!)
- `ADMIN_EMAIL` - Email do admin

## Rotas Principais

### API
- `POST /api/auth/login` - Autenticação
- `GET /api/users/` - Listar usuários (admin)
- `GET /api/tickets/` - Listar tickets
- `POST /webhook/whatsapp` - Webhook WAHA
- `GET /api/integrations/` - Listar integrações (admin)
- `GET /api/integrations/{id}/status` - Testar conexão (admin)
- `GET /api/analytics/summary` - Resumo de KPIs (admin/broker)
- `GET /api/analytics/resolution-time` - Tempo médio por assessor (admin/broker)
- `GET /api/analytics/tickets-by-category` - Tickets por categoria (admin/broker)
- `GET /api/agent-config/` - Configuração do agente (admin)
- `PUT /api/agent-config/` - Atualizar configuração do agente (admin)
- `GET /api/assessores` - Listar assessores (admin/broker)
- `POST /api/assessores` - Criar assessor (admin/broker)
- `PUT /api/assessores/{id}` - Atualizar assessor (admin/broker)
- `DELETE /api/assessores/{id}` - Excluir assessor (admin/broker)
- `GET /api/custom-fields` - Listar campos customizados (admin/broker)
- `POST /api/custom-fields` - Criar campo customizado (admin/broker)
- `POST /api/upload/preview` - Preview de planilha para importação (admin/broker)
- `POST /api/upload/confirm` - Confirmar importação com mapeamento (admin/broker)

### Frontend
- `/login` - Página de login (redireciona para /analytics após login)
- `/analytics` - Dashboard de indicadores (admin/broker/gestao_rv)
- `/kanban` - Quadro Kanban (admin/broker/gestao_rv)
- `/admin` - Gerenciamento de usuários (admin)
- `/integrations` - Gerenciamento de integrações (admin)
- `/agent-brain` - Painel de Controle do Cérebro do Agente (admin/gestao_rv)
- `/assessores` - Base de Assessores (admin/broker/gestao_rv)
- `/campanhas` - Campanhas Ativas (admin/gestao_rv)

## Roles de Usuário
- `admin` - Acesso total ao sistema
- `gestao_rv` - Acesso a tudo exceto Usuários e Integrações
- `broker` - Acesso aos chamados próprios e dashboard
- `client` - Apenas via WhatsApp

## Execução

A aplicação roda em `http://0.0.0.0:5000`.

Para indexar documentos do Notion:
```bash
python indexer.py
```

## Gerenciamento de Integrações

A página `/integrations` (apenas admin) permite:
- Visualizar status das integrações configuradas (OpenAI, Notion, WAHA)
- Configurar chaves de API diretamente na interface
- Testar conexões com serviços externos
- Ativar/desativar integrações

**Nota:** Os secrets configurados pela interface são salvos em memória para a sessão atual. Para persistência permanente, configure também em Tools > Secrets no Replit.

## Dashboard de Analytics

A página `/analytics` (admin, gestao_rv e broker) exibe indicadores de controle:

### KPIs Disponíveis
- **Total de Atendimentos** - Quantidade de interações registradas
- **Chamados Abertos** - Tickets com status "Aberto" ou "Em Andamento"
- **Chamados Concluídos** - Tickets com status "Concluído"
- **Mensagens Enviadas** - Total de mensagens disparadas via campanhas
- **Assessores Impactados** - Assessores únicos que receberam mensagens de campanhas

### Recursos
- Filtro por período (7, 30, 90 dias ou personalizado)
- Gráfico de dúvidas por categoria
- Tabela de tempo médio de resolução por Broker (perfil de usuário)

### Categorias de Tickets
Categorias padrão criadas automaticamente:
- Investimentos, Conta, Transferências, Produtos, Suporte Técnico, Outros

## Painel de Controle do Cérebro do Agente

A página `/agent-brain` (admin e gestao_rv) permite configurar em tempo real:

### Campos Disponíveis
- **Personalidade e Regras** - Define como o agente deve se comportar, seu tom e princípios
- **Restrições e Proibições** - O que o agente NÃO pode fazer em hipótese alguma
- **Modelo de IA** - Escolha entre GPT-4o, GPT-4 Turbo, GPT-4 ou GPT-3.5 Turbo
- **Temperatura** - Controle de criatividade (0 = objetivo, 2 = criativo)
- **Tamanho Máximo da Resposta** - Limite de tokens por resposta

### Funcionamento
- Configurações são aplicadas imediatamente a todas as novas conversas
- Não requer reinicialização do sistema
- Armazenado no banco de dados (tabela `agent_config`)

## Mudanças Recentes
- 2026-01-20: Aplicação criada com todas as funcionalidades
- 2026-01-20: Corrigido serialização UserResponse (from_attributes)
- 2026-01-20: Admin bootstrap via variáveis de ambiente
- 2026-01-20: Adicionado painel de gerenciamento de integrações
- 2026-01-20: Adicionado dashboard de analytics com KPIs e filtro de data
- 2026-01-20: Adicionado Painel de Controle do Cérebro do Agente com configuração em tempo real
- 2026-01-20: Menu de navegação unificado em todas as páginas
- 2026-01-20: Renomeado app para "Agente IA - RV" e adicionado logo SVN
- 2026-01-20: Adicionado módulo Base de Assessores com CRUD, campos customizados e importação de planilhas
- 2026-01-20: **Reformulação completa da UI** - Novo design system com:
  - Menu lateral vertical minimizável (260px/70px) com ícones SVG e persistência via localStorage
  - Tema claro em toda aplicação (fundo #f8fafc, cards brancos)
  - Fonte padronizada Inter (Google Fonts)
  - Arquivo CSS global compartilhado (`frontend/static/global.css`)
  - Português corrigido em todas as interfaces (acentuação, gramática)
  - Modais padronizados com estrutura consistente
- 2026-01-21: **Sistema de Permissões Atualizado**:
  - Novo role `gestao_rv` com acesso a tudo exceto Usuários e Integrações
  - Broker agora vê apenas seus próprios chamados (atribuídos a ele)
  - Menu lateral dinâmico que oculta itens conforme o role do usuário
- 2026-01-21: **Configuração de Secrets na Interface**:
  - Página de integrações permite configurar chaves de API diretamente
  - Endpoint `POST /api/integrations/save-secrets` para salvar configurações
- 2026-01-21: **Sistema de Campanhas Ativas**:
  - Wizard de 4 passos para criação de campanhas de disparo em massa
  - Templates de mensagem reutilizáveis com variáveis dinâmicas
  - Agrupamento inteligente por assessor e cliente
  - Histórico de campanhas com estatísticas de sucesso/falha

## Design System

### Arquivo Global CSS
O arquivo `frontend/static/global.css` contém:
- CSS Custom Properties (variáveis) para cores, espaçamentos e fontes
- Estilos base para body, tipografia e formulários
- Componentes reutilizáveis: `.card`, `.btn`, `.form-input`, `.table`, `.badge`, `.alert`
- Sistema de grid responsivo: `.grid`, `.grid-2`, `.grid-3`, `.grid-4`
- Menu lateral: `.sidebar`, `.nav-item`, `.sidebar-toggle`
- Modais: `.modal-overlay`, `.modal`, `.modal-header`, `.modal-body`, `.modal-footer`

### Variáveis CSS Principais
```css
--primary-color: #4f46e5 (indigo)
--bg-color: #f8fafc (fundo claro)
--card-bg: #ffffff (cards brancos)
--sidebar-width: 260px (menu expandido)
--sidebar-collapsed: 70px (menu minimizado)
--font-family: 'Inter', sans-serif
```

### Menu Lateral
- Estado persistente via localStorage (`sidebarCollapsed`)
- Toggle com animação suave de 0.3s
- Ícones SVG inline em cada item de navegação
- Função `toggleSidebar()` presente em todos os templates

## Base de Assessores

A página `/assessores` (admin e broker) permite gerenciar a base de assessores para disparo de mensagens e identificação.

### Campos Padrão
- **Nome do Assessor** - Nome completo (obrigatório)
- **Telefone WhatsApp** - Número para identificação e contato
- **Unidade** - Unidade de trabalho do assessor
- **Equipe** - Equipe à qual pertence
- **Broker Responsável** - Broker que supervisiona o assessor

### Funcionalidades
1. **CRUD Completo** - Criar, visualizar, editar e excluir assessores
2. **Filtros Dinâmicos** - Filtrar por unidade, equipe, broker ou busca por nome/telefone
3. **Campos Customizados** - Criar campos adicionais dinamicamente (ex: código do parceiro)
4. **Importação de Planilhas** - Upload de Excel/CSV com mapeamento de campos

### Importação de Planilhas
1. Faça upload de arquivo Excel (.xlsx, .xls) ou CSV
2. O sistema mostra as colunas encontradas e tenta mapear automaticamente
3. Ajuste o mapeamento conforme necessário
4. Opção de atualizar registros existentes pelo telefone
5. Confirme a importação

### Tabelas do Banco de Dados
- `assessores` - Registros dos assessores com campos customizados em JSON
- `custom_field_definitions` - Definições de campos customizados

## Sistema de Campanhas Ativas

A página `/campanhas` (admin e gestao_rv) permite criar e gerenciar campanhas de disparo em massa via WhatsApp.

### Funcionalidades
1. **Wizard de 4 passos** - Processo guiado para criação de campanhas
2. **Upload de Planilhas** - Aceita Excel (.xlsx, .xls) ou CSV
3. **Mapeamento Flexível** - Mapeia colunas da planilha para campos do sistema
4. **Templates Reutilizáveis** - Cria e gerencia templates de mensagem com variáveis
5. **Agrupamento Inteligente** - Agrupa recomendações por assessor e depois por cliente
6. **Preview Antes do Disparo** - Visualiza mensagens formatadas antes de enviar
7. **Disparo Sequencial com Progresso** - Envio de mensagens uma a uma com delay de 2.5s e barra de progresso em tempo real via SSE
8. **Histórico de Campanhas** - Consulta campanhas anteriores com status e estatísticas

### Etapas do Wizard
1. **Upload** - Carrega planilha com dados de clientes e recomendações
2. **Mapeamento** - Define quais colunas correspondem a cada campo
3. **Template** - Seleciona ou cria template de mensagem com variáveis
4. **Preview e Disparo** - Visualiza mensagens agrupadas e confirma envio

### Variáveis de Template
- `{{nome_assessor}}` - Nome do assessor
- `{{lista_clientes}}` - Lista formatada de clientes com recomendações
- `{{data_atual}}` - Data do disparo
- Variáveis customizadas conforme mapeamento

### Tabelas do Banco de Dados
- `message_templates` - Templates de mensagem com nome e conteúdo
- `campaigns` - Campanhas com status, contadores e metadados
- `campaign_dispatches` - Registro de cada mensagem enviada

### Endpoints API
- `GET /api/templates` - Listar templates
- `POST /api/templates` - Criar template
- `PUT /api/templates/{id}` - Atualizar template
- `DELETE /api/templates/{id}` - Excluir template
- `POST /api/campaigns/upload` - Upload de planilha
- `POST /api/campaigns/preview` - Preview com mapeamento
- `POST /api/campaigns/dispatch` - Disparar campanha (método antigo, instantâneo)
- `GET /api/campaigns/{id}/dispatch-stream` - Disparar campanha com SSE para progresso em tempo real
- `GET /api/campaigns/history` - Histórico de campanhas

### Disparo com Progresso em Tempo Real
O endpoint `/api/campaigns/{id}/dispatch-stream` usa Server-Sent Events (SSE) para:
- Enviar mensagens uma a uma com delay de 5 segundos entre cada envio
- Retry automático com até 3 tentativas para erros HTTP 5xx, TIMEOUT e CONNECTION_ERROR
- Delay de 3 segundos entre retries
- Transmitir progresso em tempo real para o frontend (incluindo status de retry)
- Evitar sobrecarga do servidor WAHA
- Exibir barra de progresso, contadores e log de envio com indicação de tentativas
