import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Plus, Trash2, RefreshCw, X, Search,
  Users, FileText, Edit2, Check, Briefcase,
} from 'lucide-react';
import { portfoliosAPI, materialsAPI } from '../services/api';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { Modal } from '../components/Modal';
import { useToast } from '../components/Toast';

const PORTFOLIO_TYPE_OPTIONS = [
  { value: '', label: '— Sem tipo —' },
  { value: 'FII', label: 'FII (Fundo Imobiliário)' },
  { value: 'Ações', label: 'Ações' },
  { value: 'Misto', label: 'Misto' },
  { value: 'Renda Fixa', label: 'Renda Fixa' },
  { value: 'Multimercado', label: 'Multimercado' },
  { value: 'Internacional', label: 'Internacional' },
  { value: 'Outro', label: 'Outro' },
];

function ProductTypeBadge({ type }) {
  const colors = {
    fii: 'bg-emerald-100 text-emerald-700',
    acao: 'bg-blue-100 text-blue-700',
    etf: 'bg-violet-100 text-violet-700',
    fundo: 'bg-indigo-100 text-indigo-700',
    estruturada: 'bg-orange-100 text-orange-700',
    debenture: 'bg-yellow-100 text-yellow-700',
  };
  const label = {
    fii: 'FII', acao: 'Ação', etf: 'ETF', fundo: 'Fundo',
    estruturada: 'Estruturada', debenture: 'Debênture',
  };
  const cls = colors[type] || 'bg-gray-100 text-gray-600';
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {label[type] || type || 'Outro'}
    </span>
  );
}

export function PortfolioDetail() {
  const { id } = useParams(); // rota /portfolios/:id
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  const [showAddMember, setShowAddMember] = useState(false);
  const [memberSearch, setMemberSearch] = useState('');
  const [availableProducts, setAvailableProducts] = useState([]);
  const [searchingProducts, setSearchingProducts] = useState(false);
  const [addingMemberId, setAddingMemberId] = useState(null);
  const [removingMemberId, setRemovingMemberId] = useState(null);

  const [reindexing, setReindexing] = useState(false);

  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadName, setUploadName] = useState('');
  const [uploading, setUploading] = useState(false);

  const loadPortfolio = useCallback(async () => {
    try {
      setLoading(true);
      const data = await portfoliosAPI.get(id);
      setPortfolio(data);
      setEditForm({
        name: data.name,
        portfolio_type: data.portfolio_type || '',
        description: data.description || '',
        is_active: data.is_active,
      });
    } catch (err) {
      addToast(`Erro ao carregar carteira: ${err.message}`, 'error');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadPortfolio();
  }, [loadPortfolio]);

  const handleSaveEdit = async () => {
    if (!editForm.name?.trim()) {
      addToast('Nome é obrigatório', 'warning');
      return;
    }
    setSaving(true);
    try {
      const updated = await portfoliosAPI.update(id, editForm);
      setPortfolio(updated);
      setEditing(false);
      addToast('Carteira atualizada com sucesso', 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const searchProducts = useCallback(async (q) => {
    setSearchingProducts(true);
    try {
      const data = await portfoliosAPI.availableProducts(id, q);
      setAvailableProducts(data.products || []);
    } catch (err) {
      addToast(`Erro ao buscar produtos: ${err.message}`, 'error');
    } finally {
      setSearchingProducts(false);
    }
  }, [id]);

  useEffect(() => {
    if (showAddMember) {
      const t = setTimeout(() => searchProducts(memberSearch), 300);
      return () => clearTimeout(t);
    }
  }, [memberSearch, showAddMember, searchProducts]);

  useEffect(() => {
    if (showAddMember) searchProducts('');
  }, [showAddMember]);

  const handleAddMember = async (productId) => {
    setAddingMemberId(productId);
    try {
      const updated = await portfoliosAPI.addMember(id, productId);
      setPortfolio(updated);
      setAvailableProducts((prev) => prev.filter((p) => p.id !== productId));
      addToast('Produto adicionado à carteira', 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setAddingMemberId(null);
    }
  };

  const handleRemoveMember = async (productId, productName) => {
    if (!confirm(`Remover "${productName}" da carteira?`)) return;
    setRemovingMemberId(productId);
    try {
      const updated = await portfoliosAPI.removeMember(id, productId);
      setPortfolio(updated);
      addToast(`"${productName}" removido da carteira`, 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setRemovingMemberId(null);
    }
  };

  const handleReindex = async () => {
    setReindexing(true);
    try {
      const result = await portfoliosAPI.reindex(id);
      addToast(`Reindexação iniciada para ${result.reindexed} material(is)`, 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    } finally {
      setReindexing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!portfolio) {
    return (
      <div className="text-center py-20">
        <p className="text-muted">Carteira não encontrada.</p>
        <Button className="mt-4" onClick={() => navigate('/')}>Voltar</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-20">
      {/* Cabeçalho */}
      <div className="flex items-start gap-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-lg text-muted hover:text-foreground hover:bg-gray-100 transition-colors mt-1"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="space-y-3">
              <input
                type="text"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                className="text-2xl font-bold w-full bg-card border border-border rounded-lg
                           px-3 py-1.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                placeholder="Nome da carteira"
                autoFocus
              />
              <div className="flex gap-3">
                <select
                  value={editForm.portfolio_type}
                  onChange={(e) => setEditForm({ ...editForm, portfolio_type: e.target.value })}
                  className="px-3 py-1.5 bg-card border border-border rounded-lg text-sm text-foreground
                             focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  {PORTFOLIO_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                <label className="flex items-center gap-2 text-sm text-muted">
                  <input
                    type="checkbox"
                    checked={editForm.is_active}
                    onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                  />
                  Ativa
                </label>
              </div>
              <textarea
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                placeholder="Descrição (opcional)..."
                rows={2}
                className="w-full px-3 py-2 bg-card border border-border rounded-lg text-sm text-foreground
                           focus:outline-none focus:ring-2 focus:ring-primary/20 resize-none"
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSaveEdit} loading={saving}>
                  <Check className="w-4 h-4" />
                  Salvar
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
                  <X className="w-4 h-4" />
                  Cancelar
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full
                                 bg-teal-100 text-teal-700 text-xs font-semibold border border-teal-200">
                  <Briefcase className="w-3.5 h-3.5" />
                  Carteira Recomendada
                </span>
                {portfolio.portfolio_type && (
                  <span className="px-2.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700
                                   text-xs font-medium border border-indigo-200">
                    {portfolio.portfolio_type}
                  </span>
                )}
                {!portfolio.is_active && (
                  <span className="px-2.5 py-0.5 rounded-full bg-gray-100 text-gray-500
                                   text-xs font-medium border border-gray-200">
                    Inativa
                  </span>
                )}
              </div>
              <h1 className="text-2xl font-bold text-foreground mt-1">{portfolio.name}</h1>
              {portfolio.description && (
                <p className="text-muted text-sm mt-1">{portfolio.description}</p>
              )}
            </>
          )}
        </div>

        {!editing && (
          <div className="flex gap-2 shrink-0">
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
              <Edit2 className="w-4 h-4" />
              Editar
            </Button>
            <Button variant="secondary" size="sm" onClick={handleReindex} disabled={reindexing}>
              <RefreshCw className={`w-4 h-4 ${reindexing ? 'animate-spin' : ''}`} />
              Reindexar
            </Button>
          </div>
        )}
      </div>

      {/* Estatísticas */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {[
          { label: 'Membros', value: portfolio.members?.length ?? portfolio.members_count ?? 0, icon: Users },
          { label: 'Materiais', value: portfolio.materials?.length ?? portfolio.materials_count ?? 0, icon: FileText },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="bg-card border border-border rounded-xl p-4 flex items-center gap-3">
            <div className="p-2 bg-primary/10 rounded-lg">
              <Icon className="w-4 h-4 text-primary" />
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">{value}</p>
              <p className="text-xs text-muted">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Produtos membros */}
      <div className="bg-card border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Users className="w-4 h-4 text-muted" />
            Produtos da Carteira
            <span className="px-2 py-0.5 bg-muted/10 rounded-full text-xs font-normal text-muted">
              {portfolio.members?.length ?? 0}
            </span>
          </h2>
          <Button size="sm" onClick={() => setShowAddMember(true)}>
            <Plus className="w-4 h-4" />
            Adicionar produto
          </Button>
        </div>

        {(portfolio.members?.length ?? 0) === 0 ? (
          <div className="text-center py-8 text-muted text-sm">
            <Users className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p>Nenhum produto na carteira ainda.</p>
            <p className="text-xs mt-1">Clique em "Adicionar produto" para incluir membros.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {portfolio.members.map((member) => (
              <motion.div
                key={member.product_id}
                layout
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 12 }}
                className="flex items-center gap-3 p-3 rounded-lg border border-border
                           bg-gray-50 hover:bg-gray-100 transition-colors group"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-sm text-foreground truncate">{member.name}</span>
                    {member.ticker && (
                      <span className="font-mono text-xs text-muted bg-muted/10 px-1.5 py-0.5 rounded">
                        {member.ticker}
                      </span>
                    )}
                    <ProductTypeBadge type={member.product_type} />
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => navigate(`/product/${member.product_id}`)}
                    className="text-xs text-primary hover:underline opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Ver produto
                  </button>
                  <button
                    onClick={() => handleRemoveMember(member.product_id, member.name)}
                    disabled={removingMemberId === member.product_id}
                    className="p-1.5 rounded-md text-muted hover:text-red-600 hover:bg-red-50
                               opacity-0 group-hover:opacity-100 transition-all
                               disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Remover da carteira"
                  >
                    {removingMemberId === member.product_id ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Materiais */}
      <div className="bg-card border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <FileText className="w-4 h-4 text-muted" />
            Materiais da Carteira
            <span className="px-2 py-0.5 bg-muted/10 rounded-full text-xs font-normal text-muted">
              {portfolio.materials?.length ?? 0}
            </span>
          </h2>
          <Button size="sm" variant="secondary" onClick={() => navigate(`/upload?portfolio_id=${id}&portfolio_name=${encodeURIComponent(portfolio.name)}`)}>
            <Plus className="w-4 h-4" />
            Fazer upload
          </Button>
        </div>

        {(portfolio.materials?.length ?? 0) === 0 ? (
          <div className="text-center py-8 text-muted text-sm">
            <FileText className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p>Nenhum material enviado ainda.</p>
            <p className="text-xs mt-1">Use "Fazer upload" para enviar PDFs e documentos desta carteira.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {portfolio.materials.map((mat) => (
              <div
                key={mat.id}
                className="flex items-center gap-3 p-3 rounded-lg border border-border bg-gray-50"
              >
                <FileText className="w-4 h-4 text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{mat.name || mat.source_filename || `Material #${mat.id}`}</p>
                  <p className="text-xs text-muted">{mat.material_type}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {mat.is_indexed ? (
                    <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-xs font-medium">
                      Indexado
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs font-medium">
                      {mat.publish_status}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modal: Adicionar produto */}
      <Modal
        open={showAddMember}
        onClose={() => { setShowAddMember(false); setMemberSearch(''); }}
        title="Adicionar produto à carteira"
      >
        <div className="space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <input
              type="text"
              value={memberSearch}
              onChange={(e) => setMemberSearch(e.target.value)}
              placeholder="Buscar por nome ou ticker..."
              className="w-full pl-9 pr-4 py-2 bg-card border border-border rounded-lg
                         text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
              autoFocus
            />
          </div>

          <div className="max-h-80 overflow-y-auto space-y-1">
            {searchingProducts ? (
              <div className="flex justify-center py-6">
                <LoadingSpinner size="sm" />
              </div>
            ) : availableProducts.length === 0 ? (
              <p className="text-center text-sm text-muted py-6">
                {memberSearch ? 'Nenhum produto encontrado.' : 'Todos os produtos já são membros.'}
              </p>
            ) : (
              availableProducts.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between gap-3 p-2.5 rounded-lg
                             border border-border hover:bg-gray-50 transition-colors"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-foreground truncate">{p.name}</span>
                      {p.ticker && (
                        <span className="font-mono text-xs text-muted bg-muted/10 px-1.5 py-0.5 rounded">
                          {p.ticker}
                        </span>
                      )}
                      <ProductTypeBadge type={p.product_type} />
                    </div>
                  </div>
                  <button
                    onClick={() => handleAddMember(p.id)}
                    disabled={addingMemberId === p.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                               bg-primary text-white text-xs font-medium
                               hover:bg-primary/90 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
                  >
                    {addingMemberId === p.id ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Plus className="w-3.5 h-3.5" />
                    )}
                    Adicionar
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}
