import express from "express";
import { WebSocketServer, WebSocket } from "ws";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join, dirname } from "node:path";
import type { Server } from "node:http";
import type { Agent } from "../agent/agent.js";
import type { MessageRouter } from "../router/message-router.js";
import type { Message, AgentResponse, ConnectorConfig } from "../types.js";

interface SavedConnectorConfig {
  type: string;
  enabled: boolean;
  credentials: Record<string, string>;
  connectedAt?: string;
}

export function createAPI(agent: Agent, router: MessageRouter, dataDir?: string): express.Express {
  const app = express();
  app.use(express.json());

  const configDir = dataDir ?? join(process.cwd(), ".autonoma");
  const connectorsConfigPath = join(configDir, "connectors.json");

  // --- Helpers for persisting connector configs ---
  async function loadSavedConfigs(): Promise<Record<string, SavedConnectorConfig>> {
    try {
      const raw = await readFile(connectorsConfigPath, "utf-8");
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  async function saveConnectorConfig(name: string, config: SavedConnectorConfig): Promise<void> {
    const all = await loadSavedConfigs();
    all[name] = config;
    await mkdir(dirname(connectorsConfigPath), { recursive: true });
    await writeFile(connectorsConfigPath, JSON.stringify(all, null, 2));
  }

  async function removeConnectorConfig(name: string): Promise<void> {
    const all = await loadSavedConfigs();
    delete all[name];
    await writeFile(connectorsConfigPath, JSON.stringify(all, null, 2));
  }

  // CORS for local dashboard
  app.use((_req, res, next) => {
    res.header("Access-Control-Allow-Origin", "*");
    res.header("Access-Control-Allow-Headers", "Content-Type");
    res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
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

  // ====== CONNECTOR ENDPOINTS ======

  // List all connectors with status
  app.get("/api/connectors", (_req, res) => {
    const connectors = [...router.getConnectors().entries()].map(([name, c]) => {
      const statusFn = (c as any).getStatus;
      const status = statusFn ? statusFn.call(c) : { state: c.connected ? "connected" : "disconnected" };
      return {
        name,
        type: c.type,
        connected: c.connected,
        status,
      };
    });
    res.json({ connectors });
  });

  // Get status of a single connector
  app.get("/api/connectors/:name/status", (req, res) => {
    const connector = router.getConnector(req.params.name);
    if (!connector) {
      res.status(404).json({ error: "Connector not found" });
      return;
    }
    const statusFn = (connector as any).getStatus;
    const status = statusFn ? statusFn.call(connector) : { state: connector.connected ? "connected" : "disconnected" };
    res.json({ name: req.params.name, type: connector.type, connected: connector.connected, status });
  });

  // Connect a connector at runtime (the main setup endpoint)
  app.post("/api/connectors/:name/connect", async (req, res) => {
    const { name } = req.params;
    const { credentials } = req.body as { credentials: Record<string, string> };

    const connector = router.getConnector(name);
    if (!connector) {
      res.status(404).json({ error: `Connector "${name}" not registered. Available: ${[...router.getConnectors().keys()].join(", ")}` });
      return;
    }

    if (connector.connected) {
      res.status(400).json({ error: "Already connected. Disconnect first." });
      return;
    }

    const config: ConnectorConfig = {
      type: connector.type,
      enabled: true,
      credentials: credentials ?? {},
    };

    try {
      await connector.connect(config);

      // Persist so it auto-connects on restart
      await saveConnectorConfig(name, {
        ...config,
        connectedAt: new Date().toISOString(),
      });

      res.json({ ok: true, message: `${name} connected successfully` });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // Disconnect a connector
  app.post("/api/connectors/:name/disconnect", async (req, res) => {
    const connector = router.getConnector(req.params.name);
    if (!connector) {
      res.status(404).json({ error: "Connector not found" });
      return;
    }

    try {
      await connector.disconnect();
      await removeConnectorConfig(req.params.name);
      res.json({ ok: true, message: `${req.params.name} disconnected` });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // Get QR code (WhatsApp)
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

  // WhatsApp-specific: start connection (no credentials needed, just QR scan)
  app.post("/api/connectors/whatsapp/start", async (_req, res) => {
    const connector = router.getConnector("whatsapp");
    if (!connector) {
      res.status(404).json({ error: "WhatsApp connector not registered" });
      return;
    }
    if (connector.connected) {
      res.json({ ok: true, message: "Already connected" });
      return;
    }

    try {
      await connector.connect({
        type: "whatsapp",
        enabled: true,
        credentials: { authDir: join(configDir, "auth", "whatsapp") },
      });
      res.json({ ok: true, message: "WhatsApp connecting — check /api/connectors/whatsapp/qr for QR code" });
    } catch (err: any) {
      res.status(500).json({ error: err.message });
    }
  });

  // Get saved connector configs (for dashboard to show what was previously set up)
  app.get("/api/connectors/saved", async (_req, res) => {
    const saved = await loadSavedConfigs();
    // Strip credentials for security — just return types and status
    const result = Object.entries(saved).map(([name, config]) => ({
      name,
      type: config.type,
      enabled: config.enabled,
      connectedAt: config.connectedAt,
      hasCredentials: Object.keys(config.credentials).length > 0,
    }));
    res.json({ saved: result });
  });

  // ====== CONVERSATION ENDPOINTS ======

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

  // ====== CHAT ENDPOINT ======

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

  // ====== MEMORY ENDPOINTS ======

  // Key-value memory
  app.get("/api/memory/kv", async (_req, res) => {
    // For backwards compat, list all kv entries
    const entries = await (agent.memory as any).getFacts?.() ?? [];
    res.json({ entries });
  });

  app.post("/api/memory/kv", async (req, res) => {
    const { key, value } = req.body as { key: string; value: string };
    await agent.memory.set(key, value);
    res.json({ ok: true });
  });

  app.delete("/api/memory/kv/:key", async (req, res) => {
    await agent.memory.delete(req.params.key);
    res.json({ ok: true });
  });

  // User profiles
  app.get("/api/memory/users", async (_req, res) => {
    const users = await (agent.memory as any).listUsers?.() ?? [];
    res.json({ users });
  });

  app.get("/api/memory/users/:platform/:userId", async (req, res) => {
    const user = await agent.memory.getUser(req.params.platform, req.params.userId);
    if (!user) {
      res.status(404).json({ error: "User not found" });
      return;
    }
    res.json({ user });
  });

  // Facts
  app.get("/api/memory/facts", async (req, res) => {
    const query = req.query.q as string | undefined;
    const facts = await (agent.memory as any).getFacts?.(query) ?? [];
    res.json({ facts });
  });

  app.post("/api/memory/facts", async (req, res) => {
    const { content, tags } = req.body as { content: string; tags?: string[] };
    const fact = await (agent.memory as any).addFact?.({
      content,
      source: "dashboard",
      tags: tags ?? [],
    });
    res.json({ fact });
  });

  app.delete("/api/memory/facts/:id", async (req, res) => {
    await (agent.memory as any).deleteFact?.(req.params.id);
    res.json({ ok: true });
  });

  // Memory stats
  app.get("/api/memory/stats", async (_req, res) => {
    const users = await (agent.memory as any).listUsers?.() ?? [];
    const facts = await (agent.memory as any).getFacts?.() ?? [];
    const conversations = agent.getConversations();
    const totalMessages = conversations.reduce((sum, c) => sum + c.messages.length, 0);

    res.json({
      users: users.length,
      facts: facts.length,
      conversations: conversations.length,
      totalMessages,
    });
  });

  return app;
}

export function createWebSocketServer(
  server: Server,
  agent: Agent,
  router: MessageRouter
): WebSocketServer {
  const wss = new WebSocketServer({ server, path: "/ws" });

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

  // Broadcast connector status changes
  for (const [name, connector] of router.getConnectors()) {
    (connector as any).on?.("status", (status: unknown) => {
      broadcast("connector:status", { name, status });
    });
  }

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
