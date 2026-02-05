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

const statusIcons = {
  new: 'M12 6v6m0 0v6m0-6h6m-6 0H6',
  open: 'M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z',
  in_progress: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
  solved: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z'
};

function StatusCard({ status, count, delay }) {
  const color = statusColors[status] || '#8b4513';
  const label = statusLabels[status] || status;
  const icon = statusIcons[status] || statusIcons.new;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.3 }}
      whileHover={{ scale: 1.02, y: -2 }}
      className="bg-gradient-to-br from-background to-card rounded-xl p-4 border border-border shadow-sm hover:shadow-md transition-all cursor-default"
    >
      <div className="flex items-center gap-3">
        <div 
          className="w-10 h-10 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${color}20` }}
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
            {count}
          </motion.div>
          <div className="text-xs text-muted font-medium">{label}</div>
        </div>
      </div>
    </motion.div>
  );
}

export default function TicketStatusDonut({ data }) {
  if (!data || !data.by_status || data.by_status.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-gradient-to-br from-card to-background rounded-2xl p-6 border border-border shadow-sm"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500/20 to-amber-500/10 flex items-center justify-center">
            <svg className="w-5 h-5 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-foreground">Distribuição de Chamados por Status</h3>
          <InfoTooltip text="Visualização da distribuição dos chamados por status atual." />
        </div>
        <div className="flex items-center justify-center h-64 text-muted">
          <div className="text-center">
            <svg className="w-16 h-16 mx-auto mb-4 text-border" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            <p>Sem dados de chamados no período</p>
          </div>
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
        borderColor: '#ffffff',
        borderWidth: 3,
        hoverOffset: 12,
        hoverBorderWidth: 0,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '65%',
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: 'rgba(0,0,0,0.8)',
        padding: 12,
        cornerRadius: 8,
        titleFont: { size: 14, weight: 'bold' },
        bodyFont: { size: 13 },
        callbacks: {
          label: (context) => {
            const total = values.reduce((a, b) => a + b, 0);
            const percentage = ((context.parsed / total) * 100).toFixed(1);
            return `${context.parsed} chamados (${percentage}%)`;
          },
        },
      },
    },
    animation: {
      animateScale: true,
      animateRotate: true,
    },
  };

  const total = data.summary?.total_tickets || values.reduce((a, b) => a + b, 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-gradient-to-br from-card to-background rounded-2xl p-6 border border-border shadow-sm hover:shadow-md transition-shadow"
    >
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500/20 to-amber-500/10 flex items-center justify-center">
          <svg className="w-5 h-5 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-foreground">Distribuição de Chamados por Status</h3>
        <InfoTooltip text="Visualização da distribuição dos chamados por status atual. Permite identificar gargalos no atendimento." />
      </div>
      
      <div className="flex flex-col lg:flex-row items-center gap-8">
        <div className="relative w-56 h-56 lg:w-64 lg:h-64 flex-shrink-0">
          <Doughnut data={chartData} options={options} />
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <motion.span 
              className="text-4xl lg:text-5xl font-bold text-foreground"
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.3, type: 'spring' }}
            >
              {total}
            </motion.span>
            <span className="text-sm text-muted font-medium">Total</span>
          </div>
        </div>
        
        <div className="w-full grid grid-cols-2 gap-3">
          <StatusCard status="new" count={data.summary?.new || 0} delay={0.1} />
          <StatusCard status="open" count={data.summary?.open || 0} delay={0.15} />
          <StatusCard status="in_progress" count={data.summary?.in_progress || 0} delay={0.2} />
          <StatusCard status="solved" count={data.summary?.solved || 0} delay={0.25} />
        </div>
      </div>
    </motion.div>
  );
}
