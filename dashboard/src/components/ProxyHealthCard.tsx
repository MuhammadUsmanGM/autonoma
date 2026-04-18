import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Radio, RefreshCw, AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { api } from '../api'
import type { ProxyHealth } from '../types'

/** Settings-page card that probes each configured proxy and reports whether
 * it can actually reach the channel's upstream (Telegram API, WhatsApp, etc.).
 *
 * Auto-refreshes every 30s; "Recheck" forces an immediate re-probe server-side
 * so the backend's cache stays warm for other clients (TUI, status screen).
 *
 * Rendered empty when no proxies are configured — rather than hide outright,
 * we show a friendly hint so users know this feature exists and how to use it. */
export default function ProxyHealthCard() {
  const [rows, setRows] = useState<ProxyHealth[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [rechecking, setRechecking] = useState<string | null>(null) // channel name or "all"
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await api.getProxyHealth()
      setRows(data)
      setErr(null)
    } catch (e: any) {
      setErr(e?.message || 'Failed to load proxy health')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // 30s cadence matches the backend's 60s poller + recheck button. Any faster
    // and we'd just be re-reading the same cached value; any slower and the UI
    // lags behind real proxy flaps.
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [load])

  const recheck = async (channel?: string) => {
    setRechecking(channel || 'all')
    try {
      const fresh = await api.recheckProxyHealth(channel)
      // Merge the recheck result into rows so the row we just probed flips
      // without waiting for the next auto-refresh.
      setRows((prev) => {
        if (!prev) return fresh
        const byCh = new Map(prev.map((r) => [r.channel, r]))
        fresh.forEach((r) => byCh.set(r.channel, r))
        return Array.from(byCh.values())
      })
      setErr(null)
    } catch (e: any) {
      setErr(e?.message || 'Recheck failed')
    } finally {
      setRechecking(null)
    }
  }

  // No proxies configured at all — render a gentle hint instead of a blank card.
  const hasRows = rows && rows.length > 0
  const anyConfigured = rows?.some((r) => r.configured) ?? false

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
      className="rounded-2xl reflective p-8 space-y-6"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[var(--accent-dim)]">
            <Radio size={18} className="text-[var(--accent)]" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text)] uppercase tracking-widest">
              Proxy Health
            </h3>
            <p className="text-[10px] text-[var(--text-muted)]">
              End-to-end reachability for channel proxies (probes through to the upstream API)
            </p>
          </div>
        </div>
        <button
          onClick={() => recheck()}
          disabled={rechecking !== null || !hasRows}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-white/5 border border-white/10 text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
          title="Re-probe every configured proxy"
        >
          <RefreshCw size={12} className={rechecking === 'all' ? 'animate-spin' : ''} />
          Recheck all
        </button>
      </div>

      {err && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--error)]/10 border border-[var(--error)]/20 text-xs text-[var(--error)]">
          <AlertTriangle size={12} />
          <span>{err}</span>
        </div>
      )}

      {loading && !rows ? (
        <div className="text-xs text-[var(--text-muted)]">Probing proxies…</div>
      ) : !hasRows || !anyConfigured ? (
        <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-white/[0.02] border border-white/5 text-xs text-[var(--text-muted)]">
          <Info size={14} className="shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-medium text-[var(--text)]">No proxies configured.</p>
            <p>
              Set <code className="font-mono text-[var(--accent)]">TELEGRAM_PROXY_URL</code> in
              <code className="font-mono text-[var(--accent)]"> .env</code> (e.g.
              <code className="font-mono"> socks5://127.0.0.1:1080</code>) to route Telegram
              through a SOCKS/HTTP proxy. Probes appear here once the agent restarts.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {rows!.map((r) => (
              <ProxyRow
                key={r.channel}
                data={r}
                onRecheck={() => recheck(r.channel)}
                rechecking={rechecking === r.channel}
              />
            ))}
          </div>

          {rows!.some((r) => r.configured && !r.ok) && (
            <div className="flex items-start gap-2 px-4 py-3 rounded-xl bg-yellow-500/5 border border-yellow-500/20 text-[11px] text-yellow-200/80">
              <Info size={12} className="shrink-0 mt-0.5" />
              <div>
                <span className="font-bold">Proxy down?</span> Free SOCKS proxies expire
                constantly. Consider a permanent option: SSH dynamic tunnel
                (<code className="font-mono">ssh -D 1080 user@vps</code>) on a $4/mo VPS, or
                Cloudflare WARP in proxy mode (application-scoped, not device-wide).
              </div>
            </div>
          )}
        </>
      )}
    </motion.div>
  )
}

function ProxyRow({
  data,
  onRecheck,
  rechecking,
}: {
  data: ProxyHealth
  onRecheck: () => void
  rechecking: boolean
}) {
  const { channel, proxy_url, configured, ok, latency_ms, error, target, checked_at } = data

  // Three-state visual: not-configured (dim), ok (green), down (red). Using
  // separate classes (not a ternary into a single bg) keeps Tailwind happy
  // about purging unused variants.
  const stateClass = !configured
    ? 'bg-white/[0.02] border-white/5 text-[var(--text-muted)]'
    : ok
    ? 'bg-[var(--success)]/5 border-[var(--success)]/20'
    : 'bg-[var(--error)]/5 border-[var(--error)]/20'

  const dotClass = !configured
    ? 'bg-white/20'
    : ok
    ? 'bg-[var(--success)] animate-pulse'
    : 'bg-[var(--error)]'

  const ago = checked_at
    ? `${Math.max(0, Math.round(Date.now() / 1000 - checked_at))}s ago`
    : '—'

  return (
    <div className={`flex items-center gap-4 px-4 py-3 rounded-xl border ${stateClass}`}>
      <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass}`} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[var(--text)]">
            {channel}
          </span>
          {configured ? (
            ok ? (
              <span className="flex items-center gap-1 text-[10px] font-bold text-[var(--success)] uppercase tracking-wider">
                <CheckCircle2 size={10} /> Online
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[10px] font-bold text-[var(--error)] uppercase tracking-wider">
                <AlertTriangle size={10} /> Down
              </span>
            )
          ) : (
            <span className="text-[10px] font-bold text-white/30 uppercase tracking-wider">
              Not configured
            </span>
          )}
        </div>
        <div className="text-[11px] font-mono text-[var(--text-muted)] truncate mt-0.5">
          {proxy_url || '—'}
        </div>
        {configured && (
          <div className="text-[10px] text-white/30 mt-1">
            {ok ? (
              <>→ {target} · {latency_ms} ms · checked {ago}</>
            ) : (
              <>→ {target} · {error || 'unknown error'} · checked {ago}</>
            )}
          </div>
        )}
      </div>

      {configured && (
        <button
          onClick={onRecheck}
          disabled={rechecking}
          className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5 disabled:opacity-30 transition-all cursor-pointer"
          title="Re-probe this proxy"
        >
          <RefreshCw size={12} className={rechecking ? 'animate-spin' : ''} />
        </button>
      )}
    </div>
  )
}
