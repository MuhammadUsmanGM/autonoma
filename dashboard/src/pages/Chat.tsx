import ChatPanel from '../components/ChatPanel'

export default function Chat() {
  return (
    <div className="p-8">
      <h2 className="text-xl font-semibold mb-4">Live Chat</h2>
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        <ChatPanel />
      </div>
    </div>
  )
}
