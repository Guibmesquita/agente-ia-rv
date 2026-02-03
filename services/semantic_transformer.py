"""
Serviço de transformação semântica para o CMS de Produtos.
Implementa a arquitetura de 3 camadas:

1. Extração Técnica (JSON bruto do GPT-4 Vision)
2. Modelo Semântico Normalizado (hierarquia editável pelo usuário)
3. Camada Vetorial/Indexação (chunks narrativos para IA)
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple


FINANCIAL_PRODUCT_SCHEMA = {
    "hierarchy": ["classe", "gestora", "fundo"],
    "primary_identifier": "ticker",
    "key_attributes": [
        "ticker", "veiculo", "publico_alvo", "oferta_base", "reservas",
        "liquidacao_oferta", "objetivo_retorno", "prazo_alvo", "duracao_estimada",
        "distribuicao_rendimentos", "tributacao", "investimento_minimo",
        "fee_topo", "repasse_adm", "repasse_pfee", "roa_total"
    ],
    "aliases": {
        "classe": ["classe", "class", "category", "categoria"],
        "gestora": ["gestora", "gestora/corretora", "manager", "asset manager", "asset"],
        "fundo": ["fundo", "fund", "nome do fundo", "fund name"],
        "ticker": ["ticker", "codigo", "code", "símbolo", "symbol"],
        "veiculo": ["veículo", "veiculo", "vehicle", "tipo", "type", "fii cetip", "instrumento"],
        "publico_alvo": ["público - alvo", "público alvo", "público-alvo", "target", "publico"],
        "oferta_base": ["oferta base", "oferta base (r$ mm)", "volume", "size"],
        "reservas": ["reservas", "reserves", "período reservas"],
        "liquidacao_oferta": ["liquidação oferta", "liquidacao", "settlement"],
        "objetivo_retorno": ["objetivo de retorno", "objetivo retorno", "retorno alvo", "target return"],
        "prazo_alvo": ["prazo alvo", "prazo", "duration", "term"],
        "duracao_estimada": ["duração estimada", "duration estimated", "prazo estimado"],
        "distribuicao_rendimentos": ["distribuição de rendimentos", "distribuição", "distribution"],
        "tributacao": ["tributação de rendimentos", "tributação", "taxation", "tax"],
        "tributacao_ganho_capital": ["tributação ganho de capital", "ganho capital", "capital gain tax"],
        "investimento_minimo": ["investimento min.", "investimento mínimo", "min investment"],
        "fee_topo": ["fee topo", "fee top", "upfront fee"],
        "repasse_adm": ["repasse adm", "admin fee", "taxa adm"],
        "repasse_pfee": ["repasse pfee", "performance fee", "pfee"],
        "roa_total": ["roa total est*", "roa total", "total roa"],
        "alocacao_carteira": ["alocação carteira xp", "alocação", "allocation"]
    }
}


def normalize_header(header: str) -> str:
    """Normaliza um cabeçalho para o nome padronizado."""
    header_lower = header.lower().strip()
    
    for normalized, aliases in FINANCIAL_PRODUCT_SCHEMA["aliases"].items():
        for alias in aliases:
            if alias.lower() == header_lower or alias.lower() in header_lower:
                return normalized
    
    clean = re.sub(r'[^a-z0-9]+', '_', header_lower)
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean if clean else "unknown"


def parse_table_to_semantic(table_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converte JSON de tabela em modelo semântico hierárquico.
    
    Input: {"headers": [...], "rows": [[...], ...]}
    Output: {
        "type": "product_table",
        "hierarchy": ["classe", "gestora", "fundo"],
        "products": [
            {
                "classe": "PR+",
                "gestora": "TG Core",
                "fundo": "ALIAR",
                "ticker": "ALIAR11",
                "attributes": {
                    "veiculo": "FII Cetip Prazo Determinado",
                    "prazo_alvo": "7 anos",
                    ...
                }
            },
            ...
        ],
        "headers_map": {"Classe": "classe", ...}
    }
    """
    if not table_data:
        return {"type": "empty", "products": []}
    
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])
    
    if not headers or not rows:
        if isinstance(table_data, list):
            if len(table_data) > 0 and isinstance(table_data[0], dict):
                headers = list(table_data[0].keys())
                rows = [list(item.values()) for item in table_data]
            else:
                return {"type": "raw_list", "items": table_data}
    
    headers_map = {}
    for h in headers:
        normalized = normalize_header(h)
        headers_map[h] = normalized
    
    products = []
    for row in rows:
        if len(row) != len(headers):
            continue
        
        product = {"attributes": {}}
        
        for i, (header, value) in enumerate(zip(headers, row)):
            normalized = headers_map.get(header, f"col_{i}")
            value_str = str(value).strip() if value else ""
            
            if normalized in FINANCIAL_PRODUCT_SCHEMA["hierarchy"]:
                product[normalized] = value_str
            elif normalized == FINANCIAL_PRODUCT_SCHEMA["primary_identifier"]:
                product[normalized] = value_str
            else:
                product["attributes"][normalized] = value_str
        
        products.append(product)
    
    return {
        "type": "product_table",
        "hierarchy": FINANCIAL_PRODUCT_SCHEMA["hierarchy"],
        "primary_identifier": FINANCIAL_PRODUCT_SCHEMA["primary_identifier"],
        "products": products,
        "headers_map": headers_map,
        "original_headers": headers
    }


def semantic_to_display_text(semantic_model: Dict[str, Any]) -> str:
    """
    Converte modelo semântico em texto hierárquico para exibição.
    
    Output:
    1. Classe: PR+
       1.1 Gestora: TG Core
           1.1.1 Fundo: ALIAR
                 Ticker: ALIAR11
                 Veículo: FII Cetip Prazo Determinado
                 Prazo Alvo: 7 anos
                 ...
    """
    if semantic_model.get("type") == "empty":
        return "(Sem dados)"
    
    if semantic_model.get("type") == "raw_list":
        return "\n".join([f"• {item}" for item in semantic_model.get("items", [])])
    
    products = semantic_model.get("products", [])
    if not products:
        return "(Sem produtos)"
    
    hierarchy = semantic_model.get("hierarchy", ["classe", "gestora", "fundo"])
    
    grouped = {}
    for product in products:
        key1 = product.get(hierarchy[0], "N/A") if len(hierarchy) > 0 else "Geral"
        key2 = product.get(hierarchy[1], "N/A") if len(hierarchy) > 1 else "Geral"
        key3 = product.get(hierarchy[2], "N/A") if len(hierarchy) > 2 else None
        
        if key1 not in grouped:
            grouped[key1] = {}
        if key2 not in grouped[key1]:
            grouped[key1][key2] = []
        grouped[key1][key2].append(product)
    
    lines = []
    level1_idx = 0
    
    for class_name, gestoras in grouped.items():
        level1_idx += 1
        lines.append(f"{level1_idx}. {hierarchy[0].title()}: {class_name}")
        
        level2_idx = 0
        for gestora_name, products_list in gestoras.items():
            level2_idx += 1
            lines.append(f"   {level1_idx}.{level2_idx} {hierarchy[1].title()}: {gestora_name}")
            
            for product in products_list:
                level3_name = product.get(hierarchy[2], None) if len(hierarchy) > 2 else None
                
                if level3_name:
                    lines.append(f"       • {hierarchy[2].title()}: {level3_name}")
                
                ticker = product.get("ticker")
                if ticker:
                    lines.append(f"         Ticker: {ticker}")
                
                attrs = product.get("attributes", {})
                for attr_key, attr_value in attrs.items():
                    display_name = attr_key.replace("_", " ").title()
                    display_value = attr_value.strip() if attr_value else "—"
                    lines.append(f"         {display_name}: {display_value}")
                
                lines.append("")
    
    return "\n".join(lines)


def generate_narrative_chunks(semantic_model: Dict[str, Any], material_title: str = "") -> List[Dict[str, Any]]:
    """
    Gera chunks narrativos para indexação vetorial.
    
    Cada produto vira um chunk narrativo como:
    "O fundo TGPR PR+, da gestora TG Core, é um FII Cetip de prazo determinado,
     com estratégia pré-fixada, voltado ao público geral, com objetivo de retorno
     de 15% ao ano, prazo alvo de 7 anos e distribuição mensal."
    """
    chunks = []
    
    if semantic_model.get("type") != "product_table":
        return chunks
    
    products = semantic_model.get("products", [])
    
    for i, product in enumerate(products):
        classe = product.get("classe", "")
        gestora = product.get("gestora", "")
        fundo = product.get("fundo", "")
        ticker = product.get("ticker", "")
        attrs = product.get("attributes", {})
        
        veiculo = attrs.get("veiculo", "")
        publico = attrs.get("publico_alvo", "")
        objetivo_retorno = attrs.get("objetivo_retorno", "")
        prazo_alvo = attrs.get("prazo_alvo", "")
        distribuicao = attrs.get("distribuicao_rendimentos", "")
        oferta_base = attrs.get("oferta_base", "")
        
        narrative_parts = []
        
        if fundo or ticker:
            identity = f"O fundo {fundo}" if fundo else f"O produto {ticker}"
            if ticker and fundo:
                identity = f"O fundo {fundo} ({ticker})"
            narrative_parts.append(identity)
        
        if gestora:
            narrative_parts.append(f"da gestora {gestora}")
        
        if classe:
            narrative_parts.append(f"classe {classe}")
        
        if veiculo:
            narrative_parts.append(f"é um {veiculo}")
        
        if publico:
            narrative_parts.append(f"voltado ao público {publico}")
        
        if objetivo_retorno:
            narrative_parts.append(f"com objetivo de retorno de {objetivo_retorno}")
        
        if prazo_alvo:
            narrative_parts.append(f"prazo alvo de {prazo_alvo}")
        
        if distribuicao:
            narrative_parts.append(f"distribuição {distribuicao}")
        
        if oferta_base:
            narrative_parts.append(f"oferta base de R$ {oferta_base}")
        
        if len(narrative_parts) >= 2:
            narrative = ", ".join(narrative_parts[:2])
            if len(narrative_parts) > 2:
                narrative += ", " + ", ".join(narrative_parts[2:])
            narrative = narrative.replace("  ", " ").strip()
            if not narrative.endswith("."):
                narrative += "."
            
            chunks.append({
                "text": narrative,
                "metadata": {
                    "chunk_type": "product_narrative",
                    "classe": classe,
                    "gestora": gestora,
                    "fundo": fundo,
                    "ticker": ticker,
                    "source": material_title,
                    "product_index": i
                }
            })
        
        detailed_parts = []
        for attr_key, attr_value in attrs.items():
            if attr_value and attr_value.strip() and attr_value.lower() not in ["n/a", "na", "-", ""]:
                display_name = attr_key.replace("_", " ")
                detailed_parts.append(f"{display_name}: {attr_value}")
        
        if detailed_parts and (fundo or ticker):
            header = f"Detalhes de {fundo or ticker}"
            if gestora:
                header += f" ({gestora})"
            detail_text = f"{header}. " + "; ".join(detailed_parts) + "."
            
            chunks.append({
                "text": detail_text,
                "metadata": {
                    "chunk_type": "product_details",
                    "classe": classe,
                    "gestora": gestora,
                    "fundo": fundo,
                    "ticker": ticker,
                    "source": material_title,
                    "product_index": i
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
