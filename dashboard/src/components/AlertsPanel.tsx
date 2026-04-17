import { motion, AnimatePresence } from 'framer-motion'
import { Bell, X, AlertTriangle, Info, CheckCircle2, Trash2 } from 'lucide-react'
import { useNotifications } from '../contexts/NotificationsContext'

export default function AlertsPanel({ isOpen, onClose }: { isOpen: boolean, onClose: () => void }) {
  const { notifications, markAsRead, markAllAsRead, clearAll } = useNotifications()

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60]"
          />

          {/* Panel */}
          <motion.div
            initial={{ x: 400 }}
            animate={{ x: 0 }}
            exit={{ x: 400 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed top-0 right-0 w-96 h-full bg-[var(--bg-sidebar)] border-l border-[var(--border)] z-[70] flex flex-col shadow-2xl"
          >
            <div className="p-6 border-b border-[var(--border)] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Bell size={18} className="text-[var(--accent)]" />
                <h3 className="text-lg font-bold text-white">System Alerts</h3>
              </div>
              <button 
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-[var(--overlay)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors cursor-pointer"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {notifications.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center opacity-20">
                  <Bell size={48} className="mb-4" />
                  <p className="text-sm font-bold uppercase tracking-widest">Resonance Stable</p>
                  <p className="text-xs mt-1 lowercase">No critical events recorded</p>
                </div>
              ) : (
                notifications.map((n) => (
                  <motion.div
                    key={n.id}
                    layout
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className={`p-4 rounded-2xl border transition-all ${
                      n.read ? 'bg-[var(--bg-faint)] border-[var(--border-faint)] opacity-60' : 'bg-[var(--bg-card)] border-[var(--border)] shadow-lg'
                    }`}
                  >
                    <div className="flex gap-4">
                      <div className={`mt-1 p-2 rounded-lg shrink-0 ${
                        n.type === 'error' ? 'bg-red-500/10 text-red-400' :
                        n.type === 'warning' ? 'bg-yellow-500/10 text-yellow-400' :
                        'bg-[var(--accent)]/10 text-[var(--accent)]'
                      }`}>
                        {n.type === 'error' ? <AlertTriangle size={16} /> :
                         n.type === 'warning' ? <AlertTriangle size={16} /> :
                         n.type === 'success' ? <CheckCircle2 size={16} /> : <Info size={16} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <h4 className="text-[13px] font-bold text-white truncate">{n.title}</h4>
                          <span className="text-[10px] text-white/20 font-mono">
                            {new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                        <p className="text-xs text-[var(--text-muted)] leading-relaxed">{n.message}</p>
                        {!n.read && (
                          <button 
                            onClick={() => markAsRead(n.id)}
                            className="mt-3 text-[10px] font-bold uppercase tracking-widest text-[var(--accent)] hover:underline"
                          >
                            Mark as Handled
                          </button>
                        )}
                      </div>
                    </div>
                  </motion.div>
                ))
              )}
            </div>

            {notifications.length > 0 && (
              <div className="p-4 border-t border-[var(--border)] flex gap-3">
                <button 
                  onClick={markAllAsRead}
                  className="flex-1 py-3 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] text-[10px] font-bold uppercase tracking-widest text-[var(--text)] hover:bg-[var(--overlay)] transition-colors"
                >
                  Clear Unread
                </button>
                <button 
                  onClick={clearAll}
                  className="p-3 rounded-xl bg-red-400/10 text-red-400 hover:bg-red-400/20 transition-colors"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
