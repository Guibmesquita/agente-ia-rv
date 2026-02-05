import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

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
      className="bg-gradient-to-br from-primary/10 to-success/10 rounded-2xl p-6 border border-primary/20"
    >
      <div className="flex items-center gap-2 mb-6">
        <h3 className="text-lg font-semibold text-foreground">Tempo Economizado pela IA</h3>
        <InfoTooltip text="Estimativa do tempo que a equipe humana economizou com resoluções automáticas pela IA." />
      </div>
      
      <div className="flex items-center justify-center mb-6">
        <div className="text-center">
          <motion.div
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.2, type: 'spring' }}
            className="text-5xl font-bold text-primary mb-2"
          >
            {totalTimeSaved.toFixed(0)}
          </motion.div>
          <div className="text-lg text-muted">minutos economizados</div>
          <div className="text-sm text-muted mt-1">({hoursEquivalent} horas)</div>
        </div>
      </div>
      
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-card rounded-xl p-4 border border-border text-center">
          <div className="text-2xl font-bold text-success">{bot_resolved_count}</div>
          <div className="text-xs text-muted mt-1">Resolvidos pela IA</div>
        </div>
        <div className="bg-card rounded-xl p-4 border border-border text-center">
          <div className="text-2xl font-bold text-primary">{bot_resolution_rate.toFixed(1)}%</div>
          <div className="text-xs text-muted mt-1">Taxa de Resolução IA</div>
        </div>
        <div className="bg-card rounded-xl p-4 border border-border text-center">
          <div className="text-2xl font-bold text-accent">{avg_time_saved_minutes.toFixed(1)}</div>
          <div className="text-xs text-muted mt-1">Média por Conversa (min)</div>
        </div>
      </div>
      
      <div className="mt-6 p-4 bg-card/50 rounded-xl border border-border">
        <div className="flex items-center gap-2 text-sm text-muted">
          <svg className="w-5 h-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span>
            A IA resolveu <strong className="text-foreground">{bot_resolved_count}</strong> de{' '}
            <strong className="text-foreground">{total_conversations}</strong> conversas automaticamente,
            economizando tempo da equipe humana.
          </span>
        </div>
      </div>
    </motion.div>
  );
}
