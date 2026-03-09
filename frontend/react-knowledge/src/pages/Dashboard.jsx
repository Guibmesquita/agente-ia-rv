import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Filter, RefreshCw, Package, Search, X } from 'lucide-react';
import { productsAPI, searchAPI } from '../services/api';
import { ProductCard } from '../components/ProductCard';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { Modal } from '../components/Modal';
import { useToast } from '../components/Toast';
import { GlobalSearchResults } from '../components/GlobalSearchResults';

export function Dashboard() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState('');
  const [showNewModal, setShowNewModal] = useState(false);
  const [newProduct, setNewProduct] = useState({ name: '', ticker: '', category: '' });
  const [creating, setCreating] = useState(false);
  const [productToDelete, setProductToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  
  const [globalSearchResults, setGlobalSearchResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [showGlobalResults, setShowGlobalResults] = useState(false);
  const searchContainerRef = useRef(null);
  const searchTimeoutRef = useRef(null);

  const loadProducts = async () => {
    try {
      setLoading(true);
      const data = await productsAPI.list();
      setProducts(data.products || data);
    } catch (err) {
      addToast('Erro ao carregar produtos', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadCategories = async () => {
    try {
      const data = await productsAPI.getCategories();
      setCategories(data.categories || []);
    } catch (err) {
      console.error('Erro ao carregar categorias:', err);
    }
  };

  useEffect(() => {
    loadProducts();
    loadCategories();
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target)) {
        setShowGlobalResults(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const performGlobalSearch = useCallback(async (query) => {
    if (!query || query.length < 2) {
      setGlobalSearchResults(null);
      setShowGlobalResults(false);
      return;
    }

    setIsSearching(true);
    try {
      const results = await searchAPI.global(query);
      setGlobalSearchResults(results);
      setShowGlobalResults(true);
    } catch (err) {
      console.error('Erro na busca global:', err);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearchChange = (value) => {
    setSearch(value);
    
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    
    searchTimeoutRef.current = setTimeout(() => {
      performGlobalSearch(value);
    }, 300);
  };

  const clearSearch = () => {
    setSearch('');
    setGlobalSearchResults(null);
    setShowGlobalResults(false);
  };

  const filteredProducts = useMemo(() => {
    return products.filter((product) => {
      const matchesCategory = selectedCategory === '' ||
        product.category === selectedCategory;
      return matchesCategory;
    });
  }, [products, selectedCategory]);

  const handleReindex = async (product) => {
    try {
      const result = await productsAPI.reindex(product.id);
      addToast(`Reindexado: ${result.reindexed_blocks} bloco(s) de "${product.name}"`, 'success');
    } catch (err) {
      addToast(`Erro ao reindexar: ${err.message}`, 'error');
    }
  };

  const handleDelete = (product) => {
    setProductToDelete(product);
  };

  const confirmDelete = async () => {
    if (!productToDelete) return;
    setDeleting(true);
    try {
      await productsAPI.delete(productToDelete.id);
      setProducts((prev) => prev.filter((p) => p.id !== productToDelete.id));
      addToast(`"${productToDelete.name}" excluído com sucesso`, 'success');
      setProductToDelete(null);
    } catch (err) {
      addToast(`Erro ao excluir: ${err.message}`, 'error');
    } finally {
      setDeleting(false);
    }
  };

  const handleCreateProduct = async (e) => {
    e.preventDefault();
    if (!newProduct.name.trim()) {
      addToast('Nome do produto é obrigatório', 'warning');
      return;
    }

    setCreating(true);
    try {
      const created = await productsAPI.create(newProduct);
      addToast('Produto criado com sucesso!', 'success');
      setShowNewModal(false);
      setNewProduct({ name: '', ticker: '', category: '' });
      navigate(`/product/${created.id}`);
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Produtos</h1>
          <p className="text-muted">Gerencie a base de conhecimento dos produtos</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={loadProducts} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
          <Button onClick={() => setShowNewModal(true)}>
            <Plus className="w-4 h-4" />
            Novo Produto
          </Button>
        </div>
      </div>

      <div className="flex gap-4">
        <div className="flex-1 relative" ref={searchContainerRef}>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              onFocus={() => search.length >= 2 && setShowGlobalResults(true)}
              placeholder="Busca global: produtos, gestores, materiais, documentos..."
              className="w-full pl-10 pr-10 py-3 bg-card border border-border rounded-xl
                        text-foreground placeholder:text-muted/60
                        focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50
                        transition-all"
            />
            {search && (
              <button
                onClick={clearSearch}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full
                          text-muted hover:text-foreground hover:bg-gray-100 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            )}
            {isSearching && (
              <div className="absolute right-10 top-1/2 -translate-y-1/2">
                <LoadingSpinner size="sm" />
              </div>
            )}
          </div>
          
          <AnimatePresence>
            {showGlobalResults && globalSearchResults && (
              <GlobalSearchResults
                results={globalSearchResults}
                query={search}
                onClose={() => setShowGlobalResults(false)}
              />
            )}
          </AnimatePresence>
        </div>
        
        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          className="px-4 py-2 bg-card border border-border rounded-input text-foreground
                     focus:outline-none focus:ring-2 focus:ring-primary/20"
        >
          <option value="">Todas categorias</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>{cat}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : filteredProducts.length === 0 ? (
        <EmptyState
          icon={Package}
          title="Nenhum produto encontrado"
          description={selectedCategory
            ? "Tente ajustar os filtros de busca"
            : "Comece criando um novo produto para sua base de conhecimento"
          }
          action={() => setShowNewModal(true)}
          actionLabel="Criar Produto"
        />
      ) : (
        <>
          <p className="text-sm text-muted">
            {filteredProducts.length} produto{filteredProducts.length !== 1 ? 's' : ''} encontrado{filteredProducts.length !== 1 ? 's' : ''}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <AnimatePresence>
              {filteredProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  onClick={(p) => navigate(`/product/${p.id}`)}
                  onReindex={handleReindex}
                  onDelete={handleDelete}
                />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      <Modal
        open={showNewModal}
        onClose={() => setShowNewModal(false)}
        title="Novo Produto"
      >
        <form onSubmit={handleCreateProduct} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Nome do Produto *
            </label>
            <input
              type="text"
              value={newProduct.name}
              onChange={(e) => setNewProduct({ ...newProduct, name: e.target.value })}
              placeholder="Ex: Fundo XPTO"
              className="w-full px-3 py-2 bg-card border border-border rounded-input
                        text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Ticker
            </label>
            <input
              type="text"
              value={newProduct.ticker}
              onChange={(e) => setNewProduct({ ...newProduct, ticker: e.target.value.toUpperCase() })}
              placeholder="Ex: XPTO11"
              className="w-full px-3 py-2 bg-card border border-border rounded-input
                        text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Categoria
            </label>
            <select
              value={newProduct.category}
              onChange={(e) => setNewProduct({ ...newProduct, category: e.target.value })}
              className="w-full px-3 py-2 bg-card border border-border rounded-input
                        text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              <option value="">Selecione...</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </div>

          <div className="flex gap-3 pt-4">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setShowNewModal(false)}
              className="flex-1"
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={creating}
              className="flex-1"
            >
              Criar Produto
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={!!productToDelete}
        onClose={() => !deleting && setProductToDelete(null)}
        title="Confirmar exclusão"
        size="sm"
      >
        <p className="text-foreground mb-6">
          Tem certeza que deseja excluir <strong>"{productToDelete?.name}"</strong>?
          Esta ação não pode ser desfeita.
        </p>
        <div className="flex gap-3 justify-end">
          <Button
            variant="secondary"
            onClick={() => setProductToDelete(null)}
            disabled={deleting}
          >
            Cancelar
          </Button>
          <button
            onClick={confirmDelete}
            disabled={deleting}
            className="px-4 py-2 rounded-input text-sm font-medium text-white
                       bg-red-600 hover:bg-red-700 disabled:opacity-50
                       disabled:cursor-not-allowed transition-colors"
          >
            {deleting ? 'Excluindo...' : 'Excluir'}
          </button>
        </div>
      </Modal>
    </div>
  );
}
