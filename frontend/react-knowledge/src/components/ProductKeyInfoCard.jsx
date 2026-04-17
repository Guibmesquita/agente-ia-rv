import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronRight, Plus, X, History, Pencil, Check, Loader, Sparkles } from 'lucide-react';
import { productsAPI } from '../services/api';
import { useToast } from './Toast';

const TEXT_FIELDS = [
  { key: 'investment_thesis', label: 'Tese de investimento', multiline: true, placeholder: 'Por que esse ativo? Qual a tese?' },
  { key: 'expected_return', label: 'Retorno esperado', multiline: false, placeholder: 'Ex.: CDI + 3% a.a., 12% a.a.' },
  { key: 'investment_term', label: 'Prazo / horizonte', multiline: false, placeholder: 'Ex.: 5 anos, longo prazo' },
  { key: 'main_risk', label: 'Principal risco', multiline: true, placeholder: 'O risco mais relevante para o investidor' },
  { key: 'issuer_or_manager', label: 'Emissor / Gestor', multiline: false, placeholder: 'Nome do emissor ou gestora' },
  { key: 'rating', label: 'Rating', multiline: false, placeholder: 'Ex.: AAA, brAAA' },
  { key: 'minimum_investment', label: 'Investimento mínimo', multiline: false, placeholder: 'Ex.: R$ 1.000,00' },
  { key: 'liquidity', label: 'Liquidez', multiline: false, placeholder: 'Ex.: D+0, D+30, sem liquidez' },
];

const IDENTITY_FIELDS = [
  { key: 'cnpj', label: 'CNPJ', placeholder: '00.000.000/0001-00' },
  { key: 'underlying_ticker', label: 'Ativo subjacente', placeholder: 'Ex.: PETR4' },
];

function parseKeyInfo(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    const v = JSON.parse(raw);
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}

function FieldEditor({ field, value, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');
  const [saving, setSaving] = useState(false);

  const handleStart = () => {
    setDraft(value || '');
    setEditing(true);
  };
  const handleCancel = () => {
    setDraft(value || '');
    setEditing(false);
  };
  const handleSave = async () => {
    if ((draft || '').trim() === (value || '').trim()) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(field.key, draft.trim());
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const Input = field.multiline ? 'textarea' : 'input';

  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-muted uppercase tracking-wide">
        {field.label}
      </label>
      {editing ? (
        <div className="flex gap-2">
          <Input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={field.placeholder}
            rows={field.multiline ? 3 : undefined}
            className={`flex-1 px-3 py-2 text-sm bg-card border border-primary rounded-input
                       text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20
                       ${field.multiline ? 'resize-none' : ''}`}
            onKeyDown={(e) => {
              if (e.key === 'Escape') handleCancel();
              else if (e.key === 'Enter' && !field.multiline) handleSave();
            }}
          />
          <div className="flex flex-col gap-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="p-2 bg-success text-white rounded-btn hover:bg-success/90 disabled:opacity-50"
            >
              {saving ? <Loader className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            </button>
            <button
              onClick={handleCancel}
              disabled={saving}
              className="p-2 bg-border text-muted rounded-btn hover:bg-border/80"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      ) : (
        <div
          onClick={handleStart}
          className={`group flex items-start gap-2 px-3 py-2 rounded-input cursor-pointer
                     hover:bg-border/30 transition-colors min-h-[2.5rem]
                     ${!value ? 'italic text-muted' : 'text-foreground'}`}
        >
          <span className={`flex-1 text-sm ${field.multiline ? 'whitespace-pre-wrap' : ''}`}>
            {value || `Adicionar ${field.label.toLowerCase()}…`}
          </span>
          <Pencil className="w-4 h-4 text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      )}
    </div>
  );
}

function HighlightsEditor({ highlights, onChange }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const list = Array.isArray(highlights) ? highlights : [];

  const handleAdd = async () => {
    const v = draft.trim();
    if (!v) {
      setAdding(false);
      setDraft('');
      return;
    }
    setSaving(true);
    try {
      await onChange([...list, v]);
      setDraft('');
      setAdding(false);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (idx) => {
    const next = list.filter((_, i) => i !== idx);
    // Para remover, fazemos PUT do produto inteiro (PATCH é apenas merge aditivo).
    await onChange(next, { replace: true });
  };

  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-muted uppercase tracking-wide">
        Destaques adicionais
      </label>
      <div className="space-y-1.5">
        {list.length === 0 && !adding && (
          <p className="text-sm italic text-muted px-3 py-2">Nenhum destaque cadastrado.</p>
        )}
        {list.map((h, idx) => (
          <div
            key={idx}
            className="group flex items-start gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-input"
          >
            <span className="text-amber-700 mt-0.5">•</span>
            <span className="flex-1 text-sm text-foreground whitespace-pre-wrap">{h}</span>
            <button
              type="button"
              onClick={() => handleRemove(idx)}
              className="p-1 text-amber-700 opacity-0 group-hover:opacity-100 hover:text-red-600 transition-opacity"
              title="Remover destaque"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
        {adding ? (
          <div className="flex gap-2">
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Novo destaque…"
              className="flex-1 px-3 py-2 text-sm bg-card border border-primary rounded-input
                         text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setAdding(false);
                  setDraft('');
                } else if (e.key === 'Enter') {
                  handleAdd();
                }
              }}
            />
            <button
              onClick={handleAdd}
              disabled={saving}
              className="p-2 bg-success text-white rounded-btn hover:bg-success/90 disabled:opacity-50"
            >
              {saving ? <Loader className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            </button>
            <button
              onClick={() => { setAdding(false); setDraft(''); }}
              disabled={saving}
              className="p-2 bg-border text-muted rounded-btn hover:bg-border/80"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 text-sm text-primary hover:text-primary/80 px-3 py-1"
          >
            <Plus className="w-4 h-4" />
            Adicionar destaque
          </button>
        )}
      </div>
    </div>
  );
}

function HistoryPanel({ history }) {
  const [open, setOpen] = useState(false);
  const items = Array.isArray(history) ? history : [];
  if (items.length === 0) return null;

  return (
    <div className="border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm text-muted hover:text-foreground transition-colors"
      >
        {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <History className="w-4 h-4" />
        Histórico de extrações ({items.length})
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1.5">
              {items.slice().reverse().map((h, idx) => (
                <div
                  key={idx}
                  className="text-xs px-3 py-2 bg-muted/10 border border-border rounded-input"
                >
                  <div className="flex justify-between gap-2 mb-1">
                    <span className="font-medium text-foreground">{h.field}</span>
                    <span className="text-muted">
                      {h.material_id ? `material #${h.material_id}` : 'edição manual'}
                      {h.extracted_at ? ` · ${new Date(h.extracted_at).toLocaleString('pt-BR')}` : ''}
                    </span>
                  </div>
                  <div className="text-muted whitespace-pre-wrap">{String(h.value || '')}</div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ProductKeyInfoCard({ product, onUpdated }) {
  const { addToast } = useToast();
  const [extracting, setExtracting] = useState(false);
  const keyInfo = useMemo(() => parseKeyInfo(product?.key_info), [product?.key_info]);
  const history = keyInfo.key_info_history;
  const hasAnyValue = useMemo(() => {
    const fieldKeys = [...TEXT_FIELDS, ...IDENTITY_FIELDS].map((f) => f.key);
    const anyText = fieldKeys.some((k) => {
      const v = keyInfo[k];
      return typeof v === 'string' && v.trim().length > 0;
    });
    const anyHighlight = Array.isArray(keyInfo.additional_highlights)
      && keyInfo.additional_highlights.length > 0;
    return anyText || anyHighlight;
  }, [keyInfo]);

  const handleAutoExtract = async () => {
    setExtracting(true);
    try {
      const result = await productsAPI.autoExtractKeyInfo(product.id);
      if (result.success && result.changed_fields?.length > 0) {
        addToast(`${result.changed_fields.length} campo(s) preenchido(s) automaticamente`, 'success');
        if (onUpdated) await onUpdated();
      } else if (result.success && result.fields_extracted?.length > 0) {
        addToast('Informações já estavam preenchidas — nenhum campo novo atualizado', 'info');
      } else if (result.success) {
        addToast('Nenhuma informação encontrada nos documentos', 'info');
      } else {
        addToast(result.message || 'Não foi possível extrair informações', 'warning');
      }
    } catch (err) {
      addToast(`Erro na extração: ${err.message}`, 'error');
    } finally {
      setExtracting(false);
    }
  };

  const handleFieldSave = async (field, value) => {
    try {
      await productsAPI.updateKeyInfo(product.id, { [field]: value });
      addToast('Campo atualizado e reindexado para o agente', 'success');
      if (onUpdated) await onUpdated();
    } catch (err) {
      addToast(`Erro ao salvar: ${err.message}`, 'error');
      throw err;
    }
  };

  const handleHighlightsChange = async (newList, opts = {}) => {
    try {
      if (opts.replace) {
        // Substitui a lista inteira via PUT (campos extras de key_info preservados)
        const merged = { ...keyInfo, additional_highlights: newList };
        // Remove o histórico de dentro do JSON para que ele seja preservado pelo backend
        // (o backend salva o JSON inteiro tal como recebido).
        await productsAPI.update(product.id, { key_info: JSON.stringify(merged) });
      } else {
        await productsAPI.updateKeyInfo(product.id, { additional_highlights: newList.slice(keyInfo.additional_highlights?.length || 0) });
      }
      addToast('Destaques atualizados e reindexados', 'success');
      if (onUpdated) await onUpdated();
    } catch (err) {
      addToast(`Erro ao salvar destaques: ${err.message}`, 'error');
      throw err;
    }
  };

  return (
    <div className="bg-card rounded-card border border-border p-6 space-y-4">
      <div className="flex items-start gap-2 pb-2 border-b border-border">
        <Sparkles className="w-5 h-5 text-primary mt-0.5" />
        <div className="flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-semibold text-foreground">Informações estratégicas</h3>
            <button
              type="button"
              onClick={handleAutoExtract}
              disabled={extracting}
              title="Extrair campos automaticamente a partir dos documentos do produto"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                         bg-primary/10 text-primary border border-primary/30 rounded-btn
                         hover:bg-primary/20 disabled:opacity-50 disabled:cursor-not-allowed
                         transition-colors"
            >
              {extracting
                ? <Loader className="w-3.5 h-3.5 animate-spin" />
                : <Sparkles className="w-3.5 h-3.5" />}
              {extracting ? 'Extraindo…' : 'Extrair automaticamente'}
            </button>
          </div>
          <p className="text-xs text-muted mt-0.5">
            Campos extraídos automaticamente dos materiais e/ou editados manualmente.
            São indexados na base do agente Stevan e usados em respostas sobre este produto,
            mesmo que ele não esteja no Comitê SVN.
          </p>
        </div>
      </div>

      {!hasAnyValue && (
        <div className="bg-muted/10 border border-dashed border-border rounded-input p-4 text-sm text-muted">
          <strong className="text-foreground">Nenhuma informação estratégica preenchida ainda.</strong>
          <p className="mt-1">
            Faça o upload de um material via <em>Upload Inteligente</em> para que tese,
            retorno esperado, prazo, risco e demais campos sejam extraídos automaticamente —
            ou preencha manualmente os campos abaixo. Tudo é indexado para o agente Stevan.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {TEXT_FIELDS.map((f) => (
          <div key={f.key} className={f.multiline ? 'md:col-span-2' : ''}>
            <FieldEditor field={f} value={keyInfo[f.key]} onSave={handleFieldSave} />
          </div>
        ))}
      </div>

      <HighlightsEditor
        highlights={keyInfo.additional_highlights}
        onChange={handleHighlightsChange}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        {IDENTITY_FIELDS.map((f) => (
          <FieldEditor key={f.key} field={f} value={keyInfo[f.key]} onSave={handleFieldSave} />
        ))}
      </div>

      <HistoryPanel history={history} />
    </div>
  );
}
