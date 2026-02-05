import { motion } from 'framer-motion';
import { Bar } from 'react-chartjs-2';
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

const categoryColors = [
  '#8b4513', '#dc7f37', '#6b8e23', '#b8860b', '#cd853f',
  '#556b2f', '#d2691e', '#8fbc8f', '#a0522d', '#9acd32', '#daa520'
];

export default function EscalationCategories({ data }) {
  if (!data || data.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-card rounded-2xl p-6 border border-border"
      >
        <div className="flex items-center gap-2 mb-4">
          <h3 className="text-lg font-semibold text-foreground">Categorias de Escalação</h3>
          <InfoTooltip text="Motivos pelos quais conversas foram escaladas para atendimento humano." />
        </div>
        <div className="flex items-center justify-center h-48 text-muted">
          Sem dados de escalação no período
        </div>
      </motion.div>
    );
  }

  const sortedData = [...data].sort((a, b) => b.count - a.count);
  const labels = sortedData.map(item => categoryLabels[item.category] || item.category);
  const values = sortedData.map(item => item.count);

  const chartData = {
    labels,
    datasets: [
      {
        data: values,
        backgroundColor: categoryColors.slice(0, values.length),
        borderRadius: 6,
        barThickness: 24,
      },
    ],
  };

  const options = {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (context) => `${context.parsed.x} chamados`,
        },
      },
    },
    scales: {
      x: {
        beginAtZero: true,
        grid: { color: 'rgba(0,0,0,0.05)' },
        ticks: { precision: 0 },
      },
      y: {
        grid: { display: false },
        ticks: {
          font: { size: 11 },
        },
      },
    },
  };

  const total = values.reduce((a, b) => a + b, 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl p-6 border border-border"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold text-foreground">Categorias de Escalação</h3>
          <InfoTooltip text="Motivos pelos quais conversas foram escaladas para atendimento humano. Ajuda a identificar gaps no conhecimento da IA." />
        </div>
        <span className="text-sm text-muted">{total} escalações totais</span>
      </div>
      
      <div style={{ height: `${Math.max(200, sortedData.length * 40)}px` }}>
        <Bar data={chartData} options={options} />
      </div>
    </motion.div>
  );
}
