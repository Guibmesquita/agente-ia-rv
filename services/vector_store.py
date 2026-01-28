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
        Gera um embedding para o texto usando o modelo text-embedding-3-small.
        
        Args:
            text: Texto para gerar embedding
            
        Returns:
            Lista de floats representando o embedding
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key não configurada")
        
        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
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
    
    def search(self, query: str, n_results: int = 3, product_filter: str = None) -> List[dict]:
        """
        Busca documentos relevantes para a consulta.
        
        Args:
            query: Pergunta ou consulta do usuário
            n_results: Número máximo de resultados
            product_filter: Filtrar por produto específico (opcional)
            
        Returns:
            Lista de documentos relevantes com scores
        """
        if not self.openai_client:
            return []
        
        query_embedding = self._generate_embedding(query)
        
        where_filter = None
        if product_filter:
            where_filter = {"products": {"$contains": product_filter.upper()}}
        
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where_filter
            )
        except Exception as e:
            print(f"[VECTOR_STORE] Erro com filtro, buscando sem filtro: {e}")
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )
        
        documents = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                documents.append({
                    "content": doc,
                    "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                    "distance": results['distances'][0][i] if results['distances'] else None
                })
        
        return documents
    
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
                for i, doc in enumerate(results['documents']):
                    documents.append({
                        "content": doc,
                        "metadata": results['metadatas'][i] if results['metadatas'] else {},
                        "distance": 0
                    })
            
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
