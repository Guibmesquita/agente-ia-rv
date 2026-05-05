import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, X, Package, Briefcase } from 'lucide-react';
import { productsAPI } from '../services/api';

export function ProductAutocomplete({
  value,
  onChange,
  placeholder = "Digite para buscar produto...",
  includePortfolios = true,
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [portfolioSuggestions, setPortfolioSuggestions] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);
  const debounceRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    if (query.length < 2) {
      setSuggestions([]);
      setPortfolioSuggestions([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const result = await productsAPI.search(query);
        setSuggestions(result.suggestions || []);
        setPortfolioSuggestions(includePortfolios ? (result.portfolios || []) : []);
        setIsOpen(true);
      } catch (err) {
        console.error('Erro na busca:', err);
        setSuggestions([]);
        setPortfolioSuggestions([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [query]);

  const handleSelect = (product) => {
    onChange(product);
    setQuery('');
    setIsOpen(false);
    setSuggestions([]);
    setPortfolioSuggestions([]);
  };

  const handleSelectPortfolio = (portfolio) => {
    setQuery('');
    setIsOpen(false);
    setSuggestions([]);
    setPortfolioSuggestions([]);
    navigate(`/portfolios/${portfolio.id}`);
  };

  const handleClear = () => {
    onChange(null);
    setQuery('');
    setSuggestions([]);
    setPortfolioSuggestions([]);
    inputRef.current?.focus();
  };

  if (value) {
    return (
      <div className="flex items-center gap-3 p-3 bg-primary/5 rounded-card border border-primary/20">
        <Package className="w-5 h-5 text-primary" />
        <div className="flex-1">
          <p className="font-medium text-foreground">{value.name}</p>
          {value.ticker && (
            <p className="text-sm text-muted">{value.ticker}</p>
          )}
        </div>
        <button
          type="button"
          onClick={handleClear}
          className="p-1 rounded hover:bg-border transition-colors"
        >
          <X className="w-4 h-4 text-muted" />
        </button>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => (suggestions.length > 0 || portfolioSuggestions.length > 0) && setIsOpen(true)}
          placeholder={placeholder}
          className="w-full pl-10 pr-4 py-3 bg-card border border-border rounded-input
                     text-foreground placeholder:text-muted
                     focus:outline-none focus:ring-2 focus:ring-primary/20"
        />
        {loading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          </div>
        )}
      </div>

      <AnimatePresence>
        {isOpen && (suggestions.length > 0 || portfolioSuggestions.length > 0) && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="absolute z-50 w-full mt-2 bg-card border border-border rounded-card shadow-lg overflow-hidden"
          >
            {portfolioSuggestions.map((portfolio) => (
              <button
                key={`portfolio-${portfolio.id}`}
                type="button"
                onClick={() => handleSelectPortfolio(portfolio)}
                className="w-full px-4 py-3 text-left hover:bg-teal-50 transition-colors
                           flex items-center gap-3 border-b border-border last:border-0"
              >
                <Briefcase className="w-5 h-5 text-teal-600" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-foreground truncate">{portfolio.name}</p>
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-teal-100 text-teal-700 whitespace-nowrap">
                      Carteira
                    </span>
                  </div>
                  <p className="text-sm text-muted truncate">
                    {portfolio.portfolio_type || ''}
                    {portfolio.member_count ? ` • ${portfolio.member_count} produto(s)` : ''}
                  </p>
                </div>
              </button>
            ))}
            {suggestions.map((product) => (
              <button
                key={`product-${product.id}`}
                type="button"
                onClick={() => handleSelect(product)}
                className="w-full px-4 py-3 text-left hover:bg-primary/5 transition-colors
                           flex items-center gap-3 border-b border-border last:border-0"
              >
                <Package className="w-5 h-5 text-muted" />
                <div>
                  <p className="font-medium text-foreground">{product.name}</p>
                  <p className="text-sm text-muted">
                    {product.ticker && `${product.ticker} • `}
                    {product.category || product.manager || ''}
                  </p>
                </div>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {query.length > 0 && query.length < 2 && (
        <p className="text-xs text-muted mt-1">Digite pelo menos 2 caracteres</p>
      )}
    </div>
  );
}
