import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { QRCodeSVG } from 'qrcode.react'
import { X, RefreshCw, AlertTriangle, CheckCircle2, Loader2, Smartphone, Settings, Share2, Scan } from 'lucide-react'
import { api } from '../api'

interface Props {
  open: boolean
  onClose: () => void
}

export default function WhatsAppQRModal({ open, onClose }: Props) {
  const [qr, setQr] = useState<string | null>(null)
  const [status, setStatus] = useState<'loading' | 'qr' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState<string>('')
  const [ageSeconds, setAgeSeconds] = useState<number | null>(null)
  const pollingRef = useRef<number | null>(null)

  useEffect(() => {
    if (!open) return

    let cancelled = false

    const poll = async () => {
      try {
        const data = await api.getWhatsAppQR()
        if (cancelled) return
        if (data.qr) {
          setQr(data.qr)
          setAgeSeconds(data.age_seconds ?? null)
          setStatus('qr')
          setMessage('')
        } else if (data.status === 'ready') {
          setStatus('ready')
          setMessage(data.message || 'Session already authenticated.')
          if (pollingRef.current) {
            window.clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        } else {
          setStatus('loading')
          setMessage(data.message || 'Waiting for bridge to emit a QR…')
        }
      } catch (e: any) {
        if (cancelled) return
        setStatus('error')
        setMessage(
          e?.message ||
            'Could not reach the WhatsApp bridge. Is whatsapp-bridge running?'
        )
      }
    }

    poll()
    pollingRef.current = window.setInterval(poll, 3000)

    return () => {
      cancelled = true
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-md"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 10 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        className="w-full max-w-md bg-[var(--bg-card)] border border-[var(--border-bright)] rounded-[2rem] shadow-[var(--shadow-premium)] overflow-hidden glass relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Accent Bar */}
        <div className="h-1.5 w-full bg-gradient-to-r from-transparent via-[var(--accent)] to-transparent opacity-50" />

        <div className="p-6 border-b border-[var(--border-faint)] flex justify-between items-center bg-white/5">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[var(--accent-dim)] border border-[var(--accent-glow)] flex items-center justify-center">
              <Smartphone size={18} className="text-[var(--accent)]" />
            </div>
            <div>
              <h3 className="font-bold text-[var(--text)] text-sm tracking-tight">
                WhatsApp Connection
              </h3>
              <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest font-semibold">
                Secure Link Gateway
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)] p-2 rounded-full hover:bg-white/10 transition-all duration-200"
          >
            <X size={20} />
          </button>
        </div>

        <div className="p-8 min-h-[440px] flex flex-col items-center justify-center relative overflow-hidden">
          {/* Subtle Background Glow */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-[var(--accent-glow)] blur-[100px] opacity-20 pointer-events-none rounded-full" />

          <AnimatePresence mode="wait">
            {status === 'loading' && (
              <motion.div
                key="loading"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="flex flex-col items-center gap-6 text-center"
              >
                <div className="relative">
                  <Loader2 size={48} className="text-[var(--accent)] animate-spin-slow opacity-30" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Loader2 size={32} className="text-[var(--accent)] animate-spin" />
                  </div>
                </div>
                <div>
                  <p className="text-base font-semibold text-[var(--text)]">Initializing Bridge</p>
                  <p className="text-sm text-[var(--text-muted)] mt-1">Connecting to WhatsApp instance...</p>
                </div>
                {message && (
                  <div className="px-4 py-2 rounded-xl bg-white/5 border border-white/5 text-xs text-[var(--text-muted)]">
                    {message}
                  </div>
                )}
              </motion.div>
            )}

            {status === 'qr' && qr && (
              <motion.div
                key="qr"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 1.05 }}
                className="flex flex-col items-center gap-8 w-full"
              >
                <div className="relative group">
                  {/* Subtle pulsing ring around QR */}
                  <div className="absolute -inset-4 bg-[var(--accent)] opacity-10 blur-xl rounded-full animate-pulse group-hover:opacity-20 transition-opacity" />
                  
                  <div className="relative p-6 rounded-3xl bg-white shadow-2xl transition-transform duration-500 group-hover:scale-[1.02]">
                    <QRCodeSVG value={qr} size={220} level="H" includeMargin={false} />
                    
                    {/* Corner accents for the QR holder */}
                    <div className="absolute top-2 left-2 w-4 h-4 border-t-2 border-l-2 border-black/10 rounded-tl-lg" />
                    <div className="absolute top-2 right-2 w-4 h-4 border-t-2 border-r-2 border-black/10 rounded-tr-lg" />
                    <div className="absolute bottom-2 left-2 w-4 h-4 border-b-2 border-l-2 border-black/10 rounded-bl-lg" />
                    <div className="absolute bottom-2 right-2 w-4 h-4 border-b-2 border-r-2 border-black/10 rounded-br-lg" />
                  </div>
                </div>

                <div className="w-full space-y-4">
                  <div className="flex justify-between items-center gap-2 max-w-[320px] mx-auto">
                    {[
                      { icon: Settings, label: 'Settings' },
                      { icon: Share2, label: 'Linked Devices' },
                      { icon: Scan, label: 'Link a Device' }
                    ].map((step, i) => (
                      <div key={i} className="flex items-center gap-2 flex-col flex-1">
                        <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-[var(--accent)]">
                          <step.icon size={14} />
                        </div>
                        <span className="text-[10px] text-[var(--text-muted)] text-center font-medium leading-tight">
                          {step.label}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="flex items-center justify-center gap-2 text-[11px] text-[var(--text-muted)] bg-white/5 py-2 px-4 rounded-full border border-white/5">
                    <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
                    Refresh: <span className="text-[var(--text)] font-mono">{ageSeconds ?? 0}s</span>
                    <span className="opacity-30">|</span>
                    <span>Self-refreshing active</span>
                  </div>
                </div>
              </motion.div>
            )}

            {status === 'ready' && (
              <motion.div
                key="ready"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center gap-6 text-center"
              >
                <div className="w-20 h-20 rounded-full bg-[var(--success)]/10 border border-[var(--success)]/20 flex items-center justify-center relative">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: 'spring', delay: 0.2 }}
                  >
                    <CheckCircle2 size={48} className="text-[var(--success)]" />
                  </motion.div>
                  <div className="absolute inset-0 rounded-full border-2 border-[var(--success)] animate-ping opacity-20" />
                </div>
                <div>
                  <h4 className="text-xl font-bold text-[var(--text)]">Authenticated</h4>
                  <p className="text-sm text-[var(--text-muted)] mt-2 max-w-[240px]">
                    {message || 'Your WhatsApp session is active and secure.'}
                  </p>
                </div>
                <button
                  onClick={onClose}
                  className="mt-4 px-8 py-3 rounded-2xl bg-[var(--success)] text-white font-bold text-sm shadow-lg shadow-[var(--success)]/20 hover:scale-105 active:scale-95 transition-all cursor-pointer"
                >
                  Continue to Workspace
                </button>
              </motion.div>
            )}

            {status === 'error' && (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col items-center gap-6 text-center"
              >
                <div className="w-16 h-16 rounded-3xl bg-[var(--error)]/10 border border-[var(--error)]/20 flex items-center justify-center">
                  <AlertTriangle size={32} className="text-[var(--error)]" />
                </div>
                <div>
                  <h4 className="text-lg font-bold text-[var(--error)]">Connection Refused</h4>
                  <p className="text-xs text-[var(--text-muted)] mt-2 max-w-[280px] font-medium leading-relaxed">
                    {message}
                  </p>
                </div>
                
                <div className="w-full text-left bg-black/40 border border-white/5 rounded-2xl p-4 overflow-hidden">
                  <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-wider mb-2">Instructions</p>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    Verify that the WhatsApp sidecar is active:
                    <code className="block mt-2 font-mono bg-white/5 p-2 rounded-lg border border-white/5 text-[var(--accent)]">
                      cd whatsapp-bridge && npm start
                    </code>
                  </p>
                </div>

                <button
                  onClick={() => {
                    setStatus('loading')
                    setMessage('')
                  }}
                  className="reflective flex items-center justify-center gap-2 w-full py-4 rounded-2xl text-sm font-black tracking-tight"
                >
                  <RefreshCw size={16} />
                  RETRY HANDSHAKE
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        
        {/* Footer info */}
        <div className="px-8 py-4 bg-white/5 text-center">
          <p className="text-[10px] text-[var(--text-faint)] font-medium">
            Powered by Autonoma Security • End-to-end Encrypted
          </p>
        </div>
      </motion.div>
    </div>
  )
}
