import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle, ChevronRight, RefreshCw, Clock } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../api'
import Skeleton from '../components/Skeleton'
import StatsCard from '../components/StatsCard'
import type { TraceItem, TraceStats } from '../types'

const STATUS_COLORS: Record<string, string> = {
  completed: 'text-[var(--success)]',
  error: 'text-[var(--error)]',
  running: 'text-[var(--accent)]',
}

const STATUS_ICONS: Record<string, typeof CheckCircle> = {
  completed: CheckCircle,
  error: AlertTriangle,
  running: Activity,
}

function formatTime(iso: string): string {
  try {
    return new Date(iso + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

function TraceRow({ trace: initialTrace }: { trace: TraceItem }) {
  const [expanded, setExpanded] = useState(false)
  const [trace, setTrace] = useState(initialTrace)
  const [loading, setLoading] = useState(false)

  const handleExpand = async () => {
    if (!expanded) {
      setExpanded(true)
      setLoading(true)
      try {
        const fullTrace = await api.getTrace(initialTrace.id)
        setTrace(fullTrace)
      } catch (e) {
        console.error('Failed to hydrate trace details:', e)
      } finally {
        setLoading(false)
      }
    } else {
      setExpanded(false)
    }
  }

  const Icon = STATUS_ICONS[trace.status] || Activity

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="reflective rounded-xl overflow-hidden"
    >
      <button
        onClick={handleExpand}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-white/[0.03] transition-all cursor-pointer group"
      >
        <motion.div animate={{ rotate: expanded ? 90 : 0 }} transition={{ duration: 0.15 }}>
          <ChevronRight size={14} className="text-[var(--text-muted)]" />
        </motion.div>
        <Icon size={16} className={STATUS_COLORS[trace.status]} />
        <span className="text-[10px] font-mono text-[var(--text-faint)] tracking-wider">{trace.id.slice(0, 8)}</span>
        <span className="text-[10px] px-2 py-0.5 rounded-lg bg-[var(--accent-dim)] text-[var(--accent)] font-bold uppercase tracking-widest">
          {trace.channel}
        </span>
        <span className="flex-1 text-xs truncate text-[var(--text-muted)] group-hover:text-[var(--text)] transition-colors">
          {trace.session_id.slice(0, 24)}
        </span>
        <div className="hidden md:flex items-center gap-2 px-3">
           <div className="w-24 h-1 rounded-full bg-[var(--bg-faint)] overflow-hidden">
               <motion.div 
                 initial={{ width: 0 }}
                 animate={{ width: '100%' }}
                 className={`h-full ${trace.status === 'error' ? 'bg-[var(--error)]' : 'bg-[var(--accent)]'}`}
                 transition={{ duration: 1, ease: 'easeOut' }}
               />
           </div>
        </div>
        <span className="text-[11px] font-mono text-[var(--text-muted)] flex items-center gap-1.5 min-w-[60px] justify-end">
          <Clock size={10} />
          {trace.elapsed_seconds.toFixed(2)}s
        </span>
        <span className="text-[11px] text-[var(--text-muted)] min-w-[80px] text-right">
          {formatTime(trace.started_at)}
        </span>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden bg-black/20"
          >
            <div className="px-5 pb-6 border-t border-[var(--border)]">
              <div className="flex items-center justify-between mt-6 mb-4">
                <div className="flex items-center gap-3">
                  <h4 className="text-[10px] font-bold text-[var(--text)] uppercase tracking-widest">Steps</h4>
                  {loading && <RefreshCw size={10} className="animate-spin text-[var(--text-muted)]" />}
                </div>
                <span className="text-[10px] text-[var(--text-faint)]">Total: {trace.elapsed_seconds.toFixed(2)}s</span>
              </div>

              <ol className="space-y-2">
                {trace.spans.map((span, i) => (
                  <li key={i} className="flex items-start gap-3 rounded-lg bg-[var(--bg-faint)] px-3 py-2">
                    <span className="text-[10px] text-[var(--text-faint)]">{i + 1}.</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-[var(--text)]">{span.stage}</p>
                      <p className="mt-1 truncate text-[10px] font-mono text-[var(--text-muted)]">
                        {JSON.stringify(span.data)}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>

              {/* Tool calls */}
              {trace.tool_calls.length > 0 && (
                <div className="mt-8">
                  <h4 className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">
                    Tools used ({trace.tool_calls.length})
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {trace.tool_calls.map((tc, i) => (
                      <div key={i} className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-3 group hover:border-[var(--accent)]/30 transition-all">
                        <div className={`p-2 rounded-lg ${ (tc as any).is_error ? 'bg-[var(--error)]/10 text-[var(--error)]' : 'bg-[var(--success)]/10 text-[var(--success)]'}`}>
                             {(tc as any).is_error ? <AlertTriangle size={12} /> : <CheckCircle size={12} />}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between mb-1">
                                <span className="font-mono font-bold text-[11px] text-white">{(tc as any).tool}</span>
                                <span className="text-[9px] font-bold text-white/20">{(tc as any).duration?.toFixed(2)}s</span>
                            </div>
                            <p className="text-[10px] text-white/40 truncate font-mono">{(tc as any).result || 'No output captured'}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error */}
              {trace.error && (
                <div className="mt-6 p-4 rounded-xl bg-[var(--error)]/5 border border-[var(--error)]/20 flex gap-3">
                  <AlertTriangle className="text-[var(--error)] shrink-0" size={16} />
                  <span className="text-xs text-[var(--error)] font-mono font-medium leading-relaxed">{trace.error}</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

export default function Traces() {
  const [traces, setTraces] = useState<TraceItem[]>([])
  const [stats, setStats] = useState<TraceStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    api.getTraces(100).then((d) => { setTraces(d); setLoading(false) }).catch((e) => { setError(e.message); setLoading(false) })
    api.getTraceStats().then(setStats).catch(() => {})
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  if (error) {
    return (
      <div className="p-10 flex flex-col items-center justify-center h-full text-center">
        <AlertTriangle className="text-[var(--error)] mb-4" size={32} />
        <h3 className="text-lg font-semibold text-white">Could not load traces</h3>
        <p className="text-[var(--text-muted)] mt-2 max-w-xs">{error}</p>
        <button onClick={() => { setError(''); load() }} className="mt-6 px-6 py-2 rounded-xl bg-white/5 border border-white/10 text-sm font-medium hover:bg-white/10 transition-colors cursor-pointer">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="p-10 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-[var(--text)] mb-2">Agent runs</h2>
          <p className="text-sm text-[var(--text-muted)]">See what the agent did and how long each run took.</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </header>

      {/* Stats bar */}
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-24 reflective rounded-2xl" />)}
        </div>
      ) : stats && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <StatsCard label="Total" value={stats.total} />
          <StatsCard label="Completed" value={stats.completed} accent />
          <StatsCard label="Errors" value={stats.errors} />
          <StatsCard label="Running" value={stats.running} />
          <StatsCard label="Avg Latency" value={`${stats.avg_elapsed_seconds.toFixed(2)}s`} />
        </div>
      )}

      {/* Traces list */}
      {loading ? (
        <Skeleton className="h-64 reflective rounded-2xl" />
      ) : traces.length === 0 ? (
        <div className="text-center py-20 reflective rounded-2xl">
          <Activity size={32} className="mx-auto mb-4 text-white/10" />
          <p className="text-sm text-white/30 font-medium">No agent runs yet</p>
          <p className="text-xs text-white/40 mt-1">Runs will appear after the agent handles a message.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {traces.map((trace) => (
            <TraceRow key={trace.id} trace={trace} />
          ))}
        </div>
      )}
    </div>
  )
}
