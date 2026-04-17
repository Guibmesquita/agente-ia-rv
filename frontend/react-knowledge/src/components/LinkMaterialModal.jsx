import { useState, useEffect, useCallback } from 'react';
import { Search, FileText, Link2, Loader2, ExternalLink } from 'lucide-react';
import { Modal } from './Modal';
import { Button } from './Button';
import { useToast } from './Toast';
import { productsAPI } from '../services/api';
import { getMaterialTypeLabel } from '../lib/materialTypes';

function MaterialTypeChip({ type }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-muted/15 text-muted">
      {getMaterialTypeLabel(type) || type || '—'}
    </span>
  );
}

export function LinkMaterialModal({ open, onClose, productId, productName, onLinked }) {
  const [query, setQuery] = useState('');
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(false);
  const [linking, setLinking] = useState(null);
  const { addToast } = useToast();

  const fetchMaterials = useCallback(async (q) => {
    setLoading(true);
    try {
      const data = await productsAPI.linkableMaterials(productId, q);
      setMaterials(data.materials || []);
    } catch (err) {
      addToast(`Erro ao carregar materiais: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    fetchMaterials('');
  }, [open, fetchMaterials]);

  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => fetchMaterials(query), 350);
    return () => clearTimeout(timer);
  }, [query, fetchMaterials, open]);

  const handleLink = async (material) => {
    setLinking(material.id);
    try {
      await productsAPI.linkMaterial(productId, material.id);
      addToast(`Material "${material.name}" vinculado com sucesso!`, 'success');
      setMaterials((prev) => prev.filter((m) => m.id !== material.id));
      if (onLinked) onLinked();
    } catch (err) {
      addToast(`Erro ao vincular: ${err.message}`, 'error');
    } finally {
      setLinking(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Vincular material existente"
      size="lg"
    >
      <div className="space-y-4">
        <p className="text-sm text-muted">
          Selecione materiais para associar a <strong className="text-foreground">{productName}</strong>.
          Os blocos de conteúdo desses materiais ficarão disponíveis para buscas relacionadas a este produto.
        </p>

        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por nome do material..."
            className="w-full pl-9 pr-3 py-2 text-sm bg-background border border-border rounded-lg
                       focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary
                       text-foreground placeholder:text-muted"
            autoFocus
          />
        </div>

        <div className="max-h-[420px] overflow-y-auto space-y-2 pr-1">
          {loading ? (
            <div className="flex items-center justify-center py-10 gap-2 text-muted">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Carregando materiais...</span>
            </div>
          ) : materials.length === 0 ? (
            <div className="text-center py-10 text-muted">
              <FileText className="w-10 h-10 mx-auto mb-3 opacity-40" />
              <p className="text-sm font-medium text-foreground">
                {query ? 'Nenhum material encontrado' : 'Todos os materiais já estão vinculados'}
              </p>
              <p className="text-xs mt-1">
                {query
                  ? 'Tente outra busca ou faça o upload de um novo documento.'
                  : 'Use o Upload Inteligente para adicionar novos documentos.'}
              </p>
            </div>
          ) : (
            materials.map((m) => (
              <div
                key={m.id}
                className="flex items-start gap-3 p-3 bg-card rounded-card border border-border
                           hover:border-primary/40 transition-colors"
              >
                <FileText className="w-5 h-5 text-muted flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{m.name}</p>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    <MaterialTypeChip type={m.material_type} />
                    <span className="text-xs text-muted">
                      {m.blocks_count} bloco{m.blocks_count !== 1 ? 's' : ''} indexado{m.blocks_count !== 1 ? 's' : ''}
                    </span>
                    {m.primary_product_name && (
                      <span className="text-xs text-muted flex items-center gap-1">
                        <ExternalLink className="w-3 h-3" />
                        Primário: {m.primary_product_ticker || m.primary_product_name}
                      </span>
                    )}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => handleLink(m)}
                  disabled={linking !== null}
                >
                  {linking === m.id ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Link2 className="w-3 h-3" />
                  )}
                  Vincular
                </Button>
              </div>
            ))
          )}
        </div>

        <div className="flex justify-end pt-2 border-t border-border">
          <Button variant="secondary" onClick={onClose}>
            Fechar
          </Button>
        </div>
      </div>
    </Modal>
  );
}
