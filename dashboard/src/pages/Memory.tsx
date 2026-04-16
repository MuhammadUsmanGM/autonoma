import { useEffect, useState, useCallback } from 'react'
import { Search, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api'
import MemoryTable from '../components/MemoryTable'
import type { Memory } from '../types'

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

  // Apply filters
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
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold">Memory Explorer</h2>
        <button
          onClick={load}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter memories..."
            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-xl pl-10 pr-4 py-2.5 text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)] transition-colors"
          />
        </div>
        <div className="flex gap-1.5">
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                typeFilter === t
                  ? 'bg-[var(--accent-dim)] text-[var(--accent)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/5'
              }`}
            >
              {t === 'all' ? 'All' : t}
            </button>
          ))}
        </div>
      </div>

      {/* Count */}
      <p className="text-xs text-[var(--text-muted)] mb-3">
        {filtered.length} memor{filtered.length === 1 ? 'y' : 'ies'}
        {typeFilter !== 'all' && ` (${typeFilter})`}
      </p>

      {/* Table */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        <MemoryTable memories={filtered} onDelete={handleDelete} />
      </div>
    </div>
  )
}
