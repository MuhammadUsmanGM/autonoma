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

export type Page = 'overview' | 'chat' | 'memory' | 'sessions'
