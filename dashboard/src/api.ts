import type { Stats, Memory, Session, SessionDetail, TraceItem, TraceStats, UsageStats, TaskItem, TaskStats, AppConfig, ChannelInfo, LogEntry, WebhookEntry, Alert, SkillManifest, ProxyHealth, ConnectorEntry } from './types'

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

  getStaleMemories: () => request<Memory[]>('/memories/stale'),

  reviewMemory: (id: number, action: 'review' | 'dismiss') =>
    request<{ reviewed?: string; dismissed?: string }>('/memories/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memory_id: id, action }),
    }),

  getSessions: () => request<Session[]>('/sessions'),

  getSessionDetail: (id: string) =>
    request<SessionDetail>(`/sessions/${id}`),

  getTraces: (limit = 50) => request<TraceItem[]>(`/traces?limit=${limit}`),

  getTrace: (id: string) => request<TraceItem>(`/traces/${id}`),

  getTraceStats: () => request<TraceStats>('/traces/stats'),

  getUsage: () => request<UsageStats>('/usage'),

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

  getSoul: () =>
    request<{ content: string; exists: boolean; size_bytes?: number; modified?: number }>('/soul'),

  updateSoul: (content: string) =>
    request<{ status: string; size_bytes: number }>('/soul', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),

  getSkills: () => request<Array<{ name: string; description: string; provider: string }>>('/skills/manifest'),

  restartAgent: () => request<{ status: string }>('/system/restart', { method: 'POST' }),

  getChannels: () => request<ChannelInfo[]>('/channels'),

  reconnectChannel: (name: string) => 
    request<{ status: string; channel: string }>(`/channels/${name}/reconnect`, { method: 'POST' }),

  toggleChannel: (name: string, enabled: boolean) =>
    request<{ status: string; restart_required: boolean }>(`/channels/${name}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),

  updateChannelCredentials: (name: string, data: Record<string, string>) =>
    request<{ status: string; applied_live?: boolean; restart_required: boolean }>(
      `/channels/${name}/credentials`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      },
    ),

  getLogs: (params: { level?: string; since?: string; q?: string }) => {
    const qs = new URLSearchParams()
    if (params.level) qs.append('level', params.level)
    if (params.since) qs.append('since', params.since)
    if (params.q) qs.append('q', params.q)
    return request<LogEntry[]>(`/logs?${qs.toString()}`)
  },

  getWebhooks: (channel?: string) => {
    return request<WebhookEntry[]>(channel ? `/webhooks?channel=${encodeURIComponent(channel)}` : '/webhooks')
  },

  replayWebhook: (id: string) => {
    return request<{ status: string }>(`/webhooks/${id}/replay`, { method: 'POST' })
  },

  getAlerts: () => request<Alert[]>('/alerts'),
  
  markAlertRead: (id?: string) => 
    request<{ status: string }>('/alerts/read', { 
      method: 'POST', 
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    }),

  getTask: (id: string) => request<TaskItem>(`/tasks/${id}`),

  createTask: (data: {
    name: string
    skill?: string
    args?: any
    prompt?: string
    priority?: number
    cron?: string | null
  }) =>
    request<{ status: string; id: string; cron?: string | null }>('/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  consolidateMemory: () => request<{ status: string }>('/memories/consolidate', { method: 'POST' }),

  exportMemory: () => request<Memory[]>('/memories/export'),

  deleteSession: (id: string) => request<{ deleted: string }>(`/sessions/${id}`, { method: 'DELETE' }),

  getSkillManifest: () => request<SkillManifest[]>('/skills/manifest'),

  getWhatsAppQR: () =>
    request<{ qr: string | null; status: string; age_seconds?: number; message?: string }>(
      '/channels/whatsapp/qr'
    ),

  getProxyHealth: () => request<ProxyHealth[]>('/proxy/health'),

  recheckProxyHealth: (channel?: string) =>
    request<ProxyHealth[]>('/proxy/health/recheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(channel ? { channel } : {}),
    }),

  getConnectors: () => request<ConnectorEntry[]>('/connectors'),

  connectConnector: (name: string) =>
    request<{ auth_url: string }>(`/connectors/${name}/connect`, { method: 'POST' }),

  disconnectConnector: (name: string) =>
    request<{ status: ConnectorEntry['status'] }>(`/connectors/${name}/disconnect`, {
      method: 'POST',
    }),
}
