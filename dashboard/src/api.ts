import type { Stats, Memory, Session, SessionDetail } from './types'

const BASE = '/api'

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  getStats: () => request<Stats>('/stats'),

  getMemories: () => request<Memory[]>('/memories'),

  searchMemories: (q: string) =>
    request<Memory[]>(`/memories/search?q=${encodeURIComponent(q)}`),

  deleteMemory: (id: number) =>
    request<{ deleted: number }>(`/memories/${id}`, { method: 'DELETE' }),

  getSessions: () => request<Session[]>('/sessions'),

  getSessionDetail: (id: string) =>
    request<SessionDetail>(`/sessions/${id}`),

  sendChat: async (message: string, sessionId?: string) => {
    const res = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        channel_id: 'dashboard',
        user_id: 'dashboard_user',
        session_id: sessionId,
      }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json() as Promise<{ response: string; session_id: string }>
  },
}
