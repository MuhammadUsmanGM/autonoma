import { useEffect, useState, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Radio, RefreshCw, AlertTriangle, CheckCircle2, Info, Pencil, Check, X, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
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

  const saveProxy = async (channel: string, url: string) => {
    // Currently only telegram is wired up server-side; fail loudly if someone
    // tries another channel so we don't silently drop the value.
    if (channel !== 'telegram') {
      toast.error(`Proxy editing is not yet supported for ${channel}`)
      return false
    }
    try {
      await api.updateChannelCredentials(channel, { proxy_url: url })
      toast.success(url ? 'Proxy updated — probing now…' : 'Proxy cleared')
      // Force an immediate recheck so the row flips without waiting for the
      // next 30s poll. Fire-and-forget is fine; the auto-refresh will catch
      // up even if this call loses.
      void recheck(channel)
      return true
    } catch (e: any) {
      toast.error(`Save failed: ${e?.message || e}`)
      return false
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
        <div className="space-y-3">
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-white/[0.02] border border-white/5 text-xs text-[var(--text-muted)]">
            <Info size={14} className="shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-medium text-[var(--text)]">No proxies configured.</p>
              <p>
                Paste a SOCKS or HTTP URL below (e.g.
                <code className="font-mono"> socks5://127.0.0.1:1080</code>) to route
                Telegram through a proxy. Saved instantly — no restart needed.
              </p>
            </div>
          </div>
          {/* Inline "add proxy" for Telegram — renders even when the health
              list is empty so first-time setup doesn't require editing .env. */}
          <InlineProxyEditor
            channel="telegram"
            initial=""
            onSave={(url) => saveProxy('telegram', url)}
          />
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {rows!.map((r) => (
              <ProxyRow
                key={r.channel}
                data={r}
                onRecheck={() => recheck(r.channel)}
                onSave={(url) => saveProxy(r.channel, url)}
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
  onSave,
  rechecking,
}: {
  data: ProxyHealth
  onRecheck: () => void
  onSave: (url: string) => Promise<boolean>
  rechecking: boolean
}) {
  const { channel, proxy_url, configured, ok, latency_ms, error, target, checked_at } = data
  const [editing, setEditing] = useState(false)
  // Only telegram is editable server-side today. Other channels show the
  // pencil greyed-out with a tooltip explaining why.
  const editable = channel === 'telegram'

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
    <div className={`rounded-xl border ${stateClass}`}>
      <div className="flex items-center gap-4 px-4 py-3">
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

        <button
          onClick={() => editable && setEditing((v) => !v)}
          disabled={!editable}
          className={`p-2 rounded-lg transition-all cursor-pointer ${
            editable
              ? 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5'
              : 'text-white/10 cursor-not-allowed'
          }`}
          title={editable ? 'Edit proxy URL' : `Editing not yet supported for ${channel}`}
        >
          <Pencil size={12} />
        </button>
      </div>

      {editing && editable && (
        <div className="border-t border-white/5 px-4 py-3">
          <InlineProxyEditor
            channel={channel}
            initial={proxy_url || ''}
            onSave={async (url) => {
              const ok = await onSave(url)
              if (ok) setEditing(false)
              return ok
            }}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}
    </div>
  )
}

/** Shared input for adding/updating a proxy URL.
 *
 * Kept as a separate component so the "first time configure" hint at the top
 * of the card and the per-row edit pencil use the exact same form. Validates
 * the URL shape client-side (socks5:// / socks4:// / http:// / https://) so
 * garbage doesn't hit the backend, but the backend is the source of truth. */
function InlineProxyEditor({
  channel,
  initial,
  onSave,
  onCancel,
}: {
  channel: string
  initial: string
  onSave: (url: string) => Promise<boolean>
  onCancel?: () => void
}) {
  const [value, setValue] = useState(initial)
  const [saving, setSaving] = useState(false)

  const validate = (v: string): string | null => {
    const t = v.trim()
    if (!t) return null // empty = clear, allowed
    if (!/^(socks5|socks4|http|https):\/\//i.test(t)) {
      return 'Must start with socks5://, socks4://, http:// or https://'
    }
    return null
  }

  const err = validate(value)

  const submit = async (clear = false) => {
    const url = clear ? '' : value.trim()
    if (!clear && err) {
      toast.error(err)
      return
    }
    setSaving(true)
    try {
      await onSave(url)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
        {channel} proxy URL
      </label>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit()
            if (e.key === 'Escape' && onCancel) onCancel()
          }}
          placeholder="socks5://user:pass@host:1080"
          disabled={saving}
          className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-xs font-mono outline-none focus:border-[var(--accent)]/40 transition-colors"
        />
        <button
          onClick={() => submit()}
          disabled={saving || !!err}
          className="p-2 rounded-lg bg-[var(--accent)]/20 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/30 disabled:opacity-30 transition-all cursor-pointer"
          title="Save"
        >
          <Check size={14} />
        </button>
        {initial && (
          <button
            onClick={() => submit(true)}
            disabled={saving}
            className="p-2 rounded-lg bg-[var(--error)]/10 border border-[var(--error)]/20 text-[var(--error)] hover:bg-[var(--error)]/20 disabled:opacity-30 transition-all cursor-pointer"
            title="Clear proxy"
          >
            <Trash2 size={14} />
          </button>
        )}
        {onCancel && (
          <button
            onClick={onCancel}
            disabled={saving}
            className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5 transition-all cursor-pointer"
            title="Cancel"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {err && <p className="text-[10px] text-[var(--error)]">{err}</p>}
    </div>
  )
}
