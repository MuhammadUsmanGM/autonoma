import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

/**
 * Discord connector using discord.js
 * Requires a bot token from Discord Developer Portal
 */
export class DiscordConnector extends BaseConnector {
  name = "discord";
  type = "discord";

  private client: any = null;

  async connect(config: ConnectorConfig): Promise<void> {
    const { Client, GatewayIntentBits } = await import("discord.js");

    const token = config.credentials.botToken;
    if (!token) throw new Error("Discord bot token is required");

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
      ],
    });

    this.client.on("messageCreate", (msg: any) => {
      if (msg.author.bot) return;

      const message: Message = {
        id: msg.id,
        platform: "discord",
        channelId: msg.channel.id,
        userId: msg.author.id,
        userName: msg.author.username,
        content: msg.content,
        timestamp: msg.createdAt,
      };
      this.emitMessage(message);
    });

    this.client.on("ready", () => {
      this.connected = true;
      this.emit("connected");
    });

    await this.client.login(token);
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      this.client.destroy();
      this.client = null;
    }
    this.connected = false;
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.client) throw new Error("Discord not connected");
    const channel = await this.client.channels.fetch(channelId);
    if (channel?.isTextBased()) {
      await channel.send(content);
    }
  }
}
