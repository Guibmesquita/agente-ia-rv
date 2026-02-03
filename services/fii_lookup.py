"""
Serviço de consulta de informações de FIIs via FundsExplorer.
Usado como fallback quando o fundo não está na base de conhecimento oficial.
Implementação escalável com sessão persistente, cache e retry logic.

=== ATIVOS SUPORTADOS ===

O FundsExplorer é especializado em Fundos Imobiliários (FIIs) listados na B3.
Quando o usuário perguntar sobre um ativo que se encaixa nas categorias abaixo
e NÃO estiver na base de conhecimento oficial da SVN, o Stevan pode usar
este serviço para buscar informações públicas.

TIPOS DE FIIs SUPORTADOS:
- FIIs de Tijolo: fundos que investem em imóveis físicos
  (shoppings, lajes corporativas, galpões logísticos, hospitais, agências bancárias, etc.)
- FIIs de Papel: fundos que investem em CRIs, LCIs e outros títulos de renda fixa imobiliária
- FIIs Híbridos: combinação de tijolo e papel
- FOFs (Fundos de Fundos): fundos que investem em cotas de outros FIIs

INFORMAÇÕES DISPONÍVEIS PARA CADA FII:
- Cotação atual e variação do dia
- Dividend Yield (DY) dos últimos 12 meses
- P/VP (Preço sobre Valor Patrimonial)
- Valor patrimonial por cota
- Patrimônio total do fundo
- Último dividendo pago
- Liquidez diária média
- Rentabilidade do mês
- Número de cotistas
- Segmento do fundo

ATIVOS NÃO SUPORTADOS (não buscar no FundsExplorer):
- Ações (PETR4, VALE3, ITUB4, etc.) - padrão: 4 letras + 3/4
- ETFs de ações (BOVA11, IVVB11, SMAL11, etc.)
- BDRs (AAPL34, GOOGL34, etc.)
- Fundos de investimento tradicionais
- Títulos públicos (Tesouro Direto)
- Criptomoedas

PADRÃO DE TICKER DE FII:
- 4 letras maiúsculas + "11" (ex: HABT11, XPLG11, MXRF11, HGLG11)
- Regex: ^[A-Z]{4}11$

IMPORTANTE:
- Sempre buscar PRIMEIRO na base de conhecimento oficial da SVN
- Só usar FundsExplorer como fallback quando o FII não estiver na base
- Incluir disclaimer quando dados vierem de fonte externa
"""
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


# Definição estruturada dos ativos e informações suportados
SUPPORTED_ASSET_TYPES = {
    "fii_tijolo": {
        "nome": "FIIs de Tijolo",
        "descricao": "Fundos que investem em imóveis físicos",
        "exemplos": ["shoppings", "lajes corporativas", "galpões logísticos", "hospitais", "agências bancárias"],
        "tickers_exemplo": ["HGLG11", "XPLG11", "VISC11", "BTLG11"]
    },
    "fii_papel": {
        "nome": "FIIs de Papel",
        "descricao": "Fundos que investem em CRIs, LCIs e outros títulos de renda fixa imobiliária",
        "exemplos": ["CRI", "LCI", "LCA", "títulos imobiliários"],
        "tickers_exemplo": ["KNIP11", "KNCR11", "MXRF11", "HABT11"]
    },
    "fii_hibrido": {
        "nome": "FIIs Híbridos",
        "descricao": "Fundos que combinam investimentos em imóveis físicos e títulos",
        "exemplos": ["mix tijolo/papel"],
        "tickers_exemplo": ["HGRE11", "KNRI11"]
    },
    "fof": {
        "nome": "FOFs (Fundos de Fundos)",
        "descricao": "Fundos que investem em cotas de outros FIIs",
        "exemplos": ["cotas de FIIs diversificados"],
        "tickers_exemplo": ["BCFF11", "KFOF11", "RVBI11"]
    }
}

AVAILABLE_FII_INFO = {
    "cotacao": "Cotação atual e variação do dia",
    "dividend_yield": "Dividend Yield (DY) dos últimos 12 meses",
    "pvp": "P/VP (Preço sobre Valor Patrimonial)",
    "valor_patrimonial": "Valor patrimonial por cota",
    "patrimonio": "Patrimônio total do fundo",
    "ultimo_dividendo": "Último dividendo pago",
    "liquidez": "Liquidez diária média",
    "rentabilidade_mes": "Rentabilidade do mês",
    "cotistas": "Número de cotistas",
    "segmento": "Segmento do fundo"
}

UNSUPPORTED_ASSETS = {
    "acoes": {
        "nome": "Ações",
        "padrao": "4 letras + 3 ou 4 (ex: PETR4, VALE3, ITUB4)",
        "motivo": "FundsExplorer é especializado apenas em FIIs"
    },
    "etfs_acoes": {
        "nome": "ETFs de Ações",
        "padrao": "Geralmente terminam em 11 mas são ETFs (ex: BOVA11, IVVB11)",
        "motivo": "Apesar de terminar em 11, não são FIIs"
    },
    "bdrs": {
        "nome": "BDRs",
        "padrao": "4 letras + 34/35 (ex: AAPL34, GOOGL34)",
        "motivo": "Representam ações estrangeiras, não FIIs"
    },
    "fundos_tradicionais": {
        "nome": "Fundos de Investimento Tradicionais",
        "padrao": "CNPJs ou códigos internos",
        "motivo": "Não são listados em bolsa como FIIs"
    },
    "tesouro_direto": {
        "nome": "Títulos Públicos",
        "padrao": "Tesouro Selic, Tesouro IPCA+, etc.",
        "motivo": "Títulos do governo, não FIIs"
    },
    "cripto": {
        "nome": "Criptomoedas",
        "padrao": "BTC, ETH, etc.",
        "motivo": "Ativos digitais, não FIIs"
    }
}

# Regex para identificar tickers de FII
FII_TICKER_PATTERN = re.compile(r'^[A-Z]{4}11$')

# Lista de ETFs que terminam em 11 mas NÃO são FIIs (para exclusão)
ETF_EXCEPTIONS = [
    "BOVA11", "IVVB11", "SMAL11", "BOVV11", "BRAX11", "ECOO11", 
    "FIND11", "GOVE11", "ISUS11", "PIBB11", "SPXI11", "XBOV11",
    "DIVO11", "GOLD11", "HASH11", "QBTC11", "QETH11", "BOVB11"
]


def is_valid_fii_ticker(ticker: str) -> bool:
    """Verifica se um ticker é válido para busca no FundsExplorer."""
    ticker_upper = ticker.upper().strip()
    if not FII_TICKER_PATTERN.match(ticker_upper):
        return False
    if ticker_upper in ETF_EXCEPTIONS:
        return False
    return True


def get_supported_assets_description() -> str:
    """Retorna descrição dos ativos suportados para uso em prompts."""
    lines = ["ATIVOS SUPORTADOS PARA CONSULTA EXTERNA (FundsExplorer):"]
    for key, info in SUPPORTED_ASSET_TYPES.items():
        lines.append(f"- {info['nome']}: {info['descricao']}")
        lines.append(f"  Exemplos de tickers: {', '.join(info['tickers_exemplo'])}")
    lines.append("\nINFORMAÇÕES DISPONÍVEIS:")
    for key, desc in AVAILABLE_FII_INFO.items():
        lines.append(f"- {desc}")
    return "\n".join(lines)


class FIIInfoType(Enum):
    COTACAO = "cotacao"
    DIVIDEND_YIELD = "dy"
    PVP = "pvp"
    ULTIMO_DIVIDENDO = "ultimo_dividendo"
    PATRIMONIO = "patrimonio"
    VALOR_PATRIMONIAL = "vp"
    COTISTAS = "cotistas"
    SEGMENTO = "segmento"
    LIQUIDEZ = "liquidez"
    VALORIZACAO_12M = "valorizacao"
    RENTABILIDADE_MES = "rentabilidade_mes"
    COMPLETO = "completo"


@dataclass
class FIIData:
    ticker: str
    nome: str = None
    cotacao: str = None
    variacao: str = None
    dividend_yield: str = None
    pvp: str = None
    valor_patrimonial: str = None
    patrimonio: str = None
    ultimo_dividendo: str = None
    data_ultimo_dividendo: str = None
    cotistas: str = None
    segmento: str = None
    liquidez: str = None
    valorizacao_12m: str = None
    rentabilidade_mes: str = None
    vacancia: str = None


class FIILookupService:
    """Serviço para buscar informações de FIIs no FundsExplorer."""
    
    BASE_URL = "https://www.fundsexplorer.com.br/funds"
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    ]
    
    INFO_KEYWORDS = {
        FIIInfoType.COTACAO: ["cotação", "cotacao", "preço", "preco", "valor", "quanto está", "quanto ta", "quanto custa"],
        FIIInfoType.DIVIDEND_YIELD: ["dy", "dividend yield", "dividendo anual", "yield"],
        FIIInfoType.PVP: ["p/vp", "pvp", "preço sobre valor patrimonial"],
        FIIInfoType.ULTIMO_DIVIDENDO: ["último dividendo", "ultimo dividendo", "dividendo", "rendimento", "quanto pagou", "quanto paga"],
        FIIInfoType.PATRIMONIO: ["patrimônio", "patrimonio", "pl"],
        FIIInfoType.VALOR_PATRIMONIAL: ["valor patrimonial", "vp", "vpa"],
        FIIInfoType.COTISTAS: ["cotistas", "investidores", "quantos"],
        FIIInfoType.SEGMENTO: ["segmento", "tipo", "setor", "categoria"],
        FIIInfoType.LIQUIDEZ: ["liquidez", "volume"],
        FIIInfoType.VALORIZACAO_12M: ["valorização", "valorizacao", "rendeu", "subiu", "caiu", "12 meses"],
        FIIInfoType.RENTABILIDADE_MES: ["rentabilidade", "mês", "mes", "mensal"],
    }
    
    def __init__(self):
        self._session = None
        self._last_request_time = 0
        self._min_request_interval = 1.0
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 300
    
    def _get_session(self) -> requests.Session:
        """Retorna sessão HTTP persistente."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(self._get_headers())
        return self._session
    
    def _get_headers(self) -> Dict[str, str]:
        """Retorna headers que simulam navegador."""
        return {
            "User-Agent": random.choice(self.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    
    def _rate_limit(self):
        """Aplica rate limiting entre requisições."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            sleep_time = self._min_request_interval - elapsed + random.uniform(0.1, 0.3)
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    def _get_from_cache(self, ticker: str) -> Optional[FIIData]:
        """Retorna dados do cache se ainda válidos."""
        if ticker in self._cache:
            data, timestamp = self._cache[ticker]
            if time.time() - timestamp < self._cache_ttl:
                print(f"[FII Lookup] Cache hit para {ticker}")
                return data
            else:
                del self._cache[ticker]
        return None
    
    def _set_cache(self, ticker: str, data: FIIData):
        """Armazena dados no cache."""
        self._cache[ticker] = (data, time.time())
    
    def extract_ticker(self, message: str) -> Optional[str]:
        """Extrai ticker de FII da mensagem."""
        pattern = r'\b([A-Z]{4}11)\b'
        match = re.search(pattern, message.upper())
        if match:
            return match.group(1)
        
        pattern_lower = r'\b([a-zA-Z]{4}11)\b'
        match_lower = re.search(pattern_lower, message)
        if match_lower:
            return match_lower.group(1).upper()
        
        return None
    
    def detect_info_type(self, message: str) -> FIIInfoType:
        """Detecta qual tipo de informação o usuário quer."""
        message_lower = message.lower()
        
        for info_type, keywords in self.INFO_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    return info_type
        
        return FIIInfoType.COMPLETO
    
    def fetch_fii_data(self, ticker: str, max_retries: int = 3) -> Optional[FIIData]:
        """Busca dados do FII no FundsExplorer."""
        ticker = ticker.upper()
        
        cached = self._get_from_cache(ticker)
        if cached:
            return cached
        
        url = f"{self.BASE_URL}/{ticker.lower()}"
        
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                
                session = self._get_session()
                
                if attempt > 0:
                    session.headers.update({"User-Agent": random.choice(self.USER_AGENTS)})
                
                response = session.get(url, timeout=15)
                
                if response.status_code == 404:
                    print(f"[FII Lookup] Ticker {ticker} não encontrado (404)")
                    return None
                
                if response.status_code != 200:
                    print(f"[FII Lookup] Status {response.status_code} para {ticker}, tentativa {attempt + 1}/{max_retries}")
                    if attempt < max_retries - 1:
                        time.sleep(1 + attempt)
                    continue
                
                data = self._parse_fundsexplorer_html(ticker, response.text)
                if data:
                    self._set_cache(ticker, data)
                    return data
                
            except requests.exceptions.Timeout:
                print(f"[FII Lookup] Timeout para {ticker}, tentativa {attempt + 1}/{max_retries}")
            except requests.exceptions.RequestException as e:
                print(f"[FII Lookup] Erro de rede para {ticker}: {e}")
            except Exception as e:
                print(f"[FII Lookup] Erro inesperado para {ticker}: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(1 + attempt)
        
        print(f"[FII Lookup] Falha ao buscar {ticker} após {max_retries} tentativas")
        return None
    
    def _parse_fundsexplorer_html(self, ticker: str, html: str) -> Optional[FIIData]:
        """Extrai dados do HTML do FundsExplorer."""
        try:
            soup = BeautifulSoup(html, 'lxml')
            data = FIIData(ticker=ticker)
            
            title = soup.find('title')
            if title:
                title_text = title.get_text(strip=True)
                if '-' in title_text:
                    parts = title_text.split('-')
                    if len(parts) >= 2:
                        data.nome = parts[1].strip().split('|')[0].strip()
            
            h1 = soup.find('h1')
            if h1 and not data.nome:
                data.nome = h1.get_text(strip=True)
            
            price_div = soup.find('div', class_='headerTicker__content__price')
            if price_div:
                price_text = price_div.get_text(strip=True)
                match = re.search(r'R\$\s*([\d.,]+)', price_text)
                if match:
                    data.cotacao = f"R$ {match.group(1)}"
                var_match = re.search(r'([+-]?[\d.,]+)%', price_text)
                if var_match:
                    data.variacao = f"{var_match.group(1)}%"
            
            if not data.cotacao:
                quotation_div = soup.find('div', class_=re.compile(r'quotation__grid__box'))
                if quotation_div:
                    price_text = quotation_div.get_text(strip=True)
                    match = re.search(r'R\$\s*([\d.,]+)', price_text)
                    if match:
                        data.cotacao = f"R$ {match.group(1)}"
            
            indicators = soup.find_all('div', class_='indicators__box')
            
            for box in indicators:
                paragraphs = box.find_all('p')
                if len(paragraphs) < 2:
                    continue
                
                label = paragraphs[0].get_text(strip=True).lower()
                value_elem = paragraphs[1]
                
                value_text = value_elem.get_text(strip=True)
                value_text = re.sub(r'\s+', ' ', value_text)
                
                if 'cotação' in label or 'cotacao' in label:
                    match = re.search(r'R?\$?\s*([\d.,]+)', value_text)
                    if match:
                        data.cotacao = f"R$ {match.group(1)}"
                
                elif 'último rendimento' in label or 'ultimo rendimento' in label:
                    match = re.search(r'R?\$?\s*([\d.,]+)', value_text)
                    if match:
                        data.ultimo_dividendo = f"R$ {match.group(1)}"
                
                elif 'dividend yield' in label or 'dy' == label:
                    match = re.search(r'([\d.,]+)\s*%?', value_text)
                    if match:
                        data.dividend_yield = f"{match.group(1)}%"
                
                elif 'patrimônio' in label or 'patrimonio' in label:
                    data.patrimonio = value_text.replace('R$', 'R$ ').strip()
                
                elif 'valor patrimonial' in label:
                    match = re.search(r'R?\$?\s*([\d.,]+)', value_text)
                    if match:
                        data.valor_patrimonial = f"R$ {match.group(1)}"
                
                elif 'p/vp' in label:
                    match = re.search(r'([\d.,]+)', value_text)
                    if match:
                        data.pvp = match.group(1)
                
                elif 'rentab' in label and 'mês' in label:
                    match = re.search(r'([-\d.,]+)\s*%?', value_text)
                    if match:
                        data.rentabilidade_mes = f"{match.group(1)}%"
                
                elif 'liquidez' in label:
                    data.liquidez = value_text.replace('R$', 'R$ ').strip()
                
                elif 'vacância' in label or 'vacancia' in label:
                    match = re.search(r'([\d.,]+)\s*%?', value_text)
                    if match:
                        data.vacancia = f"{match.group(1)}%"
                
                elif 'cotistas' in label:
                    match = re.search(r'([\d.,]+)', value_text)
                    if match:
                        data.cotistas = match.group(1)
            
            segment_elem = soup.find('span', class_='badge')
            if segment_elem:
                data.segmento = segment_elem.get_text(strip=True)
            
            if not data.cotacao and not data.dividend_yield:
                print(f"[FII Lookup] Dados não encontrados no HTML para {ticker}")
                return None
            
            return data
            
        except Exception as e:
            print(f"[FII Lookup] Erro ao parsear HTML para {ticker}: {e}")
            return None
    
    def get_specific_info(self, data: FIIData, info_type: FIIInfoType) -> str:
        """Retorna informação específica formatada."""
        ticker = data.ticker
        
        if info_type == FIIInfoType.COTACAO:
            if data.cotacao:
                return f"A cotação atual do {ticker} é {data.cotacao}"
            return f"Não consegui encontrar a cotação do {ticker}"
        
        elif info_type == FIIInfoType.DIVIDEND_YIELD:
            if data.dividend_yield:
                return f"O Dividend Yield do {ticker} é {data.dividend_yield} (últimos 12 meses)"
            return f"Não consegui encontrar o DY do {ticker}"
        
        elif info_type == FIIInfoType.PVP:
            if data.pvp:
                return f"O P/VP do {ticker} está em {data.pvp}"
            return f"Não consegui encontrar o P/VP do {ticker}"
        
        elif info_type == FIIInfoType.ULTIMO_DIVIDENDO:
            if data.ultimo_dividendo:
                return f"O último dividendo do {ticker} foi de {data.ultimo_dividendo}"
            return f"Não consegui encontrar o último dividendo do {ticker}"
        
        elif info_type == FIIInfoType.PATRIMONIO:
            if data.patrimonio:
                return f"O patrimônio líquido do {ticker} é {data.patrimonio}"
            return f"Não consegui encontrar o patrimônio do {ticker}"
        
        elif info_type == FIIInfoType.VALOR_PATRIMONIAL:
            if data.valor_patrimonial:
                return f"O valor patrimonial por cota do {ticker} é {data.valor_patrimonial}"
            return f"Não consegui encontrar o valor patrimonial do {ticker}"
        
        elif info_type == FIIInfoType.COTISTAS:
            if data.cotistas:
                return f"O {ticker} tem {data.cotistas} cotistas"
            return f"Não consegui encontrar o número de cotistas do {ticker}"
        
        elif info_type == FIIInfoType.SEGMENTO:
            if data.segmento:
                return f"O {ticker} é um fundo do segmento {data.segmento}"
            return f"Não consegui identificar o segmento do {ticker}"
        
        elif info_type == FIIInfoType.LIQUIDEZ:
            if data.liquidez:
                return f"A liquidez média diária do {ticker} é {data.liquidez}"
            return f"Não consegui encontrar a liquidez do {ticker}"
        
        elif info_type == FIIInfoType.VALORIZACAO_12M:
            if data.valorizacao_12m:
                return f"A valorização do {ticker} nos últimos 12 meses foi de {data.valorizacao_12m}"
            return f"Não consegui encontrar a valorização do {ticker}"
        
        elif info_type == FIIInfoType.RENTABILIDADE_MES:
            if data.rentabilidade_mes:
                return f"A rentabilidade do {ticker} no mês atual é de {data.rentabilidade_mes}"
            return f"Não consegui encontrar a rentabilidade mensal do {ticker}"
        
        else:
            return self.format_complete_response(data)
    
    def _get_segment_description(self, segmento: str) -> str:
        """Retorna descrição do segmento do FII."""
        segmento_lower = segmento.lower() if segmento else ""
        
        descriptions = {
            "logística": "investe em galpões logísticos e centros de distribuição, gerando renda através de aluguéis de empresas de e-commerce e logística",
            "logístico": "investe em galpões logísticos e centros de distribuição, gerando renda através de aluguéis de empresas de e-commerce e logística",
            "lajes corporativas": "investe em escritórios e lajes comerciais em edifícios corporativos, com receita proveniente de aluguéis de empresas",
            "shoppings": "investe em participações de shopping centers, com receita de aluguéis e participação nas vendas dos lojistas",
            "shopping": "investe em participações de shopping centers, com receita de aluguéis e participação nas vendas dos lojistas",
            "papel": "investe em títulos de crédito imobiliário como CRIs e LCIs, gerando renda através dos juros recebidos",
            "recebíveis": "investe em títulos de crédito imobiliário como CRIs e LCIs, gerando renda através dos juros recebidos",
            "híbrido": "combina investimentos em imóveis físicos e títulos de crédito imobiliário, diversificando fontes de receita",
            "fundo de fundos": "investe em cotas de outros FIIs, oferecendo diversificação automática entre diferentes segmentos",
            "fof": "investe em cotas de outros FIIs, oferecendo diversificação automática entre diferentes segmentos",
            "agências": "investe em agências bancárias e imóveis de varejo, com contratos de aluguel de longo prazo",
            "hospital": "investe em hospitais e centros médicos, com contratos de aluguel de longo prazo com operadoras de saúde",
            "educacional": "investe em imóveis educacionais como faculdades e escolas, com contratos de aluguel de longo prazo",
            "hotel": "investe em hotéis e empreendimentos de hospitalidade, com receita atrelada à ocupação e diárias",
            "residencial": "investe em imóveis residenciais para locação, gerando renda através de aluguéis de apartamentos",
            "varejo": "investe em imóveis comerciais de varejo, como lojas e centros comerciais",
        }
        
        for key, desc in descriptions.items():
            if key in segmento_lower:
                return desc
        
        return "é um fundo imobiliário listado na B3, gerando renda através de seus investimentos"
    
    def format_complete_response(self, data: FIIData) -> str:
        """Formata resposta completa com contexto e indicadores."""
        lines = []
        
        nome_display = data.nome if data.nome else data.ticker
        segmento = data.segmento if data.segmento else "Fundo Imobiliário"
        seg_desc = self._get_segment_description(segmento)
        
        lines.append(f"📋 Sobre o {data.ticker}:")
        lines.append(f"{nome_display} é um FII do segmento {segmento}. Este fundo {seg_desc}.")
        lines.append("")
        lines.append("📊 Indicadores atuais:")
        
        if data.cotacao:
            lines.append(f"• Cotação: {data.cotacao}")
        if data.dividend_yield:
            lines.append(f"• Dividend Yield: {data.dividend_yield}")
        if data.pvp:
            lines.append(f"• P/VP: {data.pvp}")
        if data.valor_patrimonial:
            lines.append(f"• Valor Patrimonial: {data.valor_patrimonial}")
        if data.ultimo_dividendo:
            lines.append(f"• Último Dividendo: {data.ultimo_dividendo}")
        if data.patrimonio:
            lines.append(f"• Patrimônio: {data.patrimonio}")
        if data.liquidez:
            lines.append(f"• Liquidez Diária: {data.liquidez}")
        if data.rentabilidade_mes:
            lines.append(f"• Rentabilidade no Mês: {data.rentabilidade_mes}")
        if data.vacancia:
            lines.append(f"• Vacância: {data.vacancia}")
        if data.cotistas:
            lines.append(f"• Cotistas: {data.cotistas}")
        
        return "\n".join(lines)
    
    def lookup(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Busca informações de FII baseado na mensagem do usuário.
        Retorna dict com ticker, info_type, data e response formatada.
        """
        ticker = self.extract_ticker(message)
        if not ticker:
            return None
        
        info_type = self.detect_info_type(message)
        
        data = self.fetch_fii_data(ticker)
        if not data:
            return None
        
        response = self.get_specific_info(data, info_type)
        
        return {
            "ticker": ticker,
            "info_type": info_type.value,
            "data": data,
            "response": response,
            "source": "FundsExplorer"
        }


fii_lookup_service = FIILookupService()


def get_fii_lookup_service() -> FIILookupService:
    """Retorna instância do serviço de lookup de FIIs."""
    return fii_lookup_service
