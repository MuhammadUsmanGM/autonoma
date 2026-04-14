import { BaseConnector } from "./base.js";
import type { ConnectorConfig, Message } from "@autonoma/core";

export interface GmailStatus {
  state: "disconnected" | "connecting" | "connected" | "error";
  email?: string;
  error?: string;
}

/**
 * Gmail/Email connector using IMAP + SMTP via nodemailer + imapflow
 *
 * Setup flow:
 * 1. Enable "Less secure apps" OR generate an App Password (recommended)
 *    - Go to myaccount.google.com → Security → 2-Step Verification → App Passwords
 * 2. Enter email and app password in Autonoma dashboard
 * 3. Connector watches inbox via IMAP IDLE and sends via SMTP
 *
 * Also works with any IMAP/SMTP email (Outlook, Yahoo, custom) by setting host/port.
 *
 * Supports: incoming mail watching, sending replies, thread tracking
 */
export class GmailConnector extends BaseConnector {
  name = "gmail";
  type = "gmail";

  private imapClient: any = null;
  private transporter: any = null;
  private status: GmailStatus = { state: "disconnected" };
  private pollInterval: ReturnType<typeof setInterval> | null = null;
  private lastSeenUid = 0;
  private email = "";

  getStatus(): GmailStatus {
    return { ...this.status };
  }

  async connect(config: ConnectorConfig): Promise<void> {
    const email = config.credentials.email;
    const password = config.credentials.password; // App password
    const imapHost = config.credentials.imapHost ?? "imap.gmail.com";
    const imapPort = parseInt(config.credentials.imapPort ?? "993", 10);
    const smtpHost = config.credentials.smtpHost ?? "smtp.gmail.com";
    const smtpPort = parseInt(config.credentials.smtpPort ?? "587", 10);

    if (!email || !password) {
      throw new Error("Email and app password are required. Generate an app password at myaccount.google.com.");
    }

    this.email = email;
    this.status = { state: "connecting", email };
    this.emitStatusChange();

    try {
      // Setup SMTP transport for sending
      const nodemailer = await import("nodemailer");
      this.transporter = nodemailer.createTransport({
        host: smtpHost,
        port: smtpPort,
        secure: smtpPort === 465,
        auth: { user: email, pass: password },
      });

      // Verify SMTP connection
      await this.transporter.verify();

      // Setup IMAP for receiving
      const { ImapFlow } = await import("imapflow");
      this.imapClient = new ImapFlow({
        host: imapHost,
        port: imapPort,
        secure: true,
        auth: { user: email, pass: password },
        logger: false,
      });

      await this.imapClient.connect();

      // Get the current highest UID so we only process new messages
      const lock = await this.imapClient.getMailboxLock("INBOX");
      try {
        const status = this.imapClient.mailbox;
        this.lastSeenUid = status?.uidNext ? status.uidNext - 1 : 0;
      } finally {
        lock.release();
      }

      // Poll for new messages (IMAP IDLE alternative that's more reliable)
      this.pollInterval = setInterval(() => this.checkNewMail(), 10000);

      // Also handle IMAP events if available
      this.imapClient.on("exists", () => this.checkNewMail());

      this.connected = true;
      this.status = { state: "connected", email };
      this.emitStatusChange();
      this.emit("connected");
    } catch (err: any) {
      this.status = { state: "error", email, error: err.message };
      this.emitStatusChange();
      throw err;
    }
  }

  private async checkNewMail(): Promise<void> {
    if (!this.imapClient || !this.connected) return;

    try {
      const lock = await this.imapClient.getMailboxLock("INBOX");
      try {
        // Fetch messages newer than our last seen UID
        const range = `${this.lastSeenUid + 1}:*`;
        for await (const msg of this.imapClient.fetch(range, {
          uid: true,
          envelope: true,
          source: false,
          bodyStructure: true,
        })) {
          if (msg.uid <= this.lastSeenUid) continue;
          this.lastSeenUid = msg.uid;

          const envelope = msg.envelope;
          if (!envelope) continue;

          // Skip messages from ourselves
          const fromAddr = envelope.from?.[0]?.address;
          if (fromAddr === this.email) continue;

          // Get text body
          let bodyText = "";
          try {
            const { content } = await this.imapClient.download(String(msg.seq), "1");
            const chunks: Buffer[] = [];
            for await (const chunk of content) {
              chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
            }
            bodyText = Buffer.concat(chunks).toString("utf-8");
          } catch {
            bodyText = envelope.subject ?? "[No content]";
          }

          const senderName = envelope.from?.[0]?.name ?? fromAddr ?? "Unknown";

          const message: Message = {
            id: String(msg.uid),
            platform: "gmail",
            channelId: fromAddr ?? "unknown",
            userId: fromAddr ?? "unknown",
            userName: senderName,
            content: `Subject: ${envelope.subject ?? "(no subject)"}\n\n${bodyText}`.trim(),
            timestamp: envelope.date ? new Date(envelope.date) : new Date(),
            metadata: {
              subject: envelope.subject,
              from: fromAddr,
              to: envelope.to?.map((t: any) => t.address),
              messageId: envelope.messageId,
              inReplyTo: envelope.inReplyTo,
              messageType: "email",
            },
          };
          this.emitMessage(message);
        }
      } finally {
        lock.release();
      }
    } catch {
      // Silently handle fetch errors — will retry on next poll
    }
  }

  async disconnect(): Promise<void> {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    if (this.imapClient) {
      await this.imapClient.logout().catch(() => {});
      this.imapClient = null;
    }
    this.transporter = null;
    this.connected = false;
    this.status = { state: "disconnected" };
    this.emitStatusChange();
  }

  async send(channelId: string, content: string): Promise<void> {
    if (!this.transporter) throw new Error("Gmail not connected");
    await this.transporter.sendMail({
      from: this.email,
      to: channelId, // channelId = recipient email
      subject: "Re: Autonoma",
      text: content,
    });
  }

  async sendReply(to: string, subject: string, content: string, inReplyTo?: string): Promise<void> {
    if (!this.transporter) throw new Error("Gmail not connected");
    await this.transporter.sendMail({
      from: this.email,
      to,
      subject: subject.startsWith("Re:") ? subject : `Re: ${subject}`,
      text: content,
      inReplyTo,
      references: inReplyTo,
    });
  }

  private emitStatusChange(): void {
    this.emit("status", this.getStatus());
  }
}
