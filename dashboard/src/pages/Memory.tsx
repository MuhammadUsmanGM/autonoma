import { useEffect, useState, useCallback } from 'react'
import { Search, RefreshCw, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import MemoryTable from '../components/MemoryTable'
import type { Memory } from '../types'
import Skeleton from '../components/Skeleton'

const TYPES = ['all', 'remember', 'fact', 'preference', 'conversation_summary', 'maintenance']

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [stale, setStale] = useState<Memory[]>([])
  const [filtered, setFiltered] = useState<Memory[]>([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [regular, staleData] = await Promise.all([
        api.getMemories(),
        api.getStaleMemories()
      ])
      setMemories(regular)
      setStale(staleData)
    } catch (e) {
      toast.error('Failed to sync cognitive registry')
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (typeFilter === 'maintenance') {
      let res = stale
      if (search.trim()) {
        const q = search.toLowerCase()
        res = res.filter(m => m.content.toLowerCase().includes(q))
      }
      setFiltered(res)
      return
    }

    let result = memories
    if (typeFilter !== 'all') {
      result = result.filter((m) => m.type === typeFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter((m) => m.content.toLowerCase().includes(q))
    }
    setFiltered(result)
  }, [memories, stale, typeFilter, search])

  const handleDelete = async (id: number) => {
    try {
      await api.deleteMemory(id)
      setMemories((prev) => prev.filter((m) => m.id !== id))
      setStale((prev) => prev.filter((m) => m.id !== id))
      toast.success('Neural path pruned')
    } catch {
      toast.error('Failed to prune memory')
    }
  }

  const handleReview = async (id: number, action: 'review' | 'dismiss') => {
    try {
      await api.reviewMemory(id, action)
      setStale((prev) => prev.filter((m) => m.id !== id))
      if (action === 'review') {
        toast.success('Cognitive node reinforced')
        load() // Reload regular memories to show the updated access time
      } else {
        toast.success('Information discarded')
      }
    } catch {
      toast.error('Maintenance command failed')
    }
  }

  return (
    <div className="p-10 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Cognitive Explorer</h2>
          <p className="text-sm text-[var(--text-muted)]">Browse and manage the agent's neural resonance</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Sync Registry
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
        
        <div className="p-1 bg-white/[0.03] border border-[var(--border)] rounded-2xl flex gap-1 shadow-lg overflow-x-auto scrollbar-hide">
          {TYPES.map((t) => {
            const active = typeFilter === t
            const count = t === 'maintenance' ? stale.length : undefined
            return (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`relative px-4 py-2 rounded-xl text-[10px] font-bold uppercase tracking-widest transition-all cursor-pointer whitespace-nowrap min-w-fit ${
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
                <span className="relative z-10">
                  {t === 'all' ? 'Universal' : t.replace('_', ' ')}
                  {count !== undefined && count > 0 && (
                    <span className={`ml-2 px-1.5 py-0.5 rounded-full text-[9px] ${active ? 'bg-black/20' : 'bg-[var(--accent)]/20 text-[var(--accent)]'}`}>
                      {count}
                    </span>
                  )}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-[500px] w-full reflective rounded-3xl" />
        </div>
      ) : typeFilter === 'maintenance' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {filtered.map((m) => (
            <motion.div 
              key={m.id}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="rounded-2xl reflective p-6 flex flex-col gap-4 border border-[var(--accent)]/10"
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold text-[var(--accent)] uppercase tracking-widest">Decaying node</span>
                <span className="text-[10px] text-[var(--text-muted)]">ID: #{m.id}</span>
              </div>
              <p className="text-sm text-white/90 leading-relaxed italic">"{m.content}"</p>
              <div className="mt-auto flex items-center justify-end gap-3 pt-4 border-t border-white/5">
                <button 
                  onClick={() => handleReview(m.id, 'dismiss')}
                  className="px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase text-[var(--error)] hover:bg-[var(--error)]/10 transition-colors"
                >
                  Prune
                </button>
                <button 
                  onClick={() => handleReview(m.id, 'review')}
                  className="px-4 py-1.5 rounded-lg text-[10px] font-bold uppercase bg-[var(--accent)] text-black hover:scale-105 active:scale-95 transition-all"
                >
                  Reinforce
                </button>
              </div>
            </motion.div>
          ))}
          {filtered.length === 0 && (
            <div className="col-span-full py-20 text-center rounded-3xl reflective border border-dashed border-white/10">
              <Sparkles className="mx-auto mb-4 text-[var(--accent)]/20" size={40} />
              <p className="text-sm font-medium text-[var(--text-muted)] uppercase tracking-widest">Cognitive resonance clear</p>
            </div>
          )}
        </div>
      ) : (
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-3xl reflective overflow-hidden shadow-2xl"
        >
          <div className="p-6 border-b border-[var(--border)] bg-white/[0.01] flex items-center justify-between">
            <span className="text-xs font-bold text-white uppercase tracking-widest">Memory Matrix</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-tight">{filtered.length} nodes active</span>
          </div>
          <MemoryTable memories={filtered} onDelete={handleDelete} />
        </motion.div>
      )}
    </div>
  )
}
