export interface Message {
  id: string;
  platform: string;
  channelId: string;
  userId: string;
  userName?: string;
  content: string;
  timestamp: Date;
  metadata?: Record<string, unknown>;
}

export interface AgentResponse {
  content: string;
  actions?: AgentAction[];
  metadata?: Record<string, unknown>;
}

export interface AgentAction {
  type: string;
  payload: Record<string, unknown>;
}

export interface Conversation {
  id: string;
  platform: string;
  channelId: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

export interface LLMProvider {
  name: string;
  chat(messages: LLMMessage[], options?: LLMOptions): Promise<string>;
  stream?(messages: LLMMessage[], options?: LLMOptions): AsyncIterable<string>;
}

export interface LLMMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface LLMOptions {
  model?: string;
  temperature?: number;
  maxTokens?: number;
  systemPrompt?: string;
}

export interface Skill {
  name: string;
  description: string;
  parameters?: SkillParameter[];
  execute(params: Record<string, unknown>, context: SkillContext): Promise<string>;
}

export interface SkillParameter {
  name: string;
  type: "string" | "number" | "boolean";
  description: string;
  required?: boolean;
}

export interface SkillContext {
  message: Message;
  conversation: Conversation;
  agent: AgentInstance;
}

export interface AgentInstance {
  id: string;
  name: string;
  systemPrompt: string;
  skills: Skill[];
  memory: MemoryStore;
  llm: LLMProvider;
}

export interface MemoryStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;
  search(query: string): Promise<MemoryEntry[]>;
  list(): Promise<MemoryEntry[]>;
}

export interface MemoryEntry {
  key: string;
  value: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface ConnectorConfig {
  type: string;
  enabled: boolean;
  credentials: Record<string, string>;
}

export interface NexKraftConfig {
  name: string;
  port: number;
  llm: {
    provider: string;
    apiKey: string;
    model?: string;
  };
  connectors: ConnectorConfig[];
  systemPrompt?: string;
  dataDir?: string;
}

export interface Connector {
  name: string;
  type: string;
  connected: boolean;
  connect(config: ConnectorConfig): Promise<void>;
  disconnect(): Promise<void>;
  send(channelId: string, content: string): Promise<void>;
  onMessage(handler: (message: Message) => void): void;
  getQRCode?(): Promise<string | null>;
}
