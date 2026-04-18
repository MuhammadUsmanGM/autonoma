import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Power, RefreshCw, AlertTriangle, Key, ChevronRight, MessageSquare, Mail, Globe, Bot } from 'lucide-react'
import { api } from '../api'
import { toast } from 'sonner'
import Skeleton from '../components/Skeleton'
import ChannelHealthBadge from '../components/ChannelHealthBadge'
import type { ChannelInfo } from '../types'

const CHANNEL_META: Record<string, { desc: string, icon: any }> = {
  telegram: { desc: 'Bot via @BotFather', icon: MessageSquare },
  discord: { desc: 'Message Content intent required', icon: Bot },
  whatsapp: { desc: 'Via whatsapp-web.js bridge', icon: MessageSquare },
  gmail: { desc: 'IMAP/SMTP with App Password', icon: Mail },
  rest: { desc: 'HTTP endpoint on gateway port', icon: Globe },
}

export default function Channels() {
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Credentials Modal State
  const [showModal, setShowModal] = useState<string | null>(null)
  const [creds, setCreds] = useState<Record<string, string>>({})

  useEffect(() => {
    loadChannels()
    const interval = setInterval(loadChannels, 5000)
    return () => clearInterval(interval)
  }, [])

  const loadChannels = async () => {
    try {
      const data = await api.getChannels()
      setChannels(data)
    } catch (e: any) {
      console.error('Failed to load channels:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleManualRefresh = async () => {
    setRefreshing(true)
    await loadChannels()
    setRefreshing(false)
  }

  const handleToggle = async (channel: ChannelInfo) => {
    try {
      const res = await api.toggleChannel(channel.id, !channel.enabled)
      toast.success(`${channel.name} ${!channel.enabled ? 'enabled' : 'disabled'} in config.`, {
        action: res.restart_required ? {
          label: 'Restart Required',
          onClick: async () => {
            await api.restartAgent()
            setTimeout(() => window.location.reload(), 3000)
          }
        } : undefined
      })
      await loadChannels()
    } catch (e: any) {
      toast.error(`Failed to toggle ${channel.name}: ${e.message}`)
    }
  }

  const handleReconnect = async (channelId: string) => {
    const toastId = toast.loading(`Reconnecting ${channelId}...`)
    try {
      await api.reconnectChannel(channelId)
      toast.success(`${channelId} reconnected successfully.`, { id: toastId })
      await loadChannels()
    } catch (e: any) {
      toast.error(`Reconnect failed: ${e.message}`, { id: toastId })
    }
  }

  const handleSaveCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!showModal) return
    try {
      const res = await api.updateChannelCredentials(showModal, creds)
      toast.success(`Credentials updated for ${showModal}.`, {
        action: res.restart_required ? {
          label: 'Restart Required',
          onClick: async () => {
            await api.restartAgent()
            setTimeout(() => window.location.reload(), 3000)
          }
        } : undefined
      })
      setShowModal(null)
      setCreds({})
    } catch (err: any) {
      toast.error(`Failed to update credentials: ${err.message}`)
    }
  }

  if (loading) {
    return (
      <div className="p-10 space-y-6">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 reflective rounded-2xl" />
        <Skeleton className="h-40 reflective rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="p-10 space-y-8 pb-32">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-[var(--text)] mb-2">Communication Pathways</h2>
          <p className="text-sm text-[var(--text-muted)]">Monitor and orchestrate your autonomous channels.</p>
        </div>
        <button 
          onClick={handleManualRefresh}
          className="p-2.5 rounded-xl bg-[var(--bg-faint)] border border-[var(--border-faint)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors cursor-pointer"
        >
          <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {channels.map((ch, idx) => {
          const MetaIcon = CHANNEL_META[ch.id]?.icon || Globe
          const isError = ch.status === 'error'
          const isRunning = ch.status === 'running'
          const isStarting = ch.status === 'starting'
          
          return (
            <motion.div
              key={ch.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.05 }}
              className={`reflective rounded-2xl p-6 border transition-colors ${
                isError ? 'border-[var(--error)]/30' : 
                isRunning ? 'border-[var(--success)]/20' : 
                'border-[var(--border)]'
              }`}
            >
              <div className="flex items-start justify-between mb-6">
                <div className="flex items-center gap-4">
                  <div className={`p-3 rounded-xl ${
                    isError ? 'bg-[var(--error)]/10 text-[var(--error)]' :
                    isRunning ? 'bg-[var(--success)]/10 text-[var(--success)]' :
                    'bg-[var(--bg-faint)] text-[var(--text-muted)]'
                  }`}>
                    <MetaIcon size={20} />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-[var(--text)]">{ch.name}</h3>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">{CHANNEL_META[ch.id]?.desc || 'Channel interface'}</p>
                  </div>
                </div>
                
                {/* Status Badge */}
                <ChannelHealthBadge 
                  status={ch.status as any} 
                  error={ch.last_error}
                />
              </div>

              {/* Error Output */}
              {isError && ch.last_error && (
                <div className="mb-6 p-3 rounded-lg bg-[var(--error)]/5 border border-[var(--error)]/20 text-xs font-mono text-[var(--error)] break-words">
                  {ch.last_error}
                </div>
              )}

              {/* Missing Credentials Alert */}
              {!ch.has_credentials && ch.enabled && !['whatsapp', 'rest'].includes(ch.id) && (
                <div className="mb-6 flex items-center gap-2 p-3 rounded-lg bg-orange-500/10 border border-orange-500/20 text-xs font-medium text-orange-400">
                  <AlertTriangle size={14} />
                  <span>Missing credentials. Tap keys below to configure.</span>
                </div>
              )}

              {/* Action Bar */}
              <div className="flex items-center justify-between mt-auto pt-4 border-t border-[var(--border)]">
                <div className="flex gap-2">
                  <button
                    onClick={() => handleToggle(ch)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-bold flex items-center gap-1.5 uppercase transition-all cursor-pointer ${
                      ch.enabled 
                        ? 'bg-[var(--error)]/10 text-[var(--error)] hover:bg-[var(--error)]/20' 
                        : 'bg-[var(--success)]/10 text-[var(--success)] hover:bg-[var(--success)]/20'
                    }`}
                  >
                    <Power size={12} />
                    {ch.enabled ? 'Disable' : 'Enable'}
                  </button>

                  {ch.enabled && ch.has_credentials && (
                    <button
                      onClick={() => handleReconnect(ch.id)}
                      className="px-3 py-1.5 rounded-lg text-[10px] font-bold text-[var(--accent)] bg-[var(--accent)]/10 shadow hover:bg-[var(--accent)] hover:text-black flex items-center gap-1.5 uppercase transition-all cursor-pointer"
                    >
                      <RefreshCw size={12} />
                      Reconnect
                    </button>
                  )}
                </div>

                {!['whatsapp', 'rest'].includes(ch.id) && (
                  <button
                    onClick={() => {
                      setCreds({})
                      setShowModal(ch.id)
                    }}
                    className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-faint)] hover:text-[var(--text)] transition-colors cursor-pointer"
                    title="Credentials"
                  >
                    <Key size={16} />
                  </button>
                )}
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Basic Credentials Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-md bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden glass"
          >
            <div className="p-4 border-b border-[var(--border)] flex justify-between items-center">
              <h3 className="font-bold text-[var(--text)] uppercase tracking-wider text-sm flex items-center gap-2">
                <Key size={14} className="text-[var(--accent)]" /> {showModal} Credentials
              </h3>
              <button onClick={() => setShowModal(null)} className="text-[var(--text-muted)] hover:text-[var(--text)]">×</button>
            </div>
            <form onSubmit={handleSaveCredentials} className="p-6 space-y-4">
              {['telegram', 'discord'].includes(showModal) && (
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Bot Token</label>
                  <input
                    type="password"
                    value={creds.bot_token || ''}
                    onChange={(e) => setCreds({ ...creds, bot_token: e.target.value })}
                    placeholder="Enter token to replace current..."
                    className="w-full bg-[var(--bg-faint)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm text-[var(--text)] font-mono outline-none focus:border-[var(--accent)]/40 transition-colors"
                  />
                </div>
              )}

              {showModal === 'gmail' && (
                <>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Email Address</label>
                    <input
                      type="text"
                      value={creds.address || ''}
                      onChange={(e) => setCreds({ ...creds, address: e.target.value })}
                      className="w-full bg-[var(--bg-faint)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">App Password</label>
                    <input
                      type="password"
                      value={creds.app_password || ''}
                      onChange={(e) => setCreds({ ...creds, app_password: e.target.value })}
                      className="w-full bg-[var(--bg-faint)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm text-[var(--text)] font-mono outline-none focus:border-[var(--accent)]/40 transition-colors"
                    />
                  </div>
                </>
              )}

              <div className="pt-4 flex justify-end gap-3">
                <button type="button" onClick={() => setShowModal(null)} className="px-4 py-2 text-xs font-bold text-[var(--text-muted)] hover:text-[var(--text)]">CANCEL</button>
                <button type="submit" className="px-5 py-2 bg-[var(--accent)] text-black rounded-lg text-xs font-bold uppercase tracking-wider hover:scale-105 active:scale-95 transition-transform flex items-center gap-1">
                  Save <ChevronRight size={14} />
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  )
}
