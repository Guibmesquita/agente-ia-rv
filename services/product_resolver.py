"""
ProductResolver — Serviço centralizado de resolução de produtos.
Ponto único de decisão para vincular documentos a produtos existentes.

Camadas de matching (em ordem de prioridade):
1. Ticker exato → vincula automaticamente (100% confiança)
2. Aliases → vincula automaticamente (nomes alternativos confirmados por humano)
3. Fuzzy melhorado → sugere candidatos (nunca vincula sozinho)
   - Gestora como boost de score, não como critério independente
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

from sqlalchemy.orm import Session

from services.document_metadata_extractor import (
    normalize_text,
    normalize_product_name,
    tokenize_product_name,
    calculate_similarity_score,
    STOPWORDS_PRODUTOS,
)


@dataclass
class ResolverCandidate:
    product_id: int
    product_name: str
    product_ticker: Optional[str]
    product_manager: Optional[str]
    score: float
    match_layer: str
    tokens_matched: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolverResult:
    matched_product_id: Optional[int] = None
    matched_product_name: Optional[str] = None
    matched_product_ticker: Optional[str] = None
    match_type: Optional[str] = None
    match_confidence: float = 0.0
    candidates: List[ResolverCandidate] = field(default_factory=list)
    decision_log: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_confident(self) -> bool:
        return self.match_type in ("ticker_exact", "alias_exact") and self.matched_product_id is not None

    @property
    def has_candidates(self) -> bool:
        return len(self.candidates) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "matched_product_id": self.matched_product_id,
            "matched_product_name": self.matched_product_name,
            "matched_product_ticker": self.matched_product_ticker,
            "match_type": self.match_type,
            "match_confidence": self.match_confidence,
            "is_confident": self.is_confident,
            "candidates": [c.to_dict() for c in self.candidates],
            "decision_log": self.decision_log,
        }


FINANCIAL_PREFIXES = [
    "fii", "fundo de investimento imobiliario", "fundo imobiliario",
    "fundo de investimento", "fundo", "fi",
]

FINANCIAL_SUFFIXES = [
    "fii", "feeder", "master", "ipca+", "ipca", "cdi+", "cdi",
    "pre", "pré", "renda fixa", "credito", "crédito",
]


def _deep_normalize(name: str) -> str:
    if not name:
        return ""
    normalized = normalize_text(name)
    normalized = re.sub(r'[^\w\s+]', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def _extract_significant_tokens(name: str) -> set:
    deep = _deep_normalize(name)
    tokens = set(deep.split())
    stopwords_extended = STOPWORDS_PRODUTOS | {
        "ipca", "cdi", "pre", "pré", "renda", "fixa",
        "credito", "crédito", "real", "estate", "prime",
    }
    return tokens - stopwords_extended


class ProductResolver:
    def __init__(self, db: Session):
        self.db = db
        self._products_cache = None
        self._cache_timestamp = None

    def _load_products(self, force_reload: bool = False) -> list:
        from database.models import Product
        if self._products_cache is not None and not force_reload:
            return self._products_cache

        products = self.db.query(Product).filter(
            Product.status == "ativo"
        ).all()

        self._products_cache = [
            {
                "id": p.id,
                "name": p.name,
                "ticker": p.ticker,
                "manager": p.manager,
                "category": p.category,
                "aliases": p.get_aliases() if hasattr(p, 'get_aliases') else [],
                "_obj": p,
            }
            for p in products
            if not p.ticker or not p.ticker.startswith("__SYSTEM")
        ]
        self._cache_timestamp = datetime.utcnow()
        return self._products_cache

    def resolve(
        self,
        fund_name: Optional[str] = None,
        ticker: Optional[str] = None,
        gestora: Optional[str] = None,
        confidence: float = 0.5,
        fuzzy_threshold: float = 0.55,
        max_candidates: int = 5,
    ) -> ResolverResult:
        products = self._load_products()
        result = ResolverResult()
        result.decision_log = {
            "input": {
                "fund_name": fund_name,
                "ticker": ticker,
                "gestora": gestora,
                "confidence": confidence,
            },
            "layers": [],
            "timestamp": datetime.utcnow().isoformat(),
        }

        layer1 = self._layer1_ticker_exact(ticker, products)
        result.decision_log["layers"].append(layer1["log"])
        if layer1["match"]:
            p = layer1["match"]
            result.matched_product_id = p["id"]
            result.matched_product_name = p["name"]
            result.matched_product_ticker = p["ticker"]
            result.match_type = "ticker_exact"
            result.match_confidence = 1.0
            print(f"[ProductResolver] L1 Ticker exato: {ticker} → {p['name']} (id={p['id']})")
            return result

        layer2 = self._layer2_alias_match(fund_name, products)
        result.decision_log["layers"].append(layer2["log"])
        if layer2["match"]:
            p = layer2["match"]
            result.matched_product_id = p["id"]
            result.matched_product_name = p["name"]
            result.matched_product_ticker = p["ticker"]
            result.match_type = "alias_exact"
            result.match_confidence = 0.95
            print(f"[ProductResolver] L2 Alias: '{fund_name}' → {p['name']} (id={p['id']})")
            return result

        layer3 = self._layer3_fuzzy(fund_name, gestora, products, fuzzy_threshold, max_candidates)
        result.decision_log["layers"].append(layer3["log"])
        result.candidates = layer3["candidates"]

        if layer3["candidates"]:
            best = layer3["candidates"][0]
            if best.score >= 0.85:
                result.matched_product_id = best.product_id
                result.matched_product_name = best.product_name
                result.matched_product_ticker = best.product_ticker
                result.match_type = "fuzzy_high_confidence"
                result.match_confidence = best.score
                print(f"[ProductResolver] L3 Fuzzy alto: '{fund_name}' → {best.product_name} (score={best.score})")
            else:
                result.match_type = "fuzzy_candidates"
                result.match_confidence = best.score
                print(f"[ProductResolver] L3 Fuzzy candidatos: '{fund_name}' → {len(layer3['candidates'])} candidatos (best={best.score})")
        else:
            result.match_type = "no_match"
            result.match_confidence = 0.0
            print(f"[ProductResolver] Nenhum match para: fund_name='{fund_name}', ticker='{ticker}'")

        return result

    def _layer1_ticker_exact(self, ticker: Optional[str], products: list) -> Dict:
        log = {"layer": "L1_ticker_exact", "input": ticker, "result": None}
        if not ticker:
            log["result"] = "skipped_no_ticker"
            return {"match": None, "log": log}

        ticker_norm = normalize_text(ticker)
        for p in products:
            if p["ticker"] and normalize_text(p["ticker"]) == ticker_norm:
                log["result"] = f"matched: {p['name']} (id={p['id']})"
                return {"match": p, "log": log}

        log["result"] = f"no_match_for_{ticker}"
        return {"match": None, "log": log}

    def _layer2_alias_match(self, fund_name: Optional[str], products: list) -> Dict:
        log = {"layer": "L2_alias", "input": fund_name, "result": None, "checked": 0}
        if not fund_name:
            log["result"] = "skipped_no_fund_name"
            return {"match": None, "log": log}

        fund_norm = _deep_normalize(fund_name)
        total_aliases = 0

        for p in products:
            aliases = p.get("aliases", [])
            name_norm = _deep_normalize(p["name"])
            if name_norm == fund_norm:
                log["result"] = f"exact_name_match: {p['name']} (id={p['id']})"
                return {"match": p, "log": log}

            for alias in aliases:
                total_aliases += 1
                alias_norm = _deep_normalize(alias)
                if alias_norm == fund_norm:
                    log["result"] = f"alias_match: '{alias}' → {p['name']} (id={p['id']})"
                    return {"match": p, "log": log}

        log["checked"] = total_aliases
        log["result"] = f"no_alias_match (checked {total_aliases} aliases)"
        return {"match": None, "log": log}

    def _layer3_fuzzy(
        self,
        fund_name: Optional[str],
        gestora: Optional[str],
        products: list,
        threshold: float,
        max_candidates: int,
    ) -> Dict:
        log = {
            "layer": "L3_fuzzy",
            "input": fund_name,
            "gestora": gestora,
            "threshold": threshold,
            "evaluated": 0,
            "above_threshold": 0,
        }
        candidates = []

        if not fund_name:
            log["result"] = "skipped_no_fund_name"
            return {"candidates": [], "log": log}

        gestora_norm = _deep_normalize(gestora) if gestora else None

        for p in products:
            product_name = p["name"]
            if not product_name:
                continue

            log["evaluated"] += 1

            similarity = calculate_similarity_score(fund_name, product_name)
            base_score = similarity["composite_score"]

            best_alias_score = 0.0
            best_alias = None
            for alias in p.get("aliases", []):
                alias_sim = calculate_similarity_score(fund_name, alias)
                if alias_sim["composite_score"] > best_alias_score:
                    best_alias_score = alias_sim["composite_score"]
                    best_alias = alias

            effective_score = max(base_score, best_alias_score)

            gestora_boost = 0.0
            if gestora_norm and p.get("manager"):
                manager_norm = _deep_normalize(p["manager"])
                if gestora_norm in manager_norm or manager_norm in gestora_norm:
                    gestora_boost = 0.10
                elif any(tok in manager_norm.split() for tok in gestora_norm.split() if len(tok) > 2):
                    gestora_boost = 0.05

            final_score = min(effective_score + gestora_boost, 1.0)

            if final_score >= threshold or similarity["tokens_matched"] >= 2:
                log["above_threshold"] += 1
                candidates.append(ResolverCandidate(
                    product_id=p["id"],
                    product_name=product_name,
                    product_ticker=p.get("ticker"),
                    product_manager=p.get("manager"),
                    score=round(final_score, 3),
                    match_layer="fuzzy",
                    tokens_matched=similarity["tokens_matched"],
                    details={
                        "base_score": round(base_score, 3),
                        "best_alias_score": round(best_alias_score, 3),
                        "best_alias": best_alias,
                        "gestora_boost": gestora_boost,
                        "similarity": {
                            "sequence_ratio": similarity["sequence_ratio"],
                            "token_jaccard": similarity["token_jaccard"],
                            "tokens_matched": similarity["tokens_matched"],
                        },
                    },
                ))

        candidates.sort(key=lambda c: (c.score, c.tokens_matched), reverse=True)
        candidates = candidates[:max_candidates]

        log["result"] = f"{len(candidates)} candidates found"
        if candidates:
            log["top_candidates"] = [
                {"name": c.product_name, "score": c.score, "tokens": c.tokens_matched}
                for c in candidates[:3]
            ]

        return {"candidates": candidates, "log": log}

    def save_alias_on_match(self, product_id: int, alias_name: str) -> bool:
        from database.models import Product
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return False

        if _deep_normalize(alias_name) == _deep_normalize(product.name):
            return False

        added = product.add_alias(alias_name)
        if added:
            self.db.commit()
            print(f"[ProductResolver] Alias salvo: '{alias_name}' → {product.name} (id={product_id})")
        return added


_resolver_instance = None


def get_product_resolver(db: Session) -> ProductResolver:
    return ProductResolver(db)
