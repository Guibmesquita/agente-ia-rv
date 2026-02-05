"""
Serviço de extração inteligente de metadados de documentos financeiros.
Usa GPT-4 Vision para analisar múltiplas páginas e extrair:
- Nome do fundo/produto
- Ticker (ex: MANA11, XPML11)
- Gestora (ex: TG Core, Manatí, XP)
- Tipo de documento

Quando o ticker não é encontrado no documento, faz busca na web para tentar identificá-lo.
"""
import os
import re
import json
import base64
import requests
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
import unicodedata

import fitz
from openai import OpenAI


@dataclass
class ExtractionResult:
    """Resultado da extração de metadados."""
    fund_name: Optional[str] = None
    ticker: Optional[str] = None
    gestora: Optional[str] = None
    document_type: Optional[str] = None
    confidence: float = 0.0
    source_pages: List[int] = None
    raw_extraction: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.source_pages is None:
            self.source_pages = []
        if self.raw_extraction is None:
            self.raw_extraction = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


KNOWN_GESTORAS = [
    "TG Core", "TG Core Asset Management", "TGCORE",
    "Manatí", "Manati", "Manatí Gestora", "Manatí Capital",
    "XP Asset", "XP Investimentos", "XP Asset Management",
    "BTG Pactual", "BTG", "BTG Asset Management",
    "Kinea", "Kinea Investimentos",
    "Vinci Partners", "Vinci",
    "Brasil Plural", "Plural",
    "RBR Asset", "RBR",
    "HSI", "Hemisfério Sul",
    "Capitânia", "Capitania",
    "VBI Real Estate", "VBI",
    "CSHG", "Credit Suisse Hedging-Griffo",
    "Hedge Investments",
    "Patria Investimentos", "Patria",
    "Iridium", "Iridium Gestão",
    "Mérito", "Merito Investimentos",
    "Guardian", "Guardian Gestora",
    "Galapagos", "Galapagos Capital",
    "Valora", "Valora Gestão",
    "Sparta", "Sparta Gestão",
    "Rio Bravo", "Rio Bravo Investimentos",
    "Bluemacaw", "Blue Macaw",
    "More Invest", "More Gestora",
    "Alianza", "Alianza Trust",
]

TICKER_PATTERN = re.compile(r'\b([A-Z]{4})(11|12|13)\b')

DOCUMENT_TYPE_KEYWORDS = {
    "material_publicitario": ["material publicitário", "material de divulgação", "oferta pública"],
    "relatorio_gerencial": ["relatório gerencial", "report mensal", "informe mensal", "relatório mensal"],
    "prospecto": ["prospecto", "prospectus"],
    "lamina": ["lâmina", "lamina informativa", "informativo"],
    "regulamento": ["regulamento", "regulation"],
    "fato_relevante": ["fato relevante", "comunicado"],
    "apresentacao": ["apresentação institucional", "apresentação do fundo", "investor presentation"],
}


def normalize_text(text: str) -> str:
    """Remove acentos e normaliza texto para comparação."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def extract_pages_as_images(pdf_path: str, pages: List[int], max_size: int = 1024) -> List[Tuple[int, str]]:
    """Extrai páginas do PDF como imagens base64."""
    results = []
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        for page_num in pages:
            if page_num < 0 or page_num >= total_pages:
                continue
            
            page = doc[page_num]
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            
            if pix.width > max_size or pix.height > max_size:
                scale = max_size / max(pix.width, pix.height)
                mat = fitz.Matrix(scale * 2.0, scale * 2.0)
                pix = page.get_pixmap(matrix=mat)
            
            img_bytes = pix.tobytes("jpeg")
            b64 = base64.b64encode(img_bytes).decode('utf-8')
            results.append((page_num + 1, b64))
        
        doc.close()
    except Exception as e:
        print(f"[MetadataExtractor] Erro ao extrair páginas: {e}")
    
    return results


def find_ticker_in_text(text: str) -> Optional[str]:
    """Busca ticker no texto usando regex."""
    matches = TICKER_PATTERN.findall(text)
    if matches:
        return f"{matches[0][0]}{matches[0][1]}"
    return None


def find_gestora_in_text(text: str) -> Optional[str]:
    """Busca gestora conhecida no texto."""
    text_normalized = normalize_text(text)
    
    for gestora in KNOWN_GESTORAS:
        gestora_normalized = normalize_text(gestora)
        if gestora_normalized in text_normalized:
            return gestora
    
    return None


def detect_document_type(text: str) -> Optional[str]:
    """Detecta tipo de documento baseado em palavras-chave."""
    text_normalized = normalize_text(text)
    
    for doc_type, keywords in DOCUMENT_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if normalize_text(keyword) in text_normalized:
                return doc_type
    
    return None


class DocumentMetadataExtractor:
    """Extrator de metadados de documentos financeiros usando GPT-4 Vision."""
    
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada")
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o"
    
    def extract_metadata(
        self,
        pdf_path: str,
        pages_to_analyze: List[int] = None,
        existing_products: List[Dict[str, Any]] = None
    ) -> ExtractionResult:
        """
        Extrai metadados do documento analisando múltiplas páginas.
        
        Args:
            pdf_path: Caminho do PDF
            pages_to_analyze: Lista de páginas a analisar (0-indexed). Default: [0, 1, 2]
            existing_products: Lista de produtos existentes para matching
        
        Returns:
            ExtractionResult com dados extraídos e confiança
        """
        if pages_to_analyze is None:
            pages_to_analyze = [0, 1, 2]
        
        page_images = extract_pages_as_images(pdf_path, pages_to_analyze)
        
        if not page_images:
            return ExtractionResult(confidence=0.0)
        
        try:
            extraction = self._analyze_with_vision(page_images)
            
            result = ExtractionResult(
                fund_name=extraction.get("fund_name"),
                ticker=extraction.get("ticker"),
                gestora=extraction.get("gestora"),
                document_type=extraction.get("document_type"),
                confidence=extraction.get("confidence", 0.5),
                source_pages=[p[0] for p in page_images],
                raw_extraction=extraction
            )
            
            if not result.ticker or not result.gestora:
                try:
                    doc = fitz.open(pdf_path)
                    for page_num, _ in page_images:
                        if result.ticker and result.gestora:
                            break
                        text = doc[page_num - 1].get_text()
                        
                        if not result.ticker:
                            ticker = find_ticker_in_text(text)
                            if ticker:
                                result.ticker = ticker
                        
                        if not result.gestora:
                            gestora = find_gestora_in_text(text)
                            if gestora:
                                result.gestora = gestora
                    doc.close()
                except Exception as e:
                    print(f"[MetadataExtractor] Erro no fallback de texto: {e}")
            
            if existing_products and result.fund_name:
                matched = self._match_to_existing_product(result, existing_products)
                if matched:
                    result.fund_name = matched.get("name", result.fund_name)
                    if not result.ticker and matched.get("ticker"):
                        result.ticker = matched["ticker"]
                    result.confidence = min(result.confidence + 0.1, 1.0)
            
            if not result.ticker and result.fund_name and result.confidence >= 0.5:
                print(f"[MetadataExtractor] Ticker não encontrado no documento. Tentando busca web...")
                web_ticker = self._search_ticker_on_web(result.fund_name, result.gestora)
                if web_ticker:
                    result.ticker = web_ticker
                    result.raw_extraction["ticker_source"] = "web_inference"
                    print(f"[MetadataExtractor] Ticker encontrado via busca web: {web_ticker}")
            
            return result
            
        except Exception as e:
            print(f"[MetadataExtractor] Erro na extração: {e}")
            return ExtractionResult(confidence=0.0, raw_extraction={"error": str(e)})
    
    def _analyze_with_vision(self, page_images: List[Tuple[int, str]]) -> Dict[str, Any]:
        """Analisa imagens das páginas com GPT-4 Vision."""
        
        content = [
            {
                "type": "text",
                "text": """Analise estas páginas de um documento financeiro brasileiro e extraia as seguintes informações:

1. **Nome do Fundo/Produto**: O nome completo do fundo de investimento (ex: "MANATÍ HEDGE FUND FII", "TG Renda Imobiliária Feeder Pré")
2. **Ticker**: O código de negociação na B3, geralmente 4 letras + 11/12/13 (ex: MANA11, XPML11, TGAR11)
3. **Gestora**: A empresa gestora do fundo (ex: "TG Core Asset Management", "Manatí", "XP Asset")
4. **Tipo de Documento**: Classifique como um dos tipos:
   - material_publicitario (oferta pública, divulgação)
   - relatorio_gerencial (report mensal, informe)
   - prospecto (prospectus)
   - lamina (lâmina informativa)
   - regulamento
   - fato_relevante (comunicado)
   - apresentacao (institucional, investor presentation)
   - outro

Procure por:
- Logos de gestoras (TG Core, XP, BTG, etc.)
- Nomes de fundos em destaque
- Códigos de ticker mencionados
- Cabeçalhos como "MATERIAL PUBLICITÁRIO", "RELATÓRIO GERENCIAL"
- Rodapés com informações de gestora

Responda APENAS em JSON válido com este formato:
{
  "fund_name": "nome completo do fundo ou null",
  "ticker": "XXXX11 ou null",
  "gestora": "nome da gestora ou null",
  "document_type": "tipo do documento",
  "confidence": 0.0 a 1.0,
  "reasoning": "explicação breve de como identificou"
}"""
            }
        ]
        
        for page_num, img_b64 in page_images:
            content.append({
                "type": "text",
                "text": f"\n--- Página {page_num} ---"
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "high"
                }
            })
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Você é um especialista em documentos financeiros brasileiros, especialmente FIIs (Fundos de Investimento Imobiliário) e fundos de investimento. Extraia informações precisas dos documentos."
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                max_tokens=1000,
                temperature=0.1
            )
            
            response_text = response.choices[0].message.content.strip()
            
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
            
        except json.JSONDecodeError as e:
            print(f"[MetadataExtractor] Erro ao parsear JSON: {e}")
            print(f"[MetadataExtractor] Resposta: {response_text[:500]}")
            return {"error": "JSON parse error", "raw": response_text[:500], "confidence": 0.0}
        except Exception as e:
            print(f"[MetadataExtractor] Erro na chamada Vision: {e}")
            return {"error": str(e), "confidence": 0.0}
    
    def _match_to_existing_product(
        self,
        result: ExtractionResult,
        existing_products: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Tenta fazer match com produto existente."""
        
        if result.ticker:
            for product in existing_products:
                if product.get("ticker") and normalize_text(product["ticker"]) == normalize_text(result.ticker):
                    return product
        
        if result.fund_name:
            result_name_normalized = normalize_text(result.fund_name)
            result_name_normalized = result_name_normalized.replace("fii", "").replace("fundo", "").strip()
            
            best_match = None
            best_score = 0
            
            for product in existing_products:
                product_name = product.get("name", "")
                product_name_normalized = normalize_text(product_name)
                product_name_normalized = product_name_normalized.replace("fii", "").replace("fundo", "").strip()
                
                if not product_name_normalized:
                    continue
                
                if result_name_normalized in product_name_normalized or product_name_normalized in result_name_normalized:
                    score = len(set(result_name_normalized.split()) & set(product_name_normalized.split()))
                    if score > best_score:
                        best_score = score
                        best_match = product
            
            if best_match and best_score >= 2:
                return best_match
        
        return None
    
    def _search_ticker_on_web(self, fund_name: str, gestora: str = None) -> Optional[str]:
        """
        Busca o ticker do fundo usando múltiplas estratégias:
        1. Primeiro tenta FundsExplorer para FIIs
        2. Depois tenta busca web via DuckDuckGo
        3. Por último usa inferência IA como fallback
        
        Args:
            fund_name: Nome do fundo identificado no documento
            gestora: Nome da gestora (opcional, para melhor precisão)
        
        Returns:
            Ticker encontrado (ex: XPLG11) ou None
        """
        if not fund_name:
            return None
        
        print(f"[MetadataExtractor] Buscando ticker para: {fund_name} (gestora: {gestora})")
        
        ticker = self._search_ticker_via_web_scraping(fund_name, gestora)
        if ticker:
            return ticker
        
        ticker = self._infer_ticker_via_ai(fund_name, gestora)
        if ticker:
            return ticker
        
        return None
    
    def _search_ticker_via_web_scraping(self, fund_name: str, gestora: str = None) -> Optional[str]:
        """Tenta buscar ticker via DuckDuckGo HTML search com validação de domínio financeiro."""
        import time
        
        FINANCE_DOMAINS = [
            "fundsexplorer", "statusinvest", "b3.com.br", "infomoney", 
            "investing.com", "meusdividendos", "fiis.com.br", "clubefii",
            "xpi.com.br", "btgpactual", "rico.com.vc", "fundamentus"
        ]
        
        try:
            time.sleep(1.5)
            
            search_query = f'"{fund_name}" ticker FII site:fundsexplorer.com.br OR site:statusinvest.com.br OR site:b3.com.br'
            if gestora:
                search_query = f'"{fund_name}" {gestora} ticker FII'
            
            url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(search_query)}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                html_text = response.text.lower()
                fund_name_lower = normalize_text(fund_name)
                
                has_finance_domain = any(domain in html_text for domain in FINANCE_DOMAINS)
                has_fund_name = fund_name_lower[:20] in normalize_text(html_text)
                
                if not (has_finance_domain and has_fund_name):
                    print(f"[MetadataExtractor] Busca web não encontrou contexto financeiro relevante")
                    return None
                
                tickers = TICKER_PATTERN.findall(response.text)
                if tickers:
                    fund_words = set(fund_name_lower.split())
                    ticker_counts = {}
                    for t in tickers:
                        ticker = f"{t[0]}{t[1]}"
                        ticker_base = t[0].lower()
                        relevance_bonus = 0
                        for word in fund_words:
                            if len(word) >= 3 and (word[:3] in ticker_base or ticker_base[:2] in word):
                                relevance_bonus += 2
                        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1 + relevance_bonus
                    
                    if ticker_counts:
                        best_ticker = max(ticker_counts.items(), key=lambda x: x[1])[0]
                        if ticker_counts[best_ticker] >= 3:
                            print(f"[MetadataExtractor] Ticker encontrado via busca web: {best_ticker} (score: {ticker_counts[best_ticker]})")
                            return best_ticker
            
            print(f"[MetadataExtractor] Nenhum ticker confiável encontrado na busca web")
            return None
            
        except requests.exceptions.Timeout:
            print(f"[MetadataExtractor] Timeout na busca web")
            return None
        except Exception as e:
            print(f"[MetadataExtractor] Erro na busca web: {e}")
            return None
    
    def _infer_ticker_via_ai(self, fund_name: str, gestora: str = None) -> Optional[str]:
        """Usa IA para inferir ticker baseado no nome do fundo."""
        try:
            prompt = f"""Você é um especialista em fundos de investimento brasileiros.

Preciso encontrar o código de negociação (ticker) na B3 para:
- Nome do Fundo: {fund_name}
- Gestora: {gestora or 'Não identificada'}

Regras de tickers de FIIs:
1. Padrão: 4 letras + 11 (ex: XPLG11, MANA11, HGLG11)
2. Fundos XP: começam com XP (XPLG, XPML, XPPR)
3. "Logístico"/"Log": usam LG (XPLG, HGLG, BTLG)
4. "Prime Yield": pode usar PY

Se conseguir identificar com confiança, responda APENAS o ticker.
Se não tiver certeza, responda "UNKNOWN".

Resposta:"""

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Responda apenas com o ticker ou UNKNOWN."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20,
                temperature=0.1
            )
            
            ticker_response = response.choices[0].message.content.strip().upper()
            
            if ticker_response and ticker_response != "UNKNOWN":
                ticker_match = re.match(r'^([A-Z]{4})(11|12|13)$', ticker_response)
                if ticker_match:
                    print(f"[MetadataExtractor] Ticker inferido via IA: {ticker_response}")
                    return ticker_response
            
            print(f"[MetadataExtractor] Não foi possível inferir ticker via IA")
            return None
            
        except Exception as e:
            print(f"[MetadataExtractor] Erro na inferência IA: {e}")
            return None


_extractor_instance = None

def get_metadata_extractor() -> DocumentMetadataExtractor:
    """Retorna instância singleton do extrator."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = DocumentMetadataExtractor()
    return _extractor_instance
