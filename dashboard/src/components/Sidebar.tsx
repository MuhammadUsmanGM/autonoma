import { LayoutDashboard, MessageSquare, Brain, History, Activity, Settings, ListTodo, Sparkles, Bell, Globe, Terminal, Webhook } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { useNotifications } from '../contexts/NotificationsContext'
import LiveLogStream from './LiveLogStream'
import type { Page } from '../types'
import { useState } from 'react'
import { X } from 'lucide-react'

const NAV_ITEMS: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'chat', label: 'Chat', icon: MessageSquare },
  { page: 'memory', label: 'Memory', icon: Brain },
  { page: 'sessions', label: 'Sessions', icon: History },
  { page: 'traces', label: 'Traces', icon: Activity },
  { page: 'webhooks', label: 'Webhooks', icon: Webhook },
  { page: 'tasks', label: 'Tasks', icon: ListTodo },
]

import ThemeToggle from './ThemeToggle'

interface Props {
  current: Page
  onChange: (page: Page) => void
  onToggleAlerts: () => void
}

export default function Sidebar({ current, onChange, onToggleAlerts }: Props) {
  const { unreadCount } = useNotifications()
  const [showDebug, setShowDebug] = useState(false)

  return (
    <aside className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-sidebar)] flex flex-col h-screen sticky top-0 z-20 font-sans">
      {/* Brand & Alerts */}
      <div className="px-6 py-9 flex items-center justify-between">
        <img 
          src="/logo.webp" 
          alt="Autonoma" 
          className="h-10 w-auto object-contain brightness-110 drop-shadow-[0_0_15px_rgba(245,158,11,0.2)]" 
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
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-4 space-y-1.5 custom-scrollbar">
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

        {/* Divider */}
        <div className="!my-4 mx-2 border-t border-[var(--border)]" />

        {/* System (separate from data pages) */}
        <div className="space-y-1.5">
          {(() => {
            const active = current === 'soul'
            return (
              <button
                onClick={() => onChange('soul')}
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
                <Sparkles size={18} className={`relative z-10 ${active ? 'text-[var(--accent)]' : 'group-hover:scale-110 transition-transform'}`} />
                <span className="relative z-10">SOUL Editor</span>
              </button>
            )
          })()}
          
          {(() => {
            const active = current === 'channels'
            return (
              <button
                onClick={() => onChange('channels')}
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
                <Globe size={18} className={`relative z-10 ${active ? 'text-[var(--accent)]' : 'group-hover:scale-110 transition-transform'}`} />
                <span className="relative z-10">Channels</span>
              </button>
            )
          })()}
          
          {(() => {
            const active = current === 'logs'
            return (
              <button
                onClick={() => onChange('logs')}
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
                <Terminal size={18} className={`relative z-10 ${active ? 'text-[var(--accent)]' : 'group-hover:scale-110 transition-transform'}`} />
                <span className="relative z-10">Logs</span>
              </button>
            )
          })()}
          
          {(() => {
            const active = current === 'settings'
            return (
              <button
                onClick={() => onChange('settings')}
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
                <Settings size={18} className={`relative z-10 ${active ? 'text-[var(--accent)]' : 'group-hover:scale-110 transition-transform'}`} />
                <span className="relative z-10">Settings</span>
              </button>
            )
          })()}
        </div>
      </nav>

      {/* Footer */}
      <div className="p-4 space-y-4">
        <div className="flex justify-center">
          <ThemeToggle />
        </div>
        
        <button 
          onClick={() => setShowDebug(true)}
          className="w-full px-4 py-3 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] flex items-center justify-between hover:bg-[var(--overlay)] transition-all group"
        >
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] shadow-[0_0_8px_var(--success)] animate-pulse" />
            <span className="text-[11px] font-bold text-[var(--text-muted)] group-hover:text-white uppercase tracking-widest">Live Telemetry</span>
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
                        <h3 className="text-sm font-bold text-white uppercase tracking-widest">Neural Stream Inspector</h3>
                        <p className="text-[10px] text-white/20">Active WebSocket: {window.location.host}/api/ws</p>
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
  )
}
