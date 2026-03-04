# Guia para Agentes de IA: Deploy Replit → GitHub → Railway → Servidor Próprio

**Para quem é este guia:** Agentes de IA (Replit Agent, Cursor, Copilot, etc.) que desenvolvem aplicações e precisam fazer o vínculo entre ambiente de desenvolvimento, repositório e produção.

**Versão:** 1.0  
**Contexto:** Aplicações com backend em qualquer linguagem + frontend compilado (React/Vue/Svelte/etc.)

---

## Conceito Central: O que vai para onde

```
REPLIT (desenvolvimento)
    ↓  git push
GITHUB (repositório — fonte da verdade)
    ↓  deploy automático
RAILWAY (produção em nuvem)
    ↓  migração futura
SERVIDOR PRÓPRIO (VPS/cloud da empresa)
```

**Regra de ouro:** O GitHub é a única fonte da verdade. Tudo que vai para produção passa por ele. Se não está no GitHub, não existe em produção.

---

## Parte 1: Arquitetura de Deploy (Entenda Antes de Agir)

### Os 3 cenários de build de frontend

Antes de qualquer configuração, identifique qual cenário se aplica ao projeto:

| Cenário | Como funciona | dist/ no .gitignore? |
|---------|---------------|----------------------|
| **A — Docker com Node.js** | Dockerfile instala Node, roda `npm run build` no servidor | SIM — build acontece no servidor |
| **B — Docker sem Node.js** | Dockerfile é só backend (Python/Go/Java/etc.), sem Node | NÃO — build deve estar no repo |
| **C — Deploy estático** | Netlify, Vercel, GitHub Pages | NÃO — build vai para o repo |

**Como identificar o seu cenário:** Abra o Dockerfile e procure por `node`, `npm`, `yarn` ou `bun`. Se não existir nenhum desses, é o Cenário B.

> **Atenção para agentes de IA:** O erro mais comum é assumir o Cenário A quando o projeto é Cenário B. Verifique o Dockerfile antes de configurar o .gitignore.

---

## Parte 2: Configuração Inicial (Execute Uma Vez)

### Fase 1: Limpeza do repositório

```bash
# Remover arquivos legados/temporários comuns
find . -type f \( -name "*.legacy" -o -name "*.old" -o -name "*.backup" -o -name "*.bak" \) -delete
rm -f sed* *.tmp *.swp *.swo cookies.txt

# Remover relatórios de teste gerados automaticamente
find . -type d -name "reports" -path "*/tests/*" -exec rm -rf {} + 2>/dev/null || true
find . -type d -name "coverage" -exec rm -rf {} + 2>/dev/null || true

# Verificar o que foi limpo
git status
```

### Fase 2: Builds de frontend

```bash
# Para cada app frontend do projeto:
cd frontend/nome-do-app
npm install
npm run build
cd ../..

# Verificar que o build foi gerado
ls frontend/nome-do-app/dist/

# Se for Cenário B ou C, adicionar ao git:
git add frontend/nome-do-app/dist/
```

### Fase 3: Criar .env.example

O arquivo `.env.example` documenta quais variáveis são necessárias, sem expor os valores reais.

```bash
# Estrutura do .env.example:
# --- Ambiente ---
APP_ENV=development

# --- URL da aplicação ---
APP_BASE_URL=http://localhost:3000

# --- Banco de dados ---
DATABASE_URL=postgresql://usuario:senha@host:porta/banco

# --- Autenticação ---
JWT_SECRET=gere-uma-chave-longa-e-aleatoria

# --- APIs externas (substitua pelos nomes das suas) ---
NOME_DA_API_KEY=sua-chave-aqui
```

**Regra:** Para cada variável em `.env`, deve existir a mesma chave (sem o valor) em `.env.example`.

### Fase 4: Configurar .gitignore corretamente

```gitignore
# === DEPENDÊNCIAS ===
node_modules/
vendor/
.venv/
__pycache__/
*.py[cod]
*.egg-info/

# === SEGREDOS — NUNCA COMMITAR ===
.env
.env.local
.env.production
*.pem
*.key

# === BANCO DE DADOS LOCAL ===
*.db
*.sqlite
*.sqlite3
backup_*.sql
*.sql.bak

# === TEMPORÁRIOS (jamais devem existir no repo) ===
sed*
*.tmp
*.swp
*.swo
cookies.txt
*.log

# === TESTES (gerados automaticamente) ===
tests/**/reports/
coverage/
.coverage
.pytest_cache/
htmlcov/

# === CÓDIGO LEGADO (regra preventiva) ===
*.legacy
*.old
*.backup
*.bak

# === IDE E OS ===
.vscode/
.idea/
.DS_Store
Thumbs.db

# === PLATAFORMA DE DESENVOLVIMENTO ===
# Replit:
.replit
replit.nix
.config/
.cache/
.upm/

# === FRONTEND — LEIA COM ATENÇÃO ===
# Cenário A (Docker com Node): descomente a linha abaixo
# dist/
# build/

# Cenário B (Docker sem Node) ou C (estático): NÃO ignore dist/
# Os builds compilados devem estar no repositório.
```

### Fase 5: Commit e push

```bash
git add .
git status

# Revisar o diff antes de commitar
git diff --staged --stat

git commit -m "clean: initial repository cleanup and configuration"
git push origin main
```

---

## Parte 3: Configuração do Railway

### Conectar GitHub ao Railway

1. Criar conta em [railway.app](https://railway.app)
2. Criar novo projeto → "Deploy from GitHub repo"
3. Autorizar acesso ao repositório
4. Selecionar o repositório e a branch (`main`)

### Variáveis de ambiente no Railway

Nunca commite `.env`. Configure as variáveis diretamente no painel do Railway:

```
Railway → Projeto → Variables → Add Variable
```

Para cada linha do `.env.example`, adicione a variável com o valor real no painel do Railway.

Variáveis essenciais para qualquer projeto:

| Variável | Descrição |
|----------|-----------|
| `PORT` | Injetada automaticamente pelo Railway — não configurar manualmente |
| `DATABASE_URL` | Gerada automaticamente se usar banco do Railway |
| `APP_ENV` ou `ENV` | Definir como `production` |
| `APP_BASE_URL` | URL pública gerada pelo Railway (ex: `https://nome.up.railway.app`) |

### Dockerfile mínimo funcional

```dockerfile
FROM python:3.12-slim
# Substitua pela linguagem do projeto (node:20-alpine, golang:1.22, etc.)

WORKDIR /app

# Instalar dependências do sistema (ajuste conforme necessidade)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências da aplicação
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código (inclui dist/ do frontend se Cenário B)
COPY . .

# Criar diretórios necessários
RUN mkdir -p uploads

# Expor porta (Railway injeta $PORT)
EXPOSE 8000

# Health check obrigatório para Railway
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Usar $PORT injetado pelo Railway
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

> **Para projetos Node.js no backend:**
> ```dockerfile
> FROM node:20-alpine
> WORKDIR /app
> COPY package*.json ./
> RUN npm ci --only=production
> COPY . .
> EXPOSE 3000
> HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
>     CMD wget -q -O- http://localhost:${PORT:-3000}/health || exit 1
> CMD ["sh", "-c", "node src/index.js"]
> ```

### railway.json (opcional mas recomendado)

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE"
  },
  "deploy": {
    "healthcheckPath": "/health",
    "healthcheckTimeout": 120,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

> **Atenção:** Não inclua `startCommand` no railway.json se o CMD do Dockerfile usa `$PORT`. O Railway injeta a porta via ambiente, e ter `startCommand` pode causar conflito.

### Rota de health check (obrigatória)

Toda aplicação precisa responder em `/health` para o Railway validar que está ativa.

```python
# Python/FastAPI
@app.get("/health")
def health():
    return {"status": "ok"}
```

```javascript
// Node.js/Express
app.get('/health', (req, res) => res.json({ status: 'ok' }));
```

```go
// Go/net http
http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    w.Write([]byte(`{"status":"ok"}`))
})
```

---

## Parte 4: Banco de Dados no Railway

### Criar banco PostgreSQL no Railway

1. Railway → Projeto → "New Service" → "Database" → PostgreSQL
2. Escolher o template com extensões necessárias (ex: `pgvector-pg17` para projetos com embeddings)
3. A variável `DATABASE_URL` é injetada automaticamente nos outros serviços do projeto

> **Importante:** Use o template correto. O PostgreSQL padrão do Railway **não** inclui extensões como `pgvector`. Escolha o template adequado no momento da criação — não é possível migrar depois sem recriar.

### Desenvolvimento vs Produção (bancos separados)

```
Desenvolvimento (local/Replit)  → Banco local ou banco de dev separado
Produção (Railway)              → Banco do Railway
```

**Consequências práticas:**
- Alterações de dados feitas localmente **não refletem em produção**
- Migrações de schema precisam rodar em produção (configure no startup da aplicação)
- Ao fazer um novo deploy, apenas o código é atualizado; os dados permanecem

---

## Parte 5: Domínio Customizado

### No Railway

1. Railway → Projeto → Settings → Domains → "Add Custom Domain"
2. Inserir o domínio (ex: `app.suaempresa.com.br`)
3. Railway fornece um registro CNAME para apontar no DNS

### No provedor de DNS

```
Tipo:  CNAME
Nome:  app (ou subdomínio desejado)
Valor: [fornecido pelo Railway]
TTL:   auto
```

### Variáveis a atualizar após trocar de domínio

Após configurar domínio customizado, atualizar no painel do Railway:

| Variável | Novo valor |
|----------|------------|
| `APP_BASE_URL` | `https://app.suaempresa.com.br` |
| `ALLOWED_ORIGINS` | `https://app.suaempresa.com.br` |

E em cada serviço externo integrado (SSO, webhooks, OAuth redirect URIs).

---

## Parte 6: Migração para Servidor Próprio (VPS)

Quando o projeto precisar sair do Railway para uma VPS (DigitalOcean, AWS EC2, Hetzner, etc.):

### Pré-requisitos no servidor

```bash
# Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# Docker Compose (opcional, para múltiplos serviços)
apt-get install docker-compose-plugin

# Nginx (proxy reverso)
apt-get install nginx certbot python3-certbot-nginx
```

### Docker Compose para VPS

```yaml
version: '3.8'

services:
  app:
    build: .
    restart: always
    environment:
      - PORT=8000
      - ENV=production
      - DATABASE_URL=${DATABASE_URL}
      # Adicione as demais variáveis
    ports:
      - "8000:8000"
    volumes:
      - ./uploads:/app/uploads
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 3

  db:
    image: pgvector/pgvector:pg17
    # Use ankane/pgvector se precisar de pgvector
    restart: always
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Nginx como proxy reverso

```nginx
server {
    listen 80;
    server_name app.suaempresa.com.br;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Ativar HTTPS com Let's Encrypt
certbot --nginx -d app.suaempresa.com.br
```

### CI/CD simples para VPS (via GitHub Actions)

```yaml
# .github/workflows/deploy.yml
name: Deploy to VPS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /app/nome-do-projeto
            git pull origin main
            docker compose build
            docker compose up -d
            docker compose ps
```

---

## Parte 7: Regras Permanentes para Agentes de IA

### NUNCA faça

```
❌ Criar arquivos com extensões: .legacy  .old  .backup  .bak
❌ Criar pastas: backup/  old/  deprecated/  temp/
❌ Deixar no disco: sed*  *.tmp  cookies.txt  *.swp
❌ Versionar: .env  segredos  credenciais  chaves privadas
❌ Versionar: relatórios de teste  coverage/  logs de execução
❌ Duplicar código: se existe v1 e v2, delete v1 após migrar
❌ Adicionar dist/ ao .gitignore em projetos Cenário B ou C
❌ Commitar node_modules/ ou dependências instaladas
```

### SEMPRE faça

```
✅ Ao substituir código: delete a versão antiga (Git guarda histórico)
✅ Ao criar variável de ambiente: adicionar em .env E em .env.example
✅ Ao mudar frontend (Cenário B/C): rebuild + commit do dist/
✅ Ao deletar arquivo: verificar se é referenciado em outro lugar antes
✅ Commits com mensagens claras (veja padrões abaixo)
✅ Verificar o checklist antes de cada push
```

### Padrão de mensagens de commit

```bash
feat: adicionar autenticação por SSO
fix: corrigir erro 500 no endpoint de upload
clean: remover código legado de autenticação antiga
build: recompilar frontend após mudanças no dashboard
docs: atualizar .env.example com nova variável
refactor: extrair lógica de pagamento para service separado
```

---

## Parte 8: Checklist Pré-Push (Execute Antes de Cada Push)

```bash
# 1. Sem arquivos legados?
find . -type f \( -name "*.legacy" -o -name "*.old" -o -name "*.bak" \) ! -path "./.git/*"
# → Deve retornar vazio

# 2. Sem temporários?
git ls-files | grep -E "sed[0-9a-zA-Z]|\.tmp$|cookies\.txt"
# → Deve retornar vazio

# 3. .env protegido?
git ls-files | grep "^\.env$"
# → Deve retornar vazio

# 4. .env.example existe?
ls .env.example
# → Deve existir

# 5. Builds de frontend no repo? (Cenário B/C)
git ls-files | grep "dist/"
# → Deve retornar arquivos (se o projeto tem frontend compilado)

# 6. Sem duplicatas de builds?
# Verificar se dist/ existe em mais de um lugar para o mesmo app
# → Deve existir apenas em frontend/nome-do-app/dist/

# 7. node_modules fora do repo?
git ls-files | grep "node_modules"
# → Deve retornar vazio
```

---

## Parte 9: Situações Especiais

### Build de frontend falhou

```bash
# 1. Verificar a versão do Node
node --version
# → Deve ser compatível com o package.json (campo "engines" ou "volta")

# 2. Limpar cache e reinstalar
rm -rf node_modules package-lock.json
npm install
npm run build

# 3. Se ainda falhar, verificar erros de TypeScript/ESLint
npm run build 2>&1 | head -50
```

### .gitignore está ignorando arquivos que deveriam estar no repo

```bash
# Ver quais arquivos estão sendo ignorados
git status --ignored

# Forçar adicionar arquivo que está sendo ignorado
git add -f caminho/para/arquivo

# Para resolver permanentemente: editar .gitignore e remover a regra que bloqueia
```

### Banco de produção dessincronizado após deploy

```bash
# Se a aplicação não roda migrations automaticamente no startup:
# Conectar ao banco de produção via Railway CLI ou psql e rodar manualmente:
# railway run python manage.py migrate  (Django)
# railway run npx prisma migrate deploy  (Prisma/Node)
# railway run alembic upgrade head  (SQLAlchemy/Python)
```

### Serviço não sobe no Railway (health check falha)

```bash
# 1. Verificar logs no painel do Railway
# 2. Confirmar que a rota /health existe e responde 200
# 3. Confirmar que a aplicação usa $PORT (não porta hardcoded)
# 4. Aumentar healthcheckTimeout no railway.json para 120s se startup é lento
# 5. Verificar que todas as variáveis de ambiente estão configuradas no Railway
```

### Variável de ambiente não encontrada em produção

```
1. Verificar se existe no painel Railway → Variables
2. Verificar se o nome está exatamente igual (case-sensitive)
3. Verificar se .env.example está atualizado com a nova variável (documentação)
4. Fazer redeploy após adicionar variável (Railway reinicia automaticamente)
```

---

## Apêndice: Templates

### .gitignore universal para projetos fullstack

```gitignore
# Dependências
node_modules/
vendor/
.venv/
__pycache__/
*.py[cod]
*.egg-info/
.bundle/

# Segredos
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx

# Banco de dados local
*.db
*.sqlite
*.sqlite3
backup_*.sql

# Temporários e lixo
sed*
*.tmp
*.swp
*.swo
cookies.txt
*.log
.DS_Store
Thumbs.db

# Relatórios e cobertura (gerados automaticamente)
tests/**/reports/
coverage/
htmlcov/
.coverage
.pytest_cache/
.nyc_output/

# Código legado (regra preventiva)
*.legacy
*.old
*.backup
*.bak

# IDE
.vscode/
.idea/
*.sublime-*

# Plataformas de desenvolvimento
.replit
replit.nix
.config/
.cache/
.upm/

# Build — LEIA ANTES DE DESCOMENTAR
# Cenário A (Docker com Node): descomente abaixo
# dist/
# build/
# .next/
# out/
#
# Cenário B ou C: NÃO descomente — builds ficam no repo
```

---

**Autor:** Gerado a partir de experiência prática com projetos Python + React no Replit → Railway  
**Aplicável a:** Qualquer stack com backend em contêiner e frontend compilado  
**Última atualização:** 2026-03-04
