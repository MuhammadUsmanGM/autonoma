import { createServer } from "node:http";
import { join } from "node:path";
import { mkdir } from "node:fs/promises";
import pino from "pino";
import { Agent } from "./agent/agent.js";
import { MessageRouter } from "./router/message-router.js";
import { createLLMProvider } from "./llm/index.js";
import { createAPI, createWebSocketServer } from "./server/api.js";
import type { NexKraftConfig, Connector, Skill } from "./types.js";

export class NexKraft {
  private agent: Agent;
  private router: MessageRouter;
  private config: NexKraftConfig;
  private logger: pino.Logger;
  private server?: ReturnType<typeof createServer>;

  constructor(config: NexKraftConfig) {
    this.config = config;
    this.logger = pino({ name: "nexkraft" });

    const llm = createLLMProvider({
      provider: config.llm.provider,
      apiKey: config.llm.apiKey,
      model: config.llm.model,
    });

    const dataDir = config.dataDir ?? join(process.cwd(), ".nexkraft");

    this.agent = new Agent({
      name: config.name,
      llm,
      dataDir,
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
    const dataDir = this.config.dataDir ?? join(process.cwd(), ".nexkraft");
    await mkdir(dataDir, { recursive: true });

    // Connect all enabled connectors
    for (const connConfig of this.config.connectors) {
      if (!connConfig.enabled) continue;
      const connector = this.router.getConnector(connConfig.type);
      if (connector) {
        try {
          await connector.connect(connConfig);
          this.logger.info({ connector: connConfig.type }, "Connector connected");
        } catch (err) {
          this.logger.error({ connector: connConfig.type, err }, "Failed to connect");
        }
      }
    }

    // Start HTTP + WebSocket server
    const app = createAPI(this.agent, this.router);
    this.server = createServer(app);
    createWebSocketServer(this.server, this.agent, this.router);

    const port = this.config.port ?? 3000;
    this.server.listen(port, () => {
      this.logger.info(`NexKraft "${this.config.name}" running at http://localhost:${port}`);
      this.logger.info(`Dashboard: http://localhost:${port}`);
      this.logger.info(`API: http://localhost:${port}/api`);
      this.logger.info(`WebSocket: ws://localhost:${port}/ws`);
    });
  }

  async stop(): Promise<void> {
    if (this.server) {
      this.server.close();
    }
    this.logger.info("NexKraft stopped");
  }

  getAgent(): Agent {
    return this.agent;
  }

  getRouter(): MessageRouter {
    return this.router;
  }
}
