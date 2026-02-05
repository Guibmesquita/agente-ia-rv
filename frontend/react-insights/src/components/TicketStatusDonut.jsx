import { motion } from 'framer-motion';
import { Doughnut } from 'react-chartjs-2';
import InfoTooltip from './InfoTooltip';

const statusLabels = {
  new: 'Novos',
  open: 'Abertos',
  in_progress: 'Em Andamento',
  solved: 'Resolvidos',
  pending: 'Pendentes',
  closed: 'Fechados'
};

const statusColors = {
  new: '#dc7f37',
  open: '#8b4513',
  in_progress: '#b8860b',
  solved: '#6b8e23',
  pending: '#cd853f',
  closed: '#556b2f'
};

export default function TicketStatusDonut({ data }) {
  if (!data || !data.by_status || data.by_status.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-card rounded-2xl p-6 border border-border"
      >
        <div className="flex items-center gap-2 mb-4">
          <h3 className="text-lg font-semibold text-foreground">Distribuição de Chamados por Status</h3>
          <InfoTooltip text="Visualização da distribuição dos chamados por status atual." />
        </div>
        <div className="flex items-center justify-center h-64 text-muted">
          Sem dados de chamados no período
        </div>
      </motion.div>
    );
  }

  const labels = data.by_status.map(item => statusLabels[item.status] || item.status);
  const values = data.by_status.map(item => item.count);
  const colors = data.by_status.map(item => statusColors[item.status] || '#8b4513');

  const chartData = {
    labels,
    datasets: [
      {
        data: values,
        backgroundColor: colors,
        borderColor: colors.map(c => c),
        borderWidth: 2,
        hoverOffset: 8,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '60%',
    plugins: {
      legend: {
        position: 'right',
        labels: {
          padding: 20,
          usePointStyle: true,
          pointStyle: 'circle',
          font: { size: 12 },
        },
      },
      tooltip: {
        callbacks: {
          label: (context) => {
            const total = values.reduce((a, b) => a + b, 0);
            const percentage = ((context.parsed / total) * 100).toFixed(1);
            return `${context.label}: ${context.parsed} (${percentage}%)`;
          },
        },
      },
    },
  };

  const total = data.summary?.total_tickets || values.reduce((a, b) => a + b, 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl p-6 border border-border"
    >
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-lg font-semibold text-foreground">Distribuição de Chamados por Status</h3>
        <InfoTooltip text="Visualização da distribuição dos chamados por status atual. Permite identificar gargalos no atendimento." />
      </div>
      
      <div className="flex items-center gap-8">
        <div className="relative w-64 h-64">
          <Doughnut data={chartData} options={options} />
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-3xl font-bold text-foreground">{total}</span>
            <span className="text-sm text-muted">Total</span>
          </div>
        </div>
        
        <div className="flex-1 grid grid-cols-2 gap-4">
          <div className="bg-background rounded-xl p-4 border border-border">
            <div className="text-2xl font-bold text-primary">{data.summary?.new || 0}</div>
            <div className="text-sm text-muted">Novos</div>
          </div>
          <div className="bg-background rounded-xl p-4 border border-border">
            <div className="text-2xl font-bold text-warning">{data.summary?.open || 0}</div>
            <div className="text-sm text-muted">Abertos</div>
          </div>
          <div className="bg-background rounded-xl p-4 border border-border">
            <div className="text-2xl font-bold text-accent">{data.summary?.in_progress || 0}</div>
            <div className="text-sm text-muted">Em Andamento</div>
          </div>
          <div className="bg-background rounded-xl p-4 border border-border">
            <div className="text-2xl font-bold text-success">{data.summary?.solved || 0}</div>
            <div className="text-sm text-muted">Resolvidos</div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
