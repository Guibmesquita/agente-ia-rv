"""
Serviço de processamento inteligente de documentos.
Usa GPT-4 Vision para analisar páginas e extrair informações estruturadas.
"""
import base64
import io
import os
import tempfile
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import json

from openai import OpenAI
from pdf2image import convert_from_path, convert_from_bytes
from PIL import Image

from core.config import get_settings

settings = get_settings()


class ContentType(str, Enum):
    TABLE = "table"
    INFOGRAPHIC = "infographic"
    TEXT = "text"
    MIXED = "mixed"
    IMAGE_ONLY = "image_only"


class DocumentProcessor:
    """Processador inteligente de documentos usando GPT-4 Vision."""
    
    def __init__(self):
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def _image_to_base64(self, image: Image.Image, format: str = "PNG") -> str:
        """Converte imagem PIL para base64."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    def _pdf_to_images(self, pdf_path: str = None, pdf_bytes: bytes = None) -> List[Image.Image]:
        """Converte PDF em lista de imagens (uma por página)."""
        if pdf_path:
            return convert_from_path(pdf_path, dpi=150)
        elif pdf_bytes:
            return convert_from_bytes(pdf_bytes, dpi=150)
        return []
    
    def analyze_page(self, image: Image.Image, document_title: str = "") -> Dict[str, Any]:
        """
        Analisa uma página usando GPT-4 Vision.
        Identifica tipo de conteúdo e extrai dados estruturados.
        """
        if not self.client:
            raise ValueError("OpenAI API key não configurada")
        
        base64_image = self._image_to_base64(image)
        
        prompt = f"""Analise esta página do documento "{document_title}" e extraia as informações de forma estruturada.

INSTRUÇÕES:
1. Primeiro, identifique o TIPO de conteúdo principal:
   - "table": Se contém tabelas com dados estruturados
   - "infographic": Se contém gráficos, diagramas ou visualizações
   - "text": Se é principalmente texto corrido
   - "mixed": Se combina vários tipos
   - "image_only": Se é apenas uma imagem sem texto significativo

2. Para TABELAS:
   - Identifique os cabeçalhos das colunas
   - Para cada linha, crie um "fato" completo que associe o item principal com todos os seus atributos
   - Exemplo: Se a tabela tem colunas "Produto | Preço | Categoria" e uma linha "iPhone | R$ 5.000 | Eletrônicos"
   - O fato seria: "iPhone: Preço é R$ 5.000, Categoria é Eletrônicos"

3. Para INFOGRÁFICOS:
   - Descreva o que o gráfico/diagrama representa
   - Extraia números, percentuais e dados chave
   - Crie fatos descritivos sobre as informações visuais

4. Para TEXTO:
   - Extraia os pontos principais como fatos independentes
   - Mantenha o contexto necessário para cada fato

FORMATO DE RESPOSTA (JSON):
{{
    "content_type": "table|infographic|text|mixed|image_only",
    "summary": "Resumo breve do conteúdo da página",
    "facts": [
        "Fato 1 completo e auto-contido",
        "Fato 2 completo e auto-contido",
        ...
    ],
    "raw_data": {{
        "tables": [
            {{
                "headers": ["col1", "col2"],
                "rows": [["val1", "val2"]]
            }}
        ],
        "key_values": {{"chave": "valor"}}
    }}
}}

Responda APENAS com o JSON, sem markdown ou explicações."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4096,
                temperature=0.1
            )
            
            result_text = response.choices[0].message.content.strip()
            
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            
            return json.loads(result_text)
            
        except json.JSONDecodeError as e:
            print(f"[DOC_PROCESSOR] Erro ao parsear JSON: {e}")
            print(f"[DOC_PROCESSOR] Resposta raw: {result_text[:500]}")
            return {
                "content_type": "text",
                "summary": "Erro ao processar página",
                "facts": [],
                "raw_data": {}
            }
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao analisar página: {e}")
            return {
                "content_type": "text",
                "summary": f"Erro: {str(e)}",
                "facts": [],
                "raw_data": {}
            }
    
    def process_pdf(
        self, 
        pdf_path: str = None, 
        pdf_bytes: bytes = None,
        document_title: str = "",
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Processa um PDF completo, analisando cada página.
        
        Args:
            pdf_path: Caminho para o arquivo PDF
            pdf_bytes: Bytes do arquivo PDF
            document_title: Título do documento
            progress_callback: Função chamada a cada página (current, total)
        
        Returns:
            Dict com informações estruturadas de todas as páginas
        """
        images = self._pdf_to_images(pdf_path=pdf_path, pdf_bytes=pdf_bytes)
        
        if not images:
            return {
                "title": document_title,
                "total_pages": 0,
                "pages": [],
                "all_facts": [],
                "error": "Não foi possível converter o PDF em imagens"
            }
        
        total_pages = len(images)
        pages_data = []
        all_facts = []
        
        if progress_callback:
            progress_callback(0, total_pages)
        
        for i, image in enumerate(images):
            print(f"[DOC_PROCESSOR] Processando página {i + 1}/{total_pages}...")
            
            if progress_callback:
                progress_callback(i + 1, total_pages)
            
            page_result = self.analyze_page(image, document_title)
            page_result["page_number"] = i + 1
            pages_data.append(page_result)
            
            for fact in page_result.get("facts", []):
                prefixed_fact = f"[{document_title} - Página {i + 1}] {fact}"
                all_facts.append(prefixed_fact)
        
        return {
            "title": document_title,
            "total_pages": total_pages,
            "pages": pages_data,
            "all_facts": all_facts
        }
    
    def process_image(
        self, 
        image_path: str = None, 
        image_bytes: bytes = None,
        document_title: str = ""
    ) -> Dict[str, Any]:
        """Processa uma imagem única."""
        if image_path:
            image = Image.open(image_path)
        elif image_bytes:
            image = Image.open(io.BytesIO(image_bytes))
        else:
            return {"error": "Nenhuma imagem fornecida"}
        
        result = self.analyze_page(image, document_title)
        result["page_number"] = 1
        
        all_facts = []
        for fact in result.get("facts", []):
            prefixed_fact = f"[{document_title}] {fact}"
            all_facts.append(prefixed_fact)
        
        return {
            "title": document_title,
            "total_pages": 1,
            "pages": [result],
            "all_facts": all_facts
        }
    
    def generate_indexable_chunks(
        self, 
        processed_data: Dict[str, Any],
        include_summary: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Gera chunks otimizados para indexação no vector store.
        Cada fato vira um chunk independente com metadata.
        """
        chunks = []
        title = processed_data.get("title", "Documento")
        
        if include_summary:
            summaries = []
            for page in processed_data.get("pages", []):
                if page.get("summary"):
                    summaries.append(f"Página {page.get('page_number', '?')}: {page['summary']}")
            
            if summaries:
                chunks.append({
                    "content": f"Resumo do documento '{title}':\n" + "\n".join(summaries),
                    "metadata": {
                        "title": title,
                        "type": "summary",
                        "source": title
                    }
                })
        
        for fact in processed_data.get("all_facts", []):
            chunks.append({
                "content": fact,
                "metadata": {
                    "title": title,
                    "type": "fact",
                    "source": title
                }
            })
        
        return chunks


_document_processor = None

def get_document_processor() -> DocumentProcessor:
    """Retorna instância singleton do DocumentProcessor."""
    global _document_processor
    if _document_processor is None:
        _document_processor = DocumentProcessor()
    return _document_processor
