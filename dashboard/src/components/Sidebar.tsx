import { LayoutDashboard, MessageSquare, Brain, History, Activity, Bot, Zap } from 'lucide-react'
import { motion } from 'framer-motion'
import type { Page } from '../types'

const NAV_ITEMS: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'chat', label: 'Chat', icon: MessageSquare },
  { page: 'memory', label: 'Memory', icon: Brain },
  { page: 'sessions', label: 'Sessions', icon: History },
  { page: 'traces', label: 'Traces', icon: Activity },
]

interface Props {
  current: Page
  onChange: (page: Page) => void
}

export default function Sidebar({ current, onChange }: Props) {
  return (
    <aside className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-sidebar)] flex flex-col h-screen sticky top-0 z-20">
      {/* Brand */}
      <div className="px-6 py-8 flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-[var(--accent)] flex items-center justify-center glow-sm">
          <Bot size={20} className="text-black" />
        </div>
        <div>
          <h1 className="text-sm font-bold tracking-tight uppercase text-white">
            Autonoma
          </h1>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Zap size={10} className="text-[var(--accent)]" />
            <span className="text-[10px] text-[var(--accent)] font-medium uppercase tracking-wider">Premium FTE</span>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 space-y-1.5">
        {NAV_ITEMS.map(({ page, label, icon: Icon }) => {
          const active = current === page
          return (
            <button
              key={page}
              onClick={() => onChange(page)}
              className={`w-full relative flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all group cursor-pointer ${
                active ? 'text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-white'
              }`}
            >
              {active && (
                <motion.div
                  layoutId="active-nav"
                  className="absolute inset-0 bg-[var(--accent-dim)] border border-[var(--accent)]/10 rounded-xl"
                  transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
                />
              )}
              <Icon size={18} className={`relative z-10 ${active ? 'text-[var(--accent)]' : 'group-hover:scale-110 transition-transform'}`} />
              <span className="relative z-10">{label}</span>
            </button>
          )
        })}
      </nav>

      {/* System Status */}
      <div className="p-4">
        <div className="px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.05] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] shadow-[0_0_8px_var(--success)]" />
            <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide">Live</span>
          </div>
          <span className="text-[10px] text-white/40 font-mono">v0.1.0</span>
        </div>
      </div>
    </aside>
  )
}
