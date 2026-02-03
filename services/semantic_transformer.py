"""
Serviço de transformação semântica para o CMS de Produtos.
Implementa a arquitetura de 3 camadas:

1. Extração Técnica (JSON bruto do GPT-4 Vision)
2. Modelo Semântico Normalizado (estrutura genérica para qualquer tabela)
3. Camada Vetorial/Indexação (chunks narrativos para IA)

IMPORTANTE: Este serviço é AGNÓSTICO à estrutura da tabela.
Não assume campos específicos como "classe", "gestora", "fundo".
Cada tabela pode ter colunas e linhas completamente diferentes.
"""
import json
from typing import Dict, Any, List, Tuple


def parse_table_to_semantic(table_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte JSON de tabela em modelo semântico genérico.
    
    Input: {"headers": [...], "rows": [[...], ...]}
    Output: {
        "type": "table",
        "headers": ["Col A", "Col B", "Col C"],
        "rows": [
            {"Col A": "valor1", "Col B": "valor2", "Col C": "valor3"},
            {"Col A": "valor4", "Col B": "valor5", "Col C": "valor6"},
        ],
        "row_count": 2,
        "col_count": 3
    }
    """
    if not table_data:
        return {"type": "empty", "headers": [], "rows": []}
    
    headers = table_data.get("headers", [])
    raw_rows = table_data.get("rows", [])
    
    if not headers and not raw_rows:
        if isinstance(table_data, list):
            if len(table_data) > 0 and isinstance(table_data[0], dict):
                headers = list(table_data[0].keys())
                raw_rows = [list(item.values()) for item in table_data]
            else:
                return {"type": "raw_list", "items": table_data}
    
    rows = []
    for row in raw_rows:
        if len(row) != len(headers):
            continue
        
        row_dict = {}
        for header, value in zip(headers, row):
            row_dict[header] = str(value).strip() if value else ""
        rows.append(row_dict)
    
    return {
        "type": "table",
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "col_count": len(headers)
    }


def semantic_to_display_text(semantic_model: Dict[str, Any]) -> str:
    """
    Converte modelo semântico em texto legível para exibição.
    
    Formato genérico linha por linha:
    
    Linha 1:
      • Coluna A: valor1
      • Coluna B: valor2
      • Coluna C: valor3
    
    Linha 2:
      • Coluna A: valor4
      • Coluna B: valor5
      • Coluna C: valor6
    """
    if semantic_model.get("type") == "empty":
        return "(Sem dados)"
    
    if semantic_model.get("type") == "raw_list":
        items = semantic_model.get("items", [])
        return "\n".join([f"• {item}" for item in items])
    
    rows = semantic_model.get("rows", [])
    headers = semantic_model.get("headers", [])
    
    if not rows:
        return "(Sem dados na tabela)"
    
    lines = []
    
    for i, row in enumerate(rows, start=1):
        lines.append(f"Linha {i}:")
        
        for header in headers:
            value = row.get(header, "")
            display_value = value if value else "—"
            lines.append(f"  • {header}: {display_value}")
        
        lines.append("")
    
    return "\n".join(lines)


def generate_narrative_chunks(semantic_model: Dict[str, Any], material_title: str = "") -> List[Dict[str, Any]]:
    """
    Gera chunks narrativos para indexação vetorial.
    
    Cada linha da tabela vira um chunk com todos os seus dados.
    Formato: "Registro: Coluna A = valor1, Coluna B = valor2, ..."
    """
    chunks = []
    
    if semantic_model.get("type") not in ["table", "product_table"]:
        return chunks
    
    rows = semantic_model.get("rows", [])
    headers = semantic_model.get("headers", [])
    
    for i, row in enumerate(rows):
        parts = []
        for header in headers:
            value = row.get(header, "")
            if value and value.strip() and value.lower() not in ["n/a", "na", "-", ""]:
                parts.append(f"{header}: {value}")
        
        if parts:
            narrative = "Registro: " + ", ".join(parts) + "."
            
            if material_title:
                narrative = f"[{material_title}] " + narrative
            
            chunks.append({
                "text": narrative,
                "metadata": {
                    "chunk_type": "table_row",
                    "source": material_title,
                    "row_index": i,
                    "row_data": row
                }
            })
    
    return chunks


def transform_content_for_display(content: str, block_type: str) -> Tuple[str, Dict[str, Any]]:
    """
    Transforma conteúdo bruto em formato para exibição ao usuário.
    
    Returns:
        (display_text, semantic_model)
    """
    if block_type != "tabela":
        return content, {"type": "text", "content": content}
    
    try:
        table_data = json.loads(content)
    except json.JSONDecodeError:
        return content, {"type": "text", "content": content}
    
    semantic_model = parse_table_to_semantic(table_data)
    display_text = semantic_to_display_text(semantic_model)
    
    return display_text, semantic_model


def transform_semantic_to_indexable(semantic_model: Dict[str, Any], title: str = "") -> str:
    """
    Transforma modelo semântico em texto para indexação vetorial.
    Gera chunks narrativos e retorna texto concatenado.
    """
    chunks = generate_narrative_chunks(semantic_model, title)
    
    if not chunks:
        return semantic_to_display_text(semantic_model)
    
    return "\n\n".join([chunk["text"] for chunk in chunks])
