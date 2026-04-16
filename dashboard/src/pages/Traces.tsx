import { useEffect, useState } from 'react'
import { Activity, Clock, AlertTriangle, CheckCircle, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../api'
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

const PRIORITY_LABELS = ['CRITICAL', 'HIGH', 'NORMAL', 'BACKGROUND']

function formatTime(iso: string): string {
  try {
    return new Date(iso + 'Z').toLocaleTimeString()
  } catch {
    return iso
  }
}

function TraceRow({ trace }: { trace: TraceItem }) {
  const [expanded, setExpanded] = useState(false)
  const Icon = STATUS_ICONS[trace.status] || Activity

  return (
    <div className="border border-[var(--border)] rounded-lg bg-[var(--bg-card)] overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-white/5 transition-colors cursor-pointer"
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <Icon size={16} className={STATUS_COLORS[trace.status]} />
        <span className="text-xs font-mono text-[var(--text-muted)]">{trace.id}</span>
        <span className="text-xs px-2 py-0.5 rounded bg-[var(--accent-dim)] text-[var(--accent)]">
          {trace.channel}
        </span>
        <span className="flex-1 text-sm truncate text-[var(--text-muted)]">
          session: {trace.session_id.slice(0, 20)}
        </span>
        <span className="text-xs text-[var(--text-muted)]">
          {trace.elapsed_seconds.toFixed(2)}s
        </span>
        <span className="text-xs text-[var(--text-muted)]">
          {formatTime(trace.started_at)}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-[var(--border)]">
          {/* Spans timeline */}
          <div className="mt-3">
            <h4 className="text-xs font-medium text-[var(--text-muted)] mb-2">Pipeline Stages</h4>
            <div className="space-y-1">
              {trace.spans.map((span, i) => (
                <div key={i} className="flex items-center gap-3 text-xs">
                  <span className="w-4 text-center text-[var(--text-muted)]">{i + 1}</span>
                  <div className="w-2 h-2 rounded-full bg-[var(--accent)]" />
                  <span className="font-mono font-medium w-32">{span.stage}</span>
                  <span className="text-[var(--text-muted)] truncate flex-1">
                    {JSON.stringify(span.data)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Tool calls */}
          {trace.tool_calls.length > 0 && (
            <div className="mt-3">
              <h4 className="text-xs font-medium text-[var(--text-muted)] mb-2">
                Tool Calls ({trace.tool_calls.length})
              </h4>
              <div className="space-y-1">
                {trace.tool_calls.map((tc, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs bg-white/5 rounded px-3 py-1.5">
                    <span className="font-mono font-medium text-[var(--accent)]">
                      {(tc as any).tool}
                    </span>
                    <span className={`text-xs ${(tc as any).is_error ? 'text-[var(--error)]' : 'text-[var(--success)]'}`}>
                      {(tc as any).is_error ? 'error' : 'ok'}
                    </span>
                    <span className="text-[var(--text-muted)] truncate flex-1">
                      {(tc as any).result?.slice(0, 100)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error */}
          {trace.error && (
            <div className="mt-3 p-3 rounded bg-[var(--error)]/10 border border-[var(--error)]/20">
              <span className="text-xs text-[var(--error)]">{trace.error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function Traces() {
  const [traces, setTraces] = useState<TraceItem[]>([])
  const [stats, setStats] = useState<TraceStats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = () => {
      api.getTraces(100).then(setTraces).catch((e) => setError(e.message))
      api.getTraceStats().then(setStats).catch(() => {})
    }
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  if (error) {
    return (
      <div className="p-8">
        <p className="text-[var(--error)]">Failed to load traces: {error}</p>
      </div>
    )
  }

  return (
    <div className="p-8">
      <h2 className="text-xl font-semibold mb-6">Traces</h2>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="text-xs text-[var(--text-muted)]">Total</div>
            <div className="text-2xl font-semibold mt-1">{stats.total}</div>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="text-xs text-[var(--text-muted)]">Completed</div>
            <div className="text-2xl font-semibold mt-1 text-[var(--success)]">{stats.completed}</div>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="text-xs text-[var(--text-muted)]">Errors</div>
            <div className="text-2xl font-semibold mt-1 text-[var(--error)]">{stats.errors}</div>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="text-xs text-[var(--text-muted)]">Running</div>
            <div className="text-2xl font-semibold mt-1 text-[var(--accent)]">{stats.running}</div>
          </div>
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="text-xs text-[var(--text-muted)]">Avg Latency</div>
            <div className="text-2xl font-semibold mt-1">{stats.avg_elapsed_seconds.toFixed(2)}s</div>
          </div>
        </div>
      )}

      {/* Traces list */}
      {traces.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-muted)]">
          <Activity size={40} className="mx-auto mb-3 opacity-50" />
          <p>No traces yet. Send a message to the agent to generate traces.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {traces.map((trace) => (
            <TraceRow key={trace.id} trace={trace} />
          ))}
        </div>
      )}
    </div>
  )
}
