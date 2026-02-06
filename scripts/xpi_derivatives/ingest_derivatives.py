"""
Script de ingestão das Estruturas de Derivativos XPI.

Executa o pipeline completo:
1. Baixa os PDFs das lâminas técnicas
2. Converte páginas em imagens e extrai gráficos de payoff
3. Processa cada PDF via GPT-4 Vision para extrair conteúdo textual
4. Ingere todo o conteúdo na base de conhecimento ChromaDB
   - Nível 1: Conteúdo geral sobre Produtos Estruturados
   - Nível 2: Contexto de cada aba e estratégia  
   - Nível 3: Cada estrutura individual (descrição contextual + conteúdo do PDF)

Uso:
    python scripts/xpi_derivatives/ingest_derivatives.py [--skip-download] [--skip-vision] [--only-structure SLUG]
"""

import os
import sys
import json
import uuid
import base64
import io
import argparse
import time
import httpx
from pathlib import Path
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from openai import OpenAI
from pdf2image import convert_from_path
from PIL import Image

from core.config import get_settings
from services.vector_store import get_vector_store
from services.chunk_enrichment import enrich_metadata
from scripts.xpi_derivatives.derivatives_dataset import GENERAL_CONTENT, TABS, get_all_structures

settings = get_settings()

PDF_DIR = os.path.join(os.path.dirname(__file__), "pdfs")
DIAGRAMS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static", "derivatives_diagrams")

os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(DIAGRAMS_DIR, exist_ok=True)

SKIP_ENRICHMENT = False


def safe_enrich(metadata: dict, content: str, product_name: str, product_ticker: str = "",
                block_type: str = "texto", material_type: str = "lamina_tecnica") -> dict:
    """Enriquece metadata se SKIP_ENRICHMENT for False, senão usa defaults."""
    if SKIP_ENRICHMENT:
        metadata["topic"] = "derivativos"
        metadata["concepts"] = json.dumps(["derivativos", "opcoes", "hedge", "estruturas"])
        return metadata
    
    try:
        return enrich_metadata(
            metadata=metadata,
            content=content,
            product_name=product_name,
            product_ticker=product_ticker,
            block_type=block_type,
            material_type=material_type
        )
    except Exception as e:
        print(f"    Aviso: enriquecimento falhou: {e}")
        metadata["topic"] = "derivativos"
        metadata["concepts"] = json.dumps(["derivativos", "opcoes", "hedge"])
        return metadata


def download_pdfs(structures: List[Dict], force: bool = False) -> Dict[str, str]:
    """Baixa os PDFs das lâminas técnicas."""
    results = {}
    
    for s in structures:
        slug = s["slug"]
        pdf_url = s["pdf_url"]
        pdf_path = os.path.join(PDF_DIR, f"{slug}.pdf")
        
        if os.path.exists(pdf_path) and not force:
            print(f"  [SKIP] {slug}.pdf já existe")
            results[slug] = pdf_path
            continue
        
        try:
            print(f"  [DOWNLOAD] {s['name']}...")
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(pdf_url)
                if response.status_code == 200:
                    with open(pdf_path, "wb") as f:
                        f.write(response.content)
                    results[slug] = pdf_path
                    print(f"    OK ({len(response.content) / 1024:.1f} KB)")
                else:
                    print(f"    ERRO: HTTP {response.status_code}")
        except Exception as e:
            print(f"    ERRO: {e}")
        
        time.sleep(0.5)
    
    return results


def extract_diagrams(structures: List[Dict], pdf_paths: Dict[str, str]) -> Dict[str, str]:
    """Extrai gráficos de payoff dos PDFs como imagens."""
    diagram_paths = {}
    
    for s in structures:
        slug = s["slug"]
        pdf_path = pdf_paths.get(slug)
        if not pdf_path or not os.path.exists(pdf_path):
            continue
        
        diagram_path = os.path.join(DIAGRAMS_DIR, f"{slug}.png")
        if os.path.exists(diagram_path):
            print(f"  [SKIP] {slug}.png já existe")
            diagram_paths[slug] = diagram_path
            continue
        
        try:
            print(f"  [EXTRACT] {s['name']}...")
            images = convert_from_path(pdf_path, dpi=200)
            
            if len(images) >= 1:
                best_image = images[0]
                if len(images) > 1:
                    best_image = images[0]
                
                best_image.save(diagram_path, "PNG", quality=95)
                diagram_paths[slug] = diagram_path
                print(f"    OK (página 1 salva como diagrama)")
        except Exception as e:
            print(f"    ERRO: {e}")
    
    return diagram_paths


def process_pdf_with_vision(pdf_path: str, structure_name: str, client: OpenAI) -> str:
    """Processa um PDF via GPT-4 Vision e extrai conteúdo textual técnico."""
    try:
        images = convert_from_path(pdf_path, dpi=150)
    except Exception as e:
        print(f"    ERRO ao converter PDF: {e}")
        return ""
    
    all_content = []
    
    for i, image in enumerate(images):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        b64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        prompt = f"""Analise esta página da lâmina técnica da estrutura de derivativos "{structure_name}" da XPI.

INSTRUÇÕES:
1. Extraia TODO o conteúdo textual da página de forma detalhada e precisa.
2. Para GRÁFICOS de payoff/resultado:
   - Descreva detalhadamente o gráfico: eixos, cenários, zonas de lucro e prejuízo
   - Identifique os pontos-chave: strikes, barreiras, breakeven, ganho máximo, perda máxima
   - Descreva o formato da curva (linear, côncava, com caps/floors)
3. Para TABELAS ou cenários numéricos:
   - Extraia todos os dados exatamente como apresentados
4. Inclua todos os disclaimers, condições e observações
5. Identifique os componentes da estrutura (quais opções compra/vende, strikes, etc.)

IMPORTANTE: Seja extremamente detalhado sobre o FUNCIONAMENTO CONCEITUAL da estrutura.
O objetivo é que um assessor financeiro consiga explicar a estrutura para um cliente usando apenas este texto.

Formato de saída: texto livre, organizado por seções claras."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}", "detail": "high"}}
                    ]
                }],
                max_tokens=4000,
                temperature=0.1
            )
            page_content = response.choices[0].message.content
            all_content.append(f"--- Página {i+1} ---\n{page_content}")
            print(f"    Página {i+1}/{len(images)} processada")
        except Exception as e:
            print(f"    ERRO na página {i+1}: {e}")
            time.sleep(2)
    
    return "\n\n".join(all_content)


def build_global_context(structure: Dict) -> str:
    """Constrói o contexto global para um chunk de estrutura de derivativos."""
    parts = ["[CONTEXTO GLOBAL]"]
    parts.append(f"Produto: {structure['name']}")
    parts.append(f"Categoria: Produtos Estruturados - Derivativos")
    parts.append(f"Aba: {structure['tab']} - {structure['tab_description']}")
    parts.append(f"Estratégia: {structure['strategy']}")
    parts.append(f"Tipo: lâmina técnica de derivativos")
    parts.append(f"Fonte: XPI Investimentos")
    return "\n".join(parts)


def ingest_general_content(vector_store) -> int:
    """Ingere o conteúdo geral sobre Produtos Estruturados."""
    count = 0
    
    for section in GENERAL_CONTENT["sections"]:
        chunk_id = f"derivatives_general_{uuid.uuid4().hex[:8]}"
        
        context = "[CONTEXTO GLOBAL]\nCategoria: Produtos Estruturados - Derivativos\nTipo: conteúdo geral introdutório\nFonte: XPI Investimentos"
        text = f"{context}\n\n{section['title']}\n\n{section['content']}"
        
        metadata = {
            "source": "XPI - Produtos Estruturados",
            "title": section["title"],
            "type": "derivatives_general",
            "block_type": "texto",
            "product_name": "Produtos Estruturados XPI",
            "product_ticker": "",
            "gestora": "XPI",
            "category": "Derivativos",
            "material_type": "lamina_tecnica",
            "publish_status": "publicado"
        }
        
        metadata = safe_enrich(metadata, section["content"], "Produtos Estruturados XPI")
        
        vector_store.add_document(doc_id=chunk_id, text=text, metadata=metadata)
        count += 1
        print(f"  [INDEXED] Geral: {section['title']}")
    
    return count


def ingest_tab_content(vector_store) -> int:
    """Ingere o conteúdo de cada aba e estratégia."""
    count = 0
    
    for tab in TABS:
        chunk_id = f"derivatives_tab_{tab['name'].lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}"
        
        strategies_text = "\n".join([
            f"- {s['name']}: {s['description']}" 
            for s in tab["strategies"]
        ])
        
        structures_text = "\n".join([
            f"  • {struct['name']}: {struct['description'][:150]}..."
            for s in tab["strategies"]
            for struct in s["structures"]
        ])
        
        text = (
            f"[CONTEXTO GLOBAL]\n"
            f"Categoria: Produtos Estruturados - Derivativos\n"
            f"Aba: {tab['name']}\n"
            f"Tipo: visão geral da categoria\n"
            f"Fonte: XPI Investimentos\n\n"
            f"Aba: {tab['name']} - Estratégias Disponíveis\n\n"
            f"{tab['description']}\n\n"
            f"Estratégias disponíveis nesta categoria:\n{strategies_text}\n\n"
            f"Estruturas:\n{structures_text}"
        )
        
        metadata = {
            "source": f"XPI - {tab['name']}",
            "title": f"Derivativos - Aba {tab['name']}",
            "type": "derivatives_tab",
            "block_type": "texto",
            "product_name": f"Derivativos - {tab['name']}",
            "product_ticker": "",
            "gestora": "XPI",
            "category": "Derivativos",
            "material_type": "lamina_tecnica",
            "publish_status": "publicado",
            "tab": tab["name"]
        }
        
        metadata = safe_enrich(metadata, text, f"Derivativos - {tab['name']}")
        
        vector_store.add_document(doc_id=chunk_id, text=text, metadata=metadata)
        count += 1
        print(f"  [INDEXED] Aba: {tab['name']}")
    
    return count


def ingest_structure_content(
    structure: Dict,
    pdf_content: str,
    diagram_path: Optional[str],
    vector_store
) -> int:
    """Ingere o conteúdo de uma estrutura individual."""
    count = 0
    global_context = build_global_context(structure)
    
    context_text = (
        f"{global_context}\n\n"
        f"Estrutura: {structure['name']}\n\n"
        f"Descrição e Contexto de Uso:\n"
        f"Estratégia: {structure['strategy']} - {structure['strategy_description']}\n\n"
        f"{structure['description']}"
    )
    
    context_metadata = {
        "source": f"XPI - {structure['name']}",
        "title": f"{structure['name']} - Descrição e Contexto",
        "type": "derivatives_structure",
        "block_type": "texto",
        "product_name": structure["name"],
        "product_ticker": "",
        "gestora": "XPI",
        "category": "Derivativos",
        "material_type": "lamina_tecnica",
        "publish_status": "publicado",
        "tab": structure["tab"],
        "strategy": structure["strategy"],
        "structure_slug": structure["slug"]
    }
    
    if diagram_path and os.path.exists(diagram_path):
        context_metadata["diagram_image_path"] = diagram_path
        context_metadata["has_diagram"] = "true"
    
    context_metadata = safe_enrich(context_metadata, context_text, structure["name"])
    
    chunk_id = f"derivatives_struct_{structure['slug']}_{uuid.uuid4().hex[:8]}"
    vector_store.add_document(doc_id=chunk_id, text=context_text, metadata=context_metadata)
    count += 1
    print(f"  [INDEXED] {structure['name']} - Descrição")
    
    if pdf_content:
        content_chunks = split_content(pdf_content, max_chars=3000)
        
        for i, chunk_text in enumerate(content_chunks):
            chunk_full_text = (
                f"{global_context}\n\n"
                f"Estrutura: {structure['name']}\n"
                f"Conteúdo Técnico (Parte {i+1}/{len(content_chunks)}):\n\n"
                f"{chunk_text}"
            )
            
            chunk_metadata = {
                "source": f"XPI - {structure['name']} - Lâmina Técnica",
                "title": f"{structure['name']} - Conteúdo Técnico (Parte {i+1})",
                "type": "derivatives_structure_technical",
                "block_type": "texto",
                "product_name": structure["name"],
                "product_ticker": "",
                "gestora": "XPI",
                "category": "Derivativos",
                "material_type": "lamina_tecnica",
                "publish_status": "publicado",
                "tab": structure["tab"],
                "strategy": structure["strategy"],
                "structure_slug": structure["slug"]
            }
            
            if diagram_path and os.path.exists(diagram_path):
                chunk_metadata["diagram_image_path"] = diagram_path
                chunk_metadata["has_diagram"] = "true"
            
            chunk_metadata = safe_enrich(chunk_metadata, chunk_text, structure["name"])
            
            chunk_id = f"derivatives_tech_{structure['slug']}_{i}_{uuid.uuid4().hex[:8]}"
            vector_store.add_document(doc_id=chunk_id, text=chunk_full_text, metadata=chunk_metadata)
            count += 1
        
        print(f"  [INDEXED] {structure['name']} - {len(content_chunks)} chunks técnicos")
    
    return count


def split_content(text: str, max_chars: int = 3000) -> List[str]:
    """Divide conteúdo longo em chunks menores preservando parágrafos."""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += ("\n\n" if current_chunk else "") + para
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text]


def main():
    parser = argparse.ArgumentParser(description="Ingestão de Estruturas de Derivativos XPI")
    parser.add_argument("--skip-download", action="store_true", help="Pular download dos PDFs")
    parser.add_argument("--skip-vision", action="store_true", help="Pular processamento GPT-4 Vision")
    parser.add_argument("--only-structure", type=str, help="Processar apenas uma estrutura (pelo slug)")
    parser.add_argument("--force-download", action="store_true", help="Forçar re-download dos PDFs")
    parser.add_argument("--skip-enrichment", action="store_true", help="Pular enriquecimento semântico (mais rápido)")
    args = parser.parse_args()
    
    global SKIP_ENRICHMENT
    SKIP_ENRICHMENT = args.skip_enrichment
    
    structures = get_all_structures()
    if args.only_structure:
        structures = [s for s in structures if s["slug"] == args.only_structure]
        if not structures:
            print(f"Estrutura '{args.only_structure}' não encontrada.")
            return
    
    print(f"\n{'='*60}")
    print(f"INGESTÃO DE ESTRUTURAS DE DERIVATIVOS XPI")
    print(f"{'='*60}")
    print(f"Total de estruturas: {len(structures)}")
    
    print(f"\n--- ETAPA 1: Download dos PDFs ---")
    if args.skip_download:
        print("  [SKIP] Download pulado")
        pdf_paths = {}
        for s in structures:
            path = os.path.join(PDF_DIR, f"{s['slug']}.pdf")
            if os.path.exists(path):
                pdf_paths[s["slug"]] = path
    else:
        pdf_paths = download_pdfs(structures, force=args.force_download)
    print(f"  PDFs disponíveis: {len(pdf_paths)}/{len(structures)}")
    
    print(f"\n--- ETAPA 2: Extração de Diagramas ---")
    diagram_paths = extract_diagrams(structures, pdf_paths)
    print(f"  Diagramas extraídos: {len(diagram_paths)}/{len(structures)}")
    
    print(f"\n--- ETAPA 3: Processamento GPT-4 Vision ---")
    openai_client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
    
    vision_results = {}
    cache_dir = os.path.join(os.path.dirname(__file__), "vision_cache")
    os.makedirs(cache_dir, exist_ok=True)
    
    if args.skip_vision:
        print("  [SKIP] Vision pulado - usando cache se disponível")
        for s in structures:
            cache_path = os.path.join(cache_dir, f"{s['slug']}.txt")
            if os.path.exists(cache_path):
                with open(cache_path, "r") as f:
                    vision_results[s["slug"]] = f.read()
    else:
        if not openai_client:
            print("  ERRO: OPENAI_API_KEY não configurada")
            return
        
        for s in structures:
            slug = s["slug"]
            cache_path = os.path.join(cache_dir, f"{slug}.txt")
            
            if os.path.exists(cache_path):
                print(f"  [CACHE] {s['name']}")
                with open(cache_path, "r") as f:
                    vision_results[slug] = f.read()
                continue
            
            pdf_path = pdf_paths.get(slug)
            if not pdf_path:
                print(f"  [SKIP] {s['name']} - PDF não disponível")
                continue
            
            print(f"  [VISION] {s['name']}...")
            content = process_pdf_with_vision(pdf_path, s["name"], openai_client)
            
            if content:
                vision_results[slug] = content
                with open(cache_path, "w") as f:
                    f.write(content)
            
            time.sleep(1)
    
    print(f"  Conteúdo Vision disponível: {len(vision_results)}/{len(structures)}")
    
    print(f"\n--- ETAPA 4: Ingestão na Base de Conhecimento ---")
    vector_store = get_vector_store()
    total_indexed = 0
    
    if not args.only_structure:
        print("\n  >> Ingerindo conteúdo geral...")
        total_indexed += ingest_general_content(vector_store)
        
        print("\n  >> Ingerindo conteúdo por aba...")
        total_indexed += ingest_tab_content(vector_store)
    
    print("\n  >> Ingerindo estruturas individuais...")
    for s in structures:
        pdf_content = vision_results.get(s["slug"], "")
        diagram_path = diagram_paths.get(s["slug"])
        total_indexed += ingest_structure_content(s, pdf_content, diagram_path, vector_store)
    
    print(f"\n{'='*60}")
    print(f"INGESTÃO CONCLUÍDA!")
    print(f"{'='*60}")
    print(f"Total de chunks indexados: {total_indexed}")
    print(f"PDFs processados: {len(pdf_paths)}")
    print(f"Diagramas extraídos: {len(diagram_paths)}")
    print(f"Conteúdos Vision: {len(vision_results)}")
    print(f"\nDiagramas salvos em: {DIAGRAMS_DIR}")


if __name__ == "__main__":
    main()
