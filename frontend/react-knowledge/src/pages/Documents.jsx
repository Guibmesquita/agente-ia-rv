import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { FileText, Upload, RefreshCw, Trash2, Search as SearchIcon, Database, AlertCircle, Play } from 'lucide-react';
import { knowledgeAPI } from '../services/api';
import { Button } from '../components/Button';
import { SearchInput } from '../components/SearchInput';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { Modal } from '../components/Modal';
import { FileUpload } from '../components/FileUpload';
import { useToast } from '../components/Toast';
import { useConfirmDialog } from '../components/ConfirmDialog';

const CATEGORIES = [
  'Estratégias',
  'Produtos',
  'Processos',
  'Compliance',
  'Treinamento',
  'FAQ',
  'Outros',
];

export function Documents() {
  const { addToast } = useToast();
  const { confirmDialog, openConfirm } = useConfirmDialog();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadCategory, setUploadCategory] = useState('');
  const [uploadDescription, setUploadDescription] = useState('');
  const [uploading, setUploading] = useState(false);

  const loadDocuments = async () => {
    try {
      setLoading(true);
      const data = await knowledgeAPI.list();
      setDocuments(data.documents || data);
    } catch (err) {
      addToast('Erro ao carregar documentos', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadFile || !uploadTitle || !uploadCategory) {
      addToast('Preencha todos os campos obrigatórios', 'warning');
      return;
    }

    setUploading(true);
    try {
      await knowledgeAPI.upload(uploadFile, uploadTitle, uploadCategory, uploadDescription);
      addToast('Documento enviado para processamento!', 'success');
      setShowUploadModal(false);
      resetUploadForm();
      loadDocuments();
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
    setUploading(false);
  };

  const handleDelete = async (docId) => {
    const confirmed = await openConfirm({
      title: 'Excluir Documento',
      message: 'Tem certeza que deseja excluir este documento? Esta ação não pode ser desfeita.',
      confirmText: 'Excluir',
      type: 'danger',
    });
    if (!confirmed) return;
    try {
      await knowledgeAPI.delete(docId);
      addToast('Documento excluído!', 'success');
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
    }
  };

  const resetUploadForm = () => {
    setUploadFile(null);
    setUploadTitle('');
    setUploadCategory('');
    setUploadDescription('');
  };

  const filteredDocuments = documents.filter((doc) =>
    search === '' ||
    doc.title?.toLowerCase().includes(search.toLowerCase()) ||
    doc.filename?.toLowerCase().includes(search.toLowerCase())
  );

  const pendingDocuments = documents.filter((doc) => !doc.is_indexed);
  const indexedDocuments = documents.filter((doc) => doc.is_indexed);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Documentos</h1>
          <p className="text-muted">Gerencie documentos da base de conhecimento</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={loadDocuments} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </Button>
          <Button onClick={() => setShowUploadModal(true)}>
            <Upload className="w-4 h-4" />
            Novo Documento
          </Button>
        </div>
      </div>

      {!loading && documents.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div className="p-4 bg-card border border-border rounded-xl text-center">
            <div className="text-2xl font-bold text-foreground">{documents.length}</div>
            <div className="text-sm text-muted">Total de Documentos</div>
          </div>
          <div className="p-4 bg-card border border-border rounded-xl text-center">
            <div className="text-2xl font-bold text-green-600">{indexedDocuments.length}</div>
            <div className="text-sm text-muted">Indexados</div>
          </div>
          {pendingDocuments.length > 0 && (
            <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-center">
              <div className="text-2xl font-bold text-amber-600">{pendingDocuments.length}</div>
              <div className="text-sm text-amber-700">Pendentes</div>
            </div>
          )}
        </div>
      )}

      <SearchInput
        value={search}
        onChange={setSearch}
        placeholder="Buscar documentos..."
      />

      {!loading && pendingDocuments.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-4 bg-amber-50 border border-amber-200 rounded-xl"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="font-semibold text-amber-800">
                {pendingDocuments.length} documento{pendingDocuments.length !== 1 ? 's' : ''} pendente{pendingDocuments.length !== 1 ? 's' : ''}
              </h3>
              <p className="text-sm text-amber-700 mt-1">
                Estes documentos não foram processados completamente. Clique em <strong>"Processar"</strong> para tentar novamente ou <strong>"Excluir"</strong> para removê-los.
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {loading ? (
        <div className="py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : filteredDocuments.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="Nenhum documento encontrado"
          description="Adicione documentos para expandir a base de conhecimento da IA"
          action={() => setShowUploadModal(true)}
          actionLabel="Adicionar Documento"
        />
      ) : (
        <>
          <p className="text-sm text-muted">
            {filteredDocuments.length} documento{filteredDocuments.length !== 1 ? 's' : ''}
          </p>

          <div className="space-y-3">
            <AnimatePresence>
              {filteredDocuments.map((doc) => (
                <motion.div
                  key={doc.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, x: -50 }}
                  className="flex items-center gap-4 p-4 bg-card rounded-card border border-border"
                >
                  <div className="p-2 bg-primary/10 rounded-lg">
                    <FileText className="w-6 h-6 text-primary" />
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-foreground truncate">{doc.title}</h3>
                    <div className="flex items-center gap-3 text-sm text-muted">
                      <span>{doc.filename}</span>
                      <span>•</span>
                      <span>{doc.category}</span>
                      <span>•</span>
                      <span>{doc.chunks_count} chunks</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {doc.is_indexed ? (
                      <span className="flex items-center gap-1 text-xs text-success px-2 py-1 bg-green-50 rounded-full">
                        <Database className="w-3 h-3" />
                        Indexado
                      </span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="flex items-center gap-1 text-xs text-amber-700 px-2 py-1 bg-amber-50 border border-amber-200 rounded-full">
                          <AlertCircle className="w-3 h-3" />
                          Pendente
                        </span>
                        {doc.index_error && (
                          <span 
                            className="text-xs text-red-600 max-w-[200px] truncate" 
                            title={doc.index_error}
                          >
                            {doc.index_error.length > 30 ? doc.index_error.substring(0, 30) + '...' : doc.index_error}
                          </span>
                        )}
                      </div>
                    )}
                    
                    {!doc.is_indexed && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => handleReindex(doc.id)}
                        className="text-xs bg-amber-100 hover:bg-amber-200 text-amber-800 border-amber-300"
                        title="Processar documento novamente"
                      >
                        <Play className="w-3 h-3 mr-1" />
                        Processar
                      </Button>
                    )}
                    
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => handleDelete(doc.id)}
                      title="Excluir"
                    >
                      <Trash2 className="w-4 h-4 text-danger" />
                    </Button>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      <Modal
        open={showUploadModal}
        onClose={() => { setShowUploadModal(false); resetUploadForm(); }}
        title="Novo Documento"
        size="md"
      >
        <form onSubmit={handleUpload} className="space-y-4">
          <FileUpload onFileSelect={setUploadFile} />

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Título *
            </label>
            <input
              type="text"
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="Ex: Manual de Estratégias 2026"
              className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Categoria *
            </label>
            <select
              value={uploadCategory}
              onChange={(e) => setUploadCategory(e.target.value)}
              className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground"
            >
              <option value="">Selecione...</option>
              {CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Descrição (opcional)
            </label>
            <textarea
              value={uploadDescription}
              onChange={(e) => setUploadDescription(e.target.value)}
              rows={3}
              placeholder="Breve descrição do conteúdo..."
              className="w-full px-3 py-2 bg-card border border-border rounded-input text-foreground resize-none"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => { setShowUploadModal(false); resetUploadForm(); }}
              className="flex-1"
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              loading={uploading}
              disabled={!uploadFile || !uploadTitle || !uploadCategory}
              className="flex-1"
            >
              Enviar Documento
            </Button>
          </div>
        </form>
      </Modal>
      {confirmDialog}
    </div>
  );
}
