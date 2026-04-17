import { useEffect, useState, useRef } from 'react'
import { Save, RefreshCw, Sparkles, FileText, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { api } from '../api'
import Skeleton from '../components/Skeleton'

export default function SoulEditor() {
  const [content, setContent] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [exists, setExists] = useState(true)
  const [sizeBytes, setSizeBytes] = useState(0)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const dirty = content !== original

  useEffect(() => {
    loadSoul()
  }, [])

  const loadSoul = async () => {
    setLoading(true)
    try {
      const data = await api.getSoul()
      setContent(data.content)
      setOriginal(data.content)
      setExists(data.exists)
      setSizeBytes(data.size_bytes || 0)
    } catch (e: any) {
      toast.error(`Failed to load SOUL.md: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const result = await api.updateSoul(content)
      setOriginal(content)
      setSizeBytes(result.size_bytes)
      setExists(true)
      toast.success('SOUL.md saved. Changes take effect on next message.', { duration: 4000 })
    } catch (e: any) {
      toast.error(`Failed to save: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  // Keyboard shortcut: Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        if (dirty && !saving) handleSave()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [dirty, saving, content])

  const lineCount = content.split('\n').length
  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0
  const charCount = content.length

  if (loading) {
    return (
      <div className="p-10 space-y-8">
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-[calc(100vh-16rem)] reflective rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="p-10 space-y-6 h-full flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-2xl bg-[var(--accent-dim)] border border-[var(--accent)]/10">
            <Sparkles size={24} className="text-[var(--accent)]" />
          </div>
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-white mb-1">SOUL Editor</h2>
            <p className="text-sm text-[var(--text-muted)]">
              Define your agent's identity, behavior, and cognitive boundaries
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadSoul}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors cursor-pointer"
          >
            <RefreshCw size={14} />
            Reload
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-bold bg-[var(--accent)] text-black hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30 disabled:scale-100 transition-all cursor-pointer shadow-lg shadow-[var(--accent-glow)]"
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
            Save SOUL
          </button>
        </div>
      </header>

      {/* Unsaved changes banner */}
      {dirty && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between px-5 py-3 rounded-xl bg-[var(--accent-dim)] border border-[var(--accent)]/20 shrink-0"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle size={16} className="text-[var(--accent)]" />
            <span className="text-sm font-medium text-[var(--accent)]">Unsaved changes</span>
          </div>
          <span className="text-xs text-[var(--accent)]/60">Ctrl+S to save</span>
        </motion.div>
      )}

      {/* Editor */}
      <div className="flex-1 min-h-0 rounded-2xl reflective overflow-hidden flex flex-col">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--border)] bg-white/[0.01] shrink-0">
          <div className="flex items-center gap-3">
            <FileText size={14} className="text-[var(--text-muted)]" />
            <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
              workspace / SOUL.md
            </span>
            {!exists && (
              <span className="text-[10px] px-2 py-0.5 rounded-lg bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 font-bold uppercase">
                New File
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-[10px] text-white/30 font-mono">
            <span>{lineCount} lines</span>
            <span>{wordCount} words</span>
            <span>{charCount > 1024 ? `${(charCount / 1024).toFixed(1)}KB` : `${charCount}B`}</span>
          </div>
        </div>

        {/* Textarea */}
        <div className="flex-1 relative min-h-0">
          <textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            spellCheck={false}
            className="absolute inset-0 w-full h-full resize-none bg-transparent text-sm text-[var(--text)] font-mono leading-relaxed p-6 outline-none placeholder:text-white/10 overflow-auto"
            placeholder="# AUTONOMA SYSTEM PROMPT&#10;&#10;Define your agent's identity here..."
            style={{ tabSize: 2 }}
          />
        </div>

        {/* Status bar */}
        <div className="flex items-center justify-between px-6 py-2 border-t border-[var(--border)] bg-white/[0.01] shrink-0">
          <div className="flex items-center gap-2">
            {dirty ? (
              <>
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                <span className="text-[10px] text-[var(--accent)] font-medium">Modified</span>
              </>
            ) : (
              <>
                <CheckCircle2 size={10} className="text-[var(--success)]" />
                <span className="text-[10px] text-[var(--success)] font-medium">Saved</span>
              </>
            )}
          </div>
          <span className="text-[10px] text-white/20 font-mono">
            {sizeBytes > 0 && `${(sizeBytes / 1024).toFixed(1)}KB on disk`}
          </span>
        </div>
      </div>
    </div>
  )
}
