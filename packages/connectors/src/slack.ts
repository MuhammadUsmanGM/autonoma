import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

export interface SlackStatus {
  state: "disconnected" | "connecting" | "connected" | "error";
  botName?: string;
  teamName?: string;
  error?: string;
}

/**
 * Slack connector using @slack/bolt
 *
 * Setup flow (Socket Mode — no public URL needed):
 * 1. Create a Slack App at api.slack.com/apps
 * 2. Enable Socket Mode → get App-Level Token (xapp-...)
 * 3. Add Bot Token Scopes: chat:write, channels:history, groups:history, im:history, mpim:history
 * 4. Install to workspace → get Bot Token (xoxb-...)
 * 5. Enter tokens in Autonoma dashboard
 *
 * Supports: text messages, mentions, DMs, channels, threads
 */
export class SlackConnector extends BaseConnector {
  name = "slack";
  type = "slack";

  private app: any = null;
  private status: SlackStatus = { state: "disconnected" };

  getStatus(): SlackStatus {
    return { ...this.status };
  }

  async connect(config: ConnectorConfig): Promise<void> {
    const { App } = await import("@slack/bolt");

    const token = config.credentials.botToken;
    const appToken = config.credentials.appToken;
    const signingSecret = config.credentials.signingSecret ?? "dummy";

    if (!token) throw new Error("Slack Bot Token (xoxb-...) is required.");
    if (!appToken) throw new Error("Slack App Token (xapp-...) is required for Socket Mode.");

    this.status = { state: "connecting" };
    this.emitStatusChange();

    this.app = new App({
      token,
      appToken,
      signingSecret,
      socketMode: true,
    });

    // Listen to all messages
    this.app.message(async ({ message: msg, client }: any) => {
      // Skip bot messages, message changes, deletions
      if (msg.subtype) return;
      if (msg.bot_id) return;

      // Get user info for display name
      let userName = msg.user;
      try {
        const userInfo = await client.users.info({ user: msg.user });
        userName = userInfo.user?.real_name ?? userInfo.user?.name ?? msg.user;
      } catch {
        // Fall back to user ID
      }

      const message: Message = {
        id: msg.ts,
        platform: "slack",
        channelId: msg.channel,
        userId: msg.user,
        userName,
        content: msg.text ?? "",
        timestamp: new Date(parseFloat(msg.ts) * 1000),
        metadata: {
          threadTs: msg.thread_ts,
          isThread: !!msg.thread_ts,
          channelType: msg.channel_type,
          messageType: "text",
        },
      };
      this.emitMessage(message);
    });

    // Handle app mention events
    this.app.event("app_mention", async ({ event, client }: any) => {
      let userName = event.user;
      try {
        const userInfo = await client.users.info({ user: event.user });
        userName = userInfo.user?.real_name ?? userInfo.user?.name ?? event.user;
      } catch {}

      const message: Message = {
        id: event.ts,
        platform: "slack",
        channelId: event.channel,
        userId: event.user,
        userName,
        content: event.text ?? "",
        timestamp: new Date(parseFloat(event.ts) * 1000),
        metadata: {
          isMention: true,
          threadTs: event.thread_ts,
          messageType: "mention",
        },
      };
      this.emitMessage(message);
    });

    await this.app.start();

    // Get team info
    try {
      const authResult = await this.app.client.auth.test();
      this.status = {
        state: "connected",
        botName: authResult.user,
        teamName: authResult.team,
      };
    } catch {
      this.status = { state: "connected" };
    }

    this.connected = true;
    this.emitStatusChange();
    this.emit("connected");
  }

  async disconnect(): Promise<void> {
    if (this.app) {
      await this.app.stop();
      this.app = null;
    }
    this.connected = false;
    this.status = { state: "disconnected" };
    this.emitStatusChange();
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.app) throw new Error("Slack not connected");
    await this.app.client.chat.postMessage({
      channel: channelId,
      text: content,
    });
  }

  async sendInThread(channelId: string, threadTs: string, content: string): Promise<void> {
    if (!this.app) throw new Error("Slack not connected");
    await this.app.client.chat.postMessage({
      channel: channelId,
      thread_ts: threadTs,
      text: content,
    });
  }

  private emitStatusChange(): void {
    this.emit("status", this.getStatus());
  }
}
