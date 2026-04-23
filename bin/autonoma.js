#!/usr/bin/env node

/**
 * Autonoma CLI — thin wrapper that invokes Python from the bundled venv.
 */

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const PYTHON = IS_WIN
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python");

const RED = "\x1b[31m";
const YEL = "\x1b[33m";
const CYN = "\x1b[36m";
const OFF = "\x1b[0m";

function printMissingPythonHelp() {
  console.error("");
  console.error(`${RED}[autonoma]${OFF} Python runtime is not set up.`);
  console.error("");
  console.error(`${YEL}Autonoma needs Python 3.11+ to run.${OFF}`);
  console.error("");
  console.error("  1. Install Python from:");
  console.error(`     ${CYN}https://www.python.org/downloads/${OFF}`);
  console.error("     (make sure to check 'Add Python to PATH' on Windows)");
  console.error("");
  console.error("  2. Re-run the installer:");
  console.error(`     ${CYN}npm rebuild -g autonoma-ai${OFF}`);
  console.error("");
  console.error(
    "  3. Then run " + CYN + "autonoma" + OFF + " again."
  );
  console.error("");
}

function tryAutoRebuild() {
  // Prevent infinite loops: only auto-rebuild once per invocation.
  if (process.env.AUTONOMA_REBUILD_ATTEMPTED === "1") return false;

  console.error(
    `${YEL}[autonoma]${OFF} Python venv not found. Attempting npm rebuild...`
  );
  const result = spawnSync("npm", ["rebuild", "autonoma-ai"], {
    stdio: "inherit",
    cwd: ROOT,
    env: { ...process.env, AUTONOMA_REBUILD_ATTEMPTED: "1" },
    shell: IS_WIN,
  });
  return result.status === 0 && fs.existsSync(PYTHON);
}

if (!fs.existsSync(PYTHON)) {
  const rebuilt = tryAutoRebuild();
  if (!rebuilt) {
    printMissingPythonHelp();
    process.exit(1);
  }
}

const args = ["-m", "autonoma", ...process.argv.slice(2)];

const child = spawn(PYTHON, args, {
  stdio: "inherit",
  cwd: ROOT,
  env: { ...process.env, VIRTUAL_ENV: path.join(ROOT, ".venv") },
});

child.on("error", (err) => {
  console.error(`${RED}[autonoma]${OFF} Failed to start: ${err.message}`);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
