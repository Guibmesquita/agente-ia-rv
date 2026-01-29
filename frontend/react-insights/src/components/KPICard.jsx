import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

export default function KPICard({ title, value, subtitle, icon, tooltip, color = 'primary' }) {
  const colorClasses = {
    primary: 'bg-primary/10 text-primary',
    success: 'bg-green-100 text-green-600',
    warning: 'bg-yellow-100 text-yellow-600',
    danger: 'bg-red-100 text-red-600',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-xl border border-border p-5 shadow-card"
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center">
            <span className="text-sm text-muted font-medium">{title}</span>
            {tooltip && <InfoTooltip text={tooltip} />}
          </div>
          <div className="mt-2 text-3xl font-bold text-foreground">{value}</div>
          {subtitle && (
            <p className="mt-1 text-sm text-muted">{subtitle}</p>
          )}
        </div>
        {icon && (
          <div className={`p-3 rounded-lg ${colorClasses[color]}`}>
            {icon}
          </div>
        )}
      </div>
    </motion.div>
  );
}
