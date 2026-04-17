import { useEffect, useState, useCallback, useMemo } from 'react'
import { Search, RefreshCw, Sparkles, Trash2, CheckSquare, X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import MemoryTable from '../components/MemoryTable'
import type { Memory } from '../types'
import Skeleton from '../components/Skeleton'

const TYPES = ['all', 'remember', 'fact', 'preference', 'conversation_summary', 'maintenance']

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [stale, setStale] = useState<Memory[]>([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

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

  const filtered = useMemo(() => {
    if (typeFilter === 'maintenance') {
      let res = stale
      if (search.trim()) {
        const q = search.toLowerCase()
        res = res.filter(m => m.content.toLowerCase().includes(q))
      }
      return res
    }

    let result = memories
    if (typeFilter !== 'all') {
      result = result.filter((m) => m.type === typeFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter((m) => m.content.toLowerCase().includes(q))
    }
    return result
  }, [memories, stale, typeFilter, search])

  const handleDelete = async (id: number) => {
    try {
      await api.deleteMemory(id)
      setMemories((prev) => prev.filter((m) => m.id !== id))
      setStale((prev) => prev.filter((m) => m.id !== id))
      setSelectedIds((prev) => prev.filter(i => i !== id))
      toast.success('Neural path pruned')
    } catch {
      toast.error('Failed to prune memory')
    }
  }

  const handleReview = async (id: number, action: 'review' | 'dismiss') => {
    try {
      await api.reviewMemory(id, action)
      setStale((prev) => prev.filter((m) => m.id !== id))
      setSelectedIds((prev) => prev.filter(i => i !== id))
      if (action === 'review') {
        toast.success('Cognitive node reinforced')
        load() 
      } else {
        toast.success('Information discarded')
      }
    } catch {
      toast.error('Maintenance command failed')
    }
  }

  const bulkDelete = async () => {
    const count = selectedIds.length
    if (count === 0) return
    const promise = Promise.all(selectedIds.map(id => api.deleteMemory(id)))
    toast.promise(promise, {
      loading: `Pruning ${count} neural nodes...`,
      success: () => {
        setMemories(prev => prev.filter(m => !selectedIds.includes(m.id)))
        setStale(prev => prev.filter(m => !selectedIds.includes(m.id)))
        setSelectedIds([])
        return `${count} paths removed from registry`
      },
      error: 'Bulk pruning failed'
    })
  }

  const onToggleSelect = (id: number) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id])
  }

  const onToggleAll = () => {
    const currentPageIds = filtered.map(m => m.id)
    const allSelected = currentPageIds.every(id => selectedIds.includes(id))
    if (allSelected) {
      setSelectedIds(prev => prev.filter(id => !currentPageIds.includes(id)))
    } else {
      setSelectedIds(prev => Array.from(new Set([...prev, ...currentPageIds])))
    }
  }

  return (
    <div className="p-10 space-y-8 pb-32">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Cognitive Explorer</h2>
          <p className="text-sm text-[var(--text-muted)]">Browse and manage the agent's neural resonance</p>
        </div>
        <div className="flex items-center gap-3">
          {typeFilter === 'maintenance' && filtered.length > 0 && (
             <button
              onClick={() => setSelectedIds(filtered.map(m => m.id))}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[var(--accent-dim)] border border-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent-dim)]/40 transition-colors cursor-pointer"
            >
              <CheckSquare size={14} />
              Select All Stale
            </button>
          )}
          <button
            onClick={load}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Sync Registry
          </button>
        </div>
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
                onClick={() => { setTypeFilter(t); setSelectedIds([]) }}
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
          {filtered.map((m) => {
            const isSelected = selectedIds.includes(m.id)
            return (
              <motion.div 
                key={m.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                onClick={() => onToggleSelect(m.id)}
                className={`rounded-2xl reflective p-6 flex flex-col gap-4 border cursor-pointer transition-all ${
                  isSelected ? 'border-[var(--accent)] bg-[var(--accent-dim)]/20 shadow-[0_0_20px_var(--accent-glow)]' : 'border-[var(--accent)]/10'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <input 
                      type="checkbox" 
                      checked={isSelected}
                      readOnly
                      className="w-3.5 h-3.5 rounded border-white/10 bg-black/40 accent-[var(--accent)]"
                    />
                    <span className="text-[10px] font-bold text-[var(--accent)] uppercase tracking-widest">Decaying node</span>
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)]">ID: #{m.id}</span>
                </div>
                <p className="text-sm text-white/90 leading-relaxed italic">"{m.content}"</p>
                <div className="mt-auto flex items-center justify-end gap-3 pt-4 border-t border-white/5" onClick={e => e.stopPropagation()}>
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
            )
          })}
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
          <MemoryTable 
            memories={filtered} 
            selectedIds={selectedIds}
            onToggleSelect={onToggleSelect}
            onToggleAll={onToggleAll}
            onDelete={handleDelete} 
          />
        </motion.div>
      )}

      {/* Bulk actions bar */}
      <AnimatePresence>
        {selectedIds.length > 0 && (
          <motion.div
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            className="fixed bottom-10 left-1/2 -translate-x-1/2 z-50 px-8 py-4 glass rounded-3xl border border-[var(--accent)]/50 shadow-[0_20px_50px_rgba(0,0,0,0.5)] flex items-center gap-8"
          >
            <div className="flex items-center gap-4 border-r border-white/10 pr-8">
              <div className="w-10 h-10 rounded-2xl bg-[var(--accent)] text-black flex items-center justify-center font-bold text-lg">
                {selectedIds.length}
              </div>
              <div>
                <h4 className="text-sm font-bold text-white">Nodes targeted</h4>
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Batch execution ready</p>
              </div>
            </div>
            
            <div className="flex items-center gap-4">
              <button 
                onClick={bulkDelete}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold bg-white text-black hover:bg-white/90 transition-all cursor-pointer"
              >
                <Trash2 size={16} />
                Prune Selected
              </button>
              <button 
                onClick={() => setSelectedIds([])}
                className="p-2.5 rounded-xl glass hover:bg-white/5 transition-all text-white/40 hover:text-white cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
