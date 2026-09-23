import { useState } from 'react'
import { Toaster } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu } from 'lucide-react'
import Sidebar from './components/Sidebar'
import Overview from './pages/Overview'
import Chat from './pages/Chat'
import Memory from './pages/Memory'
import Sessions from './pages/Sessions'
import Traces from './pages/Traces'
import Settings from './pages/Settings'
import Tasks from './pages/Tasks'
import SoulEditor from './pages/SoulEditor'
import Channels from './pages/Channels'
import Connectors from './pages/Connectors'
import Contacts from './pages/Contacts'
import Logs from './pages/Logs'
import Webhooks from './pages/Webhooks'
import { NotificationsProvider } from './contexts/NotificationsContext'
import AlertsPanel from './components/AlertsPanel'
import type { Page } from './types'

function App() {
  const [page, setPage] = useState<Page>('overview')
  const [isAlertsOpen, setIsAlertsOpen] = useState(false)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  return (
    <NotificationsProvider>
      <div className="flex h-screen bg-[var(--bg)] text-[var(--text)] overflow-hidden font-sans">
        <Sidebar
          current={page}
          onChange={(nextPage) => { setPage(nextPage); setIsSidebarOpen(false) }}
          onToggleAlerts={() => setIsAlertsOpen(true)}
          mobileOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
        />
        
        <main className="flex-1 relative overflow-y-auto overflow-x-hidden z-20">
          <div className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 py-3 bg-[var(--bg)]/95 border-b border-[var(--border)]">
            <button
              type="button"
              aria-label="Open navigation"
              onClick={() => setIsSidebarOpen(true)}
              className="min-h-11 min-w-11 inline-flex items-center justify-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg-faint)]"
            >
              <Menu size={20} />
            </button>
            <span className="text-sm font-semibold">{page.charAt(0).toUpperCase() + page.slice(1)}</span>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={page}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.16 }}
              className="h-full flex flex-col"
            >
              {page === 'overview' && <Overview />}
              {page === 'chat' && <Chat />}
              {page === 'memory' && <Memory />}
              {page === 'sessions' && <Sessions />}
              {page === 'traces' && <Traces />}
              {page === 'settings' && <Settings />}
              {page === 'tasks' && <Tasks />}
              {page === 'webhooks' && <Webhooks />}
              {page === 'soul' && <SoulEditor />}
              {page === 'channels' && <Channels />}
              {page === 'connectors' && <Connectors />}
              {page === 'contacts' && <Contacts />}
              {page === 'logs' && <Logs />}
            </motion.div>
          </AnimatePresence>
        </main>

        <AlertsPanel isOpen={isAlertsOpen} onClose={() => setIsAlertsOpen(false)} />

        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            style: {
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              borderRadius: '12px',
              fontSize: '13px',
            },
          }}
        />
      </div>
    </NotificationsProvider>
  )
}

export default App
