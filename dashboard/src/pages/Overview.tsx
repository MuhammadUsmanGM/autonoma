import { useEffect, useState } from 'react'
import { Radio, Brain, MessageSquare, Clock, Archive, Settings2, Activity } from 'lucide-react'
import { motion } from 'framer-motion'
import StatsCard from '../components/StatsCard'
import { api } from '../api'
import type { Stats, TraceItem } from '../types'
import Skeleton from '../components/Skeleton'

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [recentTraces, setRecentTraces] = useState<TraceItem[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = () => {
      Promise.all([
        api.getStats(),
        api.getTraces(5)
      ]).then(([s, t]) => {
        setStats(s)
        setRecentTraces(t)
        setLoading(false)
      }).catch((e) => {
        setError(e.message)
        setLoading(false)
      })
    }
    load()
    const id = setInterval(load, 15000)
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
      <div className="p-10 space-y-10">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
          <Skeleton className="h-32 reflective rounded-2xl" />
          <Skeleton className="h-32 reflective rounded-2xl" />
          <Skeleton className="h-32 reflective rounded-2xl" />
          <Skeleton className="h-32 reflective rounded-2xl" />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <Skeleton className="lg:col-span-2 h-64 reflective rounded-2xl" />
          <Skeleton className="h-64 reflective rounded-2xl" />
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

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        {/* Pulse / Activity Feed */}
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="xl:col-span-2 rounded-2xl reflective p-8 flex flex-col"
        >
          <div className="flex items-center justify-between mb-8">
            <h3 className="text-sm font-bold text-white uppercase tracking-widest flex items-center gap-2">
              <Activity size={16} className="text-[var(--accent)]" />
              Recent Pulses
            </h3>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-tight">Real-time Telemetry</span>
          </div>
          
          <div className="space-y-4">
            {recentTraces.map((trace) => (
              <div 
                key={trace.id}
                className="group flex items-center gap-4 p-4 rounded-xl bg-white/[0.02] border border-white/[0.05] hover:border-[var(--accent)]/30 hover:bg-[var(--accent-dim)] transition-all cursor-pointer"
              >
                <div className={`w-2 h-2 rounded-full shrink-0 ${trace.status === 'completed' ? 'bg-[var(--success)] shadow-lg shadow-[var(--success)]/20' : trace.status === 'error' ? 'bg-[var(--error)] shadow-lg shadow-[var(--error)]/20' : 'bg-blue-400 shadow-lg shadow-blue-400/20'}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-sm font-semibold text-white truncate capitalize">{trace.channel} Interaction</span>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">{new Date(trace.started_at).toLocaleTimeString()}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] text-[var(--accent)] font-bold uppercase tracking-wider">ID: {trace.id}</span>
                    <span className="text-[10px] text-white/20">|</span>
                    <span className="text-[10px] text-[var(--text-muted)] truncate">Session: {trace.session_id}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <span className="text-xs font-mono text-[var(--accent)] font-bold">{Math.round(trace.elapsed_seconds * 1000)}ms</span>
                </div>
              </div>
            ))}
            {recentTraces.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-center opacity-40">
                <Archive size={32} className="mb-4 text-[var(--text-muted)]" />
                <p className="text-xs text-[var(--text-muted)] uppercase tracking-widest">No activity pulses detected</p>
              </div>
            )}
          </div>
        </motion.div>

        <div className="space-y-8 flex flex-col">
          {/* Channels list */}
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex-1 rounded-2xl reflective p-8"
          >
            <h3 className="text-sm font-bold text-white uppercase tracking-widest mb-6 flex items-center gap-2">
              <Radio size={16} className="text-[var(--accent)]" />
              Pathways
            </h3>
            <div className="space-y-3">
              {stats.active_channels.map((ch) => (
                <div
                  key={ch}
                  className="px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.05] flex items-center justify-between"
                >
                  <span className="text-[11px] font-bold text-white uppercase tracking-wider">{ch}</span>
                  <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] glow-sm" />
                </div>
              ))}
              {stats.active_channels.length === 0 && (
                <p className="text-[10px] text-[var(--text-muted)] py-4 text-center">No active signals.</p>
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
              Cognitive
            </h3>
            <div className="space-y-6">
              <div className="p-4 rounded-xl bg-[var(--accent-dim)] border border-[var(--accent)]/10">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-[var(--accent)]">Active</span>
                  <span className="text-lg font-bold text-white">{stats.memory_active}</span>
                </div>
                <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-[var(--accent)] glow-sm" 
                    style={{ width: `${Math.min((stats.memory_active / (stats.memory_active + stats.memory_archived || 1)) * 100, 100)}%` }} 
                  />
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
