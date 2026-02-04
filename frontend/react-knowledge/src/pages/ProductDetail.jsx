import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import * as Tabs from '@radix-ui/react-tabs';
import {
  ArrowLeft, FileText, MessageSquare, Edit, Trash2, Plus,
  Upload, ChevronDown, ChevronRight, Clock, Check, AlertTriangle,
  RefreshCw, History, Send, Table2,
} from 'lucide-react';
import { productsAPI, materialsAPI, blocksAPI, scriptsAPI } from '../services/api';
import { Button } from '../components/Button';
import { StatusBadge } from '../components/StatusBadge';
import { InlineEdit } from '../components/InlineEdit';
import { Modal } from '../components/Modal';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { useToast } from '../components/Toast';

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
  const { addToast } = useToast();
  
  const materialStatus = getMaterialStatus(material);

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

  const handlePublish = async () => {
    try {
      await materialsAPI.publish(material.id);
      addToast('Material publicado!', 'success');
      onRefresh();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const blocks = material.blocks || [];
  const pendingBlocks = blocks.filter(b => b.status === 'pending_review');

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
              {material.publication_status !== 'published' && (
                <div className="flex justify-end">
                  <Button size="sm" onClick={handlePublish}>
                    <Send className="w-4 h-4" />
                    Publicar Material
                  </Button>
                </div>
              )}

              {blocks.length === 0 ? (
                <p className="text-center text-muted py-4">
                  Nenhum bloco de conteúdo ainda
                </p>
              ) : (
                <div className="space-y-3">
                  {blocks.map((block) => (
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
          <h1 className="text-2xl font-bold text-foreground">{product.name}</h1>
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
            <InlineEdit
              label="Categoria"
              value={product.category}
              onSave={(v) => handleUpdateProduct('category', v)}
            />
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
          </div>
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
