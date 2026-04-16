#!/usr/bin/env node

/**
 * Autonoma CLI — thin wrapper that invokes Python from the bundled venv.
 */

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const PYTHON = IS_WIN
  ? path.join(ROOT, ".venv", "Scripts", "python.exe")
  : path.join(ROOT, ".venv", "bin", "python");

if (!fs.existsSync(PYTHON)) {
  console.error(
    "\x1b[31m[autonoma]\x1b[0m Python venv not found. Run: npm rebuild autonoma"
  );
  process.exit(1);
}

const args = ["-m", "autonoma", ...process.argv.slice(2)];

const child = spawn(PYTHON, args, {
  stdio: "inherit",
  cwd: ROOT,
  env: { ...process.env, VIRTUAL_ENV: path.join(ROOT, ".venv") },
});

child.on("error", (err) => {
  console.error(`\x1b[31m[autonoma]\x1b[0m Failed to start: ${err.message}`);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code ?? 0);
});
