import { useEffect, useState, useCallback } from 'react'
import { Search, RefreshCw } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import MemoryTable from '../components/MemoryTable'
import type { Memory } from '../types'
import Skeleton from '../components/Skeleton'

const TYPES = ['all', 'remember', 'fact', 'preference', 'conversation_summary']

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [filtered, setFiltered] = useState<Memory[]>([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getMemories()
      setMemories(data)
    } catch (e) {
      toast.error('Failed to load memories')
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    let result = memories
    if (typeFilter !== 'all') {
      result = result.filter((m) => m.type === typeFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter((m) => m.content.toLowerCase().includes(q))
    }
    setFiltered(result)
  }, [memories, typeFilter, search])

  const handleDelete = async (id: number) => {
    try {
      await api.deleteMemory(id)
      setMemories((prev) => prev.filter((m) => m.id !== id))
      toast.success('Memory deleted')
    } catch {
      toast.error('Failed to delete memory')
    }
  }

  return (
    <div className="p-10 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Cognitive Explorer</h2>
          <p className="text-sm text-[var(--text-muted)]">Browse and manage long-term agent memories</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh Registry
        </button>
      </header>

      {/* Filters Overlay */}
      <div className="flex flex-col lg:flex-row gap-4">
        <div className="relative flex-1 group">
          <Search size={18} className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent)] transition-colors" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search within neural paths..."
            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl pl-12 pr-4 py-3 text-sm text-[var(--text)] placeholder:text-white/20 outline-none focus:border-[var(--accent)]/40 focus:ring-1 focus:ring-[var(--accent)]/20 transition-all shadow-xl"
          />
        </div>
        
        <div className="p-1 bg-white/[0.03] border border-[var(--border)] rounded-2xl flex gap-1 shadow-lg">
          {TYPES.map((t) => {
            const active = typeFilter === t
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`relative px-4 py-2 rounded-xl text-[11px] font-bold uppercase tracking-widest transition-all cursor-pointer ${
                  active ? 'text-black' : 'text-[var(--text-muted)] hover:text-white'
                }`}
              >
                {active && (
                  <motion.div
                    layoutId="active-type"
                    className="absolute inset-0 bg-[var(--accent)] rounded-xl"
                    transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
                  />
                )}
                <span className="relative z-10">{t === 'all' ? 'All' : t.replace('_', ' ')}</span>
              </button>
            )
          })}
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-[400px] w-full reflective rounded-3xl" />
        </div>
      ) : (
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-3xl reflective overflow-hidden shadow-2xl"
        >
          <div className="p-6 border-b border-[var(--border)] bg-white/[0.01] flex items-center justify-between">
            <span className="text-xs font-bold text-white uppercase tracking-widest">Memory Matrix</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-tight">{filtered.length} entries registered</span>
          </div>
          <MemoryTable memories={filtered} onDelete={handleDelete} />
        </motion.div>
      )}
    </div>
  )
}
