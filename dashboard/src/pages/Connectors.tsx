import { useEffect, useState } from 'react'
import { Plug, RefreshCw, LogOut, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { api } from '../api'
import type { ConnectorEntry } from '../types'
import EmptyState from '../components/EmptyState'

const ICONS: Record<string, string> = {
  google_calendar: 'GC',
  onedrive: 'OD',
}

export default function Connectors() {
  const [items, setItems] = useState<ConnectorEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    try {
      const data = await api.getConnectors()
      setItems(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // The OAuth popup posts a message back when the callback page closes.
    const onMessage = (ev: MessageEvent) => {
      const data = ev.data as { type?: string; status?: string }
      if (data && data.type === 'autonoma:connector') {
        refresh()
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  const connect = async (name: string) => {
    setBusy(name)
    try {
      const { auth_url } = await api.connectConnector(name)
      // Open the provider auth in a popup so the user keeps the dashboard tab.
      const w = 480
      const h = 720
      const left = window.screen.width / 2 - w / 2
      const top = window.screen.height / 2 - h / 2
      window.open(
        auth_url,
        `autonoma-${name}`,
        `width=${w},height=${h},left=${left},top=${top}`,
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const disconnect = async (name: string) => {
    if (!confirm(`Sign out of ${name}? Tokens will be revoked.`)) return
    setBusy(name)
    try {
      await api.disconnectConnector(name)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return <div className="p-8 text-[var(--text-muted)]">Loading connectors…</div>
  }

  if (items.length === 0) {
    return (
      <div className="p-8">
        <EmptyState
          icon={Plug}
          title="No connectors registered"
          description="Add a client_id and client_secret for Google Calendar or OneDrive in your .env to enable connectors."
        />
      </div>
    )
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Plug size={22} className="text-[var(--accent)]" /> Connectors
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Sign Autonoma into third-party services. One account per connector at a time.
          </p>
        </div>
        <button
          onClick={refresh}
          className="px-3 py-2 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] text-sm flex items-center gap-2 hover:bg-[var(--overlay)]"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300 flex items-center gap-2">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {items.map(({ manifest, status }) => {
          const connected = status.state === 'connected'
          const expired = status.state === 'expired'
          return (
            <div
              key={manifest.name}
              className="rounded-2xl border border-[var(--border)] bg-[var(--bg-faint)] p-5 flex flex-col gap-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-[var(--overlay)] flex items-center justify-center font-bold text-[var(--accent)]">
                    {ICONS[manifest.name] ?? manifest.display_name.slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-semibold">{manifest.display_name}</div>
                    <div className="text-xs text-[var(--text-muted)]">{manifest.description}</div>
                  </div>
                </div>
                <span
                  className={`text-[10px] uppercase tracking-widest font-bold px-2 py-1 rounded-full border ${
                    connected
                      ? 'border-green-500/40 bg-green-500/10 text-green-400'
                      : expired
                        ? 'border-yellow-500/40 bg-yellow-500/10 text-yellow-300'
                        : 'border-[var(--border-faint)] bg-[var(--overlay)] text-[var(--text-muted)]'
                  }`}
                >
                  {status.state}
                </span>
              </div>

              {connected && (
                <div className="text-sm flex items-center gap-2 text-[var(--text)]">
                  <CheckCircle2 size={14} className="text-green-400" />
                  <span>{status.account_label || status.account_id}</span>
                </div>
              )}

              {status.scopes.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {status.scopes.slice(0, 5).map((s) => (
                    <span
                      key={s}
                      className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--overlay)] text-[var(--text-muted)]"
                    >
                      {s.split('/').pop()}
                    </span>
                  ))}
                </div>
              )}

              <div className="flex gap-2 pt-2">
                {connected ? (
                  <button
                    onClick={() => disconnect(manifest.name)}
                    disabled={busy === manifest.name}
                    className="flex-1 px-3 py-2 rounded-xl border border-[var(--border-faint)] text-sm flex items-center justify-center gap-2 hover:bg-[var(--overlay)] disabled:opacity-50"
                  >
                    <LogOut size={14} /> Sign out
                  </button>
                ) : (
                  <button
                    onClick={() => connect(manifest.name)}
                    disabled={busy === manifest.name}
                    className="flex-1 px-3 py-2 rounded-xl bg-[var(--accent)] text-black font-semibold text-sm flex items-center justify-center gap-2 hover:opacity-90 disabled:opacity-50"
                  >
                    <Plug size={14} /> {expired ? 'Reconnect' : 'Connect'}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
