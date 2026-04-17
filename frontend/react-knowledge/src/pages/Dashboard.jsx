import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus, RefreshCw, Package, Search, X,
  CheckSquare, Square, Trash2, Star, StarOff, MousePointer,
} from 'lucide-react';
import { productsAPI, searchAPI } from '../services/api';
import { ProductCard } from '../components/ProductCard';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { Modal } from '../components/Modal';
import { useToast } from '../components/Toast';
import { GlobalSearchResults } from '../components/GlobalSearchResults';
import { ProductCategories } from '../components/ProductCategories';

const STORAGE_SEARCH_KEY = 'products_filter_search';
const STORAGE_CATEGORY_KEY = 'products_filter_category';
const STORAGE_COMMITTEE_KEY = 'products_filter_committee';

export function Dashboard() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState(() => localStorage.getItem(STORAGE_SEARCH_KEY) || '');
  const [categories, setCategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(() => localStorage.getItem(STORAGE_CATEGORY_KEY) || '');
  const [committeeFilter, setCommitteeFilter] = useState(() => localStorage.getItem(STORAGE_COMMITTEE_KEY) === 'true');
  const [showNewModal, setShowNewModal] = useState(false);
  const [newProduct, setNewProduct] = useState({ name: '', ticker: '', categories: [] });
  const [creating, setCreating] = useState(false);
  const [productToDelete, setProductToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [reindexingIds, setReindexingIds] = useState(new Set());
  const MAX_CONCURRENT_REINDEX = 2;

  const [globalSearchResults, setGlobalSearchResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [showGlobalResults, setShowGlobalResults] = useState(false);
  const searchContainerRef = useRef(null);
  const searchTimeoutRef = useRef(null);

  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [bulkCommitteeWorking, setBulkCommitteeWorking] = useState(false);

  useEffect(() => {
    localStorage.setItem(STORAGE_SEARCH_KEY, search);
  }, [search]);

  useEffect(() => {
    localStorage.setItem(STORAGE_CATEGORY_KEY, selectedCategory);
  }, [selectedCategory]);

  useEffect(() => {
    localStorage.setItem(STORAGE_COMMITTEE_KEY, committeeFilter);
  }, [committeeFilter]);

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
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
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
      if (committeeFilter && !product.is_committee) return false;

      const matchesCategory =
        selectedCategory === '' || product.category === selectedCategory;
      if (!matchesCategory) return false;

      const term = search.trim().toLowerCase();
      if (!term) return true;

      const nameMatch = product.name?.toLowerCase().includes(term);
      const tickerMatch = product.ticker?.toLowerCase().includes(term);
      const categoryMatch = product.category?.toLowerCase().includes(term);
      const categoriesMatch =
        Array.isArray(product.categories) &&
        product.categories.some((c) => c?.toLowerCase().includes(term));

      return nameMatch || tickerMatch || categoryMatch || categoriesMatch;
    });
  }, [products, selectedCategory, search, committeeFilter]);

  const handleCommitteeChange = (productId, newValue) => {
    setProducts((prev) =>
      prev.map((p) => (p.id === productId ? { ...p, is_committee: newValue } : p))
    );
  };

  const handleReindex = async (product) => {
    if (reindexingIds.size >= MAX_CONCURRENT_REINDEX) {
      addToast('Aguarde: já há 2 reindexamentos em andamento.', 'warning');
      return;
    }
    setReindexingIds((prev) => new Set(prev).add(product.id));
    try {
      const result = await productsAPI.reindex(product.id);
      addToast(`Reindexado: ${result.reindexed_blocks} bloco(s) de "${product.name}"`, 'success');
    } catch (err) {
      addToast(`Erro ao reindexar "${product.name}": ${err.message}`, 'error');
    } finally {
      setReindexingIds((prev) => {
        const next = new Set(prev);
        next.delete(product.id);
        return next;
      });
    }
  };

  const handleDelete = (product) => setProductToDelete(product);

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
      setNewProduct({ name: '', ticker: '', categories: [] });
      navigate(`/product/${created.id}`);
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  const handleToggleSelect = (productId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      return next;
    });
  };

  const allVisibleSelected =
    filteredProducts.length > 0 && filteredProducts.every((p) => selectedIds.has(p.id));

  const handleToggleSelectAll = () => {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredProducts.map((p) => p.id)));
    }
  };

  const exitSelectionMode = () => {
    setSelectionMode(false);
    setSelectedIds(new Set());
  };

  const handleBulkAddCommittee = async () => {
    const targets = products.filter((p) => selectedIds.has(p.id) && !p.is_committee);
    if (targets.length === 0) {
      addToast('Todos os produtos selecionados já estão no Comitê', 'info');
      return;
    }
    setBulkCommitteeWorking(true);
    try {
      await Promise.all(targets.map((p) => productsAPI.toggleCommittee(p.id)));
      setProducts((prev) =>
        prev.map((p) => (selectedIds.has(p.id) ? { ...p, is_committee: true } : p))
      );
      addToast(`${targets.length} produto(s) adicionado(s) ao Comitê SVN`, 'success');
      setSelectedIds(new Set());
    } catch (err) {
      addToast(`Erro ao atualizar Comitê: ${err.message}`, 'error');
    } finally {
      setBulkCommitteeWorking(false);
    }
  };

  const handleBulkRemoveCommittee = async () => {
    const targets = products.filter((p) => selectedIds.has(p.id) && p.is_committee);
    if (targets.length === 0) {
      addToast('Nenhum dos produtos selecionados está no Comitê', 'info');
      return;
    }
    setBulkCommitteeWorking(true);
    try {
      await Promise.all(targets.map((p) => productsAPI.toggleCommittee(p.id)));
      setProducts((prev) =>
        prev.map((p) => (selectedIds.has(p.id) ? { ...p, is_committee: false } : p))
      );
      addToast(`${targets.length} produto(s) removido(s) do Comitê SVN`, 'success');
      setSelectedIds(new Set());
    } catch (err) {
      addToast(`Erro ao atualizar Comitê: ${err.message}`, 'error');
    } finally {
      setBulkCommitteeWorking(false);
    }
  };

  const handleBulkDelete = async () => {
    setBulkDeleting(true);
    setConfirmBulkDelete(false);
    const targets = [...selectedIds];
    const results = await Promise.allSettled(targets.map((id) => productsAPI.delete(id)));
    const succeeded = targets.filter((_, i) => results[i].status === 'fulfilled');
    const failedCount = results.filter((r) => r.status === 'rejected').length;

    if (succeeded.length > 0) {
      const succeededSet = new Set(succeeded);
      setProducts((prev) => prev.filter((p) => !succeededSet.has(p.id)));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        succeeded.forEach((id) => next.delete(id));
        return next;
      });
      addToast(`${succeeded.length} produto(s) excluído(s) com sucesso`, 'success');
    }
    if (failedCount > 0) {
      addToast(
        `${failedCount} produto(s) não ${failedCount === 1 ? 'pôde' : 'puderam'} ser excluído(s)`,
        'error'
      );
    }
    if (failedCount === 0) setSelectionMode(false);
    setBulkDeleting(false);
  };

  const bulkWorking = bulkDeleting || bulkCommitteeWorking;

  return (
    <div className="space-y-6 pb-28">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Produtos</h1>
          <p className="text-muted">Gerencie a base de conhecimento dos produtos</p>
        </div>
        <div className="flex gap-2">
          {selectionMode ? (
            <Button variant="secondary" onClick={exitSelectionMode}>
              <X className="w-4 h-4" />
              Cancelar seleção
            </Button>
          ) : (
            <>
              <Button variant="secondary" onClick={() => setSelectionMode(true)}>
                <MousePointer className="w-4 h-4" />
                Selecionar
              </Button>
              <Button variant="secondary" onClick={loadProducts} disabled={loading}>
                <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                Atualizar
              </Button>
              <Button onClick={() => setShowNewModal(true)}>
                <Plus className="w-4 h-4" />
                Novo Produto
              </Button>
            </>
          )}
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
              placeholder="Filtrar por nome, ticker ou categoria..."
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

        <button
          onClick={() => setCommitteeFilter((prev) => !prev)}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-input text-sm font-medium border transition-colors whitespace-nowrap
            ${committeeFilter
              ? 'bg-amber-50 border-amber-300 text-amber-700 hover:bg-amber-100'
              : 'bg-card border-border text-muted hover:text-foreground hover:border-primary/40'
            }`}
        >
          <Star className={`w-4 h-4 ${committeeFilter ? 'fill-amber-400 text-amber-400' : ''}`} />
          Somente Comitê ({products.filter((p) => p.is_committee).length})
        </button>
      </div>

      {loading ? (
        <div className="py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : filteredProducts.length === 0 ? (
        <EmptyState
          icon={Package}
          title="Nenhum produto encontrado"
          description={
            search || selectedCategory || committeeFilter
              ? 'Tente ajustar os filtros de busca'
              : 'Comece criando um novo produto para sua base de conhecimento'
          }
          action={() => setShowNewModal(true)}
          actionLabel="Criar Produto"
        />
      ) : (
        <>
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted">
              {filteredProducts.length} produto{filteredProducts.length !== 1 ? 's' : ''} encontrado{filteredProducts.length !== 1 ? 's' : ''}
              {(search || selectedCategory || committeeFilter) && products.length !== filteredProducts.length && (
                <span className="ml-1 text-primary font-medium">
                  (de {products.length} no total)
                </span>
              )}
            </p>
            {selectionMode && (
              <button
                onClick={handleToggleSelectAll}
                className="flex items-center gap-1.5 text-sm text-primary hover:text-primary-dark transition-colors"
              >
                {allVisibleSelected ? (
                  <CheckSquare className="w-4 h-4" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                {allVisibleSelected ? 'Desselecionar todos' : 'Selecionar todos'}
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <AnimatePresence>
              {filteredProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  onClick={(p) => !selectionMode && navigate(`/product/${p.id}`)}
                  onReindex={!selectionMode ? handleReindex : undefined}
                  onDelete={!selectionMode ? handleDelete : undefined}
                  onCommitteeChange={handleCommitteeChange}
                  isReindexing={reindexingIds.has(product.id)}
                  selectionMode={selectionMode}
                  isSelected={selectedIds.has(product.id)}
                  onToggleSelect={handleToggleSelect}
                />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      <AnimatePresence>
        {selectionMode && selectedIds.size > 0 && (
          <motion.div
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50
                       bg-white border border-border rounded-2xl shadow-xl
                       flex items-center gap-3 px-5 py-3"
          >
            <span className="text-sm font-semibold text-foreground whitespace-nowrap">
              {selectedIds.size} selecionado{selectedIds.size !== 1 ? 's' : ''}
            </span>

            <div className="w-px h-5 bg-border" />

            <button
              onClick={handleBulkAddCommittee}
              disabled={bulkWorking}
              title="Adicionar ao Comitê SVN"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                         text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200
                         transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Star className="w-4 h-4 fill-amber-400 text-amber-400" />
              Adicionar ao Comitê
            </button>

            <button
              onClick={handleBulkRemoveCommittee}
              disabled={bulkWorking}
              title="Retirar do Comitê SVN"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                         text-gray-600 bg-gray-100 hover:bg-gray-200 border border-gray-200
                         transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <StarOff className="w-4 h-4" />
              Retirar do Comitê
            </button>

            <button
              onClick={() => setConfirmBulkDelete(true)}
              disabled={bulkWorking}
              title="Excluir selecionados"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                         text-red-600 bg-red-50 hover:bg-red-100 border border-red-200
                         transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Trash2 className="w-4 h-4" />
              Excluir
            </button>

            <div className="w-px h-5 bg-border" />

            <button
              onClick={exitSelectionMode}
              className="p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-gray-100 transition-colors"
              title="Cancelar seleção"
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

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
            <ProductCategories
              value={newProduct.categories}
              onChange={(cats) => setNewProduct({ ...newProduct, categories: cats })}
            />
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
            <Button type="submit" loading={creating} className="flex-1">
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

      <Modal
        open={confirmBulkDelete}
        onClose={() => !bulkDeleting && setConfirmBulkDelete(false)}
        title="Confirmar exclusão em massa"
        size="sm"
      >
        <p className="text-foreground mb-6">
          Tem certeza que deseja excluir{' '}
          <strong>{selectedIds.size} produto{selectedIds.size !== 1 ? 's' : ''}</strong>?
          Esta ação não pode ser desfeita.
        </p>
        <div className="flex gap-3 justify-end">
          <Button
            variant="secondary"
            onClick={() => setConfirmBulkDelete(false)}
            disabled={bulkDeleting}
          >
            Cancelar
          </Button>
          <button
            onClick={handleBulkDelete}
            disabled={bulkDeleting}
            className="px-4 py-2 rounded-input text-sm font-medium text-white
                       bg-red-600 hover:bg-red-700 disabled:opacity-50
                       disabled:cursor-not-allowed transition-colors"
          >
            {bulkDeleting ? 'Excluindo...' : `Excluir ${selectedIds.size} produto${selectedIds.size !== 1 ? 's' : ''}`}
          </button>
        </div>
      </Modal>
    </div>
  );
}
