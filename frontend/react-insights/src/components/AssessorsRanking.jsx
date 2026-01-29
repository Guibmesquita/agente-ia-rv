import { motion } from 'framer-motion';
import InfoTooltip from './InfoTooltip';

export default function AssessorsRanking({ assessors }) {
  const displayAssessors = assessors?.slice(0, 10) || [];
  const maxCount = displayAssessors[0]?.count || 1;

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card h-full">
      <div className="flex items-center mb-4">
        <h3 className="text-base font-semibold text-foreground">Top 10 Assessores</h3>
        <InfoTooltip text="Ranking dos assessores com maior volume de interacoes com o agente IA no periodo selecionado." />
      </div>
      
      <div className="space-y-3">
        {displayAssessors.map((assessor, index) => {
          const percentage = (assessor.count / maxCount) * 100;

          return (
            <motion.div
              key={assessor.name || index}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              className="p-3 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                    index === 0 ? 'bg-yellow-400 text-yellow-900' :
                    index === 1 ? 'bg-gray-300 text-gray-700' :
                    index === 2 ? 'bg-amber-600 text-white' :
                    'bg-gray-100 text-gray-600'
                  }`}>
                    {index + 1}
                  </span>
                  <div className="flex flex-col">
                    <span className="font-medium text-foreground text-sm">
                      {assessor.name || 'Desconhecido'}
                    </span>
                    {assessor.unidade && (
                      <span className="text-xs text-muted">{assessor.unidade}</span>
                    )}
                  </div>
                </div>
                <span className="text-lg font-bold text-foreground">
                  {assessor.count}
                </span>
              </div>
              
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${percentage}%` }}
                  transition={{ duration: 0.5, delay: index * 0.1 }}
                  className="h-full rounded-full bg-svn-orange"
                />
              </div>
            </motion.div>
          );
        })}
        
        {displayAssessors.length === 0 && (
          <p className="text-center text-muted py-4">Nenhum dado disponivel</p>
        )}
      </div>
    </div>
  );
}
