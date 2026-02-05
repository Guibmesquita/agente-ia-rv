import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

function GaugeCircle({ value, maxValue, label, color, unit = 'min' }) {
  const percentage = Math.min((value / maxValue) * 100, 100);
  const circumference = 2 * Math.PI * 45;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;
  
  return (
    <div className="flex flex-col items-center">
      <div className="relative w-32 h-32">
        <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r="45"
            fill="none"
            stroke="currentColor"
            strokeWidth="8"
            className="text-border"
          />
          <motion.circle
            cx="50"
            cy="50"
            r="45"
            fill="none"
            stroke={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset }}
            transition={{ duration: 1, ease: 'easeOut' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-bold text-foreground">{value.toFixed(1)}</span>
          <span className="text-xs text-muted">{unit}</span>
        </div>
      </div>
      <span className="mt-2 text-sm font-medium text-muted text-center">{label}</span>
    </div>
  );
}

export default function TimeGauges({ avgResponseTime, avgResolutionTime }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl p-6 border border-border"
    >
      <div className="flex items-center gap-2 mb-6">
        <h3 className="text-lg font-semibold text-foreground">Tempos de Atendimento</h3>
        <InfoTooltip text="Tempo médio de primeira resposta e tempo total até resolução do chamado." />
      </div>
      
      <div className="flex justify-around items-center gap-8">
        <GaugeCircle
          value={avgResponseTime || 0}
          maxValue={60}
          label="Primeira Resposta"
          color="#8b4513"
        />
        <GaugeCircle
          value={avgResolutionTime || 0}
          maxValue={120}
          label="Tempo de Conclusão"
          color="#dc7f37"
        />
      </div>
      
      <div className="mt-6 grid grid-cols-2 gap-4">
        <div className="bg-background rounded-xl p-4 border border-border text-center">
          <div className="text-sm text-muted mb-1">Meta Resposta</div>
          <div className="text-lg font-semibold text-foreground">{'< 15 min'}</div>
        </div>
        <div className="bg-background rounded-xl p-4 border border-border text-center">
          <div className="text-sm text-muted mb-1">Meta Resolução</div>
          <div className="text-lg font-semibold text-foreground">{'< 60 min'}</div>
        </div>
      </div>
    </motion.div>
  );
}
