import { LayoutDashboard, MessageSquare, Brain, History, Activity, Settings, ListTodo, Sparkles, Bell, Globe, Plug, Terminal, Webhook, Users } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNotifications } from '../contexts/NotificationsContext'
import LiveLogStream from './LiveLogStream'
import type { Page } from '../types'
import { useState } from 'react'
import { X } from 'lucide-react'

const NAV_GROUPS: { label: string; items: { page: Page; label: string; icon: typeof LayoutDashboard }[] }[] = [
  {
    label: 'Workspace',
    items: [
      { page: 'overview', label: 'Overview', icon: LayoutDashboard },
      { page: 'chat', label: 'Chat', icon: MessageSquare },
      { page: 'memory', label: 'Memory', icon: Brain },
      { page: 'sessions', label: 'Sessions', icon: History },
      { page: 'tasks', label: 'Tasks', icon: ListTodo },
    ],
  },
  {
    label: 'Connections',
    items: [
      { page: 'channels', label: 'Channels', icon: Globe },
      { page: 'connectors', label: 'Integrations', icon: Plug },
      { page: 'contacts', label: 'Contacts', icon: Users },
    ],
  },
  {
    label: 'Activity',
    items: [
      { page: 'traces', label: 'Agent runs', icon: Activity },
      { page: 'webhooks', label: 'Webhook history', icon: Webhook },
      { page: 'logs', label: 'Log history', icon: Terminal },
    ],
  },
  {
    label: 'Settings',
    items: [
      { page: 'soul', label: 'Identity', icon: Sparkles },
      { page: 'settings', label: 'Settings', icon: Settings },
    ],
  },
]

import ThemeToggle from './ThemeToggle'

interface Props {
  current: Page
  onChange: (page: Page) => void
  onToggleAlerts: () => void
  mobileOpen: boolean
  onClose: () => void
}

export default function Sidebar({ current, onChange, onToggleAlerts, mobileOpen, onClose }: Props) {
  const { unreadCount } = useNotifications()
  const [showDebug, setShowDebug] = useState(false)

  return (
    <>
    <div
      onClick={onClose}
      className={`fixed inset-0 z-40 bg-black/40 lg:hidden ${mobileOpen ? 'block' : 'hidden'}`}
      aria-hidden="true"
    />
    <aside className={`w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-sidebar)] flex flex-col h-screen sticky top-0 z-50 font-sans transition-transform duration-200 max-lg:fixed max-lg:left-0 max-lg:top-0 max-lg:bottom-0 ${mobileOpen ? 'max-lg:translate-x-0' : 'max-lg:-translate-x-full'}`}>
      {/* Brand & Alerts */}
      <div className="px-5 py-5 flex items-center justify-between border-b border-[var(--border)]">
        <img 
          src="/logo.webp" 
          alt="Autonoma" 
          className="h-8 w-auto object-contain"
        />
        
        <button 
          onClick={onToggleAlerts}
          className="relative p-2 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] hover:bg-[var(--overlay)] transition-all cursor-pointer group"
        >
          <Bell size={18} className="text-[var(--text-muted)] group-hover:text-[var(--text)] transition-colors" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 w-4">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--accent)] opacity-75"></span>
              <span className="relative inline-flex rounded-full h-4 w-4 bg-[var(--accent)] text-[9px] font-bold text-black items-center justify-center">
                {unreadCount}
              </span>
            </span>
          )}
        </button>
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="lg:hidden min-h-11 min-w-11 inline-flex items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-faint)] hover:text-[var(--text)]"
        >
          <X size={19} />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-4 space-y-1 custom-scrollbar">
        {NAV_GROUPS.map(({ label, items }, groupIndex) => (
          <div key={label} className={groupIndex > 0 ? 'mt-5 border-t border-[var(--border)] pt-4' : ''}>
            <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">{label}</p>
            <div className="space-y-1">
              {items.map(({ page, label: itemLabel, icon: Icon }) => {
                const active = current === page
                return (
                  <button
                    key={page}
                    onClick={() => onChange(page)}
                    className={`w-full relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                      active ? 'text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                    }`}
                  >
                    {active && (
                      <motion.div
                        layoutId="active-nav"
                        className="absolute inset-0 bg-[var(--accent-dim)] border border-[var(--accent)]/20 rounded-lg"
                      />
                    )}
                    <Icon size={17} className="relative z-10" />
                    <span className="relative z-10">{itemLabel}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3 space-y-3 border-t border-[var(--border)]">
        <div className="flex justify-center">
          <ThemeToggle />
        </div>
        
        <button 
          onClick={() => setShowDebug(true)}
          className="w-full px-4 py-3 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] flex items-center justify-between hover:bg-[var(--overlay)] transition-all group"
        >
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] shadow-[0_0_8px_var(--success)] animate-pulse" />
            <span className="text-[11px] font-bold text-[var(--text-muted)] group-hover:text-white uppercase tracking-widest">Live logs</span>
          </div>
          <span className="text-[10px] text-[var(--text-faint)] font-mono">DEBUG</span>
        </button>
      </div>

      {/* Live Log Drawer Overlay */}
      <AnimatePresence>
        {showDebug && (
          <div className="fixed inset-0 z-[100] flex items-end justify-center pointer-events-none">
             <motion.div 
               initial={{ opacity: 0 }}
               animate={{ opacity: 1 }}
               exit={{ opacity: 0 }}
               onClick={() => setShowDebug(false)}
               className="absolute inset-0 bg-black/60 backdrop-blur-md pointer-events-auto"
             />
             <motion.div 
               initial={{ y: '100%' }}
               animate={{ y: 0 }}
               exit={{ y: '100%' }}
               transition={{ type: 'spring', damping: 25, stiffness: 150 }}
               className="relative w-full max-w-6xl h-[60vh] bg-black border-t border-white/10 rounded-t-3xl shadow-2xl overflow-hidden pointer-events-auto flex flex-col"
             >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-white/[0.02]">
                   <div className="flex items-center gap-3">
                      <Terminal size={18} className="text-[var(--accent)]" />
                      <div>
                        <h3 className="text-sm font-bold text-white uppercase tracking-widest">Live logs</h3>
                        <p className="text-[10px] text-white/20">Connection: {window.location.host}/api/ws</p>
                      </div>
                   </div>
                   <button 
                     onClick={() => setShowDebug(false)}
                     className="p-2 rounded-xl hover:bg-white/5 text-white/20 hover:text-white transition-all"
                   >
                     <X size={20} />
                   </button>
                </div>
                <div className="flex-1 p-6 overflow-hidden">
                   <LiveLogStream />
                </div>
             </motion.div>
          </div>
        )}
      </AnimatePresence>
    </aside>
    </>
  )
}
