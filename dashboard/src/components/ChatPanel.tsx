import { useState, useRef, useEffect } from 'react'
import { Send, Loader2, User, Bot, Sparkles, Trash2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '../api'
import type { ChatMessage } from '../types'

// Persist the dashboard chat session across page navigation AND browser reloads
// so users don't lose context when they flip to Settings and back. The session
// id is stable per-browser; the message history is reloaded from the backend
// on mount (single source of truth — we never trust a stale local cache).
const SESSION_STORAGE_KEY = 'autonoma.chat.sessionId'

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [hydrating, setHydrating] = useState(true)
  const [sessionId, setSessionId] = useState<string | undefined>(() => {
    try {
      return localStorage.getItem(SESSION_STORAGE_KEY) || undefined
    } catch {
      return undefined
    }
  })
  const bottomRef = useRef<HTMLDivElement>(null)

  // On mount: if we remember a session from a previous visit, pull its history
  // from the backend and replay it into the UI. Failure modes handled:
  //   - 404 (session was deleted server-side) → clear local id, start fresh
  //   - any other error → keep the id, show empty list (user can keep chatting)
  useEffect(() => {
    let cancelled = false
    const rehydrate = async () => {
      if (!sessionId) {
        setHydrating(false)
        return
      }
      try {
        const detail = await api.getSessionDetail(sessionId)
        if (cancelled) return
        const restored: ChatMessage[] = detail.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            timestamp: m.timestamp,
          }))
        setMessages(restored)
      } catch (e: any) {
        // Session gone from the server? Drop the stale id so the next send
        // creates a new one instead of aiming at a dead handle.
        if (String(e?.message || '').includes('404')) {
          try { localStorage.removeItem(SESSION_STORAGE_KEY) } catch { /* noop */ }
          setSessionId(undefined)
        }
      } finally {
        if (!cancelled) setHydrating(false)
      }
    }
    rehydrate()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // run once on mount; sessionId changes are handled explicitly elsewhere

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Mirror sessionId to localStorage so a reload picks up where we left off.
  useEffect(() => {
    try {
      if (sessionId) localStorage.setItem(SESSION_STORAGE_KEY, sessionId)
      else localStorage.removeItem(SESSION_STORAGE_KEY)
    } catch { /* storage disabled — fall back to in-memory only */ }
  }, [sessionId])

  const clearChat = () => {
    // "New conversation" — wipe the local view and forget the session id.
    // The backend's JSONL stays on disk (users can find it via Sessions page
    // if they need it); we just stop following it from this panel.
    setMessages([])
    setSessionId(undefined)
  }

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
        content: 'Failed to connect to the neural gateway. Is Autonoma active?',
        timestamp: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar — shows hydration status + a "new conversation" escape hatch
          so users can reset the stored session on purpose. Hidden when empty
          so the first-run welcome stays clean. */}
      {(messages.length > 0 || hydrating) && (
        <div className="flex items-center justify-between px-6 pt-4 pb-2 shrink-0">
          <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
            {hydrating ? 'Restoring session…' : sessionId ? 'Session active' : 'New conversation'}
          </span>
          {messages.length > 0 && !hydrating && (
            <button
              onClick={clearChat}
              className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--error)] transition-colors cursor-pointer"
              title="Start a new conversation (history stays on disk)"
            >
              <Trash2 size={10} />
              New chat
            </button>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-hide min-w-0">
        <AnimatePresence initial={false}>
          {messages.length === 0 && !hydrating && (
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col items-center justify-center h-full text-center space-y-4"
            >
              <div className="w-16 h-16 rounded-3xl bg-[var(--accent-dim)] border border-[var(--accent)]/20 flex items-center justify-center glow-sm">
                <Sparkles className="text-[var(--accent)]" size={32} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white tracking-tight">Direct Neural Link</h3>
                <p className="text-sm text-[var(--text-muted)] mt-1 max-w-[200px]">
                  Send a transmission to initiate the handshake.
                </p>
              </div>
            </motion.div>
          )}
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className={`flex items-start gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border ${
                msg.role === 'user' 
                  ? 'bg-white/5 border-white/10' 
                  : 'bg-[var(--accent-dim)] border-[var(--accent)]/20'
              }`}>
                {msg.role === 'user' ? <User size={14} className="text-white/60" /> : <Bot size={14} className="text-[var(--accent)]" />}
              </div>
              <div
                className={`max-w-[80%] min-w-0 px-5 py-3.5 rounded-2xl text-[14px] leading-relaxed relative break-words ${
                  msg.role === 'user'
                    ? 'bg-white/[0.04] text-white border border-white/10 rounded-tr-none'
                    : 'bg-[var(--bg-card)] border border-[var(--border)] text-white/90 rounded-tl-none ring-1 ring-white/5'
                }`}
              >
                <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)] mt-2 block opacity-40">
                  {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            </motion.div>
          ))}
          {loading && (
            <motion.div 
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex justify-start gap-4"
            >
              <div className="w-8 h-8 rounded-lg bg-[var(--accent-dim)] border border-[var(--accent)]/20 flex items-center justify-center">
                <Bot size={14} className="text-[var(--accent)]" />
              </div>
              <div className="px-5 py-4 rounded-2xl rounded-tl-none bg-[var(--bg-card)] border border-[var(--border)] ring-1 ring-white/5 flex items-center gap-2">
                <motion.div
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                  className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]"
                />
                <motion.div
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5, delay: 0.2 }}
                  className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]"
                />
                <motion.div
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5, delay: 0.4 }}
                  className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-6 pt-2 bg-gradient-to-t from-[var(--bg)] via-[var(--bg)] to-transparent">
        <div className="glass px-2 py-2 rounded-2xl flex gap-2 items-center focus-within:border-[var(--accent)]/40 transition-premium shadow-2xl">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Transmit command to Autonoma..."
            className="flex-1 bg-transparent border-none rounded-xl px-4 py-3 text-sm text-white placeholder:text-white/20 outline-none"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="w-10 h-10 flex items-center justify-center rounded-xl bg-[var(--accent)] text-black hover:scale-105 active:scale-95 disabled:opacity-20 disabled:grayscale transition-all cursor-pointer shadow-lg shadow-[var(--accent-glow)]"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  )
}
