import { useState } from 'react'
import { Toaster } from 'sonner'
import Sidebar from './components/Sidebar'
import Overview from './pages/Overview'
import Chat from './pages/Chat'
import Memory from './pages/Memory'
import Sessions from './pages/Sessions'
import type { Page } from './types'

function App() {
  const [page, setPage] = useState<Page>('overview')

  return (
    <div className="flex min-h-screen bg-[var(--bg)]">
      <Sidebar current={page} onChange={setPage} />
      <main className="flex-1 overflow-y-auto">
        {page === 'overview' && <Overview />}
        {page === 'chat' && <Chat />}
        {page === 'memory' && <Memory />}
        {page === 'sessions' && <Sessions />}
      </main>
      <Toaster
        theme="dark"
        toastOptions={{
          style: {
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            color: 'var(--text)',
          },
        }}
      />
    </div>
  )
}

export default App
