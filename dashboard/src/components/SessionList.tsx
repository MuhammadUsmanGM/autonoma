import { MessageSquare } from 'lucide-react'
import type { Session } from '../types'

interface Props {
  sessions: Session[]
  selected: string | null
  onSelect: (id: string) => void
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
    ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

const CHANNEL_COLORS: Record<string, string> = {
  cli: 'text-green-400',
  telegram: 'text-blue-400',
  discord: 'text-indigo-400',
  whatsapp: 'text-emerald-400',
  rest: 'text-[var(--accent)]',
  dashboard: 'text-[var(--accent)]',
}

export default function SessionList({ sessions, selected, onSelect }: Props) {
  if (sessions.length === 0) {
    return (
      <p className="text-sm text-[var(--text-muted)] py-8 text-center">
        No sessions yet.
      </p>
    )
  }

  return (
    <div className="space-y-1">
      {sessions.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-all cursor-pointer ${
            selected === s.id
              ? 'bg-[var(--accent-dim)] border border-[var(--accent)]/20'
              : 'hover:bg-white/[0.03] border border-transparent'
          }`}
        >
          <MessageSquare size={16} className={CHANNEL_COLORS[s.channel] || 'text-[var(--text-muted)]'} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">
              <span className={CHANNEL_COLORS[s.channel] || 'text-[var(--text-muted)]'}>
                {s.channel}
              </span>
              <span className="text-[var(--text-muted)] font-normal ml-2 text-xs">
                {s.id.slice(-6)}
              </span>
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">{formatDate(s.modified)}</p>
          </div>
        </button>
      ))}
    </div>
  )
}
