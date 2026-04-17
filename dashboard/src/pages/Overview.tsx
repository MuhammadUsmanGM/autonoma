import { useEffect, useState } from 'react'
import { Radio, Brain, MessageSquare, Clock, Archive, Settings2, Activity } from 'lucide-react'
import { motion } from 'framer-motion'
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
      <div className="p-10 flex flex-col items-center justify-center h-full text-center">
        <div className="w-12 h-12 rounded-full bg-[var(--error)]/10 flex items-center justify-center mb-4">
          <Settings2 className="text-[var(--error)]" size={24} />
        </div>
        <h3 className="text-lg font-semibold text-white">System Error</h3>
        <p className="text-[var(--text-muted)] mt-2 max-w-xs">{error}</p>
        <button 
          onClick={() => window.location.reload()}
          className="mt-6 px-6 py-2 rounded-xl bg-white/5 border border-white/10 text-sm font-medium hover:bg-white/10 transition-colors"
        >
          Retry Connection
        </button>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="p-10 space-y-8">
        <div className="h-12 w-48 bg-white/5 rounded-lg animate-pulse" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-32 rounded-2xl bg-white/5 animate-pulse" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-10 space-y-10">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Systems Overview</h2>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-[var(--success)] font-bold uppercase tracking-widest bg-[var(--success)]/10 px-2 py-0.5 rounded">
              <Activity size={12} />
              Operational
            </span>
            <span className="text-xs text-[var(--text-muted)] font-medium">Last updated: Just now</span>
          </div>
        </div>
      </header>

      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard label="System Uptime" value={formatUptime(stats.uptime_seconds)} icon={Clock} />
        <StatsCard label="Connected Channels" value={stats.channel_count} icon={Radio} accent />
        <StatsCard label="Neural Memories" value={stats.memory_active} icon={Brain} accent />
        <StatsCard label="Processed Sessions" value={stats.session_count} icon={MessageSquare} />
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Channels list */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="lg:col-span-2 rounded-2xl reflective p-8"
        >
          <h3 className="text-sm font-bold text-white uppercase tracking-widest mb-6 flex items-center gap-2">
            <Radio size={16} className="text-[var(--accent)]" />
            Active Pathways
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {stats.active_channels.map((ch) => (
              <div
                key={ch}
                className="group px-4 py-4 rounded-xl bg-white/[0.03] border border-white/[0.05] hover:border-[var(--accent)]/30 hover:bg-[var(--accent-dim)] transition-all flex flex-col gap-2"
              >
                <span className="text-xs font-bold text-white uppercase tracking-wider">{ch}</span>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--text-muted)] group-hover:text-[var(--accent)]/70 transition-colors capitalize">Protocol: WebSocket</span>
                  <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
                </div>
              </div>
            ))}
            {stats.active_channels.length === 0 && (
              <p className="text-xs text-[var(--text-muted)] py-4">No channels connected yet.</p>
            )}
          </div>
        </motion.div>

        {/* Memory breakdown */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1 }}
          className="rounded-2xl reflective p-8 flex flex-col"
        >
          <h3 className="text-sm font-bold text-white uppercase tracking-widest mb-6 flex items-center gap-2">
            <Brain size={16} className="text-[var(--accent)]" />
            Cognitive Storage
          </h3>
          <div className="flex-1 space-y-6">
            <div className="p-4 rounded-xl bg-[var(--accent-dim)] border border-[var(--accent)]/10">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-[var(--accent)]">Active Context</span>
                <span className="text-lg font-bold text-white">{stats.memory_active}</span>
              </div>
              <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-[var(--accent)] glow-sm" 
                  style={{ width: `${Math.min((stats.memory_active / (stats.memory_active + stats.memory_archived || 1)) * 100, 100)}%` }} 
                />
              </div>
            </div>
            
            <div className="p-4 rounded-xl bg-white/[0.02] border border-white/5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-[var(--text-muted)]">Archived Data</span>
                <span className="text-lg font-bold text-white/60">{stats.memory_archived}</span>
              </div>
              <div className="h-1.5 w-full bg-black/20 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-white/10" 
                  style={{ width: `${Math.min((stats.memory_archived / (stats.memory_active + stats.memory_archived || 1)) * 100, 100)}%` }} 
                />
              </div>
            </div>
          </div>
          <p className="mt-8 text-[10px] text-[var(--text-muted)] uppercase tracking-tight text-center">
            Optimized via BM25 & Importance Decay
          </p>
        </motion.div>
      </div>
    </div>
  )
}
