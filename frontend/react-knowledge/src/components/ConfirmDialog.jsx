import { useState, useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, AlertTriangle } from 'lucide-react';

function ConfirmDialog({ open, onClose, onConfirm, title, message, confirmText, cancelText, type }) {
  const confirmBtnRef = useRef(null);
  const isDanger = type === 'danger';

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  useEffect(() => {
    if (open && confirmBtnRef.current) {
      confirmBtnRef.current.focus();
    }
  }, [open]);

  if (!open) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[10001]"
            style={{ background: 'rgba(0, 0, 0, 0.5)' }}
          />
          <div
            className="fixed inset-0 z-[10002] flex items-center justify-center"
            onClick={onClose}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -10 }}
              transition={{ duration: 0.3 }}
              style={{
                background: 'white',
                borderRadius: '16px',
                boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
                maxWidth: '400px',
                width: '90%',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ padding: '24px 24px 0', display: 'flex', alignItems: 'center', gap: '16px' }}>
                <div
                  style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    background: isDanger ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)',
                    color: isDanger ? '#ef4444' : '#f59e0b',
                  }}
                >
                  {isDanger
                    ? <X style={{ width: '24px', height: '24px' }} />
                    : <AlertTriangle style={{ width: '24px', height: '24px' }} />
                  }
                </div>
              </div>
              <div style={{ padding: '24px' }}>
                <div style={{ fontSize: '18px', fontWeight: 600, color: '#1f2937', marginBottom: '8px' }}>
                  {title}
                </div>
                <div style={{ fontSize: '14px', color: '#6b7280', lineHeight: 1.5 }}>
                  {message}
                </div>
              </div>
              <div style={{ padding: '0 24px 24px', display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                <button
                  onClick={onClose}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: 500,
                    cursor: 'pointer',
                    minWidth: '100px',
                    background: '#f3f4f6',
                    border: '1px solid #e5e7eb',
                    color: '#374151',
                  }}
                >
                  {cancelText}
                </button>
                <button
                  ref={confirmBtnRef}
                  onClick={onConfirm}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '8px',
                    fontSize: '14px',
                    fontWeight: 500,
                    cursor: 'pointer',
                    minWidth: '100px',
                    background: isDanger ? '#AC3631' : '#772B21',
                    border: 'none',
                    color: 'white',
                  }}
                >
                  {confirmText}
                </button>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}

export function useConfirmDialog() {
  const [state, setState] = useState({ open: false, options: {}, resolve: null });

  const openConfirm = useCallback((options = {}) => {
    return new Promise((resolve) => {
      setState({ open: true, options, resolve });
    });
  }, []);

  const handleClose = useCallback(() => {
    setState((prev) => {
      if (prev.resolve) prev.resolve(false);
      return { open: false, options: {}, resolve: null };
    });
  }, []);

  const handleConfirm = useCallback(() => {
    setState((prev) => {
      if (prev.resolve) prev.resolve(true);
      return { open: false, options: {}, resolve: null };
    });
  }, []);

  const confirmDialog = (
    <ConfirmDialog
      open={state.open}
      onClose={handleClose}
      onConfirm={handleConfirm}
      title={state.options.title || 'Confirmar ação'}
      message={state.options.message || 'Tem certeza que deseja continuar?'}
      confirmText={state.options.confirmText || 'Confirmar'}
      cancelText={state.options.cancelText || 'Cancelar'}
      type={state.options.type || 'warning'}
    />
  );

  return { confirmDialog, openConfirm };
}
