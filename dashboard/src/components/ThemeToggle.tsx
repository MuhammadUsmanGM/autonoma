import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from './ThemeProvider'
import { motion, AnimatePresence } from 'framer-motion'

export default function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  const modes: { mode: 'light' | 'dark' | 'system'; icon: typeof Sun }[] = [
    { mode: 'light', icon: Sun },
    { mode: 'dark', icon: Moon },
    { mode: 'system', icon: Monitor },
  ]

  return (
    <div className="flex p-1 bg-white/[0.03] dark:bg-black/20 border border-[var(--border)] rounded-xl relative group">
      {modes.map(({ mode, icon: Icon }) => {
        const active = theme === mode
        return (
          <button
            key={mode}
            onClick={() => setTheme(mode)}
            className={`relative z-10 p-2 rounded-lg transition-all cursor-pointer ${
              active ? 'text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
            title={`${mode.charAt(0).toUpperCase() + mode.slice(1)} Mode`}
          >
            {active && (
              <motion.div
                layoutId="active-theme"
                className="absolute inset-0 bg-[var(--accent-dim)] rounded-lg border border-[var(--accent)]/10"
                transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
              />
            )}
            <Icon size={14} className="relative z-10" />
          </button>
        )
      })}
    </div>
  )
}
