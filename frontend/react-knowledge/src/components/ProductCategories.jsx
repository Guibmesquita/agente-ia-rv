import { useState } from 'react';
import { motion } from 'framer-motion';

const PRODUCT_CATEGORIES = [
  { value: 'FII', label: 'FII' },
  { value: 'FII de Papel', label: 'FII de Papel' },
  { value: 'FII de CRI', label: 'FII de CRI' },
  { value: 'Ação', label: 'Ação' },
  { value: 'COE', label: 'COE' },
  { value: 'Derivativo', label: 'Derivativo' },
  { value: 'Fundo Multimercado', label: 'Fundo Multimercado' },
  { value: 'Renda Fixa', label: 'Renda Fixa' },
  { value: 'Comitê', label: '⭐ Comitê', tooltip: 'Produto com recomendação formal do Comitê de Investimentos da SVN. Ativa regras especiais no agente.' },
];

export function ProductCategories({ value = [], onChange, label = 'Categorias do Produto' }) {
  const [hoveredCat, setHoveredCat] = useState(null);

  const toggle = (cat) => {
    if (value.includes(cat)) {
      onChange(value.filter(v => v !== cat));
    } else {
      onChange([...value, cat]);
    }
  };

  return (
    <div className="space-y-2">
      {label && (
        <label className="block text-sm font-medium text-foreground">{label}</label>
      )}
      <div className="flex flex-wrap gap-2">
        {PRODUCT_CATEGORIES.map((cat) => {
          const isSelected = value.includes(cat.value);
          return (
            <div key={cat.value} className="relative">
              <motion.button
                type="button"
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => toggle(cat.value)}
                onMouseEnter={() => cat.tooltip && setHoveredCat(cat.value)}
                onMouseLeave={() => setHoveredCat(null)}
                className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-all
                  ${isSelected
                    ? 'bg-primary text-white border-primary shadow-sm'
                    : 'bg-card border-border text-foreground hover:border-primary/50 hover:bg-primary/5'}`}
              >
                {cat.label}
              </motion.button>
              {hoveredCat === cat.value && cat.tooltip && (
                <motion.div
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-56 p-2.5
                             bg-slate-800 text-white text-xs rounded-lg shadow-lg z-50
                             pointer-events-none"
                >
                  {cat.tooltip}
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
        <p className="text-xs text-muted">
          Selecionadas: {value.join(', ')}
        </p>
      )}
    </div>
  );
}

export { PRODUCT_CATEGORIES };
