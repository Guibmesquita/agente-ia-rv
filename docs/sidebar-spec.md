# Sidebar - Contrato Visual e Técnico

**Versão:** 1.0  
**Data:** 2026-01-30  
**Status:** Fonte da Verdade para todas implementações de sidebar

---

## Objetivo

Este documento define a estrutura, comportamento e visual da sidebar do sistema SVN. Toda implementação (React ou Jinja) deve seguir exatamente este contrato.

---

## Estrutura Hierárquica

### Seção 1: Operação (Topo Fixo)

Sempre visível, sem collapso:

| Ordem | Label | Rota | Ícone (Heroicons) |
|-------|-------|------|-------------------|
| 1 | Insights | /insights | document-report |
| 2 | Conversas | /conversas | chat-alt-2 |
| 3 | Campanhas | /campanhas | speakerphone |
| 4 | Testar Agente | /teste-agente | play |

### Divisor Visual

Após "Testar Agente", adicionar linha divisória com margem vertical.

### Seção 2: Configurações (Colapsável)

Accordion principal com chevron rotativo:

| Ordem | Label | Rota | Tipo |
|-------|-------|------|------|
| 1 | Assessores | /assessores | Item direto |
| 2 | Usuários | /admin | Item direto |
| 3 | Personalidade IA | /agent-brain | Item direto |
| 4 | **Conhecimento** | - | Sub-accordion |
| 5 | Integrações | /integrations | Item direto |

### Sub-seção: Conhecimento (Colapsável Aninhado)

Dentro de Configurações:

| Ordem | Label | Rota |
|-------|-------|------|
| 1 | Produtos | /base-conhecimento |
| 2 | Upload Inteligente | /upload-inteligente |
| 3 | Fila de Revisão | /fila-revisao |
| 4 | Documentos | /documentos |

### Rodapé

Botão "Sair" fixo no bottom com hover vermelho.

---

## Comportamentos

### 1. Auto-expansão por Rota

Ao carregar página:
- Se rota está em `configRoutes`: expandir Configurações
- Se rota está em `knowledgeRoutes`: expandir Configurações + Conhecimento

```javascript
const knowledgeRoutes = ['/base-conhecimento', '/upload-inteligente', '/fila-revisao', '/documentos'];
const configRoutes = ['/assessores', '/admin', '/agent-brain', '/integrations', ...knowledgeRoutes];
```

### 2. Animação de Accordion

- Duração: 200ms
- Easing: ease-out
- Chevron: rotação 90° ao expandir

### 3. Estado Ativo

Item ativo recebe:
- Background: `bg-primary/10`
- Text color: `text-primary`

### 4. Modo Colapsado

Quando sidebar está retraída (width: 64px):
- Mostrar apenas ícones
- Remover accordions
- Exibir todos itens flat

---

## Especificações Visuais

### Dimensões

| Propriedade | Valor Expandido | Valor Colapsado |
|-------------|-----------------|-----------------|
| Width | 260px | 64px |
| Padding nav | py-4 | py-4 |
| Padding item | px-4 py-2.5 | px-4 py-2.5 |
| Border radius | rounded-lg | rounded-lg |

### Tipografia

| Elemento | Tamanho | Peso |
|----------|---------|------|
| Label Seção (OPERAÇÃO) | text-xs uppercase | font-semibold |
| Item Principal | text-base | font-medium |
| Item Indentado | text-sm | font-medium |
| Sub-accordion (Conhecimento) | text-sm | font-medium |

### Cores (usando tokens Tailwind)

| Elemento | Cor |
|----------|-----|
| Background sidebar | bg-white |
| Border | border-border |
| Texto normal | text-muted |
| Texto hover | text-foreground |
| Texto ativo | text-primary |
| Background ativo | bg-primary/10 |
| Background hover | bg-gray-50 |
| Botão sair hover | bg-red-50 text-danger |

### Ícones

- Tamanho: w-5 h-5
- Stroke: currentColor
- Stroke width: 2

---

## Ícones SVG (Heroicons Outline)

### Operação

```
Insights: M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z

Conversas: M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z

Campanhas: M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z

Testar Agente: M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z M21 12a9 9 0 11-18 0 9 9 0 0118 0z
```

### Configurações

```
Configurações (engrenagem): M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z + M15 12a3 3 0 11-6 0 3 3 0 016 0z

Assessores: M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z

Usuários: M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z

Personalidade IA: M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z

Conhecimento: M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253

Integrações: M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1
```

### Conhecimento (subitens)

```
Produtos: M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4

Upload Inteligente: M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12

Fila de Revisão: M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4

Documentos: M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z
```

### Rodapé

```
Sair: M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1

Chevron: M9 5l7 7-7 7
```

---

## Regras de Implementação

### React (Fonte Primária)

- Usar Framer Motion para animações
- Estado local para accordions
- useEffect para auto-expansão por rota

### Jinja (Réplica Temporária)

- Seguir EXATAMENTE as mesmas classes CSS
- JavaScript vanilla para accordion behavior
- Mesmo HTML structure
- Marcado como TEMPORÁRIO - migração futura para React

### Isolamento CSS

- NUNCA usar `* { margin: 0; padding: 0; }`
- NUNCA importar global.css em páginas React
- Apenas Tailwind utilities
- Sidebar Jinja não deve afetar React e vice-versa

---

## Checklist de QA

Antes de considerar sidebar implementada:

- [ ] Estrutura segue ordem exata deste spec
- [ ] Labels correspondem exatamente
- [ ] Ícones SVG corretos
- [ ] Auto-expansão funciona por rota
- [ ] Animação accordion suave (200ms)
- [ ] Chevron rotaciona corretamente
- [ ] Estado ativo marca item correto
- [ ] Sem rolagem lateral (overflow-x: hidden)
- [ ] Fonte legível (text-base para principais)
- [ ] Funciona igual em React e Jinja

---

## Roadmap

### Curto Prazo
- Sidebar Jinja como réplica fiel do React

### Médio Prazo
- Migrar todas páginas Jinja para React
- Sidebar única em React

### Longo Prazo
- Remover código Jinja de sidebar
- Componentização avançada
