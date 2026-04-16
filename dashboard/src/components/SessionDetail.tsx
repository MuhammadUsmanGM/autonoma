import type { SessionMessage } from '../types'

interface Props {
  sessionId: string
  messages?: SessionMessage[]
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function SessionDetail({ sessionId, messages = [] }: Props) {
  return (
    <div>
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <p className="text-sm font-medium">Session</p>
        <p className="text-xs text-[var(--text-muted)] font-mono mt-0.5">{sessionId}</p>
      </div>

      <div className="p-4 space-y-3 max-h-[calc(100vh-14rem)] overflow-y-auto">
        {messages.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-8">
            Empty session.
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-[var(--accent)] text-black rounded-br-md'
                  : 'bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-bl-md'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
              <p className={`text-[10px] mt-1 ${
                msg.role === 'user' ? 'text-black/50' : 'text-[var(--text-muted)]'
              }`}>
                {formatTime(msg.timestamp)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
