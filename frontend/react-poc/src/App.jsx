import { useState, useMemo, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { mockProducts, categories, statuses, allTickers } from './data/mockProducts';

console.log('React POC loading...', { mockProducts: mockProducts?.length });

function StatusBadge({ status }) {
  const config = {
    ativo: { bg: 'bg-green-100', text: 'text-green-700', label: 'Ativo' },
    expirando: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: 'Expirando' },
    expirado: { bg: 'bg-red-100', text: 'text-red-700', label: 'Expirado' },
  }[status] || { bg: 'bg-gray-100', text: 'text-gray-700', label: 'Rascunho' };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      {config.label}
    </span>
  );
}

function ProductCard({ product, onClick }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2, boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)' }}
      onClick={() => onClick(product)}
      className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm cursor-pointer"
    >
      <div className="flex justify-between items-start mb-2">
        <h3 className="font-semibold text-gray-900">{product.name}</h3>
        <StatusBadge status={product.status} />
      </div>
      <p className="text-sm text-gray-500 mb-3">{product.category}</p>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {product.tickers.slice(0, 3).map((ticker) => (
          <span key={ticker} className="px-2 py-0.5 bg-red-50 text-red-800 text-xs font-medium rounded">
            {ticker}
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${product.confidence >= 80 ? 'bg-green-500' : product.confidence >= 50 ? 'bg-yellow-500' : 'bg-red-500'}`}
            style={{ width: `${product.confidence}%` }}
          />
        </div>
        <span className="text-xs text-gray-500">{product.confidence}%</span>
      </div>
    </motion.div>
  );
}

function Drawer({ product, open, onClose, onUpdate }) {
  const [rate, setRate] = useState(product?.rate || '');
  const [onePage, setOnePage] = useState(product?.onePage || '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (product) {
      setRate(product.rate || '');
      setOnePage(product.onePage || '');
    }
  }, [product]);

  if (!open || !product) return null;

  const handleSave = async () => {
    setSaving(true);
    await new Promise(r => setTimeout(r, 800));
    onUpdate(product.id, { rate, onePage });
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="fixed inset-0 bg-black/40" onClick={onClose} />
      <motion.div
        initial={{ x: '100%' }}
        animate={{ x: 0 }}
        exit={{ x: '100%' }}
        className="ml-auto relative w-full max-w-lg bg-white h-full shadow-xl flex flex-col"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="font-semibold text-lg">{product.name}</h2>
            <p className="text-sm text-gray-500">{product.category}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-full">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div>
            <label className="block text-sm font-medium mb-1">Taxa</label>
            <input
              type="text"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-red-200 focus:border-red-500"
              placeholder="Ex: 1.0% a.a."
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">One-Page</label>
            <textarea
              value={onePage}
              onChange={(e) => setOnePage(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 border rounded-lg focus:ring-2 focus:ring-red-200 focus:border-red-500"
              placeholder="Descrição do produto..."
            />
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="w-full py-2 bg-red-800 text-white rounded-lg font-medium hover:bg-red-900 disabled:opacity-50"
          >
            {saving ? 'Salvando...' : 'Salvar Alterações'}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

function App() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedProduct, setSelectedProduct] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setProducts(mockProducts);
      setLoading(false);
    }, 800);
    return () => clearTimeout(timer);
  }, []);

  const filteredProducts = useMemo(() => {
    return products.filter((product) =>
      search === '' ||
      product.name.toLowerCase().includes(search.toLowerCase()) ||
      product.tickers.some(t => t.toLowerCase().includes(search.toLowerCase()))
    );
  }, [products, search]);

  const handleProductUpdate = (productId, updates) => {
    setProducts((prev) =>
      prev.map((p) => p.id === productId ? { ...p, ...updates } : p)
    );
    if (selectedProduct?.id === productId) {
      setSelectedProduct((prev) => ({ ...prev, ...updates }));
    }
  };

  return (
    <div className="min-h-screen bg-orange-50">
      <header className="bg-white border-b sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-xl font-bold text-gray-900">Base de Conhecimento</h1>
              <p className="text-sm text-gray-500">POC UX - React + Tailwind</p>
            </div>
            <button className="px-4 py-2 bg-red-800 text-white rounded-lg font-medium hover:bg-red-900">
              Novo Produto
            </button>
          </div>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nome ou ticker..."
            className="w-full max-w-md px-4 py-2 border rounded-lg focus:ring-2 focus:ring-red-200 focus:border-red-500"
          />
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <p className="text-sm text-gray-500 mb-6">
          {loading ? 'Carregando...' : `${filteredProducts.length} produtos encontrados`}
        </p>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="bg-white rounded-xl border p-5 animate-pulse">
                <div className="h-5 bg-gray-200 rounded w-3/4 mb-3" />
                <div className="h-4 bg-gray-200 rounded w-1/2 mb-3" />
                <div className="h-6 bg-gray-200 rounded w-1/3" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <AnimatePresence>
              {filteredProducts.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  onClick={setSelectedProduct}
                />
              ))}
            </AnimatePresence>
          </div>
        )}
      </main>

      <AnimatePresence>
        {selectedProduct && (
          <Drawer
            product={selectedProduct}
            open={!!selectedProduct}
            onClose={() => setSelectedProduct(null)}
            onUpdate={handleProductUpdate}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
