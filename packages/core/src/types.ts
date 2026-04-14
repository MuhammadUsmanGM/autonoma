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
  memory: MemoryManager;
  llm: LLMProvider;
}

// ====== MEMORY TYPES ======

/** A user the agent has interacted with */
export interface UserProfile {
  id: string;
  platform: string;
  userName: string;
  displayName?: string;
  facts: string[];
  preferences: Record<string, string>;
  firstSeen: Date;
  lastSeen: Date;
  messageCount: number;
}

/** A fact/knowledge the agent has learned */
export interface MemoryFact {
  id: string;
  content: string;
  source: string;        // "user:whatsapp:123" or "conversation:xyz"
  tags: string[];
  createdAt: Date;
}

/** The full memory manager interface */
export interface MemoryManager {
  // User profiles
  getUser(platform: string, userId: string): Promise<UserProfile | null>;
  saveUser(user: UserProfile): Promise<void>;
  listUsers(): Promise<UserProfile[]>;

  // Facts / knowledge
  addFact(fact: Omit<MemoryFact, "id" | "createdAt">): Promise<MemoryFact>;
  getFacts(query?: string): Promise<MemoryFact[]>;
  deleteFact(id: string): Promise<void>;

  // Key-value (general purpose)
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  delete(key: string): Promise<void>;

  // Context building — get relevant memory for a given message
  getContextForMessage(message: Message): Promise<string>;
}

/** Conversation store — separate from memory */
export interface ConversationStore {
  save(conversation: Conversation): Promise<void>;
  load(platform: string, channelId: string): Promise<Conversation | null>;
  list(): Promise<Array<{ id: string; platform: string; channelId: string; messageCount: number; updatedAt: Date }>>;
  delete(platform: string, channelId: string): Promise<void>;
}

// Legacy compat
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

export interface AutonomaConfig {
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
