import { useEffect, useState } from 'react'
import { Activity, Clock, AlertTriangle, CheckCircle, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
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

function TraceRow({ trace }: { trace: TraceItem }) {
  const [expanded, setExpanded] = useState(false)
  const Icon = STATUS_ICONS[trace.status] || Activity

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="reflective rounded-xl overflow-hidden"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-white/[0.03] transition-all cursor-pointer group"
      >
        <motion.div animate={{ rotate: expanded ? 90 : 0 }} transition={{ duration: 0.15 }}>
          <ChevronRight size={14} className="text-[var(--text-muted)]" />
        </motion.div>
        <Icon size={16} className={STATUS_COLORS[trace.status]} />
        <span className="text-[10px] font-mono text-white/30 tracking-wider">{trace.id.slice(0, 8)}</span>
        <span className="text-[10px] px-2 py-0.5 rounded-lg bg-[var(--accent-dim)] text-[var(--accent)] font-bold uppercase tracking-widest">
          {trace.channel}
        </span>
        <span className="flex-1 text-xs truncate text-[var(--text-muted)] group-hover:text-[var(--text)] transition-colors">
          {trace.session_id.slice(0, 24)}
        </span>
        <span className="text-[11px] font-mono text-[var(--text-muted)]">
          {trace.elapsed_seconds.toFixed(2)}s
        </span>
        <span className="text-[11px] text-[var(--text-muted)]">
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
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 border-t border-[var(--border)]">
              {/* Spans timeline */}
              <div className="mt-4">
                <h4 className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">Pipeline Stages</h4>
                <div className="space-y-1.5">
                  {trace.spans.map((span, i) => (
                    <div key={i} className="flex items-center gap-3 text-xs">
                      <span className="w-5 text-center text-white/20 font-mono text-[10px]">{i + 1}</span>
                      <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] shadow-[0_0_6px_var(--accent)]" />
                      <span className="font-mono font-bold text-white/70 w-36">{span.stage}</span>
                      <span className="text-white/30 truncate flex-1 font-mono text-[10px]">
                        {JSON.stringify(span.data).slice(0, 100)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Tool calls */}
              {trace.tool_calls.length > 0 && (
                <div className="mt-4">
                  <h4 className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">
                    Tool Invocations ({trace.tool_calls.length})
                  </h4>
                  <div className="space-y-1.5">
                    {trace.tool_calls.map((tc, i) => (
                      <div key={i} className="flex items-center gap-3 text-xs bg-white/[0.02] rounded-lg px-4 py-2">
                        <span className="font-mono font-bold text-[var(--accent)]">
                          {(tc as any).tool}
                        </span>
                        <span className={`text-[10px] font-bold uppercase ${(tc as any).is_error ? 'text-[var(--error)]' : 'text-[var(--success)]'}`}>
                          {(tc as any).is_error ? 'ERR' : 'OK'}
                        </span>
                        <span className="text-white/30 truncate flex-1 font-mono text-[10px]">
                          {(tc as any).result?.slice(0, 100)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error */}
              {trace.error && (
                <div className="mt-4 p-4 rounded-xl bg-[var(--error)]/5 border border-[var(--error)]/20">
                  <span className="text-xs text-[var(--error)] font-mono">{trace.error}</span>
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
        <h3 className="text-lg font-semibold text-white">Telemetry Error</h3>
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
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Execution Traces</h2>
          <p className="text-sm text-[var(--text-muted)]">End-to-end telemetry for every agent invocation</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Sync Traces
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
          <p className="text-sm text-white/30 font-medium">No traces recorded yet</p>
          <p className="text-xs text-white/15 mt-1">Send a message to generate execution telemetry</p>
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
