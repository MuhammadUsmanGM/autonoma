import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'

interface Props {
  isOpen: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  isDestructive?: boolean
  onConfirm: () => void
  onClose: () => void
}

export default function ConfirmDialog({
  isOpen,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = false,
  onConfirm,
  onClose
}: Props) {
  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-6">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/80 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="relative w-full max-w-md bg-[var(--bg-card)] border border-white/10 rounded-3xl shadow-2xl overflow-hidden"
          >
            <div className={`p-1 h-1 w-full ${isDestructive ? 'bg-red-500' : 'bg-[var(--accent)]'}`} />
            
            <div className="p-8 space-y-6">
              <div className="flex items-start justify-between">
                <div className={`p-3 rounded-2xl ${isDestructive ? 'bg-red-500/10 text-red-400' : 'bg-[var(--accent)]/10 text-[var(--accent)]'}`}>
                  <AlertTriangle size={24} />
                </div>
                <button 
                  onClick={onClose}
                  className="p-2 rounded-xl border border-white/5 hover:bg-white/5 text-white/20 hover:text-white transition-all"
                >
                  <X size={18} />
                </button>
              </div>

              <div className="space-y-2">
                <h3 className="text-xl font-bold text-white tracking-tight">{title}</h3>
                <p className="text-sm text-[var(--text-muted)] leading-relaxed">{description}</p>
              </div>

              <div className="flex gap-3 pt-4">
                <button 
                  onClick={onClose}
                  className="flex-1 px-6 py-3 rounded-xl border border-white/10 text-sm font-bold text-[var(--text-muted)] hover:bg-white/5 hover:text-white transition-all cursor-pointer"
                >
                  {cancelLabel}
                </button>
                <button 
                  onClick={() => { onConfirm(); onClose(); }}
                  className={`flex-1 px-6 py-3 rounded-xl text-sm font-bold shadow-lg transition-all cursor-pointer hover:scale-[1.02] active:scale-[0.98] ${
                    isDestructive 
                      ? 'bg-red-500 text-white shadow-red-500/20' 
                      : 'bg-[var(--accent)] text-black shadow-[var(--accent-glow)]'
                  }`}
                >
                  {confirmLabel}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
