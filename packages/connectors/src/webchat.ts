import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@nexkraft/core";

/**
 * Built-in web chat connector
 * Messages are received via the REST API and WebSocket server in @digital-fte/core
 * This connector acts as a bridge for the dashboard's built-in chat
 */
export class WebChatConnector extends BaseConnector {
  name = "webchat";
  type = "webchat";

  private pendingResponses = new Map<string, (content: string) => void>();

  async connect(_config: ConnectorConfig): Promise<void> {
    this.connected = true;
    this.emit("connected");
  }

  async disconnect(): Promise<void> {
    this.connected = false;
  }

  async send(channelId: string, content: string): Promise<void> {
    // Web chat responses are sent directly through the API/WebSocket
    // This is a no-op since the server handles the response delivery
    const resolver = this.pendingResponses.get(channelId);
    if (resolver) {
      resolver(content);
      this.pendingResponses.delete(channelId);
    }
  }

  /**
   * Inject a message from the web dashboard
   */
  injectMessage(message: Message): void {
    this.emitMessage(message);
  }
}
