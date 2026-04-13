import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import chalk from "chalk";
import inquirer from "inquirer";

export async function initCommand() {
  console.log(chalk.bold("\n  Digital FTE — Project Setup\n"));

  const answers = await inquirer.prompt([
    {
      type: "input",
      name: "name",
      message: "Agent name:",
      default: "My Digital FTE",
    },
    {
      type: "list",
      name: "provider",
      message: "LLM Provider:",
      choices: ["openai", "anthropic", "custom"],
    },
    {
      type: "input",
      name: "apiKey",
      message: "API Key (or leave blank to use .env):",
      default: "",
    },
    {
      type: "checkbox",
      name: "connectors",
      message: "Which platforms do you want to connect?",
      choices: [
        { name: "WhatsApp (QR code scan)", value: "whatsapp" },
        { name: "Telegram (Bot)", value: "telegram" },
        { name: "Discord (Bot)", value: "discord" },
        { name: "Slack (App)", value: "slack" },
        { name: "Web Chat (built-in)", value: "webchat", checked: true },
      ],
    },
    {
      type: "number",
      name: "port",
      message: "Dashboard port:",
      default: 3000,
    },
  ]);

  const config = {
    name: answers.name,
    port: answers.port,
    llm: {
      provider: answers.provider,
      apiKey: answers.apiKey || `\${${answers.provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY"}}`,
      model: answers.provider === "anthropic" ? "claude-sonnet-4-6" : "gpt-4o",
    },
    connectors: answers.connectors.map((type: string) => ({
      type,
      enabled: true,
      credentials: {},
    })),
  };

  const configPath = resolve(process.cwd(), "digital-fte.config.json");
  await writeFile(configPath, JSON.stringify(config, null, 2));

  // Create .env template
  const envLines = [
    `# Digital FTE Configuration`,
    `DFTE_NAME="${answers.name}"`,
    `DFTE_LLM_PROVIDER=${answers.provider}`,
    `DFTE_LLM_API_KEY=your-api-key-here`,
    ``,
  ];

  if (answers.connectors.includes("whatsapp")) {
    envLines.push("DFTE_WHATSAPP_ENABLED=true");
  }
  if (answers.connectors.includes("telegram")) {
    envLines.push("DFTE_TELEGRAM_TOKEN=your-telegram-bot-token");
  }
  if (answers.connectors.includes("discord")) {
    envLines.push("DFTE_DISCORD_TOKEN=your-discord-bot-token");
  }
  if (answers.connectors.includes("slack")) {
    envLines.push("DFTE_SLACK_TOKEN=your-slack-bot-token");
    envLines.push("DFTE_SLACK_SIGNING_SECRET=your-signing-secret");
    envLines.push("DFTE_SLACK_APP_TOKEN=your-app-token");
  }

  const envPath = resolve(process.cwd(), ".env");
  await writeFile(envPath, envLines.join("\n"));

  console.log("");
  console.log(chalk.green("  Project initialized!"));
  console.log("");
  console.log(`  ${chalk.dim("Config:")} ${configPath}`);
  console.log(`  ${chalk.dim("Env:")}    ${envPath}`);
  console.log("");
  console.log(chalk.bold("  Next steps:"));
  console.log(`  1. Edit ${chalk.cyan(".env")} with your API keys`);
  console.log(`  2. Run ${chalk.cyan("npx digital-fte start")}`);
  console.log(`  3. Open ${chalk.cyan(`http://localhost:${answers.port}`)} to access the dashboard`);
  console.log("");
}
