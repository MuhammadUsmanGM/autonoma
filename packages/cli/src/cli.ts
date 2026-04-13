#!/usr/bin/env node
import { Command } from "commander";
import { startCommand } from "./commands/start.js";
import { initCommand } from "./commands/init.js";

const program = new Command();

program
  .name("nexkraft")
  .description("NexKraft — AI agents that work like full-time employees")
  .version("0.1.0");

program
  .command("start")
  .description("Start your NexKraft agent and dashboard")
  .option("-p, --port <port>", "Port to run on", "3000")
  .option("-c, --config <path>", "Path to config file", "nexkraft.config.json")
  .action(startCommand);

program
  .command("init")
  .description("Initialize a new NexKraft project")
  .action(initCommand);

program.parse();
