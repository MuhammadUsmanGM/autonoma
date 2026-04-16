import { useEffect, useState, useCallback } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api'
import SessionList from '../components/SessionList'
import SessionDetailView from '../components/SessionDetail'
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
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Sessions</h2>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Session list */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3 max-h-[calc(100vh-10rem)] overflow-y-auto">
          <SessionList sessions={sessions} selected={selected} onSelect={selectSession} />
        </div>

        {/* Session detail */}
        <div className="lg:col-span-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
          {selected ? (
            <SessionDetailView sessionId={selected} messages={messages} />
          ) : (
            <div className="flex items-center justify-center h-64">
              <p className="text-sm text-[var(--text-muted)]">
                Select a session to view its conversation
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
