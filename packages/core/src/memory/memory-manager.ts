import { readFile, writeFile, mkdir, readdir, unlink } from "node:fs/promises";
import { join } from "node:path";
import { nanoid } from "nanoid";
import type { MemoryManager, UserProfile, MemoryFact, Message } from "../types.js";

/**
 * Full memory system for Autonoma — like OpenClaw's persistent memory.
 *
 * Storage layout:
 *   .autonoma/
 *     memory/
 *       users/           — one JSON file per user (platform_userId.json)
 *       facts/           — one JSON file per fact
 *       kv/              — general key-value store
 */
export class FileMemoryManager implements MemoryManager {
  private usersDir: string;
  private factsDir: string;
  private kvDir: string;

  constructor(dataDir: string) {
    const base = join(dataDir, "memory");
    this.usersDir = join(base, "users");
    this.factsDir = join(base, "facts");
    this.kvDir = join(base, "kv");
  }

  private async ensureDirs(): Promise<void> {
    await Promise.all([
      mkdir(this.usersDir, { recursive: true }),
      mkdir(this.factsDir, { recursive: true }),
      mkdir(this.kvDir, { recursive: true }),
    ]);
  }

  // ====== USER PROFILES ======

  private userFilePath(platform: string, userId: string): string {
    const safe = `${platform}_${userId}`.replace(/[^a-zA-Z0-9_@.-]/g, "_");
    return join(this.usersDir, `${safe}.json`);
  }

  async getUser(platform: string, userId: string): Promise<UserProfile | null> {
    try {
      const data = await readFile(this.userFilePath(platform, userId), "utf-8");
      return JSON.parse(data) as UserProfile;
    } catch {
      return null;
    }
  }

  async saveUser(user: UserProfile): Promise<void> {
    await this.ensureDirs();
    await writeFile(
      this.userFilePath(user.platform, user.id),
      JSON.stringify(user, null, 2)
    );
  }

  async listUsers(): Promise<UserProfile[]> {
    await this.ensureDirs();
    const files = await readdir(this.usersDir);
    const users: UserProfile[] = [];
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const data = await readFile(join(this.usersDir, file), "utf-8");
        users.push(JSON.parse(data));
      } catch { /* skip */ }
    }
    return users.sort(
      (a, b) => new Date(b.lastSeen).getTime() - new Date(a.lastSeen).getTime()
    );
  }

  /** Get or create a user profile, updating lastSeen and messageCount */
  async touchUser(message: Message): Promise<UserProfile> {
    let user = await this.getUser(message.platform, message.userId);
    if (!user) {
      user = {
        id: message.userId,
        platform: message.platform,
        userName: message.userName ?? message.userId,
        facts: [],
        preferences: {},
        firstSeen: new Date(),
        lastSeen: new Date(),
        messageCount: 0,
      };
    }
    user.lastSeen = new Date();
    user.messageCount++;
    if (message.userName && message.userName !== user.userName) {
      user.userName = message.userName;
    }
    await this.saveUser(user);
    return user;
  }

  /** Add a fact to a user's profile */
  async addUserFact(platform: string, userId: string, fact: string): Promise<void> {
    const user = await this.getUser(platform, userId);
    if (!user) return;
    // Avoid duplicates
    if (!user.facts.includes(fact)) {
      user.facts.push(fact);
      await this.saveUser(user);
    }
  }

  /** Set a user preference */
  async setUserPreference(platform: string, userId: string, key: string, value: string): Promise<void> {
    const user = await this.getUser(platform, userId);
    if (!user) return;
    user.preferences[key] = value;
    await this.saveUser(user);
  }

  // ====== FACTS / KNOWLEDGE ======

  async addFact(data: Omit<MemoryFact, "id" | "createdAt">): Promise<MemoryFact> {
    await this.ensureDirs();
    const fact: MemoryFact = {
      id: nanoid(),
      content: data.content,
      source: data.source,
      tags: data.tags,
      createdAt: new Date(),
    };
    await writeFile(
      join(this.factsDir, `${fact.id}.json`),
      JSON.stringify(fact, null, 2)
    );
    return fact;
  }

  async getFacts(query?: string): Promise<MemoryFact[]> {
    await this.ensureDirs();
    const files = await readdir(this.factsDir);
    const facts: MemoryFact[] = [];
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const data = await readFile(join(this.factsDir, file), "utf-8");
        facts.push(JSON.parse(data));
      } catch { /* skip */ }
    }

    if (query) {
      const lower = query.toLowerCase();
      return facts.filter(
        (f) =>
          f.content.toLowerCase().includes(lower) ||
          f.tags.some((t) => t.toLowerCase().includes(lower))
      );
    }

    return facts.sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  }

  async deleteFact(id: string): Promise<void> {
    try {
      await unlink(join(this.factsDir, `${id}.json`));
    } catch { /* skip */ }
  }

  // ====== KEY-VALUE ======

  async get(key: string): Promise<string | null> {
    try {
      const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, "_");
      const data = await readFile(join(this.kvDir, `${safeKey}.json`), "utf-8");
      return JSON.parse(data).value;
    } catch {
      return null;
    }
  }

  async set(key: string, value: string): Promise<void> {
    await this.ensureDirs();
    const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, "_");
    await writeFile(
      join(this.kvDir, `${safeKey}.json`),
      JSON.stringify({ key, value, updatedAt: new Date() }, null, 2)
    );
  }

  async delete(key: string): Promise<void> {
    try {
      const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, "_");
      await unlink(join(this.kvDir, `${safeKey}.json`));
    } catch { /* skip */ }
  }

  // ====== CONTEXT BUILDING ======

  /**
   * Build a memory context string for the LLM.
   * This gets injected into the system prompt so the agent "remembers" the user.
   */
  async getContextForMessage(message: Message): Promise<string> {
    const parts: string[] = [];

    // 1. User profile
    const user = await this.getUser(message.platform, message.userId);
    if (user) {
      parts.push(`## About this user`);
      parts.push(`- Name: ${user.userName}`);
      parts.push(`- Platform: ${user.platform}`);
      parts.push(`- First seen: ${new Date(user.firstSeen).toLocaleDateString()}`);
      parts.push(`- Messages exchanged: ${user.messageCount}`);

      if (user.facts.length > 0) {
        parts.push(`- Known facts:`);
        for (const fact of user.facts.slice(-10)) {
          parts.push(`  - ${fact}`);
        }
      }

      if (Object.keys(user.preferences).length > 0) {
        parts.push(`- Preferences:`);
        for (const [k, v] of Object.entries(user.preferences)) {
          parts.push(`  - ${k}: ${v}`);
        }
      }
    }

    // 2. Relevant facts
    const keywords = message.content.split(/\s+/).filter((w) => w.length > 3).slice(0, 5);
    if (keywords.length > 0) {
      const relevantFacts: MemoryFact[] = [];
      for (const kw of keywords) {
        const matched = await this.getFacts(kw);
        for (const f of matched) {
          if (!relevantFacts.some((r) => r.id === f.id)) {
            relevantFacts.push(f);
          }
        }
      }
      if (relevantFacts.length > 0) {
        parts.push(`\n## Relevant knowledge`);
        for (const fact of relevantFacts.slice(0, 5)) {
          parts.push(`- ${fact.content}`);
        }
      }
    }

    return parts.join("\n");
  }
}
