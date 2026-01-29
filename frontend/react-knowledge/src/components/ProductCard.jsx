import { motion } from 'framer-motion';
import { FileText, Calendar } from 'lucide-react';
import { StatusBadge } from './StatusBadge';

function getProductStatus(product) {
  if (product.status === 'archived') return 'archived';
  
  const now = new Date();
  const expiring = product.materials?.some(m => {
    if (m.valid_until) {
      const validUntil = new Date(m.valid_until);
      const daysUntil = (validUntil - now) / (1000 * 60 * 60 * 24);
      return daysUntil > 0 && daysUntil <= 30;
    }
    return false;
  });
  
  if (expiring) return 'expirando';
  return 'ativo';
}

export function ProductCard({ product, onClick }) {
  const status = getProductStatus(product);
  const materialsCount = product.materials_count ?? product.materials?.length ?? 0;
  const blocksCount = product.blocks_count ?? product.materials?.reduce((acc, m) => acc + (m.blocks?.length || 0), 0) ?? 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2, boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)' }}
      onClick={() => onClick(product)}
      className="bg-card rounded-card border border-border p-5 shadow-card cursor-pointer"
    >
      <div className="flex justify-between items-start mb-3">
        <h3 className="font-semibold text-foreground text-lg">{product.name}</h3>
        <StatusBadge status={status} />
      </div>
      
      <p className="text-sm text-muted mb-3">{product.category || 'Sem categoria'}</p>
      
      {product.ticker && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          <span className="px-2 py-0.5 bg-primary/10 text-primary text-xs font-medium rounded">
            {product.ticker}
          </span>
        </div>
      )}
      
      <div className="flex items-center gap-4 text-sm text-muted">
        <div className="flex items-center gap-1.5">
          <FileText className="w-4 h-4" />
          <span>{materialsCount} materiais</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Calendar className="w-4 h-4" />
          <span>{blocksCount} blocos</span>
        </div>
      </div>
      
      {product.description && (
        <p className="text-sm text-muted mt-3 line-clamp-2">{product.description}</p>
      )}
    </motion.div>
  );
}
