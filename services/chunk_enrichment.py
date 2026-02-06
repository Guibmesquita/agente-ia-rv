"""
Serviço centralizado de enriquecimento semântico de chunks.

Classifica chunks com topic e concepts via GPT-4o-mini,
cruzando com o glossário de conceitos financeiros.

Usado tanto no pipeline de ingestão (novos chunks) quanto
no script de enriquecimento retroativo (chunks existentes).
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List

from openai import OpenAI

logger = logging.getLogger(__name__)

TOPIC_CLASSIFICATION_PROMPT = """Analise o conteúdo abaixo de um documento financeiro e classifique-o.

CONTEÚDO:
{content}

METADADOS EXISTENTES:
- Produto: {product_name} ({product_ticker})
- Tipo de bloco: {block_type}
- Tipo de material: {material_type}

Retorne um JSON com:
1. "topic": O tema principal do trecho (escolha UM dos temas abaixo):
   - "estrategia": Tese de investimento, filosofia, posicionamento, como o fundo investe
   - "composicao": Carteira, alocação, ativos, exposição, setores, CRIs
   - "performance": Rentabilidade, retorno, valorização, comparativo com benchmark
   - "dividendos": Distribuição, proventos, dividend yield, guidance
   - "risco": Garantias, LTV, inadimplência, vacância, diversificação
   - "mercado": Cotação, liquidez, volume, P/VP, cotistas
   - "operacional": Taxas, regulamento, administrador, dados cadastrais
   - "perspectivas": Outlook, projeções, cenário futuro, comentário do gestor
   - "derivativos": Opções, gregas, estruturas, hedge
   - "geral": Outros temas não listados acima

2. "concepts": Lista de até 5 conceitos financeiros presentes (ex: ["dividend_yield", "cota", "rentabilidade"])
   Use os IDs do glossário: estrategia_investimento, composicao_carteira, dividendo, dividend_yield,
   cota, patrimonio, rentabilidade, cap_rate, vacancia, ltv, garantias, cri, benchmark, guidance,
   perspectivas, resultado_operacional, incorporacao, recebimento_preferencial, diversificacao,
   indexador, duration_conceito, subscricao, liquidez, pvp, taxa_administracao, hedge, etc.

3. "summary": Resumo de 1 frase do conteúdo (max 100 caracteres)

Responda APENAS com o JSON, sem markdown."""

VALID_TOPICS = [
    "estrategia", "composicao", "performance", "dividendos",
    "risco", "mercado", "operacional", "perspectivas",
    "derivativos", "geral"
]

_openai_client = None


def _get_openai_client() -> Optional[OpenAI]:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("[ENRICHMENT] OPENAI_API_KEY não configurada")
            return None
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def classify_chunk_content(
    content: str,
    product_name: str = "N/A",
    product_ticker: str = "N/A",
    block_type: str = "N/A",
    material_type: str = "N/A",
    client: Optional[OpenAI] = None
) -> Optional[Dict[str, Any]]:
    """
    Classifica um chunk de conteúdo com topic e concepts via GPT-4o-mini.
    
    Args:
        content: Texto do chunk a classificar
        product_name: Nome do produto
        product_ticker: Ticker do produto
        block_type: Tipo do bloco (text, table, etc)
        material_type: Tipo do material (relatório gerencial, etc)
        client: Cliente OpenAI opcional (usa singleton se não fornecido)
    
    Returns:
        Dict com keys 'topic', 'concepts', 'summary' ou None em caso de erro
    """
    if not content or not content.strip():
        return None

    openai_client = client or _get_openai_client()
    if not openai_client:
        return None

    clean_content = content
    if "---" in clean_content:
        parts = clean_content.split("---", 1)
        if len(parts) > 1:
            clean_content = parts[1]

    clean_content = clean_content[:2000]

    prompt = TOPIC_CLASSIFICATION_PROMPT.format(
        content=clean_content,
        product_name=product_name,
        product_ticker=product_ticker,
        block_type=block_type,
        material_type=material_type
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Você é um analista financeiro especializado em classificação de documentos de Renda Variável. Responda APENAS com JSON válido."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=300
        )

        result_text = response.choices[0].message.content.strip()

        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text
            if result_text.endswith("```"):
                result_text = result_text[:-3]
            result_text = result_text.strip()

        result = json.loads(result_text)

        if result.get('topic') not in VALID_TOPICS:
            result['topic'] = 'geral'

        if not isinstance(result.get('concepts'), list):
            result['concepts'] = []
        result['concepts'] = result['concepts'][:5]

        return result

    except json.JSONDecodeError as e:
        logger.warning(f"[ENRICHMENT] JSON inválido do GPT: {e}")
        return None
    except Exception as e:
        logger.warning(f"[ENRICHMENT] Erro GPT: {e}")
        return None


def enrich_metadata(
    metadata: Dict[str, Any],
    content: str,
    product_name: str = "N/A",
    product_ticker: str = "N/A",
    block_type: str = "N/A",
    material_type: str = "N/A"
) -> Dict[str, Any]:
    """
    Enriquece um dicionário de metadados com topic, concepts e chunk_summary.
    
    Retorna o metadata atualizado (ou inalterado em caso de falha).
    """
    result = classify_chunk_content(
        content=content,
        product_name=product_name,
        product_ticker=product_ticker,
        block_type=block_type,
        material_type=material_type
    )

    if result:
        metadata['topic'] = result.get('topic', 'geral')
        metadata['concepts'] = json.dumps(result.get('concepts', []))
        if result.get('summary'):
            metadata['chunk_summary'] = result['summary'][:200]
        logger.info(
            f"[ENRICHMENT] Chunk enriquecido: [{product_ticker}] "
            f"topic={metadata['topic']}, concepts={metadata['concepts']}"
        )
    else:
        metadata['topic'] = 'geral'
        metadata['concepts'] = '[]'
        logger.warning(f"[ENRICHMENT] Falha ao classificar chunk de {product_ticker}, usando defaults")

    return metadata
