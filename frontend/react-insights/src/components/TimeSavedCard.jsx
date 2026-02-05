import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

function MetricCard({ value, label, icon, color, delay }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      whileHover={{ scale: 1.02, y: -2 }}
      className="bg-gradient-to-br from-background to-card rounded-xl p-4 border border-border shadow-sm hover:shadow-md transition-all cursor-default"
    >
      <div className="flex items-center gap-3">
        <div 
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${color}15` }}
        >
          <svg className="w-5 h-5" style={{ color }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
          </svg>
        </div>
        <div>
          <motion.div 
            className="text-2xl font-bold text-foreground"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: delay + 0.2 }}
          >
            {value}
          </motion.div>
          <div className="text-xs text-muted font-medium">{label}</div>
        </div>
      </div>
    </motion.div>
  );
}

export default function TimeSavedCard({ botMetrics }) {
  const {
    bot_resolved_count = 0,
    bot_resolution_rate = 0,
    avg_time_saved_minutes = 0,
    total_conversations = 0
  } = botMetrics || {};

  const totalTimeSaved = bot_resolved_count * avg_time_saved_minutes;
  const hoursEquivalent = (totalTimeSaved / 60).toFixed(1);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-emerald-500/10 via-card to-teal-500/5 rounded-2xl p-6 border border-emerald-500/20 shadow-sm hover:shadow-md transition-shadow"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/30 to-teal-500/20 flex items-center justify-center">
          <svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-foreground">Tempo Economizado pela IA</h3>
        <InfoTooltip text="Estimativa do tempo que a equipe humana economizou com resoluções automáticas pela IA." />
      </div>
      
      <div className="flex items-center justify-center mb-6">
        <div className="relative">
          <motion.div
            className="absolute inset-0 bg-gradient-to-r from-emerald-500/20 to-teal-500/20 rounded-full blur-2xl"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.3, duration: 0.8 }}
          />
          <div className="relative text-center bg-gradient-to-br from-background/80 to-card/50 rounded-2xl px-8 py-6 border border-emerald-500/10">
            <motion.div
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.2, type: 'spring', stiffness: 200 }}
              className="text-5xl lg:text-6xl font-bold bg-gradient-to-r from-emerald-600 to-teal-600 bg-clip-text text-transparent mb-1"
            >
              {hoursEquivalent}h
            </motion.div>
            <div className="text-sm text-muted font-medium">economizadas</div>
            <div className="text-xs text-muted mt-1">({totalTimeSaved.toFixed(0)} minutos)</div>
          </div>
        </div>
      </div>
      
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <MetricCard
          value={bot_resolved_count}
          label="Resolvidos pela IA"
          icon="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
          color="#059669"
          delay={0.1}
        />
        <MetricCard
          value={`${bot_resolution_rate.toFixed(1)}%`}
          label="Taxa de Resolução IA"
          icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
          color="#0d9488"
          delay={0.15}
        />
        <MetricCard
          value={`${avg_time_saved_minutes.toFixed(0)}min`}
          label="Média por Conversa"
          icon="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          color="#0891b2"
          delay={0.2}
        />
      </div>
      
      <motion.div 
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
        className="mt-5 p-4 bg-gradient-to-r from-emerald-500/5 to-teal-500/5 rounded-xl border border-emerald-500/10"
      >
        <div className="flex items-start gap-3 text-sm text-muted">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0 mt-0.5">
            <svg className="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <span>
            A IA resolveu <strong className="text-foreground">{bot_resolved_count}</strong> de{' '}
            <strong className="text-foreground">{total_conversations}</strong> conversas automaticamente,
            liberando a equipe para focar em casos mais complexos.
          </span>
        </div>
      </motion.div>
    </motion.div>
  );
}
