# Diagnóstico: Falha Persistente no Health Check do Deployment

**Projeto:** Agente IA - RV (Stevan)  
**Plataforma:** Replit (Reserved VM Deployment)  
**Data:** 26 de fevereiro de 2026  
**Tentativas de deploy:** 4+ (todas falharam com a mesma mensagem)

---

## 1. Erro Reportado pelo Replit

```
The deployment is failing health checks. This can happen if the application 
isn't responding, responds with an error, or doesn't respond in time. 
Health checks are sent to the / endpoint by default and must respond as 
soon as possible. Make sure that the / endpoint is implemented and returns 
a 200 status code in a timely manner. Avoid doing expensive or long running 
operations on the / endpoint, prefer deferring them to a different route. 
Check the logs for more information.
```

**Timestamp do erro:** 2026-02-25T19:28:43Z (primeira tentativa documentada)

---

## 2. Comportamento do Health Check (Documentação Oficial do Replit)

Fonte: https://docs.replit.com/cloud-services/deployments/troubleshooting

> "Before marking your published app as live, a health check sends an HTTP request to your app. If your homepage takes more than five seconds to respond, the health check times out and publishing fails at the final step."

- **Endpoint:** `/` (padrão, não configurável via código — `.replit` é protegido)
- **Timeout:** 5 segundos
- **Protocolo:** HTTP request (GET presumido)
- **Critério:** HTTP 200 em ≤5 segundos

---

## 3. Configuração do Deployment

### `.replit`
```toml
[deployment]
deploymentTarget = "vm"
run = ["python", "main.py"]

[[ports]]
localPort = 5000
externalPort = 80
```

- **Nota:** Não há campo `healthcheckPath` (arquivo `.replit` é protegido e não pode ser editado programaticamente).

### Startup em Produção (cold start)
O Python leva **~11-13 segundos** para compilar os módulos pesados (FastAPI, SQLAlchemy, OpenAI, JWT, etc.) antes do uvicorn sequer iniciar. Para contornar isso, implementamos um **TCP Health Shim** — servidor TCP raw usando apenas `socket` + `threading` (stdlib) que faz bind na porta 5000 antes de qualquer import pesado.

---

## 4. Logs de Deployment (Última Tentativa)

```
TIMESTAMP (unix ms)          NÍVEL    CONTEÚDO
───────────────────────────────────────────────────────────────────
1772105709261.0              [Info]   starting up user application
1772105709261.0              [Info]   metasidecar: loaded enterprise status is_enterprise=false
1772105709263.0              [Info]   forwarding local port 5000 to external port 80 (mapped as 1104)
1772105709751.0              [Error]  [SHIM] Health check shim ativo na porta 5000
1772105720546.0              [Error]  INFO: Waiting for application startup.
1772105720546.0              [Error]  INFO: Started server process [28]
1772105722809.0              [Error]  INFO: Application startup complete.
1772105730552.0              [Error]  [SHIM] Health check shim parado — uvicorn operacional.
```

### Análise da Timeline

| Tempo relativo | Evento | Status |
|---|---|---|
| t=0ms | Container inicia, metasidecar configura | Infraestrutura Replit |
| t=+2ms | Port forwarding: 5000 → 80 (mapped 1104) | Proxy pronto |
| t=+490ms | **Shim bind(5000) + listen(10) + thread** | Porta 5000 aceitando conexões |
| t=+11.285s | Uvicorn inicia (PID 28) | Servidor HTTP Python ativo |
| t=+13.548s | `Application startup complete` (lifespan yield) | Uvicorn processando requests |
| t=+21.291s | Shim parado via background task | Apenas uvicorn na porta 5000 |

### Observação Crítica

**ZERO entradas de access log.** Nenhum `GET / HTTP/1.1 200 OK` aparece nos logs, nem do shim (que não loga requests individuais) nem do uvicorn (que deveria logar via `uvicorn.access` para stderr). Isso significa que **nenhum HTTP request chegou ao uvicorn** durante todo o ciclo de vida do deployment, ou as requisições foram todas tratadas pelo shim sem chegar ao uvicorn.

---

## 5. Logs de Deployment (Tentativa Anterior — sem shim stderr)

```
TIMESTAMP (unix ms)          NÍVEL    CONTEÚDO
───────────────────────────────────────────────────────────────────
1772047678116.0              [Info]   starting up user application
1772047678116.0              [Info]   metasidecar: loaded enterprise status is_enterprise=false
1772047678118.0              [Info]   forwarding local port 5000 to external port 80 (mapped as 1104)
1772047690891.0              [Error]  INFO: Started server process [27]
1772047690891.0              [Error]  INFO: Waiting for application startup.
1772047693045.0              [Error]  INFO: Application startup complete.
```

Nota: Nesta tentativa, o shim usava `print()` (stdout), invisível nos logs de deployment (que capturam apenas stderr). Sem o `[SHIM]` nos logs, não era possível verificar se o shim estava ativo.

---

## 6. Comparação: Development vs Production

| Aspecto | Development (Replit Workspace) | Production (VM Deployment) |
|---|---|---|
| `[SHIM] ativo` | ✅ Aparece nos logs | ✅ Aparece nos logs (stderr) |
| `GET / HTTP/1.1 200 OK` | ✅ Aparece nos access logs | ❌ **Nunca aparece** |
| `GET /health` | ✅ Retorna `{"status":"ok"}` | ❓ Sem evidência de requisição |
| Cold start time | <2s (módulos em cache) | ~11-13s (compilação from scratch) |
| Porta 5000 ativa em | t<1s | t=490ms (shim), t=13.5s (uvicorn) |
| Resultado health check | ✅ App funciona | ❌ **Falha consistente** |

---

## 7. Código do TCP Health Shim (main.py linhas 1-70)

```python
import socket as _socket
import threading as _threading

class _TCPHealthShim(_threading.Thread):
    _HTTP_200 = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 15\r\n"
        b"Connection: close\r\n\r\n"
        b'{"status":"ok"}'
    )

    def __init__(self, port=5000):
        super().__init__(daemon=True)
        self._port = port
        self._sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        self._sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
        self._active = False

    def start_listening(self):
        # bind('0.0.0.0', 5000), listen(10), settimeout(0.5)
        # self._sock (listener) TEM timeout de 0.5s no accept()
        ...

    def run(self):
        while self._active:
            conn, _ = self._sock.accept()    # timeout=0.5s no listener ✅
            conn.recv(2048)                  # ⚠️ SEM TIMEOUT na conexão aceita
            conn.sendall(self._HTTP_200)
            conn.close()

_health_shim = _TCPHealthShim()
_health_shim.start_listening()

# ... imports pesados começam aqui (~11s em produção) ...
```

### Bug Identificado: `conn.recv(2048)` sem timeout

O socket listener (`self._sock`) tem `settimeout(0.5)`, mas o socket da conexão aceita (`conn`) **não tem timeout configurado**. Se o health checker do Replit:

1. Abre uma conexão TCP (SYN/ACK) ✅
2. Mas **não envia dados HTTP imediatamente** (ou envia parcialmente)
3. `conn.recv(2048)` **bloqueia indefinidamente** esperando dados

O shim tem **uma única thread**. Se `recv()` bloqueia, nenhuma outra conexão pode ser atendida. O health checker eventualmente faz timeout (5s) e marca o deployment como falho.

---

## 8. Uvicorn via Socket Pré-criado (main.py linhas 1149-1162)

```python
if __name__ == "__main__":
    import uvicorn

    _uvicorn_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    _uvicorn_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    _uvicorn_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
    _uvicorn_sock.bind(('0.0.0.0', 5000))
    _uvicorn_sock.listen(10)

    config = uvicorn.Config(app, host="0.0.0.0", port=5000, log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve(sockets=[_uvicorn_sock]))
```

Nota: `_uvicorn_sock` é criado no bloco `if __name__ == "__main__"`, que executa APÓS todos os imports (~11s). Até lá, apenas o shim está na porta 5000.

---

## 9. Hipóteses Analisadas

### H1: `conn.recv(2048)` bloqueia — shim trava (PROVÁVEL ★★★★★)
**Análise do Arquiteto (Subagente):** "conn.recv(2048) without timeout can block indefinitely if the health checker opens a TCP connection but sends no data or only partial data. That would tie up the shim thread and prevent responding."

O health checker do Replit pode enviar um TCP SYN, esperar pela resposta HTTP, e o shim fica preso no `recv()` sem retornar dados a tempo. Como o shim é single-threaded, TODAS as conexões subsequentes ficam na fila do kernel.

**Evidência:** Zero access logs → shim nunca completou `sendall()` → travou em `recv()`.

### H2: Gap de ~490ms antes do shim iniciar (POSSÍVEL ★★★☆☆)
O shim leva ~490ms para fazer bind na porta. Se o health checker enviar a primeira requisição antes disso, recebe "connection refused". Se não há retry automático no health checker do Replit, o deployment falha imediatamente.

**Contra-argumento:** 490ms está dentro do timeout de 5s. Seria razoável esperar que o health checker retente.

### H3: Formato HTTP do shim não aceito pelo health checker (POSSÍVEL ★★★☆☆)
O shim envia HTTP/1.1 raw via TCP. O health checker pode esperar comportamento HTTP completo (parsing de headers, chunked encoding, etc.) que o shim não implementa. Ou o health checker pode usar HTTP/1.0.

### H4: SO_REUSEPORT causa conflito (IMPROVÁVEL ★★☆☆☆)
Tanto o shim quanto o `_uvicorn_sock` usam SO_REUSEPORT na mesma porta. O OS Linux faz load-balancing entre eles. Em teoria, uma health check request poderia ir para o `_uvicorn_sock` (que está listening mas o event loop ainda não processa) antes do uvicorn estar pronto. A requisição ficaria na fila do kernel e eventualmente seria processada, mas se o timeout for curto, pode falhar.

### H5: Health check usa porta diferente de 5000 (IMPROVÁVEL ★☆☆☆☆)
O log mostra "mapped as 1104" — pode indicar porta interna do proxy. Se o health check for para porta 1104, nada estaria ouvindo.

**Contra-argumento:** Improvável — a documentação diz que o health check vai para o endpoint `/` da app, que é servido na porta configurada (5000→80).

### H6: Requirement de múltiplas respostas 200 consecutivas (DESCONHECIDO ★★☆☆☆)
Possível que o Replit exija N respostas 200 consecutivas durante um período, e a transição shim→uvicorn cause uma falha intermitente que quebra a sequência.

### H7: Health check testa APÓS deploy completo (POSSÍVEL ★★★☆☆)
A documentação diz "Before marking your published app as live" — pode significar que o health check só dispara APÓS o container considerar que a app está estável. Se isso acontece em t=30-45s, o shim já parou (t=21s) e o uvicorn deveria estar respondendo. Mas não há evidence de requests HTTP nos logs.

---

## 10. Soluções Propostas (Ranqueadas por Confiabilidade)

### Solução A: Corrigir o shim — timeout no `conn` + resposta sem esperar recv (★★★★★)
```python
def run(self):
    while self._active:
        try:
            conn, _ = self._sock.accept()
            try:
                conn.settimeout(2)          # Timeout de 2s na conexão aceita
                try:
                    conn.recv(1024)          # Tenta ler, mas com timeout
                except _socket.timeout:
                    pass                     # Sem dados? Responde mesmo assim
                conn.sendall(self._HTTP_200)
            except Exception:
                pass
            finally:
                conn.close()
        except _socket.timeout:
            continue
        except Exception:
            break
```

Adicionar `conn.settimeout(2)` e fazer `sendall()` mesmo se o `recv()` der timeout. Isso garante que o shim SEMPRE responde, independente do comportamento do health checker.

Também: adicionar logging para cada `accept()` e `sendall()` no shim para confirmar se o tráfego está chegando.

### Solução B: Substituir shim TCP por mini-app ASGI (★★★★☆)
Em vez de um servidor TCP raw, usar um uvicorn mínimo com app ASGI instantânea:

```python
import socket as _socket

# Criar socket com SO_REUSEPORT ANTES dos imports
_shared_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
_shared_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
_shared_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
_shared_sock.bind(('0.0.0.0', 5000))
_shared_sock.listen(10)

# ... imports pesados ...

# No if __name__:
config = uvicorn.Config(app, host="0.0.0.0", port=5000, log_level="info")
server = uvicorn.Server(config)
asyncio.run(server.serve(sockets=[_shared_sock]))
```

Isso garante que o socket está bound/listening desde t=0, mas o uvicorn processa as conexões quando estiver pronto. Conexões durante cold start ficam na fila do kernel (backlog=10) sem "connection refused".

**Limitação:** A fila do kernel segura conexões até o `listen(backlog)` se esgotar. Se o health checker fizer muitas tentativas, pode estourar o backlog.

### Solução C: Usar gunicorn como wrapper (★★★☆☆)
Mudar o deployment para gunicorn com `--reuse-port`:

```toml
[deployment]
run = ["gunicorn", "--bind=0.0.0.0:5000", "--reuse-port", "--timeout=120", "--workers=1", "main:app"]
```

O gunicorn faz bind na porta ANTES de carregar a app, e gerencia workers que importam a app. Isso elimina o cold start problem porque o gunicorn responde ao health check antes da app estar pronta.

**Limitação:** Pode precisar de ajustes no `main.py` para funcionar como módulo WSGI/ASGI importável (sem `if __name__`).

---

## 11. Informações para o Consultor Externo

### Perguntas Específicas para o Suporte Replit:

1. **O health check do deployment para VM (`deploymentTarget = "vm"`) é idêntico ao do autoscale?** A documentação de troubleshooting menciona "homepage takes more than five seconds" mas não especifica se isso se aplica a VMs.

2. **O health checker do Replit faz retry em "connection refused"?** Se a primeira tentativa (antes do app iniciar) recebe ECONNREFUSED, ele retenta dentro dos 5 segundos ou marca como falha imediata?

3. **Qual é o request HTTP exato que o health checker envia?** Método, headers, path. Se é um simples `GET / HTTP/1.1`, nosso shim deveria responder. Se é algo mais complexo (TLS, HTTP/2, WebSocket upgrade), o shim não suporta.

4. **O "mapped as 1104" no log de forwarding indica uma porta alternativa?** O health check poderia estar indo para porta 1104 em vez de 5000?

5. **É possível configurar `healthcheckPath` para Reserved VM Deployments?** A documentação não menciona esse campo, e o arquivo `.replit` é protegido para edição via código.

6. **Existe uma forma de acessar logs do health checker (não apenas da aplicação)?** Precisamos ver SE o health check está sendo enviado, QUANDO, e QUAL resposta ele recebe.

### Reprodução do Problema

1. Abrir o Replit `agente-ia-rv-svn`
2. Clicar em "Publish" → selecionar "Reserved VM"
3. Aguardar o deploy
4. Deploy falha na etapa de health check (~30-45s após iniciar)
5. Logs de deployment mostram app completamente funcional

### Ambiente

- **Replit Plan:** (verificar com o usuário)
- **Python:** 3.11
- **Framework:** FastAPI + Uvicorn
- **Banco:** PostgreSQL
- **Nix packages:** 30+ (incluindo mupdf, cairo, ffmpeg, etc.)
- **Tamanho do projeto:** ~1100 linhas em main.py, 16 módulos de endpoint

---

## 12. Próximos Passos

1. **Implementar Solução A** (timeout no `conn` + logging de tráfego no shim)
2. Se Solução A falhar: **Implementar Solução B** (socket pré-criado sem shim, fila do kernel)
3. Se Solução B falhar: **Contactar suporte Replit** com este documento
4. Se Solução C for necessária: **Mudar para gunicorn** (requer refatoração de startup)
