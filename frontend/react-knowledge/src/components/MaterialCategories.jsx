import { useState } from 'react';
import { motion } from 'framer-motion';
import { Info } from 'lucide-react';

const MATERIAL_CATEGORIES = [
  {
    value: 'comite',
    label: 'Comitê',
    tooltip: 'Decisões e teses de comitê de investimentos. Contém recomendações formais da casa.'
  },
  {
    value: 'research',
    label: 'Research',
    tooltip: 'Análises de mercado, setoriais e cenários. Fundamentação técnica para decisões.'
  },
  {
    value: 'one_page',
    label: 'One-Page',
    tooltip: 'Resumo comercial do produto em 1 página. Material de consulta rápida para o broker.'
  },
  {
    value: 'apresentacao',
    label: 'Apresentação',
    tooltip: 'Decks para reuniões com clientes. Slides e argumentos visuais de venda.'
  },
  {
    value: 'taxas',
    label: 'Taxas',
    tooltip: 'Tabelas de taxas e rendimentos. Dados "vivos" com prioridade alta na busca.'
  },
  {
    value: 'campanha',
    label: 'Campanha',
    tooltip: 'Materiais promocionais com prazo. Ofertas e ações comerciais temporárias.'
  },
  {
    value: 'treinamento',
    label: 'Treinamento',
    tooltip: 'Capacitação interna e playbooks. Conhecimento técnico operacional.'
  },
  {
    value: 'faq',
    label: 'FAQ',
    tooltip: 'Perguntas frequentes e objeções. Respostas prontas para dúvidas comuns.'
  },
  {
    value: 'regulatorio',
    label: 'Regulatório',
    tooltip: 'Disclaimers, compliance e regras. Informações obrigatórias e legais.'
  },
  {
    value: 'script',
    label: 'Script',
    tooltip: 'Roteiros de abordagem. Textos prontos para WhatsApp ou reunião.'
  },
];

export function MaterialCategories({ value = [], onChange }) {
  const [hoveredCategory, setHoveredCategory] = useState(null);

  const toggleCategory = (categoryValue) => {
    if (value.includes(categoryValue)) {
      onChange(value.filter(v => v !== categoryValue));
    } else {
      onChange([...value, categoryValue]);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <label className="block text-sm font-medium text-foreground">
          Categorias do Material
        </label>
        <div className="relative group">
          <Info className="w-4 h-4 text-muted cursor-help" />
          <div className="absolute left-0 bottom-6 w-64 p-2 bg-slate-800 text-white text-xs rounded-lg 
                          opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
            Selecione uma ou mais categorias que descrevem o tipo de conteúdo. 
            Isso ajuda o agente a encontrar o material correto.
          </div>
        </div>
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        {MATERIAL_CATEGORIES.map((category) => {
          const isSelected = value.includes(category.value);
          const isHovered = hoveredCategory === category.value;
          
          return (
            <div key={category.value} className="relative">
              <motion.button
                type="button"
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => toggleCategory(category.value)}
                onMouseEnter={() => setHoveredCategory(category.value)}
                onMouseLeave={() => setHoveredCategory(null)}
                className={`w-full px-3 py-2.5 rounded-lg border text-sm font-medium transition-all
                           ${isSelected 
                             ? 'bg-primary text-white border-primary shadow-sm' 
                             : 'bg-card border-border text-foreground hover:border-primary/50 hover:bg-primary/5'}`}
              >
                {category.label}
              </motion.button>
              
              {isHovered && (
                <motion.div
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-52 p-2.5 
                             bg-slate-800 text-white text-xs rounded-lg shadow-lg z-50
                             pointer-events-none"
                >
                  <div className="font-medium mb-1">{category.label}</div>
                  <div className="text-slate-300">{category.tooltip}</div>
                  <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 
                                  border-l-4 border-r-4 border-t-4 
                                  border-l-transparent border-r-transparent border-t-slate-800" />
                </motion.div>
              )}
            </div>
          );
        })}
      </div>
      
      {value.length > 0 && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="flex items-center gap-2 text-xs text-muted"
        >
          <span>Selecionadas:</span>
          <div className="flex flex-wrap gap-1">
            {value.map(v => {
              const cat = MATERIAL_CATEGORIES.find(c => c.value === v);
              return (
                <span key={v} className="px-2 py-0.5 bg-primary/10 text-primary rounded-full">
                  {cat?.label}
                </span>
              );
            })}
          </div>
        </motion.div>
      )}
    </div>
  );
}

export { MATERIAL_CATEGORIES };
