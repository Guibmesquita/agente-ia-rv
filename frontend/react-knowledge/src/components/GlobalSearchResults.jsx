import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Package, FileText, LayoutGrid, ScrollText, MessageSquare,
  ChevronDown, ChevronUp, ExternalLink, Search, Sparkles, Briefcase
} from 'lucide-react';

const SectionHeader = ({ icon: Icon, title, count, color, isOpen, onToggle }) => (
  <button
    onClick={onToggle}
    className={`w-full flex items-center justify-between p-3 rounded-lg transition-colors ${color}`}
  >
    <div className="flex items-center gap-2">
      <Icon className="w-5 h-5" />
      <span className="font-semibold">{title}</span>
      <span className="px-2 py-0.5 text-xs rounded-full bg-white/50">{count}</span>
    </div>
    {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
  </button>
);

const MatchHighlight = ({ text, query }) => {
  if (!text || !query) return <span>{text}</span>;
  
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const index = lowerText.indexOf(lowerQuery);
  
  if (index === -1) return <span>{text}</span>;
  
  return (
    <span>
      {text.slice(0, index)}
      <mark className="bg-yellow-200 px-0.5 rounded">{text.slice(index, index + query.length)}</mark>
      {text.slice(index + query.length)}
    </span>
  );
};

const PortfolioResult = ({ item, query, onClick }) => (
  <motion.div
    initial={{ opacity: 0, x: -10 }}
    animate={{ opacity: 1, x: 0 }}
    className="p-3 bg-white rounded-lg border border-border hover:border-teal-300 hover:shadow-sm transition-all cursor-pointer"
    onClick={onClick}
  >
    <div className="flex items-start justify-between">
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <h4 className="font-medium text-foreground">
            <MatchHighlight text={item.name} query={query} />
          </h4>
          <span className="px-2 py-0.5 text-xs font-medium bg-teal-100 text-teal-700 rounded-full">
            Carteira
          </span>
          {item.portfolio_type && (
            <span className="px-2 py-0.5 text-xs bg-teal-50 text-teal-600 rounded">
              <MatchHighlight text={item.portfolio_type} query={query} />
            </span>
          )}
          {item.is_active === false && (
            <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-500 rounded">Inativa</span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1 text-sm text-muted">
          <span>{item.member_count} produto{item.member_count !== 1 ? 's' : ''}</span>
        </div>
        {item.match_context && item.match_field !== 'nome' && item.match_field !== 'tipo' && (
          <div className="mt-2 p-2 bg-teal-50/60 rounded text-sm">
            <span className="text-teal-700 font-medium">Encontrado em {item.match_field}: </span>
            <MatchHighlight text={item.match_context} query={query} />
          </div>
        )}
      </div>
      <ExternalLink className="w-4 h-4 text-muted" />
    </div>
  </motion.div>
);

const ProductResult = ({ item, query, onClick }) => (
  <motion.div
    initial={{ opacity: 0, x: -10 }}
    animate={{ opacity: 1, x: 0 }}
    className="p-3 bg-white rounded-lg border border-border hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
    onClick={onClick}
  >
    <div className="flex items-start justify-between">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <h4 className="font-medium text-foreground">
            <MatchHighlight text={item.name} query={query} />
          </h4>
          {item.ticker && (
            <span className="px-2 py-0.5 text-xs bg-primary/10 text-primary rounded">
              <MatchHighlight text={item.ticker} query={query} />
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1 text-sm text-muted">
          {item.category && <span>{item.category}</span>}
          {item.manager && (
            <>
              <span>•</span>
              <span>Gestor: <MatchHighlight text={item.manager} query={query} /></span>
            </>
          )}
        </div>
        {item.match_context && item.match_field !== 'nome' && item.match_field !== 'ticker' && (
          <div className="mt-2 p-2 bg-amber-50 rounded text-sm">
            <span className="text-amber-700 font-medium">Encontrado em {item.match_field}: </span>
            <MatchHighlight text={item.match_context} query={query} />
          </div>
        )}
      </div>
      <ExternalLink className="w-4 h-4 text-muted" />
    </div>
  </motion.div>
);

const PUBLISH_STATUS_STYLE = {
  publicado: 'bg-green-100 text-green-700',
  rascunho: 'bg-gray-100 text-gray-500',
};

const PUBLISH_STATUS_LABEL = {
  publicado: 'Publicado',
  rascunho: 'Rascunho',
};

const MaterialResult = ({ item, query, onClick }) => {
  const statusKey = item.publish_status || 'rascunho';
  const statusStyle = PUBLISH_STATUS_STYLE[statusKey] || PUBLISH_STATUS_STYLE.rascunho;
  const statusLabel = PUBLISH_STATUS_LABEL[statusKey] || statusKey;

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      className="p-3 bg-white rounded-lg border border-border hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h4 className="font-medium text-foreground">
              <MatchHighlight text={item.name} query={query} />
            </h4>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusStyle}`}>
              {statusLabel}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1 text-sm text-muted">
            <span className="text-primary">{item.product_name}</span>
            <span>•</span>
            <span className="capitalize">{item.material_type}</span>
          </div>
        </div>
        <ExternalLink className="w-4 h-4 text-muted" />
      </div>
    </motion.div>
  );
};

const BlockResult = ({ item, query, onClick }) => (
  <motion.div
    initial={{ opacity: 0, x: -10 }}
    animate={{ opacity: 1, x: 0 }}
    className="p-3 bg-white rounded-lg border border-border hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
    onClick={onClick}
  >
    <div className="flex-1">
      <div className="flex items-center gap-2">
        {item.title && (
          <h4 className="font-medium text-foreground">
            <MatchHighlight text={item.title} query={query} />
          </h4>
        )}
        <span className="px-2 py-0.5 text-xs bg-gray-100 rounded capitalize">{item.block_type}</span>
      </div>
      <div className="flex items-center gap-2 mt-1 text-sm text-muted">
        <span className="text-primary">{item.product_name}</span>
        <span>→</span>
        <span>{item.material_title}</span>
      </div>
      {item.match_context && (
        <div className="mt-2 p-2 bg-gray-50 rounded text-sm text-gray-700 line-clamp-2">
          <MatchHighlight text={item.match_context} query={query} />
        </div>
      )}
    </div>
  </motion.div>
);

const DocumentResult = ({ item, query }) => (
  <motion.div
    initial={{ opacity: 0, x: -10 }}
    animate={{ opacity: 1, x: 0 }}
    className="p-3 bg-white rounded-lg border border-border hover:border-primary/30 hover:shadow-sm transition-all"
  >
    <div className="flex items-start justify-between">
      <div className="flex-1">
        <h4 className="font-medium text-foreground">
          <MatchHighlight text={item.filename} query={query} />
        </h4>
        <div className="flex items-center gap-2 mt-1 text-sm text-muted">
          {item.category && <span>{item.category}</span>}
          <span>•</span>
          <span>{item.chunk_count} chunks</span>
          <span>•</span>
          <span className={item.is_indexed ? 'text-green-600' : 'text-amber-600'}>
            {item.is_indexed ? 'Indexado' : 'Não indexado'}
          </span>
        </div>
      </div>
    </div>
  </motion.div>
);

const ScriptResult = ({ item, query, onClick }) => (
  <motion.div
    initial={{ opacity: 0, x: -10 }}
    animate={{ opacity: 1, x: 0 }}
    className="p-3 bg-white rounded-lg border border-border hover:border-primary/30 hover:shadow-sm transition-all cursor-pointer"
    onClick={onClick}
  >
    <div className="flex-1">
      <h4 className="font-medium text-foreground">
        <MatchHighlight text={item.title} query={query} />
      </h4>
      <div className="flex items-center gap-2 mt-1 text-sm text-muted">
        <span className="text-primary">{item.product_name}</span>
        <span>•</span>
        <span className="capitalize">{item.usage_type}</span>
      </div>
      {item.match_context && (
        <div className="mt-2 p-2 bg-green-50 rounded text-sm text-green-800 line-clamp-2">
          <MatchHighlight text={item.match_context} query={query} />
        </div>
      )}
    </div>
  </motion.div>
);

export function GlobalSearchResults({ results, query, onClose }) {
  const navigate = useNavigate();
  const [openSections, setOpenSections] = useState({
    portfolios: true,
    products: true,
    materials: true,
    blocks: true,
    documents: true,
    scripts: true,
  });

  const toggleSection = (section) => {
    setOpenSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  const navigateToProduct = (id) => {
    navigate(`/product/${id}`);
    onClose?.();
  };

  const navigateToPortfolio = (id) => {
    navigate(`/portfolio/${id}`);
    onClose?.();
  };

  if (!results) return null;

  const { portfolios = [], products, materials, content_blocks, documents, scripts, total_results } = results;
  const hasResults = total_results > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="absolute top-full left-0 right-0 mt-2 bg-card rounded-xl border border-border shadow-xl max-h-[70vh] overflow-hidden z-50"
    >
      <div className="p-4 border-b border-border bg-gradient-to-r from-primary/5 to-transparent">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <span className="font-semibold text-foreground">
              Busca Global: "{query}"
            </span>
          </div>
          <span className="px-3 py-1 text-sm bg-primary/10 text-primary rounded-full">
            {total_results} resultado{total_results !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      <div className="overflow-y-auto max-h-[calc(70vh-80px)] p-4 space-y-4">
        {!hasResults ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Search className="w-12 h-12 text-muted/50 mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-1">
              Nenhum resultado encontrado
            </h3>
            <p className="text-sm text-muted">
              Tente termos diferentes ou verifique a ortografia
            </p>
          </div>
        ) : (
          <>
            {portfolios.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={Briefcase}
                  title="Carteiras"
                  count={portfolios.length}
                  color="bg-teal-50 text-teal-700 hover:bg-teal-100"
                  isOpen={openSections.portfolios}
                  onToggle={() => toggleSection('portfolios')}
                />
                <AnimatePresence>
                  {openSections.portfolios && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {portfolios.map(item => (
                        <PortfolioResult
                          key={item.id}
                          item={item}
                          query={query}
                          onClick={() => navigateToPortfolio(item.id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {products.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={Package}
                  title="Produtos"
                  count={products.length}
                  color="bg-blue-50 text-blue-700 hover:bg-blue-100"
                  isOpen={openSections.products}
                  onToggle={() => toggleSection('products')}
                />
                <AnimatePresence>
                  {openSections.products && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {products.map(item => (
                        <ProductResult
                          key={item.id}
                          item={item}
                          query={query}
                          onClick={() => navigateToProduct(item.id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {materials.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={FileText}
                  title="Materiais"
                  count={materials.length}
                  color="bg-purple-50 text-purple-700 hover:bg-purple-100"
                  isOpen={openSections.materials}
                  onToggle={() => toggleSection('materials')}
                />
                <AnimatePresence>
                  {openSections.materials && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {materials.map(item => (
                        <MaterialResult
                          key={item.id}
                          item={item}
                          query={query}
                          onClick={() => navigateToProduct(item.product_id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {content_blocks.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={LayoutGrid}
                  title="Blocos de Conteúdo"
                  count={content_blocks.length}
                  color="bg-amber-50 text-amber-700 hover:bg-amber-100"
                  isOpen={openSections.blocks}
                  onToggle={() => toggleSection('blocks')}
                />
                <AnimatePresence>
                  {openSections.blocks && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {content_blocks.map(item => (
                        <BlockResult
                          key={item.id}
                          item={item}
                          query={query}
                          onClick={() => navigateToProduct(item.product_id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {documents.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={ScrollText}
                  title="Documentos"
                  count={documents.length}
                  color="bg-green-50 text-green-700 hover:bg-green-100"
                  isOpen={openSections.documents}
                  onToggle={() => toggleSection('documents')}
                />
                <AnimatePresence>
                  {openSections.documents && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {documents.map(item => (
                        <DocumentResult key={item.id} item={item} query={query} />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {scripts.length > 0 && (
              <div className="space-y-2">
                <SectionHeader
                  icon={MessageSquare}
                  title="Scripts WhatsApp"
                  count={scripts.length}
                  color="bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  isOpen={openSections.scripts}
                  onToggle={() => toggleSection('scripts')}
                />
                <AnimatePresence>
                  {openSections.scripts && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="space-y-2 overflow-hidden"
                    >
                      {scripts.map(item => (
                        <ScriptResult
                          key={item.id}
                          item={item}
                          query={query}
                          onClick={() => navigateToProduct(item.product_id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}
          </>
        )}
      </div>
    </motion.div>
  );
}
