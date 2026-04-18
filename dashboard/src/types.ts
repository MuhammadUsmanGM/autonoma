export interface Stats {
  uptime_seconds: number
  active_channels: string[]
  channel_count: number
  memory_active: number
  memory_archived: number
  session_count: number
}

export interface Memory {
  id: number
  content: string
  type: string
  source: string
  importance: number
  created_at: string
  accessed_at: string
  access_count: number
  active: boolean | number
}

export interface Session {
  id: string
  channel: string
  created: string
  modified: string
  size: number
}

export interface SessionMessage {
  role: string
  content: string
  channel: string
  user_id: string
  timestamp: string
}

export interface SessionDetail {
  session_id: string
  messages: SessionMessage[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface TraceSpan {
  stage: string
  data: Record<string, unknown>
  timestamp: string
}

export interface TraceItem {
  id: string
  session_id: string
  channel: string
  user_id: string
  started_at: string
  completed_at: string | null
  elapsed_seconds: number
  status: 'running' | 'completed' | 'error'
  spans: TraceSpan[]
  tool_calls: Record<string, unknown>[]
  error: string | null
}

export interface TraceStats {
  total: number
  completed: number
  errors: number
  running: number
  avg_elapsed_seconds: number
}

export interface TaskItem {
  id: string
  name: string
  priority: number
  skill: string
  args: Record<string, any>
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at: string | null
  completed_at: string | null
  result: any | null
  error: string | null
  retries: number
  max_retries: number
}

export interface TaskStats {
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  cancelled: number
}

export interface AppConfig {
  name: string
  llm: {
    provider: string
    model: string
    api_key_configured: boolean
  }
  gateway: {
    host: string
    port: number
    http_port: number
  }
  channels: {
    telegram: { enabled: boolean }
    discord: { enabled: boolean }
    whatsapp: { enabled: boolean }
    gmail: { enabled: boolean }
    rest: { enabled: boolean }
  }
  memory: {
    max_context_memories: number
    decay_interval: number
    importance_threshold: number
    consolidation_enabled: boolean
  }
  log_level: string
}

export interface ChannelInfo {
  id: string
  name: string
  enabled: boolean
  has_credentials: boolean
  status: 'starting' | 'running' | 'stopped' | 'error' | 'disabled'
  last_error: string | null
}

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
  msg_raw: string
}

export interface Alert {
  id: string
  level: 'info' | 'warning' | 'error'
  title: string
  message: string
  timestamp: string
  channel?: string
  read: boolean
}

export interface SkillManifest {
  name: string
  description: string
  parameters: Record<string, any>
}

export interface WebhookEntry {
  id: string
  timestamp: string
  method: string
  path: string
  headers: Record<string, string>
  body: string
  json: Record<string, any>
}

export type Page = 'overview' | 'chat' | 'memory' | 'sessions' | 'traces' | 'tasks' | 'soul' | 'settings' | 'channels' | 'logs' | 'webhooks'
