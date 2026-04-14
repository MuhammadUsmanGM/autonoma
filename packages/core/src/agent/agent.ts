import { nanoid } from "nanoid";
import type {
  AgentInstance,
  AgentResponse,
  Conversation,
  LLMProvider,
  Message,
  Skill,
  MemoryManager,
  LLMMessage,
} from "../types.js";
import { SkillRegistry } from "../skills/skill-registry.js";
import { FileMemoryManager } from "../memory/memory-manager.js";
import { FileConversationStore } from "../memory/conversation-store.js";

const DEFAULT_SYSTEM_PROMPT = `You are an Autonoma agent — an AI-powered digital employee that works like a dedicated team member. You are helpful, proactive, and capable of completing tasks across multiple platforms.

You have access to the following skills/tools:
{skills}

{memory_context}

When the user asks you to perform a task that matches a skill, use it. Otherwise, respond conversationally and helpfully.

IMPORTANT — Memory instructions:
- You remember users across conversations. Use their name when you know it.
- If the user tells you something important about themselves (their name, job, preferences, instructions), acknowledge it and remember it.
- When you learn a new fact about the user, include [REMEMBER: <fact>] at the end of your response. This will be saved to memory automatically. The user will NOT see this tag.
- When the user sets a preference, include [PREFERENCE: <key>=<value>] at the end of your response.
- You can store general knowledge with [FACT: <content> #tag1 #tag2].
- Keep responses concise and actionable.`;

/** Regex to extract memory commands from agent responses */
const REMEMBER_RE = /\[REMEMBER:\s*(.+?)\]/g;
const PREFERENCE_RE = /\[PREFERENCE:\s*(\w+)=(.+?)\]/g;
const FACT_RE = /\[FACT:\s*(.+?)(?:\s+(#\S+(?:\s+#\S+)*))?]/g;

/** Strip memory tags from the response the user sees */
function stripMemoryTags(text: string): string {
  return text
    .replace(REMEMBER_RE, "")
    .replace(PREFERENCE_RE, "")
    .replace(FACT_RE, "")
    .trim();
}

export class Agent implements AgentInstance {
  id: string;
  name: string;
  systemPrompt: string;
  skills: Skill[];
  memory: MemoryManager;
  llm: LLMProvider;

  private skillRegistry: SkillRegistry;
  private conversations = new Map<string, Conversation>();
  private conversationStore: FileConversationStore;
  private dataDir: string;

  constructor(config: {
    name: string;
    llm: LLMProvider;
    dataDir: string;
    systemPrompt?: string;
  }) {
    this.id = nanoid();
    this.name = config.name;
    this.llm = config.llm;
    this.dataDir = config.dataDir;
    this.memory = new FileMemoryManager(config.dataDir);
    this.conversationStore = new FileConversationStore(config.dataDir);
    this.skillRegistry = new SkillRegistry();
    this.skills = [];
    this.systemPrompt = config.systemPrompt ?? DEFAULT_SYSTEM_PROMPT;
  }

  registerSkill(skill: Skill): void {
    this.skillRegistry.register(skill);
    this.skills = this.skillRegistry.list();
  }

  async handleMessage(message: Message): Promise<AgentResponse> {
    // 1. Load or create conversation (from disk if first time this session)
    const conversation = await this.getOrLoadConversation(message);
    conversation.messages.push(message);
    conversation.updatedAt = new Date();

    // 2. Touch user profile (updates lastSeen, messageCount)
    const memoryManager = this.memory as FileMemoryManager;
    await memoryManager.touchUser(message);

    // 3. Build memory context for this user
    const memoryContext = await this.memory.getContextForMessage(message);

    // 4. Build system prompt with skills + memory
    const systemPrompt = this.systemPrompt
      .replace("{skills}", this.skillRegistry.getToolDescriptions() || "No skills loaded.")
      .replace("{memory_context}", memoryContext ? `## Your memory\n${memoryContext}` : "");

    // 5. Build LLM messages — include conversation history
    const llmMessages: LLMMessage[] = conversation.messages
      .slice(-30)
      .map((m) => ({
        role: (m.userId === this.id ? "assistant" : "user") as LLMMessage["role"],
        content: m.content,
      }));

    // 6. Get LLM response
    const rawResponse = await this.llm.chat(llmMessages, { systemPrompt });

    // 7. Extract and process memory commands from the response
    await this.processMemoryCommands(rawResponse, message);

    // 8. Strip memory tags from what the user sees
    const cleanResponse = stripMemoryTags(rawResponse);

    // 9. Store agent's response in conversation
    const agentMessage: Message = {
      id: nanoid(),
      platform: message.platform,
      channelId: message.channelId,
      userId: this.id,
      userName: this.name,
      content: cleanResponse,
      timestamp: new Date(),
    };
    conversation.messages.push(agentMessage);

    // 10. Persist conversation to disk
    await this.conversationStore.save(conversation);

    return { content: cleanResponse };
  }

  /**
   * Extract [REMEMBER], [PREFERENCE], [FACT] tags from the LLM response
   * and save them to memory.
   */
  private async processMemoryCommands(response: string, message: Message): Promise<void> {
    const memoryManager = this.memory as FileMemoryManager;

    // [REMEMBER: user likes coffee]
    let match;
    REMEMBER_RE.lastIndex = 0;
    while ((match = REMEMBER_RE.exec(response)) !== null) {
      const fact = match[1].trim();
      if (fact) {
        await memoryManager.addUserFact(message.platform, message.userId, fact);
      }
    }

    // [PREFERENCE: language=Spanish]
    PREFERENCE_RE.lastIndex = 0;
    while ((match = PREFERENCE_RE.exec(response)) !== null) {
      const key = match[1].trim();
      const value = match[2].trim();
      if (key && value) {
        await memoryManager.setUserPreference(message.platform, message.userId, key, value);
      }
    }

    // [FACT: TypeScript is a typed superset of JavaScript #programming #typescript]
    FACT_RE.lastIndex = 0;
    while ((match = FACT_RE.exec(response)) !== null) {
      const content = match[1].trim();
      const tagsStr = match[2]?.trim() ?? "";
      const tags = tagsStr.split(/\s+/).filter((t) => t.startsWith("#")).map((t) => t.slice(1));
      if (content) {
        await memoryManager.addFact({
          content,
          source: `user:${message.platform}:${message.userId}`,
          tags,
        });
      }
    }
  }

  /**
   * Get a conversation from in-memory cache, or load from disk.
   */
  private async getOrLoadConversation(message: Message): Promise<Conversation> {
    const key = `${message.platform}:${message.channelId}`;

    // Check in-memory cache first
    let conv = this.conversations.get(key);
    if (conv) return conv;

    // Try loading from disk (previous session)
    const saved = await this.conversationStore.load(message.platform, message.channelId);
    if (saved) {
      this.conversations.set(key, saved);
      return saved;
    }

    // Create new
    conv = {
      id: nanoid(),
      platform: message.platform,
      channelId: message.channelId,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    this.conversations.set(key, conv);
    return conv;
  }

  getConversations(): Conversation[] {
    return [...this.conversations.values()];
  }
}
