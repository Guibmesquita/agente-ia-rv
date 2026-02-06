"""
Script para enriquecer chunks existentes no ChromaDB com metadados semânticos.

Para cada chunk sem metadados semânticos (topic, concepts), usa GPT-4o-mini para:
1. Classificar o tema principal (topic)
2. Extrair conceitos financeiros relevantes (concepts)
3. Atualizar os metadados no ChromaDB

Uso:
    python scripts/enrich_chunks.py [--dry-run] [--batch-size 20] [--limit 100]
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI


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


def enrich_chunks(dry_run=False, batch_size=20, limit=None):
    from services.vector_store import get_vector_store
    
    vs = get_vector_store()
    if not vs or not vs.collection:
        print("Erro: VectorStore não inicializado")
        return
    
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    if not client:
        print("Erro: OPENAI_API_KEY não configurada")
        return
    
    all_docs = vs.collection.get(include=['documents', 'metadatas'])
    
    if not all_docs or not all_docs['ids']:
        print("Nenhum documento encontrado no ChromaDB")
        return
    
    total = len(all_docs['ids'])
    print(f"Total de chunks no ChromaDB: {total}")
    
    chunks_to_enrich = []
    already_enriched = 0
    
    for i in range(total):
        metadata = all_docs['metadatas'][i] if all_docs['metadatas'] else {}
        
        if metadata.get('topic') and metadata.get('concepts'):
            already_enriched += 1
            continue
        
        chunks_to_enrich.append({
            'index': i,
            'id': all_docs['ids'][i],
            'document': all_docs['documents'][i] if all_docs['documents'] else "",
            'metadata': metadata
        })
    
    print(f"Já enriquecidos: {already_enriched}")
    print(f"A enriquecer: {len(chunks_to_enrich)}")
    
    if limit:
        chunks_to_enrich = chunks_to_enrich[:limit]
        print(f"Limitado a: {len(chunks_to_enrich)} chunks")
    
    if not chunks_to_enrich:
        print("Nada a fazer!")
        return
    
    if dry_run:
        print("\n=== DRY RUN - Mostrando primeiro chunk ===")
        chunk = chunks_to_enrich[0]
        content_preview = chunk['document'][:300] if chunk['document'] else "N/A"
        print(f"ID: {chunk['id']}")
        print(f"Produto: {chunk['metadata'].get('product_name', 'N/A')} ({chunk['metadata'].get('product_ticker', 'N/A')})")
        print(f"Conteúdo: {content_preview}...")
        
        result = classify_chunk(client, chunk)
        if result:
            print(f"\nResultado GPT:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    
    enriched_count = 0
    errors = 0
    
    for batch_start in range(0, len(chunks_to_enrich), batch_size):
        batch = chunks_to_enrich[batch_start:batch_start + batch_size]
        print(f"\n--- Batch {batch_start // batch_size + 1} ({batch_start + 1}-{batch_start + len(batch)}/{len(chunks_to_enrich)}) ---")
        
        for chunk in batch:
            try:
                result = classify_chunk(client, chunk)
                
                if result:
                    updated_metadata = dict(chunk['metadata'])
                    updated_metadata['topic'] = result.get('topic', 'geral')
                    updated_metadata['concepts'] = json.dumps(result.get('concepts', []))
                    if result.get('summary'):
                        updated_metadata['chunk_summary'] = result['summary'][:200]
                    
                    vs.collection.update(
                        ids=[chunk['id']],
                        metadatas=[updated_metadata]
                    )
                    
                    enriched_count += 1
                    ticker = chunk['metadata'].get('product_ticker', '?')
                    topic = result.get('topic', '?')
                    print(f"  ✓ {chunk['id'][:30]}... [{ticker}] → topic={topic}")
                else:
                    errors += 1
                    print(f"  ✗ {chunk['id'][:30]}... - GPT retornou vazio")
                    
            except Exception as e:
                errors += 1
                print(f"  ✗ {chunk['id'][:30]}... - Erro: {e}")
        
        if batch_start + batch_size < len(chunks_to_enrich):
            time.sleep(1)
    
    print(f"\n=== Resultado ===")
    print(f"Enriquecidos: {enriched_count}")
    print(f"Erros: {errors}")
    print(f"Total processado: {enriched_count + errors}")


def classify_chunk(client, chunk):
    content = chunk['document']
    if not content:
        return None
    
    if "---" in content:
        parts = content.split("---", 1)
        if len(parts) > 1:
            content = parts[1]
    
    content = content[:2000]
    
    metadata = chunk['metadata']
    prompt = TOPIC_CLASSIFICATION_PROMPT.format(
        content=content,
        product_name=metadata.get('product_name', 'N/A'),
        product_ticker=metadata.get('product_ticker', 'N/A'),
        block_type=metadata.get('block_type', 'N/A'),
        material_type=metadata.get('material_type', 'N/A')
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Você é um analista financeiro especializado em classificação de documentos de Renda Variável. Responda APENAS com JSON válido."},
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
        
        valid_topics = ["estrategia", "composicao", "performance", "dividendos", "risco", "mercado", "operacional", "perspectivas", "derivativos", "geral"]
        if result.get('topic') not in valid_topics:
            result['topic'] = 'geral'
        
        if not isinstance(result.get('concepts'), list):
            result['concepts'] = []
        result['concepts'] = result['concepts'][:5]
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"    JSON inválido do GPT: {e}")
        return None
    except Exception as e:
        print(f"    Erro GPT: {e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enriquecer chunks do ChromaDB com metadados semânticos")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostrar o que seria feito")
    parser.add_argument("--batch-size", type=int, default=20, help="Tamanho do batch (default: 20)")
    parser.add_argument("--limit", type=int, default=None, help="Limitar número de chunks a processar")
    
    args = parser.parse_args()
    enrich_chunks(dry_run=args.dry_run, batch_size=args.batch_size, limit=args.limit)
