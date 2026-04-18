import { motion } from 'framer-motion'
import { AlertCircle, CheckCircle2, XCircle, Clock } from 'lucide-react'

type Status = 'running' | 'stopped' | 'error' | 'disabled' | 'reconnecting'

interface Props {
  status: Status
  error?: string | null
  size?: 'sm' | 'md'
}

const CONFIG: Record<Status, { color: string; bg: string; icon: any, label: string }> = {
  running: { color: 'text-[var(--success)]', bg: 'bg-[var(--success)]', icon: CheckCircle2, label: 'Stable' },
  error: { color: 'text-red-400', bg: 'bg-red-400', icon: AlertCircle, label: 'Crashed' },
  stopped: { color: 'text-white/30', bg: 'bg-white/30', icon: XCircle, label: 'Stopped' },
  disabled: { color: 'text-white/10', bg: 'bg-white/10', icon: XCircle, label: 'Inactive' },
  reconnecting: { color: 'text-yellow-400', bg: 'bg-yellow-400', icon: Clock, label: 'Syncing' },
}

export default function ChannelHealthBadge({ status, error, size = 'md' }: Props) {
  const cfg = CONFIG[status] || CONFIG.stopped

  return (
    <div className="flex items-center gap-2 group relative">
      <div className={`relative ${size === 'sm' ? 'w-2 h-2' : 'w-2.5 h-2.5'}`}>
        <div className={`absolute inset-0 rounded-full ${cfg.bg} ${status === 'running' || status === 'reconnecting' ? 'animate-ping opacity-20' : 'opacity-0'}`} />
        <div className={`absolute inset-0 rounded-full ${cfg.bg} shadow-[0_0_8px_currentColor] ${cfg.color}`} />
      </div>
      <span className={`font-bold uppercase tracking-widest ${size === 'sm' ? 'text-[8px]' : 'text-[10px]'} ${cfg.color}`}>
        {cfg.label}
      </span>

      {error && (
        <div className="absolute bottom-full left-0 mb-2 invisible group-hover:visible z-50">
          <motion.div 
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[var(--bg-card)] border border-red-500/30 text-red-200 text-[10px] px-3 py-2 rounded-xl shadow-2xl min-w-[200px] backdrop-blur-xl"
          >
             <div className="font-bold text-red-400 mb-1 uppercase tracking-tighter">Stack Error</div>
             <p className="font-mono leading-relaxed">{error}</p>
          </motion.div>
        </div>
      )}
    </div>
  )
}
