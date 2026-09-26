#!/usr/bin/env node

/**
 * Autonoma CLI — thin wrapper that invokes Python from the bundled venv.
 */

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const VENV = path.join(ROOT, ".venv");
const PYTHON = IS_WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");

const RED = "\x1b[31m";
const YEL = "\x1b[33m";
const CYN = "\x1b[36m";
const OFF = "\x1b[0m";

function findPython() {
  // Same candidate order as scripts/install.js.
  const candidates = IS_WIN
    ? ["python", "python3", "py -3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    const res = spawnSync(cmd, ["--version"], {
      encoding: "utf-8",
      shell: IS_WIN,
    });
    const ver = ((res.stdout || "") + (res.stderr || "")).trim();
    const match = ver.match(/Python (\d+)\.(\d+)\.(\d+)/);
    if (match) {
      const major = parseInt(match[1]);
      const minor = parseInt(match[2]);
      if (major > 3 || (major === 3 && minor >= 11)) return cmd;
    }
  }
  return null;
}

/**
 * Bootstrap the Python venv directly, without going through npm.
 *
 * `npm rebuild` is subject to the same install-scripts policy that may have
 * blocked the original postinstall, so on policy-restricted setups it exits 0
 * while silently skipping scripts/install.js — which left the venv missing
 * forever. Doing the work here (venv + pip install -e .) makes the launcher
 * self-healing regardless of npm's allowScripts configuration.
 */
function tryBootstrapVenv() {
  // Prevent infinite loops: only auto-bootstrap once per invocation.
  if (process.env.AUTONOMA_BOOTSTRAP_ATTEMPTED === "1") return false;

  console.error(
    `${YEL}[autonoma]${OFF} Python venv not found. Setting up Python runtime...`
  );

  const python = findPython();
  if (!python) return false;

  console.error(`${YEL}[autonoma]${OFF} Using ${python} — creating virtual environment...`);
  const venv = spawnSync(python, ["-m", "venv", VENV], {
    stdio: "inherit",
    cwd: ROOT,
    env: { ...process.env, AUTONOMA_BOOTSTRAP_ATTEMPTED: "1" },
    shell: IS_WIN,
  });
  if (venv.status !== 0 || !fs.existsSync(PYTHON)) return false;

  console.error(`${YEL}[autonoma]${OFF} Installing Python dependencies (this can take a minute)...`);
  const pip = spawnSync(PYTHON, ["-m", "pip", "install", "-e", ".", "--quiet"], {
    stdio: "inherit",
    cwd: ROOT,
    shell: IS_WIN,
  });
  return pip.status === 0 && fs.existsSync(PYTHON);
}

function printMissingPythonHelp() {
  console.error("");
  console.error(`${RED}[autonoma]${OFF} Python runtime could not be set up automatically.`);
  console.error("");
  console.error(`${YEL}Autonoma needs Python 3.11+ to run.${OFF}`);
  console.error("");
  console.error("  1. Install Python from:");
  console.error(`     ${CYN}https://www.python.org/downloads/${OFF}`);
  console.error("     (make sure to check 'Add Python to PATH' on Windows)");
  console.error("");
  console.error("  2. Re-run the installer:");
  console.error(`     ${CYN}npm rebuild -g --allow-scripts=autonoma-ai autonoma-ai${OFF}`);
  console.error("");
  console.error(
    "  3. Then run " + CYN + "autonoma" + OFF + " again."
  );
  console.error("");
}

if (!fs.existsSync(PYTHON)) {
  const bootstrapped = tryBootstrapVenv();
  if (!bootstrapped) {
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
