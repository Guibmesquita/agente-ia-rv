"""
Módulo de Busca Semântica Aprimorada
Implementa as 10 camadas de melhoria para matching tolerante a erros.

Camadas:
1. Normalização Forte de Texto
2. Tokenização Inteligente
3. Tabela de Sinônimos e Alias
4. Indexação Vetorial com Campos Separados (integrado no vector_store)
5. Busca Multi-Query com Fusão de Resultados
6. Fuzzy Matching
7. Uso do Contexto da Conversa
8. Fallback Estruturado
9. Score Composto de Confiança
10. Auditoria e Log de Falhas de Busca
"""

import re
import unicodedata
from typing import List, Dict, Optional, Set, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, field
from collections import defaultdict


# =============================================================================
# CAMADA 1: NORMALIZAÇÃO FORTE DE TEXTO
# =============================================================================

class QueryNormalizer:
    """
    Normaliza queries antes da busca para reduzir variações artificiais.
    - Converte para lowercase
    - Remove acentuação
    - Remove caracteres especiais
    - Normaliza espaços, hífens, barras
    - Remove stopwords financeiras
    """
    
    STOPWORDS_FINANCEIRAS = {
        'o', 'a', 'os', 'as', 'um', 'uma', 'uns', 'umas',
        'de', 'da', 'do', 'das', 'dos', 'em', 'na', 'no', 'nas', 'nos',
        'para', 'por', 'com', 'sem',
        'e', 'ou', 'mas', 'que', 'qual', 'quais',
        'me', 'te', 'se', 'nos', 'vos', 'lhe', 'lhes',
        'meu', 'minha', 'seu', 'sua', 'nosso', 'nossa',
        'esse', 'essa', 'este', 'esta', 'isso', 'isto', 'aquele', 'aquela',
        'fala', 'fale', 'sobre', 'informacoes', 'informações', 'info',
        'preciso', 'quero', 'gostaria', 'poderia', 'pode',
        'saber', 'conhecer', 'entender', 'ver',
    }
    
    @staticmethod
    def remove_accents(text: str) -> str:
        """Remove acentuação do texto."""
        if not text:
            return ""
        nfkd = unicodedata.normalize('NFD', text)
        return ''.join(c for c in nfkd if not unicodedata.combining(c))
    
    @staticmethod
    def normalize_separators(text: str) -> str:
        """Normaliza hífens, barras e underscores para espaços."""
        return re.sub(r'[-_/\\]+', ' ', text)
    
    @staticmethod
    def remove_special_chars(text: str) -> str:
        """Remove caracteres especiais mantendo alfanuméricos e espaços."""
        return re.sub(r'[^a-zA-Z0-9\s]', '', text)
    
    @staticmethod
    def normalize_spaces(text: str) -> str:
        """Remove espaços múltiplos."""
        return re.sub(r'\s+', ' ', text).strip()
    
    @classmethod
    def normalize(cls, text: str, remove_stopwords: bool = True) -> str:
        """
        Aplica normalização completa ao texto.
        
        Args:
            text: Texto original
            remove_stopwords: Se deve remover stopwords
            
        Returns:
            Texto normalizado
        """
        if not text:
            return ""
        
        result = text.lower()
        result = cls.remove_accents(result)
        result = cls.normalize_separators(result)
        result = cls.remove_special_chars(result)
        result = cls.normalize_spaces(result)
        
        if remove_stopwords:
            words = result.split()
            words = [w for w in words if w not in cls.STOPWORDS_FINANCEIRAS]
            result = ' '.join(words)
        
        return result
    
    @classmethod
    def normalize_for_comparison(cls, text: str) -> str:
        """Normalização leve para comparação (mantém stopwords)."""
        return cls.normalize(text, remove_stopwords=False)


# =============================================================================
# CAMADA 2: TOKENIZAÇÃO INTELIGENTE
# =============================================================================

@dataclass
class ExtractedTokens:
    """Resultado da tokenização de uma query."""
    original: str
    normalized: str
    possible_tickers: List[str] = field(default_factory=list)
    possible_fund_names: List[str] = field(default_factory=list)
    possible_gestoras: List[str] = field(default_factory=list)
    financial_keywords: List[str] = field(default_factory=list)
    context_words: List[str] = field(default_factory=list)
    all_tokens: List[str] = field(default_factory=list)


class EntityResolver:
    """
    Camada 0: Resolve termos da query para product_ids via tabela products.
    Busca relacional (não vetorial), independente de product_ticker nos embeddings.
    """

    AMBIGUOUS_TERMS = {
        'xp', 'cdi', 'ibov', 'ibovespa', 'selic', 'ipca', 'igpm', 'igp-m',
        'ifix', 'dolar', 'dólar', 'dollar', 's&p', 's&p500', 'sp500',
        'di', 'pre', 'pos', 'coe', 'lci', 'lca', 'cdb', 'cri', 'cra',
        'fii', 'fidc', 'fiagro', 'etf', 'bdr',
        # Task #152 — termos genéricos que NÃO devem virar produto
        'fundo', 'fundos', 'produto', 'produtos', 'ativo', 'ativos',
        'papel', 'papeis', 'papéis', 'cota', 'cotas',
        'recomendação', 'recomendacao', 'recomendações', 'recomendacoes',
        'carteira', 'comitê', 'comite', 'oferta', 'ofertas',
    }

    MIN_NAME_MATCH_CONFIDENCE = 0.85

    @classmethod
    def resolve(cls, query: str, db=None) -> List[Dict[str, Any]]:
        """
        Resolve termos da query para produtos no banco.
        Returns: lista de {product_id, name, ticker, confidence}
        """
        if not db:
            from database.database import SessionLocal
            db = SessionLocal()
            should_close = True
        else:
            should_close = False

        try:
            from database.models import Product
            import json

            terms = cls._extract_search_terms(query)
            if not terms:
                return []

            results = []
            seen_ids = set()

            for term in terms:
                term_lower = term.lower().strip()
                if len(term_lower) < 3:
                    continue
                if term_lower in cls.AMBIGUOUS_TERMS:
                    continue

                matches = cls._find_products(term, db, Product)
                for match in matches:
                    if match['product_id'] not in seen_ids:
                        seen_ids.add(match['product_id'])
                        results.append(match)

            return results
        except Exception as e:
            print(f"[EntityResolver] Erro: {e}")
            return []
        finally:
            if should_close:
                db.close()

    @classmethod
    def _extract_search_terms(cls, query: str) -> List[str]:
        ticker_pat = re.compile(r'\b([A-Z]{4}\d{1,2})\b', re.IGNORECASE)
        tickers = ticker_pat.findall(query)

        cleaned = ticker_pat.sub('', query)
        cleaned = re.sub(r'\b(o|a|os|as|de|da|do|das|dos|em|na|no|para|por|com|'
                         r'me|fala|fale|sobre|quero|saber|qual|quais|que|'
                         r'informações|informacoes|info|como|está|esta|vai)\b',
                         '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        terms = [t.upper() for t in tickers]
        if cleaned and len(cleaned) >= 3:
            terms.append(cleaned)

        return terms

    @classmethod
    def _find_products(cls, term: str, db, Product) -> List[Dict[str, Any]]:
        import json
        results = []

        product = db.query(Product).filter(
            Product.ticker.ilike(term),
            Product.status == 'ativo'
        ).first()
        if product:
            results.append({
                'product_id': product.id,
                'name': product.name,
                'ticker': product.ticker,
                # Task #153 — expõe product_type para roteamento downstream
                'product_type': (product.product_type or '').lower() or 'outro',
                'confidence': 1.0,
                'match_type': 'ticker_exact'
            })
            return results

        # Task #153 — exceção de prefixo de ticker: termos como "MANA", "GARE",
        # "PETR" devem matchar tickers MANA11, GARE11, PETR4 com confiança alta.
        # Este caso regrediu na Task #152 quando o threshold foi endurecido.
        # Critério estrito: termo é puramente alfabético com 4+ chars (formato típico
        # de prefixo B3) e o ticker do banco começa com ele.
        term_alpha = term.upper().strip()
        if term_alpha.isalpha() and len(term_alpha) >= 4:
            prefix_matches = db.query(Product).filter(
                Product.ticker.ilike(f"{term_alpha}%"),
                Product.status == 'ativo'
            ).limit(3).all()
            for p in prefix_matches:
                results.append({
                    'product_id': p.id,
                    'name': p.name,
                    'ticker': p.ticker,
                    'product_type': (p.product_type or '').lower() or 'outro',
                    'confidence': 0.95,
                    'match_type': 'ticker_prefix'
                })
            if results:
                return results

        name_matches = db.query(Product).filter(
            Product.name.ilike(f"%{term}%"),
            Product.status == 'ativo'
        ).limit(5).all()
        for p in name_matches:
            name_upper = (p.name or '').upper()
            term_upper = term.upper()
            if term_upper == name_upper or term_upper in name_upper.split():
                conf = 0.9
            elif len(term) >= 5:
                conf = 0.85
            else:
                conf = 0.6
            # Task #152 — corte de baixa confiança para evitar falsos positivos
            if conf < cls.MIN_NAME_MATCH_CONFIDENCE:
                continue
            results.append({
                'product_id': p.id,
                'name': p.name,
                'ticker': p.ticker,
                'product_type': (p.product_type or '').lower() or 'outro',
                'confidence': conf,
                'match_type': 'name_ilike'
            })

        if not results:
            all_products = db.query(Product).filter(
                Product.status == 'ativo'
            ).all()
            term_upper = term.upper()
            for p in all_products:
                try:
                    aliases = json.loads(p.name_aliases or "[]")
                except (json.JSONDecodeError, TypeError):
                    aliases = []
                for alias in aliases:
                    if term_upper in alias.upper() or alias.upper() in term_upper:
                        results.append({
                            'product_id': p.id,
                            'name': p.name,
                            'ticker': p.ticker,
                            'product_type': (p.product_type or '').lower() or 'outro',
                            'confidence': 0.8,
                            'match_type': 'alias_match'
                        })
                        break

        return results


class TokenExtractor:
    """
    Extrai tokens inteligentes de uma query.
    Separa: tickers, nomes de fundos, gestoras, keywords financeiras.
    """
    
    TICKER_PATTERN = re.compile(r'\b([A-Z]{4}[0-9]{1,2})\b', re.IGNORECASE)
    
    TICKER_PATTERN_EXTENDED = re.compile(
        r'\b([A-Z]{4,5}\s*(?:PRE|POS|PRÉ|PÓS|PREV|CDI|IPCA|DI)?\s*(?:11|12|13))\b',
        re.IGNORECASE
    )
    
    FINANCIAL_KEYWORDS = {
        'taxa', 'taxas', 'rentabilidade', 'rendimento', 'yield', 'dividendo',
        'cotacao', 'cotação', 'preco', 'preço', 'valor', 'custo',
        'pvp', 'p/vp', 'dy', 'dividend', 'yield',
        'liquidez', 'prazo', 'vencimento', 'amortizacao', 'amortização',
        'carencia', 'carência', 'resgate', 'aplicacao', 'aplicação',
        'fii', 'fundo', 'cri', 'cra', 'fidc', 'fiagro',
        'credito', 'crédito', 'equity', 'acoes', 'ações',
        'imobiliario', 'imobiliário', 'multimarket', 'multimercado',
        'renda fixa', 'renda variavel', 'variável',
        'high yield', 'high grade', 'investment grade',
        'long', 'short', 'biased', 'long biased', 'long short',
        'pre', 'pré', 'pos', 'pós', 'cdi', 'ipca', 'igpm', 'selic',
        'prev', 'previdencia', 'previdência'
    }
    
    CONTEXT_WORDS = {
        'ultimo', 'última', 'proximo', 'próximo', 'atual', 'hoje',
        'historico', 'histórico', 'performance', 'resultado',
        'comparar', 'comparativo', 'versus', 'vs', 'melhor', 'pior',
        'ranking', 'top', 'mais', 'menos'
    }

    TEMPORAL_KEYWORDS = {
        'ultimo', 'ultima', 'recente', 'recentes', 'atual', 'atuais',
        'hoje', 'esse mes', 'este mes', 'esse mês', 'este mês',
        'mais recente', 'mais recentes', 'agora', 'vigente', 'vigentes',
        'ultima carta', 'ultimo relatorio', 'ultimo one pager',
    }

    COMPARATIVE_KEYWORDS = {
        'comparar', 'compare', 'comparativo', 'diferenca', 'diferença',
        'versus', 'vs', 'ou', 'entre', 'melhor entre', 'qual melhor',
        'qual é melhor', 'diferenca entre', 'diferença entre',
        'os dois', 'as duas', 'ambos', 'ambas', 'entre eles', 'entre elas',
        'qual dos dois', 'qual das duas',
    }

    RANKING_KEYWORDS = {
        'melhor', 'pior', 'maior', 'menor', 'top', 'ranking',
        'mais alto', 'mais baixo', 'mais rentavel', 'mais rentável',
        'maior dy', 'maior dividend', 'menor pvp', 'menor p/vp',
    }
    
    @classmethod
    def extract(cls, query: str) -> ExtractedTokens:
        """
        Extrai todos os tokens relevantes de uma query.
        
        Args:
            query: Query do usuário
            
        Returns:
            ExtractedTokens com todos os componentes identificados
        """
        normalized = QueryNormalizer.normalize(query, remove_stopwords=False)
        tokens = ExtractedTokens(original=query, normalized=normalized)
        
        tickers = cls.TICKER_PATTERN.findall(query.upper())
        tickers.extend(cls.TICKER_PATTERN_EXTENDED.findall(query.upper()))
        tokens.possible_tickers = list(set(t.replace(' ', '') for t in tickers if len(t) >= 4))
        
        words = normalized.split()
        for word in words:
            word_lower = word.lower()
            
            if word_lower in cls.FINANCIAL_KEYWORDS or any(kw in word_lower for kw in cls.FINANCIAL_KEYWORDS):
                tokens.financial_keywords.append(word)
            elif word_lower in cls.CONTEXT_WORDS:
                tokens.context_words.append(word)
            elif len(word) >= 3 and word.upper() not in tokens.possible_tickers:
                if not word.isdigit():
                    tokens.all_tokens.append(word)
        
        tokens.possible_gestoras = cls._extract_gestoras(query)
        tokens.possible_fund_names = cls._extract_fund_names(query, tokens)
        
        return tokens

    @classmethod
    def detect_query_intent(cls, query: str, tokens: 'ExtractedTokens') -> str:
        """
        Detecta o tipo de intenção da query para guiar re-ranking.

        Returns:
            'comparative' - múltiplos produtos / palavras de comparação
            'temporal'    - palavras de tempo / recência
            'ranking'     - melhor, maior, top, etc.
            'numeric'     - pergunta de dado numérico específico
            'conceptual'  - pergunta conceitual/geral
        """
        query_norm = QueryNormalizer.normalize_for_comparison(query)

        if len(tokens.possible_tickers) >= 2:
            return 'comparative'

        for kw in cls.COMPARATIVE_KEYWORDS:
            if kw in query_norm:
                return 'comparative'

        for kw in cls.TEMPORAL_KEYWORDS:
            if kw in query_norm:
                return 'temporal'

        for kw in cls.RANKING_KEYWORDS:
            if kw in query_norm:
                return 'ranking'

        for kw in cls.FINANCIAL_KEYWORDS:
            if kw in query_norm:
                return 'numeric'

        return 'conceptual'
    
    @classmethod
    def _extract_gestoras(cls, query: str) -> List[str]:
        """Extrai possíveis nomes de gestoras da query."""
        from services.semantic_search import SynonymLookup
        
        gestoras_found = []
        query_normalized = QueryNormalizer.normalize_for_comparison(query)
        
        for alias, official in SynonymLookup.GESTORAS.items():
            alias_norm = QueryNormalizer.normalize_for_comparison(alias)
            if alias_norm in query_normalized:
                gestoras_found.append(official)
        
        return list(set(gestoras_found))
    
    @classmethod
    def _extract_fund_names(cls, query: str, tokens: ExtractedTokens) -> List[str]:
        """Extrai possíveis nomes de fundos (palavras longas que não são tickers ou gestoras)."""
        fund_names = []
        words = query.split()
        
        for i, word in enumerate(words):
            clean = QueryNormalizer.normalize_for_comparison(word)
            if len(clean) >= 4 and clean.upper() not in tokens.possible_tickers:
                if clean not in [g.lower() for g in tokens.possible_gestoras]:
                    if i + 1 < len(words):
                        compound = f"{clean} {QueryNormalizer.normalize_for_comparison(words[i+1])}"
                        if len(compound) >= 6:
                            fund_names.append(compound)
                    fund_names.append(clean)
        
        return fund_names[:5]


# =============================================================================
# CAMADA 3: TABELA DE SINÔNIMOS E ALIASES
# =============================================================================

class SynonymLookup:
    """
    Tabela de sinônimos e aliases para lookup semântico.
    Mapeia abreviações, apelidos e variações para nomes oficiais.
    """
    
    GESTORAS = {
        'tg': 'TG Core',
        'tg core': 'TG Core',
        'tgcore': 'TG Core',
        'manati': 'Manatí',
        'manatí': 'Manatí',
        'kinea': 'Kinea',
        'xp': 'XP Asset',
        'xp asset': 'XP Asset',
        'xpasset': 'XP Asset',
        'btg': 'BTG Pactual',
        'btg pactual': 'BTG Pactual',
        'itau': 'Itaú Asset',
        'itaú': 'Itaú Asset',
        'itau asset': 'Itaú Asset',
        'verde': 'Verde Asset',
        'verde am': 'Verde Asset',
        'verde asset': 'Verde Asset',
        'credit suisse': 'Credit Suisse',
        'cs': 'Credit Suisse',
        'jgp': 'JGP',
        'spx': 'SPX',
        'safra': 'Safra',
        'bb': 'BB Asset',
        'bb asset': 'BB Asset',
        'bradesco': 'Bradesco Asset',
        'caixa': 'Caixa Asset',
        'hsbc': 'HSBC',
        'santander': 'Santander Asset',
        'vinci': 'Vinci Partners',
        'capitania': 'Capitânia',
        'capitânia': 'Capitânia',
        'hedge': 'Hedge Investments',
        'hectare': 'Hectare',
        'xp log': 'XP Log',
        'xplog': 'XP Log',
        'xp malls': 'XP Malls',
        'xpmalls': 'XP Malls',
        'hglg': 'CSHG Logística',
        'cshg': 'CSHG',
        'vbi': 'VBI',
        'rbrr': 'RBR',
        'rbr': 'RBR',
        'patria': 'Pátria',
        'pátria': 'Pátria',
        'alianza': 'Alianza',
        'vgir': 'Valora',
        'valora': 'Valora',
        'recr': 'REC',
        'rec': 'REC',
        'mxrf': 'Maxi Renda',
        'maxi renda': 'Maxi Renda',
        'brcr': 'BC Fund',
        'bc fund': 'BC Fund',
        'ggrc': 'GGR Covepi',
        'ggr': 'GGR Covepi',
        'hgru': 'CSHG Renda Urbana',
        'trxf': 'TRX',
        'trx': 'TRX',
        'visc': 'Vinci Shopping',
        'hsml': 'HSI Malls',
        'hsi': 'HSI',
        'brco': 'Bresco',
        'bresco': 'Bresco',
        'knri': 'Kinea Renda Imobiliária',
        'kncr': 'Kinea Crédito',
        'knip': 'Kinea Índices de Preços',
        'knhy': 'Kinea High Yield',
        'knsc': 'Kinea Securities',
    }
    
    PRODUTOS_ALIASES = {
        'xp lb': 'XP Long Biased',
        'xp long biased': 'XP Long Biased',
        'xplb': 'XP Long Biased',
        'kinea cp': 'Kinea Crédito Privado',
        'kinea credito': 'Kinea Crédito Privado',
        'kinea crédito': 'Kinea Crédito Privado',
        'verde master': 'Verde FIC FIM',
        'verde fic': 'Verde FIC FIM',
        'spx nimitz': 'SPX Nimitz',
        'jgp strategy': 'JGP Strategy',
        'kapitalo kappa': 'Kapitalo Kappa',
        'kapitalo': 'Kapitalo Kappa',
        'adam macro': 'Adam Macro',
        'adam': 'Adam Macro',
        'legacy capital': 'Legacy Capital',
        'legacy': 'Legacy Capital',
        'vinland macro': 'Vinland Macro',
        'vinland': 'Vinland Macro',
        'ibiuna hedge': 'Ibiuna Hedge',
        'ibiuna': 'Ibiuna Hedge',
        'bahia am': 'Bahia AM',
        'bahia': 'Bahia AM',
        'gavea macro': 'Gávea Macro',
        'gávea': 'Gávea Macro',
        'gavea': 'Gávea Macro',
        'absolute vertex': 'Absolute Vertex',
        'absolute': 'Absolute Vertex',
        'tg pre': 'TGRI PRÉ',
        'tg pré': 'TGRI PRÉ',
        'tgri pre': 'TGRI PRÉ',
        'tgri pré': 'TGRI PRÉ',
        'tg pos': 'TGRI PÓS',
        'tg pós': 'TGRI PÓS',
        'tgri pos': 'TGRI PÓS',
        'tgri pós': 'TGRI PÓS',
        'aliar': 'ALIAR',
    }
    
    CATEGORIAS_ALIASES = {
        'fii': 'FII',
        'fundo imobiliario': 'FII',
        'fundo imobiliário': 'FII',
        'fiis': 'FII',
        'cri': 'CRI',
        'cra': 'CRA',
        'fidc': 'FIDC',
        'fiagro': 'FIAGRO',
        'rf': 'Renda Fixa',
        'renda fixa': 'Renda Fixa',
        'rv': 'Renda Variável',
        'renda variavel': 'Renda Variável',
        'renda variável': 'Renda Variável',
        'multimercado': 'Multimercado',
        'multi': 'Multimercado',
        'mm': 'Multimercado',
        'acoes': 'Ações',
        'ações': 'Ações',
        'equity': 'Ações',
        'prev': 'Previdência',
        'previdencia': 'Previdência',
        'previdência': 'Previdência',
    }
    
    @classmethod
    def expand_query(cls, query: str) -> List[str]:
        """
        Expande uma query com sinônimos e aliases.
        
        Args:
            query: Query original
            
        Returns:
            Lista de queries expandidas (original + variações)
        """
        queries = [query]
        query_lower = query.lower()
        query_normalized = QueryNormalizer.normalize_for_comparison(query)
        
        for alias, official in cls.GESTORAS.items():
            if alias in query_normalized:
                expanded = query_normalized.replace(alias, official.lower())
                if expanded not in queries:
                    queries.append(expanded)
        
        for alias, official in cls.PRODUTOS_ALIASES.items():
            alias_norm = QueryNormalizer.normalize_for_comparison(alias)
            if alias_norm in query_normalized:
                expanded = query_normalized.replace(alias_norm, official.lower())
                if expanded not in queries:
                    queries.append(expanded)
        
        for alias, official in cls.CATEGORIAS_ALIASES.items():
            if alias in query_normalized:
                expanded = query_normalized.replace(alias, official.lower())
                if expanded not in queries:
                    queries.append(expanded)
        
        return queries[:5]
    
    @classmethod
    def resolve_gestora(cls, text: str) -> Optional[str]:
        """Resolve alias de gestora para nome oficial."""
        text_norm = QueryNormalizer.normalize_for_comparison(text)
        return cls.GESTORAS.get(text_norm)
    
    @classmethod
    def resolve_produto(cls, text: str) -> Optional[str]:
        """Resolve alias de produto para nome oficial."""
        text_norm = QueryNormalizer.normalize_for_comparison(text)
        return cls.PRODUTOS_ALIASES.get(text_norm)


# =============================================================================
# CAMADA 6: FUZZY MATCHING
# =============================================================================

class FuzzyMatcher:
    """
    Matching aproximado usando distância de Levenshtein.
    Captura erros de digitação comuns.
    """
    
    @staticmethod
    def levenshtein_distance(s1: str, s2: str) -> int:
        """Calcula a distância de Levenshtein entre duas strings."""
        if len(s1) < len(s2):
            return FuzzyMatcher.levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    @staticmethod
    def similarity_ratio(s1: str, s2: str) -> float:
        """
        Calcula a similaridade entre 0 e 1.
        1 = idêntico, 0 = completamente diferente.
        """
        if not s1 or not s2:
            return 0.0
        
        distance = FuzzyMatcher.levenshtein_distance(s1.lower(), s2.lower())
        max_len = max(len(s1), len(s2))
        return 1.0 - (distance / max_len)
    
    @classmethod
    def find_best_matches(
        cls, 
        query: str, 
        candidates: List[str], 
        threshold: float = 0.6,
        max_results: int = 5
    ) -> List[Tuple[str, float]]:
        """
        Encontra os melhores matches fuzzy para uma query.
        
        Args:
            query: Texto a buscar
            candidates: Lista de candidatos
            threshold: Similaridade mínima (0-1)
            max_results: Máximo de resultados
            
        Returns:
            Lista de (candidato, score) ordenada por similaridade
        """
        query_norm = QueryNormalizer.normalize_for_comparison(query)
        
        matches = []
        for candidate in candidates:
            candidate_norm = QueryNormalizer.normalize_for_comparison(candidate)
            
            if query_norm in candidate_norm or candidate_norm in query_norm:
                matches.append((candidate, 0.95))
                continue
            
            similarity = cls.similarity_ratio(query_norm, candidate_norm)
            
            if len(query_norm) >= 3 and len(candidate_norm) >= 3:
                if query_norm[:3] == candidate_norm[:3]:
                    similarity = min(1.0, similarity + 0.1)
            
            if similarity >= threshold:
                matches.append((candidate, similarity))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:max_results]


# =============================================================================
# CAMADA 7: CONTEXTO DA CONVERSA
# =============================================================================

@dataclass
class ConversationContext:
    """Contexto temporário de uma conversa."""
    conversation_id: str
    last_products: List[str] = field(default_factory=list)
    last_gestoras: List[str] = field(default_factory=list)
    last_categories: List[str] = field(default_factory=list)
    last_query: str = ""
    updated_at: datetime = field(default_factory=datetime.now)
    
    def add_product(self, product: str):
        """Adiciona produto ao contexto (mantém últimos 5)."""
        if product and product not in self.last_products:
            self.last_products.insert(0, product)
            self.last_products = self.last_products[:5]
        self.updated_at = datetime.now()
    
    def add_gestora(self, gestora: str):
        """Adiciona gestora ao contexto (mantém últimas 3)."""
        if gestora and gestora not in self.last_gestoras:
            self.last_gestoras.insert(0, gestora)
            self.last_gestoras = self.last_gestoras[:3]
        self.updated_at = datetime.now()
    
    def add_category(self, category: str):
        """Adiciona categoria ao contexto (mantém últimas 3)."""
        if category and category not in self.last_categories:
            self.last_categories.insert(0, category)
            self.last_categories = self.last_categories[:3]
        self.updated_at = datetime.now()


class ConversationContextManager:
    """
    Gerencia contextos de múltiplas conversas.
    Permite reutilizar contexto para buscas mais naturais.
    """
    
    _contexts: Dict[str, ConversationContext] = {}
    _max_age_minutes: int = 30
    
    @classmethod
    def get_context(cls, conversation_id: str) -> ConversationContext:
        """Obtém ou cria contexto para uma conversa."""
        if conversation_id not in cls._contexts:
            cls._contexts[conversation_id] = ConversationContext(conversation_id=conversation_id)
        
        context = cls._contexts[conversation_id]
        
        age = (datetime.now() - context.updated_at).total_seconds() / 60
        if age > cls._max_age_minutes:
            cls._contexts[conversation_id] = ConversationContext(conversation_id=conversation_id)
        
        return cls._contexts[conversation_id]
    
    @classmethod
    def update_context(
        cls, 
        conversation_id: str, 
        products: Optional[List[str]] = None,
        gestoras: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        query: Optional[str] = None
    ):
        """Atualiza contexto com novos dados."""
        context = cls.get_context(conversation_id)
        
        if products:
            for p in products:
                context.add_product(p)
        if gestoras:
            for g in gestoras:
                context.add_gestora(g)
        if categories:
            for c in categories:
                context.add_category(c)
        if query:
            context.last_query = query
    
    @classmethod
    def should_use_context(cls, query: str) -> bool:
        """Verifica se a query indica uso de contexto anterior."""
        context_indicators = [
            'esse', 'essa', 'este', 'esta', 'isso', 'isto',
            'mesmo', 'mesma', 'ai', 'aí',
            'ele', 'ela', 'aquele', 'aquela',
            'o da', 'a da', 'do mesmo', 'da mesma',
            'anterior', 'ultimo', 'última'
        ]
        query_lower = query.lower()
        return any(indicator in query_lower for indicator in context_indicators)
    
    @classmethod
    def cleanup_old_contexts(cls):
        """Remove contextos antigos."""
        now = datetime.now()
        to_remove = []
        
        for conv_id, context in cls._contexts.items():
            age = (now - context.updated_at).total_seconds() / 60
            if age > cls._max_age_minutes * 2:
                to_remove.append(conv_id)
        
        for conv_id in to_remove:
            del cls._contexts[conv_id]


# =============================================================================
# CAMADA 9: SCORE COMPOSTO DE CONFIANÇA
# =============================================================================

@dataclass
class SearchResult:
    """Resultado de busca com score composto."""
    content: str
    metadata: Dict[str, Any]
    vector_distance: float
    vector_score: float
    fuzzy_score: float = 0.0
    ticker_match: bool = False
    gestora_match: bool = False
    context_match: bool = False
    recency_score: float = 0.5
    composite_score: float = 0.0
    confidence_level: str = "low"
    source: str = "vector"
    
    def calculate_composite_score(self):
        """Calcula o score composto com 6 fatores (pesos somam 1.0)."""
        score = (
            self.vector_score * 0.45 +
            self.fuzzy_score * 0.20 +
            (0.15 if self.ticker_match else 0.0) +
            (0.10 if self.gestora_match else 0.0) +
            (0.05 if self.context_match else 0.0) +
            self.recency_score * 0.05
        )
        
        self.composite_score = min(1.0, score)
        
        if self.composite_score >= 0.7:
            self.confidence_level = "high"
        elif self.composite_score >= 0.4:
            self.confidence_level = "medium"
        else:
            self.confidence_level = "low"


class CompositeScorer:
    """Calcula scores compostos para resultados de busca."""
    
    @classmethod
    def score_results(
        cls,
        results: List[Dict],
        tokens: ExtractedTokens,
        context: Optional[ConversationContext] = None,
        query_intent: str = 'conceptual'
    ) -> List[SearchResult]:
        """
        Calcula scores compostos para uma lista de resultados.
        
        Args:
            results: Resultados da busca vetorial
            tokens: Tokens extraídos da query
            context: Contexto da conversa (opcional)
            query_intent: Tipo de intenção da query (numeric, temporal, comparative, ranking, conceptual)
            
        Returns:
            Lista de SearchResult com scores calculados
        """
        scored_results = []
        
        for r in results:
            distance = r.get('distance', 1.0)
            
            # SCORING NÍVEL 2 (Ranking final único)
            # O VectorStore (Nível 1) agora retorna apenas distância cosseno bruta.
            # Todo o ranking é feito aqui com 6 fatores:
            # vetor (0.45), fuzzy (0.20), ticker (0.15), gestora (0.10),
            # contexto (0.05), recência (0.05)
            vector_score = max(0, 1.0 - distance)
            
            metadata = r.get('metadata', {})

            # Para queries temporais, aumentar peso de recência de 5% para 25%
            recency_score = cls._calculate_recency_score(metadata)
            
            result = SearchResult(
                content=r.get('content', ''),
                metadata=metadata,
                vector_distance=distance,
                vector_score=vector_score,
                recency_score=recency_score,
                source=r.get('source', 'vector')
            )
            
            products_meta = metadata.get('products', '').upper()
            for ticker in tokens.possible_tickers:
                if ticker in products_meta:
                    result.ticker_match = True
                    break
            
            for gestora in tokens.possible_gestoras:
                gestora_meta = metadata.get('gestora', '').lower()
                if gestora.lower() in gestora_meta or gestora.lower() in result.content.lower():
                    result.gestora_match = True
                    break
            
            if context and query_intent != 'comparative':
                for prod in context.last_products:
                    if prod.upper() in products_meta:
                        result.context_match = True
                        break
            
            content_norm = QueryNormalizer.normalize_for_comparison(result.content[:500])
            for token in tokens.all_tokens[:5]:
                if token in content_norm:
                    result.fuzzy_score += 0.1
            
            # BOOST DETERMINÍSTICO POR GLOSSÁRIO LITERAL:
            # Se a query menciona um termo do glossário (LTV, FFO, duration, etc.)
            # e o embedding tem esse termo populado em metadata['keywords'] OU em
            # metadata['concepts'], dá um forte boost de fuzzy_score.
            # Isso resolve o caso "LTV médio do MCCE11" mesmo quando o termo
            # está diluído em um bloco grande.
            try:
                from services.financial_concepts import extract_glossary_terms_from_text
                query_text_for_glossary = getattr(tokens, 'original', '') or ' '.join(tokens.all_tokens)
                query_terms = extract_glossary_terms_from_text(query_text_for_glossary)
                query_concept_ids = set(query_terms.get('concept_ids', []))
                query_literal_terms = set(query_terms.get('matched_terms', []))
                
                if query_literal_terms or query_concept_ids:
                    kw_meta = (metadata.get('keywords') or '').lower()
                    concepts_meta_raw = metadata.get('concepts') or '[]'
                    try:
                        import json as _json
                        concepts_meta = set(_json.loads(concepts_meta_raw)) if isinstance(concepts_meta_raw, str) else set(concepts_meta_raw)
                    except Exception:
                        concepts_meta = set()
                    
                    # Match literal de termos no campo keywords
                    literal_hit = any(t in kw_meta for t in query_literal_terms if t)
                    # Match conceitual via concepts
                    concept_hit = bool(query_concept_ids & concepts_meta)
                    # Fallback: termo literal aparece no conteúdo bruto
                    content_hit = any(t in result.content.lower() for t in query_literal_terms if len(t) >= 3)
                    
                    if literal_hit:
                        result.fuzzy_score += 0.4
                    elif concept_hit:
                        result.fuzzy_score += 0.25
                    elif content_hit:
                        result.fuzzy_score += 0.15
            except Exception:
                pass
            
            result.fuzzy_score = min(1.0, result.fuzzy_score)
            
            result.calculate_composite_score()

            # BOOST ORIENTADO POR INTENÇÃO — aplicado APÓS o composite score base
            intent_boost = cls._calculate_intent_boost(result, query_intent)
            result.composite_score = min(1.0, result.composite_score + intent_boost)

            # Para queries temporais, re-calcular com peso maior de recência
            if query_intent == 'temporal':
                temporal_score = (
                    result.vector_score * 0.35 +
                    result.fuzzy_score * 0.15 +
                    (0.10 if result.ticker_match else 0.0) +
                    (0.08 if result.gestora_match else 0.0) +
                    (0.07 if result.context_match else 0.0) +
                    result.recency_score * 0.25
                )
                result.composite_score = min(1.0, temporal_score + intent_boost)

            scored_results.append(result)
        
        scored_results.sort(key=lambda x: x.composite_score, reverse=True)
        return scored_results

    @classmethod
    def _calculate_intent_boost(cls, result: 'SearchResult', query_intent: str) -> float:
        """
        Calcula boost adicional baseado na intenção detectada da query.

        Para numeric: blocos com tabelas e dados numéricos recebem boost.
        Para temporal: documentos mais recentes recebem boost extra (tratado no caller).
        Para ranking: blocos de múltiplos produtos recebem boost.
        """
        boost = 0.0
        block_type = result.metadata.get('block_type', '').lower()
        topic = result.metadata.get('topic', '').lower()
        content_lower = result.content.lower()

        if query_intent == 'numeric':
            # Tabelas e blocos com dados numéricos são prioritários
            if block_type in ('table', 'key_metrics', 'chart'):
                boost += 0.15
            # Blocos com tópico de dividendos/performance têm bônus extra para queries numéricas
            if topic in ('dividendos', 'performance', 'rentabilidade'):
                boost += 0.08
            # Conteúdo com % ou números explícitos
            if any(c in content_lower for c in ['%', 'dy', 'p/vp', 'pvp', 'dividend', 'yield']):
                boost += 0.05

        elif query_intent == 'ranking':
            # Blocos de múltiplos produtos ou comparativos
            if topic in ('comparativo', 'ranking', 'performance'):
                boost += 0.10
            if block_type == 'table':
                boost += 0.08

        return boost
    
    @staticmethod
    def _calculate_recency_score(metadata: Dict) -> float:
        """
        Score de recência (Task #152):
        - Se houver `valid_until_dt` (data parseada de validade), penaliza fortemente
          documentos vencidos (score 0.05) e dá score alto para os ainda vigentes.
        - Caso contrário, usa created_at / created_at_source / valid_until (string)
          decaindo linearmente em 730 dias.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        def _parse(value) -> Optional[datetime]:
            if not value:
                return None
            try:
                if isinstance(value, datetime):
                    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                if isinstance(value, str):
                    if 'T' in value:
                        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    else:
                        d = datetime.strptime(value[:10], "%Y-%m-%d")
                        d = d.replace(tzinfo=timezone.utc)
                    return d
            except Exception:
                return None
            return None

        valid_until_dt = _parse(metadata.get("valid_until_dt"))
        if valid_until_dt is not None:
            if valid_until_dt < now:
                return 0.05
            days_to_expiry = max(0, (valid_until_dt - now).days)
            return max(0.6, min(1.0, 1.0 - (days_to_expiry / 730)))

        date_str = metadata.get("created_at") or metadata.get("created_at_source") or metadata.get("valid_until")
        doc_date = _parse(date_str)
        if doc_date is None:
            return 0.5
        days_old = (now - doc_date).days
        return max(0.2, 1.0 - (days_old / 730))


# =============================================================================
# CAMADA 10: AUDITORIA E LOG DE FALHAS
# =============================================================================

@dataclass
class SearchAuditEntry:
    """Entrada de auditoria de busca."""
    timestamp: datetime
    conversation_id: Optional[str]
    original_query: str
    normalized_query: str
    tokens: Dict[str, Any]
    results_count: int
    top_result_score: float
    chosen_result: Optional[str]
    user_confirmed: Optional[bool]
    fallback_used: bool
    search_duration_ms: float
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'conversation_id': self.conversation_id,
            'original_query': self.original_query,
            'normalized_query': self.normalized_query,
            'tokens': self.tokens,
            'results_count': self.results_count,
            'top_result_score': self.top_result_score,
            'chosen_result': self.chosen_result,
            'user_confirmed': self.user_confirmed,
            'fallback_used': self.fallback_used,
            'search_duration_ms': self.search_duration_ms
        }


class SearchAuditLog:
    """
    Log de auditoria para buscas.
    Permite análise de falhas e aprendizado do sistema.
    """
    
    _entries: List[SearchAuditEntry] = []
    _max_entries: int = 1000
    
    @classmethod
    def log_search(
        cls,
        original_query: str,
        normalized_query: str,
        tokens: ExtractedTokens,
        results_count: int,
        top_result_score: float,
        fallback_used: bool,
        search_duration_ms: float,
        conversation_id: Optional[str] = None,
        chosen_result: Optional[str] = None
    ):
        """Registra uma busca no log."""
        entry = SearchAuditEntry(
            timestamp=datetime.now(),
            conversation_id=conversation_id,
            original_query=original_query,
            normalized_query=normalized_query,
            tokens={
                'tickers': tokens.possible_tickers,
                'gestoras': tokens.possible_gestoras,
                'keywords': tokens.financial_keywords
            },
            results_count=results_count,
            top_result_score=top_result_score,
            chosen_result=chosen_result,
            user_confirmed=None,
            fallback_used=fallback_used,
            search_duration_ms=search_duration_ms
        )
        
        cls._entries.append(entry)
        
        if len(cls._entries) > cls._max_entries:
            cls._entries = cls._entries[-cls._max_entries:]
        
        if results_count == 0:
            print(f"[SEARCH_AUDIT] Zero results for: '{original_query}' | Tokens: {entry.tokens}")
    
    @classmethod
    def get_failed_searches(cls, limit: int = 50) -> List[Dict]:
        """Retorna buscas que falharam (0 resultados)."""
        failed = [e.to_dict() for e in cls._entries if e.results_count == 0]
        return failed[-limit:]
    
    @classmethod
    def get_low_confidence_searches(cls, threshold: float = 0.5, limit: int = 50) -> List[Dict]:
        """Retorna buscas com baixa confiança."""
        low_conf = [e.to_dict() for e in cls._entries if e.top_result_score < threshold]
        return low_conf[-limit:]
    
    @classmethod
    def get_stats(cls) -> Dict:
        """Retorna estatísticas do log."""
        if not cls._entries:
            return {'total': 0}
        
        total = len(cls._entries)
        zero_results = sum(1 for e in cls._entries if e.results_count == 0)
        low_confidence = sum(1 for e in cls._entries if e.top_result_score < 0.5)
        fallback_used = sum(1 for e in cls._entries if e.fallback_used)
        avg_duration = sum(e.search_duration_ms for e in cls._entries) / total
        
        return {
            'total': total,
            'zero_results': zero_results,
            'zero_results_rate': zero_results / total,
            'low_confidence': low_confidence,
            'low_confidence_rate': low_confidence / total,
            'fallback_used': fallback_used,
            'fallback_rate': fallback_used / total,
            'avg_duration_ms': avg_duration
        }


# =============================================================================
# CAMADA 5 & 8: BUSCA MULTI-QUERY E FALLBACK ESTRUTURADO
# =============================================================================

class EnhancedSearch:
    """
    Orquestrador de busca aprimorada.
    Combina todas as camadas para uma busca robusta e tolerante a erros.
    """
    
    def __init__(self, vector_store):
        self.vector_store = vector_store
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        conversation_id: Optional[str] = None,
        similarity_threshold: float = 0.4,  # Task #152 — recall-friendly default
        db: Optional[Any] = None
    ) -> List[SearchResult]:
        """
        Executa busca aprimorada com todas as camadas.
        
        Args:
            query: Query do usuário
            n_results: Número de resultados desejados
            conversation_id: ID da conversa para contexto
            similarity_threshold: Threshold de similaridade
            
        Returns:
            Lista de SearchResult ordenados por score composto.
            Cada SearchResult tem atributo extra_meta['query_intent'] e
            extra_meta['is_comparative'] para uso downstream.
        """
        import time
        start_time = time.time()
        
        tokens = TokenExtractor.extract(query)
        normalized_query = QueryNormalizer.normalize(query)

        # DETECÇÃO DE INTENÇÃO DA QUERY — antes de qualquer busca
        query_intent = TokenExtractor.detect_query_intent(query, tokens)
        is_comparative = query_intent == 'comparative'
        
        context = None
        if conversation_id:
            context = ConversationContextManager.get_context(conversation_id)
            
            if is_comparative and len(tokens.possible_tickers) >= 2:
                pass
            elif is_comparative and len(tokens.possible_tickers) < 2 and context.last_products:
                needed = 2 - len(tokens.possible_tickers)
                existing = set(t.upper() for t in tokens.possible_tickers)
                for prod in context.last_products:
                    if prod.upper() not in existing:
                        tokens.possible_tickers.append(prod)
                        existing.add(prod.upper())
                        needed -= 1
                        if needed <= 0:
                            break
                print(f"[EnhancedSearch] Comparativa 'os dois/ambos' resolvida para: {tokens.possible_tickers}")
            elif ConversationContextManager.should_use_context(query) and context.last_products:
                tokens.possible_tickers.extend(context.last_products[:2])
        
        expanded_queries = SynonymLookup.expand_query(query)
        
        all_results = []
        seen_ids = set()

        # CAMADA 0: ENTITY RESOLVER — busca relacional na tabela products
        try:
            resolved_products = EntityResolver.resolve(query, db=db)
            if resolved_products:
                high_confidence = [p for p in resolved_products if p['confidence'] >= 0.8]
                if high_confidence:
                    product_ids = [p['product_id'] for p in high_confidence]
                    entity_results = self.vector_store.search_by_product_ids(product_ids, max_per_product=5)
                    for r in entity_results:
                        doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                        if doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            all_results.append(r)
                    resolved_names = [p['name'] for p in high_confidence]
                    print(f"[EnhancedSearch] Layer 0 EntityResolver: {len(entity_results)} blocos de {resolved_names}")
        except Exception as e:
            print(f"[EnhancedSearch] Layer 0 EntityResolver erro (não-bloqueante): {e}")

        # BUSCA MULTI-ENTIDADE PARA QUERIES COMPARATIVAS
        # Para "compare MANA11 com LIFE11": busca separada por entidade,
        # garantindo representação equilibrada de cada produto no contexto.
        if is_comparative and len(tokens.possible_tickers) >= 2:
            results_per_entity = max(3, n_results // len(tokens.possible_tickers))
            for ticker in tokens.possible_tickers[:3]:
                entity_results = self.vector_store.search_by_product(ticker, n_results=results_per_entity)
                for r in entity_results:
                    doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        r['distance'] = r.get('distance', 0.1)
                        r['entity_source'] = ticker
                        all_results.append(r)
            print(f"[EnhancedSearch] Comparativa detectada: {tokens.possible_tickers} | {len(all_results)} blocos multi-entidade")
        
        # Task #152 — block_type_filter dirigido pela intenção da query
        intent_block_types: Optional[List[str]] = None
        if query_intent == 'numeric':
            intent_block_types = ['tabela', 'financial_table', 'texto']
        elif query_intent == 'visual':
            # Task #152 — visual queries devem privilegiar gráficos/imagens
            # (evita ruído de texto genérico).
            intent_block_types = ['grafico', 'imagem']

        for q in expanded_queries[:3]:
            results = self.vector_store.search(
                query=q,
                n_results=n_results * 2,
                similarity_threshold=similarity_threshold,
                query_type=query_intent,
                block_type_filter=intent_block_types,
                conversation_id=conversation_id,
            )
            for r in results:
                doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    all_results.append(r)
        
        if tokens.possible_tickers and not is_comparative:
            for ticker in tokens.possible_tickers[:2]:
                ticker_results = self.vector_store.search_by_product(ticker, n_results=5)
                for r in ticker_results:
                    doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        r['distance'] = r.get('distance', 0.1)
                        all_results.append(r)
        
        fallback_used = False
        if len(all_results) < 2:
            db_result = self.vector_store.search_product_in_database(query)
            if db_result:
                fallback_used = True
                all_results.append({
                    'content': f"Produto: {db_result['name']} ({db_result['ticker']})\n"
                               f"Gestora: {db_result['manager']}\n"
                               f"Categoria: {db_result['category']}\n"
                               f"Descrição: {db_result['description'] or 'Sem descrição'}",
                    'metadata': db_result,
                    'distance': 0.2,
                    'source': 'database_fallback'
                })
        
        if len(all_results) < 2 and tokens.possible_tickers:
            for ticker in tokens.possible_tickers:
                all_products = self.vector_store.get_all_products()
                fuzzy_matches = FuzzyMatcher.find_best_matches(ticker, list(all_products), threshold=0.6)
                
                for match, score in fuzzy_matches[:3]:
                    match_results = self.vector_store.search_by_product(match, n_results=3)
                    for r in match_results:
                        doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                        if doc_id not in seen_ids:
                            seen_ids.add(doc_id)
                            r['distance'] = 1.0 - score
                            r['fuzzy_matched'] = match
                            all_results.append(r)
                            fallback_used = True
        
        # COMPOSITE SCORING com boost orientado por intenção
        scored_results = CompositeScorer.score_results(all_results, tokens, context, query_intent=query_intent)

        # Para comparativas: garantir pelo menos 1 bloco por entidade no resultado final
        if is_comparative and len(tokens.possible_tickers) >= 2:
            final_results = self._ensure_entity_coverage(scored_results, tokens.possible_tickers, n_results)
        else:
            final_results = scored_results[:n_results]

        # Task #152 — Reranker LLM opt-in (RAG_USE_RERANKER=1)
        reranker_kept_ids: List[str] = []
        try:
            from services import reranker as _reranker
            if _reranker.is_enabled() and len(final_results) >= 2:
                reranker_input = scored_results[: max(n_results, 8)]
                # Task #152 — não impomos cap aqui para preservar Recall@K em
                # avaliações; o agent_tools controla seu próprio cap (4) antes
                # do payload da tool. Callers de avaliação podem pedir n=12.
                reranked = _reranker.rerank(query, reranker_input, top_k=n_results)
                if reranked:
                    final_results = reranked
                    for r in final_results:
                        try:
                            bid = r.metadata.get("block_id") if hasattr(r, "metadata") else None
                            if bid is not None:
                                reranker_kept_ids.append(str(bid))
                        except Exception:
                            pass
        except Exception as _e_rr:
            print(f"[EnhancedSearch] Reranker desativado por erro: {_e_rr}")

        # Persiste reranker_kept_ids + composite_score_max nos RetrievalLogs
        # recentes desta conversa (Task #152 — observabilidade).
        composite_score_max = (
            max((r.composite_score for r in final_results), default=None)
            if final_results else None
        )
        if conversation_id and (reranker_kept_ids or composite_score_max is not None):
            try:
                self.vector_store.update_retrieval_telemetry_for_conversation(
                    conversation_id=conversation_id,
                    reranker_kept_ids=reranker_kept_ids or None,
                    composite_score_max=composite_score_max,
                )
            except Exception as _e_tl:
                print(f"[EnhancedSearch] Falha ao gravar telemetria do reranker: {_e_tl}")
        
        # Anotar metadata de intent em cada resultado para uso no agente
        for r in final_results:
            if not hasattr(r, 'extra_meta'):
                r.extra_meta = {}
            r.extra_meta['query_intent'] = query_intent
            r.extra_meta['is_comparative'] = is_comparative

        if db and final_results:
            try:
                from services.temporal_enrichment import enrich_results_with_temporal_refs
                final_results = enrich_results_with_temporal_refs(final_results, db)
            except Exception as e:
                print(f"[EnhancedSearch] Erro no enriquecimento temporal (não-bloqueante): {e}")

        duration_ms = (time.time() - start_time) * 1000
        print(f"[EnhancedSearch] query_intent={query_intent} | {len(final_results)} resultados | {duration_ms:.0f}ms")
        SearchAuditLog.log_search(
            original_query=query,
            normalized_query=normalized_query,
            tokens=tokens,
            results_count=len(final_results),
            top_result_score=final_results[0].composite_score if final_results else 0.0,
            fallback_used=fallback_used,
            search_duration_ms=duration_ms,
            conversation_id=conversation_id
        )
        
        if conversation_id and final_results:
            products_found = []
            gestoras_found = []
            for r in final_results[:3]:
                if r.metadata.get('products'):
                    products_found.extend(r.metadata['products'].split(','))
                if r.metadata.get('gestora'):
                    gestoras_found.append(r.metadata['gestora'])
            
            ConversationContextManager.update_context(
                conversation_id,
                products=products_found[:3],
                gestoras=gestoras_found[:2],
                query=query
            )
        
        return final_results

    def _ensure_entity_coverage(
        self,
        scored_results: List[SearchResult],
        tickers: List[str],
        n_results: int
    ) -> List[SearchResult]:
        """
        Para queries comparativas, garante que cada ticker tenha ao menos
        1 bloco no resultado final. Preenche lacunas com os blocos de maior
        score do ticker faltante, mesmo que estejam abaixo do corte normal.
        """
        covered = {t: False for t in tickers[:3]}
        final: List[SearchResult] = []

        for r in scored_results:
            products_meta = r.metadata.get('products', '').upper()
            for t in covered:
                if t in products_meta:
                    covered[t] = True
            final.append(r)
            if len(final) >= n_results and all(covered.values()):
                break

        # Preencher tickers não cobertos
        if not all(covered.values()):
            for t, is_covered in covered.items():
                if not is_covered:
                    extra = self.vector_store.search_by_product(t, n_results=2)
                    for r in extra:
                        doc_id = r.get('metadata', {}).get('block_id', r.get('content', '')[:50])
                        if doc_id not in {
                            res.metadata.get('block_id', res.content[:50]) for res in final
                        }:
                            sr = SearchResult(
                                content=r.get('content', ''),
                                metadata=r.get('metadata', {}),
                                vector_distance=r.get('distance', 0.3),
                                vector_score=max(0, 1.0 - r.get('distance', 0.3)),
                                source='entity_coverage_fallback'
                            )
                            sr.calculate_composite_score()
                            final.append(sr)
                            break

        return final[:n_results]
    
    def get_search_stats(self) -> Dict:
        """Retorna estatísticas de busca."""
        return SearchAuditLog.get_stats()
    
    def get_failed_searches(self, limit: int = 50) -> List[Dict]:
        """Retorna buscas que falharam."""
        return SearchAuditLog.get_failed_searches(limit)


# Função helper para criar instância
def get_enhanced_search():
    """Retorna instância do EnhancedSearch."""
    from services.vector_store import get_vector_store
    return EnhancedSearch(get_vector_store())
