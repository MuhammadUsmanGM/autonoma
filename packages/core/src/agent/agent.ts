import { nanoid } from "nanoid";
import type {
  AgentInstance,
  AgentResponse,
  Conversation,
  LLMProvider,
  Message,
  Skill,
  MemoryStore,
  LLMMessage,
} from "../types.js";
import { SkillRegistry } from "../skills/skill-registry.js";
import { FileMemoryStore } from "../memory/file-memory.js";

const DEFAULT_SYSTEM_PROMPT = `You are an Autonoma agent — an AI-powered digital employee that works like a dedicated team member. You are helpful, proactive, and capable of completing tasks across multiple platforms.

You have access to the following skills/tools:
{skills}

When the user asks you to perform a task that matches a skill, use it. Otherwise, respond conversationally and helpfully.

Keep responses concise and actionable. If you need more information, ask.`;

export class Agent implements AgentInstance {
  id: string;
  name: string;
  systemPrompt: string;
  skills: Skill[];
  memory: MemoryStore;
  llm: LLMProvider;

  private skillRegistry: SkillRegistry;
  private conversations = new Map<string, Conversation>();

  constructor(config: {
    name: string;
    llm: LLMProvider;
    dataDir: string;
    systemPrompt?: string;
  }) {
    this.id = nanoid();
    this.name = config.name;
    this.llm = config.llm;
    this.memory = new FileMemoryStore(config.dataDir);
    this.skillRegistry = new SkillRegistry();
    this.skills = [];
    this.systemPrompt = config.systemPrompt ?? DEFAULT_SYSTEM_PROMPT;
  }

  registerSkill(skill: Skill): void {
    this.skillRegistry.register(skill);
    this.skills = this.skillRegistry.list();
  }

  async handleMessage(message: Message): Promise<AgentResponse> {
    const conversation = this.getOrCreateConversation(message);
    conversation.messages.push(message);
    conversation.updatedAt = new Date();

    const systemPrompt = this.systemPrompt.replace(
      "{skills}",
      this.skillRegistry.getToolDescriptions() || "No skills loaded."
    );

    const llmMessages: LLMMessage[] = [
      ...conversation.messages.slice(-20).map((m) => ({
        role: (m.userId === this.id ? "assistant" : "user") as LLMMessage["role"],
        content: m.content,
      })),
    ];

    const response = await this.llm.chat(llmMessages, { systemPrompt });

    const agentMessage: Message = {
      id: nanoid(),
      platform: message.platform,
      channelId: message.channelId,
      userId: this.id,
      userName: this.name,
      content: response,
      timestamp: new Date(),
    };
    conversation.messages.push(agentMessage);

    return { content: response };
  }

  private getOrCreateConversation(message: Message): Conversation {
    const key = `${message.platform}:${message.channelId}`;
    let conv = this.conversations.get(key);
    if (!conv) {
      conv = {
        id: nanoid(),
        platform: message.platform,
        channelId: message.channelId,
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      this.conversations.set(key, conv);
    }
    return conv;
  }

  getConversations(): Conversation[] {
    return [...this.conversations.values()];
  }
}
