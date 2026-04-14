import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import './index.css';

import Sidebar from './components/Sidebar';
import KPICard from './components/KPICard';
import ChartCard from './components/ChartCard';
import FilterBar from './components/FilterBar';
import ProductsImageChart from './components/ProductsImageChart';
import CampaignsSummary from './components/CampaignsSummary';
import CategoryRadialChart from './components/CategoryRadialChart';
import AnimatedGauge from './components/AnimatedGauge';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

const API_BASE = '';

function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [filters, setFilters] = useState({ period: '30d' });
  const [filterOptions, setFilterOptions] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [activityData, setActivityData] = useState(null);
  const [categoriesData, setCategoriesData] = useState(null);
  const [productsData, setProductsData] = useState(null);
  const [resolutionData, setResolutionData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const buildQueryString = useCallback(() => {
    const params = new URLSearchParams();
    
    if (filters.period === 'custom') {
      if (filters.start_date) params.append('start_date', filters.start_date);
      if (filters.end_date) params.append('end_date', filters.end_date);
    } else {
      params.append('period', filters.period);
    }
    
    if (filters.macro_area) params.append('macro_area', filters.macro_area);
    if (filters.unidade) params.append('unidade', filters.unidade);
    if (filters.broker) params.append('broker', filters.broker);
    if (filters.equipe) params.append('equipe', filters.equipe);
    
    return params.toString();
  }, [filters]);

  const fetchFilters = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/insights/filters`, { credentials: 'include' });
      if (response.ok) {
        const data = await response.json();
        setFilterOptions(data);
      }
    } catch (err) {
      console.error('Error loading filters:', err);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    const qs = buildQueryString();

    try {
      const [metricsRes, activityRes, categoriesRes, productsRes, resolutionRes] = await Promise.all([
        fetch(`${API_BASE}/api/insights/metrics?${qs}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/insights/activity?${qs}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/insights/categories?${qs}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/insights/products?${qs}`, { credentials: 'include' }),
        fetch(`${API_BASE}/api/insights/resolution?${qs}`, { credentials: 'include' }),
      ]);

      if (!metricsRes.ok) throw new Error('Falha ao carregar metricas');

      const [metricsData, activity, categories, products, resolution] = await Promise.all([
        metricsRes.json(),
        activityRes.json(),
        categoriesRes.json(),
        productsRes.json(),
        resolutionRes.json(),
      ]);

      setMetrics(metricsData);
      setActivityData(activity);
      setCategoriesData(categories);
      setProductsData(products);
      setResolutionData(resolution);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [buildQueryString]);

  useEffect(() => {
    fetchFilters();
  }, [fetchFilters]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const activityChartData = {
    labels: activityData?.labels?.map(d => {
      const date = new Date(d);
      return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
    }) || [],
    datasets: [{
      label: 'Interações',
      data: activityData?.data || [],
      fill: true,
      borderColor: '#772B21',
      backgroundColor: 'rgba(119, 43, 33, 0.1)',
      tension: 0.4,
      pointBackgroundColor: '#772B21',
      pointBorderColor: '#fff',
      pointHoverRadius: 6,
    }]
  };

  const categoriesChartFormatted = categoriesData?.labels?.map((label, index) => ({
    label: label,
    value: categoriesData.data[index],
  })) || [];

  const resolutionChartFormatted = resolutionData?.labels?.map((label, index) => ({
    label: label,
    value: resolutionData.data[index],
  })) || [];

  const productsChartFormatted = productsData?.labels?.map((label, index) => ({
    label: label,
    value: productsData.data[index],
  })) || [];

  if (error) {
    return (
      <div className="flex">
        <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />
        <div className={`${sidebarCollapsed ? 'ml-16' : 'ml-60'} flex-1 min-h-screen bg-background flex items-center justify-center transition-all duration-300`}>
          <div className="text-center p-8">
            <h2 className="text-xl font-semibold text-danger mb-2">Erro ao carregar dados</h2>
            <p className="text-muted">{error}</p>
            <button
              onClick={fetchData}
              className="mt-4 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark"
            >
              Tentar novamente
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex">
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />
      <div className={`${sidebarCollapsed ? 'ml-16' : 'ml-60'} flex-1 min-h-screen bg-background p-6 transition-all duration-300`}>
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-7xl mx-auto"
        >
          <div className="mb-6">
            <h1 className="text-2xl font-bold text-foreground">Insights</h1>
            <p className="text-muted">Dashboard de metricas e analises de desempenho</p>
          </div>

          <FilterBar filters={filters} onFilterChange={setFilters} filterOptions={filterOptions} />

          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                <KPICard
                  title="Conversas (jan. 12h)"
                  value={metrics?.total_interactions?.toLocaleString('pt-BR') || '0'}
                  tooltip="Total de janelas de 12 horas com atividade de mensagens no período selecionado."
                  icon={
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  }
                  color="primary"
                />
                <KPICard
                  title="Assessores Ativos"
                  value={metrics?.active_assessors?.toLocaleString('pt-BR') || '0'}
                  tooltip="Quantidade de assessores únicos que interagiram com o agente IA no período."
                  icon={
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                    </svg>
                  }
                  color="success"
                />
              </div>

              <CampaignsSummary
                totalCampaigns={metrics?.total_campaigns}
                assessorsReached={metrics?.total_assessors_reached}
              />

              <div className="mt-6">
                <ChartCard
                  title="Atividade Diária"
                  tooltip="Série histórica do volume de interações por dia. Permite identificar tendências e picos de atividade."
                  fullWidth
                >
                  <div style={{ height: '280px' }}>
                    <Line
                      data={activityChartData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: { display: false },
                        },
                        scales: {
                          y: {
                            beginAtZero: true,
                            grid: { color: 'rgba(0,0,0,0.05)' },
                            ticks: { precision: 0 },
                          },
                          x: {
                            grid: { display: false },
                          },
                        },
                      }}
                    />
                  </div>
                </ChartCard>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
                <ProductsImageChart
                  data={productsChartFormatted}
                  title="Produtos em Alta"
                  tooltip="Ranking dos produtos/tickers mais mencionados nas conversas. Indica demanda e interesse dos assessores."
                />
                <AnimatedGauge
                  title="Taxa de Resolução IA"
                  percentage={metrics?.ai_resolution_rate || 0}
                  label="Janelas de 12h sem intervenção humana"
                  tooltip="Proporção de janelas de 12h resolvidas pela IA versus as que tiveram intervenção humana."
                />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
                <CategoryRadialChart
                  title="Categorias de Dúvidas"
                  data={categoriesChartFormatted}
                  tooltip="Distribuição das conversas por tipo de assunto. Volumes absolutos de cada categoria."
                />
                <CategoryRadialChart
                  title="IA vs Humanos"
                  data={resolutionChartFormatted}
                  tooltip="Distribuição das janelas de 12h entre resolvidas pela IA e com intervenção humana."
                />
              </div>
            </>
          )}
        </motion.div>
      </div>
    </div>
  );
}

export default App;
