import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@nexkraft/core";

/**
 * Slack connector using @slack/bolt
 * Requires bot token and signing secret from Slack App settings
 */
export class SlackConnector extends BaseConnector {
  name = "slack";
  type = "slack";

  private app: any = null;

  async connect(config: ConnectorConfig): Promise<void> {
    const { App } = await import("@slack/bolt");

    const token = config.credentials.botToken;
    const signingSecret = config.credentials.signingSecret;
    const appToken = config.credentials.appToken;

    if (!token || !signingSecret) {
      throw new Error("Slack bot token and signing secret are required");
    }

    this.app = new App({
      token,
      signingSecret,
      appToken,
      socketMode: !!appToken,
    });

    this.app.message(async ({ message: msg, say }: any) => {
      if (msg.subtype) return; // Skip bot messages, edits, etc.

      const message: Message = {
        id: msg.ts,
        platform: "slack",
        channelId: msg.channel,
        userId: msg.user,
        userName: msg.user,
        content: msg.text ?? "",
        timestamp: new Date(parseFloat(msg.ts) * 1000),
      };
      this.emitMessage(message);
    });

    await this.app.start();
    this.connected = true;
    this.emit("connected");
  }

  async disconnect(): Promise<void> {
    if (this.app) {
      await this.app.stop();
      this.app = null;
    }
    this.connected = false;
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.app) throw new Error("Slack not connected");
    await this.app.client.chat.postMessage({
      channel: channelId,
      text: content,
    });
  }
}
