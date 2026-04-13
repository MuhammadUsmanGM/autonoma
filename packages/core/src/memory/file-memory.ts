import { readFile, writeFile, mkdir, readdir, unlink, stat } from "node:fs/promises";
import { join } from "node:path";
import type { MemoryStore, MemoryEntry } from "../types.js";

export class FileMemoryStore implements MemoryStore {
  private dir: string;

  constructor(dataDir: string) {
    this.dir = join(dataDir, "memory");
  }

  private async ensureDir(): Promise<void> {
    await mkdir(this.dir, { recursive: true });
  }

  private filePath(key: string): string {
    const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, "_");
    return join(this.dir, `${safeKey}.json`);
  }

  async get(key: string): Promise<string | null> {
    try {
      const data = await readFile(this.filePath(key), "utf-8");
      const entry = JSON.parse(data) as MemoryEntry;
      return entry.value;
    } catch {
      return null;
    }
  }

  async set(key: string, value: string): Promise<void> {
    await this.ensureDir();
    const existing = await this.get(key);
    const now = new Date();
    const entry: MemoryEntry = {
      key,
      value,
      createdAt: existing ? new Date() : now,
      updatedAt: now,
    };
    await writeFile(this.filePath(key), JSON.stringify(entry, null, 2));
  }

  async delete(key: string): Promise<void> {
    try {
      await unlink(this.filePath(key));
    } catch {
      // Ignore if not found
    }
  }

  async search(query: string): Promise<MemoryEntry[]> {
    const all = await this.list();
    const lower = query.toLowerCase();
    return all.filter(
      (e) =>
        e.key.toLowerCase().includes(lower) ||
        e.value.toLowerCase().includes(lower)
    );
  }

  async list(): Promise<MemoryEntry[]> {
    await this.ensureDir();
    const files = await readdir(this.dir);
    const entries: MemoryEntry[] = [];

    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const data = await readFile(join(this.dir, file), "utf-8");
        entries.push(JSON.parse(data) as MemoryEntry);
      } catch {
        // Skip corrupt files
      }
    }

    return entries.sort(
      (a, b) =>
        new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    );
  }
}
