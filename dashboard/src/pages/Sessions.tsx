import { useEffect, useState, useCallback } from 'react'
import { RefreshCw, History, MessageSquareText } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import SessionList from '../components/SessionList'
import SessionDetailView from '../components/SessionDetail'
import Skeleton from '../components/Skeleton'
import type { Session, SessionMessage } from '../types'

export default function Sessions() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getSessions()
      setSessions(data)
    } catch {
      toast.error('Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const selectSession = async (id: string) => {
    setSelected(id)
    try {
      const detail = await api.getSessionDetail(id)
      setMessages(detail.messages)
    } catch {
      toast.error('Failed to load session')
      setMessages([])
    }
  }

  return (
    <div className="p-10 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Registry Logs</h2>
          <p className="text-sm text-[var(--text-muted)]">Replay and audit historical human-agent interactions</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Sync Sessions
        </button>
      </header>

      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="h-96 reflective rounded-2xl" />
          <Skeleton className="lg:col-span-2 h-96 reflective rounded-2xl" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Session list */}
          <div className="rounded-2xl reflective p-4 h-[calc(100vh-16rem)] overflow-y-auto scrollbar-hide">
            <h3 className="text-[10px] font-bold text-white uppercase tracking-[0.2em] mb-4 px-2">Active Channels</h3>
            <SessionList sessions={sessions} selected={selected} onSelect={selectSession} />
          </div>

          {/* Session detail */}
          <div className="lg:col-span-2 rounded-2xl reflective overflow-hidden bg-black/20 h-[calc(100vh-16rem)]">
            {selected ? (
              <SessionDetailView sessionId={selected} messages={messages} />
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
                <div className="w-12 h-12 rounded-full bg-white/[0.03] border border-white/[0.05] flex items-center justify-center">
                  <History size={20} className="text-white/20" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white/40 tracking-tight">Handshake Pending</h4>
                  <p className="text-xs text-white/20 mt-1">Select a session from the registry to decrypt logs</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
