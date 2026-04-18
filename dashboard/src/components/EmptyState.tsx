import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'

interface Props {
  icon: LucideIcon
  title: string
  description: string
  actionLabel?: string
  onAction?: () => void
}

export default function EmptyState({ icon: Icon, title, description, actionLabel, onAction }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="w-full flex flex-col items-center justify-center p-12 text-center rounded-3xl reflective border border-dashed border-white/10"
    >
      <div className="w-16 h-16 rounded-full bg-white/[0.03] flex items-center justify-center mb-6">
        <Icon size={32} className="text-white/10" />
      </div>
      <h3 className="text-lg font-bold text-white mb-2 tracking-tight uppercase tracking-widest">{title}</h3>
      <p className="text-sm text-[var(--text-muted)] max-w-xs leading-relaxed mb-8">{description}</p>
      
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          className="px-6 py-2.5 rounded-xl bg-white/5 border border-white/10 text-sm font-bold text-white hover:bg-white/10 transition-all cursor-pointer shadow-xl hover:scale-105 active:scale-95"
        >
          {actionLabel}
        </button>
      )}
    </motion.div>
  )
}
