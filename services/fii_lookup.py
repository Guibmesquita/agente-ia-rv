"""
Serviço de consulta de informações de FIIs via StatusInvest.
Usado como fallback quando o fundo não está na base de conhecimento oficial.
"""
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


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
    administrador: str = None


class FIILookupService:
    """Serviço para buscar informações de FIIs no StatusInvest."""
    
    BASE_URL = "https://statusinvest.com.br/fundos-imobiliarios"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
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
        FIIInfoType.VALORIZACAO_12M: ["valorização", "valorizacao", "rendeu", "subiu", "caiu"],
    }
    
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
    
    def fetch_fii_data(self, ticker: str) -> Optional[FIIData]:
        """Busca dados do FII no StatusInvest."""
        ticker = ticker.upper()
        url = f"{self.BASE_URL}/{ticker.lower()}"
        
        try:
            response = requests.get(url, headers=self.HEADERS, timeout=10)
            if response.status_code != 200:
                print(f"[FII Lookup] Erro ao acessar {url}: {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            data = FIIData(ticker=ticker)
            
            title = soup.find('title')
            if title:
                nome_match = re.search(r'([A-Z]{4}11)\s*-\s*(.+?)\s*\|', title.text)
                if nome_match:
                    data.nome = nome_match.group(2).strip()
            
            cotacao_div = soup.find('div', class_='value')
            if cotacao_div:
                cotacao_strong = cotacao_div.find('strong')
                if cotacao_strong:
                    data.cotacao = f"R$ {cotacao_strong.text.strip()}"
            
            for div in soup.find_all('div', class_='info'):
                title_elem = div.find('h3', class_='title')
                value_elem = div.find('strong', class_='value')
                
                if not title_elem or not value_elem:
                    continue
                
                title_text = title_elem.get_text(strip=True).lower()
                value_text = value_elem.get_text(strip=True)
                
                if 'dividend yield' in title_text or 'dy' in title_text:
                    data.dividend_yield = f"{value_text}%"
                elif 'p/vp' in title_text:
                    data.pvp = value_text
                elif 'val. patrim' in title_text or 'valor patrimonial' in title_text:
                    data.valor_patrimonial = f"R$ {value_text}"
                elif 'patrimônio' in title_text or 'patrimonio' in title_text:
                    data.patrimonio = f"R$ {value_text}"
                elif 'cotistas' in title_text:
                    data.cotistas = value_text
                elif 'liquidez' in title_text or 'liq.' in title_text:
                    data.liquidez = f"R$ {value_text}"
                elif 'valorização' in title_text and '12' in title_text:
                    data.valorizacao_12m = f"{value_text}%"
            
            self._extract_from_indicators(soup, data)
            
            segmento_link = soup.find('a', href=re.compile(r'/fundos-imobiliarios/setor/'))
            if segmento_link:
                data.segmento = segmento_link.get_text(strip=True)
            
            admin_div = soup.find('span', class_='sub-value')
            if admin_div and 'administrador' in str(admin_div.parent).lower():
                data.administrador = admin_div.get_text(strip=True)
            
            ultimo_div = soup.find('div', class_='top-info', text=re.compile(r'Último rendimento', re.I))
            if ultimo_div:
                valor = ultimo_div.find_next('strong')
                if valor:
                    data.ultimo_dividendo = f"R$ {valor.get_text(strip=True)}"
            
            return data
            
        except Exception as e:
            print(f"[FII Lookup] Erro ao buscar {ticker}: {e}")
            return None
    
    def _extract_from_indicators(self, soup: BeautifulSoup, data: FIIData):
        """Extrai dados dos cards de indicadores."""
        indicator_items = soup.find_all('div', class_=re.compile(r'top-info.*item'))
        
        for item in indicator_items:
            title_elem = item.find(['span', 'h3'], class_='title')
            value_elem = item.find('strong', class_='value')
            
            if not title_elem or not value_elem:
                continue
            
            title = title_elem.get_text(strip=True).lower()
            value = value_elem.get_text(strip=True)
            
            if not data.cotacao and 'valor atual' in title:
                data.cotacao = f"R$ {value}"
            elif not data.dividend_yield and 'dividend yield' in title:
                data.dividend_yield = f"{value}%"
            elif not data.pvp and 'p/vp' in title:
                data.pvp = value
            elif not data.valor_patrimonial and 'val. patrim' in title:
                data.valor_patrimonial = f"R$ {value}"
            elif not data.cotistas and 'cotistas' in title:
                data.cotistas = value
            elif not data.valorizacao_12m and 'valorização' in title and '12' in title:
                data.valorizacao_12m = f"{value}%"
    
    def get_specific_info(self, data: FIIData, info_type: FIIInfoType) -> str:
        """Retorna informação específica formatada."""
        ticker = data.ticker
        
        if info_type == FIIInfoType.COTACAO:
            if data.cotacao:
                return f"A cotação atual do {ticker} é {data.cotacao}"
            return f"Não consegui encontrar a cotação do {ticker}"
        
        elif info_type == FIIInfoType.DIVIDEND_YIELD:
            if data.dividend_yield:
                return f"O Dividend Yield do {ticker} é {data.dividend_yield} ao ano"
            return f"Não consegui encontrar o DY do {ticker}"
        
        elif info_type == FIIInfoType.PVP:
            if data.pvp:
                return f"O P/VP do {ticker} está em {data.pvp}"
            return f"Não consegui encontrar o P/VP do {ticker}"
        
        elif info_type == FIIInfoType.ULTIMO_DIVIDENDO:
            if data.ultimo_dividendo:
                resp = f"O último dividendo do {ticker} foi de {data.ultimo_dividendo}"
                if data.data_ultimo_dividendo:
                    resp += f" (pago em {data.data_ultimo_dividendo})"
                return resp
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
        
        else:
            return self.format_complete_response(data)
    
    def format_complete_response(self, data: FIIData) -> str:
        """Formata resposta completa com todos os dados disponíveis."""
        lines = [f"Informações do {data.ticker}"]
        
        if data.nome:
            lines.append(f"• Nome: {data.nome}")
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
        if data.cotistas:
            lines.append(f"• Cotistas: {data.cotistas}")
        if data.segmento:
            lines.append(f"• Segmento: {data.segmento}")
        if data.liquidez:
            lines.append(f"• Liquidez Diária: {data.liquidez}")
        if data.valorizacao_12m:
            lines.append(f"• Valorização 12m: {data.valorizacao_12m}")
        
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
            "source": "StatusInvest"
        }


fii_lookup_service = FIILookupService()


def get_fii_lookup_service() -> FIILookupService:
    """Retorna instância do serviço de lookup de FIIs."""
    return fii_lookup_service
