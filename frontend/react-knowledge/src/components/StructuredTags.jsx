import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Info, ChevronDown, ChevronUp } from 'lucide-react';

const TAG_SECTIONS = [
  {
    id: 'contexto',
    title: 'Contexto de Uso',
    description: 'Em qual momento o broker vai usar este material?',
    color: 'blue',
    tags: [
      { value: 'abordagem', label: 'Abordagem', tip: 'Primeiro contato com o cliente' },
      { value: 'fechamento', label: 'Fechamento', tip: 'Momento de fechar a venda' },
      { value: 'objecao', label: 'Objeção', tip: 'Responder dúvidas e resistências' },
      { value: 'follow-up', label: 'Follow-up', tip: 'Acompanhamento pós-contato' },
      { value: 'renovacao', label: 'Renovação', tip: 'Renovar ou manter posição' },
      { value: 'rebalanceamento', label: 'Rebalanceamento', tip: 'Ajuste de carteira' },
    ]
  },
  {
    id: 'perfil',
    title: 'Perfil do Cliente',
    description: 'Para qual perfil de investidor este material é indicado?',
    color: 'green',
    tags: [
      { value: 'conservador', label: 'Conservador', tip: 'Baixa tolerância a risco' },
      { value: 'moderado', label: 'Moderado', tip: 'Aceita risco equilibrado' },
      { value: 'arrojado', label: 'Arrojado', tip: 'Alta tolerância a risco' },
      { value: 'institucional', label: 'Institucional', tip: 'Fundos e empresas' },
      { value: 'pf', label: 'Pessoa Física', tip: 'Investidor individual' },
      { value: 'pj', label: 'Pessoa Jurídica', tip: 'Empresas e CNPJs' },
    ]
  },
  {
    id: 'momento',
    title: 'Momento de Mercado',
    description: 'Em qual cenário econômico este material é mais relevante?',
    color: 'amber',
    tags: [
      { value: 'alta', label: 'Mercado em Alta', tip: 'Bull market, otimismo' },
      { value: 'baixa', label: 'Mercado em Baixa', tip: 'Bear market, cautela' },
      { value: 'volatilidade', label: 'Alta Volatilidade', tip: 'Incerteza e oscilações' },
      { value: 'selic-alta', label: 'Selic Alta', tip: 'Juros elevados' },
      { value: 'selic-baixa', label: 'Selic Baixa', tip: 'Juros baixos' },
      { value: 'dolar-forte', label: 'Dólar Forte', tip: 'Moeda valorizada' },
    ]
  },
  {
    id: 'informacao',
    title: 'Tipo de Informação',
    description: 'Qual tipo de dado este material contém?',
    color: 'purple',
    tags: [
      { value: 'indicadores', label: 'Indicadores', tip: 'Números e métricas' },
      { value: 'historico', label: 'Histórico', tip: 'Dados passados' },
      { value: 'comparativo', label: 'Comparativo', tip: 'Versus concorrentes' },
      { value: 'projecao', label: 'Projeção', tip: 'Estimativas futuras' },
      { value: 'risco', label: 'Risco', tip: 'Análise de riscos' },
      { value: 'estrategia', label: 'Estratégia', tip: 'Tese e argumentos' },
    ]
  },
];

const colorClasses = {
  blue: {
    bg: 'bg-blue-50',
    border: 'border-blue-200',
    text: 'text-blue-700',
    hover: 'hover:bg-blue-100',
    selected: 'bg-blue-500 text-white border-blue-500',
    chip: 'bg-blue-100 text-blue-700',
  },
  green: {
    bg: 'bg-green-50',
    border: 'border-green-200',
    text: 'text-green-700',
    hover: 'hover:bg-green-100',
    selected: 'bg-green-500 text-white border-green-500',
    chip: 'bg-green-100 text-green-700',
  },
  amber: {
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    text: 'text-amber-700',
    hover: 'hover:bg-amber-100',
    selected: 'bg-amber-500 text-white border-amber-500',
    chip: 'bg-amber-100 text-amber-700',
  },
  purple: {
    bg: 'bg-purple-50',
    border: 'border-purple-200',
    text: 'text-purple-700',
    hover: 'hover:bg-purple-100',
    selected: 'bg-purple-500 text-white border-purple-500',
    chip: 'bg-purple-100 text-purple-700',
  },
};

export function StructuredTags({ value = [], onChange }) {
  const [expandedSections, setExpandedSections] = useState(['contexto']);
  const [hoveredTag, setHoveredTag] = useState(null);

  const toggleSection = (sectionId) => {
    if (expandedSections.includes(sectionId)) {
      setExpandedSections(expandedSections.filter(id => id !== sectionId));
    } else {
      setExpandedSections([...expandedSections, sectionId]);
    }
  };

  const toggleTag = (tagValue) => {
    if (value.includes(tagValue)) {
      onChange(value.filter(v => v !== tagValue));
    } else {
      onChange([...value, tagValue]);
    }
  };

  const removeTag = (tagValue) => {
    onChange(value.filter(v => v !== tagValue));
  };

  const getTagInfo = (tagValue) => {
    for (const section of TAG_SECTIONS) {
      const tag = section.tags.find(t => t.value === tagValue);
      if (tag) return { ...tag, section };
    }
    return null;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <label className="block text-sm font-medium text-foreground">
          Tags (opcional)
        </label>
        <div className="relative group">
          <Info className="w-4 h-4 text-muted cursor-help" />
          <div className="absolute left-0 bottom-6 w-72 p-2 bg-slate-800 text-white text-xs rounded-lg 
                          opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
            As tags ajudam o agente a encontrar o material certo para cada situação.
            Quanto mais precisas as tags, melhor será a busca.
          </div>
        </div>
      </div>

      {value.length > 0 && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="flex flex-wrap gap-2 p-3 bg-slate-50 rounded-lg border border-slate-200"
        >
          <span className="text-xs text-muted self-center">Selecionadas:</span>
          {value.map(tagValue => {
            const info = getTagInfo(tagValue);
            if (!info) return null;
            const colors = colorClasses[info.section.color];
            return (
              <motion.span
                key={tagValue}
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${colors.chip}`}
              >
                {info.label}
                <button
                  onClick={() => removeTag(tagValue)}
                  className="ml-0.5 hover:opacity-70"
                >
                  <X className="w-3 h-3" />
                </button>
              </motion.span>
            );
          })}
        </motion.div>
      )}

      <div className="space-y-2">
        {TAG_SECTIONS.map((section) => {
          const colors = colorClasses[section.color];
          const isExpanded = expandedSections.includes(section.id);
          const selectedCount = section.tags.filter(t => value.includes(t.value)).length;
          
          return (
            <div key={section.id} className={`rounded-lg border ${colors.border} overflow-hidden`}>
              <button
                type="button"
                onClick={() => toggleSection(section.id)}
                className={`w-full flex items-center justify-between px-4 py-3 ${colors.bg} ${colors.text}`}
              >
                <div className="flex items-center gap-3">
                  <span className="font-medium">{section.title}</span>
                  {selectedCount > 0 && (
                    <span className={`px-2 py-0.5 rounded-full text-xs ${colors.chip}`}>
                      {selectedCount} selecionada{selectedCount > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {isExpanded ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>
              
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="p-4 bg-white">
                      <p className="text-xs text-muted mb-3">{section.description}</p>
                      <div className="flex flex-wrap gap-2">
                        {section.tags.map((tag) => {
                          const isSelected = value.includes(tag.value);
                          const isHovered = hoveredTag === tag.value;
                          
                          return (
                            <div key={tag.value} className="relative">
                              <motion.button
                                type="button"
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.98 }}
                                onClick={() => toggleTag(tag.value)}
                                onMouseEnter={() => setHoveredTag(tag.value)}
                                onMouseLeave={() => setHoveredTag(null)}
                                className={`px-3 py-1.5 rounded-full border text-xs font-medium transition-all
                                           ${isSelected 
                                             ? colors.selected
                                             : `bg-white ${colors.border} ${colors.text} ${colors.hover}`}`}
                              >
                                {tag.label}
                              </motion.button>
                              
                              {isHovered && (
                                <motion.div
                                  initial={{ opacity: 0, y: 5 }}
                                  animate={{ opacity: 1, y: 0 }}
                                  className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 
                                             px-2.5 py-1.5 bg-slate-800 text-white text-xs rounded-lg 
                                             shadow-lg z-50 whitespace-nowrap pointer-events-none"
                                >
                                  {tag.tip}
                                  <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 
                                                  border-l-4 border-r-4 border-t-4 
                                                  border-l-transparent border-r-transparent border-t-slate-800" />
                                </motion.div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { TAG_SECTIONS };
