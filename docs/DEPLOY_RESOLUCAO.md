# Resolução do Deploy — Health Check VM Replit

**Data de resolução:** 2026-02-26
**Tentativas até resolver:** 7
**Causa raiz:** `SO_REUSEPORT` interfere com o proxy interno do Replit (metasidecar)

---

## Problema

O deploy em Reserved VM do Replit falhava consistentemente por timeout no health check (5s). A aplicação subia corretamente, mas o health checker nunca conectava na porta 5000.

## Cronologia das tentativas

| # | Mudança | Resultado |
|---|---------|-----------|
| 1 | Lazy router registration (imports em background) | Falhou — cold start ainda >5s |
| 2 | Deferred dependency checks | Falhou — cold start ainda >5s |
| 3 | TCP Health Shim com `SO_REUSEPORT` | Falhou — zero conexões no shim |
| 4 | Socket pré-criado com `SO_REUSEPORT` para uvicorn | Falhou — zero conexões |
| 5 | Shim logando em stderr + delayed stop | Falhou — confirmou zero conexões |
| 6 | `healthcheckPath=/health` + remoção da segunda `[[ports]]` | Falhou — zero conexões |
| 7 | **Remoção completa do shim + SO_REUSEPORT + socket pré-criado** | **SUCESSO** |

## Causa raiz

O `SO_REUSEPORT` permite múltiplos sockets escutarem na mesma porta. O kernel do Linux faz load-balancing entre eles. O proxy interno do Replit (metasidecar) também precisa interagir com a porta 5000 para fazer o port-forwarding (5000 → 80 externo). Quando o shim TCP e/ou o socket pré-criado faziam bind com `SO_REUSEPORT` antes do metasidecar, isso impedia o proxy de rotear o health check para a aplicação.

Evidência: em 6 tentativas com `SO_REUSEPORT`, **zero conexões TCP** chegaram na porta 5000, apesar do shim estar ativo e pronto para responder.

## Solução final

1. Removida a classe `_TCPHealthShim` inteira
2. Removido o socket pré-criado com `SO_REUSEPORT` para uvicorn
3. Restaurado o uvicorn para bind padrão: `uvicorn.run(app, host="0.0.0.0", port=5000)`
4. Mantido lazy router registration (não interfere no port binding)
5. Mantida rota `/health` top-level (responde instantaneamente)

## Aprendizados

### Regras para deploy em VM no Replit

1. **NUNCA usar `SO_REUSEPORT`** — interfere com o metasidecar/proxy interno
2. **NUNCA criar sockets pré-bound** na porta de serviço — deixar o framework (uvicorn) fazer o bind
3. **Usar bind padrão**: `uvicorn.run(app, host="0.0.0.0", port=5000)` — simples funciona
4. **Rota `/health` top-level** é suficiente para o health check se o startup for razoável
5. **Lazy imports** são seguros — não envolvem port binding, apenas deferimento de imports Python
6. **Logs devem usar stderr** — deployment logs do Replit capturam apenas stderr
7. **Middleware de logging `[ACCESS]`** é útil para confirmar que requests chegam em produção

### O que o log "mapped as 1104" significa

O Replit usa um proxy interno (metasidecar) que:
- Escuta na porta 1104 externamente
- Faz forwarding para localPort 5000
- Mapeia para externalPort 80

O health checker provavelmente bate no metasidecar, que redireciona para 5000. Se a porta 5000 tem listeners conflitantes (SO_REUSEPORT), o forwarding falha silenciosamente.

### Diagnóstico eficaz

O middleware `[ACCESS]` em stderr foi crucial para confirmar que o health check não chegava. Sem ele, seria impossível distinguir entre "health check chega mas falha" e "health check nunca chega".

## Arquivos modificados

- `main.py` — removido shim TCP, SO_REUSEPORT, socket pré-criado; restaurado uvicorn padrão
- `replit.md` — atualizado com novas regras de deployment
- `.replit` — adicionado `healthcheckPath = "/health"`, removida segunda `[[ports]]`
