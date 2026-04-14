import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

export interface DiscordStatus {
  state: "disconnected" | "connecting" | "connected" | "error";
  botUsername?: string;
  guildCount?: number;
  error?: string;
}

/**
 * Discord connector using discord.js
 *
 * Setup flow:
 * 1. User enters bot token from Discord Developer Portal
 * 2. Bot connects to Discord gateway
 * 3. Listens for messages in all guilds + DMs
 * 4. Auto-reconnects via discord.js built-in handling
 *
 * Supports: text, embeds, attachments, DMs, guild channels, threads
 */
export class DiscordConnector extends BaseConnector {
  name = "discord";
  type = "discord";

  private client: any = null;
  private status: DiscordStatus = { state: "disconnected" };

  getStatus(): DiscordStatus {
    return { ...this.status };
  }

  async connect(config: ConnectorConfig): Promise<void> {
    const { Client, GatewayIntentBits, Partials } = await import("discord.js");

    const token = config.credentials.botToken;
    if (!token) throw new Error("Discord bot token is required. Get one from the Discord Developer Portal.");

    this.status = { state: "connecting" };
    this.emitStatusChange();

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
        GatewayIntentBits.GuildMembers,
      ],
      partials: [Partials.Channel, Partials.Message],
    });

    this.client.on("messageCreate", (msg: any) => {
      // Skip bot messages
      if (msg.author.bot) return;

      const isDM = !msg.guild;
      let content = msg.content ?? "";

      // Append attachment info
      if (msg.attachments.size > 0) {
        const attachmentList = msg.attachments.map((a: any) => a.name ?? a.url).join(", ");
        content += content ? `\n[Attachments: ${attachmentList}]` : `[Attachments: ${attachmentList}]`;
      }

      if (!content) return;

      const message: Message = {
        id: msg.id,
        platform: "discord",
        channelId: msg.channel.id,
        userId: msg.author.id,
        userName: msg.member?.displayName ?? msg.author.displayName ?? msg.author.username,
        content,
        timestamp: msg.createdAt,
        metadata: {
          isDM,
          guildId: msg.guild?.id,
          guildName: msg.guild?.name,
          channelName: (msg.channel as any).name,
          isThread: msg.channel.isThread?.() ?? false,
          messageType: msg.attachments.size > 0 ? "attachment" : "text",
        },
      };
      this.emitMessage(message);
    });

    this.client.on("ready", () => {
      this.connected = true;
      this.status = {
        state: "connected",
        botUsername: this.client.user?.tag,
        guildCount: this.client.guilds.cache.size,
      };
      this.emitStatusChange();
      this.emit("connected");
    });

    this.client.on("error", (err: any) => {
      this.status = { ...this.status, state: "error", error: err.message };
      this.emitStatusChange();
      this.emit("error", err);
    });

    // discord.js handles reconnection internally
    this.client.on("shardReconnecting", () => {
      this.status = { ...this.status, state: "connecting" };
      this.emitStatusChange();
    });

    this.client.on("shardResume", () => {
      this.status = { ...this.status, state: "connected" };
      this.emitStatusChange();
    });

    await this.client.login(token);
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      this.client.destroy();
      this.client = null;
    }
    this.connected = false;
    this.status = { state: "disconnected" };
    this.emitStatusChange();
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.client) throw new Error("Discord not connected");
    const channel = await this.client.channels.fetch(channelId);
    if (channel?.isTextBased()) {
      // Split long messages (Discord 2000 char limit)
      if (content.length <= 2000) {
        await channel.send(content);
      } else {
        const chunks = content.match(/[\s\S]{1,2000}/g) ?? [];
        for (const chunk of chunks) {
          await channel.send(chunk);
        }
      }
    }
  }

  async sendEmbed(channelId: string, embed: Record<string, unknown>): Promise<void> {
    if (!this.client) throw new Error("Discord not connected");
    const channel = await this.client.channels.fetch(channelId);
    if (channel?.isTextBased()) {
      await channel.send({ embeds: [embed] });
    }
  }

  private emitStatusChange(): void {
    this.emit("status", this.getStatus());
  }
}
