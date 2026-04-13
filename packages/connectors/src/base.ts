import EventEmitter from "eventemitter3";
import type { Connector, ConnectorConfig, Message } from "@nexkraft/core";

export abstract class BaseConnector extends EventEmitter implements Connector {
  abstract name: string;
  abstract type: string;
  connected = false;

  protected messageHandlers: Array<(message: Message) => void> = [];

  abstract connect(config: ConnectorConfig): Promise<void>;
  abstract disconnect(): Promise<void>;
  abstract send(channelId: string, content: string): Promise<void>;

  onMessage(handler: (message: Message) => void): void {
    this.messageHandlers.push(handler);
  }

  protected emitMessage(message: Message): void {
    for (const handler of this.messageHandlers) {
      handler(message);
    }
  }

  async getQRCode(): Promise<string | null> {
    return null;
  }
}
