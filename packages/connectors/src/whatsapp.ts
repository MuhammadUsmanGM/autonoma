import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@nexkraft/core";

/**
 * WhatsApp connector using @whiskeysockets/baileys
 * Connects via QR code scanning — just like WhatsApp Web
 */
export class WhatsAppConnector extends BaseConnector {
  name = "whatsapp";
  type = "whatsapp";

  private socket: any = null;
  private currentQR: string | null = null;
  private authDir: string = ".nexkraft/auth/whatsapp";

  async connect(config: ConnectorConfig): Promise<void> {
    // Dynamic import to avoid issues if baileys isn't installed
    const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } =
      await import("@whiskeysockets/baileys");

    this.authDir = config.credentials.authDir ?? this.authDir;

    const { state, saveCreds } = await useMultiFileAuthState(this.authDir);

    this.socket = makeWASocket({
      auth: state,
      printQRInTerminal: true,
    });

    this.socket.ev.on("creds.update", saveCreds);

    this.socket.ev.on("connection.update", (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        this.currentQR = qr;
        this.emit("qr", qr);
      }

      if (connection === "close") {
        const statusCode = (lastDisconnect?.error as any)?.output?.statusCode;
        if (statusCode !== DisconnectReason.loggedOut) {
          // Reconnect if not logged out
          this.connect(config);
        } else {
          this.connected = false;
          this.emit("disconnected");
        }
      } else if (connection === "open") {
        this.connected = true;
        this.currentQR = null;
        this.emit("connected");
      }
    });

    this.socket.ev.on("messages.upsert", (m: any) => {
      for (const msg of m.messages) {
        if (msg.key.fromMe) continue;
        const text =
          msg.message?.conversation ||
          msg.message?.extendedTextMessage?.text;

        if (text) {
          const message: Message = {
            id: msg.key.id ?? crypto.randomUUID(),
            platform: "whatsapp",
            channelId: msg.key.remoteJid ?? "",
            userId: msg.key.remoteJid ?? "",
            userName: msg.pushName ?? "Unknown",
            content: text,
            timestamp: new Date((msg.messageTimestamp as number) * 1000),
          };
          this.emitMessage(message);
        }
      }
    });
  }

  async disconnect(): Promise<void> {
    if (this.socket) {
      this.socket.end();
      this.socket = null;
    }
    this.connected = false;
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.socket) throw new Error("WhatsApp not connected");
    await this.socket.sendMessage(channelId, { text: content });
  }

  async getQRCode(): Promise<string | null> {
    return this.currentQR;
  }
}
