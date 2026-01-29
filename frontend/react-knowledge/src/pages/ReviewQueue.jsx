import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ClipboardCheck, Check, X, Edit, AlertTriangle, RefreshCw } from 'lucide-react';
import { reviewAPI } from '../services/api';
import { Button } from '../components/Button';
import { Modal } from '../components/Modal';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { EmptyState } from '../components/EmptyState';
import { useToast } from '../components/Toast';

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

  const loadItems = async () => {
    try {
      setLoading(true);
      const data = await reviewAPI.listPending();
      setItems(data.pending_items || data.items || data || []);
    } catch (err) {
      addToast('Erro ao carregar itens pendentes', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadItems();
  }, []);

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
    setEditContent(item.content || '');
    setShowEditModal(true);
  };

  const openRejectModal = (item) => {
    setSelectedItem(item);
    setShowRejectModal(true);
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
        <Button variant="secondary" onClick={loadItems} disabled={loading}>
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Atualizar
        </Button>
      </div>

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
          <p className="text-sm text-muted">
            {items.length} item{items.length !== 1 ? 's' : ''} aguardando revisão
          </p>

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

                      {item.title && (
                        <h3 className="font-medium text-foreground mb-2">{item.title}</h3>
                      )}

                      <p className="text-sm text-muted mb-3 whitespace-pre-wrap line-clamp-4">
                        {item.content}
                      </p>

                      {item.reason && (
                        <div className="flex items-center gap-2 text-sm text-warning mb-3">
                          <AlertTriangle className="w-4 h-4" />
                          Motivo: {item.reason}
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

      <Modal
        open={showEditModal}
        onClose={() => setShowEditModal(false)}
        title="Editar e Aprovar"
        size="lg"
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Edite o conteúdo abaixo e aprove o item:
          </p>
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={10}
            className="w-full px-3 py-2 bg-card border border-border rounded-input
                       text-foreground resize-none focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <div className="flex gap-3">
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
