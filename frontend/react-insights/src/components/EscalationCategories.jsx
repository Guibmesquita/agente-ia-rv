import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

const categoryLabels = {
  out_of_scope: 'Fora do Escopo',
  info_not_found: 'Informação não Encontrada',
  technical_complexity: 'Complexidade Técnica',
  commercial_request: 'Solicitação Comercial',
  explicit_human_request: 'Solicitou Humano',
  emotional_friction: 'Fricção Emocional',
  stalled_conversation: 'Conversa Estagnada',
  recurring_issue: 'Problema Recorrente',
  sensitive_topic: 'Tema Sensível',
  investment_decision: 'Decisão de Investimento',
  other: 'Outros'
};

const categoryColors = {
  out_of_scope: '#8b4513',
  info_not_found: '#dc7f37',
  technical_complexity: '#6b8e23',
  commercial_request: '#b8860b',
  explicit_human_request: '#cd853f',
  emotional_friction: '#556b2f',
  stalled_conversation: '#d2691e',
  recurring_issue: '#8fbc8f',
  sensitive_topic: '#a0522d',
  investment_decision: '#9acd32',
  other: '#daa520'
};

const categoryIcons = {
  out_of_scope: 'M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636',
  info_not_found: 'M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  technical_complexity: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z',
  commercial_request: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  explicit_human_request: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z',
  emotional_friction: 'M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  stalled_conversation: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
  recurring_issue: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
  sensitive_topic: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
  investment_decision: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
  other: 'M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z'
};

function CategoryBar({ category, count, maxCount, index, total }) {
  const color = categoryColors[category] || '#8b4513';
  const label = categoryLabels[category] || category;
  const icon = categoryIcons[category] || categoryIcons.other;
  const percentage = ((count / total) * 100).toFixed(1);
  const barWidth = (count / maxCount) * 100;

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.05 }}
      className="group"
    >
      <div className="flex items-center gap-3 mb-2">
        <div 
          className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-transform group-hover:scale-110"
          style={{ backgroundColor: `${color}20` }}
        >
          <svg className="w-4 h-4" style={{ color }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={icon} />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm font-medium text-foreground truncate">{label}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-sm font-bold text-foreground">{count}</span>
              <span className="text-xs text-muted">({percentage}%)</span>
            </div>
          </div>
          <div className="h-3 bg-border/30 rounded-full overflow-hidden">
            <motion.div
              className="h-full rounded-full transition-all"
              style={{ backgroundColor: color }}
              initial={{ width: 0 }}
              animate={{ width: `${barWidth}%` }}
              transition={{ delay: index * 0.05 + 0.2, duration: 0.5, ease: 'easeOut' }}
            />
          </div>
        </div>
      </div>
    </motion.div>
  );
}

export default function EscalationCategories({ data }) {
  if (!data || data.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-gradient-to-br from-card to-background rounded-2xl p-6 border border-border shadow-sm"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500/20 to-orange-500/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-foreground">Categorias de Escalação</h3>
          <InfoTooltip text="Motivos pelos quais conversas foram escaladas para atendimento humano." />
        </div>
        <div className="flex items-center justify-center h-48 text-muted">
          <div className="text-center">
            <svg className="w-16 h-16 mx-auto mb-4 text-border" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            <p>Sem dados de escalação no período</p>
          </div>
        </div>
      </motion.div>
    );
  }

  const sortedData = [...data].sort((a, b) => b.count - a.count);
  const total = sortedData.reduce((sum, item) => sum + item.count, 0);
  const maxCount = Math.max(...sortedData.map(item => item.count));

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-card to-background rounded-2xl p-6 border border-border shadow-sm hover:shadow-md transition-shadow"
    >
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-red-500/20 to-orange-500/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-foreground">Categorias de Escalação</h3>
          <InfoTooltip text="Motivos pelos quais conversas foram escaladas para atendimento humano. Ajuda a identificar gaps no conhecimento da IA." />
        </div>
        <div className="flex items-center gap-2 bg-background px-3 py-1.5 rounded-full border border-border">
          <span className="text-sm font-bold text-foreground">{total}</span>
          <span className="text-xs text-muted">escalações</span>
        </div>
      </div>
      
      <div className="space-y-4">
        {sortedData.map((item, index) => (
          <CategoryBar
            key={item.category}
            category={item.category}
            count={item.count}
            maxCount={maxCount}
            index={index}
            total={total}
          />
        ))}
      </div>
    </motion.div>
  );
}
