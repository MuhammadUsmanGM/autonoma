import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Terminal, Search, AlertTriangle, Pause, Play, Download } from 'lucide-react'
import { api } from '../api'
import type { LogEntry } from '../types'
import Dropdown from '../components/Dropdown'

const LEVELS = [
  { label: 'ALL LEVELS', value: 'ALL' },
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
]

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [level, setLevel] = useState('ALL')
  const [search, setSearch] = useState('')
  const [isPaused, setIsPaused] = useState(false)
  
  const wsRef = useRef<WebSocket | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  
  // Custom ref to always have the latest logs state without stale closures in WS
  const logsStateRef = useRef(logs)
  useEffect(() => {
    logsStateRef.current = logs
  }, [logs])

  const isPausedRef = useRef(isPaused)
  useEffect(() => {
    isPausedRef.current = isPaused
  }, [isPaused])

  useEffect(() => {
    const init = async () => {
      // 1. Fetch history
      try {
        const history = await api.getLogs({ level: level === 'ALL' ? undefined : level, q: search || undefined })
        setLogs(history)
      } catch (e) {
        console.error("Failed to load log history:", e)
      }
      
      // 2. Connect WS
      try {
        const config = await api.getConfig()
        const wsUrl = `ws://${config.gateway.host}:${config.gateway.port}`
        const ws = new WebSocket(wsUrl)
        wsRef.current = ws

        ws.onopen = () => {
          ws.send(JSON.stringify({ type: 'subscribe_logs' }))
        }

        ws.onmessage = (event) => {
          if (isPausedRef.current) return
          try {
            const msg = JSON.parse(event.data)
            if (msg.type === 'log' && msg.data) {
              const line = msg.data as LogEntry
              
              // Apply active filters
              if (level !== 'ALL') {
                const ranks: Record<string, number> = { "DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50 }
                if ((ranks[line.level] || 0) < (ranks[level] || 0)) return
              }
              if (search) {
                const q = search.toLowerCase()
                if (!line.message.toLowerCase().includes(q) && !line.logger.toLowerCase().includes(q)) return
              }

              setLogs(prev => [...prev.slice(-1999), line])
            }
          } catch (e) {
            // ignore
          }
        }
      } catch (e) {
        console.error("Failed to connect WS:", e)
      }
    }

    init()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [level, search]) // Re-run when filters change to fetch exact history and restart stream.

  // Auto-scroll
  useEffect(() => {
    if (!isPaused) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, isPaused])

  const handleDownload = () => {
    const raw = logs.map(l => `[${l.timestamp}] [${l.level}] ${l.logger}: ${l.message}`).join('\n')
    const blob = new Blob([raw], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `autonoma-logs-${new Date().toISOString()}.log`
    a.click()
  }

  const getLevelColor = (lvl: string) => {
    if (['ERROR', 'CRITICAL'].includes(lvl)) return 'text-[var(--error)] bg-[var(--error)]/10'
    if (lvl === 'WARNING') return 'text-[#f5a623] bg-[#f5a623]/10'
    if (lvl === 'DEBUG') return 'text-[var(--text-muted)] bg-[var(--bg-faint)]'
    return 'text-[var(--success)] bg-[var(--success)]/10'
  }

  return (
    <div className="flex flex-col h-full bg-[var(--bg)] font-mono text-sm relative pb-10">
      
      {/* Header Overlay */}
      <header className="shrink-0 flex items-center justify-between p-4 border-b border-[var(--border)] bg-[var(--bg-card)]/80 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-4 flex-1">
          <Terminal size={18} className="text-[var(--accent)]" />
          <h2 className="text-lg font-bold text-[var(--text)] tracking-wider">SYSTEM.LOGS</h2>
          
          <div className="h-6 w-px bg-[var(--border)] mx-2" />
          
          <div className="relative w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input 
              type="text" 
              placeholder="Search telemetry..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full bg-[var(--bg-faint)] border border-[var(--border)] rounded-lg pl-9 pr-4 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]/40 transition-colors"
            />
          </div>

          <div className="w-40 z-20">
            <Dropdown 
              options={LEVELS}
              value={level}
              onChange={setLevel}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button 
            onClick={handleDownload}
            className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg-faint)] transition-colors"
            title="Download Logs"
          >
            <Download size={16} />
          </button>
          
          <button 
            onClick={() => setIsPaused(!isPaused)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition-all ${
              isPaused 
                ? 'bg-orange-500/10 text-orange-400 border border-orange-500/20' 
                : 'bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20'
            }`}
          >
            {isPaused ? <Play size={12} /> : <Pause size={12} />}
            {isPaused ? 'RESUME' : 'PAUSE'}
          </button>
        </div>
      </header>

      {/* Log Visualizer */}
      <div className="flex-1 overflow-y-auto p-4 space-y-1 scroll-smooth">
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] opcity-50">
            <AlertTriangle size={32} className="mb-4 opacity-50" />
            <p>No telemetry recorded yet.</p>
          </div>
        ) : (
          logs.map((log, i) => (
            <motion.div 
              initial={{ opacity: 0, x: -5 }} animate={{ opacity: 1, x: 0 }}
              key={`${log.timestamp}-${i}`} 
              className="flex items-start gap-4 hover:bg-[var(--bg-faint)] rounded py-1 px-2 transition-colors group"
            >
              <div className="text-[10px] text-[var(--text-faint)] shrink-0 pt-0.5 opacity-50 group-hover:opacity-100">
                {log.timestamp.split('T')[1]?.substring(0, 12)}
              </div>
              <div className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 min-w-[60px] text-center ${getLevelColor(log.level)}`}>
                {log.level}
              </div>
              <div className="text-[10px] text-[var(--accent)] shrink-0 w-32 truncate pt-0.5" title={log.logger}>
                {log.logger}
              </div>
              <div className="text-xs text-[var(--text-sub)] break-words whitespace-pre-wrap">
                {log.message}
              </div>
            </motion.div>
          ))
        )}
        <div ref={logsEndRef} className="h-4" />
      </div>

    </div>
  )
}
