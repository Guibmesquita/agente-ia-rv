# GUIDELINES — Guia Técnico Completo do Projeto Stevan

> **Quando consultar este documento:** Antes de mudanças em deploy, segurança, banco de dados, RAG, WhatsApp, upload, visual ou integrações externas, consulte a seção relevante. Para tarefas simples (ajuste de texto, CSS pontual), não é necessário.

---

## 1. Propósito e Visão

O **Stevan** é um agente de IA para a equipe de Renda Variável da SVN. Seu propósito é **empoderar assessores financeiros**, centralizando informações, automatizando tarefas rotineiras e melhorando a interação com clientes via WhatsApp.

**Princípio orientador:** Antes de implementar qualquer feature, pergunte: *"Isso ajuda o assessor a ser mais eficiente, tomar decisões melhores ou atender melhor o cliente?"* Se a resposta for não, questione se a feature é realmente necessária.

**Público-alvo:**
- **Assessores financeiros** — usam o Stevan via WhatsApp para consultar produtos, estratégias e materiais
- **Gestão RV** — usam o painel admin para acompanhar métricas, campanhas e insights
- **Administradores** — configuram integrações, usuários e comportamento do agente

**O Stevan NÃO é:**
- Um substituto do assessor — é um suporte interno (broker de informação)
- Um sistema de trading — não executa ordens
- Um chatbot genérico — é especializado em produtos de renda variável

---

## 2. Tech Stack

### Backend
| Tecnologia | Versão | Uso |
|---|---|---|
| Python | 3.11 | Linguagem principal |
| FastAPI | 0.109.0 | Framework web / API |
| Uvicorn | 0.27.0 | Servidor ASGI |
| SQLAlchemy | 2.0.25 | ORM |
| PostgreSQL | 16 | Banco de dados principal |
| pgvector | - | Extensão para busca vetorial |
| OpenAI SDK | 1.12.0 | GPT-4o-mini (agent), GPT-4 Vision (PDFs), text-embedding-3-large (RAG) |
| MSAL | - | SSO Microsoft (Azure AD) |
| python-jose | - | JWT |
| slowapi | - | Rate limiting |
| PyMuPDF (fitz) | - | Processamento de PDF |
| python-magic | - | Detecção de MIME type real |
| tiktoken | - | Contagem de tokens |
| httpx | - | HTTP client assíncrono |

### Frontend
| Tecnologia | Uso |
|---|---|
| Jinja2 | Templates HTML (pages legado/admin) |
| React 18 | 4 micro-apps SPA |
| Vite | Build tool para React apps |
| Tailwind CSS | Estilização (CDN em Jinja2, PostCSS em React) |
| Radix UI | Componentes acessíveis (Dialog, Tabs, Select, Tooltip) |
| Framer Motion | Animações e transições |
| Lucide React | Ícones |
| Chart.js / amCharts 5 | Gráficos |
| react-dropzone | Upload de arquivos |

### Serviços Externos
| Serviço | Uso |
|---|---|
| Z-API | Integração WhatsApp (envio/recebimento) |
| OpenAI | IA (chat, embeddings, vision) |
| Tavily AI | Busca web para dados de mercado em tempo real |
| Microsoft Azure AD | SSO com MFA |
| FundsExplorer.com.br | Dados públicos de FIIs |

### Infraestrutura
| Item | Configuração |
|---|---|
| Hosting | Replit Reserved VM (always running) |
| Porta | 5000 (local) → 80 (externo) |
| Banco dev | PostgreSQL (Replit) |
| Banco prod | PostgreSQL separado (Replit) |

---

## 3. Arquitetura e Estrutura

### Organização de Pastas
```
/
├── main.py                    # Entrypoint, lifespan, rotas top-level
├── core/
│   ├── config.py              # Configurações e env vars
│   ├── security.py            # JWT, hashing, token blacklist
│   ├── security_middleware.py  # Middlewares (auth, headers, CORS, rate limit)
│   └── upload_validator.py    # Validação de uploads
├── api/endpoints/             # 16 módulos de rotas (lazy loaded)
├── database/
│   ├── models.py              # Modelos SQLAlchemy
│   └── connection.py          # Engine e session
├── services/                  # Lógica de negócio
│   ├── openai_agent.py        # Agente IA principal
│   ├── vector_store.py        # RAG / busca semântica
│   ├── whatsapp_client.py     # Cliente Z-API
│   ├── web_search.py          # Busca Tavily
│   ├── document_processor.py  # Processamento de PDFs
│   └── upload_queue.py        # Fila persistente de uploads
├── frontend/
│   ├── templates/             # Templates Jinja2
│   ├── static/                # CSS, JS, imagens
│   ├── react-knowledge/       # App React: Base de Conhecimento
│   ├── react-conversations/   # App React: Central de Mensagens
│   ├── react-insights/        # App React: Dashboard de Insights
│   └── react-costs/           # App React: Central de Custos
├── scripts/                   # Scripts de manutenção e seed
├── data/                      # Dados de seed e glossário
├── tests/                     # Testes de conversação e RAG
└── docs/                      # Documentação histórica
```

### Fluxo de Request
```
Cliente → Replit Proxy (metasidecar) → Uvicorn (:5000)
  → SecurityHeadersMiddleware (headers CSP, HSTS, etc.)
  → GlobalAuthMiddleware (verifica JWT, PUBLIC_PATHS)
  → log_all_requests middleware (stderr, [ACCESS])
  → Rota/Endpoint
  → Response
```

### Lazy Router Loading
Os 16 módulos de endpoint são importados em background thread após o uvicorn subir. Rotas top-level (`/`, `/health`, `/favicon.ico`, static files) ficam disponíveis imediatamente. Rotas de API (`/api/*`) ficam disponíveis ~10-25s após o startup.

### Lifespan Pattern
O `lifespan` do FastAPI gerencia background tasks:
- `run_init_background()` — importa routers, init DB, seed, upload queue
- `check_and_reindex_embeddings()` — re-indexa embeddings pendentes
- `confirmation_timeout_scheduler()` — timeout de confirmações bot
- `revoked_tokens_cleanup_scheduler()` — limpa tokens revogados

---

## 4. Identidade Visual

### Paleta de Cores (CSS Variables)
```css
--primary-color: #772B21    /* Marrom avermelhado — cor principal da marca */
--primary-hover: #381811    /* Hover do botão primário */
--primary-light: #CFE3DA    /* Verde menta claro — backgrounds de destaque */
--bg-color: #FFF8F3         /* Off-white quente — fundo geral */
--card-bg: #ffffff          /* Branco puro — cards */
--border-color: #e5dcd7     /* Cinza quente claro — bordas */
--text-primary: #221B19     /* Quase preto quente — texto principal */
--text-secondary: #5a4f4c   /* Marrom acinzentado — texto secundário */
--success-color: #10b981    /* Verde esmeralda */
--danger-color: #AC3631     /* Vermelho */
--warning-color: #f59e0b    /* Âmbar */
```

### Cores SVN (sub-marca Tailwind)
```
svn-brown: #8b4513
svn-orange: #dc7f37
svn-green: #6b8e23
```

### Tipografia
- **Fonte principal:** Inter (Google Fonts)
- **Fallbacks:** -apple-system, BlinkMacSystemFont, sans-serif
- **Não usar** outras fontes sem decisão explícita

### Spacing e Dimensões
| Elemento | Valor |
|---|---|
| Sidebar expandida | 260px |
| Sidebar colapsada | 64px |
| Topbar | 60px |
| Padding de página | 32px (desktop), 20px (mobile) |
| Border-radius cards | 16px |
| Border-radius botões/inputs | 10px |
| Breakpoint mobile | 768px |
| Transição sidebar | 300ms |

### Sidebar SVN
- Fixa à esquerda, altura 100vh
- Colapsável com estado persistido em `localStorage`
- Logo troca entre versão completa e ícone
- Grupos de navegação com labels uppercase
- Acordeões para "Configurações" e "Conhecimento"
- Item ativo: `bg-primary/10` + `text-primary`
- Hover: `bg-gray-50`

### Componentes
- **Cards:** fundo branco, border-radius 16px, borda sutil, hover com shadow `0 4px 12px rgba(0,0,0,0.05)`
- **Botão primário:** fundo `#772B21`, texto branco
- **Botão secundário:** fundo `#FFF8F3`, com borda
- **Badges:** pills com texto colorido sobre fundo muito claro da mesma cor

### Tema
- **Sempre tema claro** — não implementar dark mode sem decisão explícita
- **Design clean e minimalista** — evitar ornamentos desnecessários

---

## 5. Sistema de Notificações

### Regra principal
**Toda ação do usuário que modifica dados ou pode falhar deve gerar um feedback visual via toast.** Nunca usar `alert()`, `console.log()` como feedback, ou falhar silenciosamente.

### Implementação em Jinja2 (templates HTML)
Usar o sistema customizado em `frontend/static/notifications.js` — disponível globalmente via `window.toast`:

```javascript
toast.success("Registro salvo com sucesso")
toast.error("Erro ao salvar registro")
toast.warning("Atenção: esta ação é irreversível")
toast.info("Processando...")
toast.confirm({
    title: "Confirmar exclusão",
    message: "Deseja excluir este item?",
    onConfirm: () => { /* ação */ },
    onCancel: () => { /* cancelar */ }
})
```

### Implementação em React
Usar o `ToastProvider` e hook `useToast()` de `frontend/react-knowledge/src/components/Toast.jsx`:

```jsx
const { showToast } = useToast();
showToast("success", "Salvo com sucesso");
showToast("error", "Erro ao processar");
```

### Estilo visual dos toasts
- **Posição:** top-center fixo (`top: 20px`, centralizado)
- **Background:** branco
- **Indicador:** borda esquerda de 4px colorida por tipo
- **Cores:** success = `#10b981`, error = `#ef4444`, warning = `#f59e0b`, info = `#772B21`
- **Animação:** slide-in de cima + fade out
- **Border-radius:** 12px
- **Shadow:** `0 10px 40px`

### O que NÃO fazer
- NÃO usar bibliotecas externas de toast (react-toastify, sonner, etc.)
- NÃO usar `alert()` nativo do browser
- NÃO usar `console.log()` como feedback ao usuário
- NÃO criar novos sistemas de notificação — usar os existentes
- NÃO esquecer de notificar em caso de erro em chamadas de API

---

## 6. Segurança

> **Regra de Ouro:** Toda entrada do usuário é suspeita até prova em contrário. Todo acesso é negado até ser explicitamente autorizado.

### 6.1 Autenticação

**SSO Microsoft é o ÚNICO método de login.** O login interno (usuário/senha) foi permanentemente desabilitado. As rotas `/api/auth/login` e `/api/auth/login-form` retornam 410 (Gone). Nunca reintroduzir login por senha.

**Fluxo:** Azure AD (MFA) → callback → aplicação emite JWT próprio → cookie httponly

**GlobalAuthMiddleware** (`core/security_middleware.py`) intercepta TODA requisição:
- `PUBLIC_PATHS`: rotas exatas sem auth (`/`, `/login`, `/health`, `/favicon.ico`)
- `PUBLIC_PREFIXES`: prefixos sem auth (`/static/`, `/api/auth/`, `/api/whatsapp/`)
- Tudo que não está listado é bloqueado automaticamente

### 6.2 JWT

| Propriedade | Valor |
|---|---|
| Access token expiration | 60 minutos (não aumentar) |
| Refresh token expiration | 7 dias |
| Algoritmo | HS256 |
| Issuer (`iss`) | `stevan-api` (validado na decodificação) |
| Audience (`aud`) | `stevan-frontend` (validado na decodificação) |
| Type claim (`type`) | `access` ou `refresh` (validado para impedir uso cruzado) |
| JTI | UUID v4 único por token (para blacklist) |
| Cookie access_token | httponly, secure (prod), samesite=lax, path=`/` |
| Cookie refresh_token | httponly, secure (prod), samesite=lax, path=`/api/auth` |

**SECRET_KEY nunca pode ter valor padrão.** A aplicação falha explicitamente na inicialização se não definida ou se contiver o valor padrão de dev. Nunca adicionar fallback como `os.environ.get("SECRET_KEY", "qualquer_valor")`. Gerar com:
```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

**Token Blacklist (Revogação):** Quando o usuário faz logout, o `jti` do access token e do refresh token são inseridos na tabela `revoked_tokens`. Qualquer tentativa de usar um token revogado é rejeitada com HTTP 401, mesmo que ainda não tenha expirado. A verificação é feita em `decode_token()`, protegendo tanto o middleware quanto os endpoints. Um scheduler (`revoked_tokens_cleanup_scheduler`) remove tokens expirados da blacklist a cada hora.

Implementação em `core/security.py`: `create_access_token`, `create_refresh_token`, `decode_token`, `decode_refresh_token`, `revoke_token`, `is_token_revoked`, `cleanup_revoked_tokens`. Model `RevokedToken` em `database/models.py`.

### 6.3 Regras para Código Novo

Use esta lista mental toda vez que criar um novo endpoint:

**1. Defina o acesso:** pública ou protegida? Quais roles? Verifica ownership de IDs?

**2. Valide todos os inputs:** Use modelos Pydantic. Nunca concatene strings em queries — sempre ORM ou parâmetros nomeados.

**3. Aplique rate limiting** se o endpoint for sensível a abuso (custo de API, enumeração, força bruta).

**4. Defina comportamento em erro:** Mensagens genéricas ao cliente, detalhes ao log. Nunca `except: pass` silencioso.

**5. Registre eventos de segurança** se envolver auth, dados sensíveis ou ações admin.

**Toda rota protegida usa `get_current_user` ou `require_role`:**
```python
# ✅ CORRETO
@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: int, current_user: User = Depends(get_current_user)):
    document = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id  # IDOR protection obrigatória
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

# ❌ ERRADO — busca pelo ID sem verificar o dono
document = db.query(Document).filter(Document.id == doc_id).first()
```

**Rotas admin verificam role:**
```python
async def admin_action(current_user: User = Depends(require_role("admin"))):
```

**Rate limiting:** SSO = 10 req/min por IP (`LOGIN_MAX_ATTEMPTS`). Account lockout após 10 falhas por 15 minutos (`LOGIN_LOCKOUT_SECONDS`). Constantes em `core/security_middleware.py`.

### 6.4 Integrações Externas

**SSRF:** Nenhuma URL com input do usuário sem validação contra allowlist de domínios:
```python
# ✅ CORRETO
ALLOWED_EXTERNAL_DOMAINS = {"api.openai.com", "fundsexplorer.com.br", "api.tavily.com"}

def fetch_external(url: str):
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    if domain not in ALLOWED_EXTERNAL_DOMAINS:
        raise ValueError(f"Domínio não autorizado: {domain}")
    return requests.get(url)
```

**Cota:** Rate limit por usuário — OpenAI: 20/hora, Tavily: 30/hora. Toda nova integração define limite antes de produção. Custos monitorados na Central de Custos (`/custos`).

### 6.5 Uploads

Usar `core/upload_validator.py`:
```python
content, file_hash = await validate_upload(file)
```
- Validação MIME real com `python-magic` (não confiar em Content-Type)
- Limite de tamanho: 50MB
- Hash SHA-256 automático
- Duplicatas com mesmo `file_hash` são bloqueadas

### 6.6 Logging de Segurança

Usar logger `"security"` via `record_security_event()` (em `core/security_middleware.py`). Nunca usar `print()` ou `logging.info()` diretamente para eventos de segurança.

**Eventos obrigatórios:** login sucesso/falha, logout, acesso negado (403), token inválido/expirado, ações admin, uploads, modificação de permissões/roles.

```python
# ✅ CORRETO
from core.security_middleware import record_security_event
record_security_event("login_failed", ip=request.client.host,
                      username_attempted=email, reason="invalid_password")

# ❌ ERRADO — expõe dados sensíveis
logging.info(f"Login failed for {email} with password {password} from {ip}")
```

**Nunca logar:** senhas (nem em hash), tokens JWT completos, cookies de sessão, valores de API keys, stack traces completos, dados pessoais sem mascaramento.

### 6.7 Tratamento de Erros

**Fail closed em autenticação:** qualquer exceção em validação de token/permissão = acesso negado, NUNCA acesso liberado.

```python
# ✅ CORRETO — fail closed
try:
    user = validate_token(token)
except Exception as e:
    record_security_event("token_validation_error", detail=str(e))
    raise HTTPException(status_code=401, detail="Não autorizado")

# ❌ ERRADO — fail open (pior cenário)
try:
    user = validate_token(token)
except Exception:
    user = get_default_user()  # bypassa segurança
```

**Mensagens genéricas ao cliente, detalhes ao log:**
```python
# ✅ CORRETO
except DatabaseError as e:
    logger.error(f"Database error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Erro interno. Tente novamente.")

# ❌ ERRADO — expõe estrutura do banco
except DatabaseError as e:
    raise HTTPException(status_code=500, detail=str(e))
```

O handler global de erros (`core/security_middleware.py`) garante que nenhum stack trace chegue ao cliente em produção.

### 6.8 Security Headers

Aplicados automaticamente via `SecurityHeadersMiddleware` (`core/security_middleware.py`):
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy` com política restritiva (self + CDNs necessários)
- `Strict-Transport-Security` — adicionado pelo proxy Replit em produção (NÃO duplicar no middleware)

Não remover ou enfraquecer esses headers. Para adicionar exceção no CSP (novo CDN), adicionar apenas o domínio específico.

**CSP Nonces (implementado):**
- `SecurityHeadersMiddleware` gera nonce criptográfico único (`secrets.token_urlsafe(16)`) por requisição
- Armazenado em `request.state.csp_nonce`
- Todo `<script>` (inline ou com src) DEVE ter `nonce="{{ request.state.csp_nonce }}"`
- Nunca usar inline event handlers (`onclick`, `onchange`) — usar `addEventListener()` ou event delegation com `data-action`

**`unsafe-eval` em script-src:** Necessário enquanto Tailwind CSS CDN for usado (compila classes no runtime com `eval()`). Mitigação futura: migrar para Tailwind CLI build-time.

**`unsafe-inline` em style-src:** Necessário para Tailwind CDN (injeta estilos inline). Risco baixo (estilos não executam código). Mesma mitigação futura.

**HSTS:** Adicionado pelo proxy Replit (`max-age=63072000; includeSubDomains`). Se mudar de plataforma, reativar no middleware.

### 6.9 Variáveis de Ambiente Obrigatórias

`SESSION_SECRET`, `DATABASE_URL`, `OPENAI_API_KEY`, `ZAPI_CLIENT_TOKEN`, `TAVILY_API_KEY`, `WAHA_API_KEY`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID`, `ALLOWED_ORIGINS`.

Swagger/OpenAPI desabilitado em produção.

### 6.10 Checklist de Segurança para Nova Feature

- [ ] Rota tem verificação de autenticação?
- [ ] Se recebe IDs, verifica ownership (IDOR)?
- [ ] Se admin-only, verifica role?
- [ ] Inputs validados com Pydantic?
- [ ] Nenhuma query com concatenação de strings?
- [ ] Chamadas externas com allowlist e rate limit?
- [ ] Uploads validam MIME, tamanho e geram hash?
- [ ] Erros retornam mensagem genérica ao cliente?
- [ ] Eventos de segurança logados?
- [ ] Nenhum segredo hardcoded?

### 6.11 Arquivos de Implementação

| Arquivo | Responsabilidade |
|---|---|
| `core/security_middleware.py` | Middlewares, rate limiting, CORS, headers, `record_security_event()` |
| `core/security.py` | JWT, hashing, token blacklist, SECRET_KEY validation |
| `core/upload_validator.py` | Validação de uploads (MIME, size, hash) |
| `api/endpoints/auth.py` | SSO, logout, token rotation |
| `database/models.py` | `RevokedToken` model |

---

## 7. Regras de Deployment

### Regras obrigatórias
1. **Deployment target: `vm` (Reserved VM)** — NUNCA usar autoscale/cloudrun (mata workers de upload)
2. **NUNCA usar `SO_REUSEPORT`** — interfere com o proxy interno do Replit (metasidecar) e impede que o health check alcance a aplicação. Confirmado após 6 tentativas de deploy falhadas.
3. **NUNCA criar sockets pré-bound** na porta de serviço — deixar o uvicorn fazer o bind
4. **Uvicorn bind padrão:** `uvicorn.run(app, host="0.0.0.0", port=5000)` — sem socket customizado
5. **Logs em stderr** — deployment logs do Replit capturam apenas stderr. Usar `sys.stderr.write()` para logs críticos
6. **Rota `/health` top-level** — registrada fora do lazy loading, responde instantaneamente

### Configuração do .replit
```toml
[[ports]]
localPort = 5000
externalPort = 80

[deployment]
deploymentTarget = "vm"
run = ["python", "main.py"]
healthcheckPath = "/health"
```
- **NÃO adicionar** entradas `[[ports]]` extras (conflita com VM deployment)

**⚠️ REGRA CRÍTICA: `.replit` é ARQUIVO PROTEGIDO pelo Replit**
- O agente IA **NÃO consegue editar** o arquivo `.replit` (nem `.replit`, nem `replit.nix`) — bloqueado pela plataforma
- A função `deployConfig()` atualiza a configuração de deploy via API interna, mas **NÃO garante** que o texto do `.replit` reflita a mudança
- **SEMPRE que uma tarefa exigir alteração no `.replit`** (deploymentTarget, ports, workflows, nix packages), o agente DEVE:
  1. Informar o usuário explicitamente quais linhas precisam ser alteradas
  2. Fornecer o texto exato a ser editado (antes/depois)
  3. Aguardar confirmação do usuário antes de prosseguir
- **Exemplos de mudanças que exigem edição manual do `.replit`:** deploymentTarget, healthcheckPath, ports, modules, nix packages
- **Lição aprendida:** `deployConfig()` reportou sucesso ao trocar `cloudrun` → `vm`, mas o arquivo continuou com `cloudrun`. Isso causou deploys incorretos em produção

### Health Check no Deploy VM (CRÍTICO)
- **Deploy VM faz health check na homepage `/`** — ignora `healthcheckPath` do `.replit`
- **Timeout de 5 segundos** — se `/` não responder em 5s, deploy falha
- **Solução implementada:** rota `/` detecta header `Accept`:
  - Sem `text/html` (health checker) → retorna `JSONResponse({"status":"ok"})` imediatamente
  - Com `text/html` (browser) → renderiza `login.html` normalmente
- **Fonte:** https://docs.replit.com/cloud-services/deployments/reserved-vm-deployments
- **`healthcheckPath` só funciona para autoscale/cloudrun**, não para VM
- **REGRA:** a rota `/` NUNCA deve ser pesada ou dependente de inicialização lazy

### Cold Start
- Lazy router registration: routers importados em background thread (~10-25s)
- Rotas `/`, `/health`, static files: disponíveis imediatamente

### Resiliência de Upload
- `_resume_interrupted_uploads()` roda no startup
- Duplicate detection via `file_hash`
- Background processing em threads (por isso VM, não autoscale)

### Dev vs Prod
- **Bancos PostgreSQL separados** — agent SQL tool = banco de dev
- Dados de produção: alterar via interface do app ou endpoints admin
- Republish: apenas código atualizado, dados permanecem

---

## 8. Banco de Dados

### Regras críticas
1. **NUNCA alterar tipo de coluna ID** — quebra dados existentes e migrações
2. **Dev e prod são bancos separados** — INSERT/UPDATE/DELETE pelo agent NÃO refletem em produção
3. **Migrações incrementais** — usar `ADD COLUMN IF NOT EXISTS` no `_apply_incremental_migrations()` em `main.py`
4. **`init_database()`** roda automaticamente no startup — cria tabelas e aplica migrações

### Padrões
- ORM: SQLAlchemy 2.0 com modelos em `database/models.py`
- Session: `get_db()` dependency injection
- Nunca usar SQL raw com concatenação de strings — sempre ORM ou parâmetros nomeados

### Modelos principais
`User`, `Conversation`, `ConversationTicket`, `ConversationInsight`, `Message`, `Product`, `Material`, `ContentBlock`, `RetrievalLog`, `IngestionLog`, `AgentConfig`, `Integration`, `Assessor`, `Campaign`, `RevokedToken`, `SecurityEvent`

---

## 9. RAG e Busca Semântica (V3.1 Enhanced)

### Configuração
| Parâmetro | Valor |
|---|---|
| Modelo de embeddings | `text-embedding-3-large` |
| Dimensões | 3072 |
| Storage | pgvector (PostgreSQL) |
| Ranking | Híbrido: 70% vetor + 20% recência + 10% exact match |

### Regras
1. **Trocar modelo de embeddings = re-indexação TOTAL obrigatória** — dimensões são incompatíveis entre modelos. Usar `reset_collection_for_migration()`
2. **Narrative chunks** — NUNCA indexar tabelas raw. Transformar cada linha em frase autocontida incluindo headers. Melhora accuracy 15-25%
3. **Glossário financeiro** — queries expandidas com sinônimos (CDB ↔ "Certificado de Depósito Bancário")
4. **Ticker detection** — detecção inteligente de tickers em queries (PETR4, VALE3, etc.)
5. **Queries temporais** ("último relatório") — peso de recência aumentado automaticamente

### Pipeline de Indexação
```
PDF → GPT-4 Vision (extração) → Semantic Modeling → Narrative Chunks → Embeddings → pgvector
```

### Semantic Transformer (3 camadas)
1. **Technical Extraction** — GPT-4 Vision extrai texto/tabelas do PDF
2. **Semantic Modeling** — estrutura dados em formato semântico
3. **Narrative Generation** — gera chunks narrativos para indexação

### XPI Derivatives (27 estruturas)
- Base de conhecimento especializada em produtos estruturados
- Fluxo de disambiguação conversacional em 4 etapas
- Diagramas de payoff em `static/derivatives_diagrams/`

---

## 10. WhatsApp (Z-API)

### Regras de Identificação
1. **Priorizar LID** (WhatsApp internal ID) sobre número de telefone — LID é estável, phone pode mudar
2. **Normalizar telefone** — remover caracteres especiais, garantir prefixo "55" (Brasil)
3. **Não responder imediatamente** a mensagens de saída do sistema — logar como `sent`

### Media Processing
| Tipo | Processamento |
|---|---|
| Áudio | Transcrição via Whisper (OpenAI) |
| Imagem | Análise via GPT-4 Vision |
| Documento/PDF | Análise via GPT-4 Vision |

### Conversation Flow
```
Webhook Z-API → Normalização → ConversationState Machine
  → SAUDACAO / DOCUMENTAL / ESCOPO / MERCADO / PITCH / FORA_ESCOPO → Bot responde
  → ATENDIMENTO_HUMANO → Escalation (ticket criado)
```

### Escalation Intelligence V2.1
- GPT analisa cada escalação com 11 categorias
- Auto-gera resumo do ticket e tópicos de conversa
- Tracking de timestamps importantes

### Bot Resolution V2.2
- `bot_resolved_at`, `awaiting_confirmation`
- Scheduler de background para mensagens de confirmação

### Ticket Architecture V2.3
- `Conversation` e `ConversationTicket` são modelos separados
- Sessão contínua de chat com tickets distintos por intervenção humana

---

## 11. Upload e Processamento de Documentos

### Adaptive DPI
Páginas pré-classificadas via PyMuPDF antes do GPT-4 Vision:
| Tipo de página | DPI |
|---|---|
| Texto | 150 |
| Tabela | 250 |
| Infográfico | 200 |
| Mixed | 200 |
| Image only | 250 |

### Metadata Extraction
`DocumentMetadataExtractor` usa GPT-4 Vision nas primeiras páginas para detectar automaticamente: nome do fundo, ticker, gestora, tipo de documento.

### Resumable Uploads
- `PersistentQueue` em `services/upload_queue.py`
- `_resume_interrupted_uploads()` no startup detecta `processing_status=processing/pending`
- Duplicate detection: uploads com `file_hash` idêntico a material `success` são bloqueados

### Pipeline Completo
```
Upload PDF → validate_upload() → Metadata Extraction (GPT-4V)
  → Match/Create Product → DPI Classification → Vision Extraction
  → Content Blocks → Review Queue → Aprovação → Embedding → pgvector
```

---

## 12. Frontend

### 4 React Apps
| App | Pasta | Rota | Descrição |
|---|---|---|---|
| Knowledge | `frontend/react-knowledge/` | `/base_conhecimento_react` | CMS de produtos, upload inteligente, review queue |
| Conversations | `frontend/react-conversations/` | `/conversas_react` | Central de mensagens estilo Zendesk, SSE real-time |
| Insights | `frontend/react-insights/` | `/insights` | Dashboard de insights com Chart.js/amCharts |
| Costs | `frontend/react-costs/` | `/custos_react` | Central de custos com gráficos |

### Comandos (dentro de cada pasta)
```bash
npm install        # Instalar dependências
npm run dev        # Dev server local
npm run build      # Build para produção
```

### Templates Jinja2 (páginas legado)
`login.html`, `assessores.html`, `campanhas.html`, `integrations.html`, `teste_agente.html`, `admin.html`, `users.html`

### Padrões de UI
- React apps montados em template container Jinja2
- Tailwind CSS em tudo (CDN em Jinja2, PostCSS em React)
- Ícones: Lucide (React e Jinja2)
- Componentes: Radix UI (Dialog, Tabs, Select, Tooltip)
- Animações: Framer Motion

---

## 13. Scripts e Comandos Úteis

| Script | Comando | Descrição |
|---|---|---|
| Seed produção | `python scripts/seed_production.py` | Popula banco de produção com dados do seed |
| Export dados dev | `python scripts/export_dev_data.py` | Exporta dados dev para seed JSON |
| Configurar webhooks | `python scripts/configure_zapi_webhooks.py` | Registra URL de deploy como webhook Z-API |
| Enriquecer chunks | `python scripts/enrich_chunks.py` | Adiciona metadata semântica a chunks existentes |
| Custos históricos | `python scripts/populate_historical_costs.py` | Gera dados históricos para dashboard de custos |
| Glossário B3 | `python scripts/extract_b3_glossary.py` | Extrai termos financeiros para expansão de query |
| Derivativos XPI | `python scripts/xpi_derivatives/process_pdfs_complete.py` | Pipeline completo de extração de derivativos |
| Re-ingest derivativos | `python scripts/xpi_derivatives/update_and_reingest.py` | Re-indexa base de derivativos |
| Testes de conversa | `python tests/conversation_tests/run_tests.py` | Testa fluxos de conversa do agente |
| Avaliação RAG | `python -m tests.rag_evaluation --evaluate [TICKER]` | Avalia accuracy do RAG para um produto |
| Comparar RAG | `python -m tests.rag_evaluation --compare [R1] [R2]` | Compara performance entre versões |

---

## 14. Workflows de Funcionalidades

### Conversa WhatsApp
```
1. Webhook Z-API recebe mensagem
2. Normalização (telefone, LID, media)
3. ConversationState machine classifica intent
4. Se ESCOPO/DOCUMENTAL → RAG busca semântica → GPT gera resposta → Z-API envia
5. Se MERCADO → Tavily busca web → GPT contextualiza → Z-API envia
6. Se ATENDIMENTO_HUMANO → Cria ticket → Notifica operador → Bot pausa
7. Se operador faz Takeover → Chat direto → Release → Bot retoma
```

### Upload de Documento
```
1. Usuário faz upload de PDF
2. validate_upload() — MIME, tamanho, hash
3. DocumentMetadataExtractor — GPT-4V analisa primeiras páginas
4. Match ou criação de produto
5. Classificação de DPI por tipo de página
6. GPT-4 Vision extrai conteúdo por página
7. Semantic Transformer gera content blocks
8. Blocks entram na Review Queue
9. Aprovação manual pelo gestor
10. Embedding e indexação no pgvector
```

### Campanha
```
1. Gestor define template com variáveis
2. Seleciona audiência (assessores/clientes)
3. Preview e confirmação
4. Bulk dispatch via Z-API com SSE para progress
5. Tracking de entrega e leitura
```

### Insights
```
1. Conversa encerrada/escalada
2. InsightAnalyzer (GPT) classifica: categoria, sentimento, tópicos
3. ConversationInsight salvo no banco
4. Dashboard agrega: KPIs, gráficos, rankings, filtros dinâmicos
```

---

## 15. Erros Conhecidos e Lições Aprendidas

### SO_REUSEPORT + Metasidecar do Replit
**Problema:** TCP Health Shim com `SO_REUSEPORT` impedia o proxy do Replit de rotear o health check para a porta 5000. 6 tentativas de deploy falharam.
**Causa:** `SO_REUSEPORT` permite múltiplos listeners na mesma porta. O kernel faz load-balancing, confundindo o metasidecar.
**Solução:** Remover todo uso de `SO_REUSEPORT` e sockets pré-criados. Usar uvicorn bind padrão.
**Regra:** NUNCA usar `SO_REUSEPORT` no Replit.

### Autoscale Matando Workers de Upload
**Problema:** Em Cloud Run (autoscale), o container escalava para zero após o HTTP response, matando o worker de processamento de PDF antes de completar.
**Solução:** Migrar para Reserved VM (always running).
**Regra:** Background processing requer VM, não autoscale.

### Logs stdout vs stderr em Produção
**Problema:** Shim TCP usava `print()` (stdout). Deployment logs do Replit capturam apenas stderr. Logs do shim ficaram invisíveis, impossibilitando diagnóstico.
**Solução:** Usar `sys.stderr.write()` para logs críticos em produção.
**Regra:** Logs de diagnóstico em produção = stderr.

### Senha Admin Hardcoded
**Problema:** Usuário admin com senha `admin123` em produção.
**Solução:** Senha gerada aleatoriamente (não recuperável), email placeholder neutralizado. Login apenas via SSO.
**Regra:** NUNCA criar credenciais padrão acessíveis.

### ChromaDB → pgvector
**Problema:** ChromaDB usado inicialmente para vetores, mas sem escalabilidade e persistência confiável.
**Solução:** Migração para pgvector (extensão PostgreSQL). Script legacy em `scripts/migrate_chroma_to_pgvector.py.legacy`.
**Regra:** Usar pgvector como storage de vetores. ChromaDB é legacy.

### Mudança de Modelo de Embeddings
**Problema:** Troca de `text-embedding-3-small` para `text-embedding-3-large` sem re-indexação.
**Solução:** Re-indexação total obrigatória via `reset_collection_for_migration()`.
**Regra:** Qualquer mudança no modelo de embeddings requer re-indexação completa.

---

## 16. Checklist Antes de Mudanças

### Antes de qualquer mudança
- [ ] Revisar quais funcionalidades existentes podem ser impactadas
- [ ] Consultar a seção relevante deste guia
- [ ] Testar em dev antes de deploy

### Antes de mudanças de deploy/startup
- [ ] Não usar `SO_REUSEPORT` ou sockets pré-criados
- [ ] Manter uvicorn bind padrão
- [ ] Rota `/health` continua top-level
- [ ] Logs críticos em stderr

### Antes de mudanças visuais
- [ ] Seguir paleta de cores (seção 4)
- [ ] Usar sistema de toast existente (seção 5)
- [ ] Manter tema claro, fonte Inter, spacing padrão

### Antes de novas rotas/endpoints
- [ ] Verificar checklist de segurança (seção 6.9)
- [ ] Adicionar a PUBLIC_PATHS se for rota pública

### Antes de mudanças no banco
- [ ] NUNCA alterar tipo de coluna ID
- [ ] Usar migrações incrementais (`ADD COLUMN IF NOT EXISTS`)
- [ ] Lembrar que mudanças de dados NÃO refletem em produção

### Antes de mudanças em RAG
- [ ] Se trocar modelo de embeddings, re-indexar tudo
- [ ] Usar narrative chunks (nunca tabelas raw)

---

*Última atualização: fevereiro de 2026. Atualizar este documento sempre que houver mudanças arquiteturais, novos aprendizados ou lições de erros.*
