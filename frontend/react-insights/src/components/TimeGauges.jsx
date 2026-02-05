import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

function GaugeCircle({ value, maxValue, label, color, unit = 'min' }) {
  const safeValue = Number(value) || 0;
  const percentage = Math.min((safeValue / maxValue) * 100, 100);
  const circumference = 2 * Math.PI * 45;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;
  
  return (
    <div className="flex flex-col items-center">
      <div className="relative w-40 h-40 lg:w-48 lg:h-48">
        <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
          <defs>
            <linearGradient id={`gradient-${label.replace(/\s/g, '')}`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={color} stopOpacity="0.3" />
              <stop offset="100%" stopColor={color} stopOpacity="0.1" />
            </linearGradient>
          </defs>
          <circle
            cx="50"
            cy="50"
            r="45"
            fill={`url(#gradient-${label.replace(/\s/g, '')})`}
            stroke="currentColor"
            strokeWidth="6"
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
            transition={{ duration: 1.2, ease: 'easeOut' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <motion.span 
            className="text-3xl lg:text-4xl font-bold text-foreground"
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.5 }}
          >
            {safeValue.toFixed(1)}
          </motion.span>
          <span className="text-sm text-muted font-medium">{unit}</span>
        </div>
      </div>
      <span className="mt-3 text-base font-semibold text-foreground text-center">{label}</span>
    </div>
  );
}

export default function TimeGauges({ avgResponseTime, avgResolutionTime }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-card to-background rounded-2xl p-6 border border-border shadow-sm hover:shadow-md transition-shadow"
    >
      <div className="flex items-center gap-2 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 flex items-center justify-center">
          <svg className="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-foreground">Tempos de Atendimento</h3>
        <InfoTooltip text="Tempo médio de primeira resposta e tempo total até resolução do chamado." />
      </div>
      
      <div className="flex justify-around items-center gap-6">
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
    </motion.div>
  );
}
