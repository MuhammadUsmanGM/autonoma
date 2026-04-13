import EventEmitter from "eventemitter3";
import type { Message, Connector, AgentResponse } from "../types.js";

interface RouterEvents {
  message: (message: Message) => void;
  response: (channelId: string, platform: string, response: AgentResponse) => void;
  error: (error: Error) => void;
  "connector:connected": (name: string) => void;
  "connector:disconnected": (name: string) => void;
}

export class MessageRouter extends EventEmitter<RouterEvents> {
  private connectors = new Map<string, Connector>();
  private messageHandler?: (message: Message) => Promise<AgentResponse>;

  registerConnector(connector: Connector): void {
    this.connectors.set(connector.name, connector);

    connector.onMessage(async (message) => {
      this.emit("message", message);

      if (this.messageHandler) {
        try {
          const response = await this.messageHandler(message);
          await connector.send(message.channelId, response.content);
          this.emit("response", message.channelId, message.platform, response);
        } catch (error) {
          this.emit("error", error as Error);
        }
      }
    });
  }

  onMessage(handler: (message: Message) => Promise<AgentResponse>): void {
    this.messageHandler = handler;
  }

  async sendTo(platform: string, channelId: string, content: string): Promise<void> {
    const connector = this.connectors.get(platform);
    if (!connector) {
      throw new Error(`No connector found for platform: ${platform}`);
    }
    if (!connector.connected) {
      throw new Error(`Connector ${platform} is not connected`);
    }
    await connector.send(channelId, content);
  }

  getConnector(name: string): Connector | undefined {
    return this.connectors.get(name);
  }

  getConnectors(): Map<string, Connector> {
    return this.connectors;
  }

  getConnectedPlatforms(): string[] {
    return [...this.connectors.entries()]
      .filter(([, c]) => c.connected)
      .map(([name]) => name);
  }
}
