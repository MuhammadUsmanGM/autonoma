import express from "express";
import { WebSocketServer, WebSocket } from "ws";
import type { Server } from "node:http";
import type { Agent } from "../agent/agent.js";
import type { MessageRouter } from "../router/message-router.js";
import type { Message, AgentResponse } from "../types.js";

export function createAPI(agent: Agent, router: MessageRouter): express.Express {
  const app = express();
  app.use(express.json());

  // CORS for local dashboard
  app.use((_req, res, next) => {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "Content-Type");
    res.header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
    if (_req.method === "OPTIONS") {
      res.sendStatus(200);
      return;
    }
    next();
  });

  // Health check
  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", name: agent.name, uptime: process.uptime() });
  });

  // Get agent info
  app.get("/api/agent", (_req, res) => {
    res.json({
      id: agent.id,
      name: agent.name,
      skills: agent.skills.map((s) => ({
        name: s.name,
        description: s.description,
      })),
    });
  });

  // List connectors
  app.get("/api/connectors", (_req, res) => {
    const connectors = [...router.getConnectors().entries()].map(
      ([name, c]) => ({
        name,
        type: c.type,
        connected: c.connected,
      })
    );
    res.json({ connectors });
  });

  // Get QR code for a connector (e.g., WhatsApp)
  app.get("/api/connectors/:name/qr", async (req, res) => {
    const connector = router.getConnector(req.params.name);
    if (!connector) {
      res.status(404).json({ error: "Connector not found" });
      return;
    }
    if (!connector.getQRCode) {
      res.status(400).json({ error: "Connector does not support QR codes" });
      return;
    }
    const qr = await connector.getQRCode();
    res.json({ qr });
  });

  // List conversations
  app.get("/api/conversations", (_req, res) => {
    const conversations = agent.getConversations().map((c) => ({
      id: c.id,
      platform: c.platform,
      channelId: c.channelId,
      messageCount: c.messages.length,
      lastMessage: c.messages[c.messages.length - 1],
      updatedAt: c.updatedAt,
    }));
    res.json({ conversations });
  });

  // Send a message via web chat
  app.post("/api/chat", async (req, res) => {
    const { content, channelId = "web-default" } = req.body as {
      content: string;
      channelId?: string;
    };

    if (!content) {
      res.status(400).json({ error: "content is required" });
      return;
    }

    const message: Message = {
      id: crypto.randomUUID(),
      platform: "webchat",
      channelId,
      userId: "web-user",
      userName: "Web User",
      content,
      timestamp: new Date(),
    };

    const response = await agent.handleMessage(message);
    res.json({ response });
  });

  // Memory endpoints
  app.get("/api/memory", async (_req, res) => {
    const entries = await agent.memory.list();
    res.json({ entries });
  });

  app.post("/api/memory", async (req, res) => {
    const { key, value } = req.body as { key: string; value: string };
    await agent.memory.set(key, value);
    res.json({ ok: true });
  });

  app.delete("/api/memory/:key", async (req, res) => {
    await agent.memory.delete(req.params.key);
    res.json({ ok: true });
  });

  return app;
}

export function createWebSocketServer(
  server: Server,
  agent: Agent,
  router: MessageRouter
): WebSocketServer {
  const wss = new WebSocketServer({ server, path: "/ws" });

  // Broadcast events to all connected dashboard clients
  function broadcast(event: string, data: unknown): void {
    const payload = JSON.stringify({ event, data });
    for (const client of wss.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(payload);
      }
    }
  }

  router.on("message", (message: Message) => {
    broadcast("message", message);
  });

  router.on("response", (channelId: string, platform: string, response: AgentResponse) => {
    broadcast("response", { channelId, platform, ...response });
  });

  router.on("connector:connected", (name: string) => {
    broadcast("connector:connected", { name });
  });

  router.on("connector:disconnected", (name: string) => {
    broadcast("connector:disconnected", { name });
  });

  // Handle web chat messages over WebSocket
  wss.on("connection", (ws) => {
    ws.on("message", async (raw) => {
      try {
        const data = JSON.parse(raw.toString()) as { type: string; content?: string; channelId?: string };

        if (data.type === "chat" && data.content) {
          const message: Message = {
            id: crypto.randomUUID(),
            platform: "webchat",
            channelId: data.channelId ?? "ws-default",
            userId: "web-user",
            userName: "Web User",
            content: data.content,
            timestamp: new Date(),
          };

          const response = await agent.handleMessage(message);
          ws.send(JSON.stringify({ event: "response", data: response }));
        }
      } catch {
        ws.send(JSON.stringify({ event: "error", data: "Invalid message format" }));
      }
    });
  });

  return wss;
}
