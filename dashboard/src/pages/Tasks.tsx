import { useEffect, useState, useCallback } from 'react'
import { ListTodo, RefreshCw, XCircle, Clock, CheckCircle2, AlertTriangle, Loader2, Plus, ChevronRight } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import Skeleton from '../components/Skeleton'
import StatsCard from '../components/StatsCard'
import EmptyState from '../components/EmptyState'
import type { TaskItem, TaskStats } from '../types'

const STATUS_CONFIG: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  pending: { color: 'text-yellow-400', icon: Clock, label: 'QUEUED' },
  running: { color: 'text-[var(--accent)]', icon: Loader2, label: 'RUNNING' },
  completed: { color: 'text-[var(--success)]', icon: CheckCircle2, label: 'DONE' },
  failed: { color: 'text-[var(--error)]', icon: AlertTriangle, label: 'FAILED' },
  cancelled: { color: 'text-white/30', icon: XCircle, label: 'CANCELLED' },
}

function TaskRow({ task: initialTask, onCancel }: { task: TaskItem; onCancel: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [task, setTask] = useState(initialTask)

  const handleExpand = async () => {
    if (!expanded) {
      setExpanded(true)
      try {
        const fullTask = await api.getTask(initialTask.id)
        setTask(fullTask)
      } catch (e) {
        console.error('Failed to hydrate task:', e)
      }
    } else {
      setExpanded(false)
    }
  }

  const cfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
  const Icon = cfg.icon

  return (
    <div className="group border-b border-white/[0.02]">
      <div
        className="grid grid-cols-[1fr_120px_80px_100px_100px_60px] gap-4 px-6 py-4 hover:bg-white/[0.01] transition-all cursor-pointer items-center"
        onClick={handleExpand}
      >
        <div className="min-w-0">
          <p className="text-sm text-white/80 group-hover:text-white transition-colors truncate font-medium flex items-center gap-2">
            {task.name}
            {expanded && <ChevronRight size={12} className="rotate-90 text-[var(--accent)]" />}
          </p>
          <p className="text-[10px] font-mono text-white/20 mt-0.5 truncate">{task.id}</p>
        </div>

        <div className="flex items-center gap-2">
          <Icon size={12} className={`${cfg.color} ${task.status === 'running' ? 'animate-spin' : ''}`} />
          <span className={`text-[10px] font-bold uppercase tracking-widest ${cfg.color}`}>
            {cfg.label}
          </span>
        </div>

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

        <div className="text-right text-[11px] text-[var(--text-muted)]">
          {new Date(task.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
        </div>

        <div className="text-right text-[11px] font-mono text-[var(--text-muted)]">
          {task.retries}/{task.max_retries}
        </div>

        <div className="text-right">
          {(task.status === 'pending' || task.status === 'running') && (
            <button
              onClick={(e) => { e.stopPropagation(); onCancel(task.id) }}
              className="p-1.5 rounded-lg hover:bg-red-500/20 text-white/20 hover:text-red-400 transition-all cursor-pointer"
            >
              <XCircle size={14} />
            </button>
          )}
        </div>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-[var(--bg)]/40"
          >
            <div className="px-6 py-6 space-y-6">
               <div className="grid grid-cols-2 gap-8">
                  {/* Skill & Args */}
                  <div>
                    <h4 className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">Skill Target</h4>
                    <div className="bg-black/20 rounded-xl p-4 border border-white/5 font-mono text-xs">
                       <span className="text-[var(--accent)] font-bold">{task.skill}</span>
                       <div className="mt-2 text-white/40 break-all">{JSON.stringify(task.args, null, 2)}</div>
                    </div>
                  </div>

                  {/* Result/Error */}
                  <div>
                    <h4 className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">Execution Outcome</h4>
                    {task.error ? (
                      <div className="bg-red-500/5 rounded-xl p-4 border border-red-500/10 text-[var(--error)] text-xs font-mono">
                         {task.error}
                      </div>
                    ) : task.result ? (
                      <div className="bg-[var(--success)]/5 rounded-xl p-4 border border-[var(--success)]/10 text-[var(--success)] text-xs font-mono">
                         {JSON.stringify(task.result, null, 2)}
                      </div>
                    ) : (
                      <div className="bg-white/5 rounded-xl p-4 border border-white/5 text-white/20 text-xs italic">
                         Pending execution result...
                      </div>
                    )}
                  </div>
               </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}



export default function Tasks() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [stats, setStats] = useState<TaskStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [showNewTask, setShowNewTask] = useState(false)
  const [manifest, setManifest] = useState<any[]>([])

  const load = useCallback(() => {
    api.getTasks().then((d) => { setTasks(d); setLoading(false) }).catch(() => setLoading(false))
    api.getTaskStats().then(setStats).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    api.getSkillManifest().then(setManifest).catch(() => {})
    const id = setInterval(load, 5000)
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

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    const form = e.target as HTMLFormElement
    const data = {
      name: (form.elements.namedItem('name') as HTMLInputElement).value,
      skill: (form.elements.namedItem('skill') as HTMLSelectElement).value,
      args: JSON.parse((form.elements.namedItem('args') as HTMLTextAreaElement).value || '{}'),
      priority: parseInt((form.elements.namedItem('priority') as HTMLSelectElement).value)
    }
    
    try {
      await api.createTask(data)
      toast.success('Task scheduled')
      setShowNewTask(false)
      load()
    } catch (err: any) {
      toast.error(`Scheduling failed: ${err.message}`)
    }
  }

  return (
    <div className="p-10 space-y-8 h-full flex flex-col overflow-y-auto">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Task Queue</h2>
          <p className="text-sm text-[var(--text-muted)]">Autonomous work items scheduled for execution</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowNewTask(true)}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold bg-[var(--accent)] text-black shadow-lg shadow-[var(--accent-glow)] hover:scale-105 active:scale-95 transition-all cursor-pointer"
          >
            <Plus size={16} />
            Dispatch New Task
          </button>
          <button
            onClick={load}
            className="p-2.5 rounded-xl bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
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
      <div className="flex-1 min-h-0">
        {loading ? (
          <Skeleton className="h-full reflective rounded-2xl" />
        ) : tasks.length === 0 ? (
          <EmptyState 
            icon={ListTodo}
            title="Task Queue Clear"
            description="No autonomous work items are currently scheduled. Tasks appear here when the agent identifies background work or you manually dispatch a mission."
            actionLabel="Dispatch New Task"
            onAction={() => setShowNewTask(true)}
          />
        ) : (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-3xl reflective overflow-hidden shadow-2xl flex flex-col h-full bg-white/[0.01]"
          >
            {/* Table header */}
            <div className="grid grid-cols-[1fr_120px_80px_100px_100px_60px] gap-4 px-6 py-4 border-b border-white/5 bg-white/[0.02]">
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Task</span>
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Status</span>
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Priority</span>
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Created</span>
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right">Retries</span>
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest text-right"></span>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar">
              {tasks.map((task) => (
                <TaskRow key={task.id} task={task} onCancel={handleCancel} />
              ))}
            </div>
          </motion.div>
        )}
      </div>

      {/* New Task Modal */}
      <AnimatePresence>
        {showNewTask && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-6">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowNewTask(false)}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="relative w-full max-w-lg bg-[var(--bg-card)] border border-white/10 rounded-3xl shadow-2xl p-8 space-y-6"
            >
               <h3 className="text-xl font-bold text-white">Dispatch New Task</h3>
               <form onSubmit={handleCreate} className="space-y-4">
                  <div className="space-y-1">
                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Task Label</label>
                    <input name="name" required placeholder="e.g. Daily Market Summary" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm outline-none focus:border-[var(--accent)]/40 transition-colors" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Target Skill</label>
                      <select name="skill" required className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm outline-none focus:border-[var(--accent)]/40 transition-colors appearance-none">
                        {manifest.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Priority</label>
                      <select name="priority" defaultValue="2" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm outline-none focus:border-[var(--accent)]/40 transition-colors appearance-none">
                        <option value="1">P1 (Urgent)</option>
                        <option value="2">P2 (Normal)</option>
                        <option value="3">P3 (Background)</option>
                      </select>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Arguments (JSON)</label>
                    <textarea name="args" rows={4} placeholder="{}" className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-mono outline-none focus:border-[var(--accent)]/40 transition-colors" />
                  </div>
                  <div className="flex gap-3 pt-4">
                    <button type="button" onClick={() => setShowNewTask(false)} className="flex-1 px-6 py-3 rounded-xl border border-white/10 text-sm font-bold text-[var(--text-muted)] hover:bg-white/5 transition-all">Cancel</button>
                    <button type="submit" className="flex-1 px-6 py-3 rounded-xl bg-[var(--accent)] text-black text-sm font-bold shadow-lg shadow-[var(--accent-glow)] hover:scale-105 active:scale-95 transition-all">Dispatch</button>
                  </div>
               </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}
