import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

const feedbackTypeStyles = {
  sugestao: 'bg-blue-100 text-blue-800',
  elogio: 'bg-green-100 text-green-800',
  reclamacao: 'bg-red-100 text-red-800',
  duvida: 'bg-yellow-100 text-yellow-800',
};

const sentimentEmojis = {
  positivo: '😊',
  neutro: '😐',
  negativo: '😞',
};

export default function FeedbacksList({ feedbacks }) {
  const [expanded, setExpanded] = useState(false);

  const displayFeedbacks = feedbacks?.slice(0, expanded ? 10 : 3) || [];

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center">
          <h3 className="text-base font-semibold text-foreground">Feedbacks Recentes</h3>
          <InfoTooltip text="Feedbacks enviados pelos assessores sobre o atendimento do agente IA." />
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-muted hover:text-primary transition-colors"
        >
          {expanded ? 'Ver menos' : 'Ver todos'}
          <svg
            className={`w-4 h-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      <AnimatePresence mode="popLayout">
        <div className="space-y-4">
          {displayFeedbacks.map((feedback, index) => (
            <motion.div
              key={feedback.id || index}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ delay: index * 0.05 }}
              className="p-4 bg-gray-50 rounded-lg"
            >
              <div className="flex justify-between items-start mb-3">
                <div>
                  <p className="font-medium text-foreground">{feedback.assessor_name || 'Anonimo'}</p>
                  <p className="text-xs text-muted">{feedback.unidade}</p>
                </div>
                <div className="flex items-center gap-2">
                  {feedback.feedback_type && (
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${feedbackTypeStyles[feedback.feedback_type] || 'bg-gray-100 text-gray-600'}`}>
                      {feedback.feedback_type}
                    </span>
                  )}
                  {feedback.sentiment && (
                    <span className="text-lg">{sentimentEmojis[feedback.sentiment] || '😐'}</span>
                  )}
                </div>
              </div>
              
              <p className="text-sm text-foreground leading-relaxed mb-2">
                {feedback.feedback_text}
              </p>
              
              <p className="text-xs text-muted">
                {feedback.created_at ? new Date(feedback.created_at).toLocaleDateString('pt-BR', {
                  day: '2-digit',
                  month: '2-digit',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit'
                }) : ''}
              </p>
            </motion.div>
          ))}
          
          {displayFeedbacks.length === 0 && (
            <p className="text-center text-muted py-8">Nenhum feedback disponivel</p>
          )}
        </div>
      </AnimatePresence>
    </div>
  );
}
