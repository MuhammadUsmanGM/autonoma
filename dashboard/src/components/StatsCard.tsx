import type { LucideIcon } from 'lucide-react'

interface Props {
  label: string
  value: string | number
  icon?: LucideIcon
  accent?: boolean
}

export default function StatsCard({ label, value, icon: Icon, accent }: Props) {
  return (
    <div className="rounded-lg reflective p-5">
      <div className="flex items-center justify-between mb-5">
        <span className="text-xs font-medium text-[var(--text-muted)]">{label}</span>
        {Icon && (
          <div className={`p-2 rounded-md ${accent ? 'bg-[var(--accent-dim)]' : 'bg-[var(--bg-faint)]'}`}>
            <Icon size={18} className={accent ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'} />
          </div>
        )}
      </div>
      <p className={`text-2xl font-semibold ${accent ? 'text-[var(--accent)]' : 'text-[var(--text)]'}`}>
        {value}
      </p>
    </div>
  )
}
