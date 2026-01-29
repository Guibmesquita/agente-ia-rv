export default function FilterBar({ filters, onFilterChange }) {
  const periods = [
    { value: '7d', label: '7 dias' },
    { value: '30d', label: '30 dias' },
    { value: '90d', label: '90 dias' },
    { value: '365d', label: '1 ano' },
  ];

  return (
    <div className="flex flex-wrap items-center gap-4 mb-6">
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-muted">Período:</label>
        <select
          value={filters.period}
          onChange={(e) => onFilterChange({ ...filters, period: e.target.value })}
          className="px-3 py-2 bg-white border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
        >
          {periods.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
