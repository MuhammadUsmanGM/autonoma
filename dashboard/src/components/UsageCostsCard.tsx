import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { DollarSign, RefreshCw, AlertTriangle, TrendingUp, Coins } from 'lucide-react'
import { api } from '../api'
import type { UsageStats, UsageBucket } from '../types'

/** Settings-page card: token + USD spend, scoped today / week / month,
 * plus a per-model breakdown for the current month.
 *
 * This is the single highest-ask question from operators once an agent is
 * live ("how much have I spent?"); we surface it here rather than on its
 * own page so it sits next to the LLM config that drives the cost. */
function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return `${n}`
}

function formatCost(n: number): string {
  if (n === 0) return '$0.00'
  if (n < 0.01) return `$${n.toFixed(4)}`
  if (n < 1) return `$${n.toFixed(3)}`
  return `$${n.toFixed(2)}`
}

const EMPTY: UsageBucket = { tokens_in: 0, tokens_out: 0, cost_usd: 0, calls: 0 }

export default function UsageCostsCard() {
  const [usage, setUsage] = useState<UsageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.getUsage()
      setUsage(data)
      setErr(null)
    } catch (e: any) {
      setErr(e?.message || 'Failed to load usage')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // 60s cadence — costs don't change every second and this keeps traffic
    // off the JSONL-scan path on big histories.
    const id = setInterval(load, 60_000)
    return () => clearInterval(id)
  }, [load])

  const today = usage?.today ?? EMPTY
  const week = usage?.week ?? EMPTY
  const month = usage?.month ?? EMPTY
  const byModel = usage?.by_model ?? {}
  const modelEntries = Object.entries(byModel).sort(
    (a, b) => b[1].cost_usd - a[1].cost_usd,
  )

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.3 }}
      className="rounded-2xl reflective p-8 space-y-6 lg:col-span-2"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[var(--accent-dim)]">
            <DollarSign size={18} className="text-[var(--accent)]" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text)] uppercase tracking-widest">Usage & Costs</h3>
            <p className="text-[10px] text-[var(--text-muted)]">Token spend across today, this week, and this month</p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-2 rounded-xl bg-white/[0.03] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5 transition-all cursor-pointer disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {err && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-[var(--error)]/10 border border-[var(--error)]/20 text-xs text-[var(--error)]">
          <AlertTriangle size={14} />
          <span>{err}</span>
        </div>
      )}

      {/* Spend buckets */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { key: 'today', label: 'Today', data: today },
          { key: 'week', label: 'This Week', data: week },
          { key: 'month', label: 'This Month', data: month },
        ].map(({ key, label, data }) => (
          <div
            key={key}
            className="rounded-xl border border-[var(--border)] bg-black/20 p-5 space-y-3"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
              <span className="text-[10px] text-[var(--text-faint)] font-mono">{data.calls} calls</span>
            </div>
            <div className="text-2xl font-bold text-[var(--accent)]">{formatCost(data.cost_usd)}</div>
            <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] font-mono pt-2 border-t border-white/5">
              <span>↓ {formatTokens(data.tokens_in)} in</span>
              <span>↑ {formatTokens(data.tokens_out)} out</span>
            </div>
          </div>
        ))}
      </div>

      {/* Per-model breakdown */}
      <div className="pt-4 border-t border-[var(--border)]">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp size={14} className="text-[var(--text-muted)]" />
          <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
            By Model (This Month)
          </span>
        </div>

        {modelEntries.length === 0 ? (
          <div className="flex flex-col items-center py-8 text-center">
            <Coins size={24} className="text-[var(--text-faint)] mb-2" />
            <p className="text-xs text-[var(--text-muted)]">
              {loading ? 'Loading usage…' : 'No LLM calls billed this month yet.'}
            </p>
            <p className="text-[10px] text-[var(--text-faint)] mt-1">
              Send a message to the agent and usage will start tracking here.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {modelEntries.map(([model, bucket]) => {
              const pct = month.cost_usd > 0 ? (bucket.cost_usd / month.cost_usd) * 100 : 0
              return (
                <div
                  key={model}
                  className="flex items-center justify-between gap-4 p-3 rounded-lg bg-white/[0.02] border border-white/5"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-mono text-[var(--text)] truncate">{model}</span>
                      <span className="text-[10px] text-[var(--text-faint)]">
                        {bucket.calls} call{bucket.calls === 1 ? '' : 's'}
                      </span>
                    </div>
                    <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-[var(--accent)] rounded-full transition-all"
                        style={{ width: `${Math.min(100, pct)}%` }}
                      />
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-bold text-[var(--accent)]">{formatCost(bucket.cost_usd)}</div>
                    <div className="text-[10px] text-[var(--text-muted)] font-mono">
                      {formatTokens(bucket.tokens_in + bucket.tokens_out)} tok
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </motion.div>
  )
}
