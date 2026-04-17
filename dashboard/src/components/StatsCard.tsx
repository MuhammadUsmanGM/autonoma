import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  icon: LucideIcon
  accent?: boolean
}

export default function StatsCard({ label, value, icon: Icon, accent }: Props) {
  return (
    <motion.div
      whileHover={{ y: -4, scale: 1.01 }}
      className={`relative overflow-hidden rounded-2xl reflective p-6 transition-premium ${accent ? 'glow-sm' : ''}`}
    >
      {accent && (
        <div className="absolute top-0 right-0 w-24 h-24 bg-[var(--accent)] opacity-[0.03] blur-3xl -mr-8 -mt-8" />
      )}
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</span>
        <div className={`p-2 rounded-lg ${accent ? 'bg-[var(--accent-dim)]' : 'bg-white/[0.03]'}`}>
          <Icon size={18} className={accent ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'} />
        </div>
      </div>
      <p className={`text-3xl font-bold tracking-tight ${accent ? 'text-[var(--accent)]' : 'text-white'}`}>
        {value}
      </p>
    </motion.div>
  )
}
