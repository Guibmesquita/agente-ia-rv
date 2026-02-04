import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Plus, User, Bot, Send, UserCheck, Loader2, MessageCircle, CheckCheck, MoreVertical, Copy, Reply, Trash2, Forward, X, Phone, AlertCircle, Clock, CheckCircle2, ArrowUpCircle, Filter, SlidersHorizontal, Calendar, Building2, Users, Tag } from 'lucide-react';

const API_BASE = '/api';

function formatPhone(phone) {
  if (!phone) return '-';
  if (phone.length === 13) {
    return `+${phone.slice(0,2)} (${phone.slice(2,4)}) ${phone.slice(4,9)}-${phone.slice(9)}`;
  }
  return phone;
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return 'Agora';
  if (minutes < 60) return `${minutes}min`;
  if (hours < 24) return `${hours}h`;
  if (days < 7) return `${days}d`;
  return date.toLocaleDateString('pt-BR');
}

function formatTime(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

function StatusBadge({ status }) {
  const config = {
    bot_active: { bg: 'bg-primary/10', text: 'text-primary', border: 'border-primary/20', label: 'Bot' },
    human_takeover: { bg: 'bg-amber-100', text: 'text-amber-700', border: 'border-amber-200', label: 'Humano' },
    closed: { bg: 'bg-gray-100', text: 'text-gray-500', border: 'border-gray-200', label: 'Encerrada' },
  };
  const c = config[status] || config.closed;
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-medium border ${c.bg} ${c.text} ${c.border}`}>
      {c.label}
    </span>
  );
}

function TicketStatusBadge({ ticketStatus, escalationLevel }) {
  const isEscalated = escalationLevel === 't1';
  
  // Se não está escalado (T0) e não tem ticket_status, é conversa com bot - sem badge de ticket
  if (!isEscalated && !ticketStatus) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border bg-gray-100 text-gray-600 border-gray-200">
        <Bot className="w-3 h-3" />
        Bot
      </span>
    );
  }
  
  const statusConfig = {
    new: { bg: 'bg-blue-100', text: 'text-blue-700', border: 'border-blue-200', label: 'Novo', icon: AlertCircle },
    open: { bg: 'bg-yellow-100', text: 'text-yellow-700', border: 'border-yellow-200', label: 'Aberto', icon: Clock },
    in_progress: { bg: 'bg-purple-100', text: 'text-purple-700', border: 'border-purple-200', label: 'Em Progresso', icon: ArrowUpCircle },
    solved: { bg: 'bg-green-100', text: 'text-green-700', border: 'border-green-200', label: 'Resolvido', icon: CheckCircle2 },
  };
  
  // Para conversas escaladas sem ticket_status definido, usar 'new' como padrão
  const effectiveStatus = ticketStatus || (isEscalated ? 'new' : null);
  const c = statusConfig[effectiveStatus] || statusConfig.new;
  const Icon = c.icon;
  
  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${c.bg} ${c.text} ${c.border}`}>
        <Icon className="w-3 h-3" />
        {c.label}
      </span>
      {isEscalated && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700 border border-red-200">
          T1
        </span>
      )}
    </div>
  );
}

function MessageContextMenu({ x, y, onClose, onCopy, onDelete }) {
  useEffect(() => {
    const handleClick = () => onClose();
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, [onClose]);

  return (
    <div 
      className="fixed bg-white rounded-lg shadow-lg border border-gray-200 py-2 min-w-[160px] z-50"
      style={{ left: x, top: y }}
      onClick={e => e.stopPropagation()}
    >
      <button className="w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-3 font-medium">
        <Reply className="w-4 h-4" /> Responder
      </button>
      <button className="w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-3 font-medium">
        <Forward className="w-4 h-4" /> Encaminhar
      </button>
      <button onClick={onCopy} className="w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-100 flex items-center gap-3 font-medium">
        <Copy className="w-4 h-4" /> Copiar
      </button>
      <button onClick={onDelete} className="w-full px-4 py-2.5 text-left text-sm text-red-600 hover:bg-gray-100 flex items-center gap-3 font-medium">
        <Trash2 className="w-4 h-4" /> Excluir
      </button>
    </div>
  );
}

function ChatBubble({ message, contactName, onContextMenu }) {
  const isOutbound = message.direction === 'outbound';
  const senderLabels = { bot: 'Agente IA', human: 'Operador' };
  const senderName = isOutbound ? senderLabels[message.sender_type] || 'Sistema' : contactName || 'Contato';
  const time = formatTime(message.created_at);
  const content = message.body || message.transcription || '[Mídia]';

  const handleMenuClick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onContextMenu(e, message);
  };

  if (isOutbound) {
    return (
      <div className="flex items-start gap-2.5 justify-end mb-4">
        <button 
          onClick={handleMenuClick}
          className="self-center p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <MoreVertical className="w-5 h-5" />
        </button>
        <div className={`flex flex-col w-full max-w-[320px] leading-relaxed p-4 rounded-s-xl rounded-ee-xl ${
          message.sender_type === 'bot' 
            ? 'bg-primary text-white' 
            : 'bg-emerald-600 text-white'
        }`}>
          <div className="flex items-center space-x-2 rtl:space-x-reverse mb-1">
            <span className="text-sm font-semibold">{senderName}</span>
            <span className="text-sm opacity-75">{time}</span>
          </div>
          <p className="text-sm py-2 whitespace-pre-wrap break-words">{content}</p>
          <div className="flex items-center gap-1.5 text-xs opacity-75">
            <CheckCheck className="w-4 h-4" />
            <span>Enviada</span>
          </div>
        </div>
        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          message.sender_type === 'bot' ? 'bg-primary/10' : 'bg-emerald-100'
        }`}>
          {message.sender_type === 'bot' ? (
            <Bot className="w-4 h-4 text-primary" />
          ) : (
            <UserCheck className="w-4 h-4 text-emerald-600" />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2.5 mb-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center">
        <User className="w-4 h-4 text-gray-500" />
      </div>
      <div className="flex flex-col w-full max-w-[320px] leading-relaxed p-4 border border-gray-200 bg-gray-50 rounded-e-xl rounded-es-xl">
        <div className="flex items-center space-x-2 rtl:space-x-reverse mb-1">
          <span className="text-sm font-semibold text-gray-900">{senderName}</span>
          <span className="text-sm text-gray-500">{time}</span>
        </div>
        <p className="text-sm py-2 text-gray-900 whitespace-pre-wrap break-words">{content}</p>
      </div>
      <button 
        onClick={handleMenuClick}
        className="self-center p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
      >
        <MoreVertical className="w-5 h-5" />
      </button>
    </div>
  );
}

function ConversationItem({ conversation, isActive, onClick }) {
  const displayName = conversation.assessor_name || conversation.contact_name || 'Desconhecido';
  const initials = displayName.charAt(0).toUpperCase();
  const preview = conversation.last_message_preview || 'Sem mensagens';
  const time = formatTimeAgo(conversation.last_message_at || conversation.updated_at);
  const assignedTo = conversation.assigned_to_name;
  const isEscalated = conversation.escalation_level === 't1';
  
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-4 px-4 py-4 cursor-pointer transition-all border-b border-gray-100 ${
        isActive 
          ? 'bg-primary/5 border-l-4 border-l-primary' 
          : isEscalated
            ? 'bg-red-50/50 hover:bg-red-50 border-l-4 border-l-red-400'
            : 'hover:bg-gray-50 border-l-4 border-l-transparent'
      }`}
    >
      <div className="relative flex-shrink-0">
        <div className={`w-12 h-12 rounded-full flex items-center justify-center text-white font-semibold text-lg ${
          conversation.status === 'human_takeover' ? 'bg-amber-500' : 'bg-gray-400'
        }`}>
          {initials}
        </div>
        {conversation.status === 'bot_active' && (
          <div className="absolute -bottom-0.5 -right-0.5 w-5 h-5 rounded-full bg-primary border-2 border-white flex items-center justify-center">
            <Bot className="w-3 h-3 text-white" />
          </div>
        )}
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-gray-900 text-sm truncate max-w-[160px]">{displayName}</span>
          <span className="text-xs text-gray-500 flex-shrink-0 ml-2">{time}</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500 mb-1.5">
          <span>{formatPhone(conversation.phone)}</span>
          {assignedTo && (
            <span className="text-primary font-medium">• {assignedTo}</span>
          )}
          {!assignedTo && conversation.status === 'bot_active' && (
            <span className="text-gray-400">• BOT</span>
          )}
        </div>
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-gray-500 truncate flex-1">{preview}</p>
          <TicketStatusBadge 
            ticketStatus={conversation.ticket_status} 
            escalationLevel={conversation.escalation_level}
          />
        </div>
      </div>
      
      {conversation.unread_count > 0 && (
        <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary flex items-center justify-center">
          <span className="text-xs text-white font-bold">{conversation.unread_count}</span>
        </div>
      )}
    </div>
  );
}

function NewConversationModal({ isOpen, onClose, onSubmit, isLoading }) {
  const [phone, setPhone] = useState('');
  const [message, setMessage] = useState('');

  const handleSubmit = () => {
    const phoneClean = phone.replace(/\D/g, '');
    if (!phoneClean || phoneClean.length < 10) {
      alert('Número de telefone inválido');
      return;
    }
    if (!message.trim()) {
      alert('Digite uma mensagem');
      return;
    }
    onSubmit({ phone: phoneClean, message: message.trim() });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-md mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-5 border-b border-gray-100 flex justify-between items-center">
          <h3 className="font-semibold text-lg text-gray-900">Nova Conversa</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-2 hover:bg-gray-100 rounded-full transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-900 mb-2">Número de Telefone</label>
            <div className="relative">
              <Phone className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                placeholder="5511999999999"
                className="w-full pl-12 pr-4 py-3 border border-gray-200 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all"
              />
            </div>
            <p className="text-xs text-gray-500 mt-2">Código do país + DDD + número</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-900 mb-2">Mensagem Inicial</label>
            <textarea
              value={message}
              onChange={e => setMessage(e.target.value)}
              placeholder="Digite a mensagem..."
              rows={4}
              className="w-full px-4 py-3 border border-gray-200 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-all resize-none"
            />
          </div>
        </div>
        <div className="px-6 py-5 border-t border-gray-100 flex gap-3 justify-end bg-gray-50 rounded-b-xl">
          <button onClick={onClose} className="px-5 py-2.5 text-gray-600 hover:text-gray-900 font-medium transition-colors">
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="px-6 py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
          >
            {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
            Enviar Mensagem
          </button>
        </div>
      </div>
    </div>
  );
}

const CATEGORY_LABELS = {
  'out_of_scope': 'Fora do Escopo',
  'info_not_found': 'Informação Não Encontrada',
  'technical_complexity': 'Complexidade Técnica',
  'commercial_request': 'Solicitação Comercial',
  'explicit_human_request': 'Solicitação Explícita de Humano',
  'emotional_friction': 'Fricção Emocional',
  'stalled_conversation': 'Conversa Travada',
  'recurring_issue': 'Problema Recorrente',
  'sensitive_topic': 'Tema Sensível',
  'investment_decision': 'Decisão de Investimento',
  'other': 'Outros'
};

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [ticketFilter, setTicketFilter] = useState('new');
  const [filterCounts, setFilterCounts] = useState({ all: 0, escalated: 0, my_tickets: 0, open: 0, solved_today: 0, new: 0, in_progress: 0 });
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [advancedFilters, setAdvancedFilters] = useState({
    conversationType: '',
    dateRange: '',
    unit: '',
    broker: '',
    category: ''
  });
  const [filterOptions, setFilterOptions] = useState({ units: [], brokers: [], categories: [] });
  const [isCreating, setIsCreating] = useState(false);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [totalCount, setTotalCount] = useState(0);
  const [contextMenu, setContextMenu] = useState(null);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const shouldScrollRef = useRef(true);
  const PAGE_SIZE = 20;

  const scrollToBottom = useCallback((behavior = 'smooth') => {
    if (messagesEndRef.current && shouldScrollRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior });
    }
  }, []);

  const fetchFilterCounts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/conversations/filters`, { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        setFilterCounts(data);
      }
    } catch (err) {
      console.error('Erro ao carregar contadores:', err);
    }
  }, []);

  const fetchConversations = useCallback(async (pageNum = 0, append = false) => {
    setIsLoading(true);
    try {
      const offset = pageNum * PAGE_SIZE;
      let url = `${API_BASE}/conversations/?limit=${PAGE_SIZE}&offset=${offset}`;
      if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;
      if (ticketFilter === 'escalated') url += `&escalation_level=t1`;
      else if (ticketFilter === 'my_tickets') url += `&assigned_to_me=true`;
      else if (ticketFilter === 'open') url += `&ticket_status=open`;
      else if (ticketFilter === 'new') url += `&ticket_status=new`;
      else if (ticketFilter === 'in_progress') url += `&ticket_status=in_progress`;
      else if (ticketFilter === 'solved') url += `&ticket_status=solved`;
      if (advancedFilters.conversationType) url += `&status=${advancedFilters.conversationType}`;
      if (advancedFilters.unit) url += `&unidade=${encodeURIComponent(advancedFilters.unit)}`;
      if (advancedFilters.broker) url += `&broker=${encodeURIComponent(advancedFilters.broker)}`;
      if (advancedFilters.category) url += `&escalation_category=${advancedFilters.category}`;
      if (advancedFilters.dateRange) url += `&date_range=${advancedFilters.dateRange}`;
      const res = await fetch(url, { credentials: 'include' });
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      const data = await res.json();
      const items = Array.isArray(data) ? data : (data.items || []);
      const total = Array.isArray(data) ? data.length : (data.total || items.length);
      
      const sortedItems = [...items].sort((a, b) => {
        const dateA = new Date(a.last_message_at || a.updated_at || 0);
        const dateB = new Date(b.last_message_at || b.updated_at || 0);
        return dateB - dateA;
      });
      
      setConversations(prev => {
        const newList = append ? [...prev, ...sortedItems] : sortedItems;
        setHasMore(newList.length < total);
        return newList;
      });
      setTotalCount(total);
    } catch (err) {
      console.error('Erro ao carregar conversas:', err);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, ticketFilter, advancedFilters]);

  const fetchMessages = async (conversationId, isInitialLoad = false) => {
    try {
      await fetch(`${API_BASE}/conversations/${conversationId}/sync-messages`, {
        method: 'POST',
        credentials: 'include',
      });
      const res = await fetch(`${API_BASE}/conversations/${conversationId}/messages`, { credentials: 'include' });
      const data = await res.json();
      setMessages(data);
      if (isInitialLoad) {
        shouldScrollRef.current = true;
        setTimeout(() => scrollToBottom('auto'), 50);
      } else if (shouldScrollRef.current) {
        setTimeout(() => scrollToBottom('smooth'), 50);
      }
    } catch (err) {
      console.error('Erro ao carregar mensagens:', err);
    }
  };

  const selectConversation = async (conv) => {
    const updatedConv = { ...conv, unread_count: 0 };
    setCurrentConversation(updatedConv);
    setConversations(prev => prev.map(c => 
      c.id === conv.id ? { ...c, unread_count: 0 } : c
    ));
    setMessages([]);
    await fetchMessages(conv.id, true);
  };

  const loadMoreConversations = () => {
    if (hasMore && !isLoading) {
      const nextPage = page + 1;
      setPage(nextPage);
      fetchConversations(nextPage, true);
    }
  };

  const sendMessage = async () => {
    if (!messageInput.trim() || !currentConversation) return;
    setIsSending(true);
    shouldScrollRef.current = true;
    try {
      const res = await fetch(`${API_BASE}/conversations/${currentConversation.id}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: messageInput.trim() }),
      });
      if (!res.ok) throw new Error('Erro ao enviar');
      setMessageInput('');
      await fetchMessages(currentConversation.id, false);
      await fetchConversations(0, false);
    } catch (err) {
      alert('Erro ao enviar mensagem');
    } finally {
      setIsSending(false);
    }
  };

  const toggleTakeover = async () => {
    if (!currentConversation) return;
    const action = currentConversation.status === 'human_takeover' ? 'release' : 'takeover';
    try {
      const res = await fetch(`${API_BASE}/conversations/${currentConversation.id}/takeover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action }),
      });
      const result = await res.json();
      setCurrentConversation(prev => ({ ...prev, status: result.status }));
      await fetchConversations(0, false);
    } catch (err) {
      alert('Erro ao alterar status');
    }
  };

  const takeTicket = async () => {
    if (!currentConversation) return;
    try {
      const res = await fetch(`${API_BASE}/conversations/${currentConversation.id}/take`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Erro ao assumir ticket');
        return;
      }
      const result = await res.json();
      setCurrentConversation(prev => ({ 
        ...prev, 
        assigned_to_id: result.assigned_to_id,
        assigned_to_name: result.assigned_to_name,
        ticket_status: result.ticket_status 
      }));
      await fetchConversations(0, false);
      fetchFilterCounts();
    } catch (err) {
      alert('Erro ao assumir ticket');
    }
  };

  const releaseTicket = async () => {
    if (!currentConversation) return;
    try {
      const res = await fetch(`${API_BASE}/conversations/${currentConversation.id}/release`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Erro ao liberar ticket');
        return;
      }
      const result = await res.json();
      setCurrentConversation(prev => ({ 
        ...prev, 
        assigned_to_id: null,
        assigned_to_name: null 
      }));
      await fetchConversations(0, false);
      fetchFilterCounts();
    } catch (err) {
      alert('Erro ao liberar ticket');
    }
  };

  const updateTicketStatus = async (newStatus) => {
    if (!currentConversation) return;
    try {
      const res = await fetch(`${API_BASE}/conversations/${currentConversation.id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ticket_status: newStatus }),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || 'Erro ao alterar status');
        return;
      }
      const result = await res.json();
      setCurrentConversation(prev => ({ ...prev, ticket_status: result.ticket_status }));
      await fetchConversations(0, false);
      fetchFilterCounts();
    } catch (err) {
      alert('Erro ao alterar status');
    }
  };

  const startNewConversation = async ({ phone, message }) => {
    setIsCreating(true);
    try {
      const res = await fetch(`${API_BASE}/conversations/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ phone, message }),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'Erro');
      setShowNewModal(false);
      
      const listRes = await fetch(`${API_BASE}/conversations/?limit=${PAGE_SIZE}&offset=0`, { credentials: 'include' });
      const listData = await listRes.json();
      const items = Array.isArray(listData) ? listData : (listData.items || []);
      setConversations(items);
      setTotalCount(Array.isArray(listData) ? items.length : (listData.total || 0));
      setHasMore(items.length < (Array.isArray(listData) ? items.length : (listData.total || 0)));
      setPage(0);
      
      if (result.conversation_id) {
        const conv = items.find(c => c.id === result.conversation_id);
        if (conv) selectConversation(conv);
      }
    } catch (err) {
      alert('Erro: ' + err.message);
    } finally {
      setIsCreating(false);
    }
  };

  const handleMessageContextMenu = (e, message) => {
    e.preventDefault();
    setContextMenu({
      x: Math.min(e.clientX, window.innerWidth - 180),
      y: Math.min(e.clientY, window.innerHeight - 220),
      message
    });
  };

  const handleCopyMessage = () => {
    if (contextMenu?.message) {
      navigator.clipboard.writeText(contextMenu.message.body || '');
    }
    setContextMenu(null);
  };

  const handleDeleteMessage = () => {
    setContextMenu(null);
  };

  useEffect(() => {
    const syncAndLoad = async () => {
      try {
        await fetch(`${API_BASE}/conversations/sync`, { method: 'POST', credentials: 'include' });
      } catch {}
      fetchConversations(0, false);
      fetchFilterCounts();
    };
    syncAndLoad();
  }, []);

  useEffect(() => {
    const fetchFilterOptions = async () => {
      try {
        const res = await fetch(`${API_BASE}/conversations/filter-options`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setFilterOptions(data);
        }
      } catch (err) {
        console.error('Erro ao carregar opções de filtro:', err);
      }
    };
    fetchFilterOptions();
  }, []);

  useEffect(() => {
    setPage(0);
    const timer = setTimeout(() => {
      fetchConversations(0, false);
      fetchFilterCounts();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, ticketFilter, advancedFilters]);

  useEffect(() => {
    if (messages.length > 0 && shouldScrollRef.current) {
      scrollToBottom('auto');
    }
  }, [messages.length, scrollToBottom]);

  const handleMessagesScroll = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    const threshold = 100;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    shouldScrollRef.current = isNearBottom;
  }, []);

  useEffect(() => {
    let sseToken = null;
    let tokenRefreshTimeout = null;
    let fallbackPollingTimeout = null;
    let sseConnected = false;

    const fetchSseToken = async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/sse-token`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          return { token: data.token, expiresIn: data.expires_in || 300 };
        }
      } catch {}
      return null;
    };

    const scheduleTokenRefresh = (expiresIn) => {
      if (tokenRefreshTimeout) clearTimeout(tokenRefreshTimeout);
      const refreshTime = Math.max((expiresIn - 60) * 1000, 30000);
      tokenRefreshTimeout = setTimeout(async () => {
        const newTokenData = await fetchSseToken();
        if (newTokenData) {
          sseToken = newTokenData.token;
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
          }
          connectSSE();
        }
      }, refreshTime);
    };

    const startFallbackPolling = () => {
      if (fallbackPollingTimeout) return;
      const poll = async () => {
        if (sseConnected) {
          fallbackPollingTimeout = null;
          return;
        }
        await fetchConversations(0, false);
        if (currentConversation) {
          await fetchMessages(currentConversation.id, false);
        }
        fallbackPollingTimeout = setTimeout(poll, 30000);
      };
      fallbackPollingTimeout = setTimeout(poll, 30000);
    };

    const connectSSE = async () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
      
      if (!sseToken) {
        const tokenData = await fetchSseToken();
        if (tokenData) {
          sseToken = tokenData.token;
          scheduleTokenRefresh(tokenData.expiresIn);
        }
      }
      
      if (!sseToken) {
        startFallbackPolling();
        return;
      }

      const url = `${API_BASE}/conversations/stream?token=${encodeURIComponent(sseToken)}`;
      const es = new EventSource(url);
      es.onopen = () => {
        sseConnected = true;
        if (fallbackPollingTimeout) {
          clearTimeout(fallbackPollingTimeout);
          fallbackPollingTimeout = null;
        }
      };
      es.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'new_message' || data.type === 'conversation_updated') {
            await fetchConversations(0, false);
            if (currentConversation && data.data?.conversation_id === currentConversation.id) {
              await fetchMessages(currentConversation.id, false);
              setConversations(prev => prev.map(c => 
                c.id === currentConversation.id ? { ...c, unread_count: 0 } : c
              ));
            }
          }
        } catch {}
      };
      es.onerror = () => {
        es.close();
        sseToken = null;
        sseConnected = false;
        startFallbackPolling();
        setTimeout(() => connectSSE(), 5000);
      };
      eventSourceRef.current = es;
    };

    connectSSE();
    return () => {
      eventSourceRef.current?.close();
      if (tokenRefreshTimeout) clearTimeout(tokenRefreshTimeout);
      if (fallbackPollingTimeout) clearTimeout(fallbackPollingTimeout);
    };
  }, [currentConversation, fetchConversations]);

  const contactName = currentConversation?.assessor_name || currentConversation?.contact_name || 'Contato';

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="flex-shrink-0 px-6 py-5 bg-white border-b border-gray-200 flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Conversas</h1>
          <p className="text-gray-500 text-sm mt-1">Visualize e gerencie todas as conversas do agente</p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-dark transition-colors shadow-sm"
        >
          <Plus className="w-5 h-5" />
          Nova Conversa
        </button>
      </div>

      <div className="flex-1 flex min-h-0 overflow-hidden">
        <div className="w-[380px] flex-shrink-0 bg-white border-r border-gray-200 flex flex-col">
          <div className="p-4 border-b border-gray-200">
            <div className="relative mb-3 flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Buscar..."
                  className="w-full pl-9 pr-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary/20 focus:border-primary focus:bg-white outline-none transition-all"
                />
              </div>
              <button
                onClick={() => setShowAdvancedFilters(true)}
                className={`flex items-center gap-1.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors border ${
                  Object.values(advancedFilters).some(v => v) 
                    ? 'bg-primary/10 text-primary border-primary/30' 
                    : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
                }`}
              >
                <SlidersHorizontal className="w-4 h-4" />
                {Object.values(advancedFilters).filter(v => v).length > 0 && (
                  <span className="w-5 h-5 rounded-full bg-primary text-white text-xs flex items-center justify-center">
                    {Object.values(advancedFilters).filter(v => v).length}
                  </span>
                )}
              </button>
            </div>
            
            <div className="mb-3">
              <p className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wide">Fila de Tickets</p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { value: 'new', label: 'Novos', count: filterCounts.new, color: 'blue', icon: AlertCircle },
                  { value: 'in_progress', label: 'Em Andamento', count: filterCounts.in_progress || filterCounts.open, color: 'amber', icon: Clock },
                  { value: 'solved', label: 'Resolvidos', count: filterCounts.solved_today, color: 'green', icon: CheckCircle2 },
                  { value: 'my_tickets', label: 'Meus', count: filterCounts.my_tickets, color: 'purple', icon: User },
                ].map(f => {
                  const Icon = f.icon;
                  const isActive = ticketFilter === f.value;
                  const colorClasses = {
                    blue: isActive ? 'bg-blue-600 text-white' : 'bg-blue-50 text-blue-700 hover:bg-blue-100 border-blue-200',
                    amber: isActive ? 'bg-amber-500 text-white' : 'bg-amber-50 text-amber-700 hover:bg-amber-100 border-amber-200',
                    green: isActive ? 'bg-green-600 text-white' : 'bg-green-50 text-green-700 hover:bg-green-100 border-green-200',
                    purple: isActive ? 'bg-purple-600 text-white' : 'bg-purple-50 text-purple-700 hover:bg-purple-100 border-purple-200',
                    red: isActive ? 'bg-red-600 text-white' : 'bg-red-50 text-red-700 hover:bg-red-100 border-red-200',
                  };
                  return (
                    <button
                      key={f.value}
                      onClick={() => setTicketFilter(f.value)}
                      className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 border ${colorClasses[f.color]}`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {f.label}
                      {f.count > 0 && (
                        <span className={`min-w-[18px] h-[18px] rounded-full text-xs flex items-center justify-center ${
                          isActive ? 'bg-white/25' : 'bg-white'
                        }`}>
                          {f.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (ticketFilter === '') {
                    setTicketFilter('new');
                  } else {
                    setTicketFilter('');
                    setAdvancedFilters({ conversationType: '', dateRange: '', unit: '', broker: '', category: '' });
                  }
                }}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  ticketFilter === ''
                    ? 'bg-gray-800 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {ticketFilter === '' ? 'Voltar para Novos' : 'Ver Todas'}
              </button>
            </div>
            
            {Object.values(advancedFilters).some(v => v) && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {advancedFilters.conversationType && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-700">
                    {advancedFilters.conversationType === 'bot_active' ? 'Bot' : 'Humano'}
                    <button onClick={() => setAdvancedFilters(prev => ({ ...prev, conversationType: '' }))} className="hover:text-gray-900">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )}
                {advancedFilters.dateRange && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-700">
                    {advancedFilters.dateRange === 'today' ? 'Hoje' : advancedFilters.dateRange === '7d' ? '7 dias' : '30 dias'}
                    <button onClick={() => setAdvancedFilters(prev => ({ ...prev, dateRange: '' }))} className="hover:text-gray-900">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )}
                {advancedFilters.unit && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-700">
                    {advancedFilters.unit}
                    <button onClick={() => setAdvancedFilters(prev => ({ ...prev, unit: '' }))} className="hover:text-gray-900">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )}
                {advancedFilters.broker && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-700">
                    {advancedFilters.broker}
                    <button onClick={() => setAdvancedFilters(prev => ({ ...prev, broker: '' }))} className="hover:text-gray-900">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )}
                {advancedFilters.category && (
                  <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-gray-100 text-gray-700">
                    {CATEGORY_LABELS[advancedFilters.category] || advancedFilters.category}
                    <button onClick={() => setAdvancedFilters(prev => ({ ...prev, category: '' }))} className="hover:text-gray-900">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto min-h-0">
            {isLoading && conversations.length === 0 ? (
              <div className="flex justify-center items-center h-32">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
              </div>
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-gray-500">
                <MessageCircle className="w-10 h-10 mb-3 opacity-30" />
                <p className="text-sm">Nenhuma conversa encontrada</p>
              </div>
            ) : (
              <>
                {conversations.map(conv => (
                  <ConversationItem
                    key={conv.id}
                    conversation={conv}
                    isActive={currentConversation?.id === conv.id}
                    onClick={() => selectConversation(conv)}
                  />
                ))}
                {hasMore && (
                  <div className="p-4">
                    <button
                      onClick={loadMoreConversations}
                      disabled={isLoading}
                      className="w-full py-3 text-sm text-primary hover:bg-primary/5 rounded-lg font-medium transition-colors disabled:opacity-50"
                    >
                      {isLoading ? 'Carregando...' : 'Carregar mais'}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex-1 flex flex-col bg-gray-50 min-h-0">
          {currentConversation ? (
            <>
              <div className="flex-shrink-0 px-6 py-4 bg-white border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 rounded-full flex items-center justify-center text-white font-semibold text-lg ${
                      currentConversation.status === 'human_takeover' ? 'bg-amber-500' : 'bg-gray-400'
                    }`}>
                      {contactName.charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="font-semibold text-gray-900 text-lg">{contactName}</h2>
                        <TicketStatusBadge 
                          ticketStatus={currentConversation.ticket_status} 
                          escalationLevel={currentConversation.escalation_level}
                        />
                      </div>
                      <div className="flex items-center gap-2 text-sm text-gray-500">
                        <span>{formatPhone(currentConversation.phone)}</span>
                        {currentConversation.assessor_unidade && (
                          <span className="text-gray-400">• {currentConversation.assessor_unidade}</span>
                        )}
                        {currentConversation.assessor_broker && (
                          <span className="text-primary font-medium">• {currentConversation.assessor_broker}</span>
                        )}
                      </div>
                      {currentConversation.assigned_to_name && (
                        <div className="text-xs text-amber-600 mt-1">
                          Responsável: {currentConversation.assigned_to_name}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!currentConversation.assigned_to_id ? (
                      <button
                        onClick={takeTicket}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-colors bg-primary text-white hover:bg-primary/90"
                      >
                        <UserCheck className="w-4 h-4" />
                        Assumir Ticket
                      </button>
                    ) : (
                      <>
                        <button
                          onClick={() => updateTicketStatus('solved')}
                          className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium text-sm transition-colors bg-green-100 text-green-700 hover:bg-green-200"
                        >
                          Resolvido
                        </button>
                        <button
                          onClick={releaseTicket}
                          className="flex items-center gap-2 px-3 py-2 rounded-lg font-medium text-sm transition-colors bg-gray-100 text-gray-600 hover:bg-gray-200"
                        >
                          Liberar
                        </button>
                      </>
                    )}
                    <select
                      value={currentConversation.ticket_status || 'new'}
                      onChange={e => updateTicketStatus(e.target.value)}
                      className="px-3 py-2 rounded-lg text-sm border border-gray-200 bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
                    >
                      <option value="new">Novo</option>
                      <option value="open">Aberto</option>
                      <option value="in_progress">Em Andamento</option>
                      <option value="solved">Resolvido</option>
                    </select>
                    <button
                      onClick={toggleTakeover}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg font-medium text-sm transition-colors ${
                        currentConversation.status === 'human_takeover'
                          ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                          : 'bg-primary/10 text-primary hover:bg-primary/20'
                      }`}
                    >
                      {currentConversation.status === 'human_takeover' ? (
                        <>
                          <Bot className="w-4 h-4" />
                          Bot
                        </>
                      ) : (
                        <>
                          <UserCheck className="w-4 h-4" />
                          Humano
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>

              <div 
                ref={messagesContainerRef}
                onScroll={handleMessagesScroll}
                className="flex-1 overflow-y-auto p-6 min-h-0"
              >
                {currentConversation.ticket_summary && currentConversation.escalation_level === 't1' && (
                  <div className="flex justify-center mb-6">
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 max-w-md shadow-sm">
                      <div className="flex items-center gap-2 text-amber-700 text-xs font-medium mb-2">
                        <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                        RESUMO DO CHAMADO
                        {currentConversation.conversation_topic && (
                          <span className="ml-auto bg-amber-100 px-2 py-0.5 rounded text-amber-600">
                            {currentConversation.conversation_topic}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-700 leading-relaxed">
                        {currentConversation.ticket_summary}
                      </p>
                      {currentConversation.escalation_category && (
                        <div className="mt-2 text-xs text-amber-600">
                          Motivo: {CATEGORY_LABELS[currentConversation.escalation_category] || currentConversation.escalation_category}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {messages.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-gray-400">
                    <MessageCircle className="w-16 h-16 mb-4 opacity-30" />
                    <p>Nenhuma mensagem ainda</p>
                  </div>
                ) : (
                  <>
                    {messages.map(msg => (
                      <ChatBubble
                        key={msg.id}
                        message={msg}
                        contactName={contactName}
                        onContextMenu={handleMessageContextMenu}
                      />
                    ))}
                    <div ref={messagesEndRef} />
                  </>
                )}
              </div>

              {currentConversation.assigned_to_id ? (
                <div className="flex-shrink-0 px-6 py-4 bg-white border-t border-gray-200">
                  <div className="flex items-center gap-4">
                    <input
                      type="text"
                      value={messageInput}
                      onChange={e => setMessageInput(e.target.value)}
                      onKeyPress={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                      placeholder="Digite sua mensagem..."
                      className="flex-1 px-5 py-3 bg-gray-50 border border-gray-200 rounded-full text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary/20 focus:border-primary focus:bg-white outline-none transition-all"
                    />
                    <button
                      onClick={sendMessage}
                      disabled={isSending || !messageInput.trim()}
                      className="p-3 bg-primary text-white rounded-full hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {isSending ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex-shrink-0 px-6 py-4 bg-gray-50 border-t border-gray-200">
                  <div className="flex items-center justify-center gap-3 text-gray-500">
                    <UserCheck className="w-5 h-5" />
                    <span className="text-sm">Clique em "Assumir Ticket" para responder</span>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
              <MessageCircle className="w-20 h-20 mb-6 opacity-20" />
              <p className="text-xl font-medium text-gray-500">Selecione uma conversa</p>
              <p className="text-sm mt-2">Clique em uma conversa à esquerda para visualizar</p>
            </div>
          )}
        </div>
      </div>

      <NewConversationModal
        isOpen={showNewModal}
        onClose={() => setShowNewModal(false)}
        onSubmit={startNewConversation}
        isLoading={isCreating}
      />

      {showAdvancedFilters && (
        <div className="fixed inset-0 bg-black/50 flex items-start justify-end z-50">
          <div className="w-[400px] h-full bg-white shadow-xl flex flex-col animate-slide-in-right">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">Filtros Avançados</h2>
              <button
                onClick={() => setShowAdvancedFilters(false)}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <Bot className="w-4 h-4" />
                  Tipo de Conversa
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { value: '', label: 'Todas' },
                    { value: 'bot_active', label: 'Bot' },
                    { value: 'human_takeover', label: 'Humano' }
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setAdvancedFilters(prev => ({ ...prev, conversationType: opt.value }))}
                      className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                        advancedFilters.conversationType === opt.value
                          ? 'bg-primary text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <Calendar className="w-4 h-4" />
                  Período
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: '', label: 'Todo o período' },
                    { value: 'today', label: 'Hoje' },
                    { value: '7d', label: 'Últimos 7 dias' },
                    { value: '30d', label: 'Últimos 30 dias' }
                  ].map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setAdvancedFilters(prev => ({ ...prev, dateRange: opt.value }))}
                      className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                        advancedFilters.dateRange === opt.value
                          ? 'bg-primary text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <Building2 className="w-4 h-4" />
                  Unidade
                </label>
                <select
                  value={advancedFilters.unit}
                  onChange={e => setAdvancedFilters(prev => ({ ...prev, unit: e.target.value }))}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
                >
                  <option value="">Todas as unidades</option>
                  {filterOptions.units.map(u => (
                    <option key={u} value={u}>{u}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <Users className="w-4 h-4" />
                  Broker
                </label>
                <select
                  value={advancedFilters.broker}
                  onChange={e => setAdvancedFilters(prev => ({ ...prev, broker: e.target.value }))}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
                >
                  <option value="">Todos os brokers</option>
                  {filterOptions.brokers.map(b => (
                    <option key={b} value={b}>{b}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                  <Tag className="w-4 h-4" />
                  Categoria de Escalação
                </label>
                <select
                  value={advancedFilters.category}
                  onChange={e => setAdvancedFilters(prev => ({ ...prev, category: e.target.value }))}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 text-sm focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none"
                >
                  <option value="">Todas as categorias</option>
                  {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="p-4 border-t border-gray-200 flex gap-3">
              <button
                onClick={() => {
                  setAdvancedFilters({ conversationType: '', dateRange: '', unit: '', broker: '', category: '' });
                }}
                className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
              >
                Limpar
              </button>
              <button
                onClick={() => setShowAdvancedFilters(false)}
                className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium bg-primary text-white hover:bg-primary-dark transition-colors"
              >
                Aplicar
              </button>
            </div>
          </div>
        </div>
      )}

      {contextMenu && (
        <MessageContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onCopy={handleCopyMessage}
          onDelete={handleDeleteMessage}
        />
      )}
    </div>
  );
}

export default App;
