import json
from typing import Optional, Tuple


# Tipos de bloco que devem ser tratados como tabela ao formatar conteúdo para o agente.
# Mantemos as strings literais aqui para evitar import circular com database.models.
#
# RAG V3.6 — BUG-FIX CRÍTICO da V3.5: o enum real `ContentBlockType.TABLE` armazena
# o valor "tabela" (em português), enquanto a V3.5 colocou "table" (inglês) neste
# set. O efeito: para 100% dos blocos de tabela em produção, o caminho rico nunca
# era ativado — só o fallback heurístico, que falha silenciosamente para JSON
# tabular bem formado mas grande. Agora cobrimos as três variantes possíveis para
# evitar regressão se houver legado: "tabela" (canônico), "financial_table" e
# "table" (defensivo).
TABLE_BLOCK_TYPES = {"tabela", "financial_table", "table"}

# Limites de truncamento. Para texto comum, mantemos um cap conservador para não
# explodir a janela de contexto do modelo. Para tabelas, usamos um cap muito maior
# porque cortar uma carteira/tabela pelo meio quebra a utilidade do RAG (ex.:
# uma carteira "Seven FIIs" com 12 ativos facilmente passa de 1500 chars quando
# expandida com Markdown + Fatos por linha).
DEFAULT_MAX_CHARS_TEXT = 600
DEFAULT_MAX_CHARS_TABLE = 4000


def format_tabular_content(raw_content: str) -> Optional[str]:
    """
    Versão LEGADA: converte JSON tabular em texto pipe-separado (compat).

    Input: '{"headers": ["Ativo", "Dív. Bruta"], "rows": [["60.414.500.000", "20.015.300.000"]]}'
    Output: 'Ativo: 60.414.500.000 | Dív. Bruta: 20.015.300.000'

    Retorna None se não for JSON tabular válido. Mantida para retrocompatibilidade
    com chamadores externos. Para uso novo, prefira `format_tabular_content_rich`.
    """
    if not raw_content or not raw_content.strip().startswith("{"):
        return None

    try:
        data = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    headers = data.get("headers", [])
    rows = data.get("rows", [])

    if not rows:
        return None

    lines = []

    for row in rows:
        if not isinstance(row, list):
            continue

        if headers and len(headers) >= 1:
            pairs = []
            for j, val in enumerate(row):
                if val is None or str(val).strip() == "":
                    continue
                if j < len(headers):
                    pairs.append(f"{headers[j]}: {val}")
                else:
                    pairs.append(str(val))
            if pairs:
                lines.append(" | ".join(pairs))
        else:
            non_empty = [str(v) for v in row if v is not None and str(v).strip()]
            if non_empty:
                lines.append(" | ".join(non_empty))

    return "\n".join(lines) if lines else None


def format_tabular_content_rich(raw_content: str) -> Optional[str]:
    """
    Converte JSON tabular em representação Markdown enriquecida.

    Produz dois blocos no mesmo conteúdo:
      1) Tabela Markdown padrão (| col1 | col2 |) — boa para leitura humana e
         útil quando o LLM precisa preservar alinhamento de colunas.
      2) Seção "Fatos por linha:" — uma linha auto-contida por registro, no
         formato `- col1=v1; col2=v2; ...`. Esse formato é o mesmo gerado por
         `ProductIngestor._table_to_markdown` e é o que o embedding/RAG usa
         durante a indexação. Reutilizá-lo na saída para o agente garante que
         o agente veja os MESMOS fatos que casaram na busca semântica, sem
         perda na conversão.

    Esta função NÃO trunca — quem chama decide o cap (ver `truncate_at_line_boundary`).
    Retorna None se o input não for JSON tabular válido.
    """
    if not raw_content or not raw_content.strip().startswith("{"):
        return None

    try:
        data = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    headers = data.get("headers", []) or []
    rows = data.get("rows", []) or []

    if not rows:
        return None

    out_lines = []

    if headers:
        clean_headers = [str(h).strip() or f"col{i+1}" for i, h in enumerate(headers)]
        out_lines.append("| " + " | ".join(clean_headers) + " |")
        out_lines.append("| " + " | ".join(["---"] * len(clean_headers)) + " |")
        for row in rows:
            if not isinstance(row, list):
                continue
            cells = [str(c).strip() if c is not None else "" for c in row]
            while len(cells) < len(clean_headers):
                cells.append("")
            out_lines.append("| " + " | ".join(cells[: len(clean_headers)]) + " |")

        out_lines.append("")
        out_lines.append("Fatos por linha:")
        for row in rows:
            if not isinstance(row, list):
                continue
            facts = []
            for i, cell in enumerate(row):
                if i < len(clean_headers) and cell not in (None, "") and str(cell).strip():
                    facts.append(f"{clean_headers[i]}={cell}")
            if facts:
                out_lines.append("- " + "; ".join(facts))
    else:
        # Sem headers — degrade graceful: serializa cada linha como pipe-separated.
        for row in rows:
            if not isinstance(row, list):
                continue
            non_empty = [str(c) for c in row if c not in (None, "") and str(c).strip()]
            if non_empty:
                out_lines.append(" | ".join(non_empty))

    return "\n".join(out_lines).strip() if out_lines else None


def truncate_at_line_boundary(content: str, max_chars: int) -> str:
    """
    Trunca `content` em no máximo `max_chars`, mas SEMPRE em um boundary de linha
    (`\\n`) — nunca corta no meio de uma linha. Para tabelas/listas, isso evita
    que a última linha mostrada apareça com um valor cortado tipo "MANA1" em vez
    de "MANA11".

    Se o truncamento ocorre, anexa um marcador indicando quantas linhas foram
    omitidas, para que o agente saiba que existe mais conteúdo e possa pedir
    refinamento se necessário.
    """
    if max_chars <= 0 or len(content) <= max_chars:
        return content

    head = content[:max_chars]
    last_nl = head.rfind("\n")
    if last_nl > 0:
        truncated = head[:last_nl]
    else:
        # Não há quebra de linha no head — fallback para corte simples.
        truncated = head

    omitted_count = content[len(truncated):].count("\n") + (
        1 if content[len(truncated):].strip() else 0
    )
    if omitted_count > 0:
        truncated = (
            truncated.rstrip()
            + f"\n[…conteúdo truncado — aproximadamente {omitted_count} linha(s) adicional(is) omitida(s)]"
        )
    return truncated


def get_rich_content(
    content_block_content: str,
    fallback_content: str,
    max_chars: int = DEFAULT_MAX_CHARS_TEXT,
    block_type: Optional[str] = None,
) -> str:
    """
    Retorna conteúdo rico para o contexto do modelo.

    Comportamento por tipo de bloco:
      - TABLE/FINANCIAL_TABLE: usa `format_tabular_content_rich` (Markdown +
        Fatos por linha) e respeita um cap default mais generoso de 4000 chars,
        truncando em boundary de linha. Se o caller passar um `max_chars` MENOR
        que `DEFAULT_MAX_CHARS_TABLE`, usamos `max(max_chars, DEFAULT_MAX_CHARS_TABLE)`
        — porque o caller típico (agent_tools) usa 600 chars, suficiente para
        texto mas hostil a tabelas. Se o caller passar EXPLICITAMENTE algo
        maior que o default de tabela, respeitamos.
      - Outros tipos (TEXT, CHART, etc.): mantém comportamento atual — tenta
        format_tabular_content legado primeiro (caso o block_type esteja errado/
        ausente mas o conteúdo seja JSON tabular), depois texto cru.

    O parâmetro `block_type` é opcional para retrocompat com chamadores antigos
    que ainda não foram atualizados.
    """
    is_table = (block_type or "").lower() in TABLE_BLOCK_TYPES

    if is_table:
        formatted = format_tabular_content_rich(content_block_content)
        if formatted:
            effective_max = max(max_chars, DEFAULT_MAX_CHARS_TABLE)
            return truncate_at_line_boundary(formatted, effective_max)
        # Bloco marcado como table mas content não é JSON válido — fallback para texto.

    # Path legado: detecta JSON tabular mesmo sem block_type, usa formato simples.
    formatted = format_tabular_content(content_block_content)
    if formatted:
        # Mesmo no path legado, se o conteúdo aparenta ser tabular, tentamos
        # ampliar o cap para não cortar pelo meio. Heurística: se tem >= 3 linhas,
        # provavelmente é tabela.
        if formatted.count("\n") >= 2:
            effective_max = max(max_chars, DEFAULT_MAX_CHARS_TABLE)
            return truncate_at_line_boundary(formatted, effective_max)
        return formatted[:max_chars]

    if content_block_content and not content_block_content.strip().startswith("[CONTEXTO GLOBAL]"):
        return content_block_content[:max_chars]

    return (fallback_content or "")[:max_chars]
