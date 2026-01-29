import { motion } from 'framer-motion';
import { unitsData } from '../data/unitsData';

export default function BrazilMap({ unitVolumes, hoveredUnit, onHover }) {
  const maxVolume = Math.max(...Object.values(unitVolumes || {}), 1);

  const getPointSize = (volume) => {
    if (!volume) return 12;
    const normalized = volume / maxVolume;
    return 12 + normalized * 20;
  };

  const getPointColor = (volume, isHovered) => {
    if (isHovered) return '#772B21';
    if (!volume) return '#e5dcd7';
    const normalized = volume / maxVolume;
    if (normalized > 0.7) return '#10b981';
    if (normalized > 0.4) return '#f59e0b';
    return '#6b8e23';
  };

  return (
    <svg viewBox="0 0 100 100" className="w-full h-full" style={{ minHeight: '400px' }}>
      <defs>
        <linearGradient id="brazilGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#CFE3DA" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#e5dcd7" stopOpacity="0.5" />
        </linearGradient>
      </defs>

      <path
        d="M25,15 
           C30,10 50,5 70,10
           Q85,15 88,25
           Q92,35 88,50
           Q85,60 80,70
           Q75,78 65,82
           Q55,88 45,85
           Q38,82 35,75
           Q32,70 28,65
           Q22,55 20,45
           Q18,35 20,25
           Q22,18 25,15
           Z"
        fill="url(#brazilGradient)"
        stroke="#c4b8b3"
        strokeWidth="0.5"
      />

      <path d="M50,65 Q55,60 60,65" stroke="#c4b8b3" strokeWidth="0.3" fill="none" opacity="0.5" />
      <path d="M45,50 Q50,45 55,50" stroke="#c4b8b3" strokeWidth="0.3" fill="none" opacity="0.5" />
      <path d="M55,68 Q58,62 65,65" stroke="#c4b8b3" strokeWidth="0.3" fill="none" opacity="0.5" />

      {unitsData.map((unit) => {
        const volume = unitVolumes?.[unit.sigla] || 0;
        const size = getPointSize(volume);
        const isHovered = hoveredUnit === unit.sigla;

        return (
          <motion.g
            key={unit.sigla}
            onMouseEnter={() => onHover(unit.sigla)}
            onMouseLeave={() => onHover(null)}
            style={{ cursor: 'pointer' }}
            animate={{ scale: isHovered ? 1.2 : 1 }}
            transition={{ duration: 0.2 }}
          >
            <motion.circle
              cx={unit.x}
              cy={unit.y}
              r={size / 5}
              fill={getPointColor(volume, isHovered)}
              stroke={isHovered ? '#381811' : '#fff'}
              strokeWidth={isHovered ? 0.8 : 0.4}
              animate={{
                r: isHovered ? size / 4 : size / 5,
              }}
            />
            
            {(isHovered || volume > 0) && (
              <motion.text
                x={unit.x}
                y={unit.y - size / 4 - 2}
                textAnchor="middle"
                fill={isHovered ? '#772B21' : '#5a4f4c'}
                fontSize={isHovered ? 3.5 : 2.5}
                fontWeight={isHovered ? 'bold' : 'normal'}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                {unit.sigla}
              </motion.text>
            )}
            
            {volume > 0 && (
              <motion.text
                x={unit.x}
                y={unit.y + 1}
                textAnchor="middle"
                fill="#fff"
                fontSize={2.5}
                fontWeight="bold"
              >
                {volume}
              </motion.text>
            )}
          </motion.g>
        );
      })}
    </svg>
  );
}
