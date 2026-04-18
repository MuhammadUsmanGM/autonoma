import { useEffect, useState, useRef } from 'react'
import { Terminal, Search, Trash2, Pause, Play, Download } from 'lucide-react'
import type { LogEntry } from '../types'

export default function LiveLogStream() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState('')
  const [isPaused, setIsPaused] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws`)
    
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe_logs' }))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'log' && !isPaused) {
        setLogs(prev => [...prev, data.data].slice(-500))
      }
    }

    wsRef.current = ws
    return () => ws.close()
  }, [isPaused])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  const filteredLogs = logs.filter(l => 
    !filter || 
    l.message.toLowerCase().includes(filter.toLowerCase()) || 
    l.logger.toLowerCase().includes(filter.toLowerCase())
  )

  const clear = () => setLogs([])

  const download = () => {
    const content = logs.map(l => `[${l.timestamp}] ${l.level} [${l.logger}]: ${l.message}`).join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `agent-logs-${new Date().toISOString()}.log`
    a.click()
  }

  return (
    <div className="flex flex-col h-full bg-[#080808] border border-white/5 rounded-2xl overflow-hidden shadow-2xl">
      {/* Toolbar */}
      <header className="px-4 py-3 bg-white/[0.02] border-b border-white/5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Terminal size={14} className="text-[var(--accent)]" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--accent)]">Live Telemetry</span>
        </div>
        
        <div className="flex-1 max-w-sm relative">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20" />
          <input 
            type="text" 
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Grep logs..."
            className="w-full bg-black/40 border border-white/5 rounded-lg pl-9 pr-3 py-1.5 text-[11px] text-white outline-none focus:border-[var(--accent)]/30 transition-all font-mono"
          />
        </div>

        <div className="flex items-center gap-1.5">
          <button 
            onClick={() => setIsPaused(!isPaused)}
            className={`p-2 rounded-lg transition-all ${isPaused ? 'bg-[var(--accent)] text-black' : 'hover:bg-white/5 text-white/40'}`}
            title={isPaused ? "Resume Stream" : "Pause Stream"}
          >
            {isPaused ? <Play size={14} fill="currentColor" /> : <Pause size={14} fill="currentColor" />}
          </button>
          <button 
            onClick={download}
            className="p-2 rounded-lg hover:bg-white/5 text-white/40 hover:text-white transition-all"
            title="Download Buffer"
          >
            <Download size={14} />
          </button>
          <button 
            onClick={clear}
            className="p-2 rounded-lg hover:bg-red-500/10 text-white/20 hover:text-red-400 transition-all"
            title="Clear Buffer"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </header>

      {/* Log Feed */}
      <div 
        ref={scrollRef}
        onScroll={(e) => {
          const target = e.currentTarget
          const isAtBottom = Math.abs(target.scrollHeight - target.clientHeight - target.scrollTop) < 50
          setAutoScroll(isAtBottom)
        }}
        className="flex-1 overflow-y-auto p-4 space-y-1 font-mono text-[11px] custom-scrollbar selection:bg-[var(--accent)] selection:text-black"
      >
        {filteredLogs.map((log, i) => (
          <div key={i} className="flex gap-4 group hover:bg-white/[0.02] px-2 py-0.5 rounded transition-all">
            <span className="text-white/20 shrink-0">{log.timestamp.split('T')[1].split('.')[0]}</span>
            <span className={`shrink-0 w-12 font-bold ${
              log.level === 'ERROR' ? 'text-red-400' : 
              log.level === 'WARNING' ? 'text-yellow-400' :
              'text-[var(--accent)]/50'
            }`}>{log.level}</span>
            <span className="text-white/30 shrink-0 min-w-[100px] border-r border-white/5 mr-2">[{log.logger}]</span>
            <span className="text-white/80 break-all">{log.message}</span>
          </div>
        ))}
        {filteredLogs.length === 0 && (
           <div className="h-full flex flex-col items-center justify-center opacity-10">
              <Terminal size={32} className="mb-4" />
              <p className="uppercase tracking-widest text-xs">Waiting for telemetry heartbeat...</p>
           </div>
        )}
      </div>

      {/* Status Bar */}
      <footer className="px-4 py-1.5 bg-black/60 border-t border-white/5 flex items-center justify-between">
         <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full ${isPaused ? 'bg-yellow-400' : 'bg-[var(--success)] animate-pulse'}`} />
            <span className="text-[9px] font-bold text-white/20 uppercase tracking-tighter">
              {isPaused ? 'STREAM PAUSED' : 'LIVE CONNECTION ACTIVE'}
            </span>
         </div>
         <span className="text-[9px] font-bold text-white/10 uppercase tracking-tighter">
           {filteredLogs.length} EVENTS IN BUFFER
         </span>
      </footer>
    </div>
  )
}
