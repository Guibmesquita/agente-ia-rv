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

from services.chunk_enrichment import classify_chunk_content


def enrich_chunks(dry_run=False, batch_size=20, limit=None):
    from services.vector_store import get_vector_store
    
    vs = get_vector_store()
    if not vs or not vs.collection:
        print("Erro: VectorStore não inicializado")
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
        
        result = classify_chunk_content(
            content=chunk['document'],
            product_name=chunk['metadata'].get('product_name', 'N/A'),
            product_ticker=chunk['metadata'].get('product_ticker', 'N/A'),
            block_type=chunk['metadata'].get('block_type', 'N/A'),
            material_type=chunk['metadata'].get('material_type', 'N/A')
        )
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
                metadata = chunk['metadata']
                result = classify_chunk_content(
                    content=chunk['document'],
                    product_name=metadata.get('product_name', 'N/A'),
                    product_ticker=metadata.get('product_ticker', 'N/A'),
                    block_type=metadata.get('block_type', 'N/A'),
                    material_type=metadata.get('material_type', 'N/A')
                )
                
                if result:
                    updated_metadata = dict(metadata)
                    updated_metadata['topic'] = result.get('topic', 'geral')
                    updated_metadata['concepts'] = json.dumps(result.get('concepts', []))
                    if result.get('summary'):
                        updated_metadata['chunk_summary'] = result['summary'][:200]
                    
                    vs.collection.update(
                        ids=[chunk['id']],
                        metadatas=[updated_metadata]
                    )
                    
                    enriched_count += 1
                    ticker = metadata.get('product_ticker', '?')
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enriquecer chunks do ChromaDB com metadados semânticos")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostrar o que seria feito")
    parser.add_argument("--batch-size", type=int, default=20, help="Tamanho do batch (default: 20)")
    parser.add_argument("--limit", type=int, default=None, help="Limitar número de chunks a processar")
    
    args = parser.parse_args()
    enrich_chunks(dry_run=args.dry_run, batch_size=args.batch_size, limit=args.limit)
