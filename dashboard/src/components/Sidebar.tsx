import { LayoutDashboard, MessageSquare, Brain, History } from 'lucide-react'
import type { Page } from '../types'

const NAV_ITEMS: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'chat', label: 'Chat', icon: MessageSquare },
  { page: 'memory', label: 'Memory', icon: Brain },
  { page: 'sessions', label: 'Sessions', icon: History },
]

interface Props {
  current: Page
  onChange: (page: Page) => void
}

export default function Sidebar({ current, onChange }: Props) {
  return (
    <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--bg-sidebar)] flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-6 border-b border-[var(--border)]">
        <h1 className="text-lg font-semibold tracking-tight">
          <span className="text-[var(--accent)]">Autonoma</span>
        </h1>
        <p className="text-xs text-[var(--text-muted)] mt-0.5">Agent Dashboard</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ page, label, icon: Icon }) => {
          const active = current === page
          return (
            <button
              key={page}
              onClick={() => onChange(page)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                active
                  ? 'bg-[var(--accent-dim)] text-[var(--accent)] glow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5'
              }`}
            >
              <Icon size={18} />
              {label}
            </button>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-[var(--border)]">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[var(--success)] animate-pulse" />
          <span className="text-xs text-[var(--text-muted)]">System Online</span>
        </div>
      </div>
    </aside>
  )
}
