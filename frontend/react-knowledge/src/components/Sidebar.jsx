import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const operationItems = [
  { href: '/insights', label: 'Insights', icon: 'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { href: '/conversas', label: 'Conversas', icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
  { href: '/campanhas', label: 'Campanhas', icon: 'M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z' },
  { href: '/teste-agente', label: 'Testar Agente', icon: 'M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
];

const configItems = [
  { href: '/assessores', label: 'Assessores', icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z' },
  { href: '/admin', label: 'Usuários', icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z' },
  { href: '/agent-brain', label: 'Personalidade IA', icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z' },
];

const knowledgeItems = [
  { href: '/base-conhecimento', label: 'Produtos', icon: 'M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4' },
  { href: '/upload-inteligente', label: 'Upload Inteligente', icon: 'M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12' },
  { href: '/fila-revisao', label: 'Fila de Revisão', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4' },
  { href: '/documentos', label: 'Documentos', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
];

const integrationsItem = { href: '/integrations', label: 'Integrações', icon: 'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1' };

const knowledgeRoutes = ['/base-conhecimento', '/upload-inteligente', '/fila-revisao', '/documentos'];
const configRoutes = ['/assessores', '/admin', '/agent-brain', '/integrations', ...knowledgeRoutes];

function ChevronIcon({ open, className = '' }) {
  return (
    <svg
      className={`w-4 h-4 transition-transform duration-200 ${open ? 'rotate-90' : ''} ${className}`}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  );
}

function NavItem({ item, currentPath, collapsed, indented = false }) {
  const isActive = currentPath === item.href;
  
  return (
    <a
      href={item.href}
      className={`flex items-center gap-3 px-4 py-2.5 mx-2 rounded-lg transition-colors ${
        isActive
          ? 'bg-primary/10 text-primary'
          : 'text-muted hover:bg-gray-50 hover:text-foreground'
      } ${indented ? 'ml-4' : ''}`}
    >
      <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={item.icon} />
      </svg>
      {!collapsed && <span className={`font-medium ${indented ? 'text-sm' : 'text-base'}`}>{item.label}</span>}
    </a>
  );
}

export default function Sidebar({ collapsed, onToggle }) {
  const [currentPath, setCurrentPath] = useState('/insights');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isKnowledgeOpen, setIsKnowledgeOpen] = useState(false);

  useEffect(() => {
    const path = window.location.pathname;
    setCurrentPath(path);
    
    if (configRoutes.includes(path)) {
      setIsSettingsOpen(true);
    }
    if (knowledgeRoutes.includes(path)) {
      setIsKnowledgeOpen(true);
    }
  }, []);

  const handleLogout = () => {
    window.location.href = '/logout';
  };

  return (
    <motion.aside
      animate={{ width: collapsed ? 64 : 260 }}
      className="fixed left-0 top-0 h-screen bg-white border-r border-border flex flex-col z-50"
    >
      <div className="p-4 flex items-center justify-center border-b border-border">
        {!collapsed && (
          <img src="/static/logo.png" alt="SVN" className="h-10" />
        )}
        {collapsed && (
          <img src="/static/logo.png" alt="SVN" className="h-8 w-8 object-contain" />
        )}
      </div>

      <button
        onClick={onToggle}
        className="absolute -right-3 top-16 w-6 h-6 bg-white border border-border rounded-full flex items-center justify-center hover:bg-gray-50 shadow-sm"
      >
        <svg
          className={`w-4 h-4 text-muted transition-transform ${collapsed ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
      </button>

      <nav className="flex-1 py-4 overflow-y-auto overflow-x-hidden">
        {!collapsed && (
          <div className="px-4 mb-2">
            <span className="text-xs font-semibold text-muted uppercase tracking-wider">Operação</span>
          </div>
        )}
        
        {operationItems.map((item) => (
          <NavItem key={item.href} item={item} currentPath={currentPath} collapsed={collapsed} />
        ))}

        <div className="my-4 mx-4 border-t border-border" />

        {!collapsed ? (
          <>
            <button
              onClick={() => setIsSettingsOpen(!isSettingsOpen)}
              className="flex items-center justify-between w-full px-4 py-2.5 mx-2 mr-4 rounded-lg text-muted hover:bg-gray-50 hover:text-foreground transition-colors"
            >
              <div className="flex items-center gap-3">
                <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span className="text-base font-medium">Configurações</span>
              </div>
              <ChevronIcon open={isSettingsOpen} />
            </button>

            <AnimatePresence>
              {isSettingsOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="pl-4">
                    {configItems.map((item) => (
                      <NavItem key={item.href} item={item} currentPath={currentPath} collapsed={collapsed} indented />
                    ))}

                    <button
                      onClick={() => setIsKnowledgeOpen(!isKnowledgeOpen)}
                      className="flex items-center justify-between w-full px-4 py-2.5 ml-4 mr-6 rounded-lg text-muted hover:bg-gray-50 hover:text-foreground transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
                        </svg>
                        <span className="text-sm font-medium">Conhecimento</span>
                      </div>
                      <ChevronIcon open={isKnowledgeOpen} />
                    </button>

                    <AnimatePresence>
                      {isKnowledgeOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden pl-4"
                        >
                          {knowledgeItems.map((item) => (
                            <NavItem key={item.href} item={item} currentPath={currentPath} collapsed={collapsed} indented />
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>

                    <NavItem item={integrationsItem} currentPath={currentPath} collapsed={collapsed} indented />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </>
        ) : (
          <>
            {configItems.map((item) => (
              <NavItem key={item.href} item={item} currentPath={currentPath} collapsed={collapsed} />
            ))}
            {knowledgeItems.map((item) => (
              <NavItem key={item.href} item={item} currentPath={currentPath} collapsed={collapsed} />
            ))}
            <NavItem item={integrationsItem} currentPath={currentPath} collapsed={collapsed} />
          </>
        )}
      </nav>

      <div className="p-4 border-t border-border">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-4 py-3 w-full rounded-lg text-muted hover:bg-red-50 hover:text-danger transition-colors"
        >
          <svg className="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          {!collapsed && <span className="text-base font-medium">Sair</span>}
        </button>
      </div>
    </motion.aside>
  );
}
