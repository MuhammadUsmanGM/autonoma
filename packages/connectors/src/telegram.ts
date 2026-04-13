import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@nexkraft/core";

/**
 * Telegram connector using Telegraf
 * Requires a bot token from @BotFather
 */
export class TelegramConnector extends BaseConnector {
  name = "telegram";
  type = "telegram";

  private bot: any = null;

  async connect(config: ConnectorConfig): Promise<void> {
    const { Telegraf } = await import("telegraf");

    const token = config.credentials.botToken;
    if (!token) throw new Error("Telegram bot token is required");

    this.bot = new Telegraf(token);

    this.bot.on("text", (ctx: any) => {
      const message: Message = {
        id: String(ctx.message.message_id),
        platform: "telegram",
        channelId: String(ctx.chat.id),
        userId: String(ctx.from.id),
        userName: ctx.from.first_name ?? ctx.from.username ?? "Unknown",
        content: ctx.message.text,
        timestamp: new Date(ctx.message.date * 1000),
      };
      this.emitMessage(message);
    });

    await this.bot.launch();
    this.connected = true;
    this.emit("connected");
  }

  async disconnect(): Promise<void> {
    if (this.bot) {
      this.bot.stop();
      this.bot = null;
    }
    this.connected = false;
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.bot) throw new Error("Telegram not connected");
    await this.bot.telegram.sendMessage(channelId, content);
  }
}
