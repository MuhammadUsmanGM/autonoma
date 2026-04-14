import { join } from "node:path";
import { mkdir } from "node:fs/promises";
import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

export interface WhatsAppStatus {
  state: "disconnected" | "connecting" | "qr" | "connected";
  qr: string | null;
  phoneNumber?: string;
  pushName?: string;
}

/**
 * WhatsApp connector using @whiskeysockets/baileys
 *
 * Setup flow:
 * 1. User clicks "Connect WhatsApp" in dashboard
 * 2. QR code appears as base64 data URL — scan with phone
 * 3. Session is saved to disk — survives restarts
 * 4. Auto-reconnects on disconnect (unless logged out)
 */
export class WhatsAppConnector extends BaseConnector {
  name = "whatsapp";
  type = "whatsapp";

  private socket: any = null;
  private status: WhatsAppStatus = { state: "disconnected", qr: null };
  private authDir = "";
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private config: ConnectorConfig | null = null;

  getStatus(): WhatsAppStatus {
    return { ...this.status };
  }

  async connect(config: ConnectorConfig): Promise<void> {
    this.config = config;
    this.authDir = config.credentials.authDir ?? join(process.cwd(), ".autonoma", "auth", "whatsapp");
    await mkdir(this.authDir, { recursive: true });

    await this.createSocket();
  }

  private async createSocket(): Promise<void> {
    const baileys = await import("@whiskeysockets/baileys");
    const makeWASocket = baileys.default;
    const { useMultiFileAuthState, DisconnectReason, makeCacheableSignalKeyStore } = baileys;
    const pino = (await import("pino")).default;

    const logger = pino({ level: "silent" });
    const { state, saveCreds } = await useMultiFileAuthState(this.authDir);

    this.status = { state: "connecting", qr: null };
    this.emitStatusChange();

    this.socket = makeWASocket({
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore(state.keys, logger),
      },
      printQRInTerminal: true,
      logger,
      generateHighQualityLinkPreview: true,
      defaultQueryTimeoutMs: undefined,
    });

    // Save credentials whenever they update
    this.socket.ev.on("creds.update", saveCreds);

    // Connection state management
    this.socket.ev.on("connection.update", async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Convert QR string to base64 data URL for dashboard
        try {
          const QRCode = (await import("qrcode")).default;
          const dataUrl = await QRCode.toDataURL(qr, {
            width: 300,
            margin: 2,
            color: { dark: "#000000", light: "#ffffff" },
          });
          this.status = { state: "qr", qr: dataUrl };
        } catch {
          // Fallback: raw QR string
          this.status = { state: "qr", qr };
        }
        this.emitStatusChange();
        this.emit("qr", this.status.qr);
      }

      if (connection === "close") {
        const statusCode = (lastDisconnect?.error as any)?.output?.statusCode;
        const loggedOut = statusCode === DisconnectReason.loggedOut;

        this.connected = false;
        this.status = { state: "disconnected", qr: null };
        this.emitStatusChange();

        if (loggedOut) {
          // User logged out — clear session and stop
          this.emit("logged-out");
          return;
        }

        // Auto-reconnect with exponential backoff
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 60000);
          this.reconnectAttempts++;
          this.reconnectTimer = setTimeout(() => this.createSocket(), delay);
        }
      }

      if (connection === "open") {
        this.connected = true;
        this.reconnectAttempts = 0;
        const me = this.socket?.user;
        this.status = {
          state: "connected",
          qr: null,
          phoneNumber: me?.id?.split(":")[0] ?? me?.id,
          pushName: me?.name,
        };
        this.emitStatusChange();
        this.emit("connected");
      }
    });

    // Incoming messages
    this.socket.ev.on("messages.upsert", async ({ messages, type }: any) => {
      if (type !== "notify") return;

      for (const msg of messages) {
        // Skip own messages and status broadcasts
        if (msg.key.fromMe) continue;
        if (msg.key.remoteJid === "status@broadcast") continue;

        const text = this.extractText(msg);
        if (!text) continue;

        const message: Message = {
          id: msg.key.id ?? crypto.randomUUID(),
          platform: "whatsapp",
          channelId: msg.key.remoteJid ?? "",
          userId: msg.key.remoteJid ?? "",
          userName: msg.pushName ?? msg.key.remoteJid?.split("@")[0] ?? "Unknown",
          content: text,
          timestamp: new Date((msg.messageTimestamp as number) * 1000),
          metadata: {
            isGroup: msg.key.remoteJid?.endsWith("@g.us") ?? false,
            participant: msg.key.participant,
            messageType: this.getMessageType(msg),
          },
        };
        this.emitMessage(message);
      }
    });
  }

  private extractText(msg: any): string | null {
    const m = msg.message;
    if (!m) return null;

    // Handle different message types
    return (
      m.conversation ||
      m.extendedTextMessage?.text ||
      m.imageMessage?.caption ||
      m.videoMessage?.caption ||
      m.documentMessage?.caption ||
      m.buttonsResponseMessage?.selectedDisplayText ||
      m.listResponseMessage?.title ||
      m.templateButtonReplyMessage?.selectedDisplayText ||
      null
    );
  }

  private getMessageType(msg: any): string {
    const m = msg.message;
    if (!m) return "unknown";
    if (m.conversation || m.extendedTextMessage) return "text";
    if (m.imageMessage) return "image";
    if (m.videoMessage) return "video";
    if (m.audioMessage) return "audio";
    if (m.documentMessage) return "document";
    if (m.stickerMessage) return "sticker";
    if (m.contactMessage) return "contact";
    if (m.locationMessage) return "location";
    return "unknown";
  }

  async disconnect(): Promise<void> {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.end();
      this.socket = null;
    }
    this.connected = false;
    this.status = { state: "disconnected", qr: null };
    this.emitStatusChange();
  }

  async logout(): Promise<void> {
    if (this.socket) {
      await this.socket.logout();
    }
    await this.disconnect();
    // Clean auth dir
    const { rm } = await import("node:fs/promises");
    await rm(this.authDir, { recursive: true, force: true });
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.socket) throw new Error("WhatsApp not connected");
    await this.socket.sendMessage(channelId, { text: content });
  }

  async sendImage(channelId: string, imageUrl: string, caption?: string): Promise<void> {
    if (!this.socket) throw new Error("WhatsApp not connected");
    await this.socket.sendMessage(channelId, {
      image: { url: imageUrl },
      caption,
    });
  }

  async getQRCode(): Promise<string | null> {
    return this.status.qr;
  }

  private emitStatusChange(): void {
    this.emit("status", this.getStatus());
  }
}
