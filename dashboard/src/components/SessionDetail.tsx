import { Download, Trash2 } from 'lucide-react'
import type { SessionMessage } from '../types'

interface Props {
  sessionId: string
  messages?: SessionMessage[]
  onExport: () => void
  onDelete: () => void
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })
}
export default function SessionDetail({ sessionId, messages = [], onExport, onDelete }: Props) {
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-6 py-4 border-b border-[var(--border)] shrink-0 bg-white/[0.01] flex items-center justify-between">
        <div>
          <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Active Resonance Link</span>
          <p className="text-xs text-white font-mono mt-1 opacity-40 truncate">{sessionId}</p>
        </div>
        <div className="flex items-center gap-2">
           <button 
             onClick={onExport}
             className="p-2 mr-1 rounded-lg hover:bg-white/5 text-[var(--text-muted)] hover:text-[var(--accent)] transition-all cursor-pointer"
             title="Export Thread"
           >
             <Download size={16} />
           </button>
           <button 
             onClick={onDelete}
             className="p-2 rounded-lg hover:bg-red-500/10 text-white/20 hover:text-red-400 transition-all cursor-pointer"
             title="Delete Session"
           >
             <Trash2 size={16} />
           </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-hide">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center py-20 opacity-20">
            <p className="text-xs font-bold uppercase tracking-widest">No data packet detected</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] px-5 py-3.5 rounded-2xl text-[13px] leading-relaxed break-words shadow-lg ${
                msg.role === 'user'
                  ? 'bg-[var(--accent)] text-black rounded-br-none font-medium'
                  : 'glass border border-white/5 text-white/90 rounded-bl-none'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
              <div className={`flex items-center gap-2 mt-2 text-[9px] font-bold uppercase tracking-tighter ${
                msg.role === 'user' ? 'text-black/40' : 'text-white/20'
              }`}>
                <span>{msg.role === 'user' ? 'Human' : 'Agent'}</span>
                <span>•</span>
                <span>{formatTime(msg.timestamp)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
