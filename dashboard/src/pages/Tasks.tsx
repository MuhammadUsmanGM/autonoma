import { useEffect, useState, useCallback } from 'react'
import { ListTodo, RefreshCw, XCircle, Clock, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import Skeleton from '../components/Skeleton'
import StatsCard from '../components/StatsCard'
import type { TaskItem, TaskStats } from '../types'

const STATUS_CONFIG: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  pending: { color: 'text-yellow-400', icon: Clock, label: 'QUEUED' },
  running: { color: 'text-[var(--accent)]', icon: Loader2, label: 'RUNNING' },
  completed: { color: 'text-[var(--success)]', icon: CheckCircle2, label: 'DONE' },
  failed: { color: 'text-[var(--error)]', icon: AlertTriangle, label: 'FAILED' },
  cancelled: { color: 'text-white/30', icon: XCircle, label: 'CANCELLED' },
}

export default function Tasks() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [stats, setStats] = useState<TaskStats | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    api.getTasks().then((d) => { setTasks(d); setLoading(false) }).catch(() => setLoading(false))
    api.getTaskStats().then(setStats).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [load])

  const handleCancel = async (id: string) => {
    try {
      await api.cancelTask(id)
      toast.success('Task cancelled')
      load()
    } catch {
      toast.error('Failed to cancel task')
    }
  }

  return (
    <div className="p-10 space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Task Queue</h2>
          <p className="text-sm text-[var(--text-muted)]">Autonomous work items scheduled for execution</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Sync Queue
        </button>
      </header>

      {/* Stats */}
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-24 reflective rounded-2xl" />)}
        </div>
      ) : stats && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <StatsCard label="Total" value={stats.total} />
          <StatsCard label="Pending" value={stats.pending} icon={Clock} />
          <StatsCard label="Running" value={stats.running} icon={Loader2} accent />
          <StatsCard label="Completed" value={stats.completed} icon={CheckCircle2} />
          <StatsCard label="Failed" value={stats.failed} icon={AlertTriangle} />
        </div>
      )}

      {/* Task List */}
      {loading ? (
        <Skeleton className="h-80 reflective rounded-2xl" />
      ) : tasks.length === 0 ? (
        <div className="text-center py-20 reflective rounded-2xl">
          <ListTodo size={32} className="mx-auto mb-4 text-white/10" />
          <p className="text-sm text-white/30 font-medium">No tasks in queue</p>
          <p className="text-xs text-white/15 mt-1">Tasks appear here when the agent schedules autonomous work</p>
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-3xl reflective overflow-hidden shadow-2xl"
        >
          {/* Table header */}
          <div className="grid grid-cols-[1fr_120px_80px_100px_100px_60px] gap-4 px-6 py-4 border-b border-[var(--border)] bg-white/[0.01]">
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Task</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Status</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Priority</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Created</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Retries</span>
            <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest"></span>
          </div>

          {/* Rows */}
          <div className="divide-y divide-white/[0.02]">
            {tasks.map((task) => {
              const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
              const Icon = cfg.icon
              return (
                <div
                  key={task.id}
                  className="grid grid-cols-[1fr_120px_80px_100px_100px_60px] gap-4 px-6 py-4 hover:bg-white/[0.03] transition-all group"
                >
                  {/* Name + ID */}
                  <div className="min-w-0">
                    <p className="text-sm text-white/80 group-hover:text-white transition-colors truncate font-medium">
                      {task.name}
                    </p>
                    <p className="text-[10px] font-mono text-white/20 mt-0.5 truncate">{task.id}</p>
                  </div>

                  {/* Status */}
                  <div className="flex items-center gap-2">
                    <Icon size={12} className={`${cfg.color} ${task.status === 'running' ? 'animate-spin' : ''}`} />
                    <span className={`text-[10px] font-bold uppercase tracking-widest ${cfg.color}`}>
                      {cfg.label}
                    </span>
                  </div>

                  {/* Priority */}
                  <div className="text-right">
                    <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-lg ${
                      task.priority <= 1
                        ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                        : task.priority === 2
                        ? 'bg-[var(--accent-dim)] text-[var(--accent)] border border-[var(--accent)]/20'
                        : 'bg-white/5 text-white/40 border border-white/10'
                    }`}>
                      P{task.priority}
                    </span>
                  </div>

                  {/* Created */}
                  <div className="text-right text-[11px] text-[var(--text-muted)]">
                    {new Date(task.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                  </div>

                  {/* Retries */}
                  <div className="text-right text-[11px] font-mono text-[var(--text-muted)]">
                    {task.retries}/{task.max_retries}
                  </div>

                  {/* Cancel */}
                  <div className="text-right">
                    {(task.status === 'pending' || task.status === 'running') && (
                      <button
                        onClick={() => handleCancel(task.id)}
                        className="p-1.5 rounded-lg hover:bg-red-500/20 text-white/20 hover:text-red-400 transition-all cursor-pointer"
                        title="Cancel task"
                      >
                        <XCircle size={14} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Error/Result details for failed/completed tasks */}
          {tasks.some(t => t.error) && (
            <div className="border-t border-[var(--border)] px-6 py-4">
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3 block">Recent Errors</span>
              {tasks.filter(t => t.error).slice(0, 3).map(t => (
                <div key={t.id} className="mt-2 p-3 rounded-xl bg-[var(--error)]/5 border border-[var(--error)]/10">
                  <span className="text-[10px] text-white/40 font-mono">{t.name}: </span>
                  <span className="text-xs text-[var(--error)] font-mono">{t.error}</span>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      )}
    </div>
  )
}
