import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Webhook, RefreshCw, Play, Clock, Braces, ChevronRight, AlertTriangle } from 'lucide-react'
import { api } from '../api'
import { toast } from 'sonner'
import type { WebhookEntry } from '../types'
import Dropdown from '../components/Dropdown'

const CHANNELS = [
  { label: 'ALL PROBES', value: '' },
  { label: 'REST', value: '/api/chat' },
  { label: 'WhatsApp', value: 'whatsapp' },
]

export default function Webhooks() {
  const [hooks, setHooks] = useState<WebhookEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<WebhookEntry | null>(null)
  const [replaying, setReplaying] = useState<string | null>(null)

  const loadHooks = async () => {
    try {
      const data = await api.getWebhooks(filter)
      setHooks(data)
      if (selected) {
        const stillExists = data.find(h => h.id === selected.id)
        if (!stillExists) setSelected(null)
      }
    } catch (e) {
      console.error('Failed to load webhooks:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadHooks()
    const int = setInterval(loadHooks, 5000)
    return () => clearInterval(int)
  }, [filter])

  const handleReplay = async (id: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()
    setReplaying(id)
    try {
      await api.replayWebhook(id)
      toast.success('Successfully dispatched replay.')
    } catch (err: any) {
      toast.error(`Replay failed: ${err.message}`)
    } finally {
      setReplaying(null)
    }
  }

  return (
    <div className="flex h-full font-sans pb-10">
      {/* Left panel - Hook list */}
      <div className="w-[380px] shrink-0 border-r border-[var(--border)] bg-[var(--bg)] flex flex-col h-full">
        <header className="p-6 border-b border-[var(--border)] space-y-4 shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-[var(--accent)]/10 text-[var(--accent)]">
                <Webhook size={18} />
              </div>
              <h2 className="text-xl font-bold tracking-tight text-[var(--text)]">Webhooks</h2>
            </div>
            <button 
              onClick={loadHooks}
              className="p-2 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors cursor-pointer"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
          <Dropdown
            options={CHANNELS}
            value={filter}
            onChange={setFilter}
          />
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-2 custom-scrollbar">
          {hooks.length === 0 ? (
            <div className="flex flex-col items-center justify-center pt-20 text-[var(--text-muted)] opacity-50">
              <Webhook size={32} className="mb-4" />
              <p className="text-sm">No webhook traces captured.</p>
            </div>
          ) : (
            <AnimatePresence>
              {hooks.map((hook, i) => {
                const isActive = selected?.id === hook.id
                return (
                  <motion.div
                    key={hook.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.03 }}
                    onClick={() => setSelected(hook)}
                    className={`p-3 rounded-xl border transition-all cursor-pointer group ${
                      isActive 
                        ? 'bg-[var(--accent-dim)] border-[var(--accent)]/30 shadow-[0_4px_20px_rgba(var(--accent-rgb),0.1)]' 
                        : 'bg-[var(--bg-card)] border-[var(--border)] hover:border-[var(--text-muted)]'
                    }`}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${isActive ? 'bg-[var(--accent)] text-black' : 'bg-[var(--bg-faint)] text-[var(--text-muted)]'}`}>
                        {hook.method}
                      </span>
                      <span className="text-[10px] text-[var(--text-faint)] flex items-center gap-1">
                        <Clock size={10} />
                        {new Date(hook.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="text-xs font-mono text-[var(--text)] truncate">{hook.path}</div>
                  </motion.div>
                )
              })}
            </AnimatePresence>
          )}
        </div>
      </div>

      {/* Right panel - Inspector */}
      <div className="flex-1 flex flex-col bg-[var(--bg-card)]/30">
        {selected ? (
          <motion.div
            key={selected.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col h-full overflow-hidden"
          >
            {/* Header */}
            <div className="shrink-0 p-6 border-b border-[var(--border)] flex justify-between items-start bg-[var(--bg)]/50 backdrop-blur">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-sm font-bold bg-[var(--accent)]/10 text-[var(--accent)] px-2 py-1 rounded">
                    {selected.method}
                  </span>
                  <span className="text-sm font-mono text-[var(--text)]">{selected.path}</span>
                </div>
                <div className="text-xs text-[var(--text-faint)]">Captured {new Date(selected.timestamp).toLocaleString()}</div>
              </div>
              
              <button
                onClick={(e) => handleReplay(selected.id, e)}
                disabled={replaying === selected.id}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold bg-[var(--accent)] text-black shadow-lg shadow-[var(--accent-glow)] hover:scale-105 active:scale-95 transition-all disabled:opacity-50 disabled:scale-100 cursor-pointer"
              >
                {replaying === selected.id ? (
                  <RefreshCw size={16} className="animate-spin" />
                ) : (
                  <Play size={16} />
                )}
                REPLAY HOOK
              </button>
            </div>

            {/* Payload View */}
            <div className="flex-1 overflow-y-auto p-8 space-y-8 custom-scrollbar">
              
              <section>
                <h3 className="text-xs font-bold text-[var(--text-muted)] tracking-widest uppercase mb-4 flex items-center gap-2">
                  <ChevronRight size={14} className="text-[var(--accent)]" /> 
                  Headers
                </h3>
                <div className="bg-[var(--bg)] rounded-xl border border-[var(--border)] p-4 font-mono text-xs overflow-x-auto">
                  {Object.entries(selected.headers).map(([k, v]) => (
                    <div key={k} className="flex gap-4 border-b border-[var(--border-faint)] last:border-0 py-1.5">
                      <span className="text-[var(--text-muted)] w-32 shrink-0">{k}:</span>
                      <span className="text-[var(--text)] break-all">{v}</span>
                    </div>
                  ))}
                </div>
              </section>

              <section>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xs font-bold text-[var(--text-muted)] tracking-widest uppercase flex items-center gap-2">
                    <Braces size={14} className="text-[var(--accent)]" /> 
                    JSON Payload
                  </h3>
                </div>
                {Object.keys(selected.json || {}).length > 0 ? (
                  <div className="bg-[#0D0D0D] p-5 rounded-xl border border-[var(--border)] overflow-x-auto">
                    <pre className="text-[11px] font-mono leading-relaxed text-[#A0A0A0]">
                      {JSON.stringify(selected.json, null, 2)}
                    </pre>
                  </div>
                ) : selected.body ? (
                   <div className="bg-[#0D0D0D] p-5 rounded-xl border border-[var(--border)] overflow-x-auto">
                     <pre className="text-[11px] font-mono leading-relaxed text-orange-300">
                       {selected.body}
                     </pre>
                   </div>
                ) : (
                  <div className="flex items-center gap-2 p-4 rounded-xl bg-white/[0.02] border border-[var(--border-faint)] text-xs text-[var(--text-muted)] italic">
                     No body attached to this payload.
                  </div>
                )}
              </section>

            </div>
          </motion.div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] opacity-50 space-y-4">
            <Webhook size={48} className="opacity-20" />
            <p>Select a webhook to inspect payloads and headers.</p>
          </div>
        )}
      </div>
    </div>
  )
}
