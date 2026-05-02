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

export interface UsageBucket {
  tokens_in: number
  tokens_out: number
  cost_usd: number
  calls: number
}

export interface UsageStats {
  today: UsageBucket
  week: UsageBucket
  month: UsageBucket
  total: UsageBucket
  by_model: Record<string, UsageBucket>
}

export interface TaskItem {
  id: string
  name: string
  priority: number
  // Server-side TaskItem stores a ``payload`` dict, not ``skill`` + ``args``.
  // Older handlers used skill/args; both are optional on the wire so the UI
  // can render either shape without exploding.
  payload?: Record<string, any>
  skill?: string
  args?: Record<string, any>
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'scheduled'
  created_at: string
  started_at: string | null
  completed_at: string | null
  result: any | null
  error: string | null
  retries: number
  max_retries: number
  // Cron fields — present when this is a recurring scheduled task.
  cron?: string | null
  next_run_at?: string | null
  last_run_at?: string | null
  run_count?: number
}

export interface TaskStats {
  total: number
  pending: number
  running: number
  completed: number
  failed: number
  cancelled: number
  scheduled?: number
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

export interface ProxyHealth {
  channel: string
  proxy_url: string      // credentials already masked by the backend
  configured: boolean
  ok: boolean
  latency_ms: number | null
  error: string | null
  target: string         // "host:port" tunneled through
  checked_at: number     // unix timestamp
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

export type Page = 'overview' | 'chat' | 'memory' | 'sessions' | 'traces' | 'tasks' | 'soul' | 'settings' | 'channels' | 'connectors' | 'contacts' | 'logs' | 'webhooks'

export interface ContactChannel {
  channel: string
  user_id: string
}

export interface ContactExtracted {
  kind: 'email' | 'phone' | 'handle'
  value: string
}

export interface Contact {
  canonical_id: string
  display_name: string
  tier: 'stranger' | 'acquaintance' | 'colleague' | 'vip'
  message_count: number
  first_seen: number
  last_seen: number
  vip_flag: boolean
  notes: string
  channels: ContactChannel[]
  extracted: ContactExtracted[]
}

export interface ConnectorManifest {
  name: string
  display_name: string
  description: string
  auth_type: 'oauth2' | 'api_key'
  scopes: string[]
  icon: string
}

export interface ConnectorStatusInfo {
  state: 'disconnected' | 'connecting' | 'connected' | 'expired' | 'error'
  account_id: string
  account_label: string
  scopes: string[]
  expires_at: number
  last_error: string
}

export interface ConnectorEntry {
  manifest: ConnectorManifest
  status: ConnectorStatusInfo
}
