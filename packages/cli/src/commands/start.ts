import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import chalk from "chalk";
import ora from "ora";
import { config as loadEnv } from "dotenv";
import { NexKraft } from "@nexkraft/core";
import type { NexKraftConfig } from "@nexkraft/core";
import {
  WhatsAppConnector,
  TelegramConnector,
  DiscordConnector,
  SlackConnector,
  WebChatConnector,
} from "@nexkraft/connectors";

export async function startCommand(options: { port: string; config: string }) {
  loadEnv();

  const spinner = ora("Starting NexKraft...").start();

  try {
    // Load config
    const configPath = resolve(process.cwd(), options.config);
    let config: NexKraftConfig;

    try {
      const raw = await readFile(configPath, "utf-8");
      config = JSON.parse(raw);
    } catch {
      // Use defaults + env vars if no config file
      config = {
        name: process.env.NK_NAME ?? "My NexKraft Agent",
        port: parseInt(options.port, 10),
        llm: {
          provider: process.env.NK_LLM_PROVIDER ?? "openai",
          apiKey: process.env.NK_LLM_API_KEY ?? process.env.OPENAI_API_KEY ?? "",
          model: process.env.NK_LLM_MODEL,
        },
        connectors: [],
      };
    }

    config.port = parseInt(options.port, 10) || config.port || 3000;

    if (!config.llm.apiKey) {
      spinner.fail(
        "No LLM API key found. Set NK_LLM_API_KEY or OPENAI_API_KEY in .env, or add it to your config file."
      );
      process.exit(1);
    }

    // Create instance
    const nk = new NexKraft(config);

    // Register available connectors
    nk.registerConnector(new WebChatConnector());

    // Auto-register connectors based on env vars
    if (process.env.NK_WHATSAPP_ENABLED === "true") {
      nk.registerConnector(new WhatsAppConnector());
    }
    if (process.env.NK_TELEGRAM_TOKEN) {
      nk.registerConnector(new TelegramConnector());
    }
    if (process.env.NK_DISCORD_TOKEN) {
      nk.registerConnector(new DiscordConnector());
    }
    if (process.env.NK_SLACK_TOKEN && process.env.NK_SLACK_SIGNING_SECRET) {
      nk.registerConnector(new SlackConnector());
    }

    // Start
    await nk.start();

    spinner.succeed(chalk.green("NexKraft is running!"));
    console.log("");
    console.log(chalk.bold("  Dashboard: ") + chalk.cyan(`http://localhost:${config.port}`));
    console.log(chalk.bold("  API:       ") + chalk.cyan(`http://localhost:${config.port}/api`));
    console.log(chalk.bold("  WebSocket: ") + chalk.cyan(`ws://localhost:${config.port}/ws`));
    console.log("");
    console.log(chalk.dim("  Press Ctrl+C to stop"));

    // Handle shutdown
    process.on("SIGINT", async () => {
      console.log("\n" + chalk.yellow("Shutting down..."));
      await nk.stop();
      process.exit(0);
    });
  } catch (error) {
    spinner.fail(chalk.red(`Failed to start: ${(error as Error).message}`));
    process.exit(1);
  }
}
