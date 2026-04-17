"""
Serviço de processamento inteligente de documentos.
Usa GPT-4 Vision para analisar páginas e extrair informações estruturadas.
Extração híbrida: texto nativo via PyMuPDF quando disponível, Vision para páginas sem texto.
"""
import base64
import io
import os
import tempfile
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import json

from openai import OpenAI
import fitz
from PIL import Image

from core.config import get_settings
from services.cost_tracker import cost_tracker

settings = get_settings()

NATIVE_TEXT_MIN_CHARS = 100

FINANCIAL_METRIC_COLUMNS = {
    "dy", "d.y.", "dividend yield", "dividendo", "dividendos",
    "p/vp", "pvp", "p/vpa",
    "ltv", "loan to value", "loan-to-value",
    "vpa", "valor patrimonial",
    "patrimônio", "patrimonio", "pl ",
    "cotistas",
    "inadimplência", "inadimplencia",
    "vacância", "vacancia", "vacância física", "vacância financeira",
    "retorno", "rentabilidade", "cdi", "ipca",
    "cap rate",
    "ffo", "ffo/cota",
}


class ContentType(str, Enum):
    TABLE = "table"
    INFOGRAPHIC = "infographic"
    TEXT = "text"
    MIXED = "mixed"
    IMAGE_ONLY = "image_only"


DPI_BY_CONTENT = {
    ContentType.TEXT: 150,
    ContentType.MIXED: 200,
    ContentType.TABLE: 250,
    ContentType.INFOGRAPHIC: 200,
    ContentType.IMAGE_ONLY: 150,
}

DPI_DEFAULT = 150


class DocumentProcessor:
    """Processador inteligente de documentos usando GPT-4 Vision."""
    
    def __init__(self):
        self.client = None
        if settings.OPENAI_API_KEY:
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
    def _extract_page_text_native(self, page) -> str:
        """Extrai texto nativo da página usando PyMuPDF (pdfminer-like).
        Retorna string vazia se a página não tem texto selecionável suficiente."""
        try:
            text = page.get_text("text").strip()
            return text
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao extrair texto nativo: {e}")
            return ""

    def _classify_page_content(self, page) -> ContentType:
        """Pré-classifica o tipo de conteúdo de uma página usando texto nativo do PyMuPDF.
        Usado para determinar o DPI ideal antes de enviar ao Vision."""
        text = page.get_text("text").strip()
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
        
        image_blocks = sum(1 for b in blocks if b.get("type") == 1)
        text_blocks = sum(1 for b in blocks if b.get("type") == 0)
        
        if text_blocks == 0 and image_blocks > 0:
            return ContentType.IMAGE_ONLY
        
        text_lower = text.lower()
        table_indicators = ["|", "\t", "   "]
        table_score = sum(1 for ind in table_indicators if ind in text)
        
        lines = text.split("\n")
        numeric_lines = sum(1 for line in lines if any(c.isdigit() for c in line))
        
        if table_score >= 2 or (len(lines) > 5 and numeric_lines / max(len(lines), 1) > 0.5):
            if image_blocks > 0:
                return ContentType.MIXED
            return ContentType.TABLE
        
        if image_blocks > 0 and text_blocks > 0:
            return ContentType.MIXED
        
        if image_blocks > text_blocks and image_blocks > 0:
            return ContentType.INFOGRAPHIC
        
        return ContentType.TEXT
    
    def _page_to_image(self, page, dpi: int = DPI_DEFAULT) -> Image.Image:
        """Renderiza uma página do PyMuPDF como imagem PIL com DPI específico."""
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    def _image_to_base64(self, image: Image.Image, format: str = "PNG") -> str:
        """Converte imagem PIL para base64."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    def _pdf_to_images(self, pdf_path: str = None, pdf_bytes: bytes = None, dpi: int = 150) -> List[Image.Image]:
        """Converte PDF em lista de imagens (uma por página) usando PyMuPDF."""
        doc = None
        if pdf_path:
            doc = fitz.open(pdf_path)
        elif pdf_bytes:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        if not doc:
            return []
        
        images = []
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        try:
            for page in doc:
                pix = page.get_pixmap(matrix=matrix)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
        finally:
            doc.close()
        return images
    
    def _pdf_page_to_image(self, pdf_path: str, page_num: int, dpi: int = 150) -> Optional[Image.Image]:
        """Converte uma única página do PDF em imagem usando PyMuPDF."""
        doc = fitz.open(pdf_path)
        try:
            if page_num < 1 or page_num > len(doc):
                return None
            page = doc[page_num - 1]
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        finally:
            doc.close()
    
    def analyze_page(self, image: Image.Image, document_title: str = "", page_number: int = 0) -> Dict[str, Any]:
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

2. Para TABELAS (MUITO IMPORTANTE - EXTRAIA TODAS AS LINHAS):
   - Identifique os cabeçalhos das colunas EXATAMENTE como estão escritos
   - EXTRAIA ABSOLUTAMENTE TODAS AS LINHAS da tabela, sem pular nenhuma
   - NÃO resuma, NÃO omita, NÃO agrupe linhas - cada linha da tabela deve virar uma linha no JSON
   - Se a tabela tem 10 linhas, o array "rows" DEVE ter 10 elementos
   - Se a tabela tem 50 linhas, o array "rows" DEVE ter 50 elementos
   - Isso é dados financeiros sensíveis - omitir linhas causa prejuízo ao usuário
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

5. EXTRAÇÃO DE PRODUTOS/ENTIDADES (MUITO IMPORTANTE):
   - Identifique TODOS os nomes de produtos, fundos, ativos ou siglas mencionados na página
   - Inclua variações do nome (ex: "TG Core", "TGRI", "TG RI", etc.)
   - Liste cada produto/entidade único que aparece no conteúdo

6. EXTRAÇÃO AUTOMÁTICA DE TAGS (IMPORTANTE):
   Analise o conteúdo e identifique tags nas 4 categorias abaixo:
   
   a) CONTEXTO DE USO - quando o broker usaria este material:
      Opções: abordagem, fechamento, objecao, follow-up, renovacao, rebalanceamento
   
   b) PERFIL DO CLIENTE - para qual perfil de investidor:
      Opções: conservador, moderado, arrojado, institucional, pf, pj
   
   c) MOMENTO DE MERCADO - em qual cenário é mais relevante:
      Opções: alta, baixa, volatilidade, selic-alta, selic-baixa, dolar-forte
   
   d) TIPO DE INFORMAÇÃO - que tipo de dado contém:
      Opções: indicadores, historico, comparativo, projecao, risco, estrategia

   Selecione APENAS as tags que se aplicam claramente ao conteúdo.
   Se não houver evidência clara, deixe a categoria vazia.

7. IGNORAR ELEMENTOS ESTRUTURAIS DO DOCUMENTO:
   Não extraia como fatos: cabeçalhos de página, rodapés,
   numeração de página, logos, disclaimers legais padrão,
   datas que aparecem apenas como timbre do documento.
   Esses elementos não têm valor para busca de informação.
   Se uma página contém APENAS esses elementos, retorne:
   content_type: "structural_only" e facts: [].
   Regra prática: se o texto seria idêntico em qualquer
   outra página do mesmo documento, ignore-o.

8. MÉTRICAS FINANCEIRAS ESPECÍFICAS (se presentes):
   Extraia indicadores financeiros em `financial_metrics` com valor e data de referência.
   Preencha APENAS os campos que aparecem explicitamente na página.
   Campos disponíveis:
   - dy_monthly: Dividend Yield mensal (ex: "0,75%")
   - dy_annual: Dividend Yield anual (ex: "9,0%")
   - pvp: Preço sobre Valor Patrimonial (ex: "0,98")
   - vpa: Valor Patrimonial por Cota (ex: "R$ 102,50")
   - ltv: Loan-to-Value médio (ex: "62%")
   - patrimonio: Patrimônio líquido (ex: "R$ 1,2 bilhão")
   - num_cotistas: Número de cotistas (ex: "45.000")
   - inadimplencia: Taxa de inadimplência (ex: "1,2%")
   - vacancia: Taxa de vacância (ex: "8,5%")
   - retornos_historicos: objeto {{periodo: retorno}} (ex: {{"1m": "0,75%", "12m": "9,0%"}})
   - composicao_setorial: objeto {{setor: percentual}} (ex: {{"Logística": "45%"}})
   - referencia: Mês/período de referência (ex: "Março 2025")
   Se não houver métricas financeiras claras, omita o campo ou retorne {{}}.

FORMATO DE RESPOSTA (JSON):
{{
    "content_type": "table|infographic|text|mixed|image_only|structural_only",
    "summary": "Resumo breve do conteúdo da página",
    "products_mentioned": ["TGRI", "TG Core", "BTG Pactual", ...],
    "auto_tags": {{
        "contexto": ["abordagem", "objecao"],
        "perfil": ["conservador"],
        "momento": ["selic-alta"],
        "informacao": ["indicadores", "comparativo"]
    }},
    "financial_metrics": {{
        "dy_monthly": "0,75%",
        "pvp": "0,98",
        "referencia": "Março 2025"
    }},
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
                max_tokens=8192,
                temperature=0.1
            )
            try:
                if response.usage:
                    cost_tracker.track_openai_chat(
                        model='gpt-4o',
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        operation='document_vision_extraction',
                        context=f'doc:{document_title}|pg:{page_number}' if document_title else None
                    )
            except Exception:
                pass
            
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
    
    def analyze_page_with_text(self, text: str, document_title: str = "", page_number: int = 0) -> Dict[str, Any]:
        """
        Analisa uma página usando APENAS o texto nativo (sem Vision).
        Mais rápido e barato para páginas com texto selecionável suficiente.
        Retorna o mesmo formato JSON que analyze_page().
        """
        if not self.client:
            raise ValueError("OpenAI API key não configurada")

        prompt = f"""Analise o texto abaixo extraído da página {page_number} do documento "{document_title}" e extraia as informações de forma estruturada.

TEXTO DA PÁGINA:
{text}

INSTRUÇÕES:
1. Identifique o TIPO de conteúdo:
   - "table": tabelas com dados estruturados
   - "text": texto corrido e parágrafos
   - "mixed": combinação de texto e dados
   - "structural_only": apenas cabeçalhos, rodapés, numeração — sem conteúdo útil

2. Para TABELAS: extraia headers e todas as linhas em raw_data.tables. Cada linha da tabela original deve virar uma linha no JSON.

3. Para TEXTO: extraia pontos principais como fatos independentes e auto-contidos.

4. Identifique PRODUTOS/FUNDOS mencionados (tickers, nomes completos, variações).

5. MÉTRICAS FINANCEIRAS (se presentes): preencha apenas campos explícitos:
   - dy_monthly, dy_annual, pvp, vpa, ltv, patrimonio, num_cotistas,
     inadimplencia, vacancia, retornos_historicos, composicao_setorial, referencia.

6. AUTO-TAGS nas categorias:
   - contexto: abordagem, fechamento, objecao, follow-up, renovacao, rebalanceamento
   - perfil: conservador, moderado, arrojado, institucional, pf, pj
   - momento: alta, baixa, volatilidade, selic-alta, selic-baixa, dolar-forte
   - informacao: indicadores, historico, comparativo, projecao, risco, estrategia

7. IGNORAR elementos estruturais (cabeçalhos, rodapés, numeração, disclaimers padrão).

FORMATO DE RESPOSTA (JSON puro, sem markdown):
{{
    "content_type": "table|text|mixed|structural_only",
    "summary": "Resumo breve do conteúdo",
    "products_mentioned": ["TGRI", "TG Core", ...],
    "auto_tags": {{"contexto": [], "perfil": [], "momento": [], "informacao": []}},
    "financial_metrics": {{}},
    "facts": ["Fato 1 auto-contido", "Fato 2 auto-contido", ...],
    "raw_data": {{
        "tables": [{{"headers": ["col1", "col2"], "rows": [["val1", "val2"]]}}],
        "key_values": {{}}
    }}
}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                temperature=0.1
            )
            try:
                if response.usage:
                    cost_tracker.track_openai_chat(
                        model='gpt-4o',
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        operation='document_text_extraction',
                        context=f'doc:{document_title}|pg:{page_number}' if document_title else None
                    )
            except Exception:
                pass

            result_text = response.choices[0].message.content.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            return json.loads(result_text)

        except json.JSONDecodeError as e:
            print(f"[DOC_PROCESSOR] Erro ao parsear JSON (texto nativo): {e}")
            return {"content_type": "text", "summary": "Erro ao processar página", "facts": [], "raw_data": {}}
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao analisar página (texto nativo): {e}")
            return {"content_type": "text", "summary": f"Erro: {str(e)}", "facts": [], "raw_data": {}}

    def _normalize_page_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza o resultado da análise de página.
        Move `financial_metrics` do topo para `raw_data.financial_metrics` de forma padronizada.
        Mantém compatibilidade: consumidores que lêem `raw_data.financial_metrics` sempre encontram os dados.
        """
        fm = result.pop("financial_metrics", None)
        if fm and isinstance(fm, dict) and fm:
            raw_data = result.get("raw_data")
            if not isinstance(raw_data, dict):
                raw_data = {}
                result["raw_data"] = raw_data
            raw_data["financial_metrics"] = fm
        return result

    def analyze_page_hybrid(self, page, pre_content_type, document_title: str = "", page_number: int = 0) -> Dict[str, Any]:
        """
        Estratégia híbrida de extração:
        - Se a página é classificada como TEXT PURO e tem texto nativo suficiente (>NATIVE_TEXT_MIN_CHARS
          chars), usa analyze_page_with_text (GPT-4o texto puro — mais barato e preciso).
        - Para MIXED, TABLE, INFOGRAPHIC e IMAGE_ONLY, usa Vision completo via analyze_page —
          essas páginas podem ter conteúdo visual que o texto nativo não captura.
        Loga qual estratégia foi usada por página.
        """
        native_text = self._extract_page_text_native(page)
        use_native = (
            len(native_text) >= NATIVE_TEXT_MIN_CHARS
            and pre_content_type == ContentType.TEXT
        )

        if use_native:
            print(f"[DOC_PROCESSOR] Página {page_number}: estratégia=TEXTO_NATIVO ({len(native_text)} chars, tipo={pre_content_type.value})")
            result = self.analyze_page_with_text(native_text, document_title, page_number)
            result["extraction_strategy"] = "native_text"
        else:
            dpi = DPI_BY_CONTENT.get(pre_content_type, DPI_DEFAULT)
            image = self._page_to_image(page, dpi=dpi)
            print(f"[DOC_PROCESSOR] Página {page_number}: estratégia=VISION (tipo={pre_content_type.value}, dpi={dpi}, texto={len(native_text)} chars)")
            result = self.analyze_page(image, document_title, page_number)
            result["extraction_strategy"] = "vision"

        return self._normalize_page_result(result)

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
        doc = None
        try:
            if pdf_path:
                doc = fitz.open(pdf_path)
            elif pdf_bytes:
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao abrir PDF: {e}")
        
        if not doc or len(doc) == 0:
            return {
                "title": document_title,
                "total_pages": 0,
                "pages": [],
                "all_facts": [],
                "error": "Não foi possível converter o PDF em imagens"
            }
        
        total_pages = len(doc)
        pages_data = []
        all_facts = []
        all_products = set()
        
        if progress_callback:
            progress_callback(0, total_pages)
        
        try:
            for i, page in enumerate(doc):
                content_type = self._classify_page_content(page)
                dpi = DPI_BY_CONTENT.get(content_type, DPI_DEFAULT)
                print(f"[DOC_PROCESSOR] Processando página {i + 1}/{total_pages} (pré-classificação={content_type.value}, dpi={dpi})...")
                
                page_result = self.analyze_page_hybrid(page, content_type, document_title, page_number=i + 1)
                page_result["page_number"] = i + 1
                page_result["adaptive_dpi"] = dpi
                page_result["pre_classification"] = content_type.value
                pages_data.append(page_result)
                
                if progress_callback:
                    progress_callback(i + 1, total_pages)
                
                for product in page_result.get("products_mentioned", []):
                    all_products.add(product.strip().upper())
                
                for fact in page_result.get("facts", []):
                    prefixed_fact = f"[{document_title} - Página {i + 1}] {fact}"
                    all_facts.append(prefixed_fact)
        finally:
            doc.close()
        
        return {
            "title": document_title,
            "total_pages": total_pages,
            "pages": pages_data,
            "all_facts": all_facts,
            "all_products": list(all_products)
        }
    
    def process_pdf_resumable(
        self,
        pdf_path: str,
        document_title: str = "",
        start_page: int = 0,
        page_callback: Optional[callable] = None,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Processa um PDF com suporte a retomada de processamento interrompido.
        
        Args:
            pdf_path: Caminho para o arquivo PDF
            document_title: Título do documento
            start_page: Página inicial (0-indexed) para retomar processamento
            page_callback: Função chamada após cada página (page_number, page_result, is_success)
            progress_callback: Função chamada a cada página (current, total)
        
        Returns:
            Dict com informações estruturadas de todas as páginas
        """
        doc = None
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao abrir PDF: {e}")
        
        if not doc or len(doc) == 0:
            return {
                "title": document_title,
                "total_pages": 0,
                "pages": [],
                "all_facts": [],
                "error": "Não foi possível converter o PDF em imagens"
            }
        
        total_pages = len(doc)
        pages_data = []
        all_facts = []
        all_products = set()
        last_successful_page = start_page - 1
        
        if progress_callback:
            progress_callback(start_page, total_pages)
        
        try:
            for i in range(start_page, total_pages):
                page = doc[i]
                content_type = self._classify_page_content(page)
                dpi = DPI_BY_CONTENT.get(content_type, DPI_DEFAULT)
                print(f"[DOC_PROCESSOR] Processando página {i + 1}/{total_pages} (pré-classificação={content_type.value}, dpi={dpi})...")
                
                try:
                    import time
                    start_time = time.time()
                    
                    page_result = self.analyze_page_hybrid(page, content_type, document_title, page_number=i + 1)
                    page_result["page_number"] = i + 1
                    page_result["adaptive_dpi"] = dpi
                    page_result["pre_classification"] = content_type.value
                    
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    page_result["processing_time_ms"] = processing_time_ms
                    
                    pages_data.append(page_result)
                    last_successful_page = i
                    
                    if progress_callback:
                        progress_callback(i + 1, total_pages)
                    
                    for product in page_result.get("products_mentioned", []):
                        all_products.add(product.strip().upper())
                    
                    for fact in page_result.get("facts", []):
                        prefixed_fact = f"[{document_title} - Página {i + 1}] {fact}"
                        all_facts.append(prefixed_fact)
                    
                    if page_callback:
                        page_callback(i + 1, page_result, True, None)
                        
                except Exception as e:
                    print(f"[DOC_PROCESSOR] Erro na página {i + 1}: {e}")
                    error_result = {
                        "page_number": i + 1,
                        "error": str(e)
                    }
                    pages_data.append(error_result)
                    
                    if page_callback:
                        page_callback(i + 1, error_result, False, str(e))
                    
                    return {
                        "title": document_title,
                        "total_pages": total_pages,
                        "pages": pages_data,
                        "all_facts": all_facts,
                        "all_products": list(all_products),
                        "last_successful_page": last_successful_page,
                        "error": f"Falha na página {i + 1}: {str(e)}",
                        "interrupted": True
                    }
        finally:
            doc.close()
        
        return {
            "title": document_title,
            "total_pages": total_pages,
            "pages": pages_data,
            "all_facts": all_facts,
            "all_products": list(all_products),
            "last_successful_page": total_pages - 1,
            "completed": True
        }
    
    def get_pdf_page_count(self, pdf_path: str) -> int:
        """Retorna o número de páginas de um PDF sem processá-lo (usa PyMuPDF)."""
        try:
            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception as e:
            print(f"[DOC_PROCESSOR] Erro ao contar páginas: {e}")
            return 0
    
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
        
        all_products = [p.strip().upper() for p in result.get("products_mentioned", [])]
        
        return {
            "title": document_title,
            "total_pages": 1,
            "pages": [result],
            "all_facts": all_facts,
            "all_products": all_products
        }
    
    def generate_indexable_chunks(
        self, 
        processed_data: Dict[str, Any],
        include_summary: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Gera chunks otimizados para indexação no vector store.
        Cada fato vira um chunk independente com metadata.
        Inclui produtos mencionados para busca por tags.
        """
        chunks = []
        title = processed_data.get("title", "Documento")
        all_products = processed_data.get("all_products", [])
        products_str = ",".join(all_products) if all_products else ""
        
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
                        "source": title,
                        "products": products_str
                    }
                })
        
        for fact in processed_data.get("all_facts", []):
            chunks.append({
                "content": fact,
                "metadata": {
                    "title": title,
                    "type": "fact",
                    "source": title,
                    "products": products_str
                }
            })
        
        return chunks
    
    def generate_document_summary_and_themes(
        self,
        processed_data: Dict[str, Any],
        document_title: str = "",
        product_name: str = "",
        gestora: str = ""
    ) -> Dict[str, Any]:
        """
        Gera um resumo conceitual e identifica temas principais do documento.
        Usa GPT-4o-mini para custo-benefício otimizado.
        
        Args:
            processed_data: Dados processados do documento (output de process_pdf)
            document_title: Título do documento
            product_name: Nome do produto associado
            gestora: Nome da gestora
            
        Returns:
            Dict com 'summary' (str) e 'themes' (list de str)
        """
        if not self.client:
            return {"summary": "", "themes": [], "error": "OpenAI não configurado"}
        
        page_summaries = []
        for page in processed_data.get("pages", []):
            if page.get("summary"):
                page_summaries.append(f"Página {page.get('page_number', '?')}: {page['summary']}")
        
        all_facts = processed_data.get("all_facts", [])
        facts_text = "\n".join([f"- {fact}" for fact in all_facts[:20]])
        
        if not page_summaries and not facts_text:
            return {"summary": "", "themes": [], "error": "Sem conteúdo para resumir"}
        
        context = f"""DOCUMENTO: {document_title}
PRODUTO: {product_name}
GESTORA: {gestora}

RESUMOS POR PÁGINA:
{chr(10).join(page_summaries)}

PRINCIPAIS FATOS EXTRAÍDOS:
{facts_text}
"""
        
        prompt = """Analise o conteúdo do documento abaixo e gere:

1. RESUMO CONCEITUAL (2-3 frases): Explique o propósito e conteúdo principal do documento de forma clara e objetiva. Foque no que é mais importante para um assessor financeiro entender rapidamente.

2. TEMAS PRINCIPAIS (1-3 temas): Liste os principais tópicos abordados no documento. Cada tema deve ser uma palavra ou frase curta (ex: "rentabilidade", "alocação de ativos", "taxas de administração").

Responda APENAS em JSON no formato:
{
  "summary": "Resumo conceitual aqui...",
  "themes": ["tema1", "tema2", "tema3"]
}
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Você é um analista de documentos financeiros. Gere resumos concisos e identifique temas relevantes para assessores de investimentos."},
                    {"role": "user", "content": prompt + "\n\n" + context}
                ],
                temperature=0.3,
                max_tokens=500
            )
            try:
                if response.usage:
                    cost_tracker.track_openai_chat(
                        model='gpt-4o-mini',
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        operation='document_summary',
                        context=f'doc:{document_title}' if document_title else None
                    )
            except Exception:
                pass
            
            content = response.choices[0].message.content
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            result = json.loads(content.strip())
            
            return {
                "summary": result.get("summary", ""),
                "themes": result.get("themes", [])
            }
            
        except json.JSONDecodeError as e:
            return {"summary": "", "themes": [], "error": f"Erro ao parsear resposta: {str(e)}"}
        except Exception as e:
            return {"summary": "", "themes": [], "error": str(e)}


_document_processor = None

def get_document_processor() -> DocumentProcessor:
    """Retorna instância singleton do DocumentProcessor."""
    global _document_processor
    if _document_processor is None:
        _document_processor = DocumentProcessor()
    return _document_processor
