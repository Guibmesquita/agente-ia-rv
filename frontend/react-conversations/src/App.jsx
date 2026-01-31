import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Plus, User, Bot, Send, UserCheck, Loader2, MessageCircle, CheckCheck, MoreVertical, Copy, Reply, Trash2, Forward, X, Phone } from 'lucide-react';

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
  
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-4 px-4 py-4 cursor-pointer transition-all border-b border-gray-100 ${
        isActive 
          ? 'bg-primary/5 border-l-4 border-l-primary' 
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
        <div className="text-xs text-gray-500 mb-1.5">{formatPhone(conversation.phone)}</div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-gray-500 truncate flex-1">{preview}</p>
          <StatusBadge status={conversation.status} />
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

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messageInput, setMessageInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [showNewModal, setShowNewModal] = useState(false);
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

  const fetchConversations = useCallback(async (pageNum = 0, append = false) => {
    setIsLoading(true);
    try {
      const offset = pageNum * PAGE_SIZE;
      let url = `${API_BASE}/conversations/?limit=${PAGE_SIZE}&offset=${offset}`;
      if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;
      if (statusFilter) url += `&status=${statusFilter}`;
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
  }, [searchQuery, statusFilter]);

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
    };
    syncAndLoad();
  }, []);

  useEffect(() => {
    setPage(0);
    const timer = setTimeout(() => fetchConversations(0, false), 300);
    return () => clearTimeout(timer);
  }, [searchQuery, statusFilter]);

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
    let pollingInterval = null;

    const fetchSseToken = async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/sse-token`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          return data.token;
        }
      } catch {}
      return null;
    };

    const connectSSE = async () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
      
      if (!sseToken) {
        sseToken = await fetchSseToken();
      }
      
      if (!sseToken) {
        startPolling();
        return;
      }

      const url = `${API_BASE}/conversations/stream?token=${encodeURIComponent(sseToken)}`;
      const es = new EventSource(url);
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
        setTimeout(() => connectSSE(), 5000);
      };
      eventSourceRef.current = es;
    };

    const startPolling = () => {
      if (pollingInterval) return;
      pollingInterval = setInterval(async () => {
        await fetchConversations(0, false);
        if (currentConversation) {
          await fetchMessages(currentConversation.id, false);
        }
      }, 5000);
    };

    connectSSE();
    return () => {
      eventSourceRef.current?.close();
      if (pollingInterval) clearInterval(pollingInterval);
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
            <div className="relative mb-4">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Buscar por número ou nome..."
                className="w-full pl-12 pr-4 py-3 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-primary/20 focus:border-primary focus:bg-white outline-none transition-all"
              />
            </div>
            <div className="flex gap-2">
              {[{ value: '', label: 'Todas' }, { value: 'bot_active', label: 'Bot' }, { value: 'human_takeover', label: 'Humano' }].map(f => (
                <button
                  key={f.value}
                  onClick={() => setStatusFilter(f.value)}
                  className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    statusFilter === f.value
                      ? 'bg-primary text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
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
              <div className="flex-shrink-0 px-6 py-4 bg-white border-b border-gray-200 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={`w-12 h-12 rounded-full flex items-center justify-center text-white font-semibold text-lg ${
                    currentConversation.status === 'human_takeover' ? 'bg-amber-500' : 'bg-gray-400'
                  }`}>
                    {contactName.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <h2 className="font-semibold text-gray-900 text-lg">{contactName}</h2>
                    <p className="text-sm text-gray-500">{formatPhone(currentConversation.phone)}</p>
                  </div>
                </div>
                <button
                  onClick={toggleTakeover}
                  className={`flex items-center gap-2 px-5 py-2.5 rounded-lg font-medium text-sm transition-colors ${
                    currentConversation.status === 'human_takeover'
                      ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                      : 'bg-primary/10 text-primary hover:bg-primary/20'
                  }`}
                >
                  {currentConversation.status === 'human_takeover' ? (
                    <>
                      <Bot className="w-5 h-5" />
                      Devolver ao Bot
                    </>
                  ) : (
                    <>
                      <UserCheck className="w-5 h-5" />
                      Assumir Conversa
                    </>
                  )}
                </button>
              </div>

              <div 
                ref={messagesContainerRef}
                onScroll={handleMessagesScroll}
                className="flex-1 overflow-y-auto p-6 min-h-0"
              >
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
