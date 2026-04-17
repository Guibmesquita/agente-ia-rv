import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import * as Tabs from '@radix-ui/react-tabs';
import {
  ArrowLeft, FileText, MessageSquare, Edit, Trash2, Plus,
  Upload, ChevronDown, ChevronRight, Clock, Check, AlertTriangle,
  RefreshCw, History, Send, Table2, CheckSquare, Square, Pencil, X, Star,
} from 'lucide-react';
import { productsAPI, materialsAPI, blocksAPI, scriptsAPI } from '../services/api';
import { Button } from '../components/Button';
import { StatusBadge } from '../components/StatusBadge';
import { InlineEdit } from '../components/InlineEdit';
import { Modal } from '../components/Modal';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { useToast } from '../components/Toast';
import { MATERIAL_TYPE_OPTIONS, getMaterialTypeLabel } from '../lib/materialTypes';
import { ProductCategories } from '../components/ProductCategories';
import { ProductKeyInfoCard } from '../components/ProductKeyInfoCard';

function convertTableToTopics(content) {
  if (!content) return null;
  
  try {
    let parsed = content;
    if (typeof content === 'string') {
      parsed = JSON.parse(content);
    }
    
    if (parsed && parsed.headers && Array.isArray(parsed.headers) && parsed.rows && Array.isArray(parsed.rows)) {
      const topics = [];
      const headers = parsed.headers;
      
      parsed.rows.forEach((row) => {
        const rowTopics = [];
        row.forEach((cell, cellIdx) => {
          if (cell && cell.toString().trim()) {
            const header = headers[cellIdx] || `Campo ${cellIdx + 1}`;
            rowTopics.push(`${header}: ${cell}`);
          }
        });
        if (rowTopics.length > 0) {
          topics.push(rowTopics.join(' | '));
        }
      });
      
      return topics.join('\n');
    }
  } catch (e) {
  }
  return null;
}

function ContentDisplay({ content, blockType }) {
  const displayContent = useMemo(() => {
    if (blockType === 'tabela' || blockType === 'table') {
      const topics = convertTableToTopics(content);
      return topics || content;
    }
    return content;
  }, [content, blockType]);

  const isTable = blockType === 'tabela' || blockType === 'table';
  const hasTopics = isTable && convertTableToTopics(content);

  if (hasTopics) {
    const lines = displayContent.split('\n');
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 text-xs text-muted mb-2">
          <Table2 className="w-3.5 h-3.5" />
          <span>Dados extraídos</span>
        </div>
        {lines.map((line, i) => (
          <div key={i} className="flex items-start gap-2 text-sm text-muted">
            <span className="text-primary mt-0.5">•</span>
            <span>{line}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <p className="text-sm text-muted whitespace-pre-wrap">
      {content}
    </p>
  );
}


function getMaterialStatus(material) {
  const now = new Date();
  
  if (material.valid_until) {
    const validUntil = new Date(material.valid_until);
    if (validUntil < now) return 'expirado';
    
    const daysUntil = (validUntil - now) / (1000 * 60 * 60 * 24);
    if (daysUntil <= 30) return 'expirando';
  }
  
  return material.publication_status || 'draft';
}

function MaterialSection({ material, productId, onRefresh }) {
  const [expanded, setExpanded] = useState(false);
  const [showVersions, setShowVersions] = useState(null);
  const [versions, setVersions] = useState([]);
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [selectedBlocks, setSelectedBlocks] = useState(new Set());
  const [bulkApproving, setBulkApproving] = useState(false);
  const [editingType, setEditingType] = useState(false);
  const [selectedType, setSelectedType] = useState(material.material_type || '');
  const [savingType, setSavingType] = useState(false);
  const { addToast } = useToast();
  
  const materialStatus = getMaterialStatus(material);

  const blocks = material.blocks || [];
  const pendingBlocks = blocks.filter(b => b.status === 'pending_review');
  
  const sortedBlocks = useMemo(() => {
    return [...blocks].sort((a, b) => {
      const aIsPending = a.status === 'pending_review' ? 0 : 1;
      const bIsPending = b.status === 'pending_review' ? 0 : 1;
      if (aIsPending !== bIsPending) return aIsPending - bIsPending;
      return (a.source_page || 0) - (b.source_page || 0);
    });
  }, [blocks]);

  useEffect(() => {
    setSelectedBlocks(new Set());
  }, [material.id, blocks.length]);

  const toggleBlockSelection = (blockId) => {
    setSelectedBlocks(prev => {
      const newSet = new Set(prev);
      if (newSet.has(blockId)) {
        newSet.delete(blockId);
      } else {
        newSet.add(blockId);
      }
      return newSet;
    });
  };

  const toggleSelectAllPending = () => {
    const pendingIds = pendingBlocks.map(b => b.id);
    if (pendingIds.every(id => selectedBlocks.has(id))) {
      setSelectedBlocks(new Set());
    } else {
      setSelectedBlocks(new Set(pendingIds));
    }
  };

  const handleBulkApprove = async () => {
    if (selectedBlocks.size === 0) return;
    
    setBulkApproving(true);
    try {
      const blockIds = Array.from(selectedBlocks);
      const result = await blocksAPI.bulkApprove(blockIds);
      addToast(`${result.approved_count} blocos aprovados!`, 'success');
      setSelectedBlocks(new Set());
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setBulkApproving(false);
  };

  const loadVersions = async (blockId) => {
    setLoadingVersions(true);
    try {
      const data = await blocksAPI.getVersions(productId, material.id, blockId);
      setVersions(data.versions || []);
      setShowVersions(blockId);
    } catch (err) {
      addToast('Erro ao carregar versões', 'error');
    }
    setLoadingVersions(false);
  };

  const handleRestoreVersion = async (blockId, version) => {
    try {
      await blocksAPI.restoreVersion(productId, material.id, blockId, version);
      addToast('Versão restaurada com sucesso!', 'success');
      setShowVersions(null);
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const handleApproveBlock = async (blockId) => {
    try {
      await blocksAPI.approve(blockId);
      addToast('Bloco aprovado!', 'success');
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const handleUpdateBlock = async (blockId, content) => {
    try {
      await blocksAPI.update(productId, material.id, blockId, { content });
      addToast('Bloco atualizado!', 'success');
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
      throw err;
    }
  };

  const handleReindex = async () => {
    try {
      await materialsAPI.reindex(material.id);
      addToast('Material reindexado com sucesso!', 'success');
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const handleSaveType = async (e) => {
    e.stopPropagation();
    if (selectedType === material.material_type) {
      setEditingType(false);
      return;
    }
    setSavingType(true);
    try {
      await materialsAPI.updateType(material.id, selectedType);
      addToast('Tipo de material atualizado!', 'success');
      setEditingType(false);
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
      setSelectedType(material.material_type || '');
    }
    setSavingType(false);
  };

  const handleCancelTypeEdit = (e) => {
    e.stopPropagation();
    setSelectedType(material.material_type || '');
    setEditingType(false);
  };

  return (
    <div className="border border-border rounded-card overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 bg-card hover:bg-background transition-colors"
      >
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <FileText className="w-5 h-5 text-primary" />
          <div className="text-left">
            <p className="font-medium text-foreground">{material.name || material.material_type}</p>
            <p className="text-sm text-muted">
              {blocks.length} bloco{blocks.length !== 1 ? 's' : ''}
              {pendingBlocks.length > 0 && (
                <span className="text-warning ml-2">
                  ({pendingBlocks.length} pendente{pendingBlocks.length !== 1 ? 's' : ''})
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {editingType ? (
            <div
              className="flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
                className="text-xs px-2 py-1 border border-border rounded bg-background text-foreground"
                disabled={savingType}
                autoFocus
              >
                {MATERIAL_TYPE_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <button
                onClick={handleSaveType}
                disabled={savingType}
                className="p-1 rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
                title="Salvar"
              >
                <Check className="w-3 h-3" />
              </button>
              <button
                onClick={handleCancelTypeEdit}
                className="p-1 rounded hover:bg-border text-muted hover:text-foreground"
                title="Cancelar"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ) : (
            <div
              className="flex items-center gap-1 group"
              onClick={(e) => e.stopPropagation()}
            >
              <span className="text-xs px-2 py-0.5 bg-muted/10 text-muted rounded font-medium">
                {getMaterialTypeLabel(material.material_type)}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); setSelectedType(material.material_type || ''); setEditingType(true); }}
                className="p-1 rounded text-muted hover:text-foreground hover:bg-border opacity-0 group-hover:opacity-100 transition-opacity"
                title="Editar tipo"
              >
                <Pencil className="w-3 h-3" />
              </button>
            </div>
          )}
          <StatusBadge status={materialStatus} />
          {material.valid_until && (
            <span className="text-xs text-muted">
              até {new Date(material.valid_until).toLocaleDateString('pt-BR')}
            </span>
          )}
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-border"
          >
            <div className="p-4 space-y-4">
              <div className="flex justify-end gap-2">
                <Button size="sm" onClick={handleReindex}>
                  <Send className="w-4 h-4" />
                  Reindexar
                </Button>
              </div>

              {sortedBlocks.length === 0 ? (
                <p className="text-center text-muted py-4">
                  Nenhum bloco de conteúdo ainda
                </p>
              ) : (
                <div className="space-y-3">
                  {pendingBlocks.length > 0 && (
                    <div className="flex items-center justify-between bg-warning/10 rounded-lg p-3 border border-warning/20">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={toggleSelectAllPending}
                          className="flex items-center gap-2 text-sm font-medium text-warning hover:text-foreground transition-colors"
                        >
                          {pendingBlocks.every(b => selectedBlocks.has(b.id)) ? (
                            <CheckSquare className="w-5 h-5 text-primary" />
                          ) : (
                            <Square className="w-5 h-5" />
                          )}
                          {pendingBlocks.every(b => selectedBlocks.has(b.id)) ? 'Desmarcar Todos' : 'Selecionar Pendentes'}
                        </button>
                        <span className="text-sm text-muted">
                          {selectedBlocks.size > 0 ? (
                            <span className="text-primary font-medium">{selectedBlocks.size} selecionado{selectedBlocks.size !== 1 ? 's' : ''}</span>
                          ) : (
                            <>{pendingBlocks.length} pendente{pendingBlocks.length !== 1 ? 's' : ''}</>
                          )}
                        </span>
                      </div>
                      {selectedBlocks.size > 0 && (
                        <Button
                          size="sm"
                          variant="success"
                          onClick={handleBulkApprove}
                          disabled={bulkApproving}
                        >
                          <Check className="w-3 h-3" />
                          Aprovar {selectedBlocks.size}
                        </Button>
                      )}
                    </div>
                  )}
                  {sortedBlocks.map((block) => (
                    <div
                      key={block.id}
                      className={`p-4 rounded-card border ${
                        block.status === 'pending_review'
                          ? 'border-warning bg-warning/5'
                          : 'border-border bg-background'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {block.status === 'pending_review' && (
                            <button
                              onClick={() => toggleBlockSelection(block.id)}
                              className="flex-shrink-0"
                            >
                              {selectedBlocks.has(block.id) ? (
                                <CheckSquare className="w-5 h-5 text-primary" />
                              ) : (
                                <Square className="w-5 h-5 text-muted hover:text-foreground transition-colors" />
                              )}
                            </button>
                          )}
                          <span className="text-xs px-2 py-0.5 bg-muted/10 text-muted rounded font-medium">
                            {block.block_type}
                          </span>
                          {block.title && (
                            <span className="font-medium text-foreground">{block.title}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          {block.status === 'pending_review' && (
                            <Button size="sm" variant="success" onClick={() => handleApproveBlock(block.id)}>
                              <Check className="w-3 h-3" />
                              Aprovar
                            </Button>
                          )}
                          <button
                            onClick={() => loadVersions(block.id)}
                            className="p-1.5 rounded hover:bg-border text-muted hover:text-foreground"
                            title="Ver histórico"
                          >
                            <History className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                      
                      <ContentDisplay 
                        content={block.content} 
                        blockType={block.block_type} 
                      />

                      {block.status === 'pending_review' && block.review_reason && (
                        <div className="mt-2 flex items-center gap-2 text-sm text-warning">
                          <AlertTriangle className="w-4 h-4" />
                          {block.review_reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Modal
        open={showVersions !== null}
        onClose={() => setShowVersions(null)}
        title="Histórico de Versões"
      >
        {loadingVersions ? (
          <LoadingSpinner />
        ) : versions.length === 0 ? (
          <p className="text-muted text-center py-4">Nenhuma versão anterior</p>
        ) : (
          <div className="space-y-3">
            {versions.map((v) => (
              <div key={v.version} className="p-3 border border-border rounded-card">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium">Versão {v.version}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">
                      {new Date(v.created_at).toLocaleString('pt-BR')}
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleRestoreVersion(showVersions, v.version)}
                    >
                      Restaurar
                    </Button>
                  </div>
                </div>
                <p className="text-sm text-muted line-clamp-3">{v.content}</p>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}

export function ProductDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { addToast } = useToast();

  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [newScript, setNewScript] = useState({ title: '', content: '' });
  const [showScriptModal, setShowScriptModal] = useState(false);

  const loadProduct = async () => {
    try {
      setLoading(true);
      const data = await productsAPI.get(id);
      setProduct(data);
    } catch (err) {
      addToast('Erro ao carregar produto', 'error');
      navigate('/');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProduct();
  }, [id]);

  const handleUpdateProduct = async (field, value) => {
    try {
      await productsAPI.update(id, { [field]: value });
      setProduct((p) => ({ ...p, [field]: value }));
      addToast('Produto atualizado!', 'success');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
      throw err;
    }
  };

  const handleDeleteProduct = async () => {
    try {
      await productsAPI.delete(id);
      addToast('Produto excluído!', 'success');
      navigate('/');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const handleCreateScript = async (e) => {
    e.preventDefault();
    try {
      await scriptsAPI.create(id, newScript);
      addToast('Script criado!', 'success');
      setShowScriptModal(false);
      setNewScript({ title: '', content: '' });
      loadProduct();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!product) return null;

  const materials = product.materials || [];
  const scripts = product.scripts || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-btn hover:bg-border text-muted hover:text-foreground transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-foreground">{product.name}</h1>
            <button
              type="button"
              onClick={async () => {
                try {
                  const result = await productsAPI.toggleCommittee(product.id);
                  setProduct((p) => ({ ...p, is_committee: Boolean(result?.is_committee) }));
                  addToast(
                    result?.is_committee
                      ? `${product.name} adicionado ao Comitê SVN`
                      : `${product.name} removido do Comitê SVN`,
                    'success'
                  );
                } catch (err) {
                  addToast(`Erro ao atualizar Comitê: ${err.message}`, 'error');
                }
              }}
              title={product.is_committee
                ? 'Produto do Comitê SVN — clique para remover'
                : 'Marcar como produto do Comitê SVN'}
              aria-pressed={Boolean(product.is_committee)}
              aria-label={product.is_committee ? 'Remover do Comitê' : 'Adicionar ao Comitê'}
              className="p-1 rounded-md hover:bg-gray-100 transition-colors"
            >
              <Star
                className={`w-6 h-6 transition-colors ${
                  product.is_committee
                    ? 'text-amber-400 fill-amber-400'
                    : 'text-gray-300 hover:text-amber-400'
                }`}
              />
            </button>
          </div>
          <p className="text-muted">
            {product.ticker && <span className="text-primary font-medium">{product.ticker}</span>}
            {product.ticker && product.category && ' • '}
            {product.category}
          </p>
        </div>
        <Button variant="secondary" onClick={loadProduct}>
          <RefreshCw className="w-4 h-4" />
          Atualizar
        </Button>
        <Button variant="danger" onClick={() => setShowDeleteModal(true)}>
          <Trash2 className="w-4 h-4" />
          Excluir
        </Button>
      </div>

      <Tabs.Root defaultValue="materials" className="space-y-4">
        <Tabs.List className="flex gap-1 border-b border-border">
          <Tabs.Trigger
            value="materials"
            className="px-4 py-2 text-sm font-medium text-muted hover:text-foreground
                       data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary"
          >
            <FileText className="w-4 h-4 inline mr-2" />
            Materiais ({materials.length})
          </Tabs.Trigger>
          <Tabs.Trigger
            value="scripts"
            className="px-4 py-2 text-sm font-medium text-muted hover:text-foreground
                       data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary"
          >
            <MessageSquare className="w-4 h-4 inline mr-2" />
            Scripts WhatsApp ({scripts.length})
          </Tabs.Trigger>
          <Tabs.Trigger
            value="info"
            className="px-4 py-2 text-sm font-medium text-muted hover:text-foreground
                       data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary"
          >
            <Edit className="w-4 h-4 inline mr-2" />
            Informações
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="materials" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => navigate(`/upload?product=${id}`)}>
              <Upload className="w-4 h-4" />
              Upload Inteligente
            </Button>
          </div>

          {materials.length === 0 ? (
            <div className="text-center py-12 bg-card rounded-card border border-border">
              <FileText className="w-12 h-12 text-muted mx-auto mb-4" />
              <p className="text-foreground font-medium mb-2">Nenhum material ainda</p>
              <p className="text-muted text-sm mb-4">
                Use o Upload Inteligente para adicionar documentos
              </p>
              <Button onClick={() => navigate(`/upload?product=${id}`)}>
                <Upload className="w-4 h-4" />
                Fazer Upload
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {materials.map((material) => (
                <MaterialSection
                  key={material.id}
                  material={material}
                  productId={id}
                  onRefresh={loadProduct}
                />
              ))}
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content value="scripts" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setShowScriptModal(true)}>
              <Plus className="w-4 h-4" />
              Novo Script
            </Button>
          </div>

          {scripts.length === 0 ? (
            <div className="text-center py-12 bg-card rounded-card border border-border">
              <MessageSquare className="w-12 h-12 text-muted mx-auto mb-4" />
              <p className="text-foreground font-medium mb-2">Nenhum script de WhatsApp</p>
              <p className="text-muted text-sm">
                Crie scripts prontos para compartilhar com clientes
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {scripts.map((script) => (
                <div key={script.id} className="p-4 bg-card rounded-card border border-border">
                  <h3 className="font-medium text-foreground mb-2">{script.title}</h3>
                  <p className="text-sm text-muted whitespace-pre-wrap">{script.content}</p>
                </div>
              ))}
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content value="info" className="space-y-4">
          <div className="bg-card rounded-card border border-border p-6 space-y-4">
            <InlineEdit
              label="Nome do Produto"
              value={product.name}
              onSave={(v) => handleUpdateProduct('name', v)}
            />
            <InlineEdit
              label="Ticker"
              value={product.ticker}
              onSave={(v) => handleUpdateProduct('ticker', v)}
              placeholder="Ex: XPTO11"
            />
            <div>
              <ProductCategories
                label="Categorias do Produto"
                value={product.categories || (product.category ? [product.category] : [])}
                onChange={(cats) => handleUpdateProduct('categories', cats)}
              />
            </div>
            <InlineEdit
              label="Gestor"
              value={product.manager}
              onSave={(v) => handleUpdateProduct('manager', v)}
            />
            <InlineEdit
              label="Descrição"
              value={product.description}
              onSave={(v) => handleUpdateProduct('description', v)}
              multiline
            />
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted uppercase tracking-wide">Tipo do Produto</label>
              <select
                value={product.product_type || ''}
                onChange={(e) => handleUpdateProduct('product_type', e.target.value || null)}
                className="w-full px-3 py-2 text-sm bg-background border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary text-foreground"
              >
                <option value="">— Não definido —</option>
                <option value="fii">FII (Fundo de Investimento Imobiliário)</option>
                <option value="acao">Ação</option>
                <option value="etf">ETF</option>
                <option value="fundo">Fundo de Investimento</option>
                <option value="debenture">Debênture</option>
                <option value="estruturada">Estrutura / Derivativo</option>
                <option value="outro">Outro</option>
              </select>
            </div>
          </div>

          <ProductKeyInfoCard product={product} onUpdated={loadProduct} />
        </Tabs.Content>
      </Tabs.Root>

      <Modal
        open={showDeleteModal}
        onClose={() => setShowDeleteModal(false)}
        title="Confirmar Exclusão"
        size="sm"
      >
        <p className="text-muted mb-6">
          Tem certeza que deseja excluir o produto <strong>{product.name}</strong>?
          Esta ação não pode ser desfeita.
        </p>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => setShowDeleteModal(false)} className="flex-1">
            Cancelar
          </Button>
          <Button variant="danger" onClick={handleDeleteProduct} className="flex-1">
            Excluir
          </Button>
        </div>
      </Modal>

      <Modal
        open={showScriptModal}
        onClose={() => setShowScriptModal(false)}
        title="Novo Script WhatsApp"
      >
        <form onSubmit={handleCreateScript} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Título</label>
            <input
              type="text"
              value={newScript.title}
              onChange={(e) => setNewScript({ ...newScript, title: e.target.value })}
              placeholder="Ex: Apresentação do Produto"
              className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Conteúdo</label>
            <textarea
              value={newScript.content}
              onChange={(e) => setNewScript({ ...newScript, content: e.target.value })}
              rows={6}
              placeholder="Olá! Gostaria de apresentar..."
              className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground resize-none"
            />
          </div>
          <div className="flex gap-3">
            <Button type="button" variant="secondary" onClick={() => setShowScriptModal(false)} className="flex-1">
              Cancelar
            </Button>
            <Button type="submit" className="flex-1">
              Criar Script
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
