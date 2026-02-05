"""
Gerenciador do banco de dados vetorial ChromaDB.
Permite armazenar e buscar documentos usando embeddings.
"""
import chromadb
import re
from openai import OpenAI
from typing import List, Optional, Set
from core.config import get_settings


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


class VectorStore:
    """Gerenciador de busca semântica usando ChromaDB e OpenAI embeddings."""
    
    def __init__(self):
        # Inicializa o cliente ChromaDB com persistência local
        self.chroma_client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIRECTORY
        )
        
        # Cria ou obtém a coleção principal
        self.collection = self.chroma_client.get_or_create_collection(
            name="knowledge_base",
            metadata={"description": "Base de conhecimento do Notion"}
        )
        
        # Cliente OpenAI para geração de embeddings
        self.openai_client = None
        if settings.OPENAI_API_KEY:
            self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    
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
        
        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata or {}]
        )
    
    def add_documents(self, doc_ids: List[str], texts: List[str], metadatas: Optional[List[dict]] = None) -> None:
        """
        Adiciona múltiplos documentos à base de conhecimento.
        
        Args:
            doc_ids: Lista de IDs únicos
            texts: Lista de conteúdos
            metadatas: Lista de metadados opcionais
        """
        embeddings = [self._generate_embedding(text) for text in texts]
        
        self.collection.add(
            ids=doc_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas or [{}] * len(texts)
        )
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Remove um documento da base de conhecimento.
        
        Args:
            doc_id: ID do documento a remover
            
        Returns:
            True se removido com sucesso
        """
        try:
            self.collection.delete(ids=[doc_id])
            return True
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
            old_count = self.collection.count()
            
            self.chroma_client.delete_collection(name="knowledge_base")
            
            self.collection = self.chroma_client.create_collection(
                name="knowledge_base",
                metadata={
                    "description": "Base de conhecimento do Notion",
                    "embedding_model": "text-embedding-3-large",
                    "dimensions": 3072,
                    "migrated_at": __import__("datetime").datetime.now().isoformat()
                }
            )
            
            return {
                "success": True,
                "old_count": old_count,
                "message": f"Collection resetada. {old_count} documentos removidos. Reindexação necessária."
            }
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
               similarity_threshold: float = 1.5) -> List[dict]:
        """
        Busca documentos relevantes para a consulta usando ranking híbrido.
        
        MELHORIA: Ranking híbrido com score composto:
        - Vetor (70%): similaridade semântica
        - Recência (20%): documentos mais novos
        - Match exato (10%): ticker/produto exato na query
        
        Args:
            query: Pergunta ou consulta do usuário
            n_results: Número máximo de resultados
            product_filter: Filtrar por produto específico (opcional)
            similarity_threshold: Threshold máximo de distância (default 0.8)
            
        Returns:
            Lista de documentos relevantes com scores
        """
        if not self.openai_client:
            return []
        
        query_embedding = self._generate_embedding(query)
        query_type = self._classify_query_type(query)
        
        where_filter = None
        if product_filter:
            where_filter = {"products": {"$contains": product_filter.upper()}}
        
        fetch_count = n_results * 3
        
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_count,
                where=where_filter
            )
        except Exception as e:
            print(f"[VECTOR_STORE] Erro com filtro, buscando sem filtro: {e}")
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_count
            )
        
        documents = []
        if results and results['documents']:
            from datetime import datetime
            now = datetime.now()
            
            query_upper = query.upper()
            
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                
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
                
                original_distance = results['distances'][0][i] if results['distances'] else 0
                
                if original_distance > similarity_threshold:
                    continue
                
                vector_score = 1.0 - min(original_distance, 1.0)
                
                recency_score = self._calculate_recency_score(metadata.get("created_at", ""), now)
                
                exact_match_score = self._calculate_exact_match_score(
                    query_upper,
                    metadata.get("product_ticker", ""),
                    metadata.get("product_name", ""),
                    metadata.get("gestora", "")
                )
                
                composite_score = (
                    vector_score * 0.70 +
                    recency_score * 0.20 +
                    exact_match_score * 0.10
                )
                
                material_type = metadata.get("material_type", "")
                block_type = metadata.get("block_type", "text")
                live_types = ["one_page", "atualizacao_taxas", "argumentos_comerciais"]
                
                if material_type in live_types:
                    composite_score *= 1.15
                
                if query_type == 'numeric' and block_type == 'table':
                    composite_score *= 1.20
                elif query_type == 'conceptual' and block_type == 'text':
                    composite_score *= 1.05
                
                composite_score = min(composite_score, 1.0)
                
                documents.append({
                    "content": doc,
                    "metadata": metadata,
                    "distance": 1.0 - composite_score,
                    "original_distance": original_distance,
                    "composite_score": composite_score,
                    "vector_score": vector_score,
                    "recency_score": recency_score,
                    "exact_match_score": exact_match_score,
                    "query_type": query_type
                })
        
        documents.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        
        deduplicated = self._deduplicate_results(documents)
        
        final_results = deduplicated[:n_results]
        
        self._log_retrieval(
            query=query,
            query_type=query_type,
            results=final_results,
            total_candidates=len(documents),
            threshold=similarity_threshold
        )
        
        return final_results
    
    def _deduplicate_results(self, documents: List[dict], similarity_threshold: float = 0.85) -> List[dict]:
        """
        Remove chunks semanticamente duplicados.
        Mantém apenas o chunk com maior score quando dois são muito similares.
        
        Critérios de duplicata:
        - Mesmo produto E mesmo tipo de bloco E conteúdo muito similar
        - Ou conteúdo quase idêntico independente do produto
        """
        if not documents:
            return documents
        
        deduplicated = []
        seen_content_hashes = set()
        
        for doc in documents:
            content = doc.get("content", "")[:500]
            metadata = doc.get("metadata", {})
            
            content_key = f"{metadata.get('product_id', '')}_{metadata.get('block_type', '')}_{hash(content)}"
            
            short_content = content[:200].lower().strip()
            
            is_duplicate = False
            for seen_doc in deduplicated:
                seen_content = seen_doc.get("content", "")[:200].lower().strip()
                
                if short_content == seen_content:
                    is_duplicate = True
                    break
                
                if len(short_content) > 50 and len(seen_content) > 50:
                    overlap = len(set(short_content.split()) & set(seen_content.split()))
                    total = len(set(short_content.split()) | set(seen_content.split()))
                    if total > 0 and overlap / total > similarity_threshold:
                        seen_product = seen_doc.get("metadata", {}).get("product_id")
                        current_product = metadata.get("product_id")
                        if seen_product == current_product:
                            is_duplicate = True
                            break
            
            if not is_duplicate and content_key not in seen_content_hashes:
                deduplicated.append(doc)
                seen_content_hashes.add(content_key)
        
        return deduplicated
    
    def _log_retrieval(
        self,
        query: str,
        query_type: str,
        results: List[dict],
        total_candidates: int,
        threshold: float
    ) -> None:
        """
        Loga a busca para observabilidade.
        Registra query, resultados, scores e metadados.
        """
        import json
        
        if not results:
            print(f"[RETRIEVAL] Query: '{query[:50]}...' | Type: {query_type} | Results: 0/{total_candidates}")
            return
        
        chunk_ids = [r.get("metadata", {}).get("material_id", "?") for r in results]
        scores = [f"{r.get('composite_score', 0):.3f}" for r in results]
        products = list(set(r.get("metadata", {}).get("product_name", "?") for r in results))
        
        print(f"[RETRIEVAL] Query: '{query[:50]}' | Type: {query_type} | Results: {len(results)}/{total_candidates} | Products: {products[:3]} | Scores: {scores[:3]}")
    
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
    
    def search_by_product(self, product_name: str, n_results: int = 10) -> List[dict]:
        """
        Busca TODOS os chunks que mencionam um produto específico.
        Faz busca textual nos metadados, não semântica.
        
        Args:
            product_name: Nome do produto para buscar
            n_results: Número máximo de resultados
            
        Returns:
            Lista de documentos que mencionam o produto
        """
        try:
            product_upper = product_name.upper().strip()
            
            results = self.collection.get(
                where={"products": {"$contains": product_upper}},
                limit=n_results
            )
            
            documents = []
            if results and results['documents']:
                from datetime import datetime
                now = datetime.now()
                
                for i, doc in enumerate(results['documents']):
                    metadata = results['metadatas'][i] if results['metadatas'] else {}
                    
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
                        "content": doc,
                        "metadata": metadata,
                        "distance": priority
                    })
            
            documents.sort(key=lambda x: x.get("distance", 0))
            
            return documents
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao buscar por produto: {e}")
            return []
    
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
            all_docs = self.collection.get()
            if all_docs and all_docs.get('documents'):
                for doc in all_docs['documents']:
                    found = ticker_pattern.findall(doc.upper())
                    tickers.update(found)
                    
            if all_docs and all_docs.get('metadatas'):
                for meta in all_docs['metadatas']:
                    products = meta.get('products', '')
                    if products:
                        found = ticker_pattern.findall(products.upper())
                        tickers.update(found)
        except Exception as e:
            print(f"[VECTOR_STORE] Erro ao extrair tickers: {e}")
        
        return tickers
    
    def get_all_products(self) -> Set[str]:
        """
        Extrai todos os produtos únicos dos metadados.
        Inclui tickers e nomes de produtos.
        
        Returns:
            Set de produtos encontrados
        """
        products = set()
        
        try:
            all_docs = self.collection.get()
            if all_docs and all_docs.get('metadatas'):
                for meta in all_docs['metadatas']:
                    product_str = meta.get('products', '')
                    if product_str:
                        for p in product_str.split(','):
                            cleaned = p.strip().upper()
                            if cleaned and len(cleaned) >= 3:
                                products.add(cleaned)
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
                Product.ticker.ilike(f"%{query}%"),
                Product.name != '__SYSTEM_UNASSIGNED__'
            ).first()
            
            if not product:
                product = db.query(Product).filter(
                    Product.name.ilike(f"%{query}%"),
                    Product.name != '__SYSTEM_UNASSIGNED__'
                ).first()
            
            if not product:
                all_products = db.query(Product).filter(
                    Product.status == 'ativo',
                    Product.name != '__SYSTEM_UNASSIGNED__'
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
    
    def clear(self) -> None:
        """Limpa toda a base de conhecimento."""
        try:
            self.chroma_client.delete_collection("knowledge_base")
        except Exception:
            pass
        self.collection = self.chroma_client.get_or_create_collection(
            name="knowledge_base",
            metadata={"description": "Base de conhecimento do Notion"}
        )
    
    def count(self) -> int:
        """Retorna o número de documentos na base."""
        return self.collection.count()


# Inicialização lazy do vector store
_vector_store = None

def get_vector_store() -> VectorStore:
    """Retorna instância singleton do VectorStore."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store

# Para compatibilidade com código existente
vector_store = None
try:
    vector_store = VectorStore()
except Exception:
    pass


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
