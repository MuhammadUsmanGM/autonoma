import { Activity, Sparkles } from 'lucide-react'
import ChatPanel from '../components/ChatPanel'

export default function Chat() {
  return (
    <div className="p-10 space-y-10 flex flex-col h-full">
      <header className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Neural Interface</h2>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-[var(--accent)] font-bold uppercase tracking-widest bg-[var(--accent-dim)] px-2 py-0.5 rounded border border-[var(--accent)]/10">
              <Sparkles size={12} />
              Direct Link
            </span>
            <span className="text-xs text-[var(--text-muted)] font-medium">Encrypted P2P Session</span>
          </div>
        </div>
      </header>

      <div className="flex-1 min-h-0 rounded-3xl reflective overflow-hidden shadow-2xl relative border border-white/5">
        <ChatPanel />
      </div>
    </div>
  )
}
