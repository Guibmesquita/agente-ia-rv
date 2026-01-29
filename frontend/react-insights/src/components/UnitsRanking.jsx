import { motion } from 'framer-motion';
import { getUnitName } from '../data/unitsData';
import InfoTooltip from './InfoTooltip';

export default function UnitsRanking({ units, hoveredUnit, onHover }) {
  const displayUnits = units?.slice(0, 10) || [];
  const maxCount = displayUnits[0]?.count || 1;

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card h-full">
      <div className="flex items-center mb-4">
        <h3 className="text-base font-semibold text-foreground">Ranking de Unidades</h3>
        <InfoTooltip text="Ranking das unidades com maior volume de interações no período selecionado." />
      </div>
      
      <div className="space-y-3">
        {displayUnits.map((unit, index) => {
          const isHovered = hoveredUnit === unit.unidade;
          const percentage = (unit.count / maxCount) * 100;

          return (
            <motion.div
              key={unit.unidade}
              onMouseEnter={() => onHover(unit.unidade)}
              onMouseLeave={() => onHover(null)}
              animate={{
                backgroundColor: isHovered ? 'rgba(119, 43, 33, 0.1)' : 'transparent',
                scale: isHovered ? 1.02 : 1,
              }}
              className="p-3 rounded-lg cursor-pointer transition-colors"
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
                  <div>
                    <span className={`font-medium ${isHovered ? 'text-primary' : 'text-foreground'}`}>
                      {unit.unidade}
                    </span>
                    <span className="text-xs text-muted ml-2">
                      {getUnitName(unit.unidade)}
                    </span>
                  </div>
                </div>
                <span className={`text-lg font-bold ${isHovered ? 'text-primary' : 'text-foreground'}`}>
                  {unit.count}
                </span>
              </div>
              
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${percentage}%` }}
                  transition={{ duration: 0.5, delay: index * 0.1 }}
                  className={`h-full rounded-full ${isHovered ? 'bg-primary' : 'bg-svn-green'}`}
                />
              </div>
            </motion.div>
          );
        })}
        
        {displayUnits.length === 0 && (
          <p className="text-center text-muted py-4">Nenhum dado disponível</p>
        )}
      </div>
    </div>
  );
}
