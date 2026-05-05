import { useState, useRef, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, FileText, CheckCircle, ArrowRight, Sparkles, Info, AlertCircle, RotateCcw, Clock, Trash2, X, Loader, Loader2, Files, List, ChevronUp, ChevronDown, FileWarning, FileUp, Copy, Search, Link2, PlusCircle, Briefcase } from 'lucide-react';
import { materialsAPI, productsAPI } from '../services/api';
import { Button } from '../components/Button';
import { ProductAutocomplete } from '../components/ProductAutocomplete';
import { StructuredTags } from '../components/StructuredTags';
import { useToast } from '../components/Toast';
import { useConfirmDialog } from '../components/ConfirmDialog';
import { useDropzone } from 'react-dropzone';

function normalize(str) {
  return (str || '').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

function extractTickers(filename) {
  const upper = filename.toUpperCase();
  const matches = upper.match(/\b[A-Z]{4}[0-9]{1,2}\b/g);
  return matches || [];
}

function matchFileToMaterial(file, materials) {
  const fname = file.name;
  const fnameNorm = normalize(fname.replace(/\.pdf$/i, ''));
  const fileTickers = extractTickers(fname);

  let bestMatch = null;
  let bestScore = 0;

  for (const m of materials) {
    let score = 0;
    const mTicker = (m.product_ticker || '').toUpperCase();
    const mNameNorm = normalize(m.name);
    const pNameNorm = normalize(m.product_name);

    if (mTicker && fileTickers.includes(mTicker)) {
      score += 50;
      const typeKeywords = {
        research: ['research', 'relatorio', 'gerencial'],
        apresentacao: ['apresentacao', 'apresenta'],
        one_page: ['one_page', 'onepage', 'one pager', 'lamina'],
        comite: ['comite'],
        campanha: ['campanha']
      };
      const typeWords = typeKeywords[m.material_type] || [];
      if (typeWords.some(tw => fnameNorm.includes(tw))) {
        score += 20;
      }
      const sameTickerCount = materials.filter(x => (x.product_ticker || '').toUpperCase() === mTicker).length;
      if (sameTickerCount === 1) {
        score += 15;
      }
    }

    const mWords = mNameNorm.split(' ').filter(w => w.length > 2);
    const matchedWords = mWords.filter(w => fnameNorm.includes(w));
    if (matchedWords.length > 0) {
      score += Math.min(30, matchedWords.length * 10);
    }

    const pWords = pNameNorm.split(' ').filter(w => w.length > 2);
    const matchedPWords = pWords.filter(w => fnameNorm.includes(w));
    if (matchedPWords.length > 0) {
      score += Math.min(15, matchedPWords.length * 5);
    }

    if (score > bestScore) {
      bestScore = score;
      bestMatch = m;
    }
  }

  let confidence = 'none';
  if (bestScore >= 50) confidence = 'high';
  else if (bestScore >= 20) confidence = 'medium';

  return { file, match: bestMatch, score: bestScore, confidence, selectedMaterialId: bestMatch ? bestMatch.id : null };
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export function SmartUpload() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { addToast } = useToast();
  const { confirmDialog, openConfirm } = useConfirmDialog();
  const logRef = useRef(null);

  // Task #206 — Lê portfolio_id da query string (?portfolio_id=N)
  // para que uploads iniciados a partir de uma Carteira Recomendada
  // sejam automaticamente vinculados a ela.
  const portfolioIdFromUrl = searchParams.get('portfolio_id')
    ? parseInt(searchParams.get('portfolio_id'), 10) || null
    : null;
  const portfolioNameFromUrl = searchParams.get('portfolio_name') || null;

  const [step, setStep] = useState(1);
  const [files, setFiles] = useState([]);
  const [materialType, setMaterialType] = useState('');
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [tags, setTags] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [logs, setLogs] = useState([]);
  const [hasError, setHasError] = useState(false);
  const [stats, setStats] = useState(null);

  const [queueItems, setQueueItems] = useState([]);
  const [showQueue, setShowQueue] = useState(false);
  const [recentlyQueued, setRecentlyQueued] = useState(false);
  const eventSourceRef = useRef(null);

  const [analysisResults, setAnalysisResults] = useState([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const [missingPdfMaterials, setMissingPdfMaterials] = useState([]);
  const [failedMaterials, setFailedMaterials] = useState([]);
  const [loadingUnified, setLoadingUnified] = useState(true);
  const [bulkMatches, setBulkMatches] = useState([]);
  const [showBulkResults, setShowBulkResults] = useState(false);
  const [bulkUploading, setBulkUploading] = useState(false);
  const [reuploadingIds, setReuploadingIds] = useState(new Set());
  const [dismissingIds, setDismissingIds] = useState(new Set());
  const [showMissingPdf, setShowMissingPdf] = useState(false);
  const [showFailed, setShowFailed] = useState(false);
  const [campaignSlug, setCampaignSlug] = useState('');
  const [campaignStructureType, setCampaignStructureType] = useState('');
  const [campaignKeyData, setCampaignKeyData] = useState([]);
  const [campaignDiagramFile, setCampaignDiagramFile] = useState(null);
  const [derivativeSlugs, setDerivativeSlugs] = useState([]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    const productId = searchParams.get('product');
    if (productId) {
      productsAPI.get(productId).then((product) => {
        setSelectedProduct(product);
      }).catch((e) => { console.warn('[SmartUpload] Erro ao carregar produto:', e.message); });
    }
  }, [searchParams]);

  useEffect(() => {
    if (materialType === 'campanha' && derivativeSlugs.length === 0) {
      fetch('/api/campaigns/derivative-slugs', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      })
        .then(r => r.json())
        .then(data => { if (data.slugs) setDerivativeSlugs(data.slugs); })
        .catch((e) => { console.warn('[SmartUpload] Erro ao carregar slugs:', e.message); });
    }
  }, [materialType]);

  useEffect(() => {
    loadQueueStatus();
    loadUnifiedPending();
  }, []);

  useEffect(() => {
    if (showQueue) {
      connectToQueueStream();
    }
    return () => {
      eventSourceRef.current = null;
    };
  }, [showQueue]);

  const loadQueueStatus = async () => {
    try {
      const response = await fetch('/api/products/upload-queue/status', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (response.ok) {
        const data = await response.json();
        const allItems = [...(data.active || []), ...(data.history || []).slice(0, 10)];
        setQueueItems(allItems);
        if (data.active && data.active.length > 0) {
          setShowQueue(true);
        } else if (allItems.length > 0 && recentlyQueued) {
          setShowQueue(true);
        }
      }
    } catch (err) {
      console.error('Erro ao carregar fila:', err);
    }
  };

  const connectToQueueStream = () => {
    if (eventSourceRef.current) return;
    eventSourceRef.current = true;

    const pollQueue = async () => {
      while (eventSourceRef.current) {
        await loadQueueStatus();
        await new Promise(r => setTimeout(r, 3000));
      }
    };
    pollQueue();
  };

  const loadUnifiedPending = async () => {
    setLoadingUnified(true);
    try {
      const response = await fetch('/api/products/materials/pending-unified', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (response.ok) {
        const data = await response.json();
        setMissingPdfMaterials(data.missing_pdf || []);
        setFailedMaterials(data.failed_processing || []);
        if ((data.missing_pdf || []).length > 0) setShowMissingPdf(true);
        if ((data.failed_processing || []).length > 0) setShowFailed(true);
      }
    } catch (err) {
      console.error('Erro ao carregar pendentes unificados:', err);
    } finally {
      setLoadingUnified(false);
    }
  };

  const handleResumeFromList = async (materialId) => {
    try {
      const response = await fetch(`/api/products/materials/${materialId}/queue-resume`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (response.ok) {
        const data = await response.json();
        addToast(data.message || 'Processamento retomado em segundo plano', 'success');
        setShowQueue(true);
        loadQueueStatus();
        loadUnifiedPending();
      } else {
        const err = await response.json().catch(() => ({}));
        addToast(err.detail || 'Erro ao retomar processamento', 'error');
      }
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const handleDiscardPending = async (materialId) => {
    const confirmed = await openConfirm({
      title: 'Descartar Upload',
      message: 'Deseja descartar este upload? O arquivo e os blocos serão removidos permanentemente.',
      confirmText: 'Descartar',
      type: 'danger',
    });
    if (!confirmed) return;

    try {
      const response = await fetch(`/api/products/materials/${materialId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` },
      });
      if (response.ok) {
        addToast('Upload descartado', 'success');
        loadUnifiedPending();
      } else {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || 'Falha ao descartar');
      }
    } catch (err) {
      addToast(`Erro ao descartar: ${err.message}`, 'error');
    }
  };

  const handleReorder = async (uploadId, direction) => {
    try {
      const response = await fetch('/api/products/upload-queue/reorder', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ upload_id: uploadId, direction })
      });
      if (response.ok) {
        loadQueueStatus();
      }
    } catch (err) {
      console.error('Erro ao reordenar:', err);
    }
  };

  const handleRemoveFromQueue = async (uploadId) => {
    try {
      const response = await fetch(`/api/products/upload-queue/${uploadId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (response.ok) {
        addToast('Item removido da fila', 'success');
        loadQueueStatus();
      } else {
        addToast('Não foi possível remover o item', 'error');
      }
    } catch (err) {
      console.error('Erro ao remover da fila:', err);
      addToast('Erro ao remover da fila', 'error');
    }
  };

  const handleSingleReupload = async (materialId, file) => {
    setReuploadingIds(prev => new Set(prev).add(materialId));
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/products/admin/reupload-pdf/${materialId}`, {
        method: 'POST',
        body: formData,
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Erro ao enviar');
      }
      addToast('PDF enviado com sucesso', 'success');
      loadUnifiedPending();
    } catch (err) {
      addToast(err.message || 'Erro ao enviar PDF', 'error');
    } finally {
      setReuploadingIds(prev => {
        const next = new Set(prev);
        next.delete(materialId);
        return next;
      });
    }
  };

  const handleDismissPdf = async (material) => {
    const confirmed = await openConfirm({
      title: 'Remover da lista de pendências',
      message: `"${material.name}" não precisa de PDF para WhatsApp? O conteúdo continua indexado e disponível para o agente.`,
      confirmText: 'Sim, remover',
      cancelText: 'Cancelar',
      type: 'warning',
    });
    if (!confirmed) return;

    setDismissingIds(prev => new Set(prev).add(material.id));
    try {
      await materialsAPI.dismissPdf(material.id);
      setMissingPdfMaterials(prev => prev.filter(m => m.id !== material.id));
      addToast('Material removido da lista de pendências', 'success');
    } catch (err) {
      addToast(err.message || 'Erro ao dispensar material', 'error');
    } finally {
      setDismissingIds(prev => {
        const next = new Set(prev);
        next.delete(material.id);
        return next;
      });
    }
  };

  const handleBulkDrop = useCallback((acceptedFiles) => {
    const pdfFiles = acceptedFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfFiles.length === 0) {
      addToast('Apenas arquivos PDF são aceitos', 'warning');
      return;
    }
    const pending = missingPdfMaterials;
    const matches = pdfFiles.map(f => matchFileToMaterial(f, pending));
    setBulkMatches(matches);
    setShowBulkResults(true);
  }, [missingPdfMaterials, addToast]);

  const { getRootProps: getBulkRootProps, getInputProps: getBulkInputProps, isDragActive: isBulkDragActive } = useDropzone({
    onDrop: handleBulkDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    noClick: false,
  });

  const updateBulkMatch = (idx, materialId) => {
    setBulkMatches(prev => {
      const next = [...prev];
      next[idx] = {
        ...next[idx],
        selectedMaterialId: materialId ? parseInt(materialId) : null,
        confidence: materialId ? 'medium' : 'none'
      };
      return next;
    });
  };

  const confirmBulkUpload = async () => {
    const toUpload = bulkMatches.filter(e => e.selectedMaterialId);
    if (toUpload.length === 0) {
      addToast('Nenhum arquivo associado a um material', 'warning');
      return;
    }

    setBulkUploading(true);
    let success = 0;
    let errors = 0;

    const updated = [...bulkMatches];

    for (let i = 0; i < updated.length; i++) {
      const entry = updated[i];
      if (!entry.selectedMaterialId) {
        updated[i] = { ...entry, uploadStatus: 'skipped' };
        continue;
      }

      updated[i] = { ...entry, uploadStatus: 'uploading' };
      setBulkMatches([...updated]);

      try {
        const formData = new FormData();
        formData.append('file', entry.file);
        const res = await fetch(`/api/products/admin/reupload-pdf/${entry.selectedMaterialId}`, {
          method: 'POST',
          body: formData,
          headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Erro');
        }
        const data = await res.json();
        updated[i] = { ...entry, uploadStatus: 'success', uploadResult: formatFileSize(data.file_size) };
        success++;
      } catch (err) {
        updated[i] = { ...entry, uploadStatus: 'error', uploadError: err.message };
        errors++;
      }
      setBulkMatches([...updated]);
    }

    setBulkUploading(false);

    if (errors === 0) {
      addToast(`${success} PDF(s) enviado(s) com sucesso!`, 'success');
      setTimeout(() => {
        setShowBulkResults(false);
        setBulkMatches([]);
        loadUnifiedPending();
      }, 1500);
    } else {
      addToast(`${success} enviado(s), ${errors} erro(s)`, 'error');
      loadUnifiedPending();
    }
  };

  const cancelBulk = () => {
    setShowBulkResults(false);
    setBulkMatches([]);
  };

  const addLog = (message, type = 'info') => {
    const time = new Date().toLocaleTimeString('pt-BR');
    setLogs(prev => [...prev, { time, message, type }]);
  };

  const handlePreAnalyze = async () => {
    if (!files.length) {
      addToast('Selecione pelo menos um arquivo para enviar', 'warning');
      return;
    }
    setAnalyzing(true);
    try {
      const formData = new FormData();
      for (const file of files) {
        formData.append('files', file);
      }
      formData.append('material_type', materialType || 'one_page');
      formData.append('tags', JSON.stringify(tags));
      if (validFrom) formData.append('valid_from', validFrom);
      if (validUntil) formData.append('valid_until', validUntil);
      // Task #206 — passa portfolio_id para que pré-análise/upload criem
      // o material já vinculado à Carteira Recomendada
      if (portfolioIdFromUrl) formData.append('portfolio_id', String(portfolioIdFromUrl));

      const response = await fetch('/api/products/pre-analyze-upload', {
        method: 'POST',
        body: formData,
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `Erro ${response.status}`);
      }

      const data = await response.json();
      const materialsWithProducts = (data.materials || []).map(m => ({
        ...m,
        identified_products: (m.identified_products || []).map(p => ({
          ...p,
          selected: p.selected !== false,
          _manualInput: false,
        })),
      }));

      setAnalysisResults(materialsWithProducts);
      setStep(3);
    } catch (err) {
      addToast(`Erro ao analisar arquivos: ${err.message}`, 'error');
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleProductSelection = (materialIdx, productIdx) => {
    setAnalysisResults(prev => {
      const next = prev.map((m, mi) => {
        if (mi !== materialIdx) return m;
        return {
          ...m,
          identified_products: m.identified_products.map((p, pi) =>
            pi === productIdx ? { ...p, selected: !p.selected } : p
          ),
        };
      });
      return next;
    });
  };

  const addManualProduct = (materialIdx, text) => {
    if (!text.trim()) return;
    const tickerMatch = text.trim().toUpperCase().match(/\b([A-Z]{4}[0-9]{1,2})\b/);
    const ticker = tickerMatch ? tickerMatch[1] : null;
    const name = text.trim();
    setAnalysisResults(prev => {
      const next = [...prev];
      next[materialIdx] = {
        ...next[materialIdx],
        identified_products: [
          ...next[materialIdx].identified_products,
          { ticker, name, product_id: null, exists_in_db: false, selected: true, _manualInput: true },
        ],
      };
      return next;
    });
  };

  const forceCreateNew = (materialIdx, productIdx) => {
    // Usuário viu que o produto identificado bateu por engano com algo já existente
    // (ex.: POP de MYPK3 batendo com a ação MYPK3) e quer forçar a criação de um produto novo.
    // Limpa o vínculo local e seta `force_new` que será enviado ao backend para
    // ignorar busca por ticker/nome no link-and-queue.
    setAnalysisResults(prev => prev.map((m, mi) => {
      if (mi !== materialIdx) return m;
      return {
        ...m,
        identified_products: m.identified_products.map((p, pi) => {
          if (pi !== productIdx) return p;
          return {
            ...p,
            product_id: null,
            exists_in_db: false,
            match_confidence: null,
            existing_product_name: null,
            existing_product_ticker: null,
            existing_product_type: null,
            force_new: true,
            // Restaura o tipo da IA quando havia "tomado emprestado" o tipo do match.
            product_type: p.ai_product_type || p.product_type,
          };
        }),
      };
    }));
  };

  const removeProduct = (materialIdx, productIdx) => {
    setAnalysisResults(prev => {
      const next = [...prev];
      next[materialIdx] = {
        ...next[materialIdx],
        identified_products: next[materialIdx].identified_products.filter((_, pi) => pi !== productIdx),
      };
      return next;
    });
  };

  const toggleProductExpansion = (materialIdx, productIdx) => {
    setAnalysisResults(prev => prev.map((m, mi) => {
      if (mi !== materialIdx) return m;
      return {
        ...m,
        identified_products: m.identified_products.map((p, pi) =>
          pi === productIdx ? { ...p, _expanded: !p._expanded } : p
        ),
      };
    }));
  };

  const updateProductKeyInfo = (materialIdx, productIdx, field, value) => {
    setAnalysisResults(prev => prev.map((m, mi) => {
      if (mi !== materialIdx) return m;
      return {
        ...m,
        identified_products: m.identified_products.map((p, pi) => {
          if (pi !== productIdx) return p;
          const deep = { ...(p.deep_info || {}) };
          deep[field] = value;
          return { ...p, deep_info: deep, _edited: true };
        }),
      };
    }));
  };

  const searchMissingProduct = async (materialIdx, description) => {
    const mat = analysisResults[materialIdx];
    if (!mat || !description?.trim()) return;

    setAnalysisResults(prev => prev.map((m, mi) =>
      mi === materialIdx ? { ...m, _searchingMissing: true, _missingNotFound: false } : m
    ));

    try {
      const existing = (mat.identified_products || [])
        .map(p => p.ticker).filter(Boolean);
      const resp = await fetch('/api/products/find-missing-product', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          material_id: mat.material_id,
          description: description.trim(),
          existing_products: existing,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Erro ${resp.status}`);
      }
      const data = await resp.json();

      if (data.found && data.product) {
        setAnalysisResults(prev => prev.map((m, mi) => {
          if (mi !== materialIdx) return m;
          return {
            ...m,
            _searchingMissing: false,
            _missingNotFound: false,
            identified_products: [
              ...m.identified_products,
              {
                ...data.product,
                selected: true,
                _expanded: true,
                _manualInput: false,
                _fromVisionSearch: true,
              },
            ],
          };
        }));
        addToast(
          `Produto encontrado nas páginas ${(data.found_on_pages || []).join(', ')}`,
          'success'
        );
      } else {
        setAnalysisResults(prev => prev.map((m, mi) =>
          mi === materialIdx ? { ...m, _searchingMissing: false, _missingNotFound: true } : m
        ));
      }
    } catch (err) {
      setAnalysisResults(prev => prev.map((m, mi) =>
        mi === materialIdx ? { ...m, _searchingMissing: false } : m
      ));
      addToast(`Erro na busca: ${err.message}`, 'error');
    }
  };

  const setMaterialConceptual = (materialIdx, value) => {
    setAnalysisResults(prev => prev.map((m, mi) =>
      mi === materialIdx ? { ...m, _isConceptual: !!value } : m
    ));
  };

  const handleConfirmAndQueue = async () => {
    // Materiais duplicados ainda são processáveis: o backend reutiliza o registro
    // existente, atualiza/cria os produtos identificados e acumula informações.
    const validMaterials = analysisResults.filter(m => m.material_id && !m.error);
    if (!validMaterials.length) {
      addToast('Nenhum material válido para processar', 'warning');
      return;
    }

    setConfirming(true);
    let successCount = 0;
    let errorCount = 0;

    for (const mat of validMaterials) {
      const isConceptual = !!mat._isConceptual;
      const confirmed = isConceptual ? [] : mat.identified_products.filter(p => p.selected);
      const primary = confirmed.find(p => p.product_id) || confirmed[0];
      const primaryId = primary?.product_id || null;

      const productsWithInfo = confirmed
        .filter(p => p.product_id && p.deep_info && Object.keys(p.deep_info).length > 0)
        .map(p => ({ product_id: p.product_id, key_info: p.deep_info }));

      try {
        const resp = await fetch(`/api/products/${mat.material_id}/link-and-queue`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            confirmed_products: confirmed,
            primary_product_id: primaryId,
            products_with_info: productsWithInfo,
            is_conceptual_material: isConceptual,
            // Task #206 — propaga portfolio_id para que o backend vincule o
            // material à Carteira Recomendada na etapa de confirmação.
            ...(portfolioIdFromUrl ? { portfolio_id: portfolioIdFromUrl } : {}),
          }),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || `Erro ${resp.status}`);
        }
        successCount++;
      } catch (err) {
        console.error(`Erro ao confirmar material ${mat.material_id}:`, err.message);
        errorCount++;
      }
    }

    setConfirming(false);

    if (successCount > 0) {
      const msg = successCount === 1
        ? 'Material enviado para processamento'
        : `${successCount} materiais enviados para processamento`;
      addToast(msg, 'success');

      // Só navega para a fila e limpa o formulário quando pelo menos um
      // material foi enfileirado com sucesso.
      setRecentlyQueued(true);
      setShowQueue(true);
      loadQueueStatus();

      setFiles([]);
      setSelectedProduct(null);
      setMaterialType('');
      setTags([]);
      setValidFrom('');
      setValidUntil('');
      setCampaignSlug('');
      setCampaignStructureType('');
      setCampaignKeyData([]);
      setCampaignDiagramFile(null);
      setAnalysisResults([]);
      setStep(1);
    }

    if (errorCount > 0) {
      const errMsg = successCount > 0
        ? `${errorCount} material(is) não pôde(ram) ser processado(s)`
        : errorCount === 1
          ? 'Erro ao confirmar o material. Verifique e tente novamente.'
          : `Erro ao confirmar ${errorCount} materiais. Verifique e tente novamente.`;
      addToast(errMsg, 'error');
      // Se TODOS falharam, mantém o usuário na tela de revisão para retry.
    }
  };

  const handleUpload = async () => {
    if (!files.length) {
      addToast('Selecione pelo menos um arquivo para enviar', 'warning');
      return;
    }

    setUploading(true);

    try {
      const formData = new FormData();
      for (const file of files) {
        formData.append('files', file);
      }
      formData.append('material_type', materialType || 'one_page');
      formData.append('tags', JSON.stringify(tags));
      if (validFrom) formData.append('valid_from', validFrom);
      if (validUntil) formData.append('valid_until', validUntil);
      if (selectedProduct) formData.append('product_id', selectedProduct.id.toString());
      // Task #206 — vincula à Carteira Recomendada quando vindo da página de carteira
      if (portfolioIdFromUrl) formData.append('portfolio_id', String(portfolioIdFromUrl));

      if (materialType === 'campanha' && campaignSlug) {
        formData.append('campaign_slug', campaignSlug);
        if (campaignStructureType) formData.append('campaign_structure_type', campaignStructureType);
        const kdObj = {};
        campaignKeyData.forEach(({ key, value }) => { if (key.trim()) kdObj[key.trim()] = value; });
        if (Object.keys(kdObj).length > 0) formData.append('campaign_key_data', JSON.stringify(kdObj));
        if (campaignDiagramFile) formData.append('campaign_diagram', campaignDiagramFile);
      }

      const response = await fetch('/api/products/batch-upload', {
        method: 'POST',
        body: formData,
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
      });

      if (!response.ok) throw new Error(`Erro ${response.status}`);

      const data = await response.json();
      const count = data.total_queued || files.length;
      const msg = count === 1
        ? 'Arquivo enviado para processamento em segundo plano'
        : `${count} arquivo(s) adicionado(s) à fila`;
      addToast(msg, 'success');

      setRecentlyQueued(true);
      setShowQueue(true);
      loadQueueStatus();

      setFiles([]);
      setSelectedProduct(null);
      setMaterialType('');
      setTags([]);
      setValidFrom('');
      setValidUntil('');
      setCampaignSlug('');
      setCampaignStructureType('');
      setCampaignKeyData([]);
      setCampaignDiagramFile(null);
      setStep(1);
      setUploading(false);
    } catch (err) {
      addToast(`Erro ao enviar arquivos: ${err.message}`, 'error');
      setUploading(false);
    }
  };

  const getLogColor = (type) => {
    switch (type) {
      case 'success': return 'text-green-400';
      case 'warning': return 'text-yellow-400';
      case 'error': return 'text-red-400';
      default: return 'text-slate-400';
    }
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'processing': return <Loader className="w-4 h-4 text-primary animate-spin" />;
      case 'failed': return <AlertCircle className="w-4 h-4 text-red-500" />;
      case 'queued': return <Clock className="w-4 h-4 text-amber-500" />;
      default: return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'completed': return 'Concluído';
      case 'processing': return 'Processando';
      case 'failed': return 'Falhou';
      case 'queued': return 'Na fila';
      default: return status;
    }
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'bg-green-50 text-green-700 border-green-200';
      case 'processing': return 'bg-primary/5 text-primary border-primary/20';
      case 'failed': return 'bg-red-50 text-red-700 border-red-200';
      case 'queued': return 'bg-amber-50 text-amber-700 border-amber-200';
      default: return 'bg-gray-50 text-gray-600 border-gray-200';
    }
  };

  const onDrop = useCallback((acceptedFiles) => {
    const pdfFiles = acceptedFiles.filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfFiles.length === 0) {
      addToast('Apenas arquivos PDF são aceitos', 'warning');
      return;
    }
    setFiles(prev => [...prev, ...pdfFiles]);
  }, [addToast]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxSize: 50 * 1024 * 1024,
    multiple: true,
  });

  const removeFile = (index) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const renderMissingPdfSection = () => {
    if (loadingUnified || missingPdfMaterials.length === 0) return null;

    return (
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <button
          onClick={() => setShowMissingPdf(!showMissingPdf)}
          className="w-full flex items-center justify-between p-4 bg-blue-50 border border-blue-200 rounded-xl hover:bg-blue-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <FileUp className="w-5 h-5 text-blue-600" />
            <h3 className="font-semibold text-blue-800">Sem PDF para WhatsApp</h3>
            <span className="text-xs px-2 py-0.5 bg-blue-200 text-blue-800 rounded-full">
              {missingPdfMaterials.length}
            </span>
          </div>
          <ChevronDown className={`w-5 h-5 text-blue-600 transition-transform ${showMissingPdf ? 'rotate-180' : ''}`} />
        </button>

        <AnimatePresence>
          {showMissingPdf && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-2 p-4 bg-white border border-blue-100 rounded-xl space-y-4">
                <p className="text-sm text-blue-700">
                  Materiais processados com sucesso (conteúdo indexado) mas sem o arquivo PDF necessário para envio via WhatsApp.
                </p>

                {!showBulkResults && (
                  <div
                    {...getBulkRootProps()}
                    className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
                      isBulkDragActive ? 'border-blue-500 bg-blue-50' : 'border-blue-200 hover:border-blue-400 bg-blue-50/50'
                    }`}
                  >
                    <input {...getBulkInputProps()} />
                    <Upload className={`w-8 h-8 mx-auto mb-2 ${isBulkDragActive ? 'text-blue-500' : 'text-blue-400'}`} />
                    <p className="text-sm font-medium text-blue-700">
                      Arraste vários PDFs aqui para upload automático
                    </p>
                    <p className="text-xs text-blue-500 mt-1">
                      O sistema identifica o material correspondente pelo nome do arquivo (ticker)
                    </p>
                  </div>
                )}

                {showBulkResults && (
                  <div className="border border-blue-200 rounded-xl overflow-hidden">
                    <div className="px-4 py-3 bg-blue-50 border-b border-blue-200 flex items-center justify-between">
                      <div>
                        <h4 className="font-semibold text-blue-800 text-sm">Arquivos identificados</h4>
                        <p className="text-xs text-blue-600 mt-0.5">
                          {bulkMatches.length} arquivo(s) — {bulkMatches.filter(e => e.selectedMaterialId).length} identificado(s)
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={cancelBulk} disabled={bulkUploading}>
                          Cancelar
                        </Button>
                        <Button size="sm" onClick={confirmBulkUpload} disabled={bulkUploading || bulkMatches.filter(e => e.selectedMaterialId).length === 0}>
                          {bulkUploading ? (
                            <>
                              <Loader2 className="w-3 h-3 animate-spin" />
                              Enviando...
                            </>
                          ) : 'Confirmar e Enviar'}
                        </Button>
                      </div>
                    </div>
                    <div className="divide-y divide-blue-100 max-h-64 overflow-y-auto">
                      {bulkMatches.map((entry, idx) => (
                        <div key={idx} className={`px-4 py-3 flex items-center gap-3 ${
                          entry.confidence === 'high' ? 'bg-green-50/50' :
                          entry.confidence === 'medium' ? 'bg-amber-50/50' : 'bg-red-50/50'
                        }`}>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-slate-800 truncate">{entry.file.name}</p>
                            <p className="text-xs text-slate-500">{formatFileSize(entry.file.size)}</p>
                          </div>
                          <select
                            className="text-xs border border-slate-300 rounded px-2 py-1.5 max-w-[200px] bg-white"
                            value={entry.selectedMaterialId || ''}
                            onChange={(e) => updateBulkMatch(idx, e.target.value)}
                            disabled={bulkUploading}
                          >
                            <option value="">-- Selecionar --</option>
                            {missingPdfMaterials.map(m => (
                              <option key={m.id} value={m.id}>
                                {m.product_ticker ? `${m.product_ticker} - ` : ''}{m.name}
                              </option>
                            ))}
                          </select>
                          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                            entry.confidence === 'high' ? 'bg-green-100 text-green-700' :
                            entry.confidence === 'medium' ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'
                          }`}>
                            {entry.confidence === 'high' ? 'Alto' : entry.confidence === 'medium' ? 'Médio' : 'Sem match'}
                          </span>
                          <div className="w-16 text-right">
                            {entry.uploadStatus === 'uploading' && <Loader2 className="w-4 h-4 text-blue-500 animate-spin inline" />}
                            {entry.uploadStatus === 'success' && <CheckCircle className="w-4 h-4 text-green-500 inline" />}
                            {entry.uploadStatus === 'error' && (
                              <span className="text-xs text-red-500" title={entry.uploadError}>Erro</span>
                            )}
                            {entry.uploadStatus === 'skipped' && <span className="text-xs text-slate-400">—</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="max-h-72 overflow-y-auto space-y-2">
                  {missingPdfMaterials.map((m) => (
                    <div key={m.id} className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100 group">
                      <FileText className="w-4 h-4 text-blue-500 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-800 truncate">{m.name}</p>
                        <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
                          {m.product_ticker && (
                            <span className="text-primary font-medium">{m.product_ticker}</span>
                          )}
                          <span>{m.blocks_count} blocos indexados</span>
                          {m.material_type && (
                            <span className="px-1.5 py-0.5 bg-slate-200 rounded text-[10px]">{m.material_type}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <label className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg cursor-pointer transition-colors ${
                          reuploadingIds.has(m.id)
                            ? 'bg-slate-200 text-slate-400 cursor-wait'
                            : 'bg-blue-600 text-white hover:bg-blue-700'
                        }`}>
                          {reuploadingIds.has(m.id) ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : (
                            <Upload className="w-3 h-3" />
                          )}
                          {reuploadingIds.has(m.id) ? 'Enviando...' : 'PDF'}
                          <input
                            type="file"
                            accept=".pdf"
                            className="hidden"
                            disabled={reuploadingIds.has(m.id)}
                            onChange={(e) => {
                              const f = e.target.files[0];
                              if (f) handleSingleReupload(m.id, f);
                              e.target.value = '';
                            }}
                          />
                        </label>
                        <button
                          onClick={() => handleDismissPdf(m)}
                          disabled={dismissingIds.has(m.id)}
                          title="Não precisa de PDF para WhatsApp"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40 disabled:cursor-wait"
                        >
                          {dismissingIds.has(m.id)
                            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            : <X className="w-3.5 h-3.5" />
                          }
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    );
  };

  const renderFailedSection = () => {
    if (loadingUnified || failedMaterials.length === 0) return null;

    return (
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <button
          onClick={() => setShowFailed(!showFailed)}
          className="w-full flex items-center justify-between p-4 bg-red-50 border border-red-200 rounded-xl hover:bg-red-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-red-600" />
            <h3 className="font-semibold text-red-800">Processamento Incompleto</h3>
            <span className="text-xs px-2 py-0.5 bg-red-200 text-red-800 rounded-full">
              {failedMaterials.length}
            </span>
          </div>
          <ChevronDown className={`w-5 h-5 text-red-600 transition-transform ${showFailed ? 'rotate-180' : ''}`} />
        </button>

        <AnimatePresence>
          {showFailed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="mt-2 p-4 bg-white border border-red-100 rounded-xl space-y-2">
                {failedMaterials.map((m) => (
                  <div key={m.id} className={`p-3 rounded-lg border ${
                    m.has_success_duplicate ? 'bg-amber-50/50 border-amber-200' : 'bg-red-50/50 border-red-100'
                  }`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <FileWarning className={`w-5 h-5 flex-shrink-0 ${m.has_success_duplicate ? 'text-amber-500' : 'text-red-500'}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="font-medium text-slate-800 truncate">{m.name}</p>
                            {m.has_success_duplicate && (
                              <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 bg-amber-100 text-amber-700 rounded-full whitespace-nowrap">
                                <Copy className="w-3 h-3" />
                                Duplicata — versão completa existe ({m.success_duplicate_blocks} blocos)
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-slate-500 mt-0.5">
                            {m.product_ticker && (
                              <span className="text-primary font-medium">{m.product_ticker}</span>
                            )}
                            {m.blocks_count > 0 && (
                              <span className="text-green-600">{m.blocks_count} blocos</span>
                            )}
                            {m.processing_error && (
                              <span className="text-red-500 truncate max-w-[200px]" title={m.processing_error}>
                                {m.processing_error}
                              </span>
                            )}
                          </div>
                          {!m.can_resume && !m.has_success_duplicate && (
                            <p className="text-xs text-amber-700 mt-1.5 leading-relaxed">
                              O arquivo original não está mais disponível no servidor. Para reprocessar, exclua este item e envie o PDF novamente.
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {m.can_resume && !m.has_success_duplicate && (
                          <Button
                            size="sm"
                            onClick={() => handleResumeFromList(m.id)}
                            className="bg-amber-600 hover:bg-amber-700"
                          >
                            <RotateCcw className="w-3 h-3" />
                            Retomar
                          </Button>
                        )}
                        <button
                          onClick={() => handleDiscardPending(m.id)}
                          className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded"
                          title={m.has_success_duplicate ? 'Descartar duplicata' : 'Descartar'}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    );
  };

  const formatEta = (seconds) => {
    if (!seconds || seconds <= 0) return null;
    if (seconds < 60) return `~${Math.ceil(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    if (mins >= 60) {
      const hrs = Math.floor(mins / 60);
      const remainMins = mins % 60;
      return `~${hrs}h${remainMins > 0 ? ` ${remainMins}min` : ''}`;
    }
    return secs > 0 ? `~${mins}min ${secs}s` : `~${mins}min`;
  };

  const renderQueueMonitor = () => {
    const activeItems = queueItems
      .filter(i => i.status === 'processing' || i.status === 'queued')
      .sort((a, b) => {
        if (a.status === 'processing' && b.status !== 'processing') return -1;
        if (a.status !== 'processing' && b.status === 'processing') return 1;
        return 0;
      });
    const doneItems = queueItems.filter(i => i.status === 'completed' || i.status === 'failed');

    return (
      <div className="space-y-3">

        {activeItems.length > 0 && (
          <div className="space-y-2">
            {activeItems.map((item, idx) => {
              const queuedItems = activeItems.filter(i => i.status === 'queued');
              const queuedIdx = queuedItems.findIndex(i => i.upload_id === item.upload_id);
              const isQueued = item.status === 'queued';
              const canMoveUp = isQueued && queuedIdx > 0;
              const canMoveDown = isQueued && queuedIdx >= 0 && queuedIdx < queuedItems.length - 1;

              return (
              <div key={item.upload_id} className={`p-4 rounded-lg border ${getStatusColor(item.status)}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    {getStatusIcon(item.status)}
                    <span className="font-medium text-sm truncate">{item.filename}</span>
                  </div>
                  <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                    {isQueued && queuedItems.length > 1 && (
                      <div className="flex flex-col">
                        <button
                          onClick={() => handleReorder(item.upload_id, 'up')}
                          disabled={!canMoveUp}
                          className={`p-0.5 rounded transition-colors ${canMoveUp ? 'text-slate-500 hover:text-primary hover:bg-primary/10' : 'text-slate-200 cursor-not-allowed'}`}
                          title="Mover para cima"
                        >
                          <ChevronUp className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleReorder(item.upload_id, 'down')}
                          disabled={!canMoveDown}
                          className={`p-0.5 rounded transition-colors ${canMoveDown ? 'text-slate-500 hover:text-primary hover:bg-primary/10' : 'text-slate-200 cursor-not-allowed'}`}
                          title="Mover para baixo"
                        >
                          <ChevronDown className="w-4 h-4" />
                        </button>
                      </div>
                    )}
                    {isQueued && (
                      <button
                        onClick={() => handleRemoveFromQueue(item.upload_id)}
                        className="p-1 rounded text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                        title="Remover da fila"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                    <span className="text-xs font-medium">{getStatusLabel(item.status)}</span>
                  </div>
                </div>
                {item.status === 'processing' && (
                  <>
                    <div className="h-2 bg-white/50 rounded-full overflow-hidden mb-1">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${item.progress}%` }}
                        className="h-full bg-primary rounded-full transition-all"
                      />
                    </div>
                    <div className="flex justify-between text-xs opacity-75">
                      <span>Página {item.current_page}/{item.total_pages}</span>
                      <span className="flex items-center gap-2">
                        {item.eta_seconds > 0 && (
                          <span className="text-primary font-medium">{formatEta(item.eta_seconds)}</span>
                        )}
                        <span>{item.progress}%</span>
                      </span>
                    </div>
                    {item.product_name && (
                      <p className="text-xs mt-1">
                        Produto:{' '}
                        <span className="font-medium">
                          {[item.product_ticker || item.product_name, ...(item.additional_tickers || [])].join(', ')}
                        </span>
                      </p>
                    )}
                  </>
                )}
                {item.status === 'queued' && (
                  <p className="text-xs opacity-75">Aguardando na fila...</p>
                )}
              </div>
              );
            })}
          </div>
        )}

        {activeItems.length === 0 && doneItems.length > 0 && (
          <div className="text-center py-8">
            <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-3" />
            <p className="font-medium text-foreground">Todos os arquivos foram processados!</p>
            <p className="text-sm text-muted mt-1">Veja os resultados abaixo</p>
          </div>
        )}

        {doneItems.length > 0 && (
          <div className="mt-4">
            <h4 className="text-sm font-medium text-muted mb-2">Histórico recente</h4>
            <div className="space-y-1">
              {doneItems.slice(0, 10).map((item) => (
                <div key={item.upload_id} className="flex items-center gap-2 p-2 rounded hover:bg-gray-50 text-sm">
                  {getStatusIcon(item.status)}
                  <span className="flex-1 truncate">{item.filename}</span>
                  {item.product_ticker && (
                    <span className="text-xs text-primary font-medium">
                      {item.product_ticker}
                      {item.additional_tickers && item.additional_tickers.length > 0 && (
                        <span className="text-gray-400"> +{item.additional_tickers.length}</span>
                      )}
                    </span>
                  )}
                  {item.stats && (
                    <span className="text-xs text-muted">{item.stats.blocks_created} blocos</span>
                  )}
                  {item.error && (
                    <span className="text-xs text-red-500 truncate max-w-[150px]" title={item.error}>{item.error}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-3 justify-center pt-4">
          <Button variant="secondary" onClick={() => {
            setShowQueue(false);
          }}>
            Ocultar Fila
          </Button>
          <Button onClick={() => navigate('/review')}>
            Ver Fila de Revisão
          </Button>
        </div>
      </div>
    );
  };

  const renderStep1 = () => (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      {!loadingUnified && (missingPdfMaterials.length > 0 || failedMaterials.length > 0) && (
        <div className="flex items-center gap-2 p-3 bg-slate-100 border border-slate-200 rounded-xl">
          <AlertCircle className="w-5 h-5 text-slate-600" />
          <span className="text-sm font-medium text-slate-700">
            {missingPdfMaterials.length + failedMaterials.length} material(is) pendente(s) de ação
          </span>
        </div>
      )}
      {renderMissingPdfSection()}
      {renderFailedSection()}

      {/* Task #206 — Banner de contexto quando upload é iniciado de uma Carteira */}
      {portfolioIdFromUrl && (
        <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-teal-50 border border-teal-200 rounded-xl text-sm text-teal-800">
          <Briefcase className="w-4 h-4 text-teal-600 shrink-0" />
          <span>
            Os materiais enviados serão vinculados automaticamente à carteira
            {portfolioNameFromUrl ? (
              <strong className="mx-1">{portfolioNameFromUrl}</strong>
            ) : (
              <span className="mx-1">selecionada</span>
            )}
          </span>
        </div>
      )}

      <div className="text-center mb-8">
        <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
          <Upload className="w-8 h-8 text-primary" />
        </div>
        <h2 className="text-xl font-semibold text-foreground">Upload Inteligente</h2>
        <p className="text-muted mt-2">
          Envie um ou mais PDFs e a IA extrairá automaticamente os blocos de conhecimento
        </p>
      </div>

      <div
        {...getRootProps()}
        className={`
          relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors
          ${isDragActive ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'}
        `}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          {files.length > 0 ? (
            <Files className="w-10 h-10 text-primary" />
          ) : (
            <Upload className={`w-10 h-10 ${isDragActive ? 'text-primary' : 'text-muted'}`} />
          )}
          <div>
            <p className="text-sm font-medium text-foreground">
              {isDragActive ? 'Solte os arquivos aqui' : 'Arraste PDFs ou clique para selecionar'}
            </p>
            <p className="text-xs text-muted mt-1">
              Múltiplos arquivos aceitos — Máximo 50MB cada
            </p>
          </div>
        </div>
      </div>

      {files.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">
              {files.length} arquivo{files.length > 1 ? 's' : ''} selecionado{files.length > 1 ? 's' : ''}
            </span>
            <button
              onClick={() => setFiles([])}
              className="text-xs text-red-500 hover:underline"
            >
              Limpar todos
            </button>
          </div>
          <div className="max-h-48 overflow-y-auto space-y-1 border border-border rounded-lg p-2">
            {files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg group">
                <FileText className="w-4 h-4 text-primary flex-shrink-0" />
                <span className="text-sm flex-1 truncate">{f.name}</span>
                <span className="text-xs text-muted">{(f.size / 1024 / 1024).toFixed(1)}MB</span>
                <button
                  onClick={() => removeFile(i)}
                  className="p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex justify-end">
            <Button onClick={() => setStep(2)}>
              Continuar
              <ArrowRight className="w-4 h-4" />
            </Button>
          </div>
        </motion.div>
      )}
    </motion.div>
  );

  const renderStep2 = () => (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      <div className="flex items-center gap-3 p-4 bg-primary/5 rounded-xl border border-primary/20">
        {files.length === 1 ? (
          <FileText className="w-6 h-6 text-primary" />
        ) : (
          <Files className="w-6 h-6 text-primary" />
        )}
        <div className="flex-1">
          {files.length === 1 ? (
            <>
              <p className="font-medium text-foreground">{files[0]?.name}</p>
              <p className="text-sm text-muted">{(files[0]?.size / 1024 / 1024).toFixed(2)} MB</p>
            </>
          ) : (
            <>
              <p className="font-medium text-foreground">{files.length} arquivos selecionados</p>
              <p className="text-sm text-muted">
                {(files.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB total
              </p>
            </>
          )}
        </div>
        <button
          onClick={() => { setFiles([]); setStep(1); }}
          className="text-sm text-primary hover:underline"
        >
          Trocar
        </button>
      </div>

      {/*
        Aviso explicando que a IA vai extrair automaticamente o que antes era
        preenchido aqui. O usuário pode então ir direto para "Analisar e Processar".
        Se quiser, todos os campos antigos seguem disponíveis no <details> abaixo
        (e também são editáveis depois na tela do produto).
      */}
      <div className="flex items-start gap-3 p-4 bg-blue-50 rounded-xl border border-blue-200">
        <Sparkles className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0" />
        <div className="text-sm text-blue-800">
          <p className="font-medium mb-1">A IA cuida da categorização para você</p>
          <p className="text-xs text-blue-700 leading-relaxed">
            Vamos identificar automaticamente os produtos, tipo de material e principais
            metadados do documento. Você poderá revisar e ajustar tudo isso depois,
            direto na tela do produto criado. Basta clicar em <strong>Analisar e Processar</strong>.
          </p>
        </div>
      </div>

      <details className="border border-border rounded-xl group">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-foreground
                            flex items-center justify-between hover:bg-gray-50 rounded-xl
                            list-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2">
            <Info className="w-4 h-4 text-muted" />
            Opções avançadas (opcional)
          </span>
          <ChevronDown className="w-4 h-4 text-muted group-open:rotate-180 transition-transform" />
        </summary>
        <div className="px-4 pb-4 pt-2 space-y-5 border-t border-border">

      <div className="space-y-2">
        <label className="block text-sm font-medium text-foreground">
          Tipo do Material
        </label>
        <select
          value={materialType}
          onChange={(e) => setMaterialType(e.target.value)}
          className="w-full px-3 py-2 bg-card border border-border rounded-lg text-foreground
                     focus:outline-none focus:ring-2 focus:ring-primary/20 text-sm"
        >
          <option value="">Detectar automaticamente</option>
          <option value="research">Research</option>
          <option value="one_page">One-Page</option>
          <option value="apresentacao">Apresentação</option>
          <option value="taxas">Taxas</option>
          <option value="campanha">Campanha</option>
          <option value="treinamento">Treinamento</option>
          <option value="faq">FAQ</option>
          <option value="regulatorio">Regulatório</option>
          <option value="script">Script</option>
        </select>
        <p className="text-xs text-muted">
          Você poderá alterar isso depois na tela do produto.
        </p>
      </div>

      {materialType === 'campanha' && (
        <div className="space-y-4 p-4 bg-amber-50 border border-amber-200 rounded-xl">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-5 h-5 rounded bg-amber-500 flex items-center justify-center">
              <span className="text-white text-xs font-bold">C</span>
            </div>
            <span className="text-sm font-semibold text-amber-800">Configuração de Campanha</span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-amber-700 mb-1">Slug da Campanha *</label>
              <input
                type="text"
                value={campaignSlug}
                onChange={(e) => setCampaignSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                placeholder="put-spread-petr4"
                className="w-full px-3 py-2 bg-white border border-amber-300 rounded-lg text-sm
                           focus:outline-none focus:ring-2 focus:ring-amber-400/40"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-700 mb-1">Tipo de Estrutura</label>
              <select
                value={campaignStructureType}
                onChange={(e) => setCampaignStructureType(e.target.value)}
                className="w-full px-3 py-2 bg-white border border-amber-300 rounded-lg text-sm
                           focus:outline-none focus:ring-2 focus:ring-amber-400/40"
              >
                <option value="">Selecione...</option>
                {derivativeSlugs.length > 0 ? (
                  derivativeSlugs.map(s => (
                    <option key={s.slug} value={s.slug}>{s.name}{s.tab ? ` (${s.tab})` : ''}</option>
                  ))
                ) : (
                  <>
                    <option value="put-spread">Put Spread</option>
                    <option value="call-spread">Call Spread</option>
                    <option value="collar">Collar</option>
                    <option value="booster">Booster</option>
                    <option value="fence">Fence</option>
                    <option value="seagull">Seagull</option>
                    <option value="outro">Outro</option>
                  </>
                )}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-amber-700 mb-1">Dados da Estrutura</label>
            <div className="space-y-2">
              {campaignKeyData.map((row, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input
                    type="text"
                    value={row.key}
                    onChange={(e) => {
                      const updated = [...campaignKeyData];
                      updated[i] = { ...updated[i], key: e.target.value };
                      setCampaignKeyData(updated);
                    }}
                    placeholder="Chave (ex: Strike)"
                    className="flex-1 px-3 py-1.5 bg-white border border-amber-300 rounded-lg text-sm"
                  />
                  <input
                    type="text"
                    value={row.value}
                    onChange={(e) => {
                      const updated = [...campaignKeyData];
                      updated[i] = { ...updated[i], value: e.target.value };
                      setCampaignKeyData(updated);
                    }}
                    placeholder="Valor (ex: 100%)"
                    className="flex-1 px-3 py-1.5 bg-white border border-amber-300 rounded-lg text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setCampaignKeyData(campaignKeyData.filter((_, j) => j !== i))}
                    className="text-amber-400 hover:text-red-500 p-1"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => setCampaignKeyData([...campaignKeyData, { key: '', value: '' }])}
                className="text-xs text-amber-700 hover:text-amber-900 font-medium"
              >
                + Adicionar campo
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-amber-700 mb-1">Diagrama de Payoff (opcional)</label>
            <div className="flex items-center gap-3">
              <input
                type="file"
                accept="image/*"
                onChange={(e) => setCampaignDiagramFile(e.target.files[0] || null)}
                className="text-xs text-amber-700 file:mr-2 file:py-1 file:px-3 file:rounded-lg
                           file:border file:border-amber-300 file:bg-white file:text-sm file:text-amber-700
                           file:cursor-pointer hover:file:bg-amber-100"
              />
              {campaignDiagramFile && (
                <span className="text-xs text-green-600">{campaignDiagramFile.name}</span>
              )}
            </div>
          </div>

          <p className="text-xs text-amber-600">
            Uma estrutura de campanha será criada automaticamente e injetada no prompt do agente durante o período de validade.
          </p>
        </div>
      )}

      {files.length === 1 && (
        <div>
          <label className="block text-sm font-medium text-foreground mb-2">
            Produto Relacionado (opcional)
          </label>
          <ProductAutocomplete
            value={selectedProduct}
            onChange={setSelectedProduct}
            placeholder="Digite para buscar um produto..."
          />
          <div className="flex items-start gap-2 mt-2 p-3 bg-blue-50 rounded-xl border border-blue-200">
            <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-blue-700">
              Se não selecionar um produto, a IA identificará automaticamente os produtos mencionados em cada página do documento.
            </p>
          </div>
        </div>
      )}

      {files.length > 1 && (
        <div className="flex items-start gap-2 p-3 bg-blue-50 rounded-xl border border-blue-200">
          <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-blue-700">
            Os {files.length} arquivos serão processados sequencialmente (um de cada vez) para evitar sobrecarga.
            A IA identificará automaticamente os produtos de cada documento. Você pode acompanhar o progresso em tempo real.
          </p>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Período de Validade (opcional)
        </label>
        <div className="grid grid-cols-2 gap-3">
          <div className="relative">
            <input
              type="date"
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
              className="w-full px-4 py-3 bg-card border border-border rounded-lg
                         text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <span className="absolute -top-2 left-3 px-1 bg-card text-xs text-muted">Início</span>
          </div>
          <div className="relative">
            <input
              type="date"
              value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)}
              min={validFrom || undefined}
              className="w-full px-4 py-3 bg-card border border-border rounded-lg
                         text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <span className="absolute -top-2 left-3 px-1 bg-card text-xs text-muted">Fim</span>
          </div>
        </div>
        <p className="text-xs text-muted mt-2">
          Após a data fim, o documento não será mais consultado pelo agente
        </p>
      </div>

      <StructuredTags 
        value={tags} 
        onChange={setTags} 
      />

        </div>
      </details>

      <div className="flex gap-3 pt-4">
        <Button variant="secondary" onClick={() => setStep(1)} className="flex-1">
          Voltar
        </Button>
        {materialType === 'campanha' ? (
          <Button
            onClick={handleUpload}
            disabled={!files.length || uploading}
            className="flex-1"
          >
            {uploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Enviando...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                {files.length > 1 ? `Processar ${files.length} Campanhas` : 'Processar Campanha'}
              </>
            )}
          </Button>
        ) : (
          <Button
            onClick={handlePreAnalyze}
            disabled={!files.length || analyzing}
            className="flex-1"
          >
            {analyzing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Analisando com IA...
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                {files.length > 1 ? `Analisar ${files.length} Arquivos` : 'Analisar e Continuar'}
              </>
            )}
          </Button>
        )}
      </div>
    </motion.div>
  );

  const renderStep3 = () => {
    const validMaterials = analysisResults.filter(m => !m.error || m.duplicate);
    const errorMaterials = analysisResults.filter(m => m.error && !m.duplicate);
    const totalSelected = analysisResults.reduce((acc, m) =>
      acc + (m.identified_products || []).filter(p => p.selected).length, 0);

    return (
      <motion.div
        key="step3"
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        className="space-y-6"
      >
        <div>
          <h3 className="font-semibold text-foreground flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-primary" />
            Produtos Identificados pela IA
          </h3>
          <p className="text-xs text-muted">
            Revise os produtos detectados. Desmarque os incorretos e adicione os que faltam antes de confirmar.
          </p>
        </div>

        {errorMaterials.map((m, idx) => (
          <div key={idx} className="p-3 bg-red-50 border border-red-200 rounded-lg flex gap-2 text-sm text-red-700">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-medium">{m.filename}</span>
              {m.duplicate && <span className="ml-1 text-amber-700">(duplicado bloqueado)</span>}
              {!m.duplicate && <span className="ml-1">{m.error}</span>}
            </div>
          </div>
        ))}

        {analysisResults.map((mat, mi) => {
          if (mat.error && !mat.duplicate) return null;
          const manualInputId = `manual-${mi}`;
          const missingInputId = `missing-${mi}`;
          const selectedCount = (mat.identified_products || []).filter(p => p.selected).length;
          const isConceptual = !!mat._isConceptual;

          const noProductsAutoDetected = mat.no_products_detected
            && (!mat.identified_products || mat.identified_products.length === 0)
            && !mat._userOverrodeNoProducts;

          return (
            <div key={mi} className="border border-border rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 bg-card border-b border-border">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="w-4 h-4 text-primary flex-shrink-0" />
                  <span className="font-medium text-sm text-foreground truncate">{mat.filename}</span>
                </div>
                {!isConceptual && (
                  <span className="text-xs text-muted ml-2 flex-shrink-0">
                    {selectedCount} produto{selectedCount !== 1 ? 's' : ''} selecionado{selectedCount !== 1 ? 's' : ''}
                  </span>
                )}
                {isConceptual && (
                  <span className="text-xs text-indigo-600 font-medium ml-2 flex-shrink-0">Material conceitual</span>
                )}
              </div>

              {mat.duplicate && (
                <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800 flex items-start gap-2">
                  <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>
                    Este arquivo já existia na base{mat.existing_material_name ? ` como "${mat.existing_material_name}"` : ''}.
                    Os produtos abaixo foram identificados a partir do conteúdo — você pode revisá-los e atualizar as informações nos cards existentes.
                  </span>
                </div>
              )}

              {noProductsAutoDetected ? (
                <div className="p-6 space-y-4">
                  <div className="flex items-start gap-3">
                    <Info className="w-5 h-5 text-indigo-500 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium text-sm text-foreground">
                        Nenhum produto específico foi identificado neste material.
                      </p>
                      <p className="text-xs text-muted mt-1">
                        Este parece ser um material de{' '}
                        <span className="font-medium">{mat.material_nature_guess || 'outro'}</span>.
                        O conteúdo será indexado na base de conhecimento do agente para consultas gerais.
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <button
                      className="flex-1 px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
                      onClick={() => setMaterialConceptual(mi, true)}
                    >
                      Confirmar como material conceitual
                    </button>
                    <button
                      className="flex-1 px-4 py-2 text-sm bg-card border border-border rounded-lg hover:bg-border/50 font-medium"
                      onClick={() => setAnalysisResults(prev => prev.map((m, idx) =>
                        idx === mi ? { ...m, _userOverrodeNoProducts: true } : m
                      ))}
                    >
                      Havia produtos — deixa eu indicar
                    </button>
                  </div>
                </div>
              ) : isConceptual ? (
                <div className="p-6">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm text-indigo-700">
                      <CheckCircle className="w-4 h-4" />
                      Material marcado como conceitual. Será indexado sem vínculo a produtos.
                    </div>
                    <button
                      className="text-xs text-muted hover:text-foreground underline"
                      onClick={() => setMaterialConceptual(mi, false)}
                    >
                      Reverter
                    </button>
                  </div>
                </div>
              ) : (
                <div className="p-4 space-y-3">
                  {mat.identified_products && mat.identified_products.length > 0 ? (
                    <div className="space-y-2">
                      {mat.identified_products.map((p, pi) => {
                        const _typeColorMap = {
                          // Renda Variável — ativos básicos
                          'Ação': 'bg-green-50 text-green-700 border-green-200',
                          'Acao': 'bg-green-50 text-green-700 border-green-200',
                          'acao': 'bg-green-50 text-green-700 border-green-200',
                          'ETF': 'bg-cyan-50 text-cyan-700 border-cyan-200',
                          'etf': 'bg-cyan-50 text-cyan-700 border-cyan-200',
                          'BDR': 'bg-teal-50 text-teal-700 border-teal-200',
                          'bdr': 'bg-teal-50 text-teal-700 border-teal-200',
                          'FII': 'bg-blue-50 text-blue-700 border-blue-200',
                          'fii': 'bg-blue-50 text-blue-700 border-blue-200',
                          // Fundos
                          'Fundo': 'bg-purple-50 text-purple-700 border-purple-200',
                          'fundo': 'bg-purple-50 text-purple-700 border-purple-200',
                          'Fundo Multimercado': 'bg-purple-50 text-purple-700 border-purple-200',
                          'Fundo de Renda Fixa': 'bg-purple-50 text-purple-700 border-purple-200',
                          'FIA': 'bg-purple-50 text-purple-700 border-purple-200',
                          'FIC-FIA': 'bg-purple-50 text-purple-700 border-purple-200',
                          'FIDC': 'bg-purple-50 text-purple-700 border-purple-200',
                          'fidc': 'bg-purple-50 text-purple-700 border-purple-200',
                          // Renda Fixa / Crédito
                          'Debênture': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'Debenture': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'debenture': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'CRI': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'CRA': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'LCI': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          'LCA': 'bg-yellow-50 text-yellow-700 border-yellow-200',
                          // Estruturadas / derivativos de opções
                          'Estruturada': 'bg-orange-50 text-orange-700 border-orange-200',
                          'estruturada': 'bg-orange-50 text-orange-700 border-orange-200',
                          'POP': 'bg-orange-50 text-orange-700 border-orange-200',
                          'Collar': 'bg-orange-50 text-orange-700 border-orange-200',
                          'collar': 'bg-orange-50 text-orange-700 border-orange-200',
                          'COE': 'bg-orange-50 text-orange-700 border-orange-200',
                          // Operações táticas
                          'Swap': 'bg-rose-50 text-rose-700 border-rose-200',
                          'swap': 'bg-rose-50 text-rose-700 border-rose-200',
                          'Troca': 'bg-rose-50 text-rose-700 border-rose-200',
                          'Long & Short': 'bg-rose-50 text-rose-800 border-rose-300',
                          'Long&Short': 'bg-rose-50 text-rose-800 border-rose-300',
                          // Derivativos de bolsa
                          'Mercado Futuro': 'bg-indigo-50 text-indigo-700 border-indigo-200',
                          'Mercado a Termo': 'bg-indigo-50 text-indigo-700 border-indigo-200',
                          // Outros veículos
                          'Joint Venture': 'bg-gray-50 text-gray-700 border-gray-300',
                          'Outro': 'bg-gray-50 text-gray-600 border-gray-200',
                          'outro': 'bg-gray-50 text-gray-600 border-gray-200',
                        };
                        const typeColor = _typeColorMap[p.product_type] || 'bg-gray-50 text-gray-600 border-gray-200';

                        const confidenceLabel = {
                          exact: 'exato', ilike: 'ilike', prefix: 'prefixo',
                          name: 'nome', alias: 'alias',
                        }[p.match_confidence] || 'novo';

                        const hasType = !!(p.product_type && String(p.product_type).trim());
                        const willCreateNew = !p.exists_in_db;
                        // SWAP: produto-troca (recomendação tática de substituir A por B).
                        // Sinalizado pela pré-análise via `is_swap_candidate` ou pela
                        // própria classificação `product_type='Swap'`. UI usa o ícone 🔄
                        // e exibe os ativos envolvidos para deixar a operação explícita.
                        const isSwap = !!(
                          p.is_swap_candidate
                          || String(p.product_type || '').toLowerCase() === 'swap'
                        );
                        const swapTickers = Array.isArray(p.underlying_tickers)
                          ? p.underlying_tickers.filter(Boolean)
                          : [];

                        const deep = p.deep_info || {};
                        const hasDeep = Object.values(deep).some(v => v && (typeof v !== 'object' || (Array.isArray(v) && v.length)));

                        return (
                          <div
                            key={pi}
                            className={`border rounded-lg transition-colors ${
                              p.selected ? 'border-primary/30 bg-card' : 'border-gray-200 bg-gray-50 opacity-60'
                            }`}
                          >
                            <div className="flex items-center gap-2 p-3">
                              <button
                                className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 ${
                                  p.selected ? 'bg-primary border-primary text-white' : 'bg-white border-gray-300'
                                }`}
                                onClick={() => toggleProductSelection(mi, pi)}
                                title={p.selected ? 'Excluir produto' : 'Incluir produto'}
                              >
                                {p.selected && <CheckCircle className="w-3 h-3" />}
                              </button>

                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                {p.ticker && (
                                  <span className="font-bold text-sm text-foreground">{p.ticker}</span>
                                )}
                                {p.name && p.name !== p.ticker && (
                                  <span className="text-sm text-muted truncate">{p.name}</span>
                                )}
                              </div>

                              {hasType ? (
                                <span
                                  className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${typeColor}`}
                                  title={`Tipo do produto: ${p.product_type}`}
                                >
                                  {p.product_type}
                                </span>
                              ) : (
                                <span
                                  className="text-[10px] font-semibold px-2 py-0.5 rounded border bg-red-50 text-red-700 border-red-200"
                                  title="Tipo não foi identificado pela leitura. Edite o produto após o upload para definir."
                                >
                                  Tipo não identificado
                                </span>
                              )}

                              {p._fromVisionSearch && (
                                <span className="text-[10px] text-indigo-600" title="Encontrado via busca visual">
                                  <Search className="w-3 h-3 inline" />
                                </span>
                              )}

                              <button
                                className="text-muted hover:text-foreground flex-shrink-0"
                                onClick={() => toggleProductExpansion(mi, pi)}
                                title={p._expanded ? 'Recolher' : 'Ver detalhes'}
                              >
                                {p._expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                              </button>

                              <button
                                className="text-muted hover:text-red-600 flex-shrink-0"
                                onClick={() => removeProduct(mi, pi)}
                                title="Remover"
                              >
                                <X className="w-4 h-4" />
                              </button>
                            </div>

                            {/* Faixa de DESTINO: deixa explícito se vai criar produto novo
                                ou vincular a um existente. Permite ao usuário corrigir
                                um match equivocado (ex.: POP de MYPK3 batendo na ação MYPK3,
                                ou Troca PETR4↔VALE3 batendo na ação PETR4). */}
                            {p.selected && (
                              willCreateNew ? (
                                isSwap ? (
                                  <div className="border-t border-border/50 px-3 py-2 bg-rose-50/70 flex items-center gap-2 text-xs flex-wrap">
                                    <span className="text-base leading-none flex-shrink-0" aria-hidden>🔄</span>
                                    <span className="text-rose-800">
                                      Vai <strong>criar produto-swap novo</strong>
                                      {swapTickers.length >= 2 && (
                                        <> agrupando <strong>{swapTickers.join(' ↔ ')}</strong></>
                                      )}
                                      . O material <strong>NÃO</strong> será vinculado às fichas individuais
                                      desses ativos — fica apenas na ficha do produto-swap.
                                    </span>
                                    {p.rejected_match_reason && (
                                      <span className="text-rose-700/80 italic ml-1" title={p.rejected_match_reason}>
                                        (match com ativo individual descartado)
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                <div className="border-t border-border/50 px-3 py-2 bg-emerald-50/60 flex items-center gap-2 text-xs">
                                  <PlusCircle className="w-3.5 h-3.5 text-emerald-700 flex-shrink-0" />
                                  <span className="text-emerald-800">
                                    {p.force_new
                                      ? <>Vai <strong>criar produto novo</strong> (você corrigiu o match anterior).</>
                                      : <>Vai <strong>criar produto novo</strong> em sua base.</>}
                                  </span>
                                  {p.rejected_match_reason && (
                                    <span className="text-emerald-700/80 italic ml-1" title={p.rejected_match_reason}>
                                      (match com produto existente foi descartado por divergência de tipo)
                                    </span>
                                  )}
                                </div>
                                )
                              ) : (
                                <div className="border-t border-border/50 px-3 py-2 bg-blue-50/70 flex items-center gap-2 text-xs flex-wrap">
                                  <Link2 className="w-3.5 h-3.5 text-blue-700 flex-shrink-0" />
                                  <span className="text-blue-800">
                                    Vai <strong>vincular ao produto existente</strong>{' '}
                                    «<strong>{p.existing_product_name || p.name}</strong>
                                    {p.existing_product_ticker ? <> ({p.existing_product_ticker})</> : null}»
                                    {p.existing_product_type && (
                                      <span className="text-blue-700/80"> — tipo {p.existing_product_type}</span>
                                    )}
                                    .
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => forceCreateNew(mi, pi)}
                                    className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded border border-blue-300 bg-white text-blue-800 hover:bg-blue-100 text-[11px] font-medium"
                                    title="Não é o mesmo produto — criar um produto novo em vez de vincular"
                                  >
                                    <PlusCircle className="w-3 h-3" /> Criar novo em vez disso
                                  </button>
                                </div>
                              )
                            )}

                            {p._expanded && (
                              <div className="border-t border-border/50 p-3 bg-gray-50/60 space-y-2 text-xs">
                                {[
                                  ['investment_thesis', 'Tese de investimento', 'textarea'],
                                  ['expected_return', 'Retorno esperado', 'input'],
                                  ['investment_term', 'Prazo', 'input'],
                                  ['main_risk', 'Risco principal', 'input'],
                                  ['issuer_or_manager', 'Emissor / Gestora', 'input'],
                                  ['rating', 'Rating', 'input'],
                                  ['minimum_investment', 'Aplicação mínima', 'input'],
                                  ['liquidity', 'Liquidez', 'input'],
                                ].map(([key, label, kind]) => (
                                  <div key={key} className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-3">
                                    <label className="sm:w-40 text-muted font-medium sm:pt-1 flex-shrink-0">{label}</label>
                                    {kind === 'textarea' ? (
                                      <textarea
                                        className="flex-1 px-2 py-1 border border-border rounded bg-white focus:outline-none focus:ring-1 focus:ring-primary/30 text-foreground resize-y"
                                        rows={2}
                                        value={deep[key] ?? ''}
                                        placeholder="—"
                                        onChange={(e) => updateProductKeyInfo(mi, pi, key, e.target.value)}
                                      />
                                    ) : (
                                      <input
                                        type="text"
                                        className="flex-1 px-2 py-1 border border-border rounded bg-white focus:outline-none focus:ring-1 focus:ring-primary/30 text-foreground"
                                        value={deep[key] ?? ''}
                                        placeholder="—"
                                        onChange={(e) => updateProductKeyInfo(mi, pi, key, e.target.value)}
                                      />
                                    )}
                                  </div>
                                ))}

                                <div className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-3">
                                  <label className="sm:w-40 text-muted font-medium sm:pt-1 flex-shrink-0">Destaques</label>
                                  <textarea
                                    className="flex-1 px-2 py-1 border border-border rounded bg-white focus:outline-none focus:ring-1 focus:ring-primary/30 text-foreground resize-y"
                                    rows={2}
                                    placeholder="Um destaque por linha"
                                    value={Array.isArray(deep.additional_highlights) ? deep.additional_highlights.join('\n') : (deep.additional_highlights || '')}
                                    onChange={(e) => updateProductKeyInfo(
                                      mi, pi, 'additional_highlights',
                                      e.target.value.split('\n').map(s => s.trim()).filter(Boolean)
                                    )}
                                  />
                                </div>

                                {!hasDeep && (
                                  <p className="text-[11px] text-muted italic">
                                    Nenhuma informação aprofundada foi extraída automaticamente. Você pode preencher manualmente os campos acima.
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-muted italic">Nenhum produto identificado automaticamente.</p>
                  )}

                  <div className="pt-2 border-t border-border/50 space-y-2">
                    <div className="flex gap-2">
                      <input
                        id={manualInputId}
                        type="text"
                        placeholder="Adicionar manualmente (ex: XPML11 ou nome)..."
                        className="flex-1 px-3 py-1.5 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            addManualProduct(mi, e.target.value);
                            e.target.value = '';
                          }
                        }}
                      />
                      <button
                        className="px-3 py-1.5 text-xs bg-primary/10 text-primary rounded-lg hover:bg-primary/20 transition-colors font-medium"
                        onClick={() => {
                          const el = document.getElementById(manualInputId);
                          if (el) { addManualProduct(mi, el.value); el.value = ''; }
                        }}
                      >
                        Adicionar
                      </button>
                    </div>

                    <div className="flex gap-2">
                      <input
                        id={missingInputId}
                        type="text"
                        placeholder="Produto não detectado no documento (descreva)..."
                        className="flex-1 px-3 py-1.5 text-xs bg-card border border-indigo-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-200"
                        disabled={mat._searchingMissing}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !mat._searchingMissing) {
                            searchMissingProduct(mi, e.target.value);
                            e.target.value = '';
                          }
                        }}
                      />
                      <button
                        className="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1"
                        disabled={mat._searchingMissing}
                        onClick={() => {
                          const el = document.getElementById(missingInputId);
                          if (el && el.value.trim()) {
                            searchMissingProduct(mi, el.value);
                            el.value = '';
                          }
                        }}
                      >
                        {mat._searchingMissing ? (
                          <><Loader2 className="w-3 h-3 animate-spin" /> Buscando...</>
                        ) : (
                          <><Search className="w-3 h-3" /> Buscar produto faltante</>
                        )}
                      </button>
                    </div>

                    {mat._missingNotFound && (
                      <div className="text-xs bg-amber-50 border border-amber-200 rounded-lg p-2 flex items-start gap-2 text-amber-700">
                        <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <div className="flex-1">
                          Produto não encontrado no material. Deseja adicioná-lo manualmente?
                          <button
                            className="ml-2 underline hover:text-amber-900 font-medium"
                            onClick={() => {
                              const el = document.getElementById(manualInputId);
                              if (el) el.focus();
                              setAnalysisResults(prev => prev.map((m, idx) =>
                                idx === mi ? { ...m, _missingNotFound: false } : m
                              ));
                            }}
                          >
                            Adicionar manualmente
                          </button>
                        </div>
                      </div>
                    )}

                    <p className="text-[11px] text-muted">
                      <span className="text-amber-600 font-medium">Novo</span> = produto será criado automaticamente.{' '}
                      <span className="text-primary font-medium">✓ Base</span> = produto já existe no cadastro.
                    </p>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        <div className="flex gap-3 pt-2">
          <Button variant="secondary" onClick={() => setStep(2)} className="flex-1" disabled={confirming}>
            Voltar
          </Button>
          <Button
            onClick={handleConfirmAndQueue}
            disabled={confirming || totalSelected === 0}
            className="flex-1"
          >
            {confirming ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Confirmando...
              </>
            ) : (
              <>
                <CheckCircle className="w-4 h-4" />
                Confirmar e Processar ({totalSelected} produto{totalSelected !== 1 ? 's' : ''})
              </>
            )}
          </Button>
        </div>
      </motion.div>
    );
  };

  const stepLabels = ['Selecionar Arquivo', 'Configurar Detalhes', 'Confirmar Produtos'];

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-4 mb-8">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
                            ${step >= s ? 'bg-primary text-white' : 'bg-border text-muted'}`}>
              {step > s ? <CheckCircle className="w-4 h-4" /> : s}
            </div>
            {s < 3 && (
              <div className={`w-12 h-0.5 ml-2 ${step > s ? 'bg-primary' : 'bg-border'}`} />
            )}
          </div>
        ))}
        <div className="flex-1" />
        <span className="text-xs text-muted">{stepLabels[step - 1]}</span>
      </div>

      <div className="bg-card rounded-xl border border-border p-8 shadow-sm">
        <AnimatePresence mode="wait">
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
        </AnimatePresence>
      </div>

      {showQueue && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-card rounded-xl border border-border p-6 shadow-sm"
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-foreground flex items-center gap-2">
              <Loader2 className={`w-4 h-4 ${queueItems.some(q => q.status === 'processing') ? 'animate-spin text-primary' : 'text-muted'}`} />
              Fila de Processamento
            </h3>
            <button
              onClick={() => setShowQueue(false)}
              className="text-xs text-muted hover:text-foreground"
            >
              Ocultar
            </button>
          </div>
          {renderQueueMonitor()}
        </motion.div>
      )}
      {confirmDialog}
    </div>
  );
}
