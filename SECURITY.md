# SECURITY.md — Diretrizes de Segurança do Projeto Stevan

> **Para desenvolvedores e assistentes de IA:** Este documento deve ser lido antes de criar qualquer nova rota, endpoint, integração externa, funcionalidade de upload ou lógica de autenticação. Ele representa as decisões de segurança tomadas para este projeto e os padrões que todo novo código deve respeitar.
>
> **Stack:** Python · FastAPI · SQLAlchemy ORM · Jinja2 · bcrypt · JWT interno · SSO Microsoft (MSAL) · Integrações externas: OpenAI, Z-API, Tavily, FundsExplorer.

---

## Por que este documento existe

Esta aplicação passou por uma auditoria de segurança baseada no OWASP Top 10:2025 antes do seu lançamento. Durante essa auditoria, foram identificadas vulnerabilidades críticas — entre elas uma `SECRET_KEY` com valor padrão hardcoded, ausência de security headers, sem rate limiting no login e uma arquitetura de autenticação dual que permitia bypass do MFA. Todas foram corrigidas.

Este documento existe para garantir que o código novo não reintroduza esses problemas. Pense nele como um contrato técnico: qualquer feature criada a partir de agora precisa respeitar as regras aqui definidas.

---

## A Regra de Ouro

> **Toda entrada do usuário é suspeita até prova em contrário. Todo acesso é negado até ser explicitamente autorizado.**

Essas duas frases resumem 80% do pensamento de segurança que você precisa ter ao escrever código novo. O restante está detalhado nas seções abaixo.

---

## 1. Autenticação e Autorização

### Como funciona neste projeto

A autenticação funciona em duas camadas que precisam ser entendidas separadamente. A **camada de identidade** é gerenciada exclusivamente pelo SSO da Microsoft: ela responde à pergunta "quem é você?" usando o Azure AD com MFA. A **camada de sessão** é gerenciada pela aplicação: após a autenticação bem-sucedida via SSO, a aplicação emite um JWT próprio que é usado nas requisições subsequentes.

**O login interno (usuário/senha) foi permanentemente desabilitado.** As rotas `/api/auth/login` e `/api/auth/login-form` existem apenas como stubs que retornam erro 410 (Gone) e registram a tentativa no log de segurança. Não existe nenhum caminho de autenticação por credenciais locais — toda autenticação passa obrigatoriamente pelo Azure AD. Nunca reintroduza login por senha sem uma decisão arquitetural documentada e aprovada.

### Como funciona o middleware de autenticação global

O sistema usa um `GlobalAuthMiddleware` (em `core/security_middleware.py`) que intercepta todas as requisições. Rotas públicas são definidas em duas estruturas:

- **`PUBLIC_PATHS`**: Rotas exatas que não exigem autenticação (ex: `/`, `/login`, `/health`, `/favicon.ico`).
- **`PUBLIC_PREFIXES`**: Prefixos de rota que não exigem autenticação (ex: `/static/`, `/api/auth/`, `/api/whatsapp/`).

Para adicionar uma nova rota pública, inclua-a em uma dessas estruturas no `core/security_middleware.py`. Toda rota que não estiver listada será bloqueada automaticamente sem autenticação válida.

### Regras para código novo

**Toda rota protegida usa o dependency `get_current_user` ou `require_role`.** O middleware global garante que nenhuma rota `/api/` funcione sem token válido, mas o dependency no endpoint é necessário para acessar os dados do usuário autenticado.

```python
# ✅ CORRETO — proteção aplicada pelo middleware global + acesso ao usuário
@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: int, current_user: User = Depends(get_current_user)):
    ...

# ✅ CORRETO — rota pública registrada em PUBLIC_PATHS/PUBLIC_PREFIXES
# Adicionar em core/security_middleware.py:
# PUBLIC_PATHS.add("/api/health")

# ❌ ERRADO — rota /api/ sem get_current_user (middleware bloqueia, mas sem acesso ao user)
@app.get("/api/documents/{doc_id}")
async def get_document(doc_id: int):
    ...
```

**Toda rota que recebe um ID de recurso precisa verificar se o recurso pertence ao usuário autenticado** antes de retornar ou modificar dados. Isso previne IDOR (Insecure Direct Object Reference), onde um usuário acessa dados de outro apenas alterando um número na URL.

```python
# ✅ CORRETO — valida ownership antes de retornar
async def get_document(doc_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    document = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id  # <- esta linha é obrigatória
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return document

# ❌ ERRADO — busca pelo ID sem verificar o dono
async def get_document(doc_id: int, ...):
    document = db.query(Document).filter(Document.id == doc_id).first()
    return document  # qualquer usuário autenticado vê qualquer documento
```

**Rotas administrativas precisam verificar a role explicitamente**, além da autenticação básica:

```python
# ✅ CORRETO
async def admin_action(current_user: User = Depends(require_role("admin"))):
    ...
```

### Rate limiting e account lockout

Os endpoints SSO Microsoft (`/api/auth/microsoft/login` e `/api/auth/microsoft/callback`) têm rate limiting de **10 requisições por minuto** por IP (via slowapi). O login interno está permanentemente desabilitado (410 Gone). Após **10 tentativas falhas** de autenticação, a conta é bloqueada por **15 minutos**. Esses parâmetros estão definidos em `core/security_middleware.py` nas constantes `LOGIN_MAX_ATTEMPTS` e `LOGIN_LOCKOUT_SECONDS`.

---

## 2. Gerenciamento de Tokens JWT

Os tokens JWT emitidos por esta aplicação têm as seguintes propriedades obrigatórias. **Não altere esses valores sem entender as implicações de segurança:**

- **Expiração do access token:** 60 minutos. Não aumente esse valor.
- **Refresh token:** 7 dias. Emitido via cookie httponly no path `/api/auth`.
- **Issuer (`iss`):** `"stevan-api"`. Validado na decodificação.
- **Audience (`aud`):** `"stevan-frontend"`. Validado na decodificação.
- **Type claim (`type`):** `"access"` ou `"refresh"`. Validado para impedir uso cruzado.
- **JWT ID (`jti`):** UUID v4 único por token. Usado para blacklist de tokens revogados.
- **Algoritmo:** `HS256` com a `SECRET_KEY` definida via variável de ambiente.

O `SECRET_KEY` **nunca pode ter um valor padrão no código.** A aplicação falha explicitamente na inicialização se essa variável não estiver definida ou contiver o valor padrão de desenvolvimento. Nunca adicione um fallback como `os.environ.get("SECRET_KEY", "qualquer_valor_aqui")`.

### Token Blacklist (Revogação)

Quando o usuário faz logout, o `jti` do access token e do refresh token são inseridos na tabela `revoked_tokens` no banco de dados. A partir desse momento, qualquer tentativa de usar um token revogado é rejeitada com HTTP 401, mesmo que o token ainda não tenha expirado. A verificação de blacklist é feita dentro da função `decode_token()`, garantindo que tanto o `GlobalAuthMiddleware` quanto os endpoints que usam `get_current_user` estejam protegidos.

Um scheduler em background (`revoked_tokens_cleanup_scheduler`) remove tokens expirados da blacklist a cada hora, mantendo a tabela limpa sem risco de segurança (tokens expirados já são rejeitados naturalmente pelo JWT).

A implementação dos tokens está em `core/security.py` com as funções `create_access_token`, `create_refresh_token`, `decode_token`, `decode_refresh_token`, `revoke_token`, `is_token_revoked` e `cleanup_revoked_tokens`. O model `RevokedToken` está em `database/models.py`.

### Cookies de sessão

Ambos os cookies (`access_token` e `refresh_token`) são configurados com:
- `httponly=True` — impede acesso via JavaScript (proteção contra XSS)
- `secure=IS_PRODUCTION` — transmissão apenas via HTTPS em produção
- `samesite="lax"` — proteção contra CSRF
- Paths restritos: `access_token` em `/`, `refresh_token` em `/api/auth`

---

## 3. Criando uma Nova Rota ou Endpoint

Use esta lista mental toda vez que criar um novo endpoint:

**Primeiro, defina o acesso:** esta rota é pública ou protegida? Se protegida, quais roles podem acessá-la? Se ela recebe IDs de recursos, há verificação de ownership?

**Segundo, valide todos os inputs:** nenhum dado vindo do cliente deve ser usado diretamente sem validação. Use modelos Pydantic para validar o schema antes de qualquer lógica de negócio. Nunca construa queries com strings concatenadas — use sempre o ORM ou parâmetros nomeados.

**Terceiro, aplique rate limiting** se o endpoint for sensível a abuso. Critério prático: se chamar esse endpoint 500 vezes em um minuto causaria algum dano (custo de API, sobrecarga, enumeração de dados, força bruta), ele precisa de rate limiting.

**Quarto, defina o comportamento em caso de erro:** erros devem retornar mensagens genéricas ao cliente e detalhes ao log. Nunca deixe um `except` silencioso (`except: pass`) — todo erro deve ser registrado.

**Quinto, registre o evento no log de segurança** se a rota envolver autenticação, autorização, modificação de dados sensíveis ou ação administrativa.

---

## 4. Integrações Externas (OpenAI, Z-API, Tavily, FundsExplorer)

Toda chamada a um serviço externo representa um risco de dois tipos: **SSRF** (se a URL de destino puder ser influenciada pelo usuário) e **exaustão de cota** (se um usuário puder acionar chamadas sem limite).

**Regra obrigatória para SSRF:** nenhuma URL enviada a um serviço externo pode ser construída com input direto do usuário sem validação contra uma allowlist. Os domínios permitidos devem estar definidos em constante no arquivo de configuração.

```python
# ✅ CORRETO — valida contra allowlist antes de fazer a chamada
ALLOWED_EXTERNAL_DOMAINS = {"api.openai.com", "fundsexplorer.com.br", "api.tavily.com"}

def fetch_external(url: str):
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    if domain not in ALLOWED_EXTERNAL_DOMAINS:
        raise ValueError(f"Domínio não autorizado: {domain}")
    return requests.get(url)
```

**Regra obrigatória para cota:** toda chamada às APIs externas deve passar pelo rate limiter por usuário antes de ser executada. Os limites de referência são: OpenAI — 20 chamadas por hora por usuário; Tavily — 30 chamadas por hora por usuário. Qualquer nova integração adicionada ao projeto precisa definir um limite análogo antes de ir a produção. Os custos de API são monitorados na Central de Custos (`/custos`).

---

## 5. Uploads de Arquivo

Todo endpoint que receba um upload de arquivo deve usar o módulo `core/upload_validator.py`, que implementa as três validações obrigatórias nessa ordem:

**Validação de tipo MIME real no servidor** usando `python-magic` (não confie no Content-Type do request nem na extensão — ambos podem ser falsificados). O validador verifica se o MIME detectado corresponde à extensão declarada:

```python
from core.upload_validator import validate_upload

# Uso em endpoint:
content, file_hash = await validate_upload(file)  # valida MIME, tamanho e gera hash
```

**Validação de tamanho:** o limite atual para todos os uploads é **50MB** (`MAX_FILE_SIZE_MB` em `core/upload_validator.py`). Defina limites mais restritivos para tipos específicos se necessário.

**Hash de integridade:** o `validate_upload` gera automaticamente um hash SHA-256 de cada arquivo. Armazene-o junto com o registro do arquivo e registre o evento de upload no log de segurança:

```python
from core.security_middleware import record_security_event

record_security_event(
    "file_upload",
    user_id=current_user.id,
    username=current_user.username,
    filename=file.filename,
    file_hash=file_hash,
    size_bytes=len(content),
)
```

---

## 6. Logging de Segurança

Esta aplicação usa logging estruturado em JSON via o logger `"security"` configurado em `core/security_middleware.py`. Todo evento de segurança deve ser registrado usando a função `record_security_event()`. Nunca use `print()` ou `logging.info()` diretamente para eventos de segurança.

Os eventos que **obrigatoriamente** precisam ser logados são: login com sucesso, login com falha, logout, acesso negado (403), token inválido ou expirado, ação administrativa, upload de arquivo e qualquer operação que modifique permissões ou roles.

O que **nunca pode aparecer em logs**: senhas (nem em hash), tokens JWT completos, cookies de sessão, valores de API keys, stack traces completos, e dados pessoais sem mascaramento.

```python
from core.security_middleware import record_security_event

# ✅ CORRETO
record_security_event("login_failed", ip=request.client.host,
                      username_attempted=email, reason="invalid_password")

# ❌ ERRADO — expõe dados sensíveis
logging.info(f"Login failed for {email} with password {password} from {ip}")
```

---

## 7. Tratamento de Erros

O handler global de erros da aplicação (em `core/security_middleware.py`) garante que nenhum stack trace chegue ao cliente. Em produção, todas as exceções não tratadas retornam `"Erro interno do servidor"` sem detalhes. No entanto, há dois padrões que precisam ser seguidos no código de cada rota para complementar esse handler:

**Fail closed em autenticação:** qualquer exceção em código de validação de token ou permissão deve resultar em acesso negado, nunca em acesso liberado. Se você está em dúvida sobre o que fazer quando der erro em uma verificação de segurança, a resposta sempre é negar o acesso.

```python
# ✅ CORRETO — fail closed
try:
    user = validate_token(token)
except Exception as e:
    record_security_event("token_validation_error", detail=str(e))
    raise HTTPException(status_code=401, detail="Não autorizado")

# ❌ ERRADO — fail open (o pior cenário possível)
try:
    user = validate_token(token)
except Exception:
    user = get_default_user()  # "funciona" mas bypassa segurança
```

**Mensagens de erro para o cliente devem ser genéricas.** O detalhe técnico vai para o log, não para a resposta:

```python
# ✅ CORRETO
except DatabaseError as e:
    logger.error(f"Database error: {e}", exc_info=True)  # detalhe no log
    raise HTTPException(status_code=500, detail="Erro interno. Tente novamente.")

# ❌ ERRADO — expõe estrutura do banco
except DatabaseError as e:
    raise HTTPException(status_code=500, detail=str(e))  # pode revelar nomes de tabelas
```

---

## 8. Security Headers

A aplicação aplica automaticamente os seguintes headers em todas as respostas via `SecurityHeadersMiddleware` (em `core/security_middleware.py`):

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy` com política restritiva (self + CDNs necessários)
- `Strict-Transport-Security` — adicionado automaticamente pelo proxy Replit em produção (não duplicar no middleware)

Não remova ou enfraqueça esses headers sem documentar o motivo. Se uma nova feature precisar de uma exceção no CSP (ex: carregar script de um novo CDN), adicione apenas o domínio específico necessário.

### 8.1 CSP Nonces (Implementado)

#### `script-src` — Nonces em vez de `unsafe-inline`

**Status:** Implementado. `unsafe-inline` foi **removido** de `script-src`.

**Implementação:** O `SecurityHeadersMiddleware` gera um nonce criptográfico único (`secrets.token_urlsafe(16)`) por requisição HTTP e o armazena em `request.state.csp_nonce`. Todos os 17 templates Jinja2 utilizam `nonce="{{ request.state.csp_nonce }}"` em todas as tags `<script>`. Os 222 inline event handlers (`onclick`, `onchange`, etc.) foram convertidos para `addEventListener()` com event delegation via `data-action` attributes.

**Regras para novos templates:**
1. Todo `<script>` (inline ou com src) deve incluir `nonce="{{ request.state.csp_nonce }}"`
2. Nunca usar inline event handlers (`onclick`, `onchange`, etc.) — usar `addEventListener()` ou event delegation com `data-action`
3. Testar com DevTools > Console para verificar ausência de violações CSP

#### `'unsafe-eval'` em `script-src`

**Status:** Necessário enquanto Tailwind CSS CDN for utilizado.

**Justificativa técnica:** O Tailwind CSS via CDN (`cdn.tailwindcss.com`), utilizado em 15 templates, compila classes utilitárias em CSS no runtime do browser usando `eval()`. Não há alternativa viável sem migrar para build-time (Tailwind CLI ou PostCSS).

**Mitigação futura:** Migrar de Tailwind CDN para build-time (Tailwind CLI com PostCSS), gerando CSS estático em tempo de compilação. Isso eliminaria a necessidade de `unsafe-eval`.

#### `'unsafe-inline'` em `style-src`

**Status:** Necessário enquanto Tailwind CSS CDN for utilizado. Nonces **não** são usados em `style-src` porque o Tailwind CDN injeta estilos inline dinamicamente e a presença de nonces causaria a rejeição desses estilos pelo browser (CSP Level 2: nonces ignoram `unsafe-inline`).

**Risco:** Baixo. Estilos inline não podem executar código arbitrário. A mitigação futura é a mesma: migrar de Tailwind CDN para build-time.

### 8.2 HSTS (Strict-Transport-Security)

O header HSTS é adicionado automaticamente pelo proxy Replit em produção (`max-age=63072000; includeSubDomains`). O middleware da aplicação **não** adiciona HSTS para evitar duplicação de headers. Se a plataforma de deploy mudar, reativar HSTS no `SecurityHeadersMiddleware`.

---

## 9. Variáveis de Ambiente e Segredos

Nenhum valor sensível pode estar hardcoded no código. Qualquer nova variável sensível adicionada ao projeto deve ser registrada no Replit Secrets e documentada aqui.

As variáveis atualmente obrigatórias em produção são: `SESSION_SECRET` (mínimo 64 caracteres hex, armazenado como Secret), `DATABASE_URL`, `OPENAI_API_KEY`, `ZAPI_CLIENT_TOKEN`, `TAVILY_API_KEY`, e `WAHA_API_KEY`. Para SSO Microsoft: `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` (armazenado como Secret), `MICROSOFT_TENANT_ID`. Domínio de produção configurado em `ALLOWED_ORIGINS`.

A aplicação falha na inicialização se `SECRET_KEY` não estiver definida ou contiver o valor padrão de desenvolvimento. Para gerar uma chave segura:

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

Swagger/OpenAPI é completamente desabilitado em produção (`docs_url=None`, `redoc_url=None`, `openapi_url=None` quando `REPL_DEPLOYMENT` está definida). Nenhuma especificação da API é exposta em produção.

---

## 10. Checklist para Nova Feature

Antes de considerar qualquer novo código pronto para produção, responda estas perguntas. Se qualquer resposta for "não" ou "não sei", o código precisa ser revisado antes de fazer deploy.

A rota nova tem verificação de autenticação? Se recebe IDs, verifica ownership? Se é admin-only, verifica a role? Todos os inputs passam por validação de schema (Pydantic)? Nenhuma query usa concatenação com dados do usuário? Se chama serviços externos, há allowlist de domínios e rate limit por usuário? Se aceita uploads, valida MIME, tamanho e gera hash? Erros retornam mensagem genérica ao cliente e detalhe ao log? Eventos de segurança relevantes são logados? Nenhum segredo novo está hardcoded?

---

## 11. Dependências

Antes de adicionar uma nova dependência ao projeto, considere: ela é ativamente mantida? Tem histórico de vulnerabilidades? É realmente necessária ou uma função da stdlib resolve?

Após qualquer alteração no `requirements.txt`, execute:

```bash
pip-audit
```

Zero vulnerabilidades de severidade HIGH ou CRITICAL é o critério de aceite. O resultado do audit deve ser revisado antes de todo deploy para produção.

---

## Referências

Este documento foi produzido com base no **OWASP Top 10:2025** e em auditoria de segurança realizada antes do lançamento da aplicação. Para aprofundamento nos tópicos cobertos aqui, as referências primárias são:

- OWASP Top 10:2025: https://owasp.org/Top10
- OWASP Application Security Verification Standard (ASVS): https://owasp.org/ASVS
- Documentação Microsoft MSAL Python: https://docs.microsoft.com/azure/active-directory/develop/msal-python
- FastAPI Security: https://fastapi.tiangolo.com/tutorial/security/

---

### Arquivos de implementação de segurança

| Arquivo | Responsabilidade |
|---|---|
| `core/security_middleware.py` | SecurityHeadersMiddleware, GlobalAuthMiddleware, rate limiting (slowapi), CORS, error handlers, `record_security_event()` |
| `core/security.py` | JWT creation/validation (access + refresh), jti generation, token blacklist (revoke/check), SECRET_KEY validation, password hashing |
| `core/upload_validator.py` | Upload validation (python-magic MIME, size limits, SHA-256 hash) |
| `api/endpoints/auth.py` | Login/logout/SSO endpoints, rate limiting (10/min SSO), token revocation on logout, refresh token rotation |
| `database/models.py` (`RevokedToken`) | Tabela de tokens revogados (blacklist) com jti, revoked_at, expires_at |

---

*Última atualização: fevereiro de 2026. Este documento deve ser revisado sempre que a arquitetura de autenticação mudar, novas integrações externas forem adicionadas, ou após qualquer incidente de segurança.*
