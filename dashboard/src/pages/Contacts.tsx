import { useEffect, useMemo, useState } from 'react'
import { Users, Search, Link2, Merge, RefreshCw, AlertTriangle, Mail, Phone, AtSign, X } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api'
import type { Contact } from '../types'
import EmptyState from '../components/EmptyState'

const TIER_STYLE: Record<Contact['tier'], string> = {
  stranger: 'bg-white/5 text-white/50 border-white/10',
  acquaintance: 'bg-blue-500/10 text-blue-300 border-blue-500/20',
  colleague: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
  vip: 'bg-[var(--accent-dim)] text-[var(--accent)] border-[var(--accent)]/30',
}

const KIND_ICON = {
  email: Mail,
  phone: Phone,
  handle: AtSign,
} as const

function fmtAge(ts: number): string {
  if (!ts) return '—'
  const delta = Date.now() / 1000 - ts
  if (delta < 60) return 'just now'
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`
  return `${Math.floor(delta / 86400)}d ago`
}

export default function Contacts() {
  const [items, setItems] = useState<Contact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [mergeFrom, setMergeFrom] = useState<Contact | null>(null)
  const [linkFor, setLinkFor] = useState<Contact | null>(null)

  const refresh = async () => {
    try {
      const data = await api.getContacts()
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
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((c) => {
      if (c.display_name.toLowerCase().includes(q)) return true
      if (c.canonical_id.toLowerCase().includes(q)) return true
      if (c.channels.some((ch) => ch.user_id.toLowerCase().includes(q))) return true
      if (c.extracted.some((e) => e.value.toLowerCase().includes(q))) return true
      return false
    })
  }, [items, query])

  const doMerge = async (keep: Contact, drop: Contact) => {
    try {
      await api.mergeContacts(keep.canonical_id, drop.canonical_id)
      toast.success(`Merged ${drop.display_name || drop.canonical_id} into ${keep.display_name || keep.canonical_id}`)
      setMergeFrom(null)
      refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const doLink = async (c: Contact, kind: 'email' | 'phone' | 'handle', value: string) => {
    try {
      const res = await api.linkContactIdentifier(c.canonical_id, kind, value)
      if (res.added > 0) {
        toast.success(`Linked ${kind} ${res.value}`)
      } else {
        toast.info(`That ${kind} is already attached to another contact`)
      }
      setLinkFor(null)
      refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="flex-1 p-8 max-w-7xl mx-auto w-full">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-3">
            <Users className="text-[var(--accent)]" size={26} />
            Contacts
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Cross-channel identity registry. Merge duplicates so context follows the human.
          </p>
        </div>
        <button
          onClick={refresh}
          className="px-3 py-2 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] hover:bg-[var(--overlay)] text-sm flex items-center gap-2"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="relative mb-4">
        <Search size={16} className="absolute top-3 left-3 text-[var(--text-faint)]" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, channel id, email, phone…"
          className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] text-sm focus:outline-none focus:border-[var(--accent)]/40"
        />
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm flex items-center gap-2">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-[var(--text-muted)]">Loading…</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Users}
          title={items.length === 0 ? 'No contacts yet' : 'No matches'}
          description={
            items.length === 0
              ? 'As messages arrive on your channels, contacts will appear here.'
              : 'Try a different search term.'
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((c) => (
            <div
              key={c.canonical_id}
              className="p-4 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--accent)]/30 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-medium text-[var(--text)]">
                      {c.display_name || <span className="text-[var(--text-faint)]">(unknown)</span>}
                    </span>
                    <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-md border ${TIER_STYLE[c.tier]}`}>
                      {c.tier}
                    </span>
                    <span className="text-xs text-[var(--text-faint)] font-mono">{c.canonical_id}</span>
                  </div>
                  <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <div className="text-[var(--text-faint)] uppercase tracking-wider mb-1">Channels</div>
                      {c.channels.length === 0 ? (
                        <span className="text-[var(--text-faint)]">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {c.channels.map((ch, i) => (
                            <span
                              key={i}
                              className="px-2 py-0.5 rounded-md bg-[var(--bg-faint)] border border-[var(--border-faint)] text-[var(--text-muted)] font-mono"
                            >
                              {ch.channel}: {ch.user_id}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <div className="text-[var(--text-faint)] uppercase tracking-wider mb-1">Known identifiers</div>
                      {c.extracted.length === 0 ? (
                        <span className="text-[var(--text-faint)]">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {c.extracted.map((e, i) => {
                            const Icon = KIND_ICON[e.kind] ?? Link2
                            return (
                              <span
                                key={i}
                                className="px-2 py-0.5 rounded-md bg-[var(--accent-dim)] border border-[var(--accent)]/20 text-[var(--accent)] flex items-center gap-1 font-mono"
                              >
                                <Icon size={10} /> {e.value}
                              </span>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 text-[11px] text-[var(--text-faint)]">
                    {c.message_count} message(s) · last seen {fmtAge(c.last_seen)}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5 shrink-0">
                  <button
                    onClick={() => setLinkFor(c)}
                    className="px-3 py-1.5 rounded-lg bg-[var(--bg-faint)] border border-[var(--border-faint)] text-xs hover:bg-[var(--overlay)] flex items-center gap-1.5"
                  >
                    <Link2 size={12} /> Link
                  </button>
                  <button
                    onClick={() => setMergeFrom(c)}
                    className="px-3 py-1.5 rounded-lg bg-[var(--bg-faint)] border border-[var(--border-faint)] text-xs hover:bg-[var(--overlay)] flex items-center gap-1.5"
                  >
                    <Merge size={12} /> Merge
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {mergeFrom && (
        <MergePicker
          source={mergeFrom}
          candidates={items.filter((c) => c.canonical_id !== mergeFrom.canonical_id)}
          onClose={() => setMergeFrom(null)}
          onPick={(target) => doMerge(target, mergeFrom)}
        />
      )}

      {linkFor && (
        <LinkDialog
          contact={linkFor}
          onClose={() => setLinkFor(null)}
          onSubmit={(kind, value) => doLink(linkFor, kind, value)}
        />
      )}
    </div>
  )
}

function MergePicker({
  source,
  candidates,
  onClose,
  onPick,
}: {
  source: Contact
  candidates: Contact[]
  onClose: () => void
  onPick: (keep: Contact) => void
}) {
  const [q, setQ] = useState('')
  const filtered = candidates.filter((c) => {
    const term = q.trim().toLowerCase()
    if (!term) return true
    return (
      c.display_name.toLowerCase().includes(term) ||
      c.canonical_id.toLowerCase().includes(term) ||
      c.channels.some((ch) => ch.user_id.toLowerCase().includes(term))
    )
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <div>
            <h3 className="font-bold flex items-center gap-2">
              <Merge size={16} className="text-[var(--accent)]" /> Merge into…
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Choose the contact to keep. <span className="text-[var(--text)] font-medium">{source.display_name || source.canonical_id}</span> will be merged in and deleted.
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--overlay)]">
            <X size={16} />
          </button>
        </div>
        <div className="p-3 border-b border-[var(--border)]">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter…"
            className="w-full px-3 py-2 rounded-lg bg-[var(--bg-faint)] border border-[var(--border-faint)] text-sm focus:outline-none focus:border-[var(--accent)]/40"
          />
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <div className="p-6 text-center text-sm text-[var(--text-faint)]">No other contacts.</div>
          ) : (
            filtered.map((c) => (
              <button
                key={c.canonical_id}
                onClick={() => onPick(c)}
                className="w-full text-left p-3 rounded-xl hover:bg-[var(--overlay)] flex items-center justify-between gap-3"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {c.display_name || <span className="text-[var(--text-faint)]">(unknown)</span>}
                  </div>
                  <div className="text-[11px] text-[var(--text-faint)] font-mono truncate">
                    {c.canonical_id} · {c.channels.map((ch) => ch.channel).join(', ') || 'no channels'}
                  </div>
                </div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--accent)]">Keep this →</span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function LinkDialog({
  contact,
  onClose,
  onSubmit,
}: {
  contact: Contact
  onClose: () => void
  onSubmit: (kind: 'email' | 'phone' | 'handle', value: string) => void
}) {
  const [kind, setKind] = useState<'email' | 'phone' | 'handle'>('email')
  const [value, setValue] = useState('')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (value.trim()) onSubmit(kind, value.trim())
        }}
        className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl w-full max-w-md"
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h3 className="font-bold flex items-center gap-2">
            <Link2 size={16} className="text-[var(--accent)]" /> Link identifier
          </h3>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--overlay)]">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-[var(--text-muted)]">
            Attach an email, phone, or handle to <span className="font-medium text-[var(--text)]">{contact.display_name || contact.canonical_id}</span>. Future messages from any channel that mention this identifier will auto-link to this contact.
          </p>
          <div className="flex gap-2">
            {(['email', 'phone', 'handle'] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={`flex-1 px-3 py-1.5 rounded-lg text-xs uppercase tracking-wider border ${
                  kind === k
                    ? 'bg-[var(--accent-dim)] text-[var(--accent)] border-[var(--accent)]/30'
                    : 'bg-[var(--bg-faint)] border-[var(--border-faint)] text-[var(--text-muted)]'
                }`}
              >
                {k}
              </button>
            ))}
          </div>
          <input
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={kind === 'email' ? 'alice@example.com' : kind === 'phone' ? '+15555550100' : 'alice'}
            className="w-full px-3 py-2 rounded-lg bg-[var(--bg-faint)] border border-[var(--border-faint)] text-sm focus:outline-none focus:border-[var(--accent)]/40"
          />
        </div>
        <div className="p-4 border-t border-[var(--border)] flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg bg-[var(--bg-faint)] border border-[var(--border-faint)] text-sm hover:bg-[var(--overlay)]"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!value.trim()}
            className="px-3 py-1.5 rounded-lg bg-[var(--accent-dim)] border border-[var(--accent)]/30 text-[var(--accent)] text-sm hover:bg-[var(--accent-dim)] disabled:opacity-50"
          >
            Link
          </button>
        </div>
      </form>
    </div>
  )
}
