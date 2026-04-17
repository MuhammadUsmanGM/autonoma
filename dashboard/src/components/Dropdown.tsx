import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown } from 'lucide-react'

interface Option {
  value: string
  label: string
}

interface Props {
  value: string
  options: (string | Option)[]
  onChange: (value: string) => void
  label?: string
}

export default function Dropdown({ value, options, onChange, label }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const normalizedOptions = options.map(opt => 
    typeof opt === 'string' ? { value: opt, label: opt.toUpperCase() } : opt
  )

  const current = normalizedOptions.find(o => o.value === value) || normalizedOptions[0]

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div className="relative" ref={containerRef}>
      {label && <label className="block text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-2">{label}</label>}
      
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between bg-[var(--bg-faint)] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text)] hover:border-[var(--accent)]/40 transition-all cursor-pointer group"
      >
        <span className="font-medium">{current.label}</span>
        <ChevronDown 
          size={14} 
          className={`text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-all ${isOpen ? 'rotate-180' : ''}`} 
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            className="absolute z-[100] mt-2 w-full bg-[var(--bg-card)]/95 border border-[var(--border)] rounded-xl shadow-2xl overflow-hidden backdrop-blur-xl"
          >
            <div className="p-1.5 space-y-1">
              {normalizedOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => {
                    onChange(opt.value)
                    setIsOpen(false)
                  }}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                    value === opt.value 
                      ? 'bg-[var(--accent)] text-black' 
                      : 'text-[var(--text-muted)] hover:bg-white/5 hover:text-white'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
