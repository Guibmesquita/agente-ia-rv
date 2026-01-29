import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export default function FilterBar({ filters, onFilterChange, filterOptions }) {
  const [showMore, setShowMore] = useState(false);
  const [showCustomDates, setShowCustomDates] = useState(false);

  const periods = [
    { value: '7d', label: 'Ultimos 7 dias' },
    { value: '30d', label: 'Ultimos 30 dias' },
    { value: '90d', label: 'Ultimos 90 dias' },
    { value: '365d', label: 'Ultimo ano' },
    { value: 'custom', label: 'Personalizado' },
  ];

  const handlePeriodChange = (value) => {
    if (value === 'custom') {
      setShowCustomDates(true);
      onFilterChange({ ...filters, period: value });
    } else {
      setShowCustomDates(false);
      onFilterChange({ ...filters, period: value, start_date: null, end_date: null });
    }
  };

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card mb-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-muted uppercase">Periodo</label>
          <select
            value={filters.period}
            onChange={(e) => handlePeriodChange(e.target.value)}
            className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm min-w-[160px] focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            {periods.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        <AnimatePresence>
          {showCustomDates && (
            <>
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 'auto' }}
                exit={{ opacity: 0, width: 0 }}
                className="flex flex-col gap-1"
              >
                <label className="text-xs font-semibold text-muted uppercase">Data Inicio</label>
                <input
                  type="date"
                  value={filters.start_date || ''}
                  onChange={(e) => onFilterChange({ ...filters, start_date: e.target.value })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </motion.div>
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 'auto' }}
                exit={{ opacity: 0, width: 0 }}
                className="flex flex-col gap-1"
              >
                <label className="text-xs font-semibold text-muted uppercase">Data Fim</label>
                <input
                  type="date"
                  value={filters.end_date || ''}
                  onChange={(e) => onFilterChange({ ...filters, end_date: e.target.value })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </motion.div>
            </>
          )}
        </AnimatePresence>

        <button
          onClick={() => setShowMore(!showMore)}
          className={`flex items-center gap-2 px-4 py-2.5 border rounded-lg text-sm transition-colors ${
            showMore ? 'bg-primary text-white border-primary' : 'bg-white text-muted border-border hover:bg-primary hover:text-white hover:border-primary'
          }`}
        >
          <svg className={`w-4 h-4 transition-transform ${showMore ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
          Mais Filtros
        </button>
      </div>

      <AnimatePresence>
        {showMore && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mt-4 pt-4 border-t border-border"
          >
            <div className="flex flex-wrap gap-4">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-muted uppercase">Macro Area</label>
                <select
                  value={filters.macro_area || ''}
                  onChange={(e) => onFilterChange({ ...filters, macro_area: e.target.value || null })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm min-w-[160px] focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Todas</option>
                  {filterOptions?.macro_areas?.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-muted uppercase">Unidade</label>
                <select
                  value={filters.unidade || ''}
                  onChange={(e) => onFilterChange({ ...filters, unidade: e.target.value || null })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm min-w-[160px] focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Todas</option>
                  {filterOptions?.unidades?.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-muted uppercase">Broker</label>
                <select
                  value={filters.broker || ''}
                  onChange={(e) => onFilterChange({ ...filters, broker: e.target.value || null })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm min-w-[160px] focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Todos</option>
                  {filterOptions?.brokers?.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-xs font-semibold text-muted uppercase">Equipe</label>
                <select
                  value={filters.equipe || ''}
                  onChange={(e) => onFilterChange({ ...filters, equipe: e.target.value || null })}
                  className="px-3 py-2.5 bg-white border border-border rounded-lg text-sm min-w-[160px] focus:outline-none focus:ring-2 focus:ring-primary/20"
                >
                  <option value="">Todas</option>
                  {filterOptions?.equipes?.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
