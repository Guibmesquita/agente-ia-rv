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
from dataclasses import dataclass, asdict, field as dataclass_field
import unicodedata
from difflib import SequenceMatcher

import fitz
from openai import OpenAI
from services.cost_tracker import cost_tracker


@dataclass
class ExtractionResult:
    """Resultado da extração de metadados."""
    fund_name: Optional[str] = None
    ticker: Optional[str] = None
    additional_tickers: List[str] = dataclass_field(default_factory=list)
    gestora: Optional[str] = None
    document_type: Optional[str] = None
    confidence: float = 0.0
    source_pages: List[int] = dataclass_field(default_factory=list)
    raw_extraction: Dict[str, Any] = dataclass_field(default_factory=dict)

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

TICKER_PATTERN = re.compile(r'\b([A-Z]{4})([3-9]|1[0-3])\b')

STOPWORDS_PRODUTOS = {
    "fii", "fundo", "de", "investimento", "imobiliario", "imobiliário",
    "fundo de investimento", "fundo imobiliario", "fundo imobiliário",
    "s/a", "sa", "ltda", "eireli", "asset", "management", "gestora",
    "feeder", "master", "br", "brasil"
}

ROMAN_NUMERALS = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"
}

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


def normalize_product_name(text: str) -> str:
    """
    Normalização avançada de nomes de produtos para matching.
    Remove acentos, stopwords, converte números romanos, e mantém tokens relevantes.
    """
    if not text:
        return ""
    
    normalized = normalize_text(text)
    normalized = re.sub(r'[^\w\s]', ' ', normalized)
    
    tokens = normalized.split()
    
    cleaned_tokens = []
    for token in tokens:
        if token in STOPWORDS_PRODUTOS:
            continue
        if token in ROMAN_NUMERALS:
            token = ROMAN_NUMERALS[token]
        cleaned_tokens.append(token)
    
    return ' '.join(cleaned_tokens).strip()


def tokenize_product_name(text: str) -> set:
    """Extrai tokens únicos do nome normalizado do produto."""
    normalized = normalize_product_name(text)
    return set(normalized.split())


def calculate_similarity_score(name1: str, name2: str) -> dict:
    """
    Calcula múltiplas métricas de similaridade entre dois nomes de produtos.
    
    Returns:
        dict com:
        - sequence_ratio: similaridade SequenceMatcher (0-1)
        - token_jaccard: overlap de tokens (0-1)
        - composite_score: score combinado (0-1)
        - tokens_matched: número de tokens em comum
    """
    norm1 = normalize_product_name(name1)
    norm2 = normalize_product_name(name2)
    
    if not norm1 or not norm2:
        return {
            "sequence_ratio": 0.0,
            "token_jaccard": 0.0,
            "composite_score": 0.0,
            "tokens_matched": 0,
            "normalized_names": (norm1, norm2)
        }
    
    sequence_ratio = SequenceMatcher(None, norm1, norm2).ratio()
    
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    
    if tokens1 and tokens2:
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        token_jaccard = len(intersection) / len(union) if union else 0.0
        tokens_matched = len(intersection)
    else:
        token_jaccard = 0.0
        tokens_matched = 0
    
    composite_score = (sequence_ratio * 0.4) + (token_jaccard * 0.6)
    
    return {
        "sequence_ratio": round(sequence_ratio, 3),
        "token_jaccard": round(token_jaccard, 3),
        "composite_score": round(composite_score, 3),
        "tokens_matched": tokens_matched,
        "normalized_names": (norm1, norm2)
    }


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
    """Busca o primeiro ticker no texto usando regex."""
    matches = TICKER_PATTERN.findall(text)
    if matches:
        return f"{matches[0][0]}{matches[0][1]}"
    return None


def find_all_tickers_in_text(text: str) -> List[str]:
    """Retorna todos os tickers únicos encontrados no texto, em ordem de aparição."""
    matches = TICKER_PATTERN.findall(text)
    seen = []
    for g1, g2 in matches:
        t = f"{g1}{g2}"
        if t not in seen:
            seen.append(t)
    return seen


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
            extraction = self._analyze_with_vision(page_images, pdf_path=pdf_path)
            
            vision_tickers = extraction.get("tickers") or []
            if isinstance(vision_tickers, list):
                vision_tickers = [t for t in vision_tickers if isinstance(t, str) and TICKER_PATTERN.match(t)]
            else:
                vision_tickers = []

            primary_ticker = extraction.get("ticker")

            all_tickers_ordered = []
            if primary_ticker and TICKER_PATTERN.match(primary_ticker):
                all_tickers_ordered.append(primary_ticker)
            for t in vision_tickers:
                if t not in all_tickers_ordered:
                    all_tickers_ordered.append(t)

            result = ExtractionResult(
                fund_name=extraction.get("fund_name"),
                ticker=all_tickers_ordered[0] if all_tickers_ordered else None,
                additional_tickers=all_tickers_ordered[1:] if len(all_tickers_ordered) > 1 else [],
                gestora=extraction.get("gestora"),
                document_type=extraction.get("document_type"),
                confidence=extraction.get("confidence", 0.5),
                source_pages=[p[0] for p in page_images],
                raw_extraction=extraction
            )

            if True:
                try:
                    doc = fitz.open(pdf_path)
                    all_text_tickers = []
                    for page_num, _ in page_images:
                        text = doc[page_num - 1].get_text()

                        page_tickers = find_all_tickers_in_text(text)
                        for t in page_tickers:
                            if t not in all_text_tickers:
                                all_text_tickers.append(t)

                        if not result.gestora:
                            gestora = find_gestora_in_text(text)
                            if gestora:
                                result.gestora = gestora

                    doc.close()

                    if all_text_tickers:
                        if not result.ticker:
                            result.ticker = all_text_tickers[0]
                            extras = all_text_tickers[1:]
                        else:
                            existing = [result.ticker] + result.additional_tickers
                            extras = [t for t in all_text_tickers if t not in existing]

                        for t in extras:
                            if t not in result.additional_tickers:
                                result.additional_tickers.append(t)

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
    
    def _analyze_with_vision(self, page_images: List[Tuple[int, str]], pdf_path: str = "") -> Dict[str, Any]:
        """Analisa imagens das páginas com GPT-4 Vision."""
        
        content = [
            {
                "type": "text",
                "text": """Analise estas páginas de um documento financeiro brasileiro e extraia as seguintes informações:

1. **Nome do Fundo/Produto Principal**: O nome completo do fundo ou produto principal
2. **Ticker Principal**: O primeiro código de negociação na B3 mencionado (ex: MANA11, XPML11, BEEF3)
3. **Todos os Tickers**: TODOS os códigos de ticker B3 mencionados no documento (ativos, FIIs, ações — qualquer código no formato XXXX + número)
4. **Gestora**: A empresa gestora (ex: "TG Core Asset Management", "XP Asset")
5. **Tipo de Documento**: Classifique como um dos tipos:
   - material_publicitario (oferta pública, divulgação)
   - relatorio_gerencial (report mensal, informe)
   - prospecto (prospectus)
   - lamina (lâmina informativa)
   - regulamento
   - fato_relevante (comunicado)
   - apresentacao (institucional, investor presentation)
   - operacoes_rv (operações estruturadas, recomendações de RV, POP, Collar, BM&F)
   - outro

Procure por:
- Logos de gestoras (TG Core, XP, BTG, etc.)
- Nomes de fundos e ações em destaque
- TODOS os códigos de ticker mencionados (ex: BEEF3, WEGE3, SMAL11, PETR4, etc.)
- Seções com múltiplos ativos / carteira recomendada
- Cabeçalhos como "MATERIAL PUBLICITÁRIO", "OPERAÇÕES RV", "RELATÓRIO GERENCIAL"

Responda APENAS em JSON válido com este formato:
{
  "fund_name": "nome completo do produto principal ou null",
  "ticker": "ticker principal ou null",
  "tickers": ["BEEF3", "WEGE3", "RAPT4"],
  "gestora": "nome da gestora ou null",
  "document_type": "tipo do documento",
  "confidence": 0.0 a 1.0,
  "reasoning": "explicação breve de como identificou"
}

IMPORTANTE: O campo "tickers" deve conter TODOS os tickers encontrados, incluindo o ticker principal."""
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
            try:
                if response.usage:
                    import os as _os
                    _filename = _os.path.basename(pdf_path) if pdf_path else ''
                    _pages = ','.join(str(p[0]) for p in page_images) if page_images else ''
                    cost_tracker.track_openai_chat(
                        model=self.model,
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        operation='metadata_vision_extraction',
                        context=f'upload:{_filename}|pgs:{_pages}' if _filename else None
                    )
            except Exception:
                pass
            
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
        existing_products: List[Dict[str, Any]],
        similarity_threshold: float = 0.65,
        min_tokens_match: int = 2
    ) -> Optional[Dict[str, Any]]:
        """
        Tenta fazer match com produto existente usando:
        1. Match exato por ticker (prioridade máxima)
        2. Match fuzzy por nome com scoring composto
        
        Args:
            result: Resultado da extração de metadados
            existing_products: Lista de produtos existentes
            similarity_threshold: Score mínimo para aceitar match (0-1)
            min_tokens_match: Mínimo de tokens em comum para considerar candidato
        
        Returns:
            Produto matched ou None
        """
        match_log = {
            "extracted_name": result.fund_name,
            "extracted_ticker": result.ticker,
            "candidates_evaluated": [],
            "best_match": None,
            "match_reason": None
        }
        
        if result.ticker:
            ticker_normalized = normalize_text(result.ticker)
            for product in existing_products:
                product_ticker = product.get("ticker")
                if product_ticker and normalize_text(product_ticker) == ticker_normalized:
                    match_log["best_match"] = product.get("name")
                    match_log["match_reason"] = f"ticker_exact_match ({result.ticker})"
                    print(f"[ProductMatcher] Match por ticker exato: {result.ticker} -> {product.get('name')}")
                    return product
        
        if result.fund_name:
            candidates = []
            
            for product in existing_products:
                product_name = product.get("name", "")
                if not product_name:
                    continue
                
                similarity = calculate_similarity_score(result.fund_name, product_name)
                
                candidate_info = {
                    "product_id": product.get("id"),
                    "product_name": product_name,
                    "product_ticker": product.get("ticker"),
                    "similarity": similarity
                }
                
                if similarity["tokens_matched"] >= min_tokens_match or similarity["composite_score"] >= similarity_threshold:
                    candidates.append({
                        "product": product,
                        "score": similarity["composite_score"],
                        "tokens_matched": similarity["tokens_matched"],
                        "details": similarity
                    })
                
                match_log["candidates_evaluated"].append(candidate_info)
            
            if candidates:
                candidates.sort(key=lambda x: (x["score"], x["tokens_matched"]), reverse=True)
                best_candidate = candidates[0]
                
                should_accept = (
                    best_candidate["score"] >= similarity_threshold or
                    (best_candidate["tokens_matched"] >= 3 and best_candidate["score"] >= 0.5)
                )
                
                match_log["best_candidate"] = {
                    "product_name": best_candidate["product"].get("name"),
                    "score": best_candidate["score"],
                    "tokens_matched": best_candidate["tokens_matched"],
                    "accepted": should_accept
                }
                match_log["all_candidates"] = [
                    {"name": c["product"].get("name"), "score": c["score"], "tokens": c["tokens_matched"]} 
                    for c in candidates[:5]
                ]
                
                if should_accept:
                    match_log["best_match"] = best_candidate["product"].get("name")
                    match_log["match_reason"] = f"fuzzy_match (score={best_candidate['score']}, tokens={best_candidate['tokens_matched']})"
                    
                    print(f"[ProductMatcher] Match fuzzy: '{result.fund_name}' -> '{best_candidate['product'].get('name')}' "
                          f"(score={best_candidate['score']}, tokens={best_candidate['tokens_matched']})")
                    
                    if len(candidates) > 1:
                        print(f"[ProductMatcher] Outros candidatos: {[(c['product'].get('name'), c['score']) for c in candidates[1:3]]}")
                    
                    if hasattr(result, 'raw_extraction') and result.raw_extraction is not None:
                        result.raw_extraction["product_match_log"] = match_log
                    
                    return best_candidate["product"]
                else:
                    match_log["rejection_reason"] = f"score ({best_candidate['score']}) < threshold ({similarity_threshold}) and tokens ({best_candidate['tokens_matched']}) < 3"
                    print(f"[ProductMatcher] Nenhum match acima do threshold ({similarity_threshold}). "
                          f"Melhor candidato: '{best_candidate['product'].get('name')}' com score={best_candidate['score']}, tokens={best_candidate['tokens_matched']}")
            else:
                match_log["rejection_reason"] = "no_candidates_found"
                print(f"[ProductMatcher] Nenhum candidato encontrado para: '{result.fund_name}'")
        
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
            try:
                if response.usage:
                    cost_tracker.track_openai_chat(
                        model='gpt-4o-mini',
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        operation='ticker_inference',
                        context=f'upload:inferencia_ticker:{fund_name[:50]}' if fund_name else None
                    )
            except Exception:
                pass
            
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
