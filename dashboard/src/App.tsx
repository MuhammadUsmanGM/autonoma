import { useState } from 'react'
import { Toaster } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar'
import Overview from './pages/Overview'
import Chat from './pages/Chat'
import Memory from './pages/Memory'
import Sessions from './pages/Sessions'
import Traces from './pages/Traces'
import type { Page } from './types'

function App() {
  const [page, setPage] = useState<Page>('overview')

  return (
    <div className="flex h-screen bg-[var(--bg)] text-[var(--text)] overflow-hidden font-sans">
      <Sidebar current={page} onChange={setPage} />
      
      <main className="flex-1 relative overflow-y-auto overflow-x-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={page}
            initial={{ opacity: 0, y: 10, filter: 'blur(8px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -10, filter: 'blur(8px)' }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="min-h-full"
          >
            {page === 'overview' && <Overview />}
            {page === 'chat' && <Chat />}
            {page === 'memory' && <Memory />}
            {page === 'sessions' && <Sessions />}
            {page === 'traces' && <Traces />}
          </motion.div>
        </AnimatePresence>
      </main>

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
  )
}

export default App
