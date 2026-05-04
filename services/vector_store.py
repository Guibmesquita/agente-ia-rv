"""
Gerenciador do banco de dados vetorial usando pgvector (PostgreSQL).
Permite armazenar e buscar documentos usando embeddings.
"""
import json
import re
from openai import OpenAI
from typing import List, Optional, Set, Dict, Tuple
from core.config import get_settings
from services.cost_tracker import cost_tracker
from database.database import SessionLocal
from database.models import DocumentEmbedding
from sqlalchemy import text as sql_text


TICKER_PATTERN = re.compile(r'\b([A-Z]{4,5})\s*(?:1[0-3]|[3-9])\b', re.IGNORECASE)

PUBLISH_STATUS_FILTER = "AND publish_status NOT IN ('rascunho', 'arquivado')"


def _log_zero_results(query_label: str, query_text: str):
    """Log diagnóstico quando busca retorna zero resultados."""
    try:
        db = SessionLocal()
        try:
            total = db.execute(sql_text("SELECT COUNT(*) FROM document_embeddings")).scalar()
            published = db.execute(sql_text(
                "SELECT COUNT(*) FROM document_embeddings "
                "WHERE publish_status NOT IN ('rascunho', 'arquivado')"
            )).scalar()
            print(
                f"[VECTORSTORE] {query_label} retornou 0 resultados. "
                f"Base: {published} publicados / {total} total. "
                f"Query: '{query_text[:80]}'"
            )
        finally:
            db.close()
    except Exception as e:
        print(f"[VECTORSTORE] Erro ao logar zero resultados: {e}")


KNOWN_MANAGERS = {
    "manati": "Manatí Capital",
    "manatí": "Manatí Capital",
    "tg core": "TG Core",
    "tgcore": "TG Core",
    "xp": "XP Asset",
    "hglg": "CSHG",
    "cshg": "CSHG",
    "kinea": "Kinea",
    "hedge": "Hedge Investments",
    "bresco": "Bresco",
    "vinci": "Vinci Partners",
    "rbrp": "RBR",
    "rbr": "RBR",
}


def _safe_load_key_info(raw) -> dict:
    """Carrega `Product.key_info` (str JSON) de forma resiliente."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def extract_tickers_from_query(query: str) -> List[str]:
    """
    Extrai tickers de uma query (FIIs e ações).
    Padrão: 4-5 letras + número (ex: MANA11, VIVT3, VALE3, XPLG11)
    
    Args:
        query: Texto da query do usuário
        
    Returns:
        Lista de tickers encontrados (uppercase, sem espaço)
    """
    full_pattern = re.compile(r'\b([A-Z]{4,5}\s*(?:1[0-3]|[3-9]))\b', re.IGNORECASE)
    matches = full_pattern.findall(query)
    return [m.upper().replace(" ", "") for m in matches]


def extract_manager_from_query(query: str) -> Optional[str]:
    """
    Detecta se a query menciona uma gestora conhecida.
    
    Args:
        query: Texto da query do usuário
        
    Returns:
        Nome normalizado da gestora ou None
    """
    query_lower = query.lower()
    
    for keyword, manager_name in KNOWN_MANAGERS.items():
        if keyword in query_lower:
            return manager_name
    
    return None


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calcula a distância de Levenshtein entre duas strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
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

settings = get_settings()

KNOWN_METADATA_FIELDS = [
    'product_name', 'product_ticker', 'gestora', 'category', 'source',
    'title', 'block_type', 'material_type', 'publish_status', 'topic',
    'concepts', 'keywords', 'strategy', 'valid_until', 'structure_slug',
    'tab', 'has_diagram', 'diagram_image_path',
    # Task #152 — data parseada de validade, usada pelo CompositeScorer
    'valid_until_dt',
    # Task #152 — versão do embedding (2 = gerado a partir de content_for_embedding markdown)
    'embedding_version',
    # NOTA Task #153 — `product_type` e `product_id` NÃO entram aqui de propósito:
    # não há colunas correspondentes em `document_embeddings`. Eles são propagados
    # via `extra_metadata` (JSON) e re-hidratados em `_row_to_metadata`.
]

FIELD_MAP_TO_COLUMN = {
    'created_at': 'created_at_source',
    'block_id': 'block_id',
    'material_id': 'material_id',
    'type': 'doc_type',
}


class VectorStore:
    """Gerenciador de busca semântica usando pgvector e OpenAI embeddings."""
    
    def __init__(self):
        self.openai_client = None
        if settings.OPENAI_API_KEY:
            self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        self._products_cache = None
    
    def _row_to_metadata(self, row):
        meta = {}
        for field in KNOWN_METADATA_FIELDS:
            val = getattr(row, field, None)
            if val is not None:
                meta[field] = val
        if row.created_at_source:
            meta['created_at'] = row.created_at_source
        if row.block_id:
            meta['block_id'] = row.block_id
        if row.material_id:
            meta['material_id'] = row.material_id
        if row.doc_type:
            meta['type'] = row.doc_type
        if row.extra_metadata:
            try:
                extra = json.loads(row.extra_metadata)
                for k, v in extra.items():
                    if k not in meta:
                        meta[k] = v
            except Exception:
                pass
        return meta
    
    def _metadata_to_columns(self, metadata: dict) -> dict:
        if not metadata:
            return {'extra_metadata': None}
        
        columns = {}
        extra = {}
        
        for key, value in metadata.items():
            if key in KNOWN_METADATA_FIELDS:
                columns[key] = value
            elif key in FIELD_MAP_TO_COLUMN:
                columns[FIELD_MAP_TO_COLUMN[key]] = value
            else:
                extra[key] = value
        
        columns['extra_metadata'] = json.dumps(extra) if extra else None
        return columns
    
    def get_all_products(self) -> Dict[str, Dict]:
        """
        Retorna todos os produtos únicos indexados na base.
        
        Returns:
            Dict[ticker, {name, gestora_inferred}]
        """
        if self._products_cache is not None:
            return self._products_cache
        
        db = SessionLocal()
        try:
            rows = db.execute(sql_text(
                "SELECT DISTINCT product_ticker, product_name FROM document_embeddings "
                f"WHERE product_ticker IS NOT NULL AND product_ticker != '' {PUBLISH_STATUS_FILTER}"
            )).fetchall()
            
            products = {}
            for row in rows:
                ticker = row[0]
                name = row[1] or ''
                if ticker and ticker not in products:
                    gestora = self._infer_gestora_from_name(name)
                    products[ticker] = {
                        'name': name,
                        'gestora': gestora
                    }
            
            self._products_cache = products
            return products
        finally:
            db.close()
    
    def _infer_gestora_from_name(self, product_name: str) -> str:
        """
        Infere a gestora a partir do nome do produto.
        Ex: "MANATÍ HEDGE FUND FII" -> "Manatí Capital"
        """
        name_lower = product_name.lower()
        
        for keyword, manager_name in KNOWN_MANAGERS.items():
            if keyword in name_lower:
                return manager_name
        
        return "Desconhecida"
    
    def get_products_by_manager(self, manager_name: str) -> List[Dict]:
        """
        Lista todos os produtos de uma gestora específica.
        
        Args:
            manager_name: Nome normalizado da gestora
            
        Returns:
            Lista de produtos [{ticker, name, gestora}]
        """
        all_products = self.get_all_products()
        
        matches = []
        for ticker, info in all_products.items():
            if info['gestora'] == manager_name:
                matches.append({
                    'ticker': ticker,
                    'name': info['name'],
                    'gestora': info['gestora']
                })
        
        return matches
    
    def detect_ambiguous_query(self, query: str) -> Optional[Dict]:
        """
        Detecta se uma query é ambígua (menciona gestora sem ticker específico).
        
        Args:
            query: Texto da query do usuário
            
        Returns:
            Dict com info de desambiguação ou None se não ambígua
            {
                'type': 'manager_ambiguous',
                'manager': 'Manatí Capital',
                'products': [...]
            }
        """
        tickers = extract_tickers_from_query(query)
        if tickers:
            return None
        
        manager = extract_manager_from_query(query)
        if not manager:
            return None
        
        products = self.get_products_by_manager(manager)
        
        if len(products) == 0:
            return None
        
        if len(products) == 1:
            return {
                'type': 'manager_single',
                'manager': manager,
                'products': products,
                'inferred_ticker': products[0]['ticker']
            }
        
        return {
            'type': 'manager_ambiguous',
            'manager': manager,
            'products': products
        }
    
    def _generate_embedding(self, text: str) -> List[float]:
        """
        Gera um embedding para o texto usando text-embedding-3-large.
        
        NOTA: O upgrade de 3-small para 3-large oferece +15-30% de precisão semântica.
        Todos os novos documentos serão indexados com 3-large.
        Documentos existentes devem ser reindexados para evitar dimensões incompatíveis.
        
        Args:
            text: Texto para gerar embedding
            
        Returns:
            Lista de floats representando o embedding (3072 dimensões para 3-large)
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key não configurada")
        
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=3072
        )
        try:
            if response.usage:
                cost_tracker.track_openai_embedding(
                    model='text-embedding-3-large',
                    total_tokens=response.usage.total_tokens
                )
        except Exception:
            pass
        return response.data[0].embedding
    
    def add_document(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """
        Adiciona um documento à base de conhecimento.
        
        Args:
            doc_id: ID único do documento
            text: Conteúdo do documento
            metadata: Metadados opcionais (título, fonte, etc.)
        """
        embedding = self._generate_embedding(text)
        embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
        
        columns = self._metadata_to_columns(metadata or {})
        
        db = SessionLocal()
        try:
            set_clauses = ["content = :content", "embedding = :embedding"]
            params = {
                'doc_id': doc_id,
                'content': text,
                'embedding': embedding_str,
            }
            
            col_names = ['doc_id', 'content', 'embedding']
            col_placeholders = [':doc_id', ':content', ':embedding']
            
            for col_key, col_val in columns.items():
                params[col_key] = col_val
                col_names.append(col_key)
                col_placeholders.append(f':{col_key}')
                set_clauses.append(f"{col_key} = :{col_key}")
            
            query = sql_text(
                f"INSERT INTO document_embeddings ({', '.join(col_names)}) "
                f"VALUES ({', '.join(col_placeholders)}) "
                f"ON CONFLICT (doc_id) DO UPDATE SET {', '.join(set_clauses)}"
            )
            db.execute(query, params)
            db.commit()
        finally:
            db.close()
    
    def add_documents(self, doc_ids: List[str], texts: List[str], metadatas: Optional[List[dict]] = None) -> None:
        """
        Adiciona múltiplos documentos à base de conhecimento.
        
        Args:
            doc_ids: Lista de IDs únicos
            texts: Lista de conteúdos
            metadatas: Lista de metadados opcionais
        """
        metas = metadatas or [{}] * len(texts)
        for i, (doc_id, text) in enumerate(zip(doc_ids, texts)):
            self.add_document(doc_id, text, metas[i])
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Remove um documento da base de conhecimento.
        
        Args:
            doc_id: ID do documento a remover
            
        Returns:
            True se removido com sucesso
        """
        try:
            db = SessionLocal()
            try:
                db.execute(sql_text("DELETE FROM document_embeddings WHERE doc_id = :doc_id"), {'doc_id': doc_id})
                db.commit()
                return True
            finally:
                db.close()
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao deletar documento {doc_id}: {e}")
            return False
    
    def reset_collection_for_migration(self) -> dict:
        """
        Reseta a collection para migração de modelo de embeddings.
        ATENÇÃO: Isso deleta todos os vetores existentes!
        Após chamar, é necessário reindexar todos os materiais.
        
        USAR QUANDO:
        - Mudar modelo de embeddings (ex: 3-small → 3-large)
        - Mudar dimensões dos vetores
        - Resolver problemas de dimensões incompatíveis
        
        Returns:
            dict com status da operação
        """
        try:
            db = SessionLocal()
            try:
                old_count_result = db.execute(sql_text("SELECT COUNT(*) FROM document_embeddings")).scalar()
                old_count = old_count_result or 0
                
                db.execute(sql_text("TRUNCATE TABLE document_embeddings"))
                db.commit()
                
                return {
                    "success": True,
                    "old_count": old_count,
                    "message": f"Collection resetada. {old_count} documentos removidos. Reindexação necessária."
                }
            finally:
                db.close()
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _classify_query_type(self, query: str) -> str:
        """
        Classifica o tipo de pergunta para re-ranking apropriado.
        
        Returns:
            'numeric' para perguntas sobre taxas/valores/números
            'conceptual' para perguntas conceituais
            'ticker' para perguntas sobre produto específico
        """
        query_lower = query.lower()
        
        numeric_keywords = [
            'taxa', 'taxas', 'valor', 'valores', 'custo', 'custos', 
            'preço', 'preco', 'rendimento', 'yield', 'dividend', 'dividendo',
            'quanto', 'qual o valor', 'percentual', '%', 'rentabilidade',
            'performance', 'retorno', 'cotação', 'cotacao', 'p/vp', 'pvp'
        ]
        
        ticker_patterns = ['qual', 'sobre', 'me fala', 'informações', 'informacoes']
        
        for keyword in numeric_keywords:
            if keyword in query_lower:
                return 'numeric'
        
        return 'conceptual'
    
    def search(self, query: str, n_results: int = 3, product_filter: str = None, 
               similarity_threshold: float = 1.5, query_type: str = None,
               block_type_filter: Optional[List[str]] = None,
               conversation_id: Optional[str] = None) -> List[dict]:
        """
        Busca documentos relevantes para a consulta usando ranking híbrido inteligente.
        
        ESTRATÉGIA DE BUSCA HÍBRIDA:
        1. Detecta tickers na query (ex: MANA11)
        2. Expande query com conceitos financeiros (glossário de RV)
        3. Se ticker detectado: busca PRIMEIRO por metadados (alta precisão)
        4. Complementa com busca semântica (threshold ajustado)
        5. Merge priorizando resultados de metadados
        
        RANKING HÍBRIDO:
        - Vetor (70%): similaridade semântica
        - Recência (20%): documentos mais novos
        - Match exato (10%): ticker/produto exato na query
        
        Args:
            query: Pergunta ou consulta do usuário
            n_results: Número máximo de resultados
            product_filter: Filtrar por produto específico (opcional)
            similarity_threshold: Threshold máximo de distância (default 1.5)
            query_type: Tipo de query detectado upstream ('temporal', 'numeric', etc.)
                        Para 'temporal': SQL ordena primeiramente por created_at DESC
                        antes do composite scorer aplicar recency_weight=0.25
            
        Returns:
            Lista de documentos relevantes com scores
        """
        if not self.openai_client:
            print("[VECTORSTORE] search() abortado: openai_client é None. "
                  "VectorStore não foi inicializado corretamente. "
                  f"OPENAI_API_KEY presente: {bool(settings.OPENAI_API_KEY)}")
            if settings.OPENAI_API_KEY:
                try:
                    self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                    print("[VECTORSTORE] openai_client recuperado com sucesso via lazy init!")
                except Exception as e:
                    print(f"[VECTORSTORE] Falha ao recuperar openai_client: {e}")
                    return []
            else:
                return []
        
        detected_tickers = extract_tickers_from_query(query)
        has_ticker = len(detected_tickers) > 0
        
        try:
            from services.financial_concepts import expand_query
            concept_expansion = expand_query(query)
            expanded_terms = concept_expansion.get("termos_busca_adicionais", [])
            detected_concepts = concept_expansion.get("conceitos_detectados", [])
            concept_context = concept_expansion.get("contexto_agente", "")
            
            if detected_concepts:
                print(f"[VECTOR_STORE] Conceitos financeiros detectados: {detected_concepts}")
        except Exception as e:
            expanded_terms = []
            detected_concepts = []
            concept_context = ""
            print(f"[VECTOR_STORE] Erro na expansão de conceitos: {e}")
        
        ticker_results = []
        if has_ticker:
            for ticker in detected_tickers[:2]:
                ticker_docs = self.search_by_ticker(ticker, n_results=n_results * 2)
                ticker_results.extend(ticker_docs)
                print(f"[VECTOR_STORE] Busca por ticker {ticker}: {len(ticker_docs)} blocos encontrados")
        
        if expanded_terms and detected_concepts:
            top_terms = expanded_terms[:8]
            enriched_query = f"{query} {' '.join(top_terms)}"
            query_embedding = self._generate_embedding(enriched_query)
            print(f"[VECTOR_STORE] Query expandida com {len(top_terms)} termos: {top_terms[:5]}...")
        else:
            query_embedding = self._generate_embedding(query)
        
        # Usar query_type passado upstream (EnhancedSearch) ou detectar localmente como fallback
        effective_query_type = query_type or self._classify_query_type(query)
        
        fetch_count = n_results * 3
        # Para queries temporais, buscar mais candidatos para garantir cobertura
        # de documentos recentes que podem ter score vetorial levemente menor
        if effective_query_type == 'temporal':
            fetch_count = n_results * 5

        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

        # Para queries temporais: ORDER BY mistura distância vetorial e created_at
        # para dar peso extra a documentos recentes sem descartar relevância semântica.
        # Usa-se um score combinado: 0.7 * distância vetorial + 0.3 * penalização de idade
        if effective_query_type == 'temporal':
            order_clause = (
                "(embedding <=> :query_vec) * 0.7 + "
                "GREATEST(0, EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 / 365.0) * 0.3"
            )
            print(f"[VECTOR_STORE] Modo temporal: ORDER BY híbrido vetorial+recência")
        else:
            order_clause = "embedding <=> :query_vec"

        # Filtro de block_type opcional (Task #152 — vinculado a query_intent)
        block_type_clause = ""
        block_type_params: dict = {}
        if block_type_filter:
            placeholders = []
            for i, bt in enumerate(block_type_filter):
                key = f"bt_{i}"
                placeholders.append(f":{key}")
                block_type_params[key] = bt
            block_type_clause = f" AND block_type IN ({', '.join(placeholders)})"
            print(f"[VECTOR_STORE] Filtro block_type ativo: {block_type_filter}")

        db = SessionLocal()
        try:
            base_params = {'query_vec': embedding_str, 'fetch_count': fetch_count}
            base_params.update(block_type_params)
            if product_filter:
                try:
                    params = {**base_params, 'product_filter': product_filter.upper()}
                    rows = db.execute(sql_text(
                        f"SELECT *, (embedding <=> :query_vec) as distance "
                        f"FROM document_embeddings "
                        f"WHERE product_ticker = :product_filter "
                        f"{PUBLISH_STATUS_FILTER} "
                        f"{block_type_clause} "
                        f"ORDER BY {order_clause} "
                        f"LIMIT :fetch_count"
                    ), params).fetchall()
                except Exception as e:
                    print(f"[VECTOR_STORE] Erro com filtro, buscando sem filtro: {e}")
                    rows = db.execute(sql_text(
                        f"SELECT *, (embedding <=> :query_vec) as distance "
                        f"FROM document_embeddings "
                        f"WHERE 1=1 {PUBLISH_STATUS_FILTER} "
                        f"{block_type_clause} "
                        f"ORDER BY {order_clause} "
                        f"LIMIT :fetch_count"
                    ), base_params).fetchall()
            else:
                rows = db.execute(sql_text(
                    f"SELECT *, (embedding <=> :query_vec) as distance "
                    f"FROM document_embeddings "
                    f"WHERE 1=1 {PUBLISH_STATUS_FILTER} "
                    f"{block_type_clause} "
                    f"ORDER BY {order_clause} "
                    f"LIMIT :fetch_count"
                ), base_params).fetchall()
            print(f"[VECTOR_STORE] SQL retornou {len(rows)} rows (fetch_count={fetch_count}, query_type={effective_query_type})")
        finally:
            db.close()
        
        documents = []
        if rows:
            from datetime import datetime
            now = datetime.now()
            
            query_upper = query.upper()
            
            for row in rows:
                metadata = {}
                for field in KNOWN_METADATA_FIELDS:
                    val = getattr(row, field, None) if hasattr(row, field) else row._mapping.get(field)
                    if val is not None:
                        metadata[field] = val
                
                created_at_source = getattr(row, 'created_at_source', None) if hasattr(row, 'created_at_source') else row._mapping.get('created_at_source')
                if created_at_source:
                    metadata['created_at'] = created_at_source
                block_id_val = getattr(row, 'block_id', None) if hasattr(row, 'block_id') else row._mapping.get('block_id')
                if block_id_val:
                    metadata['block_id'] = block_id_val
                material_id_val = getattr(row, 'material_id', None) if hasattr(row, 'material_id') else row._mapping.get('material_id')
                if material_id_val:
                    metadata['material_id'] = material_id_val
                doc_type_val = getattr(row, 'doc_type', None) if hasattr(row, 'doc_type') else row._mapping.get('doc_type')
                if doc_type_val:
                    metadata['type'] = doc_type_val
                
                extra_meta_val = getattr(row, 'extra_metadata', None) if hasattr(row, 'extra_metadata') else row._mapping.get('extra_metadata')
                if extra_meta_val:
                    try:
                        extra = json.loads(extra_meta_val)
                        for k, v in extra.items():
                            if k not in metadata:
                                metadata[k] = v
                    except Exception:
                        pass
                
                doc_content = row._mapping.get('content', '') if hasattr(row, '_mapping') else getattr(row, 'content', '')
                original_distance = row._mapping.get('distance', 0) if hasattr(row, '_mapping') else getattr(row, 'distance', 0)
                doc_id = row._mapping.get('doc_id', '') if hasattr(row, '_mapping') else getattr(row, 'doc_id', '')
                
                valid_until_str = metadata.get("valid_until", "")
                if valid_until_str:
                    try:
                        if 'T' in valid_until_str:
                            valid_until = datetime.fromisoformat(valid_until_str.replace('Z', '+00:00'))
                            if valid_until.tzinfo:
                                valid_until = valid_until.replace(tzinfo=None)
                        else:
                            valid_until = datetime.strptime(valid_until_str[:10], "%Y-%m-%d")
                        if valid_until < now:
                            continue
                    except Exception:
                        pass
                
                publish_status = metadata.get("publish_status", "publicado")
                if publish_status in ["rascunho", "arquivado"]:
                    continue
                
                if original_distance > similarity_threshold:
                    continue
                
                # NÍVEL 1 SIMPLIFICADO: Apenas distância cosseno + filtros.
                # O ranking final é feito pelo CompositeScorer no EnhancedSearch (Nível 2),
                # que aplica fuzzy, ticker, gestora, contexto e recência.
                # Este nível serve apenas como seleção de candidatos por proximidade vetorial.
                documents.append({
                    "content": doc_content,
                    "metadata": metadata,
                    "distance": original_distance,
                    "source": "vector"
                })
        
        documents.sort(key=lambda x: x.get("distance", 1.0))
        
        all_documents = []
        seen_ids = set()
        
        for doc in ticker_results:
            doc_id = doc.get('doc_id') or doc.get('chroma_id') or doc.get('metadata', {}).get('block_id') or f"ticker_{len(seen_ids)}"
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                if 'distance' not in doc:
                    doc['distance'] = 0.05
                all_documents.append(doc)
        
        for doc in documents:
            doc_id = doc.get('doc_id') or doc.get('chroma_id') or doc.get('metadata', {}).get('block_id') or f"semantic_{len(seen_ids)}"
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                all_documents.append(doc)
        
        all_documents.sort(key=lambda x: x.get("distance", 1.0))
        
        deduplicated = self._deduplicate_results(all_documents)
        
        final_results = deduplicated[:n_results]
        
        if not final_results:
            _log_zero_results("search()", query)
        
        if has_ticker:
            print(f"[VECTOR_STORE] Busca híbrida: {len(ticker_results)} por ticker + {len(documents)} semânticos = {len(final_results)} finais")
        
        self._log_retrieval(
            query=query,
            query_type=query_type,
            results=final_results,
            total_candidates=len(all_documents),
            threshold=similarity_threshold,
            conversation_id=conversation_id,
        )

        self._annotate_committee_flags(final_results)

        return final_results

    def _annotate_committee_flags(self, results: List[dict]) -> None:
        """
        Enriquece metadata de cada chunk com:
          - is_committee_active: Material.is_committee_active
          - excluded_from_committee: MaterialProductLink.excluded_from_committee
            para o par (material_id, product_ticker) do chunk.
        Usado pelo agente para decidir [COMITÊ] vs [NÃO-COMITÊ] com isolamento por produto.
        """
        if not results:
            return
        try:
            from database.database import SessionLocal
            from database.models import Material, MaterialProductLink, Product as ProductModel
            from sqlalchemy import and_, func as _sa_func

            material_ids = set()
            pairs = set()
            for r in results:
                meta = r.get("metadata") or {}
                try:
                    mid = int(meta.get("material_id")) if meta.get("material_id") else None
                except Exception:
                    mid = None
                if mid:
                    material_ids.add(mid)
                ticker = (meta.get("product_ticker") or meta.get("ticker") or "").strip().upper()
                if mid and ticker:
                    pairs.add((mid, ticker))

            if not material_ids:
                return

            db = SessionLocal()
            try:
                mat_flag = dict(
                    db.query(Material.id, Material.is_committee_active)
                      .filter(Material.id.in_(material_ids))
                      .all()
                )

                excluded_set = set()
                if pairs:
                    ticker_to_pids = {}
                    tickers = {tk for _, tk in pairs}
                    if tickers:
                        prod_rows = db.query(ProductModel.id, ProductModel.ticker).filter(
                            _sa_func.upper(ProductModel.ticker).in_([t.upper() for t in tickers])
                        ).all()
                        for pid, tk in prod_rows:
                            tkn = (tk or "").strip().upper()
                            if tkn:
                                ticker_to_pids.setdefault(tkn, set()).add(pid)

                    mat_pid_pairs = []
                    for mid, tk in pairs:
                        for pid in ticker_to_pids.get(tk, []):
                            mat_pid_pairs.append((mid, pid))
                    if mat_pid_pairs:
                        mids_for_q = {m for m, _ in mat_pid_pairs}
                        pids_for_q = {p for _, p in mat_pid_pairs}
                        excl_rows = db.query(
                            MaterialProductLink.material_id,
                            MaterialProductLink.product_id,
                        ).filter(
                            MaterialProductLink.material_id.in_(mids_for_q),
                            MaterialProductLink.product_id.in_(pids_for_q),
                            MaterialProductLink.excluded_from_committee == True,
                        ).all()
                        excl_set_db = {(m, p) for m, p in excl_rows}
                        for mid, pid in mat_pid_pairs:
                            if (mid, pid) in excl_set_db:
                                excluded_set.add((mid, pid))

                for r in results:
                    meta = r.get("metadata") or {}
                    try:
                        mid = int(meta.get("material_id")) if meta.get("material_id") else None
                    except Exception:
                        mid = None
                    is_active = bool(mat_flag.get(mid, False)) if mid else False
                    ticker = (meta.get("product_ticker") or meta.get("ticker") or "").strip().upper()
                    excluded = False
                    if mid and ticker:
                        for pid in ticker_to_pids.get(ticker, []) if pairs else []:
                            if (mid, pid) in excluded_set:
                                excluded = True
                                break
                    meta["is_committee_active"] = is_active
                    meta["excluded_from_committee"] = excluded
                    r["metadata"] = meta
            finally:
                db.close()
        except Exception as e:
            print(f"[VECTOR_STORE][COMMITTEE_FLAGS] Falha ao anotar flags: {e}")
    
    def _deduplicate_results(self, documents: List[dict], similarity_threshold: float = 0.85) -> List[dict]:
        """
        Remove chunks semanticamente duplicados.
        Mantém apenas o chunk com maior score quando dois são muito similares.
        
        Critérios de duplicata:
        - Conteúdo quase idêntico (overlap > 90%) independente do produto
        - Mesmo produto E conteúdo similar (overlap > 85%)
        
        Lista já vem ordenada por score, então o primeiro sempre tem maior score.
        """
        if not documents:
            return documents
        
        deduplicated = []
        
        for doc in documents:
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            current_distance = doc.get("distance", 1.0)
            
            if "---" in content:
                content = content.split("---", 1)[1]
            short_content = content[:500].lower().strip()
            current_words = set(short_content.split())
            current_block_id = metadata.get("block_id") or doc.get("metadata", {}).get("block_id")
            
            is_duplicate = False
            duplicate_idx = -1
            
            for idx, seen_doc in enumerate(deduplicated):
                seen_block_id = seen_doc.get("metadata", {}).get("block_id")
                if current_block_id and seen_block_id and current_block_id == seen_block_id:
                    is_duplicate = True
                    duplicate_idx = idx
                    break
                
                seen_content = seen_doc.get("content", "")
                if "---" in seen_content:
                    seen_content = seen_content.split("---", 1)[1]
                seen_short = seen_content[:500].lower().strip()
                
                if short_content == seen_short:
                    is_duplicate = True
                    duplicate_idx = idx
                    break
                
                if len(current_words) > 15:
                    seen_words = set(seen_short.split())
                    intersection = len(current_words & seen_words)
                    union = len(current_words | seen_words)
                    
                    if union > 0:
                        overlap = intersection / union
                        
                        if overlap > 0.95:
                            is_duplicate = True
                            duplicate_idx = idx
                            break
            
            if is_duplicate:
                if duplicate_idx >= 0 and current_distance < deduplicated[duplicate_idx].get("distance", 1.0):
                    deduplicated[duplicate_idx] = doc
            else:
                deduplicated.append(doc)
        
        return deduplicated
    
    def _log_retrieval(
        self,
        query: str,
        query_type: str,
        results: List[dict],
        total_candidates: int,
        threshold: float,
        conversation_id: str = None,
        user_id: int = None,
        intent_detected: str = None,
        entities_detected: list = None,
        composite_score_max: float = None,
        web_search_used: bool = False,
        blocks_with_scores: list = None,
        is_comparative: bool = False,
        tools_used: Optional[list] = None,
        reranker_kept_ids: Optional[list] = None
    ) -> None:
        """
        Loga a busca para observabilidade.
        Registra query, resultados, scores e metadados.
        Persiste no RetrievalLog para auditoria.
        """
        import json
        
        chunk_ids = [str(r.get("metadata", {}).get("block_id", "?")) for r in results]
        distances = [f"{r.get('distance', 1.0):.3f}" for r in results]
        products = list(set(r.get("metadata", {}).get("product_name", "?") for r in results))
        
        min_dist = min([r.get("distance", 1.0) for r in results]) if results else None
        max_dist = max([r.get("distance", 1.0) for r in results]) if results else None
        
        print(f"[RETRIEVAL] Query: '{query[:50]}' | Type: {query_type} | Intent: {intent_detected} | Entities: {entities_detected} | Results: {len(results)}/{total_candidates} | Products: {products[:3]} | MaxScore: {composite_score_max}")
        
        try:
            from database.database import SessionLocal
            from database.models import RetrievalLog
            
            db = SessionLocal()
            try:
                log_entry = RetrievalLog(
                    query=query[:1000],
                    query_type=query_type,
                    chunks_retrieved=json.dumps(chunk_ids[:20]),
                    result_count=len(results),
                    min_distance=f"{min_dist:.4f}" if min_dist else None,
                    max_distance=f"{max_dist:.4f}" if max_dist else None,
                    threshold_applied=f"{threshold:.2f}",
                    conversation_id=conversation_id,
                    user_id=user_id,
                    intent_detected=intent_detected,
                    entities_detected=json.dumps(entities_detected or []),
                    composite_score_max=composite_score_max,
                    web_search_used=web_search_used,
                    blocks_with_scores=json.dumps(blocks_with_scores or []),
                    is_comparative=is_comparative,
                    tools_used=json.dumps(tools_used or []),
                    reranker_kept_ids=json.dumps(reranker_kept_ids or [])
                )
                db.add(log_entry)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[RETRIEVAL] Warning: Failed to persist log: {e}")
    
    def update_tools_used_for_conversation(
        self,
        conversation_id: Optional[str],
        tools_used: List[str],
        within_seconds: int = 120,
    ) -> int:
        """Wrapper retrocompatível — vide `update_retrieval_telemetry_for_conversation`."""
        return self.update_retrieval_telemetry_for_conversation(
            conversation_id=conversation_id,
            tools_used=tools_used,
            within_seconds=within_seconds,
        )

    def update_retrieval_telemetry_for_conversation(
        self,
        conversation_id: Optional[str],
        tools_used: Optional[List[str]] = None,
        reranker_kept_ids: Optional[List[str]] = None,
        composite_score_max: Optional[float] = None,
        within_seconds: int = 120,
    ) -> int:
        """
        Atualiza retrieval_logs recentes desta conversa com:
        - tools_used   (lista de tools que o agente chamou no turno)
        - reranker_kept_ids (lista de block_ids mantidos pelo reranker LLM)
        Apenas campos vazios/nulos são preenchidos para preservar histórico.
        Retorna o número de linhas atualizadas.
        """
        if not conversation_id:
            return 0
        if not tools_used and not reranker_kept_ids and composite_score_max is None:
            return 0
        import json

        sets = []
        params = {"cid": conversation_id, "secs": str(within_seconds)}
        if tools_used:
            sets.append(
                "tools_used = CASE WHEN tools_used IS NULL OR tools_used = '' OR tools_used = '[]' "
                "THEN :tools ELSE tools_used END"
            )
            params["tools"] = json.dumps(list(dict.fromkeys(tools_used)))
        if reranker_kept_ids:
            sets.append(
                "reranker_kept_ids = CASE WHEN reranker_kept_ids IS NULL OR reranker_kept_ids = '' "
                "OR reranker_kept_ids = '[]' THEN :kept ELSE reranker_kept_ids END"
            )
            params["kept"] = json.dumps(list(dict.fromkeys(reranker_kept_ids)))
        if composite_score_max is not None:
            sets.append(
                "composite_score_max = COALESCE(composite_score_max, :csm)"
            )
            params["csm"] = float(composite_score_max)

        try:
            from database.database import SessionLocal
            db = SessionLocal()
            try:
                res = db.execute(
                    sql_text(
                        f"UPDATE retrieval_logs SET {', '.join(sets)} "
                        f"WHERE conversation_id = :cid "
                        f"AND created_at >= NOW() - (:secs || ' seconds')::interval"
                    ),
                    params,
                )
                db.commit()
                return res.rowcount or 0
            finally:
                db.close()
        except Exception as e:
            print(f"[RETRIEVAL] Warning: update_retrieval_telemetry falhou: {e}")
            return 0

    def _calculate_recency_score(self, created_at_str: str, now: 'datetime') -> float:
        """
        Calcula score de recência (0-1).
        Documentos mais recentes recebem score maior.
        
        Escala:
        - Últimos 7 dias: 1.0
        - Últimos 30 dias: 0.8
        - Últimos 90 dias: 0.6
        - Últimos 180 dias: 0.4
        - Mais antigo: 0.2
        """
        if not created_at_str:
            return 0.3
        
        try:
            from datetime import datetime
            if 'T' in created_at_str:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                if created_at.tzinfo:
                    created_at = created_at.replace(tzinfo=None)
            else:
                created_at = datetime.strptime(created_at_str[:10], "%Y-%m-%d")
            
            days_old = (now - created_at).days
            
            if days_old <= 7:
                return 1.0
            elif days_old <= 30:
                return 0.8
            elif days_old <= 90:
                return 0.6
            elif days_old <= 180:
                return 0.4
            else:
                return 0.2
        except Exception:
            return 0.3
    
    def _calculate_exact_match_score(
        self, 
        query_upper: str, 
        ticker: str, 
        product_name: str,
        gestora: str
    ) -> float:
        """
        Calcula score de match exato (0-1).
        Bonus para quando o ticker, produto ou gestora aparecem na query.
        """
        score = 0.0
        
        if ticker and ticker.upper() in query_upper:
            score += 0.6
        
        if product_name:
            product_words = product_name.upper().split()
            matches = sum(1 for w in product_words if len(w) >= 4 and w in query_upper)
            if matches >= 2:
                score += 0.3
            elif matches >= 1:
                score += 0.15
        
        if gestora and gestora.upper() in query_upper:
            score += 0.1
        
        return min(score, 1.0)
    
    def search_by_ticker(self, ticker: str, n_results: int = 10) -> List[dict]:
        """
        Busca chunks pelo ticker do produto usando metadados.
        Usa filtro exato no campo product_ticker.
        
        Args:
            ticker: Ticker do produto (ex: MANA11)
            n_results: Número máximo de resultados
            
        Returns:
            Lista de documentos do produto
        """
        try:
            ticker_upper = ticker.upper().strip()
            
            db = SessionLocal()
            try:
                rows = db.execute(sql_text(
                    "SELECT * FROM document_embeddings WHERE product_ticker = :ticker "
                    f"{PUBLISH_STATUS_FILTER} LIMIT :limit"
                ), {'ticker': ticker_upper, 'limit': n_results}).fetchall()
            finally:
                db.close()
            
            documents = []
            if rows:
                from datetime import datetime
                now = datetime.now()
                
                for i, row in enumerate(rows):
                    metadata = {}
                    for field in KNOWN_METADATA_FIELDS:
                        val = row._mapping.get(field)
                        if val is not None:
                            metadata[field] = val
                    
                    created_at_source = row._mapping.get('created_at_source')
                    if created_at_source:
                        metadata['created_at'] = created_at_source
                    block_id_val = row._mapping.get('block_id')
                    if block_id_val:
                        metadata['block_id'] = block_id_val
                    material_id_val = row._mapping.get('material_id')
                    if material_id_val:
                        metadata['material_id'] = material_id_val
                    doc_type_val = row._mapping.get('doc_type')
                    if doc_type_val:
                        metadata['type'] = doc_type_val
                    extra_meta_val = row._mapping.get('extra_metadata')
                    if extra_meta_val:
                        try:
                            extra = json.loads(extra_meta_val)
                            for k, v in extra.items():
                                if k not in metadata:
                                    metadata[k] = v
                        except Exception:
                            pass
                    
                    doc_id = row._mapping.get('doc_id', f"ticker_doc_{i}")
                    doc_content = row._mapping.get('content', '')
                    
                    valid_until_str = metadata.get("valid_until", "")
                    if valid_until_str:
                        try:
                            if 'T' in valid_until_str:
                                valid_until = datetime.fromisoformat(valid_until_str.replace('Z', '+00:00'))
                                if valid_until.tzinfo:
                                    valid_until = valid_until.replace(tzinfo=None)
                            else:
                                valid_until = datetime.strptime(valid_until_str[:10], "%Y-%m-%d")
                            if valid_until < now:
                                continue
                        except Exception:
                            pass
                    
                    publish_status = metadata.get("publish_status", "publicado")
                    if publish_status in ["rascunho", "arquivado"]:
                        continue
                    
                    priority = 0.1
                    material_type = metadata.get("material_type", "")
                    live_types = ["one_page", "atualizacao_taxas", "argumentos_comerciais"]
                    if material_type in live_types:
                        priority = 0.05
                    
                    documents.append({
                        "content": doc_content,
                        "metadata": metadata,
                        "distance": priority,
                        "source": "ticker_metadata",
                        "doc_id": doc_id
                    })
            
            documents.sort(key=lambda x: x.get("distance", 0))
            if not documents:
                _log_zero_results("search_by_ticker()", ticker)
            return documents
            
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao buscar por ticker: {e}")
            return []
    
    def search_by_product(self, product_name: str, n_results: int = 10) -> List[dict]:
        """
        Busca TODOS os chunks que mencionam um produto específico.
        Primeiro tenta busca por ticker, depois fallback para busca textual.
        
        Args:
            product_name: Nome do produto para buscar
            n_results: Número máximo de resultados
            
        Returns:
            Lista de documentos que mencionam o produto
        """
        tickers = extract_tickers_from_query(product_name)
        if tickers:
            results = self.search_by_ticker(tickers[0], n_results)
            if results:
                return results
        
        try:
            product_upper = product_name.upper().strip()
            
            db = SessionLocal()
            try:
                rows = db.execute(sql_text(
                    "SELECT * FROM document_embeddings WHERE product_ticker = :ticker "
                    f"{PUBLISH_STATUS_FILTER} LIMIT :limit"
                ), {'ticker': product_upper, 'limit': n_results}).fetchall()
            finally:
                db.close()
            
            documents = []
            if rows:
                from datetime import datetime
                now = datetime.now()
                
                for i, row in enumerate(rows):
                    metadata = {}
                    for field in KNOWN_METADATA_FIELDS:
                        val = row._mapping.get(field)
                        if val is not None:
                            metadata[field] = val
                    
                    created_at_source = row._mapping.get('created_at_source')
                    if created_at_source:
                        metadata['created_at'] = created_at_source
                    block_id_val = row._mapping.get('block_id')
                    if block_id_val:
                        metadata['block_id'] = block_id_val
                    material_id_val = row._mapping.get('material_id')
                    if material_id_val:
                        metadata['material_id'] = material_id_val
                    doc_type_val = row._mapping.get('doc_type')
                    if doc_type_val:
                        metadata['type'] = doc_type_val
                    extra_meta_val = row._mapping.get('extra_metadata')
                    if extra_meta_val:
                        try:
                            extra = json.loads(extra_meta_val)
                            for k, v in extra.items():
                                if k not in metadata:
                                    metadata[k] = v
                        except Exception:
                            pass
                    
                    doc_content = row._mapping.get('content', '')
                    
                    valid_until_str = metadata.get("valid_until", "")
                    if valid_until_str:
                        try:
                            if 'T' in valid_until_str:
                                valid_until = datetime.fromisoformat(valid_until_str.replace('Z', '+00:00'))
                                if valid_until.tzinfo:
                                    valid_until = valid_until.replace(tzinfo=None)
                            else:
                                valid_until = datetime.strptime(valid_until_str[:10], "%Y-%m-%d")
                            if valid_until < now:
                                continue
                        except Exception:
                            pass
                    
                    publish_status = metadata.get("publish_status", "publicado")
                    if publish_status in ["rascunho", "arquivado"]:
                        continue
                    
                    priority = 0
                    material_type = metadata.get("material_type", "")
                    live_types = ["one_page", "atualizacao_taxas", "argumentos_comerciais"]
                    if material_type in live_types:
                        priority = -1
                    
                    documents.append({
                        "content": doc_content,
                        "metadata": metadata,
                        "distance": priority
                    })
            
            documents.sort(key=lambda x: x.get("distance", 0))
            
            if not documents:
                _log_zero_results("search_by_product()", product_name)
            return documents
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao buscar por produto: {e}")
            return []
    
    def search_by_portfolio(
        self,
        query: str,
        n_results: int = 30,
        db: Optional["object"] = None,
    ) -> List[dict]:
        """Task #204 — Lookup relacional de blocos de carteira/portfólio.

        Quando a intenção da query é "portfólio" (`detect_portfolio_intent`),
        a busca semântica padrão pode falhar por dois motivos:
          1. Cada `portfolio_row` fala apenas de UM ticker (ex.: "BTLG11:
             Peso=6%; DY=0,78%..."), então o embedding de "liste FIIs da
             carteira Seven" fica semanticamente distante de cada linha
             individual — top-K convencional pega 4 linhas das 12 e
             responde "documento incompleto".
          2. O `composite_score` cai abaixo do `LOW_CONFIDENCE_THRESHOLD`
             (0.30) e o guard anti-alucinação retorna `no_results`.

        Solução: identificar o(s) material(is)-carteira por nome relacional
        (não por embedding) e devolver TODOS os blocos `portfolio_row` +
        `financial_table` desse material. O `composite_score` injetado é
        alto (0.05 de distância = ~0.95 de score) para passar o guard.

        Estratégia:
          1. Tokeniza a query removendo stopwords e keywords genéricas de
             portfólio (carteira/composição/lista/...) — sobram tokens
             distintivos (ex.: "seven", "abril").
          2. Encontra materiais cujo `product.product_type='carteira'`
             (taxonomia oficial) OU cujo `material.name` casa o regex
             de carteira em `product_ingestor`.
          3. Filtra: se há tokens distintivos, prioriza materiais cujo
             `name` ou `product.name` casa pelo menos 1 token.
          4. Devolve TODOS os blocos prioritários (`portfolio_row`,
             `financial_table`, `tabela`) desses materiais, mais blocos
             de texto da MESMA(s) carteira(s) como contexto.

        Sem isso, queries como "fundos da carteira Seven", "composição da
        carteira recomendada", "alocação dos FIIs" caem no fluxo semântico
        puro e retornam resultados incompletos ou no_results.
        """
        from database.models import Product as _Prod, Material as _Mat, ContentBlock as _CB
        try:
            from services.product_ingestor import _PORTFOLIO_REGEX
        except Exception:
            _PORTFOLIO_REGEX = None

        owns_db = False
        if db is None:
            db = SessionLocal()
            owns_db = True

        try:
            # 1) Tokeniza a query removendo termos genéricos para extrair
            #    tokens distintivos (nome da carteira: "seven", "arrojada"...).
            _GENERIC_TOKENS = {
                "carteira", "carteiras", "portfolio", "portfólio", "portfolios",
                "composicao", "composição", "alocacao", "alocação",
                "lista", "listar", "liste", "todos", "todas", "todo", "toda",
                "fundos", "ativos", "papeis", "papéis", "fiis", "fii",
                "peso", "pesos", "participacao", "participação",
                "qual", "quais", "quanto", "quantos", "quantas",
                "da", "do", "de", "dos", "das", "para", "com", "em",
                "a", "o", "os", "as", "um", "uma", "e", "ou",
                "me", "mostre", "mostra", "diga", "fale", "explique",
                "recomendada", "recomendado", "sugerida", "sugerido",
                "atual", "atualizada", "agora", "hoje",
            }
            import unicodedata
            def _norm(s: str) -> str:
                if not s:
                    return ""
                nfkd = unicodedata.normalize("NFKD", str(s))
                return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
            q_norm = _norm(query)
            raw_tokens = re.findall(r"[a-zA-Z0-9]+", q_norm)
            distinctive = [
                t for t in raw_tokens
                if len(t) >= 4 and t not in _GENERIC_TOKENS and not t.isdigit()
            ]

            # 2) Candidatos: materiais cujo produto associado é do tipo
            #    'carteira' OU cujo nome casa o regex de carteira.
            candidate_mats = (
                db.query(_Mat, _Prod)
                .outerjoin(_Prod, _Mat.product_id == _Prod.id)
                .filter(_Mat.source_file_path.isnot(None))
                .filter(_Mat.publish_status.notin_(["rascunho", "arquivado"]))
                .all()
            )
            target_materials: List[_Mat] = []
            for mat, prod in candidate_mats:
                prod_type = (prod.product_type or "").lower() if prod else ""
                is_carteira = prod_type == "carteira"
                if not is_carteira and _PORTFOLIO_REGEX is not None:
                    name_check = " ".join(
                        s for s in [mat.name, prod.name if prod else None] if s
                    )
                    is_carteira = bool(_PORTFOLIO_REGEX.search(name_check))
                if is_carteira:
                    target_materials.append(mat)

            if not target_materials:
                _log_zero_results("search_by_portfolio()", query)
                return []

            # 3) Filtra por tokens distintivos quando disponíveis. Se nenhum
            #    material casar com nenhum token, mantém TODOS (a query é
            #    genérica do tipo "liste as carteiras"; agente verá tudo).
            #    Code review (Task #204): rastreamos `_match_strength` para
            #    diferenciar match RELACIONAL FORTE (distintivo casou um
            #    nome de carteira específico) de FALLBACK (query genérica
            #    sem nome — devolve todas como contexto exploratório). O
            #    bypass do guard de baixa confiança em agent_tools só
            #    deve disparar no modo FORTE — caso contrário mistura
            #    carteiras não relacionadas e mascara false-positives.
            match_strength = "weak"  # default: sem distintivo OU sem match
            if distinctive:
                ranked: List[Tuple[int, _Mat]] = []
                for mat in target_materials:
                    haystack = _norm(
                        " ".join(s for s in [mat.name, getattr(mat.product, "name", None)] if s)
                    )
                    score = sum(1 for t in distinctive if t in haystack)
                    if score > 0:
                        ranked.append((score, mat))
                if ranked:
                    ranked.sort(key=lambda kv: -kv[0])
                    target_materials = [m for _s, m in ranked]
                    match_strength = "strong"  # casou nome específico
                # caso contrário (nenhum token bateu), mantém a lista cheia
                # — talvez seja query genérica "liste as carteiras".

            # Limite defensivo para não devolver dezenas de blocos por
            # múltiplas carteiras concorrentes.
            target_materials = target_materials[:3]
            mat_ids = [m.id for m in target_materials]

            # 4) Busca blocos prioritários + texto desses materiais.
            #    Ordem: portfolio_row > financial_table/tabela > texto.
            from database.models import ContentBlockStatus as _CBS
            blocks = (
                db.query(_CB, _Mat)
                .join(_Mat, _CB.material_id == _Mat.id)
                .filter(_CB.material_id.in_(mat_ids))
                .filter(_CB.status.in_([
                    _CBS.APPROVED.value, _CBS.AUTO_APPROVED.value,
                ]))
                .order_by(_CB.material_id, _CB.source_page, _CB.id)
                .all()
            )

            # Mapas de produto/material para hidratar metadata.
            # Code review (Task #204): substitui o N+1 (1 query por material)
            # por uma única query `IN (...)` cobrindo todos os produtos das
            # carteiras-alvo de uma vez. Para até 3 carteiras o ganho é
            # marginal, mas o padrão evita regressão se o limite subir.
            _pids_needed = [
                m.product_id for m in target_materials if m.product_id is not None
            ]
            _prod_rows = (
                db.query(_Prod).filter(_Prod.id.in_(_pids_needed)).all()
                if _pids_needed else []
            )
            _prod_by_id = {p.id: p for p in _prod_rows}
            prod_by_mat = {
                m.id: _prod_by_id.get(m.product_id) for m in target_materials
            }

            # Prioridade explícita: portfolio_row primeiro, tabelas depois,
            # texto por último — o caller do agent_tools mantém essa ordem.
            _PRIORITY_ORDER = {
                "portfolio_row": 0,
                "financial_table": 1,
                "tabela": 1,
                "table": 1,
                "texto": 2,
                "text": 2,
            }
            def _prio(bt: str) -> int:
                return _PRIORITY_ORDER.get((bt or "").lower(), 9)

            # Limita texto a no máximo 4 por material (contexto narrativo,
            # mas sem inundar). Tabelas e portfolio_rows passam todas.
            text_count_per_mat: Dict[int, int] = {}
            documents: List[dict] = []
            for blk, mat in blocks:
                bt = (blk.block_type or "").lower()
                if bt in ("texto", "text"):
                    text_count_per_mat.setdefault(mat.id, 0)
                    if text_count_per_mat[mat.id] >= 4:
                        continue
                    text_count_per_mat[mat.id] += 1
                if _prio(bt) >= 9:
                    continue  # tipos desconhecidos (chart/imagem) — não úteis para listagem

                prod = prod_by_mat.get(mat.id)
                metadata = {
                    "block_id": str(blk.id),
                    "material_id": str(mat.id),
                    "material_name": mat.name or "",
                    "material_type": mat.material_type or "",
                    "block_type": bt,
                    "page": str(blk.source_page or 0),
                    "source_page": blk.source_page,
                    "title": blk.title or "",
                    "product_name": prod.name if prod else "",
                    "product_ticker": (prod.ticker or "") if prod else "",
                    "product_type": (prod.product_type or "carteira") if prod else "carteira",
                    "product_id": str(prod.id) if prod else None,
                    "publish_status": mat.publish_status or "publicado",
                    "products": (prod.name.upper() if prod and prod.name else ""),
                    # Tag de força do match relacional. Vai dentro de
                    # `metadata` (não no top-level do dict) porque o
                    # `CompositeScorer.score_results` converte os dicts em
                    # `SearchResult` e só os campos do dataclass + metadata
                    # sobrevivem. agent_tools lê `r.metadata["portfolio_match_strength"]`
                    # para decidir se pode bypassar o guard de baixa confiança.
                    "portfolio_match_strength": match_strength,
                    "portfolio_lookup_source": True,
                }
                # distância sintética baixa (= score alto) para entrar com
                # prioridade no merge da EnhancedSearch.
                documents.append({
                    "content": blk.content or "",
                    "metadata": metadata,
                    "distance": 0.05 + 0.05 * _prio(bt),
                    "source": "portfolio_lookup",
                })

            documents.sort(key=lambda d: (
                _prio(d["metadata"]["block_type"]),
                int(d["metadata"].get("material_id") or "0"),
                int(d["metadata"].get("source_page") or 0),
                int(d["metadata"].get("block_id") or "0"),
            ))

            # Task #204 — EXAUSTIVIDADE para portfolio_row: o cap n_results
            # NÃO se aplica a linhas de carteira. Se a carteira tem 30 FIIs,
            # o agente recebe os 30 mesmo que `n_results=20`. O cap é
            # respeitado apenas para os blocos de CONTEXTO (texto, tabela
            # auxiliar). Sem isso, perguntas como "todos os ativos da
            # carteira" devolveriam parcialmente quando `n_results < N`.
            portfolio_rows = [
                d for d in documents
                if (d["metadata"].get("block_type") or "").lower() == "portfolio_row"
            ]
            other_blocks = [
                d for d in documents
                if (d["metadata"].get("block_type") or "").lower() != "portfolio_row"
            ]
            # cap dos auxiliares: pelo menos n_results - len(portfolio_rows),
            # nunca menos que 5 (para preservar contexto narrativo mínimo).
            aux_cap = max(5, n_results - len(portfolio_rows))
            final_documents = portfolio_rows + other_blocks[:aux_cap]

            print(
                f"[VECTOR_STORE] search_by_portfolio: query={query!r} "
                f"distinctive={distinctive} materiais={mat_ids} "
                f"portfolio_rows={len(portfolio_rows)} "
                f"aux_blocos={min(len(other_blocks), aux_cap)} "
                f"total={len(final_documents)}"
            )
            return final_documents
        except Exception as e:
            print(f"[VECTOR_STORE] Erro em search_by_portfolio: {e}")
            return []
        finally:
            if owns_db:
                db.close()

    def search_by_product_ids(self, product_ids: List[int], max_per_product: int = 5) -> List[dict]:
        """
        Busca blocos de conteúdo via ORM relacional (Product→Material→ContentBlock).
        Não depende de product_ticker nos embeddings.
        Filtra por ContentBlock.status aprovado e Material publicado (mesma política do PUBLISH_STATUS_FILTER).
        """
        from database.models import Product, Material, ContentBlock
        from datetime import datetime

        if not product_ids:
            return []

        db = SessionLocal()
        try:
            documents = []
            now = datetime.now()

            for pid in product_ids[:5]:
                product = db.query(Product).filter(Product.id == pid).first()
                if not product:
                    continue

                gestora_inferred = self._infer_gestora_from_name(product.name) if hasattr(self, '_infer_gestora_from_name') else ''

                from database.models import MaterialProductLink
                from sqlalchemy import or_

                linked_material_ids = [
                    row.material_id for row in
                    db.query(MaterialProductLink.material_id).filter(
                        MaterialProductLink.product_id == pid
                    ).all()
                ]

                blocks = db.query(ContentBlock).join(Material).filter(
                    or_(
                        Material.product_id == pid,
                        Material.id.in_(linked_material_ids)
                    ),
                    Material.publish_status.notin_(['rascunho', 'arquivado']),
                    ContentBlock.status.in_(['approved', 'auto_approved'])
                ).order_by(ContentBlock.id).limit(max_per_product).all()

                if not blocks:
                    blocks = db.query(ContentBlock).join(Material).filter(
                        or_(
                            Material.product_id == pid,
                            Material.id.in_(linked_material_ids)
                        ),
                        Material.publish_status != 'arquivado',
                        ContentBlock.status.in_(['approved', 'auto_approved'])
                    ).order_by(ContentBlock.id).limit(max_per_product).all()

                for block in blocks:
                    material = block.material

                    valid_until = material.valid_until if material else None
                    if valid_until:
                        try:
                            if hasattr(valid_until, 'replace'):
                                vu = valid_until.replace(tzinfo=None) if valid_until.tzinfo else valid_until
                            else:
                                vu = datetime.fromisoformat(str(valid_until).replace('Z', '+00:00')).replace(tzinfo=None)
                            if vu < now:
                                continue
                        except Exception:
                            pass

                    metadata = {
                        'product_name': product.name,
                        'product_ticker': product.ticker or '',
                        'products': product.name,
                        'gestora': gestora_inferred,
                        'category': product.category or '',
                        'material_id': material.id if material else None,
                        'material_type': material.material_type if material else '',
                        'block_id': block.id,
                        'block_type': block.block_type or 'text',
                        'source': 'entity_resolver',
                        'publish_status': material.publish_status if material else 'publicado',
                    }

                    documents.append({
                        'content': block.content or '',
                        'metadata': metadata,
                        'distance': 0.15,
                    })

            return documents
        except Exception as e:
            print(f"[VECTOR_STORE] Erro em search_by_product_ids: {e}")
            return []
        finally:
            db.close()

    def get_all_tickers(self) -> Set[str]:
        """
        Extrai todos os tickers únicos da base de conhecimento.
        Padrão: 4-5 letras + 11 (ex: TGRE11, XPLG11)
        
        Returns:
            Set de tickers encontrados
        """
        ticker_pattern = re.compile(r'\b([A-Z]{4,5}11)\b', re.IGNORECASE)
        tickers = set()
        
        try:
            db = SessionLocal()
            try:
                ticker_rows = db.execute(sql_text(
                    "SELECT DISTINCT product_ticker FROM document_embeddings "
                    f"WHERE product_ticker IS NOT NULL AND product_ticker != '' {PUBLISH_STATUS_FILTER}"
                )).fetchall()
                for row in ticker_rows:
                    t = row[0]
                    if t:
                        tickers.add(t.upper())
                
                content_rows = db.execute(sql_text(
                    f"SELECT content FROM document_embeddings WHERE 1=1 {PUBLISH_STATUS_FILTER}"
                )).fetchall()
                for row in content_rows:
                    doc = row[0] or ''
                    found = ticker_pattern.findall(doc.upper())
                    tickers.update(found)
            finally:
                db.close()
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao extrair tickers: {e}")
        
        return tickers
    
    def get_all_product_names(self) -> Set[str]:
        """
        Extrai todos os nomes/tickers de produtos únicos dos metadados.
        Versão legada - retorna apenas nomes como strings.
        
        Returns:
            Set de nomes de produtos encontrados
        """
        products = set()
        
        try:
            db = SessionLocal()
            try:
                rows = db.execute(sql_text(
                    "SELECT DISTINCT product_ticker FROM document_embeddings "
                    f"WHERE product_ticker IS NOT NULL AND product_ticker != '' {PUBLISH_STATUS_FILTER}"
                )).fetchall()
                for row in rows:
                    ticker = row[0]
                    if ticker:
                        cleaned = ticker.strip().upper()
                        if cleaned and len(cleaned) >= 3:
                            products.add(cleaned)
                
                name_rows = db.execute(sql_text(
                    "SELECT DISTINCT product_name FROM document_embeddings "
                    f"WHERE product_name IS NOT NULL AND product_name != '' {PUBLISH_STATUS_FILTER}"
                )).fetchall()
                for row in name_rows:
                    name = row[0]
                    if name:
                        cleaned = name.strip().upper()
                        if cleaned and len(cleaned) >= 3:
                            products.add(cleaned)
            finally:
                db.close()
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao extrair produtos: {e}")
        
        return products
    
    def find_exact_ticker(self, ticker: str) -> bool:
        """
        Verifica se um ticker EXATO existe na base de conhecimento.
        
        Args:
            ticker: Ticker a ser buscado (ex: TGRE11)
            
        Returns:
            True se encontrado exatamente, False caso contrário
        """
        ticker_upper = ticker.upper().strip()
        all_tickers = self.get_all_tickers()
        return ticker_upper in all_tickers
    
    def find_similar_tickers(self, ticker: str, max_distance: int = 3, limit: int = 3, debug: bool = False) -> List[str]:
        """
        Encontra tickers/produtos similares ao fornecido usando distância de Levenshtein.
        Busca tanto em tickers (padrão XX11) quanto em produtos gerais.
        
        Args:
            ticker: Ticker a ser buscado (ex: TGRE11)
            max_distance: Distância máxima de Levenshtein para considerar similar
            limit: Número máximo de sugestões
            debug: Se True, imprime logs de debug
            
        Returns:
            Lista de tickers/produtos similares ordenados por similaridade
        """
        ticker_upper = ticker.upper().strip()
        ticker_base = ticker_upper.replace('11', '')
        is_ticker_format = bool(re.match(r'^[A-Z]{4,5}11$', ticker_upper))
        
        all_tickers = self.get_all_tickers()
        all_products = self.get_all_products()
        all_items = all_tickers.union(all_products)
        
        if debug:
            print(f"[VECTOR_STORE] find_similar_tickers: buscando similares para '{ticker_upper}'")
            print(f"[VECTOR_STORE] Total de tickers na base: {len(all_tickers)}")
            print(f"[VECTOR_STORE] Total de produtos na base: {len(all_products)}")
        
        similar = []
        for existing_item in all_items:
            if existing_item == ticker_upper:
                continue
            
            item_len = len(existing_item)
            if item_len > 15:
                continue
            
            existing_base = existing_item.replace('11', '').replace(' ', '')
            
            distance = levenshtein_distance(ticker_upper, existing_item)
            base_distance = levenshtein_distance(ticker_base, existing_base)
            
            if distance <= max_distance:
                similar.append((existing_item, distance))
            elif base_distance <= 2 and item_len <= 10:
                similar.append((existing_item, base_distance + 1))
            elif ticker_upper[:3] == existing_item[:3] and item_len <= 10 and distance <= 5:
                similar.append((existing_item, distance))
        
        similar.sort(key=lambda x: x[1])
        
        if debug:
            print(f"[VECTOR_STORE] Similares encontrados: {similar[:10]}")
        
        seen = set()
        unique_similar = []
        for item, dist in similar:
            normalized = item.replace(' ', '')
            if normalized not in seen:
                seen.add(normalized)
                unique_similar.append(normalized)
                if len(unique_similar) >= limit:
                    break
        
        if debug:
            print(f"[VECTOR_STORE] Retornando: {unique_similar}")
        return unique_similar
    
    def search_product_in_database(self, query: str) -> Optional[dict]:
        """
        Fallback: busca produtos diretamente no banco de dados PostgreSQL.
        Útil quando o produto existe mas não tem blocos indexados no ChromaDB.
        
        Args:
            query: Nome do produto ou ticker a buscar
            
        Returns:
            Dict com informações do produto ou None se não encontrado
        """
        from database.database import SessionLocal
        from database.models import Product, Material, ContentBlock
        import unicodedata
        
        def normalize_text(text: str) -> str:
            if not text:
                return ""
            text = unicodedata.normalize('NFD', text)
            text = ''.join(c for c in text if not unicodedata.combining(c))
            return text.upper().strip()
        
        query_normalized = normalize_text(query)
        query_words = query_normalized.split()
        
        db = SessionLocal()
        try:
            product = db.query(Product).filter(
                Product.ticker.ilike(f"%{query}%")
            ).first()
            
            if not product:
                product = db.query(Product).filter(
                    Product.name.ilike(f"%{query}%")
                ).first()
            
            if not product:
                all_products = db.query(Product).filter(
                    Product.status == 'ativo'
                ).all()
                
                for p in all_products:
                    ticker_norm = normalize_text(p.ticker) if p.ticker else ""
                    name_norm = normalize_text(p.name) if p.name else ""
                    
                    if query_normalized in ticker_norm or query_normalized in name_norm:
                        product = p
                        break
                    if ticker_norm and ticker_norm in query_normalized:
                        product = p
                        break
                    for word in query_words:
                        if len(word) >= 4 and (word in ticker_norm or word in name_norm):
                            product = p
                            break
                    if product:
                        break
            
            if product:
                materials_count = db.query(Material).filter(
                    Material.product_id == product.id
                ).count()
                
                blocks_count = db.query(ContentBlock).join(Material).filter(
                    Material.product_id == product.id
                ).count()
                
                return {
                    'id': product.id,
                    'name': product.name,
                    'ticker': product.ticker,
                    'manager': product.manager,
                    'category': product.category,
                    'description': product.description,
                    'status': product.status,
                    'materials_count': materials_count,
                    'blocks_count': blocks_count,
                    'source': 'database_fallback'
                }
            
            return None
            
        except Exception as e:
            print(f"[VECTOR_STORE] Erro na busca de fallback: {e}")
            return None
        finally:
            db.close()
    
    def get_active_committee_product_ids(self) -> List[int]:
        """
        Retorna product_ids de produtos marcados como Comitê SVN.

        Fonte de verdade única: flag `Product.is_committee` (botão estrela no card).
        Legados (RecommendationEntry e categoria "Comitê") foram removidos —
        a estrela é a única forma de adicionar um produto ao comitê.
        """
        from database.database import SessionLocal
        db = SessionLocal()
        try:
            from database.models import Product
            rows = db.query(Product.id).filter(Product.is_committee == True).all()
            return [row[0] for row in rows]
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao buscar product_ids do Comitê: {e}")
            return []
        finally:
            db.close()

    def get_committee_summary(self) -> List[dict]:
        """
        Retorna resumo estruturado do comitê ativo para injeção no system prompt.

        Fonte de verdade: Product.is_committee == True (botão estrela no card).
        Enriquecimento (opcional, não obrigatório):
          - RecommendationEntry ativa: rating, preço-alvo, tese, validade
          - Material com is_committee_active: nome do material fonte
        Legados removidos: categorias "Comitê", fallback por entries sem estrela.
        """
        from database.database import SessionLocal
        from datetime import datetime
        from sqlalchemy import or_
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            result = []

            # ── Fonte de verdade: Product.is_committee == True ─────────────────
            from database.models import Product as ProductModel
            committee_products = db.query(ProductModel).filter(
                ProductModel.is_committee == True
            ).all()

            if not committee_products:
                print("[VECTOR_STORE] committee_summary: nenhum produto com estrela ativa")
                return []

            # ── Enriquecimento 1: RecommendationEntry ativas ───────────────────
            rec_map: dict = {}
            try:
                from database.models import RecommendationEntry
                entries = db.query(RecommendationEntry).filter(
                    RecommendationEntry.is_active == True,
                ).filter(
                    or_(
                        RecommendationEntry.valid_until == None,
                        RecommendationEntry.valid_until >= now,
                    )
                ).order_by(RecommendationEntry.added_at.desc()).all()
                for e in entries:
                    if e.product_id not in rec_map:
                        rec_map[e.product_id] = e
            except Exception as rec_err:
                print(f"[VECTOR_STORE] Aviso: erro ao carregar recommendation_entries: {rec_err}")

            # ── Enriquecimento 2: materiais com is_committee_active=True ────────
            mat_product_map: dict = {}  # product_id -> material_name
            try:
                from database.models import Material, MaterialProductLink
                active_mats = db.query(Material).filter(
                    Material.is_committee_active == True,
                    Material.publish_status == 'publicado',
                    or_(
                        Material.valid_until.is_(None),
                        Material.valid_until >= now,
                    ),
                ).all()
                for mat in active_mats:
                    pids_for_mat = []
                    if mat.product_id:
                        pids_for_mat.append(mat.product_id)
                    links = db.query(MaterialProductLink).filter(
                        MaterialProductLink.material_id == mat.id,
                        MaterialProductLink.excluded_from_committee != True,
                    ).all()
                    for lnk in links:
                        if lnk.product_id not in pids_for_mat:
                            pids_for_mat.append(lnk.product_id)
                    for pid in pids_for_mat:
                        if pid not in mat_product_map:
                            mat_product_map[pid] = mat.name or ""
            except Exception as mat_err:
                print(f"[VECTOR_STORE] Aviso: erro ao carregar materiais do comitê: {mat_err}")

            # ── Montar resultado por produto com estrela ───────────────────────
            for prod in committee_products:
                rec = rec_map.get(prod.id)
                material_name = mat_product_map.get(prod.id, "")
                result.append({
                    "product_id": prod.id,
                    "product_name": prod.name,
                    "ticker": prod.ticker or "",
                    # Task #153 — tipo do produto exposto ao agente para
                    # diferenciar ação x estruturada sobre a mesma ação.
                    "product_type": (prod.product_type or "").lower() or "outro",
                    "manager": prod.manager or "",
                    "rating": rec.rating if rec else "",
                    "target_price": rec.target_price if rec else None,
                    "valid_until": rec.valid_until.strftime("%d/%m/%Y") if (rec and rec.valid_until) else "",
                    "rationale": rec.rationale if rec else "",
                    "key_info": _safe_load_key_info(prod.key_info),
                    "source": "is_committee_flag",
                    "material_name": material_name,
                })

            print(f"[VECTOR_STORE] committee_summary via Product.is_committee: {len(result)} produto(s)")
            return result

        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao buscar comitê summary: {e}")
            return []
        finally:
            db.close()

    def search_comite_vigent(self, query: str = "", n_results: int = 20) -> List[dict]:
        """
        Busca materiais vigentes de produtos que estão no Comitê SVN ativo.

        Camada 0 (primária): materiais com is_committee_active=True — conteúdo direto.
        Camada 1: recommendation_entries ativas (fonte formal de recomendação).
        Camada 2: Product.categories com 'Comitê' (marcação manual).
        """
        from database.database import SessionLocal
        from database.models import Product, Material, ContentBlock, MaterialStatus
        from datetime import datetime
        from sqlalchemy import or_

        db = SessionLocal()
        try:
            now = datetime.utcnow()

            # ── Camada 0: materiais com is_committee_active=True ──────────────
            from database.models import MaterialProductLink
            active_committee_mats = db.query(Material).filter(
                Material.is_committee_active == True,
                Material.publish_status == MaterialStatus.PUBLISHED.value,
                or_(
                    Material.valid_until.is_(None),
                    Material.valid_until >= now,
                )
            ).all()

            if active_committee_mats:
                print(f"[VECTOR_STORE] Comitê Layer 0: {len(active_committee_mats)} material(is) ativo(s)")

                # Enriquecimento opcional com recommendation_entries
                from database.models import RecommendationEntry
                rec_entries = db.query(RecommendationEntry).filter(
                    RecommendationEntry.is_active == True,
                ).filter(
                    or_(
                        RecommendationEntry.valid_until == None,
                        RecommendationEntry.valid_until >= now,
                    )
                ).all()
                rec_map = {e.product_id: e for e in rec_entries}

                mat_ids = [m.id for m in active_committee_mats]
                mat_map = {m.id: m for m in active_committee_mats}

                # Pré-computar produtos derivados por material (primário + junction links)
                mat_derived_products: dict = {}  # material_id → list of Product
                all_link_rows = db.query(MaterialProductLink).filter(
                    MaterialProductLink.material_id.in_(mat_ids)
                ).all()
                link_map: dict = {}       # material_id → [product_id (não excluídos)]
                excluded_map: dict = {}   # material_id → set de product_ids excluídos
                for lnk in all_link_rows:
                    if lnk.excluded_from_committee:
                        excluded_map.setdefault(lnk.material_id, set()).add(lnk.product_id)
                    else:
                        link_map.setdefault(lnk.material_id, []).append(lnk.product_id)

                for mat in active_committee_mats:
                    derived_pids = []
                    exc = excluded_map.get(mat.id, set())
                    if mat.product_id and mat.product_id not in exc:
                        derived_pids.append(mat.product_id)
                    for pid in link_map.get(mat.id, []):
                        if pid not in derived_pids:
                            derived_pids.append(pid)
                    derived_prods = []
                    for pid in derived_pids:
                        p = db.query(Product).filter(Product.id == pid).first()
                        if p:
                            derived_prods.append(p)
                    mat_derived_products[mat.id] = derived_prods

                blocks = db.query(ContentBlock).filter(
                    ContentBlock.material_id.in_(mat_ids),
                    ContentBlock.status.in_(['auto_approved', 'approved'])
                ).order_by(ContentBlock.material_id, ContentBlock.order).all()

                documents = []
                for block in blocks:
                    material = mat_map.get(block.material_id)
                    if not material:
                        continue

                    derived_prods = mat_derived_products.get(material.id, [])
                    # Produto primário para o enriquecimento principal (fallback ao primeiro derivado)
                    primary_prod = material.product or (derived_prods[0] if derived_prods else None)
                    primary_id = primary_prod.id if primary_prod else None
                    rec = rec_map.get(primary_id) if primary_id else None
                    # Tenta enriquecer com recommendation_entry de qualquer produto derivado
                    if not rec:
                        for dp in derived_prods:
                            rec = rec_map.get(dp.id)
                            if rec:
                                break

                    rating = rec.rating if rec else ""
                    target_price = rec.target_price if rec else None
                    valid_until_str = (
                        rec.valid_until.strftime("%d/%m/%Y") if (rec and rec.valid_until)
                        else (material.valid_until.strftime("%d/%m/%Y") if material.valid_until else "")
                    )
                    rationale = rec.rationale if rec else ""

                    # Construir string de produtos derivados para contexto do agente
                    derived_tickers = [p.ticker for p in derived_prods if p.ticker]
                    derived_names = [p.name for p in derived_prods if p.name]
                    derived_str = (
                        " | Produtos: " + ", ".join(derived_tickers or derived_names)
                        if (derived_tickers or derived_names) else ""
                    )

                    rating_str = f" | Rating: {rating}" if rating else ""
                    price_str = f" | Preço-alvo: R${target_price:.2f}" if target_price else ""
                    valid_str = f" | Válido até {valid_until_str}" if valid_until_str else " | Vigente sem prazo"
                    rationale_str = f" | Tese: {rationale}" if rationale else ""
                    enriched_content = (
                        f"[COMITÊ]{derived_str}{rating_str}{price_str}{valid_str}{rationale_str}\n{block.content or ''}"
                    )

                    documents.append({
                        "content": enriched_content,
                        "metadata": {
                            "product_name": primary_prod.name if primary_prod else "",
                            "product_ticker": primary_prod.ticker if primary_prod else "",
                            "product_id": primary_id,
                            "gestora": primary_prod.manager if primary_prod else "",
                            "derived_product_ids": [p.id for p in derived_prods],
                            "derived_tickers": derived_tickers,
                            "material_type": material.material_type,
                            "material_name": material.name or "",
                            "valid_until": valid_until_str,
                            "rating": rating,
                            "target_price": target_price,
                            "block_type": block.block_type,
                            "publish_status": material.publish_status,
                            "source_layer": "committee_material",
                        },
                        "distance": 0.03,
                        "source": "comite_vigent",
                    })

                print(f"[VECTOR_STORE] Comitê Layer 0: {len(documents)} bloco(s) de {len(active_committee_mats)} material(is) ativo(s)")
                # Materiais ativos são fonte exclusiva — não executa fallback legado
                return documents[:n_results]

            # ── Camadas 1–3: fallback SOMENTE se não há materiais ativos ──────
            # 1. Obter product_ids do comitê via recommendation_entries (fonte primária)
            committee_product_ids = []
            recommendation_map = {}  # product_id → entry metadata
            try:
                from database.models import RecommendationEntry
                entries = db.query(RecommendationEntry).filter(
                    RecommendationEntry.is_active == True,
                ).filter(
                    or_(
                        RecommendationEntry.valid_until == None,
                        RecommendationEntry.valid_until >= now
                    )
                ).all()
                for e in entries:
                    committee_product_ids.append(e.product_id)
                    recommendation_map[e.product_id] = {
                        "rating": e.rating or "",
                        "target_price": e.target_price,
                        "valid_until": e.valid_until.strftime("%d/%m/%Y") if e.valid_until else "",
                        "rationale": e.rationale or "",
                    }
            except Exception as inner_e:
                print(f"[VECTOR_STORE] recommendation_entries não disponível: {inner_e}")

            # 2. Fallback: Product.categories com "Comitê" (marcação manual)
            manual_products = db.query(Product).filter(
                or_(
                    Product.categories.like('%"Comitê"%'),
                    Product.categories.like('%"comite"%'),
                )
            ).all()
            for p in manual_products:
                if p.id not in committee_product_ids:
                    committee_product_ids.append(p.id)
                    if p.id not in recommendation_map:
                        recommendation_map[p.id] = {
                            "rating": "", "target_price": None, "valid_until": "", "rationale": ""
                        }

            committee_product_ids = list(set(committee_product_ids))

            if not committee_product_ids:
                print("[VECTOR_STORE] Nenhum produto no Comitê ativo encontrado")
                return []

            print(f"[VECTOR_STORE] Comitê: {len(committee_product_ids)} produtos ativos")

            # 3. Buscar materiais publicados desses produtos
            vigent_materials = db.query(Material).filter(
                Material.product_id.in_(committee_product_ids),
                Material.publish_status == MaterialStatus.PUBLISHED.value,
                or_(
                    Material.valid_until.is_(None),
                    Material.valid_until >= now
                )
            ).all()

            if not vigent_materials:
                print("[VECTOR_STORE] Produtos no Comitê encontrados, mas sem materiais publicados vigentes")
                return []

            material_ids = [m.id for m in vigent_materials]
            material_map = {m.id: m for m in vigent_materials}

            # 4. Buscar content_blocks aprovados
            blocks = db.query(ContentBlock).filter(
                ContentBlock.material_id.in_(material_ids),
                ContentBlock.status.in_(['auto_approved', 'approved'])
            ).order_by(ContentBlock.material_id, ContentBlock.order).all()

            if not blocks:
                print("[VECTOR_STORE] Materiais vigentes do Comitê sem blocos aprovados")
                return []

            # 5. Montar documentos enriquecidos
            documents = []
            for block in blocks:
                material = material_map.get(block.material_id)
                if not material:
                    continue

                product = material.product
                product_id = product.id if product else None
                rec_meta = recommendation_map.get(product_id, {})

                rating = rec_meta.get("rating", "")
                target_price = rec_meta.get("target_price")
                valid_until_str = rec_meta.get("valid_until") or (
                    material.valid_until.strftime("%d/%m/%Y") if material.valid_until else ""
                )
                rationale = rec_meta.get("rationale", "")

                rating_str = f" | Rating: {rating}" if rating else ""
                price_str = f" | Preço-alvo: R${target_price:.2f}" if target_price else ""
                valid_str = f" | Válido até {valid_until_str}" if valid_until_str else " | Vigente sem prazo"
                rationale_str = f" | Tese: {rationale}" if rationale else ""

                content = block.content or ""
                enriched_content = (
                    f"[COMITÊ]{rating_str}{price_str}{valid_str}{rationale_str}\n{content}"
                )

                metadata = {
                    "product_name": product.name if product else "",
                    "product_ticker": product.ticker if product else "",
                    "product_id": product_id,
                    "gestora": product.manager if product else "",
                    "material_type": material.material_type,
                    "material_name": material.name or "",
                    "valid_until": valid_until_str,
                    "rating": rating,
                    "target_price": target_price,
                    "block_type": block.block_type,
                    "publish_status": material.publish_status,
                }

                documents.append({
                    "content": enriched_content,
                    "metadata": metadata,
                    "distance": 0.05,
                    "source": "comite_vigent"
                })

            print(f"[VECTOR_STORE] Comitê: {len(documents)} blocos de {len(vigent_materials)} materiais de {len(committee_product_ids)} produtos")
            return documents[:n_results]

        except Exception as e:
            print(f"[VECTOR_STORE] Erro na busca de Comitê vigente: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            db.close()
    
    def clear(self) -> None:
        """Limpa toda a base de conhecimento."""
        db = SessionLocal()
        try:
            db.execute(sql_text("DELETE FROM document_embeddings"))
            db.commit()
        finally:
            db.close()
    
    def count(self) -> int:
        """Retorna o número de documentos na base."""
        db = SessionLocal()
        try:
            result = db.execute(sql_text("SELECT COUNT(*) FROM document_embeddings")).scalar()
            return result or 0
        finally:
            db.close()


_vector_store = None

def get_vector_store() -> VectorStore:
    """Retorna instância singleton do VectorStore, com auto-recuperação."""
    global _vector_store
    if _vector_store is None:
        try:
            _vector_store = VectorStore()
            print(f"[VECTORSTORE] Singleton criado com sucesso | openai_client={_vector_store.openai_client is not None}")
        except Exception as e:
            print(f"[VECTORSTORE] Falha ao criar singleton: {type(e).__name__}: {e}")
    elif _vector_store.openai_client is None and settings.OPENAI_API_KEY:
        try:
            _vector_store.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            print("[VECTORSTORE] Singleton existente: openai_client recuperado via lazy init")
        except Exception as e:
            print(f"[VECTORSTORE] Falha ao recuperar openai_client no singleton: {e}")
    return _vector_store



def filter_expired_results(results: list, db) -> list:
    """
    Filtra resultados de busca semântica removendo materiais expirados.
    Um material é considerado expirado se valid_until < data atual.
    Cobre múltiplos formatos de metadados: block_id, material_id, document_id.
    """
    from datetime import datetime
    from database.models import Material, ContentBlock, KnowledgeDocument
    
    if not results:
        return results
    
    now = datetime.now()
    
    block_ids = set()
    material_ids = set()
    document_ids = set()
    
    for r in results:
        meta = r.get("metadata", {})
        
        block_id = meta.get("block_id")
        if block_id:
            try:
                block_ids.add(int(block_id))
            except (ValueError, TypeError):
                pass
        
        material_id = meta.get("material_id")
        if material_id:
            try:
                material_ids.add(int(material_id))
            except (ValueError, TypeError):
                pass
        
        document_id = meta.get("document_id")
        if document_id:
            try:
                document_ids.add(int(document_id))
            except (ValueError, TypeError):
                pass
    
    expired_material_ids = set()
    expired_block_ids = set()
    expired_document_ids = set()
    
    if block_ids:
        blocks = db.query(ContentBlock).filter(ContentBlock.id.in_(block_ids)).all()
        for block in blocks:
            if block.material_id:
                material_ids.add(block.material_id)
    
    if material_ids:
        materials = db.query(Material).filter(Material.id.in_(material_ids)).all()
        for m in materials:
            if m.valid_until and m.valid_until < now:
                expired_material_ids.add(m.id)
    
    if block_ids:
        blocks = db.query(ContentBlock).filter(ContentBlock.id.in_(block_ids)).all()
        for block in blocks:
            if block.material_id in expired_material_ids:
                expired_block_ids.add(block.id)
    
    if document_ids:
        docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(document_ids)).all()
        for doc in docs:
            if doc.valid_until and doc.valid_until < now:
                expired_document_ids.add(doc.id)
    
    filtered = []
    for r in results:
        meta = r.get("metadata", {})
        is_expired = False
        
        block_id = meta.get("block_id")
        if block_id:
            try:
                if int(block_id) in expired_block_ids:
                    is_expired = True
            except (ValueError, TypeError):
                pass
        
        material_id = meta.get("material_id")
        if material_id and not is_expired:
            try:
                if int(material_id) in expired_material_ids:
                    is_expired = True
            except (ValueError, TypeError):
                pass
        
        document_id = meta.get("document_id")
        if document_id and not is_expired:
            try:
                if int(document_id) in expired_document_ids:
                    is_expired = True
            except (ValueError, TypeError):
                pass
        
        if not is_expired:
            filtered.append(r)
        else:
            print(f"[SEARCH] Resultado filtrado - conteúdo expirado: {meta}")
    
    return filtered
