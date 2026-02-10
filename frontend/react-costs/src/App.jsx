import { useState, useEffect, useCallback } from 'react'
import {
  DollarSign, TrendingUp, Cpu, Globe, Mic, FileText, Image,
  Brain, Search, Server, Plus, Pencil, Trash2, X, Check,
  ChevronDown, BarChart3, Loader2, RefreshCw, AlertCircle,
  Settings, Zap, Database
} from 'lucide-react'
import { Line, Doughnut, Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Title, Tooltip, Legend, Filler
} from 'chart.js'

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Title, Tooltip, Legend, Filler
)

const API_BASE = window.location.origin + '/api'

const SERVICE_ICONS = {
  openai: Brain,
  tavily: Globe,
  whisper: Mic,
}

const OPERATION_LABELS = {
  chat_response: 'Resposta do Stevan',
  chat_completion: 'Chat Completion',
  intent_classification: 'Classificação de Intenção',
  conversation_analysis: 'Análise de Conversa',
  escalation_analysis: 'Análise de Escalação',
  document_vision_extraction: 'Extração de PDF (Vision)',
  document_summary: 'Resumo de Documento',
  metadata_vision_extraction: 'Extração de Metadados',
  ticker_inference: 'Inferência de Ticker',
  image_analysis: 'Análise de Imagem',
  transcription: 'Transcrição de Áudio',
  chunk_enrichment: 'Enriquecimento de Chunks',
  embedding: 'Embeddings (RAG)',
  web_search: 'Busca Web (Tavily)',
}

const UPLOAD_OPERATIONS = new Set([
  'document_vision_extraction',
  'document_summary',
  'metadata_vision_extraction',
  'ticker_inference',
  'chunk_enrichment',
])

const CATEGORY_LABELS = {
  infrastructure: 'Infraestrutura',
  api: 'API / Serviço',
  platform: 'Plataforma',
}

function formatBRL(value) {
  if (value === null || value === undefined) return 'R$ 0,00'
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)
}

function formatUSD(value) {
  if (value === null || value === undefined) return '$ 0.00'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

function formatNumber(value) {
  if (!value) return '0'
  return new Intl.NumberFormat('pt-BR').format(value)
}

function KPICard({ title, value, subtitle, icon: Icon, color = 'primary', trend }) {
  const colorMap = {
    primary: 'bg-primary/10 text-primary border-primary/20',
    green: 'bg-green-50 text-green-700 border-green-200',
    blue: 'bg-blue-50 text-blue-700 border-blue-200',
    purple: 'bg-purple-50 text-purple-700 border-purple-200',
    red: 'bg-red-50 text-red-700 border-red-200',
    gray: 'bg-gray-50 text-gray-700 border-gray-200',
  }

  const iconColorMap = {
    primary: 'bg-primary/15 text-primary',
    green: 'bg-green-100 text-green-600',
    blue: 'bg-blue-100 text-blue-600',
    purple: 'bg-purple-100 text-purple-600',
    red: 'bg-red-100 text-red-600',
    gray: 'bg-gray-100 text-gray-600',
  }

  return (
    <div className={`rounded-xl border p-5 ${colorMap[color]} transition-all hover:shadow-md`}>
      <div className="flex items-start justify-between mb-3">
        <div className={`p-2.5 rounded-lg ${iconColorMap[color]}`}>
          <Icon className="w-5 h-5" />
        </div>
        {trend && (
          <span className={`text-xs font-medium px-2 py-1 rounded-full ${
            trend > 0 ? 'bg-red-100 text-red-600' : 'bg-green-100 text-green-600'
          }`}>
            {trend > 0 ? '+' : ''}{trend}%
          </span>
        )}
      </div>
      <p className="text-2xl font-bold tracking-tight">{value}</p>
      <p className="text-sm font-medium mt-1 opacity-80">{title}</p>
      {subtitle && <p className="text-xs opacity-60 mt-0.5">{subtitle}</p>}
    </div>
  )
}

function ProgressBar({ label, current, max, unit = '', color = 'primary' }) {
  const percentage = max > 0 ? Math.min((current / max) * 100, 100) : 0
  const colorClasses = {
    primary: 'bg-primary',
    green: 'bg-green-500',
    blue: 'bg-blue-500',
    red: 'bg-red-500',
    purple: 'bg-purple-500',
  }

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-1.5">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <span className="text-sm text-gray-500">
          {formatNumber(current)}{unit} / {formatNumber(max)}{unit}
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2.5">
        <div
          className={`h-2.5 rounded-full transition-all duration-500 ${colorClasses[color]}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="text-right mt-0.5">
        <span className={`text-xs font-medium ${percentage > 80 ? 'text-red-500' : 'text-gray-400'}`}>
          {percentage.toFixed(1)}%
        </span>
      </div>
    </div>
  )
}

function FixedCostModal({ isOpen, onClose, onSave, editingCost }) {
  const [form, setForm] = useState({
    name: '', description: '', monthly_cost_brl: '', category: 'infrastructure', plan_details: ''
  })

  useEffect(() => {
    if (editingCost) {
      setForm({
        name: editingCost.name || '',
        description: editingCost.description || '',
        monthly_cost_brl: editingCost.monthly_cost_brl?.toString() || '',
        category: editingCost.category || 'infrastructure',
        plan_details: editingCost.plan_details || '',
      })
    } else {
      setForm({ name: '', description: '', monthly_cost_brl: '', category: 'infrastructure', plan_details: '' })
    }
  }, [editingCost, isOpen])

  if (!isOpen) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      ...form,
      monthly_cost_brl: parseFloat(form.monthly_cost_brl) || 0,
    })
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-semibold text-gray-900">
            {editingCost ? 'Editar Custo Fixo' : 'Novo Custo Fixo'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Nome do Serviço</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="Ex: Z-API, Replit, Tavily"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Descrição</label>
            <input
              type="text"
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="Descrição breve do serviço"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Custo Mensal (R$)</label>
            <input
              type="number"
              step="0.01"
              value={form.monthly_cost_brl}
              onChange={e => setForm({ ...form, monthly_cost_brl: e.target.value })}
              placeholder="0,00"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Categoria</label>
            <select
              value={form.category}
              onChange={e => setForm({ ...form, category: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none"
            >
              <option value="infrastructure">Infraestrutura</option>
              <option value="api">API / Serviço</option>
              <option value="platform">Plataforma</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Detalhes do Plano</label>
            <textarea
              value={form.plan_details}
              onChange={e => setForm({ ...form, plan_details: e.target.value })}
              placeholder="Ex: Plano Pro, 1000 buscas/mês, inclui suporte..."
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none resize-none"
            />
          </div>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 font-medium">
              Cancelar
            </button>
            <button type="submit" className="flex-1 px-4 py-2.5 bg-primary text-white rounded-lg hover:bg-primary-dark font-medium">
              {editingCost ? 'Salvar' : 'Adicionar'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [period, setPeriod] = useState(30)
  const [summary, setSummary] = useState(null)
  const [daily, setDaily] = useState([])
  const [breakdown, setBreakdown] = useState([])
  const [fixedCosts, setFixedCosts] = useState([])
  const [pricing, setPricing] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingCost, setEditingCost] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [summaryRes, dailyRes, breakdownRes, fixedRes, pricingRes] = await Promise.all([
        fetch(`${API_BASE}/costs/summary?days=${period}`, { credentials: 'include' }),
        fetch(`${API_BASE}/costs/daily?days=${period}`, { credentials: 'include' }),
        fetch(`${API_BASE}/costs/breakdown?days=${period}`, { credentials: 'include' }),
        fetch(`${API_BASE}/costs/fixed`, { credentials: 'include' }),
        fetch(`${API_BASE}/costs/pricing`, { credentials: 'include' }),
      ])

      if (!summaryRes.ok) throw new Error('Erro ao carregar dados')

      const [summaryData, dailyData, breakdownData, fixedData, pricingData] = await Promise.all([
        summaryRes.json(), dailyRes.json(), breakdownRes.json(), fixedRes.json(), pricingRes.json(),
      ])

      setSummary(summaryData)
      setDaily(dailyData)
      setBreakdown(breakdownData)
      setFixedCosts(fixedData)
      setPricing(pricingData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => { fetchData() }, [fetchData])

  const handleSaveFixed = async (data) => {
    try {
      const url = editingCost
        ? `${API_BASE}/costs/fixed/${editingCost.id}`
        : `${API_BASE}/costs/fixed`
      const method = editingCost ? 'PUT' : 'POST'

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(data),
      })

      if (res.ok) {
        setModalOpen(false)
        setEditingCost(null)
        fetchData()
      }
    } catch (err) {
      console.error('Erro ao salvar:', err)
    }
  }

  const handleDeleteFixed = async (id) => {
    if (!confirm('Tem certeza que deseja excluir este custo fixo?')) return
    try {
      await fetch(`${API_BASE}/costs/fixed/${id}`, { method: 'DELETE', credentials: 'include' })
      fetchData()
    } catch (err) {
      console.error('Erro ao excluir:', err)
    }
  }

  const dailyChartData = {
    labels: daily.map(d => {
      const date = new Date(d.date)
      return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
    }),
    datasets: [{
      label: 'Custo (R$)',
      data: daily.map(d => d.cost_brl),
      borderColor: '#772B21',
      backgroundColor: 'rgba(119, 43, 33, 0.1)',
      fill: true,
      tension: 0.4,
      pointRadius: 2,
      pointHoverRadius: 5,
    }],
  }

  const dailyChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => `R$ ${ctx.parsed.y.toFixed(2)}`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { font: { size: 11 } } },
      y: {
        beginAtZero: true,
        ticks: {
          callback: (v) => `R$ ${v.toFixed(2)}`,
          font: { size: 11 },
        },
        grid: { color: 'rgba(0,0,0,0.05)' },
      },
    },
  }

  const serviceChartData = summary?.by_service ? {
    labels: summary.by_service.map(s => s.service === 'openai' ? 'OpenAI' : s.service === 'tavily' ? 'Tavily' : s.service),
    datasets: [{
      data: summary.by_service.map(s => s.cost_brl),
      backgroundColor: ['#772B21', '#2563eb', '#7c3aed', '#059669', '#dc2626'],
      borderWidth: 0,
    }],
  } : null

  const operationChartData = summary?.by_operation ? (() => {
    const uploadOps = summary.by_operation.filter(o => UPLOAD_OPERATIONS.has(o.operation))
    const otherOps = summary.by_operation.filter(o => !UPLOAD_OPERATIONS.has(o.operation))
    const grouped = [...otherOps]
    if (uploadOps.length > 0) {
      grouped.push({
        operation: '__uploads__',
        cost_brl: uploadOps.reduce((s, o) => s + o.cost_brl, 0),
        cost_usd: uploadOps.reduce((s, o) => s + (o.cost_usd || 0), 0),
      })
    }
    grouped.sort((a, b) => b.cost_brl - a.cost_brl)
    const top8 = grouped.slice(0, 8)
    return {
      labels: top8.map(o => o.operation === '__uploads__' ? 'Processamento de Uploads' : (OPERATION_LABELS[o.operation] || o.operation)),
      datasets: [{
        label: 'Custo (R$)',
        data: top8.map(o => o.cost_brl),
        backgroundColor: [
          '#772B21', '#2563eb', '#7c3aed', '#059669',
          '#dc2626', '#0891b2', '#c026d3', '#8b4513'
        ],
        borderRadius: 6,
      }],
    }
  })() : null

  const operationChartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => `R$ ${ctx.parsed.x.toFixed(4)}`,
        },
      },
    },
    scales: {
      x: {
        beginAtZero: true,
        ticks: { callback: (v) => `R$ ${v.toFixed(2)}`, font: { size: 11 } },
        grid: { color: 'rgba(0,0,0,0.05)' },
      },
      y: {
        ticks: { font: { size: 11 } },
        grid: { display: false },
      },
    },
  }

  const totalFixedCost = fixedCosts.filter(f => f.is_active).reduce((sum, f) => sum + f.monthly_cost_brl, 0)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <p className="text-gray-500">Carregando dados de custos...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3 text-red-500">
          <AlertCircle className="w-8 h-8" />
          <p>{error}</p>
          <button onClick={fetchData} className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark">
            Tentar novamente
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Central de Custos</h1>
            <p className="text-sm text-gray-500 mt-1">Monitoramento de gastos com APIs e serviços</p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={period}
              onChange={e => setPeriod(parseInt(e.target.value))}
              className="px-3 py-2 border border-border rounded-lg text-sm bg-white focus:ring-2 focus:ring-primary/40 focus:border-primary outline-none"
            >
              <option value={7}>Últimos 7 dias</option>
              <option value={30}>Últimos 30 dias</option>
              <option value={90}>Últimos 90 dias</option>
              <option value={365}>Último ano</option>
            </select>
            <button onClick={fetchData} className="p-2 text-gray-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors" title="Atualizar">
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex gap-1 mb-6 bg-gray-100 p-1 rounded-lg w-fit">
          {[
            { key: 'overview', label: 'Visão Geral', icon: BarChart3 },
            { key: 'details', label: 'Detalhamento', icon: FileText },
            { key: 'fixed', label: 'Custos Fixos', icon: Server },
            { key: 'pricing', label: 'Tabela de Preços', icon: DollarSign },
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === tab.key
                  ? 'bg-white text-primary shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'overview' && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <KPICard
                title="Custo Total (Variável)"
                value={formatBRL(summary?.variable_costs_brl || 0)}
                subtitle={`${formatUSD(summary?.total_cost_usd || 0)} USD`}
                icon={DollarSign}
                color="primary"
              />
              <KPICard
                title="Custos Fixos / Mês"
                value={formatBRL(totalFixedCost)}
                subtitle={`${fixedCosts.filter(f => f.is_active).length} serviços ativos`}
                icon={Server}
                color="blue"
              />
              <KPICard
                title="Total Chamadas API"
                value={formatNumber(summary?.by_service?.reduce((s, sv) => s + sv.count, 0) || 0)}
                subtitle={`${period} dias`}
                icon={Zap}
                color="purple"
              />
              <KPICard
                title="Custo Estimado Mensal"
                value={formatBRL((summary?.variable_costs_brl || 0) / period * 30 + totalFixedCost)}
                subtitle="Projeção (fixo + variável)"
                icon={TrendingUp}
                color="green"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
              <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-base font-semibold text-gray-900 mb-4">Evolução de Custos Variáveis</h3>
                <div className="h-64">
                  {daily.length > 0 ? (
                    <Line data={dailyChartData} options={dailyChartOptions} />
                  ) : (
                    <div className="flex items-center justify-center h-full text-gray-400">
                      <p>Sem dados no período selecionado</p>
                    </div>
                  )}
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-base font-semibold text-gray-900 mb-4">Distribuição por Serviço</h3>
                <div className="h-64 flex items-center justify-center">
                  {serviceChartData && serviceChartData.datasets[0].data.some(v => v > 0) ? (
                    <Doughnut
                      data={serviceChartData}
                      options={{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                          legend: { position: 'bottom', labels: { font: { size: 12 }, padding: 16 } },
                          tooltip: {
                            callbacks: { label: (ctx) => `${ctx.label}: R$ ${ctx.parsed.toFixed(4)}` },
                          },
                        },
                      }}
                    />
                  ) : (
                    <div className="text-gray-400 text-center">
                      <Database className="w-10 h-10 mx-auto mb-2 opacity-30" />
                      <p className="text-sm">Sem dados no período</p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
              <h3 className="text-base font-semibold text-gray-900 mb-4">Custo por Operação</h3>
              <div className="h-80">
                {operationChartData && operationChartData.datasets[0].data.some(v => v > 0) ? (
                  <Bar data={operationChartData} options={operationChartOptions} />
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-400">
                    <p>Sem dados no período selecionado</p>
                  </div>
                )}
              </div>
            </div>

            {summary?.by_service?.length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-base font-semibold text-gray-900 mb-4">Resumo por Serviço</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-3 px-4 font-semibold text-gray-600">Serviço</th>
                        <th className="text-right py-3 px-4 font-semibold text-gray-600">Chamadas</th>
                        <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (R$)</th>
                        <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (USD)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.by_service.map((s, i) => {
                        const Icon = SERVICE_ICONS[s.service] || Cpu
                        return (
                          <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                            <td className="py-3 px-4 flex items-center gap-2">
                              <Icon className="w-4 h-4 text-gray-500" />
                              <span className="font-medium">{s.service === 'openai' ? 'OpenAI' : s.service === 'tavily' ? 'Tavily' : s.service}</span>
                            </td>
                            <td className="text-right py-3 px-4 text-gray-600">{formatNumber(s.count)}</td>
                            <td className="text-right py-3 px-4 font-medium">{formatBRL(s.cost_brl)}</td>
                            <td className="text-right py-3 px-4 text-gray-500">{formatUSD(s.cost_usd)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}

        {activeTab === 'details' && (() => {
          const uploadRows = breakdown.filter(b => UPLOAD_OPERATIONS.has(b.operation))
          const otherRows = breakdown.filter(b => !UPLOAD_OPERATIONS.has(b.operation))
          const uploadSummary = uploadRows.length > 0 ? {
            count: uploadRows.reduce((s, b) => s + b.count, 0),
            total_prompt_tokens: uploadRows.reduce((s, b) => s + b.total_prompt_tokens, 0),
            total_completion_tokens: uploadRows.reduce((s, b) => s + b.total_completion_tokens, 0),
            total_tokens: uploadRows.reduce((s, b) => s + b.total_tokens, 0),
            cost_brl: uploadRows.reduce((s, b) => s + b.cost_brl, 0),
            cost_usd: uploadRows.reduce((s, b) => s + b.cost_usd, 0),
          } : null
          return (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-base font-semibold text-gray-900 mb-4">Detalhamento por Operação</h3>
            {breakdown.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-3 px-4 font-semibold text-gray-600">Operação</th>
                      <th className="text-left py-3 px-4 font-semibold text-gray-600">Modelo</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Chamadas</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Tokens (Prompt)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Tokens (Resposta)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Total Tokens</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (R$)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {uploadSummary && (
                      <tr className="border-b border-primary/10 bg-primary/5 font-medium">
                        <td className="py-3 px-4" colSpan={1}>
                          <div className="flex items-center gap-2">
                            <FileText className="w-4 h-4 text-primary" />
                            <span className="text-primary">Processamento de Uploads</span>
                            <span className="text-xs text-gray-400 font-normal">({uploadRows.length} sub-operações)</span>
                          </div>
                        </td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 bg-primary/10 rounded text-xs font-mono text-primary">vários</span>
                        </td>
                        <td className="text-right py-3 px-4">{formatNumber(uploadSummary.count)}</td>
                        <td className="text-right py-3 px-4">{formatNumber(uploadSummary.total_prompt_tokens)}</td>
                        <td className="text-right py-3 px-4">{formatNumber(uploadSummary.total_completion_tokens)}</td>
                        <td className="text-right py-3 px-4">{formatNumber(uploadSummary.total_tokens)}</td>
                        <td className="text-right py-3 px-4 text-primary">{formatBRL(uploadSummary.cost_brl)}</td>
                        <td className="text-right py-3 px-4 text-primary/70">{formatUSD(uploadSummary.cost_usd)}</td>
                      </tr>
                    )}
                    {uploadRows.map((b, i) => (
                      <tr key={`upload-${i}`} className="border-b border-gray-50 hover:bg-gray-50 bg-gray-50/50">
                        <td className="py-2.5 px-4 pl-10">
                          <span className="text-gray-600 text-xs">{OPERATION_LABELS[b.operation] || b.operation}</span>
                        </td>
                        <td className="py-2.5 px-4">
                          <span className="px-2 py-0.5 bg-gray-100 rounded text-xs font-mono">
                            {b.model || '-'}
                          </span>
                        </td>
                        <td className="text-right py-2.5 px-4 text-gray-500 text-xs">{formatNumber(b.count)}</td>
                        <td className="text-right py-2.5 px-4 text-gray-500 text-xs">{formatNumber(b.total_prompt_tokens)}</td>
                        <td className="text-right py-2.5 px-4 text-gray-500 text-xs">{formatNumber(b.total_completion_tokens)}</td>
                        <td className="text-right py-2.5 px-4 text-gray-500 text-xs">{formatNumber(b.total_tokens)}</td>
                        <td className="text-right py-2.5 px-4 text-gray-500 text-xs">{formatBRL(b.cost_brl)}</td>
                        <td className="text-right py-2.5 px-4 text-gray-400 text-xs">{formatUSD(b.cost_usd)}</td>
                      </tr>
                    ))}
                    {otherRows.map((b, i) => (
                      <tr key={`other-${i}`} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="py-3 px-4">
                          <span className="font-medium">{OPERATION_LABELS[b.operation] || b.operation}</span>
                        </td>
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 bg-gray-100 rounded text-xs font-mono">
                            {b.model || '-'}
                          </span>
                        </td>
                        <td className="text-right py-3 px-4 text-gray-600">{formatNumber(b.count)}</td>
                        <td className="text-right py-3 px-4 text-gray-600">{formatNumber(b.total_prompt_tokens)}</td>
                        <td className="text-right py-3 px-4 text-gray-600">{formatNumber(b.total_completion_tokens)}</td>
                        <td className="text-right py-3 px-4 text-gray-600">{formatNumber(b.total_tokens)}</td>
                        <td className="text-right py-3 px-4 font-medium">{formatBRL(b.cost_brl)}</td>
                        <td className="text-right py-3 px-4 text-gray-500">{formatUSD(b.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-gray-200 font-semibold">
                      <td colSpan={2} className="py-3 px-4">Total</td>
                      <td className="text-right py-3 px-4">{formatNumber(breakdown.reduce((s, b) => s + b.count, 0))}</td>
                      <td className="text-right py-3 px-4">{formatNumber(breakdown.reduce((s, b) => s + b.total_prompt_tokens, 0))}</td>
                      <td className="text-right py-3 px-4">{formatNumber(breakdown.reduce((s, b) => s + b.total_completion_tokens, 0))}</td>
                      <td className="text-right py-3 px-4">{formatNumber(breakdown.reduce((s, b) => s + b.total_tokens, 0))}</td>
                      <td className="text-right py-3 px-4">{formatBRL(breakdown.reduce((s, b) => s + b.cost_brl, 0))}</td>
                      <td className="text-right py-3 px-4">{formatUSD(breakdown.reduce((s, b) => s + b.cost_usd, 0))}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                <BarChart3 className="w-12 h-12 mb-3 opacity-30" />
                <p>Nenhum registro de custo variável no período selecionado</p>
                <p className="text-xs mt-1">Os custos serão registrados conforme o Stevan interagir com assessores</p>
              </div>
            )}
          </div>
          )
        })()}

        {activeTab === 'fixed' && (
          <div className="space-y-6">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-base font-semibold text-gray-900">Custos Fixos Mensais</h3>
                <button
                  onClick={() => { setEditingCost(null); setModalOpen(true) }}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark text-sm font-medium"
                >
                  <Plus className="w-4 h-4" />
                  Adicionar
                </button>
              </div>

              {fixedCosts.length > 0 ? (
                <div className="space-y-3">
                  {fixedCosts.map(cost => (
                    <div key={cost.id} className={`flex items-center justify-between p-4 rounded-lg border ${cost.is_active ? 'border-gray-200 bg-white' : 'border-gray-100 bg-gray-50 opacity-60'}`}>
                      <div className="flex items-center gap-4">
                        <div className="p-2.5 bg-blue-50 rounded-lg">
                          <Server className="w-5 h-5 text-blue-600" />
                        </div>
                        <div>
                          <p className="font-medium text-gray-900">{cost.name}</p>
                          <p className="text-sm text-gray-500">{cost.description || CATEGORY_LABELS[cost.category] || cost.category}</p>
                          {cost.plan_details && (
                            <p className="text-xs text-gray-400 mt-0.5">{cost.plan_details}</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-lg font-semibold text-gray-900">{formatBRL(cost.monthly_cost_brl)}</span>
                        <span className="text-xs text-gray-400">/mês</span>
                        <div className="flex gap-1 ml-2">
                          <button
                            onClick={() => { setEditingCost(cost); setModalOpen(true) }}
                            className="p-1.5 text-gray-400 hover:text-primary hover:bg-primary/10 rounded-lg"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDeleteFixed(cost.id)}
                            className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                  <div className="flex justify-between items-center pt-3 border-t border-gray-200 mt-4">
                    <span className="font-semibold text-gray-700">Total Mensal</span>
                    <span className="text-xl font-bold text-gray-900">{formatBRL(totalFixedCost)}</span>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-gray-400">
                  <Server className="w-12 h-12 mb-3 opacity-30" />
                  <p>Nenhum custo fixo cadastrado</p>
                  <p className="text-xs mt-1">Adicione serviços como Z-API, Replit, Tavily, etc.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'pricing' && pricing && (
          <div className="space-y-6">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-base font-semibold text-gray-900 mb-4">Tabela de Preços OpenAI</h3>
              <p className="text-sm text-gray-500 mb-4">Preços por 1 milhão de tokens (USD). Taxa de câmbio: R$ {pricing.exchange_rate?.toFixed(2) || '5,80'}</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-3 px-4 font-semibold text-gray-600">Modelo</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Entrada (USD/1M)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Saída (USD/1M)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Entrada (BRL/1M)</th>
                      <th className="text-right py-3 px-4 font-semibold text-gray-600">Saída (BRL/1M)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pricing.openai && Object.entries(pricing.openai).map(([model, prices]) => (
                      <tr key={model} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="py-3 px-4">
                          <span className="px-2 py-0.5 bg-gray-100 rounded text-xs font-mono">{model}</span>
                        </td>
                        {prices.per_minute !== undefined ? (
                          <>
                            <td className="text-right py-3 px-4 text-gray-600" colSpan={4}>
                              ${prices.per_minute}/minuto ({formatBRL(prices.per_minute * (pricing.exchange_rate || 5.80))}/minuto)
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="text-right py-3 px-4 text-gray-600">${prices.input?.toFixed(2)}</td>
                            <td className="text-right py-3 px-4 text-gray-600">${prices.output?.toFixed(2)}</td>
                            <td className="text-right py-3 px-4 font-medium">{formatBRL(prices.input * (pricing.exchange_rate || 5.80))}</td>
                            <td className="text-right py-3 px-4 font-medium">{formatBRL(prices.output * (pricing.exchange_rate || 5.80))}</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {pricing.tavily && (
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-base font-semibold text-gray-900 mb-4">Preços Tavily</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="text-left py-3 px-4 font-semibold text-gray-600">Operação</th>
                        <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (USD)</th>
                        <th className="text-right py-3 px-4 font-semibold text-gray-600">Custo (BRL)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(pricing.tavily).map(([op, price]) => (
                        <tr key={op} className="border-b border-gray-50 hover:bg-gray-50">
                          <td className="py-3 px-4 font-medium">{op === 'search' ? 'Busca Web' : op}</td>
                          <td className="text-right py-3 px-4">${price.toFixed(4)}</td>
                          <td className="text-right py-3 px-4 font-medium">{formatBRL(price * (pricing.exchange_rate || 5.80))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <FixedCostModal
        isOpen={modalOpen}
        onClose={() => { setModalOpen(false); setEditingCost(null) }}
        onSave={handleSaveFixed}
        editingCost={editingCost}
      />
    </div>
  )
}
