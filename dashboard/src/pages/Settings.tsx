import { useEffect, useState } from 'react'
import { Save, RefreshCw, Shield, Cpu, Radio, HardDrive, Eye, EyeOff, AlertTriangle, CheckCircle2, ChevronDown } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import Skeleton from '../components/Skeleton'
import type { AppConfig } from '../types'

const PROVIDERS = [
  { value: 'openrouter', label: 'OpenRouter', desc: 'One key, 100+ models' },
  { value: 'anthropic', label: 'Anthropic', desc: 'Direct Claude API' },
]

const MODEL_SUGGESTIONS: Record<string, string[]> = {
  openrouter: [
    'anthropic/claude-sonnet-4.5',
    'anthropic/claude-haiku-4.5',
    'openai/gpt-4o-mini',
    'google/gemini-2.0-flash-exp',
  ],
  anthropic: [
    'claude-sonnet-4-6',
    'claude-haiku-4-5-20251001',
    'claude-opus-4-6',
  ],
}

const LOG_LEVELS = ['debug', 'info', 'warning', 'error']

const CHANNEL_META: Record<string, { label: string; desc: string }> = {
  telegram: { label: 'Telegram', desc: 'Bot via @BotFather' },
  discord: { label: 'Discord', desc: 'Message Content intent required' },
  whatsapp: { label: 'WhatsApp', desc: 'Via whatsapp-web.js bridge' },
  gmail: { label: 'Gmail', desc: 'IMAP/SMTP with App Password' },
  rest: { label: 'REST API', desc: 'HTTP endpoint on gateway port' },
}

export default function Settings() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [dirty, setDirty] = useState(false)

  // Draft state for editable fields
  const [draft, setDraft] = useState<Partial<AppConfig>>({})

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const data = await api.getConfig()
      setConfig(data)
      setDraft({})
      setApiKey('')
      setDirty(false)
    } catch (e: any) {
      toast.error(`Failed to load config: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const updateDraft = (path: string, value: unknown) => {
    setDirty(true)
    setDraft((prev) => {
      const next = { ...prev }
      const keys = path.split('.')
      let obj: any = next
      for (let i = 0; i < keys.length - 1; i++) {
        obj[keys[i]] = obj[keys[i]] ? { ...obj[keys[i]] } : {}
        obj = obj[keys[i]]
      }
      obj[keys[keys.length - 1]] = value
      return next
    })
  }

  const getVal = <T,>(path: string, fallback: T): T => {
    const keys = path.split('.')
    let draftObj: any = draft
    let configObj: any = config
    for (const k of keys) {
      if (draftObj && draftObj[k] !== undefined) {
        draftObj = draftObj[k]
      } else {
        draftObj = undefined
      }
      if (configObj) configObj = configObj[k]
    }
    return (draftObj !== undefined ? draftObj : configObj ?? fallback) as T
  }

  const handleSave = async () => {
    if (!dirty && !apiKey) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = { ...draft }
      if (apiKey) {
        const llm = (payload.llm as Record<string, unknown>) || {}
        llm.api_key = apiKey
        llm.provider = getVal('llm.provider', 'openrouter')
        payload.llm = llm
      }
      await api.updateConfig(payload)
      toast.success('Configuration saved. Restart agent to apply changes.', {
        duration: 5000,
      })
      await loadConfig()
    } catch (e: any) {
      toast.error(`Failed to save: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="p-10 space-y-10">
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <Skeleton className="h-80 reflective rounded-2xl" />
          <Skeleton className="h-80 reflective rounded-2xl" />
        </div>
        <Skeleton className="h-52 reflective rounded-2xl" />
      </div>
    )
  }

  if (!config) {
    return (
      <div className="p-10 flex flex-col items-center justify-center h-full">
        <AlertTriangle className="text-[var(--error)] mb-4" size={32} />
        <p className="text-white font-semibold">Configuration unavailable</p>
        <p className="text-sm text-[var(--text-muted)] mt-1">Is Autonoma running on port 8766?</p>
        <button onClick={loadConfig} className="mt-4 px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm hover:bg-white/10 transition-colors">
          Retry
        </button>
      </div>
    )
  }

  const currentProvider = getVal('llm.provider', 'openrouter')
  const currentModel = getVal('llm.model', '')
  const models = MODEL_SUGGESTIONS[currentProvider] || []

  return (
    <div className="p-10 space-y-10">
      {/* Header */}
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-[var(--text)] mb-2">System Configuration</h2>
          <p className="text-sm text-[var(--text-muted)]">Modify agent parameters. Changes require a restart to take effect.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadConfig}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-[var(--text)] hover:bg-white/10 transition-colors cursor-pointer"
          >
            <RefreshCw size={14} />
            Reload
          </button>
          <button
            onClick={handleSave}
            disabled={saving || (!dirty && !apiKey)}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold bg-[var(--accent)] text-black hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30 disabled:scale-100 transition-all cursor-pointer shadow-lg shadow-[var(--accent-glow)]"
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
            Save Changes
          </button>
        </div>
      </header>

      {/* Unsaved changes banner */}
      {(dirty || apiKey) && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-3 px-5 py-3 rounded-xl bg-[var(--accent-dim)] border border-[var(--accent)]/20"
        >
          <AlertTriangle size={16} className="text-[var(--accent)]" />
          <span className="text-sm font-medium text-[var(--accent)]">You have unsaved changes</span>
        </motion.div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* LLM Configuration */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="rounded-2xl reflective p-8 space-y-6"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--accent-dim)]">
              <Cpu size={18} className="text-[var(--accent)]" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-[var(--text)] uppercase tracking-widest">Neural Engine</h3>
              <p className="text-[10px] text-[var(--text-muted)]">LLM provider, model, and API credentials</p>
            </div>
          </div>

          {/* Provider */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Provider</label>
            <div className="grid grid-cols-2 gap-3">
              {PROVIDERS.map((p) => {
                const active = currentProvider === p.value
                return (
                  <button
                    key={p.value}
                    onClick={() => updateDraft('llm.provider', p.value)}
                    className={`text-left px-4 py-3 rounded-xl border transition-all cursor-pointer ${
                      active
                        ? 'border-[var(--accent)]/40 bg-[var(--accent-dim)] text-[var(--accent)]'
                        : 'border-[var(--border)] bg-white/[0.02] text-[var(--text-muted)] hover:border-white/20'
                    }`}
                  >
                    <span className="text-sm font-bold block">{p.label}</span>
                    <span className="text-[10px] opacity-60">{p.desc}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Model */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Model</label>
            <div className="relative">
              <select
                value={currentModel}
                onChange={(e) => updateDraft('llm.model', e.target.value)}
                className="w-full appearance-none bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors cursor-pointer"
              >
                {models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
                {!models.includes(currentModel) && (
                  <option value={currentModel}>{currentModel}</option>
                )}
              </select>
              <ChevronDown size={14} className="absolute right-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
            </div>
          </div>

          {/* API Key */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">API Key</label>
            <div className="flex items-center gap-2">
              {config.llm.api_key_configured && !apiKey && (
                <div className="flex items-center gap-1.5 text-xs text-[var(--success)]">
                  <CheckCircle2 size={12} />
                  <span className="font-medium">Configured</span>
                </div>
              )}
            </div>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={config.llm.api_key_configured ? 'Enter new key to replace…' : 'Paste your API key here'}
                className="w-full bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 pr-12 text-sm text-[var(--text)] placeholder:text-white/15 outline-none focus:border-[var(--accent)]/40 transition-colors font-mono"
              />
              <button
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] hover:text-[var(--text)] transition-colors cursor-pointer"
              >
                {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        </motion.div>

        {/* Channels */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1 }}
          className="rounded-2xl reflective p-8 space-y-6"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--accent-dim)]">
              <Radio size={18} className="text-[var(--accent)]" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-[var(--text)] uppercase tracking-widest">Communication Pathways</h3>
              <p className="text-[10px] text-[var(--text-muted)]">Enable or disable active channel adapters</p>
            </div>
          </div>

          <div className="space-y-3">
            {Object.entries(CHANNEL_META).map(([key, meta]) => {
              const enabled = getVal(`channels.${key}.enabled`, false)
              return (
                <div
                  key={key}
                  className={`flex items-center justify-between px-5 py-4 rounded-xl border transition-all ${
                    enabled
                      ? 'border-[var(--accent)]/20 bg-[var(--accent-dim)]'
                      : 'border-[var(--border)] bg-white/[0.02]'
                  }`}
                >
                  <div>
                    <span className={`text-sm font-bold ${enabled ? 'text-[var(--accent)]' : 'text-[var(--text)]'}`}>{meta.label}</span>
                    <p className="text-[10px] text-[var(--text-muted)]">{meta.desc}</p>
                  </div>
                  <button
                    onClick={() => updateDraft(`channels.${key}.enabled`, !enabled)}
                    className={`relative w-11 h-6 rounded-full transition-colors cursor-pointer shrink-0 ${
                      enabled ? 'bg-[var(--accent)]' : 'bg-white/10'
                    }`}
                  >
                    <motion.div
                      layout
                      className="absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-md"
                      style={{ left: enabled ? 'calc(100% - 22px)' : '2px' }}
                      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                    />
                  </button>
                </div>
              )
            })}
          </div>
        </motion.div>
      </div>

      {/* System Settings */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2 }}
        className="rounded-2xl reflective p-8"
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="p-2 rounded-lg bg-[var(--accent-dim)]">
            <HardDrive size={18} className="text-[var(--accent)]" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--text)] uppercase tracking-widest">System Parameters</h3>
            <p className="text-[10px] text-[var(--text-muted)]">Memory engine tuning and runtime behavior</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Agent Name */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Agent Name</label>
            <input
              type="text"
              value={getVal('name', 'Autonoma')}
              onChange={(e) => updateDraft('name', e.target.value)}
              className="w-full bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors"
            />
          </div>

          {/* Log Level */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Log Level</label>
            <div className="relative">
              <select
                value={getVal('log_level', 'info')}
                onChange={(e) => updateDraft('log_level', e.target.value)}
                className="w-full appearance-none bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors cursor-pointer"
              >
                {LOG_LEVELS.map((l) => (
                  <option key={l} value={l}>{l.toUpperCase()}</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
            </div>
          </div>

          {/* Context Window */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Max Context Memories</label>
            <input
              type="number"
              value={getVal('memory.max_context_memories', 15)}
              onChange={(e) => updateDraft('memory.max_context_memories', parseInt(e.target.value) || 15)}
              className="w-full bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors"
            />
          </div>

          {/* Importance Threshold */}
          <div className="space-y-2">
            <label className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Importance Threshold</label>
            <input
              type="number"
              step="0.01"
              value={getVal('memory.importance_threshold', 0.1)}
              onChange={(e) => updateDraft('memory.importance_threshold', parseFloat(e.target.value) || 0.1)}
              className="w-full bg-white/[0.03] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors"
            />
          </div>
        </div>

        {/* Gateway Info (read-only) */}
        <div className="mt-8 pt-6 border-t border-[var(--border)]">
          <div className="flex items-center gap-2 mb-4">
            <Shield size={14} className="text-[var(--text-muted)]" />
            <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Gateway (Read-only)</span>
          </div>
          <div className="flex gap-8 text-sm">
            <div>
              <span className="text-[var(--text-muted)]">WebSocket: </span>
              <span className="font-mono text-[var(--text)]">{config.gateway.host}:{config.gateway.port}</span>
            </div>
            <div>
              <span className="text-[var(--text-muted)]">HTTP API: </span>
              <span className="font-mono text-[var(--text)]">{config.gateway.host}:{config.gateway.http_port}</span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
