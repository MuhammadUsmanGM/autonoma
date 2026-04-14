import { createServer } from "node:http";
import { join } from "node:path";
import { mkdir, readFile } from "node:fs/promises";
import pino from "pino";
import { Agent } from "./agent/agent.js";
import { MessageRouter } from "./router/message-router.js";
import { createLLMProvider } from "./llm/index.js";
import { createAPI, createWebSocketServer } from "./server/api.js";
import type { AutonomaConfig, Connector, ConnectorConfig, Skill } from "./types.js";

export class Autonoma {
  private agent: Agent;
  private router: MessageRouter;
  private config: AutonomaConfig;
  private logger: pino.Logger;
  private server?: ReturnType<typeof createServer>;
  private dataDir: string;

  constructor(config: AutonomaConfig) {
    this.config = config;
    this.dataDir = config.dataDir ?? join(process.cwd(), ".autonoma");
    this.logger = pino({ name: "autonoma" });

    const llm = createLLMProvider({
      provider: config.llm.provider,
      apiKey: config.llm.apiKey,
      model: config.llm.model,
    });

    this.agent = new Agent({
      name: config.name,
      llm,
      dataDir: this.dataDir,
      systemPrompt: config.systemPrompt,
    });

    this.router = new MessageRouter();

    // Wire up router → agent
    this.router.onMessage(async (message) => {
      this.logger.info({ platform: message.platform, user: message.userName }, "Incoming message");
      return this.agent.handleMessage(message);
    });
  }

  registerConnector(connector: Connector): void {
    this.router.registerConnector(connector);
    this.logger.info({ connector: connector.name }, "Connector registered");
  }

  registerSkill(skill: Skill): void {
    this.agent.registerSkill(skill);
    this.logger.info({ skill: skill.name }, "Skill registered");
  }

  async start(): Promise<void> {
    await mkdir(this.dataDir, { recursive: true });

    // 1. Connect connectors from config file
    for (const connConfig of this.config.connectors) {
      if (!connConfig.enabled) continue;
      const connector = this.router.getConnector(connConfig.type);
      if (connector) {
        await this.connectSafe(connector, connConfig);
      }
    }

    // 2. Auto-reconnect previously saved connectors (from dashboard setup)
    await this.restoreSavedConnectors();

    // Start HTTP + WebSocket server
    const app = createAPI(this.agent, this.router, this.dataDir);
    this.server = createServer(app);
    createWebSocketServer(this.server, this.agent, this.router);

    const port = this.config.port ?? 3000;
    this.server.listen(port, () => {
      this.logger.info(`Autonoma "${this.config.name}" running at http://localhost:${port}`);
      this.logger.info(`Dashboard: http://localhost:${port}`);
      this.logger.info(`API: http://localhost:${port}/api`);
      this.logger.info(`WebSocket: ws://localhost:${port}/ws`);
    });
  }

  private async restoreSavedConnectors(): Promise<void> {
    try {
      const configPath = join(this.dataDir, "connectors.json");
      const raw = await readFile(configPath, "utf-8");
      const saved = JSON.parse(raw) as Record<string, { type: string; enabled: boolean; credentials: Record<string, string> }>;

      for (const [name, config] of Object.entries(saved)) {
        if (!config.enabled) continue;
        const connector = this.router.getConnector(name);
        if (connector && !connector.connected) {
          await this.connectSafe(connector, config);
        }
      }
    } catch {
      // No saved config or parse error — that's fine
    }
  }

  private async connectSafe(connector: Connector, config: ConnectorConfig): Promise<void> {
    try {
      await connector.connect(config);
      this.logger.info({ connector: connector.name }, "Connector connected");
    } catch (err) {
      this.logger.error({ connector: connector.name, err }, "Failed to connect");
    }
  }

  async stop(): Promise<void> {
    // Disconnect all connectors gracefully
    for (const [name, connector] of this.router.getConnectors()) {
      if (connector.connected) {
        try {
          await connector.disconnect();
          this.logger.info({ connector: name }, "Connector disconnected");
        } catch (err) {
          this.logger.error({ connector: name, err }, "Error disconnecting");
        }
      }
    }
    if (this.server) {
      this.server.close();
    }
    this.logger.info("Autonoma stopped");
  }

  getAgent(): Agent {
    return this.agent;
  }

  getRouter(): MessageRouter {
    return this.router;
  }
}
