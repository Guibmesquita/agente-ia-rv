import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

export default function ChartCard({ title, tooltip, children, fullWidth = false }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`bg-white rounded-xl border border-border p-5 shadow-card ${fullWidth ? 'col-span-full' : ''}`}
    >
      <div className="flex items-center mb-4">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {tooltip && <InfoTooltip text={tooltip} />}
      </div>
      <div className="relative">
        {children}
      </div>
    </motion.div>
  );
}
