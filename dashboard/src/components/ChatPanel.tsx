import { useState, useRef, useEffect } from 'react'
import { Send, Loader2 } from 'lucide-react'
import { api } from '../api'
import type { ChatMessage } from '../types'

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string>()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.sendChat(text, sessionId)
      if (res.session_id) setSessionId(res.session_id)
      const botMsg: ChatMessage = {
        role: 'assistant',
        content: res.response,
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, botMsg])
    } catch {
      const errMsg: ChatMessage = {
        role: 'assistant',
        content: 'Failed to get response. Is Autonoma running?',
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-[var(--text-muted)] text-sm">
              Send a message to start chatting with Autonoma
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[70%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-[var(--accent)] text-black rounded-br-md'
                  : 'bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text)] rounded-bl-md'
              }`}
            >
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="px-4 py-2.5 rounded-2xl rounded-bl-md bg-[var(--bg-card)] border border-[var(--border)]">
              <Loader2 size={16} className="animate-spin text-[var(--accent)]" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[var(--border)] p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Type a message..."
            className="flex-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)] transition-colors"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-[var(--accent)] text-black font-medium text-sm hover:brightness-110 disabled:opacity-40 transition-all cursor-pointer"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  )
}
