import { useEffect, useState } from 'react'
import { Radio, Brain, MessageSquare, Clock, Archive } from 'lucide-react'
import StatsCard from '../components/StatsCard'
import { api } from '../api'
import type { Stats } from '../types'

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = () => {
      api.getStats().then(setStats).catch((e) => setError(e.message))
    }
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  if (error) {
    return (
      <div className="p-8">
        <p className="text-[var(--error)]">Failed to load stats: {error}</p>
        <p className="text-sm text-[var(--text-muted)] mt-2">
          Make sure Autonoma is running on port 8766.
        </p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="p-8">
        <div className="animate-pulse flex gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 flex-1 rounded-xl bg-[var(--bg-card)]" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-8">
      <h2 className="text-xl font-semibold mb-6">Overview</h2>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatsCard label="Uptime" value={formatUptime(stats.uptime_seconds)} icon={Clock} />
        <StatsCard label="Active Channels" value={stats.channel_count} icon={Radio} accent />
        <StatsCard label="Memories" value={stats.memory_active} icon={Brain} accent />
        <StatsCard label="Sessions" value={stats.session_count} icon={MessageSquare} />
      </div>

      {/* Channels list */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5 mb-6">
        <h3 className="text-sm font-medium text-[var(--text-muted)] mb-3">Active Channels</h3>
        <div className="flex flex-wrap gap-2">
          {stats.active_channels.map((ch) => (
            <span
              key={ch}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/20"
            >
              {ch}
            </span>
          ))}
        </div>
      </div>

      {/* Memory breakdown */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <h3 className="text-sm font-medium text-[var(--text-muted)] mb-3">Memory Stats</h3>
        <div className="flex gap-6">
          <div className="flex items-center gap-2">
            <Brain size={16} className="text-[var(--accent)]" />
            <span className="text-sm">{stats.memory_active} active</span>
          </div>
          <div className="flex items-center gap-2">
            <Archive size={16} className="text-[var(--text-muted)]" />
            <span className="text-sm text-[var(--text-muted)]">{stats.memory_archived} archived</span>
          </div>
        </div>
      </div>
    </div>
  )
}
