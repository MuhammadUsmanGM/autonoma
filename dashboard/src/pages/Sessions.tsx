import { useEffect, useState, useCallback, useMemo } from 'react'
import { RefreshCw, History, Search, Filter } from 'lucide-react'
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
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'success' | 'error'>('all')

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

  const filteredSessions = useMemo(() => {
    return sessions.filter(s => {
      const matchesSearch = s.id.toLowerCase().includes(search.toLowerCase()) || 
                           s.channel.toLowerCase().includes(search.toLowerCase())
      
      const matchesStatus = statusFilter === 'all'
      
      return matchesSearch && matchesStatus
    })
  }, [sessions, search, statusFilter])

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
    <div className="p-10 space-y-8 h-screen flex flex-col">
      <header className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-[var(--text)] mb-2">Registry Logs</h2>
          <p className="text-sm text-[var(--text-muted)]">Replay and audit historical human-agent interactions</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[var(--bg-faint)] border border-[var(--border-faint)] text-[var(--text)] hover:bg-[var(--overlay)] transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Sync Sessions
        </button>
      </header>

      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
          <Skeleton className="h-full reflective rounded-2xl" />
          <Skeleton className="lg:col-span-2 h-full reflective rounded-2xl" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
          {/* Left Panel: Search & Filtered List */}
          <div className="flex flex-col min-h-0 gap-4">
             {/* Search & Filter Bar */}
             <div className="space-y-3">
                <div className="relative group">
                    <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/20 group-focus-within:text-[var(--accent)] transition-colors" />
                    <input 
                      type="text"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search ID or Platform..."
                      className="w-full bg-white/[0.02] border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-xs text-white outline-none focus:border-[var(--accent)]/40 focus:bg-white/[0.04] transition-all"
                    />
                </div>
                <div className="flex p-1 bg-white/[0.02] border border-white/10 rounded-xl">
                    {(['all', 'success', 'error'] as const).map(f => (
                        <button
                          key={f}
                          onClick={() => setStatusFilter(f)}
                          className={`flex-1 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-widest transition-all ${
                            statusFilter === f ? 'bg-[var(--accent)] text-black' : 'text-white/20 hover:text-white'
                          }`}
                        >
                          {f}
                        </button>
                    ))}
                </div>
             </div>

             {/* Session list */}
             <div className="flex-1 rounded-2xl reflective p-4 overflow-y-auto scrollbar-hide min-h-0">
                <h3 className="text-[10px] font-bold text-[var(--text-faint)] uppercase tracking-[0.2em] mb-4 px-2">Handshake Registry</h3>
                {filteredSessions.length > 0 ? (
                  <SessionList sessions={filteredSessions} selected={selected} onSelect={selectSession} />
                ) : (
                  <div className="py-20 text-center">
                      <Filter size={24} className="mx-auto mb-3 text-[var(--text-faint)]" />
                      <p className="text-[10px] font-bold text-[var(--text-faint)] uppercase tracking-widest">No matching resonance</p>
                  </div>
                )}
             </div>
          </div>

          {/* Right Panel: Detail View */}
          <div className="lg:col-span-2 rounded-2xl reflective overflow-hidden bg-black/20 flex flex-col min-h-0">
            {selected ? (
              <SessionDetailView sessionId={selected} messages={messages} />
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
                <div className="w-12 h-12 rounded-full bg-white/[0.03] border border-white/[0.05] flex items-center justify-center">
                  <History size={20} className="text-white/20" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white/40 tracking-tight text-center">Neural Link Inactive</h4>
                  <p className="text-xs text-white/20 mt-1 max-w-[200px] text-center">Select a historical handshake from the registry to replay transmission logs</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
