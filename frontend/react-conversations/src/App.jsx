import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Plus, User, Bot, Send, UserCheck, Loader2, MessageCircle, CheckCheck } from 'lucide-react';

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
  const styles = {
    bot_active: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    human_takeover: 'bg-amber-100 text-amber-700 border-amber-200',
    closed: 'bg-gray-100 text-gray-500 border-gray-200',
  };
  const labels = {
    bot_active: 'Bot',
    human_takeover: 'Humano',
    closed: 'Encerrada',
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${styles[status] || 'bg-gray-100 border-gray-200'}`}>
      {labels[status] || status}
    </span>
  );
}

function ChatBubble({ message, contactName }) {
  const isOutbound = message.direction === 'outbound';
  const senderLabels = { bot: 'Agente IA', human: 'Operador' };
  const senderName = isOutbound ? senderLabels[message.sender_type] || 'Sistema' : contactName || 'Contato';
  const time = formatTime(message.created_at);
  const content = message.body || message.transcription || '[Mídia]';

  if (isOutbound) {
    return (
      <div className="flex items-start gap-2.5 justify-end mb-4">
        <div className={`flex flex-col w-full max-w-[320px] leading-1.5 p-4 border rounded-s-xl rounded-ee-xl ${
          message.sender_type === 'bot' 
            ? 'bg-blue-600 border-blue-600' 
            : 'bg-emerald-600 border-emerald-600'
        }`}>
          <div className="flex items-center space-x-2 rtl:space-x-reverse mb-1">
            <span className="text-sm font-semibold text-white">{senderName}</span>
            <span className="text-xs text-white/70">{time}</span>
          </div>
          <p className="text-sm font-normal text-white whitespace-pre-wrap">{content}</p>
          <div className="flex items-center justify-end gap-1 mt-1.5">
            <CheckCheck className="w-3.5 h-3.5 text-white/70" />
            <span className="text-xs text-white/70">Enviada</span>
          </div>
        </div>
        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          message.sender_type === 'bot' ? 'bg-blue-100' : 'bg-emerald-100'
        }`}>
          {message.sender_type === 'bot' ? (
            <Bot className="w-4 h-4 text-blue-600" />
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
        <User className="w-4 h-4 text-gray-600" />
      </div>
      <div className="flex flex-col w-full max-w-[320px] leading-1.5 p-4 border border-gray-200 bg-gray-100 rounded-e-xl rounded-es-xl">
        <div className="flex items-center space-x-2 rtl:space-x-reverse mb-1">
          <span className="text-sm font-semibold text-gray-900">{senderName}</span>
          <span className="text-xs text-gray-500">{time}</span>
        </div>
        <p className="text-sm font-normal text-gray-900 whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  );
}

function ConversationItem({ conversation, isActive, onClick }) {
  const displayName = conversation.assessor_name || conversation.contact_name || 'Desconhecido';
  const initials = displayName.charAt(0).toUpperCase();
  
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-3 p-3 cursor-pointer transition-all duration-150 border-l-4 ${
        isActive 
          ? 'bg-blue-50 border-l-blue-600' 
          : 'bg-white border-l-transparent hover:bg-gray-50'
      }`}
    >
      <div className="relative flex-shrink-0">
        <div className={`w-12 h-12 rounded-full flex items-center justify-center text-white font-semibold text-sm ${
          conversation.status === 'human_takeover' ? 'bg-amber-500' : 'bg-gray-400'
        }`}>
          {initials}
        </div>
        {conversation.status === 'bot_active' && (
          <div className="absolute -bottom-0.5 -right-0.5 w-4 h-4 rounded-full bg-emerald-500 border-2 border-white flex items-center justify-center">
            <Bot className="w-2.5 h-2.5 text-white" />
          </div>
        )}
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <span className="font-semibold text-gray-900 text-sm truncate">{displayName}</span>
          <span className="text-xs text-gray-500 flex-shrink-0 ml-2">{formatTimeAgo(conversation.last_message_at)}</span>
        </div>
        <div className="text-xs text-gray-500 mb-1">{formatPhone(conversation.phone)}</div>
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-600 truncate flex-1">{conversation.last_message_preview || 'Sem mensagens'}</p>
          <StatusBadge status={conversation.status} />
        </div>
      </div>
      
      {conversation.unread_count > 0 && (
        <div className="flex-shrink-0 w-5 h-5 rounded-full bg-red-500 flex items-center justify-center">
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
      <div className="bg-white rounded-lg w-full max-w-md mx-4 shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="font-semibold text-lg text-gray-900">Nova Conversa</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
        </div>
        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Número de Telefone</label>
            <input
              type="text"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="Ex: 5511999999999"
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
            />
            <p className="text-xs text-gray-500 mt-1.5">Formato: código do país + DDD + número</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Mensagem Inicial</label>
            <textarea
              value={message}
              onChange={e => setMessage(e.target.value)}
              placeholder="Digite a mensagem..."
              rows={4}
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors resize-none"
            />
          </div>
        </div>
        <div className="px-6 py-4 border-t border-gray-200 flex gap-3 justify-end bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-2 text-gray-600 hover:text-gray-800 font-medium transition-colors">
            Cancelar
          </button>
          <button
            onClick={handleSubmit}
            disabled={isLoading}
            className="px-5 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
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
      
      setConversations(prev => {
        const newList = append ? [...prev, ...items] : items;
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
    setCurrentConversation(conv);
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
      const items = listData.items || [];
      setConversations(items);
      setTotalCount(listData.total || 0);
      setHasMore(items.length < (listData.total || 0));
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
    const connectSSE = () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
      const es = new EventSource(`${API_BASE}/conversations/stream`);
      es.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'new_message' || data.type === 'conversation_updated') {
            await fetchConversations(0, false);
            if (currentConversation && data.data?.conversation_id === currentConversation.id) {
              await fetchMessages(currentConversation.id, false);
            }
          }
        } catch {}
      };
      es.onerror = () => {
        es.close();
        setTimeout(connectSSE, 5000);
      };
      eventSourceRef.current = es;
    };
    connectSSE();
    return () => eventSourceRef.current?.close();
  }, [currentConversation, fetchConversations]);

  const contactName = currentConversation?.assessor_name || currentConversation?.contact_name || 'Contato';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex-shrink-0 flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Conversas</h1>
          <p className="text-gray-500 text-sm">Visualize e gerencie todas as conversas do agente</p>
        </div>
        <button
          onClick={() => setShowNewModal(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Nova Conversa
        </button>
      </div>

      <div className="flex-1 grid grid-cols-[360px_1fr] gap-4 min-h-0 overflow-hidden">
        <div className="bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden shadow-sm">
          <div className="p-3 border-b border-gray-100 bg-gray-50">
            <div className="relative mb-2.5">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Buscar por número ou nome..."
                className="w-full pl-9 pr-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
              />
            </div>
            <div className="flex gap-1.5">
              {[{ value: '', label: 'Todas' }, { value: 'bot_active', label: 'Bot' }, { value: 'human_takeover', label: 'Humano' }].map(f => (
                <button
                  key={f.value}
                  onClick={() => setStatusFilter(f.value)}
                  className={`flex-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    statusFilter === f.value
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-gray-600 border border-gray-200 hover:bg-gray-100'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-gray-100 min-h-0">
            {isLoading && conversations.length === 0 ? (
              <div className="flex justify-center items-center h-32">
                <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
              </div>
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-gray-400">
                <MessageCircle className="w-8 h-8 mb-2 opacity-50" />
                <span className="text-sm">Nenhuma conversa</span>
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
                  <button
                    onClick={loadMoreConversations}
                    disabled={isLoading}
                    className="w-full py-3 text-sm text-blue-600 hover:bg-blue-50 font-medium flex items-center justify-center gap-2 transition-colors"
                  >
                    {isLoading ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      'Carregar mais conversas'
                    )}
                  </button>
                )}
              </>
            )}
          </div>
          {conversations.length > 0 && (
            <div className="flex-shrink-0 px-3 py-2 border-t border-gray-100 bg-gray-50 text-xs text-gray-500 text-center">
              Exibindo {conversations.length} {totalCount > 0 ? `de ${totalCount}` : ''} conversas
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden shadow-sm">
          {!currentConversation ? (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
              <div className="w-20 h-20 rounded-full bg-gray-100 flex items-center justify-center mb-4">
                <MessageCircle className="w-10 h-10 text-gray-300" />
              </div>
              <h3 className="text-lg font-semibold text-gray-700 mb-1">Selecione uma conversa</h3>
              <p className="text-sm">Clique em uma conversa à esquerda para visualizar</p>
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-semibold ${
                    currentConversation.status === 'human_takeover' ? 'bg-amber-500' : 'bg-gray-400'
                  }`}>
                    {contactName.charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900 text-sm">{contactName}</h3>
                    <p className="text-xs text-gray-500">{formatPhone(currentConversation.phone)}</p>
                  </div>
                </div>
                <button
                  onClick={toggleTakeover}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    currentConversation.status === 'human_takeover'
                      ? 'bg-emerald-100 text-emerald-700 hover:bg-emerald-200'
                      : 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                  }`}
                >
                  {currentConversation.status === 'human_takeover' ? (
                    <>
                      <Bot className="w-3.5 h-3.5" />
                      Devolver ao Agente
                    </>
                  ) : (
                    <>
                      <UserCheck className="w-3.5 h-3.5" />
                      Assumir Conversa
                    </>
                  )}
                </button>
              </div>

              <div 
                ref={messagesContainerRef}
                onScroll={handleMessagesScroll}
                className="flex-1 overflow-y-auto p-4 bg-gray-50 min-h-0"
              >
                {messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                    Nenhuma mensagem ainda
                  </div>
                ) : (
                  <>
                    {messages.map((msg) => (
                      <ChatBubble key={msg.id} message={msg} contactName={contactName} />
                    ))}
                    <div ref={messagesEndRef} />
                  </>
                )}
              </div>

              <div className="p-3 border-t border-gray-200 bg-white flex gap-2">
                <input
                  type="text"
                  value={messageInput}
                  onChange={e => setMessageInput(e.target.value)}
                  onKeyPress={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
                  placeholder="Digite sua mensagem..."
                  className="flex-1 px-4 py-2.5 bg-gray-100 border border-gray-200 rounded-full text-sm text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:bg-white outline-none transition-all"
                />
                <button
                  onClick={sendMessage}
                  disabled={isSending || !messageInput.trim()}
                  className="px-4 py-2.5 bg-blue-600 text-white rounded-full font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
                >
                  {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <NewConversationModal
        isOpen={showNewModal}
        onClose={() => setShowNewModal(false)}
        onSubmit={startNewConversation}
        isLoading={isCreating}
      />
    </div>
  );
}

export default App;
