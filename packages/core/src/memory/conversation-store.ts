import { readFile, writeFile, mkdir, readdir, unlink } from "node:fs/promises";
import { join } from "node:path";
import type { Conversation, ConversationStore, Message } from "../types.js";

/**
 * Persists conversations to disk so the agent remembers past chats across restarts.
 *
 * Storage: .autonoma/conversations/{platform}_{channelId}.json
 *
 * Keeps last 100 messages per conversation to avoid unbounded growth.
 */
export class FileConversationStore implements ConversationStore {
  private dir: string;
  private maxMessages: number;

  constructor(dataDir: string, maxMessages = 100) {
    this.dir = join(dataDir, "conversations");
    this.maxMessages = maxMessages;
  }

  private async ensureDir(): Promise<void> {
    await mkdir(this.dir, { recursive: true });
  }

  private filePath(platform: string, channelId: string): string {
    const safe = `${platform}_${channelId}`.replace(/[^a-zA-Z0-9_@.-]/g, "_");
    return join(this.dir, `${safe}.json`);
  }

  async save(conversation: Conversation): Promise<void> {
    await this.ensureDir();

    // Only keep recent messages
    const trimmed: Conversation = {
      ...conversation,
      messages: conversation.messages.slice(-this.maxMessages),
    };

    await writeFile(
      this.filePath(conversation.platform, conversation.channelId),
      JSON.stringify(trimmed, null, 2)
    );
  }

  async load(platform: string, channelId: string): Promise<Conversation | null> {
    try {
      const data = await readFile(this.filePath(platform, channelId), "utf-8");
      const conv = JSON.parse(data) as Conversation;
      // Restore Date objects
      conv.createdAt = new Date(conv.createdAt);
      conv.updatedAt = new Date(conv.updatedAt);
      conv.messages = conv.messages.map((m) => ({
        ...m,
        timestamp: new Date(m.timestamp),
      }));
      return conv;
    } catch {
      return null;
    }
  }

  async list(): Promise<Array<{
    id: string;
    platform: string;
    channelId: string;
    messageCount: number;
    updatedAt: Date;
  }>> {
    await this.ensureDir();
    const files = await readdir(this.dir);
    const summaries = [];

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const data = await readFile(join(this.dir, file), "utf-8");
        const conv = JSON.parse(data) as Conversation;
        summaries.push({
          id: conv.id,
          platform: conv.platform,
          channelId: conv.channelId,
          messageCount: conv.messages.length,
          updatedAt: new Date(conv.updatedAt),
        });
      } catch { /* skip */ }
    }

    return summaries.sort(
      (a, b) => b.updatedAt.getTime() - a.updatedAt.getTime()
    );
  }

  async delete(platform: string, channelId: string): Promise<void> {
    try {
      await unlink(this.filePath(platform, channelId));
    } catch { /* skip */ }
  }
}
