import { useState, useRef, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FileText, Calendar, MoreVertical, RefreshCw, Trash2, Pencil, X, Star } from 'lucide-react';
import { StatusBadge } from './StatusBadge';
import { productsAPI, materialsAPI } from '../services/api';
import { useToast } from './Toast';
import { MATERIAL_TYPE_OPTIONS } from '../lib/materialTypes';

function getProductStatus(product) {
  if (product.status === 'archived') return 'archived';

  const now = new Date();

  const allExpired = product.materials?.length > 0 && product.materials.every(m => {
    if (m.valid_until) {
      const validUntil = new Date(m.valid_until);
      return validUntil < now;
    }
    return false;
  });

  if (allExpired) return 'expirado';

  const someExpiring = product.materials?.some(m => {
    if (m.valid_until) {
      const validUntil = new Date(m.valid_until);
      const daysUntil = (validUntil - now) / (1000 * 60 * 60 * 24);
      return daysUntil > 0 && daysUntil <= 30;
    }
    return false;
  });

  if (someExpiring) return 'expirando';
  return 'ativo';
}

function EditCategoryModal({ product, onClose }) {
  const { addToast } = useToast();
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await productsAPI.get(product.id);
        setMaterials(data.materials || []);
      } catch (err) {
        addToast(`Erro ao carregar materiais: ${err.message}`, 'error');
        onClose();
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [product.id]);

  const handleSelectType = async (materialId, type, currentType) => {
    if (type === currentType || savingId) return;
    setSavingId(materialId);
    try {
      await materialsAPI.updateType(materialId, type);
      setMaterials(prev =>
        prev.map(m => m.id === materialId ? { ...m, material_type: type } : m)
      );
      addToast('Categoria atualizada!', 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div>
            <p className="text-xs text-muted font-medium uppercase tracking-wide mb-0.5">Configurar Tipo de Material</p>
            <h3 className="font-semibold text-foreground text-base leading-tight">{product.name}</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-muted hover:text-foreground hover:bg-gray-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <svg className="w-6 h-6 animate-spin text-primary" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          ) : materials.length === 0 ? (
            <p className="text-sm text-muted text-center py-8">Nenhum material encontrado.</p>
          ) : (
            <div className="space-y-5">
              {materials.map(material => (
                <div key={material.id}>
                  {materials.length > 1 && (
                    <p className="text-sm font-medium text-foreground mb-2 truncate">{material.name || 'Material sem nome'}</p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {MATERIAL_TYPE_OPTIONS.map(opt => {
                      const isSelected = material.material_type === opt.value;
                      const isSaving = savingId === material.id;
                      return (
                        <button
                          key={opt.value}
                          disabled={isSaving}
                          onClick={() => handleSelectType(material.id, opt.value, material.material_type)}
                          className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-all ${
                            isSelected
                              ? 'bg-primary text-white border-primary shadow-sm'
                              : 'bg-white text-gray-600 border-gray-200 hover:border-primary hover:text-primary'
                          } ${isSaving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                        >
                          {isSaving && isSelected ? (
                            <span className="flex items-center gap-1">
                              <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                              </svg>
                              {opt.label}
                            </span>
                          ) : opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-border flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 transition-colors"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}

export function ProductCard({ product, onClick, onReindex, onDelete, onCommitteeChange, isReindexing = false }) {
  const { addToast } = useToast();
  const status = getProductStatus(product);
  const materialsCount = product.materials_count ?? product.materials?.length ?? 0;
  const blocksCount = product.blocks_count ?? product.materials?.reduce((acc, m) => acc + (m.blocks?.length || 0), 0) ?? 0;
  const [menuOpen, setMenuOpen] = useState(false);
  const [editCategoryOpen, setEditCategoryOpen] = useState(false);
  const [isCommittee, setIsCommittee] = useState(Boolean(product.is_committee));
  const [togglingCommittee, setTogglingCommittee] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    setIsCommittee(Boolean(product.is_committee));
  }, [product.is_committee]);

  const handleToggleCommittee = async (e) => {
    e.stopPropagation();
    if (togglingCommittee) return;
    setTogglingCommittee(true);
    const previous = isCommittee;
    setIsCommittee(!previous);
    try {
      const result = await productsAPI.toggleCommittee(product.id);
      const newValue = Boolean(result?.is_committee);
      setIsCommittee(newValue);
      onCommitteeChange?.(product.id, newValue);
      addToast(
        newValue
          ? `${product.name} adicionado ao Comitê SVN`
          : `${product.name} removido do Comitê SVN`,
        'success'
      );
    } catch (err) {
      setIsCommittee(previous);
      addToast(`Erro ao atualizar Comitê: ${err.message}`, 'error');
    } finally {
      setTogglingCommittee(false);
    }
  };

  useEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [menuOpen]);

  const handleMenuClick = (e) => {
    e.stopPropagation();
    if (isReindexing) return;
    setMenuOpen((prev) => !prev);
  };

  const handleReindex = (e) => {
    e.stopPropagation();
    setMenuOpen(false);
    onReindex?.(product);
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    setMenuOpen(false);
    onDelete?.(product);
  };

  const handleEditCategory = (e) => {
    e.stopPropagation();
    setMenuOpen(false);
    setEditCategoryOpen(true);
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: isReindexing ? 0.6 : 1, y: 0 }}
        whileHover={{ y: isReindexing ? 0 : -2, boxShadow: isReindexing ? undefined : '0 4px 12px rgba(0, 0, 0, 0.1)' }}
        onClick={() => !isReindexing && onClick(product)}
        className={`bg-card rounded-card border border-border p-5 shadow-card transition-opacity duration-200 ${isReindexing ? 'cursor-default' : 'cursor-pointer'}`}
      >
        <div className="flex justify-between items-start mb-3">
          <h3 className="font-semibold text-foreground text-lg flex-1 mr-2">{product.name}</h3>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              type="button"
              onClick={handleToggleCommittee}
              disabled={togglingCommittee}
              title={isCommittee
                ? 'Produto do Comitê SVN — clique para remover'
                : 'Marcar como produto do Comitê SVN'}
              aria-pressed={isCommittee}
              aria-label={isCommittee ? 'Remover do Comitê' : 'Adicionar ao Comitê'}
              className={`p-1 rounded-md transition-all ${
                togglingCommittee ? 'opacity-50 cursor-wait' : 'cursor-pointer hover:bg-gray-100'
              }`}
            >
              <Star
                className={`w-4 h-4 transition-colors ${
                  isCommittee
                    ? 'text-amber-400 fill-amber-400'
                    : 'text-gray-300 hover:text-amber-400'
                }`}
              />
            </button>
            <StatusBadge status={status} />
            {(onReindex || onDelete) && (
              <div className="relative" ref={menuRef}>
                {isReindexing ? (
                  <span title="Reindexando..." className="p-1 flex items-center justify-center">
                    <svg className="w-4 h-4 animate-spin text-primary" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10"
                              stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor"
                            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                  </span>
                ) : (
                  <button
                    onClick={handleMenuClick}
                    className="p-1 rounded-md text-muted hover:text-foreground hover:bg-gray-100 transition-colors"
                    title="Opções"
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                )}
                {menuOpen && !isReindexing && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="absolute right-0 top-full mt-1 w-44 bg-white border border-border rounded-lg shadow-md z-50 py-1"
                  >
                    <button
                      onClick={handleEditCategory}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-gray-50 transition-colors"
                    >
                      <Pencil className="w-4 h-4 text-muted" />
                      Tipo do Material
                    </button>
                    {onReindex && (
                      <button
                        onClick={handleReindex}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-gray-50 transition-colors"
                      >
                        <RefreshCw className="w-4 h-4 text-muted" />
                        Reindexar
                      </button>
                    )}
                    {onDelete && (
                      <button
                        onClick={handleDelete}
                        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                        Deletar
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {(product.categories && product.categories.length > 0) ? (
          <div className="flex flex-wrap gap-1 mb-3">
            {product.categories.map((cat) => (
              <span key={cat}
                className={`px-2 py-0.5 text-xs font-medium rounded-full border
                  ${cat === 'Comitê'
                    ? 'bg-amber-50 text-amber-700 border-amber-200'
                    : 'bg-muted/20 text-muted border-border'}`}>
                {cat}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted mb-3">{product.category || 'Sem categoria'}</p>
        )}

        {product.ticker && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            <span className="px-2 py-0.5 bg-primary/10 text-primary text-xs font-medium rounded">
              {product.ticker}
            </span>
          </div>
        )}

        <div className="flex items-center gap-4 text-sm text-muted">
          <div className="flex items-center gap-1.5">
            <FileText className="w-4 h-4" />
            <span>{materialsCount} materiais</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Calendar className="w-4 h-4" />
            <span>{blocksCount} blocos</span>
          </div>
        </div>

        {isReindexing && (
          <p className="text-xs text-primary mt-3 font-medium">Reindexando...</p>
        )}

        {!isReindexing && product.description && (
          <p className="text-sm text-muted mt-3 line-clamp-2">{product.description}</p>
        )}

        {!isReindexing && (() => {
          let ki = null;
          try {
            ki = product.key_info
              ? (typeof product.key_info === 'string' ? JSON.parse(product.key_info) : product.key_info)
              : null;
          } catch { ki = null; }
          if (!ki) return null;
          const summary =
            (ki.investment_thesis && String(ki.investment_thesis).trim()) ||
            (Array.isArray(ki.additional_highlights) && ki.additional_highlights.find((h) => h && String(h).trim())) ||
            null;
          if (!summary) return null;
          return (
            <p className="text-xs text-foreground/80 mt-2 line-clamp-2 italic border-l-2 border-primary/40 pl-2">
              {summary}
            </p>
          );
        })()}
      </motion.div>

      {editCategoryOpen && (
        <EditCategoryModal
          product={product}
          onClose={() => setEditCategoryOpen(false)}
        />
      )}
    </>
  );
}
