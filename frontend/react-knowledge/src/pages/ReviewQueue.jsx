import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ClipboardCheck, Check, X, Edit, AlertTriangle, RefreshCw, Table2, Search, FileText, Maximize2, CheckSquare, Square, Package, Link, Plus, Upload } from 'lucide-react';
import { reviewAPI, blocksAPI } from '../services/api';
import { Button } from '../components/Button';
import { Modal } from '../components/Modal';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { useToast } from '../components/Toast';
import { ProductAutocomplete } from '../components/ProductAutocomplete';

const API_BASE = '/api/products';

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
      
      parsed.rows.forEach((row, rowIdx) => {
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

function TopicsPreview({ content, maxLines = 4 }) {
  const lines = content.split('\n').slice(0, maxLines);
  const hasMore = content.split('\n').length > maxLines;
  
  return (
    <div className="space-y-1">
      {lines.map((line, i) => (
        <div key={i} className="flex items-start gap-2 text-sm text-muted">
          <span className="text-primary mt-0.5">•</span>
          <span className="line-clamp-1">{line}</span>
        </div>
      ))}
      {hasMore && (
        <p className="text-xs text-muted/70 italic pl-4">
          + {content.split('\n').length - maxLines} itens adicionais...
        </p>
      )}
    </div>
  );
}

function ContentPreview({ content, blockType }) {
  const topicsContent = useMemo(() => {
    if (blockType === 'tabela' || blockType === 'table') {
      return convertTableToTopics(content);
    }
    return null;
  }, [content, blockType]);

  if (topicsContent) {
    return (
      <div className="mb-3">
        <div className="flex items-center gap-1.5 text-xs text-muted mb-2">
          <Table2 className="w-3.5 h-3.5" />
          <span>Dados extraídos</span>
        </div>
        <TopicsPreview content={topicsContent} maxLines={4} />
      </div>
    );
  }

  return (
    <p className="text-sm text-muted mb-3 whitespace-pre-wrap line-clamp-4">
      {content}
    </p>
  );
}

function PDFViewer({ materialId, page = 1 }) {
  const { addToast } = useToast();
  const containerRef = useRef(null);
  const fileInputRef = useRef(null);
  const [showMagnifier, setShowMagnifier] = useState(false);
  const [magnifierPos, setMagnifierPos] = useState({ x: 0, y: 0 });
  const [error, setError] = useState(false);
  // Espelha o tratamento usado em Documentos/Upload: detectar
  // FILE_MISSING (PDF sumiu do disco do Railway) e oferecer reupload
  // imediato em vez de mostrar 404 cru no iframe.
  const [pdfStatus, setPdfStatus] = useState('loading'); // 'loading' | 'ok' | 'missing' | 'error'
  const [missingMessage, setMissingMessage] = useState('');
  const [reuploading, setReuploading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const magnifierSize = 150;
  const zoomLevel = 2.5;

  useEffect(() => {
    let cancelled = false;
    if (!materialId) {
      setPdfStatus('loading');
      return () => { cancelled = true; };
    }

    setPdfStatus('loading');
    setError(false);

    (async () => {
      const url = `${API_BASE}/materials/${materialId}/pdf`;
      try {
        // HEAD evita baixar o PDF inteiro só para checar disponibilidade.
        const probe = await fetch(url, { method: 'HEAD' });
        if (cancelled) return;
        if (probe.ok) {
          setPdfStatus('ok');
          return;
        }
        if (probe.status === 404) {
          // HEAD não traz o JSON; faz GET pequeno só para inspecionar
          // o `code` (FILE_MISSING vs MATERIAL_NOT_FOUND).
          let body = {};
          try {
            const detailResp = await fetch(url, {
              method: 'GET',
              headers: { 'Accept': 'application/json' },
            });
            body = await detailResp.json();
          } catch (_) {
            body = {};
          }
          if (cancelled) return;
          const detail = body && body.detail;
          const code = detail && typeof detail === 'object' ? detail.code : null;
          if (code === 'FILE_MISSING') {
            setMissingMessage(
              (detail && detail.message) ||
              'Arquivo binário não disponível para este material.'
            );
            setPdfStatus('missing');
            return;
          }
        }
        setPdfStatus('error');
      } catch (_) {
        if (cancelled) return;
        setPdfStatus('error');
      }
    })();

    return () => { cancelled = true; };
  }, [materialId, reloadKey]);

  const pdfUrl = materialId
    ? `${API_BASE}/materials/${materialId}/pdf?v=${reloadKey}#page=${page}`
    : null;

  const handleMouseMove = useCallback((e) => {
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    setMagnifierPos({ x, y });
  }, []);

  const triggerReupload = () => {
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const handleReuploadFile = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!file || !materialId) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      addToast('Apenas arquivos PDF são aceitos', 'error');
      return;
    }
    setReuploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(`${API_BASE}/admin/reupload-pdf/${materialId}`, {
        method: 'POST',
        body: fd,
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` },
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const errDetail = errBody && errBody.detail;
        const txt = (errDetail && typeof errDetail === 'object' ? errDetail.message : errDetail) || `HTTP ${res.status}`;
        addToast(`Falha ao enviar PDF: ${txt}`, 'error');
        return;
      }
      addToast('PDF reenviado com sucesso', 'success');
      // Re-dispara o probe e o iframe para mostrar o PDF recém-enviado.
      setReloadKey((k) => k + 1);
    } catch (_) {
      addToast('Erro de rede ao reenviar PDF', 'error');
    } finally {
      setReuploading(false);
    }
  };

  const openInNewTab = () => {
    if (!materialId) return;
    if (pdfStatus === 'missing') {
      triggerReupload();
      return;
    }
    window.open(`${API_BASE}/materials/${materialId}/pdf?v=${reloadKey}`, '_blank', 'noopener');
  };

  if (!materialId) {
    return (
      <div className="flex items-center justify-center h-full bg-muted/5 rounded-lg border border-border">
        <div className="text-center text-muted">
          <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
          <p className="text-sm">PDF não disponível</p>
        </div>
      </div>
    );
  }

  const showMagnifierUI = pdfStatus === 'ok';

  return (
    <div className="flex flex-col h-full">
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf,.pdf"
        style={{ display: 'none' }}
        onChange={handleReuploadFile}
      />
      <div className="flex items-center justify-between px-3 py-2 bg-muted/10 border-b border-border rounded-t-lg">
        <span className="text-xs font-medium text-muted">Documento Original</span>
        <div className="flex items-center gap-2">
          {showMagnifierUI && (
            <div className="flex items-center gap-1 text-xs text-muted">
              <Search className="w-3.5 h-3.5" />
              <span>Lupa ativa</span>
            </div>
          )}
          <button
            type="button"
            onClick={openInNewTab}
            className="p-1 hover:bg-muted/20 rounded transition-colors"
            title={pdfStatus === 'missing' ? 'Reenviar PDF' : 'Abrir em nova aba'}
          >
            <Maximize2 className="w-4 h-4 text-muted" />
          </button>
        </div>
      </div>
      <div
        ref={containerRef}
        className={`flex-1 overflow-auto bg-muted/5 rounded-b-lg relative ${showMagnifierUI ? 'cursor-crosshair' : ''}`}
        onMouseEnter={() => showMagnifierUI && setShowMagnifier(true)}
        onMouseLeave={() => setShowMagnifier(false)}
        onMouseMove={showMagnifierUI ? handleMouseMove : undefined}
      >
        {pdfStatus === 'loading' && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-muted">
              <RefreshCw className="w-6 h-6 mx-auto mb-2 animate-spin opacity-60" />
              <p className="text-sm">Carregando PDF...</p>
            </div>
          </div>
        )}
        {pdfStatus === 'missing' && (
          <div className="flex items-center justify-center h-full p-6">
            <div className="text-center text-muted max-w-sm">
              <AlertTriangle className="w-12 h-12 mx-auto mb-3 text-warning" />
              <p className="text-sm font-medium text-foreground mb-2">PDF não disponível</p>
              <p className="text-xs text-muted mb-4">{missingMessage}</p>
              <Button
                size="sm"
                variant="primary"
                onClick={triggerReupload}
                loading={reuploading}
              >
                <Upload className="w-4 h-4" />
                Reenviar PDF
              </Button>
            </div>
          </div>
        )}
        {pdfStatus === 'error' && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-muted">
              <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
              <p className="text-sm">Não foi possível carregar o PDF</p>
            </div>
          </div>
        )}
        {pdfStatus === 'ok' && !error && (
          <>
            <iframe
              src={pdfUrl}
              className="w-full h-full border-0 pointer-events-none"
              onError={() => setError(true)}
              title="PDF Preview"
            />
            {showMagnifier && (
              <div
                className="absolute pointer-events-none border-2 border-primary rounded-full shadow-lg overflow-hidden bg-white"
                style={{
                  width: magnifierSize,
                  height: magnifierSize,
                  left: magnifierPos.x - magnifierSize / 2,
                  top: magnifierPos.y - magnifierSize / 2,
                  zIndex: 10
                }}
              >
                <iframe
                  src={pdfUrl}
                  className="border-0 pointer-events-none"
                  style={{
                    width: containerRef.current?.clientWidth || 400,
                    height: containerRef.current?.clientHeight || 600,
                    transform: `scale(${zoomLevel})`,
                    transformOrigin: `${magnifierPos.x}px ${magnifierPos.y}px`,
                    position: 'absolute',
                    left: -(magnifierPos.x * zoomLevel - magnifierSize / 2),
                    top: -(magnifierPos.y * zoomLevel - magnifierSize / 2)
                  }}
                  title="PDF Magnifier"
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ConfidenceBadge({ confidence }) {
  const value = parseFloat(confidence) || 0;
  const pct = Math.round(value * 100);
  let colorClass = 'bg-danger/10 text-danger';
  if (value >= 0.8) colorClass = 'bg-success/10 text-success';
  else if (value >= 0.5) colorClass = 'bg-warning/10 text-warning';

  return (
    <span className={`text-xs px-2 py-0.5 rounded font-medium ${colorClass}`}>
      {pct}%
    </span>
  );
}

function ProductMatchCard({ item, onResolved, addToast }) {
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState({ name: '', ticker: '', manager: '' });
  const [processing, setProcessing] = useState(false);

  const handleLink = async (productId) => {
    setProcessing(true);
    try {
      await reviewAPI.resolveProduct({ material_id: item.material_id, action: 'link', product_id: productId });
      addToast('Produto vinculado com sucesso!', 'success');
      onResolved(item.material_id);
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  const handleLinkFromAutocomplete = async (product) => {
    if (!product) return;
    setSelectedProduct(product);
    await handleLink(product.id);
  };

  const handleCreate = async () => {
    if (!createForm.name.trim()) {
      addToast('Nome do produto é obrigatório', 'warning');
      return;
    }
    setProcessing(true);
    try {
      await reviewAPI.resolveProduct({
        material_id: item.material_id,
        action: 'create',
        product_name: createForm.name,
        product_ticker: createForm.ticker,
        product_manager: createForm.manager,
      });
      addToast('Produto criado e vinculado!', 'success');
      onResolved(item.material_id);
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -100 }}
      className="bg-card rounded-card border border-border p-5 shadow-card"
    >
      <div className="flex flex-col lg:flex-row gap-5">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="w-5 h-5 text-primary flex-shrink-0" />
            <h3 className="font-medium text-foreground truncate">
              {item.source_filename || 'Documento sem nome'}
            </h3>
          </div>

          <div className="space-y-1.5 mb-3">
            {item.extracted_fund_name && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted">Fundo:</span>
                <span className="text-foreground font-medium">{item.extracted_fund_name}</span>
              </div>
            )}
            {item.extracted_ticker && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted">Ticker:</span>
                <span className="text-foreground font-medium">{item.extracted_ticker}</span>
              </div>
            )}
            {item.extracted_gestora && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted">Gestora:</span>
                <span className="text-foreground font-medium">{item.extracted_gestora}</span>
              </div>
            )}
          </div>

          {item.extracted_confidence != null && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted">Confiança:</span>
              <ConfidenceBadge confidence={item.extracted_confidence} />
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          {item.candidates && item.candidates.length > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-muted mb-2">Candidatos encontrados:</p>
              <div className="space-y-2">
                {item.candidates.map((candidate) => (
                  <div
                    key={candidate.product_id}
                    className="flex items-center justify-between gap-3 p-3 bg-muted/5 rounded-lg border border-border"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{candidate.product_name}</p>
                      {candidate.ticker && (
                        <p className="text-xs text-muted">{candidate.ticker}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded font-medium">
                        {Math.round((candidate.similarity || candidate.score || 0) * 100)}%
                      </span>
                      <Button
                        size="sm"
                        variant="success"
                        onClick={() => handleLink(candidate.product_id)}
                        disabled={processing}
                      >
                        <Link className="w-3.5 h-3.5" />
                        Vincular
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mb-3">
            <p className="text-xs font-medium text-muted mb-2">Buscar produto existente:</p>
            <ProductAutocomplete
              value={selectedProduct}
              onChange={handleLinkFromAutocomplete}
              placeholder="Buscar produto para vincular..."
              includePortfolios={false}
            />
          </div>

          {!showCreateForm ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setShowCreateForm(true)}
              disabled={processing}
            >
              <Plus className="w-4 h-4" />
              Criar Novo Produto
            </Button>
          ) : (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className="space-y-3 p-4 bg-muted/5 rounded-lg border border-border"
            >
              <p className="text-xs font-medium text-muted">Criar novo produto:</p>
              <input
                type="text"
                placeholder="Nome do produto *"
                value={createForm.name}
                onChange={(e) => setCreateForm(prev => ({ ...prev, name: e.target.value }))}
                className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Ticker"
                  value={createForm.ticker}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, ticker: e.target.value }))}
                  className="flex-1 px-3 py-2 bg-card border border-border rounded-input text-foreground text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
                <input
                  type="text"
                  placeholder="Gestora"
                  value={createForm.manager}
                  onChange={(e) => setCreateForm(prev => ({ ...prev, manager: e.target.value }))}
                  className="flex-1 px-3 py-2 bg-card border border-border rounded-input text-foreground text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => { setShowCreateForm(false); setCreateForm({ name: '', ticker: '', manager: '' }); }}
                >
                  Cancelar
                </Button>
                <Button
                  size="sm"
                  variant="success"
                  onClick={handleCreate}
                  disabled={processing}
                >
                  <Plus className="w-4 h-4" />
                  Criar e Vincular
                </Button>
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export function ReviewQueue() {
  const { addToast } = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedItem, setSelectedItem] = useState(null);
  const [editContent, setEditContent] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [showEditModal, setShowEditModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [selectedBlocks, setSelectedBlocks] = useState(new Set());

  const [activeTab, setActiveTab] = useState('content');
  const [productItems, setProductItems] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [pendingProductsCount, setPendingProductsCount] = useState(0);

  const selectableItems = useMemo(() => 
    items.filter(i => i.block_id), 
    [items]
  );

  const toggleBlockSelection = (blockId) => {
    if (!blockId) return;
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

  const toggleSelectAll = () => {
    const allBlockIds = selectableItems.map(i => i.block_id);
    if (selectedBlocks.size === allBlockIds.length && allBlockIds.length > 0) {
      setSelectedBlocks(new Set());
    } else {
      setSelectedBlocks(new Set(allBlockIds));
    }
  };

  const handleBulkApprove = async () => {
    if (selectedBlocks.size === 0) {
      addToast('Selecione ao menos um bloco', 'warning');
      return;
    }

    setProcessing(true);
    try {
      const blockIds = Array.from(selectedBlocks);
      const result = await blocksAPI.bulkApprove(blockIds);
      addToast(`${result.approved_count} blocos aprovados!`, 'success');
      setItems(prev => prev.filter(i => !selectedBlocks.has(i.block_id)));
      setSelectedBlocks(new Set());
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  const loadItems = async () => {
    try {
      setLoading(true);
      const data = await reviewAPI.listPending();
      setItems(data.pending_items || data.items || data || []);
      if (data.pending_products_count != null) {
        setPendingProductsCount(data.pending_products_count);
      }
      setSelectedBlocks(new Set());
    } catch (err) {
      addToast('Erro ao carregar itens pendentes', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadProductItems = async () => {
    try {
      setLoadingProducts(true);
      const data = await reviewAPI.listPendingProducts();
      setProductItems(data.items || data.pending_items || data || []);
    } catch (err) {
      addToast('Erro ao carregar produtos pendentes', 'error');
    } finally {
      setLoadingProducts(false);
    }
  };

  useEffect(() => {
    loadItems();
    loadProductItems();
  }, []);

  const handleProductResolved = (materialId) => {
    setProductItems(prev => prev.filter(i => i.material_id !== materialId));
    setPendingProductsCount(prev => Math.max(0, prev - 1));
  };

  const handleApprove = async (item) => {
    setProcessing(true);
    try {
      await reviewAPI.approve(item.id);
      addToast('Item aprovado com sucesso!', 'success');
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  const handleEdit = async () => {
    if (!editContent.trim()) {
      addToast('Conteúdo não pode estar vazio', 'warning');
      return;
    }

    setProcessing(true);
    try {
      await reviewAPI.edit(selectedItem.id, { content: editContent });
      addToast('Item editado e aprovado!', 'success');
      setItems((prev) => prev.filter((i) => i.id !== selectedItem.id));
      setShowEditModal(false);
      setSelectedItem(null);
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      addToast('Motivo da rejeição é obrigatório', 'warning');
      return;
    }

    setProcessing(true);
    try {
      await reviewAPI.reject(selectedItem.id, { reason: rejectReason });
      addToast('Item rejeitado', 'success');
      setItems((prev) => prev.filter((i) => i.id !== selectedItem.id));
      setShowRejectModal(false);
      setSelectedItem(null);
      setRejectReason('');
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setProcessing(false);
  };

  const openEditModal = (item) => {
    setSelectedItem(item);
    const content = item.extracted_content || item.content || '';
    
    if (item.block_type === 'tabela' || item.block_type === 'table') {
      const topicsContent = convertTableToTopics(content);
      setEditContent(topicsContent || content);
    } else {
      setEditContent(content);
    }
    
    setShowEditModal(true);
  };

  const openRejectModal = (item) => {
    setSelectedItem(item);
    setShowRejectModal(true);
  };

  const handleRefresh = () => {
    loadItems();
    loadProductItems();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Fila de Revisão</h1>
          <p className="text-muted">
            Itens que requerem revisão manual antes de serem publicados
          </p>
        </div>
        <Button variant="secondary" onClick={handleRefresh} disabled={loading || loadingProducts}>
          <RefreshCw className={`w-4 h-4 ${(loading || loadingProducts) ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

      <div className="flex items-center gap-1 p-1 bg-muted/10 rounded-full w-fit">
        <button
          onClick={() => setActiveTab('content')}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all ${
            activeTab === 'content'
              ? 'bg-primary text-white shadow-sm'
              : 'text-muted hover:text-foreground'
          }`}
        >
          <ClipboardCheck className="w-4 h-4" />
          Conteúdo
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
            activeTab === 'content'
              ? 'bg-white/20 text-white'
              : 'bg-muted/20 text-muted'
          }`}>
            {items.length}
          </span>
        </button>
        <button
          onClick={() => setActiveTab('products')}
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all ${
            activeTab === 'products'
              ? 'bg-primary text-white shadow-sm'
              : 'text-muted hover:text-foreground'
          }`}
        >
          <Package className="w-4 h-4" />
          Produtos
          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
            activeTab === 'products'
              ? 'bg-white/20 text-white'
              : 'bg-muted/20 text-muted'
          }`}>
            {productItems.length || pendingProductsCount}
          </span>
        </button>
      </div>

      {activeTab === 'content' && (
        <>
          {loading ? (
            <div className="py-20">
              <LoadingSpinner size="lg" />
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={ClipboardCheck}
              title="Nenhum item pendente"
              description="Todos os itens foram revisados. Volte mais tarde para verificar novos itens."
            />
          ) : (
            <>
              <div className="flex items-center justify-between bg-card rounded-card border border-border p-4">
                <div className="flex items-center gap-4">
                  {selectableItems.length > 0 && (
                    <button
                      onClick={toggleSelectAll}
                      className="flex items-center gap-2 text-sm font-medium text-muted hover:text-foreground transition-colors"
                    >
                      {selectedBlocks.size === selectableItems.length && selectableItems.length > 0 ? (
                        <CheckSquare className="w-5 h-5 text-primary" />
                      ) : (
                        <Square className="w-5 h-5" />
                      )}
                      {selectedBlocks.size === selectableItems.length && selectableItems.length > 0 ? 'Desmarcar Todos' : 'Selecionar Todos'}
                    </button>
                  )}
                  <span className="text-sm text-muted">
                    {selectedBlocks.size > 0 ? (
                      <span className="text-primary font-medium">{selectedBlocks.size} selecionado{selectedBlocks.size !== 1 ? 's' : ''}</span>
                    ) : (
                      <>{items.length} item{items.length !== 1 ? 's' : ''} aguardando revisão</>
                    )}
                  </span>
                </div>
                {selectedBlocks.size > 0 && (
                  <Button
                    variant="success"
                    onClick={handleBulkApprove}
                    disabled={processing}
                  >
                    <Check className="w-4 h-4" />
                    Aprovar {selectedBlocks.size} Selecionado{selectedBlocks.size !== 1 ? 's' : ''}
                  </Button>
                )}
              </div>

              <div className="space-y-4">
                <AnimatePresence>
                  {items.map((item) => (
                    <motion.div
                      key={item.id}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, x: -100 }}
                      className="bg-card rounded-card border border-warning/30 p-5 shadow-card"
                    >
                      <div className="flex items-start gap-4">
                        {item.block_id ? (
                          <button
                            onClick={() => toggleBlockSelection(item.block_id)}
                            className="mt-1 flex-shrink-0"
                          >
                            {selectedBlocks.has(item.block_id) ? (
                              <CheckSquare className="w-5 h-5 text-primary" />
                            ) : (
                              <Square className="w-5 h-5 text-muted hover:text-foreground transition-colors" />
                            )}
                          </button>
                        ) : (
                          <div className="mt-1 w-5" />
                        )}
                        <div className="p-2 bg-warning/10 rounded-full">
                          <AlertTriangle className="w-5 h-5 text-warning" />
                        </div>
                        
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-xs px-2 py-0.5 bg-muted/10 text-muted rounded font-medium">
                              {item.block_type || 'texto'}
                            </span>
                            {item.product_name && (
                              <span className="text-xs text-primary font-medium">
                                {item.product_name}
                              </span>
                            )}
                          </div>

                          {(item.block_title || item.title) && (
                            <h3 className="font-medium text-foreground mb-2">{item.block_title || item.title}</h3>
                          )}

                          <ContentPreview 
                            content={item.extracted_content || item.content} 
                            blockType={item.block_type}
                          />

                          {(item.risk_reason || item.reason) && (
                            <div className="flex items-center gap-2 text-sm text-warning mb-3">
                              <AlertTriangle className="w-4 h-4" />
                              Motivo: {item.risk_reason || item.reason}
                            </div>
                          )}

                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              variant="success"
                              onClick={() => handleApprove(item)}
                              disabled={processing}
                            >
                              <Check className="w-4 h-4" />
                              Aprovar
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => openEditModal(item)}
                              disabled={processing}
                            >
                              <Edit className="w-4 h-4" />
                              Editar e Aprovar
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => openRejectModal(item)}
                              disabled={processing}
                            >
                              <X className="w-4 h-4" />
                              Rejeitar
                            </Button>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            </>
          )}
        </>
      )}

      {activeTab === 'products' && (
        <>
          {loadingProducts ? (
            <div className="py-20">
              <LoadingSpinner size="lg" />
            </div>
          ) : productItems.length === 0 ? (
            <EmptyState
              icon={Package}
              title="Nenhum produto pendente de confirmação"
              description="Todos os materiais já foram vinculados a produtos. Volte mais tarde para verificar novos itens."
            />
          ) : (
            <div className="space-y-4">
              <AnimatePresence>
                {productItems.map((item) => (
                  <ProductMatchCard
                    key={item.material_id}
                    item={item}
                    onResolved={handleProductResolved}
                    addToast={addToast}
                  />
                ))}
              </AnimatePresence>
            </div>
          )}
        </>
      )}

      <Modal
        open={showEditModal}
        onClose={() => setShowEditModal(false)}
        title={
          <div className="flex items-center gap-3">
            <span>Editar e Aprovar</span>
            {selectedItem && (
              <>
                <span className="text-xs px-2 py-0.5 bg-muted/10 text-muted rounded">
                  {selectedItem.block_type || 'texto'}
                </span>
                {selectedItem.product_name && (
                  <span className="text-xs text-primary font-medium">
                    {selectedItem.product_name}
                  </span>
                )}
                {selectedItem.source_page && (
                  <span className="text-xs text-muted">
                    Página {selectedItem.source_page}
                  </span>
                )}
              </>
            )}
          </div>
        }
        size="xl"
      >
        <div className="flex gap-4 h-[70vh]">
          <div className="w-1/2 flex flex-col">
            <PDFViewer 
              materialId={selectedItem?.material_id} 
              page={selectedItem?.source_page || 1}
            />
          </div>
          
          <div className="w-1/2 flex flex-col">
            <div className="flex items-center justify-between px-3 py-2 bg-muted/10 border-b border-border rounded-t-lg">
              <span className="text-xs font-medium text-muted">Conteúdo Extraído</span>
              {selectedItem?.block_type === 'tabela' && (
                <span className="text-xs text-muted">Convertido em tópicos</span>
              )}
            </div>
            
            <div className="flex-1 overflow-auto p-3 bg-card border border-t-0 border-border rounded-b-lg">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full h-full px-3 py-2 bg-transparent border-0
                           text-foreground text-sm resize-none focus:outline-none"
                placeholder="Conteúdo do bloco..."
              />
            </div>
            
            {selectedItem?.risk_reason && (
              <div className="flex items-center gap-2 text-sm text-warning mt-3 px-1">
                <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                <span>Motivo: {selectedItem.risk_reason}</span>
              </div>
            )}
            
            <div className="flex gap-3 mt-4">
              <Button
                variant="secondary"
                onClick={() => setShowEditModal(false)}
                className="flex-1"
              >
                Cancelar
              </Button>
              <Button
                variant="success"
                onClick={handleEdit}
                loading={processing}
                className="flex-1"
              >
                Salvar e Aprovar
              </Button>
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={showRejectModal}
        onClose={() => setShowRejectModal(false)}
        title="Rejeitar Item"
        size="sm"
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Informe o motivo da rejeição:
          </p>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={4}
            placeholder="Ex: Informação desatualizada, dados incorretos..."
            className="w-full px-3 py-2 bg-card border border-border rounded-input
                       text-foreground resize-none focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <div className="flex gap-3">
            <Button
              variant="secondary"
              onClick={() => setShowRejectModal(false)}
              className="flex-1"
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              onClick={handleReject}
              loading={processing}
              className="flex-1"
            >
              Confirmar Rejeição
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
