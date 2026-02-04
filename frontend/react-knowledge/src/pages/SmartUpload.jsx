import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, FileText, CheckCircle, ArrowRight, Sparkles, Info, AlertCircle } from 'lucide-react';
import { materialsAPI } from '../services/api';
import { FileUpload } from '../components/FileUpload';
import { Button } from '../components/Button';
import { ProductAutocomplete } from '../components/ProductAutocomplete';
import { MaterialCategories } from '../components/MaterialCategories';
import { StructuredTags } from '../components/StructuredTags';
import { useToast } from '../components/Toast';

export function SmartUpload() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const logRef = useRef(null);
  
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [materialCategories, setMaterialCategories] = useState([]);
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [tags, setTags] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadComplete, setUploadComplete] = useState(false);
  const [currentPage, setCurrentPage] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState(null);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const addLog = (message, type = 'info') => {
    const time = new Date().toLocaleTimeString('pt-BR');
    setLogs(prev => [...prev, { time, message, type }]);
  };

  const handleUploadWithProduct = async () => {
    setUploading(true);
    setStep(3);
    setLogs([]);
    setHasError(false);
    setStats(null);

    try {
      const materialData = {
        material_type: materialCategories[0] || 'outro',
        material_categories: materialCategories,
        name: file.name.replace('.pdf', ''),
        tags: tags,
        valid_from: validFrom || null,
        valid_until: validUntil || null,
      };

      addLog('Iniciando upload para produto selecionado...', 'info');
      
      let progress = 0;
      const progressInterval = setInterval(() => {
        progress += Math.random() * 15;
        if (progress > 90) progress = 90;
        setUploadProgress(Math.round(progress));
        addLog(`Processando... ${Math.round(progress)}%`, 'info');
      }, 1500);

      const material = await materialsAPI.create(selectedProduct.id, materialData);
      addLog('Material criado, enviando PDF...', 'info');
      
      await materialsAPI.uploadPDF(selectedProduct.id, material.id, file);
      
      clearInterval(progressInterval);
      setUploadProgress(100);
      setUploadComplete(true);
      setUploading(false);
      setStats({ blocks_created: 0, auto_approved: 0, pending_review: 0, products_matched: [selectedProduct.ticker || selectedProduct.name] });
      addLog('Documento processado com sucesso!', 'success');
      addToast('Documento processado com sucesso!', 'success');
    } catch (err) {
      addLog(`Erro: ${err.message}`, 'error');
      addToast(`Erro: ${err.message}`, 'error');
      setHasError(true);
      setUploading(false);
    }
  };

  const handleUploadStreaming = async () => {
    setUploading(true);
    setStep(3);
    setLogs([]);
    setHasError(false);
    setStats(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('material_type', materialCategories[0] || 'outro');
      formData.append('material_categories', JSON.stringify(materialCategories));
      formData.append('name', file.name.replace('.pdf', ''));
      formData.append('tags', JSON.stringify(tags));
      if (validFrom) formData.append('valid_from', validFrom);
      if (validUntil) formData.append('valid_until', validUntil);

      addLog('Iniciando upload do arquivo...', 'info');

      const response = await fetch('/api/products/smart-upload-stream', {
        method: 'POST',
        body: formData,
        credentials: 'include'
      });

      if (!response.ok) {
        throw new Error(`Erro ${response.status}: ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';

        for (const eventBlock of events) {
          const lines = eventBlock.split('\n');
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const event = JSON.parse(line.slice(6));
                
                if (event.type === 'start') {
                  addLog(event.message, 'info');
                } else if (event.type === 'progress') {
                  setCurrentPage(event.current);
                  setTotalPages(event.total);
                  setUploadProgress(event.percent);
                } else if (event.type === 'log') {
                  addLog(event.message, event.log_type || 'info');
                } else if (event.type === 'complete') {
                  setUploadProgress(100);
                  setUploadComplete(true);
                  setUploading(false);
                  setStats(event.stats);
                  addLog(event.message, 'success');
                  addToast('Documento processado com sucesso!', 'success');
                } else if (event.type === 'error') {
                  setHasError(true);
                  setUploading(false);
                  addLog(event.message, 'error');
                  addToast(event.message, 'error');
                }
              } catch (e) {
              }
            }
          }
        }
      }
    } catch (err) {
      addLog(`Erro: ${err.message}`, 'error');
      addToast(`Erro: ${err.message}`, 'error');
      setHasError(true);
      setUploading(false);
    }
  };

  const handleUpload = async () => {
    if (!file || materialCategories.length === 0) {
      addToast('Selecione um arquivo e pelo menos uma categoria', 'warning');
      return;
    }

    if (selectedProduct) {
      await handleUploadWithProduct();
    } else {
      await handleUploadStreaming();
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

  const renderStep1 = () => (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      <div className="text-center mb-8">
        <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
          <Upload className="w-8 h-8 text-primary" />
        </div>
        <h2 className="text-xl font-semibold text-foreground">Upload Inteligente</h2>
        <p className="text-muted mt-2">
          Envie um PDF e a IA extrairá automaticamente os blocos de conhecimento
        </p>
      </div>

      <FileUpload onFileSelect={setFile} />

      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex justify-end"
        >
          <Button onClick={() => setStep(2)}>
            Continuar
            <ArrowRight className="w-4 h-4" />
          </Button>
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
      <div className="flex items-center gap-3 p-4 bg-primary/5 rounded-card border border-primary/20">
        <FileText className="w-6 h-6 text-primary" />
        <div className="flex-1">
          <p className="font-medium text-foreground">{file?.name}</p>
          <p className="text-sm text-muted">{(file?.size / 1024 / 1024).toFixed(2)} MB</p>
        </div>
        <button
          onClick={() => { setFile(null); setStep(1); }}
          className="text-sm text-primary hover:underline"
        >
          Trocar arquivo
        </button>
      </div>

      <MaterialCategories 
        value={materialCategories} 
        onChange={setMaterialCategories} 
      />

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Produto Relacionado (opcional)
        </label>
        <ProductAutocomplete
          value={selectedProduct}
          onChange={setSelectedProduct}
          placeholder="Digite para buscar um produto..."
        />
        <div className="flex items-start gap-2 mt-2 p-3 bg-blue-50 rounded-card border border-blue-200">
          <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-blue-700">
            Se não selecionar um produto, a IA identificará automaticamente os produtos mencionados em cada página do documento.
          </p>
        </div>
      </div>

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
              className="w-full px-4 py-3 bg-card border border-border rounded-input
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
              className="w-full px-4 py-3 bg-card border border-border rounded-input
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

      <div className="flex gap-3 pt-4">
        <Button variant="secondary" onClick={() => setStep(1)} className="flex-1">
          Voltar
        </Button>
        <Button 
          onClick={handleUpload} 
          disabled={materialCategories.length === 0}
          className="flex-1"
        >
          <Sparkles className="w-4 h-4" />
          Processar Automaticamente
        </Button>
      </div>
    </motion.div>
  );

  const renderStep3 = () => (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="space-y-6"
    >
      {!uploadComplete ? (
        <>
          <div className="bg-card border border-border rounded-xl p-6">
            <div className="flex justify-between items-center mb-4">
              <h4 className="font-semibold text-foreground flex items-center gap-2">
                {hasError ? (
                  <AlertCircle className="w-5 h-5 text-red-500" />
                ) : (
                  <Sparkles className="w-5 h-5 text-primary animate-pulse" />
                )}
                {hasError ? 'Erro no processamento' : 'Processando documento...'}
              </h4>
              <span className="text-2xl font-bold text-primary">{uploadProgress}%</span>
            </div>
            
            <div className="h-3 bg-border rounded-full overflow-hidden mb-4">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${uploadProgress}%` }}
                className={`h-full rounded-full transition-all ${hasError ? 'bg-red-500' : 'bg-gradient-to-r from-primary to-indigo-400'}`}
              />
            </div>
            
            <div className="flex justify-between text-sm text-muted mb-4">
              <span>{currentPage} de {totalPages} páginas</span>
              <span>
                {stats ? (
                  <>Blocos: <span className="text-green-600 font-semibold">{stats.blocks_created}</span></>
                ) : 'Aguardando...'}
              </span>
            </div>

            <div 
              ref={logRef}
              className="bg-slate-800 text-slate-300 rounded-lg p-4 font-mono text-xs max-h-48 overflow-y-auto"
              style={{ display: logs.length > 0 ? 'block' : 'none' }}
            >
              {logs.map((log, i) => (
                <div key={i} className={`mb-1 ${getLogColor(log.type)}`}>
                  [{log.time}] {log.message}
                </div>
              ))}
            </div>
          </div>

          {hasError && (
            <div className="flex gap-3 justify-center">
              <Button variant="secondary" onClick={() => {
                setStep(2);
                setUploading(false);
                setUploadProgress(0);
                setLogs([]);
                setHasError(false);
              }}>
                Tentar Novamente
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="text-center py-4">
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="w-20 h-20 rounded-full bg-green-100 flex items-center justify-center mx-auto mb-6"
            >
              <CheckCircle className="w-10 h-10 text-green-600" />
            </motion.div>
            <h2 className="text-xl font-semibold text-foreground mb-2">
              Documento processado!
            </h2>
            <p className="text-muted mb-4">
              {selectedProduct 
                ? 'Os blocos foram extraídos e estão prontos para revisão'
                : 'Os blocos foram extraídos e vinculados automaticamente aos produtos identificados'}
            </p>
          </div>

          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-blue-600">{stats.blocks_created}</div>
                <div className="text-xs text-blue-700">Blocos Criados</div>
              </div>
              <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-green-600">{stats.auto_approved}</div>
                <div className="text-xs text-green-700">Auto-Aprovados</div>
              </div>
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-yellow-600">{stats.pending_review}</div>
                <div className="text-xs text-yellow-700">Para Revisão</div>
              </div>
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-purple-600">{stats.products_matched?.length || 0}</div>
                <div className="text-xs text-purple-700">Produtos</div>
              </div>
            </div>
          )}

          <div 
            ref={logRef}
            className="bg-slate-800 text-slate-300 rounded-lg p-4 font-mono text-xs max-h-36 overflow-y-auto mb-6"
          >
            {logs.map((log, i) => (
              <div key={i} className={`mb-1 ${getLogColor(log.type)}`}>
                [{log.time}] {log.message}
              </div>
            ))}
          </div>

          <div className="flex gap-3 justify-center">
            <Button variant="secondary" onClick={() => {
              setStep(1);
              setFile(null);
              setMaterialCategories([]);
              setTags([]);
              setSelectedProduct(null);
              setUploadComplete(false);
              setUploadProgress(0);
              setLogs([]);
              setStats(null);
              setCurrentPage(0);
              setTotalPages(0);
            }}>
              Novo Upload
            </Button>
            {selectedProduct ? (
              <Button onClick={() => navigate(`/product/${selectedProduct.id}`)}>
                Ver Produto
              </Button>
            ) : (
              <Button onClick={() => navigate('/review')}>
                Ver Fila de Revisão
              </Button>
            )}
          </div>
        </>
      )}
    </motion.div>
  );

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
                            ${step >= s ? 'bg-primary text-white' : 'bg-border text-muted'}`}>
              {s}
            </div>
            {s < 3 && (
              <div className={`w-16 h-0.5 ml-2 ${step > s ? 'bg-primary' : 'bg-border'}`} />
            )}
          </div>
        ))}
      </div>

      <div className="bg-card rounded-card border border-border p-8 shadow-card">
        <AnimatePresence mode="wait">
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
        </AnimatePresence>
      </div>
    </div>
  );
}
