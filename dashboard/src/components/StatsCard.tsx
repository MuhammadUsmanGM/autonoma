import type { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  icon: LucideIcon
  accent?: boolean
}

export default function StatsCard({ label, value, icon: Icon, accent }: Props) {
  return (
    <div className={`rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5 ${accent ? 'glow-sm' : ''}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-[var(--text-muted)]">{label}</span>
        <Icon size={18} className={accent ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'} />
      </div>
      <p className={`text-2xl font-semibold ${accent ? 'text-[var(--accent)]' : 'text-[var(--text)]'}`}>
        {value}
      </p>
    </div>
  )
}
