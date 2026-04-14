import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

export interface TelegramStatus {
  state: "disconnected" | "connecting" | "connected" | "error";
  botUsername?: string;
  error?: string;
}

/**
 * Telegram connector using Telegraf
 *
 * Setup flow:
 * 1. User enters bot token from @BotFather
 * 2. Bot connects and starts polling
 * 3. Auto-reconnects on error
 *
 * Supports: text, photos with captions, documents, stickers, voice messages, locations
 */
export class TelegramConnector extends BaseConnector {
  name = "telegram";
  type = "telegram";

  private bot: any = null;
  private status: TelegramStatus = { state: "disconnected" };

  getStatus(): TelegramStatus {
    return { ...this.status };
  }

  async connect(config: ConnectorConfig): Promise<void> {
    const { Telegraf } = await import("telegraf");

    const token = config.credentials.botToken;
    if (!token) throw new Error("Telegram bot token is required. Get one from @BotFather.");

    this.status = { state: "connecting" };
    this.emitStatusChange();

    this.bot = new Telegraf(token);

    // Get bot info
    const botInfo = await this.bot.telegram.getMe();

    // Handle all text messages
    this.bot.on("text", (ctx: any) => {
      this.emitMessage(this.buildMessage(ctx, ctx.message.text, "text"));
    });

    // Handle photos
    this.bot.on("photo", (ctx: any) => {
      const caption = ctx.message.caption ?? "[Photo]";
      this.emitMessage(this.buildMessage(ctx, caption, "photo"));
    });

    // Handle documents
    this.bot.on("document", (ctx: any) => {
      const caption = ctx.message.caption ?? `[Document: ${ctx.message.document.file_name}]`;
      this.emitMessage(this.buildMessage(ctx, caption, "document"));
    });

    // Handle voice messages
    this.bot.on("voice", (ctx: any) => {
      this.emitMessage(this.buildMessage(ctx, "[Voice message]", "voice"));
    });

    // Handle stickers
    this.bot.on("sticker", (ctx: any) => {
      this.emitMessage(this.buildMessage(ctx, `[Sticker: ${ctx.message.sticker.emoji ?? ""}]`, "sticker"));
    });

    // Handle location
    this.bot.on("location", (ctx: any) => {
      const { latitude, longitude } = ctx.message.location;
      this.emitMessage(this.buildMessage(ctx, `[Location: ${latitude}, ${longitude}]`, "location"));
    });

    // Error handling
    this.bot.catch((err: any) => {
      this.status = { state: "error", error: err.message, botUsername: botInfo.username };
      this.emitStatusChange();
      this.emit("error", err);
    });

    await this.bot.launch();

    this.connected = true;
    this.status = { state: "connected", botUsername: botInfo.username };
    this.emitStatusChange();
    this.emit("connected");

    // Graceful shutdown
    process.once("SIGINT", () => this.bot?.stop("SIGINT"));
    process.once("SIGTERM", () => this.bot?.stop("SIGTERM"));
  }

  private buildMessage(ctx: any, content: string, messageType: string): Message {
    const chat = ctx.chat;
    const from = ctx.from;
    const isGroup = chat.type === "group" || chat.type === "supergroup";

    return {
      id: String(ctx.message.message_id),
      platform: "telegram",
      channelId: String(chat.id),
      userId: String(from.id),
      userName: from.first_name
        ? `${from.first_name}${from.last_name ? ` ${from.last_name}` : ""}`
        : from.username ?? "Unknown",
      content,
      timestamp: new Date(ctx.message.date * 1000),
      metadata: {
        isGroup,
        chatTitle: chat.title,
        username: from.username,
        messageType,
      },
    };
  }

  async disconnect(): Promise<void> {
    if (this.bot) {
      this.bot.stop();
      this.bot = null;
    }
    this.connected = false;
    this.status = { state: "disconnected" };
    this.emitStatusChange();
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.bot) throw new Error("Telegram not connected");
    await this.bot.telegram.sendMessage(channelId, content, { parse_mode: "Markdown" });
  }

  async sendPhoto(channelId: string, photoUrl: string, caption?: string): Promise<void> {
    if (!this.bot) throw new Error("Telegram not connected");
    await this.bot.telegram.sendPhoto(channelId, photoUrl, { caption });
  }

  private emitStatusChange(): void {
    this.emit("status", this.getStatus());
  }
}
