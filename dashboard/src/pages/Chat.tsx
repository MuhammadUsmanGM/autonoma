import ChatPanel from '../components/ChatPanel'

export default function Chat() {
  return (
    <div className="p-10 space-y-10 flex flex-col h-full">
      <header className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-2xl font-semibold text-[var(--text)] mb-2">Chat</h2>
          <p className="text-sm text-[var(--text-muted)]">Send a message to your agent.</p>
        </div>
      </header>

      <div className="flex-1 min-h-0 rounded-3xl reflective overflow-hidden shadow-2xl relative border border-white/5">
        <ChatPanel />
      </div>
    </div>
  )
}
