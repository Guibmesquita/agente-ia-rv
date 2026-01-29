import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export default function InfoTooltip({ text }) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <div className="relative inline-block ml-2">
      <button
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        className="w-4 h-4 rounded-full bg-gray-200 text-gray-500 text-xs flex items-center justify-center hover:bg-gray-300 transition-colors cursor-help"
      >
        i
      </button>
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 5 }}
            className="absolute z-50 w-64 p-3 bg-gray-800 text-white text-xs rounded-lg shadow-lg -left-28 top-6"
          >
            <div className="absolute -top-1 left-1/2 transform -translate-x-1/2 w-2 h-2 bg-gray-800 rotate-45" />
            {text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
