import { useState, useEffect } from 'react'
import { Toaster } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar'
import Overview from './pages/Overview'
import Chat from './pages/Chat'
import Memory from './pages/Memory'
import Sessions from './pages/Sessions'
import Traces from './pages/Traces'
import Settings from './pages/Settings'
import Tasks from './pages/Tasks'
import SoulEditor from './pages/SoulEditor'
import type { Page } from './types'

function App() {
  const [page, setPage] = useState<Page>('overview')
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 })

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setMousePos({ x: e.clientX, y: e.clientY })
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  return (
    <div className="flex h-screen bg-[var(--bg)] text-[var(--text)] overflow-hidden font-sans relative">
      {/* Background Mesh Gradients */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <motion.div 
          animate={{ 
            x: [0, 100, 0], 
            y: [0, 50, 0],
            scale: [1, 1.2, 1] 
          }}
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
          className="absolute -top-[10%] -left-[10%] w-[40%] h-[40%] rounded-full bg-[var(--accent)] opacity-[0.07] blur-[120px]" 
        />
        <motion.div 
          animate={{ 
            x: [0, -80, 0], 
            y: [0, 120, 0],
            scale: [1, 1.1, 1] 
          }}
          transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
          className="absolute top-[20%] -right-[10%] w-[35%] h-[35%] rounded-full bg-purple-500 opacity-[0.05] blur-[120px]" 
        />
        <motion.div 
          animate={{ 
            x: [0, 50, 0], 
            y: [0, -100, 0] 
          }}
          transition={{ duration: 18, repeat: Infinity, ease: "linear" }}
          className="absolute -bottom-[10%] left-[20%] w-[30%] h-[30%] rounded-full bg-blue-500 opacity-[0.04] blur-[120px]" 
        />
      </div>

      {/* Cursor Spotlight Aura */}
      <div 
        className="fixed inset-0 pointer-events-none z-10 transition-opacity duration-500"
        style={{
          background: `radial-gradient(600px circle at ${mousePos.x}px ${mousePos.y}px, var(--accent-dim), transparent 80%)`
        }}
      />

      {/* Background Watermark */}
      <div className="fixed -bottom-24 -right-24 w-[600px] h-[600px] opacity-[0.03] pointer-events-none select-none z-0">
        <img 
          src="/favicon.webp" 
          alt="" 
          className="w-full h-full object-contain grayscale blur-[2px]" 
        />
      </div>

      <Sidebar current={page} onChange={setPage} />
      
      <main className="flex-1 relative overflow-y-auto overflow-x-hidden z-20">
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
            {page === 'settings' && <Settings />}
            {page === 'tasks' && <Tasks />}
            {page === 'soul' && <SoulEditor />}
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
