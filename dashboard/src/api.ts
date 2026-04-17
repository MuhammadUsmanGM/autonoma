import type { Stats, Memory, Session, SessionDetail, TraceItem, TraceStats, TaskItem, TaskStats, AppConfig } from './types'

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

  getTraces: (limit = 50) => request<TraceItem[]>(`/traces?limit=${limit}`),

  getTrace: (id: string) => request<TraceItem>(`/traces/${id}`),

  getTraceStats: () => request<TraceStats>('/traces/stats'),

  getTasks: () => request<TaskItem[]>('/tasks'),

  getTaskStats: () => request<TaskStats>('/tasks/stats'),

  cancelTask: (id: string) =>
    request<{ cancelled: string }>(`/tasks/${id}`, { method: 'DELETE' }),

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

  getConfig: () => request<AppConfig>('/config'),

  updateConfig: (data: Record<string, unknown>) =>
    request<{ status: string; updated: string[]; restart_required: boolean }>('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
}
