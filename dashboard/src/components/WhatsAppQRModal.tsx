import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { QRCodeSVG } from 'qrcode.react'
import { X, RefreshCw, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import { api } from '../api'

interface Props {
  open: boolean
  onClose: () => void
}

/** WhatsApp QR modal.
 *
 * Polls /api/channels/whatsapp/qr on a 3s cadence while open. The bridge
 * rotates its QR every ~20s, so by polling we stay ahead of expiry without
 * hammering the sidecar. Three visible states:
 *   - loading: first fetch in flight, show spinner
 *   - qr: render the payload (a literal whatsapp:// string) as an SVG QR
 *   - ready: bridge reports the session is already authenticated
 *   - error: bridge unreachable / returned an error — explain and offer retry
 */
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
          // No need to keep polling once we're logged in.
          if (pollingRef.current) {
            window.clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        } else {
          // Bridge is up but hasn't emitted a QR yet (puppeteer still booting).
          // Keep polling — a 404 here is normal during cold start.
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

    // Fire immediately, then every 3s. We clear on unmount/close below.
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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="w-full max-w-md bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden glass"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-4 border-b border-[var(--border)] flex justify-between items-center">
          <h3 className="font-bold text-[var(--text)] uppercase tracking-wider text-sm">
            Scan with WhatsApp
          </h3>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text)] p-1 rounded-lg hover:bg-white/5 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-8 flex flex-col items-center justify-center min-h-[360px]">
          {status === 'loading' && (
            <div className="flex flex-col items-center gap-4 text-center">
              <Loader2 size={32} className="text-[var(--accent)] animate-spin" />
              <p className="text-sm font-medium text-[var(--text)]">Fetching QR from bridge…</p>
              {message && (
                <p className="text-xs text-[var(--text-muted)] max-w-[280px]">{message}</p>
              )}
            </div>
          )}

          {status === 'qr' && qr && (
            <div className="flex flex-col items-center gap-5">
              {/* White background is mandatory — scanners choke on dark themes. */}
              <div className="p-4 rounded-xl bg-white">
                <QRCodeSVG value={qr} size={240} level="M" />
              </div>
              <div className="text-center space-y-2">
                <p className="text-xs text-[var(--text-muted)]">
                  WhatsApp → <span className="text-[var(--text)]">Settings</span> →{' '}
                  <span className="text-[var(--text)]">Linked devices</span> →{' '}
                  <span className="text-[var(--text)]">Link a device</span>
                </p>
                {ageSeconds !== null && (
                  <p className="text-[10px] text-[var(--text-muted)]">
                    QR age: {ageSeconds}s · refreshes automatically
                  </p>
                )}
              </div>
            </div>
          )}

          {status === 'ready' && (
            <div className="flex flex-col items-center gap-3 text-center">
              <CheckCircle2 size={32} className="text-[var(--success)]" />
              <p className="text-sm font-bold text-[var(--success)]">Session Active</p>
              <p className="text-xs text-[var(--text-muted)] max-w-[280px]">{message}</p>
              <button
                onClick={onClose}
                className="mt-2 px-4 py-2 rounded-xl text-xs font-bold bg-white/5 border border-white/10 text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-white/10 transition-all cursor-pointer"
              >
                Close
              </button>
            </div>
          )}

          {status === 'error' && (
            <div className="flex flex-col items-center gap-3 text-center">
              <AlertTriangle size={32} className="text-[var(--error)]" />
              <p className="text-sm font-bold text-[var(--error)]">Bridge Unreachable</p>
              <p className="text-xs text-[var(--text-muted)] max-w-[280px] font-mono">
                {message}
              </p>
              <p className="text-[11px] text-[var(--text-muted)] max-w-[300px]">
                Start the sidecar: <code className="font-mono">cd whatsapp-bridge && npm start</code>
              </p>
              <button
                onClick={() => {
                  setStatus('loading')
                  setMessage('')
                }}
                className="mt-2 flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-[var(--accent)] text-black hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer"
              >
                <RefreshCw size={12} />
                Retry
              </button>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  )
}
