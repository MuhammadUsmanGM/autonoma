#!/usr/bin/env node

/**
 * Autonoma — postinstall script
 * Creates a Python virtual environment and installs dependencies.
 */

const { execSync, execFileSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const VENV = path.join(ROOT, ".venv");
const PIP = IS_WIN
  ? path.join(VENV, "Scripts", "pip.exe")
  : path.join(VENV, "bin", "pip");
const PYTHON_VENV = IS_WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");

const MIN_PYTHON = [3, 11];

function log(msg) {
  console.log(`\x1b[33m[autonoma]\x1b[0m ${msg}`);
}

function warn(msg) {
  console.warn(`\x1b[33m[autonoma]\x1b[0m ${msg}`);
}

function error(msg) {
  console.error(`\x1b[31m[autonoma]\x1b[0m ${msg}`);
}

function bail(msg) {
  console.log("");
  warn(msg);
  warn("Autonoma is installed, but the Python runtime was not set up.");
  warn("Finish setup manually when ready:");
  warn("  1. Install Python " + MIN_PYTHON.join(".") + "+ from https://www.python.org/downloads/");
  warn("  2. cd " + ROOT);
  warn("  3. python -m venv .venv");
  warn(
    "  4. " +
      (IS_WIN ? ".venv\\Scripts\\pip" : ".venv/bin/pip") +
      " install -e ."
  );
  warn("Or run: npm rebuild autonoma-ai");
  console.log("");
  process.exit(0);
}

// --- Find Python ---

function findPython() {
  const candidates = IS_WIN
    ? ["python", "python3", "py -3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { encoding: "utf-8" }).trim();
      const match = ver.match(/Python (\d+)\.(\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1]);
        const minor = parseInt(match[2]);
        if (major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])) {
          log(`Found ${ver} (${cmd})`);
          return cmd;
        }
        log(`${ver} found but need >= ${MIN_PYTHON.join(".")}, skipping...`);
      }
    } catch {
      // not found, try next
    }
  }
  return null;
}

// --- Main ---

function main() {
  // Skip postinstall in CI and when explicitly opted out. npm install should
  // never fail just because Python isn't on the box.
  if (process.env.AUTONOMA_SKIP_POSTINSTALL === "1") {
    log("AUTONOMA_SKIP_POSTINSTALL=1 set, skipping Python setup.");
    return;
  }
  if (process.env.CI && !process.env.AUTONOMA_FORCE_POSTINSTALL) {
    log("CI detected, skipping Python setup (set AUTONOMA_FORCE_POSTINSTALL=1 to run).");
    return;
  }

  log("Setting up Autonoma...\n");

  // 1. Find Python
  const python = findPython();
  if (!python) {
    return bail(`Python ${MIN_PYTHON.join(".")}+ not found on PATH.`);
  }

  // 2. Create venv (skip if already exists)
  if (fs.existsSync(PYTHON_VENV)) {
    log("Virtual environment already exists, skipping creation.");
  } else {
    log("Creating virtual environment...");
    try {
      execSync(`${python} -m venv "${VENV}"`, { stdio: "inherit", cwd: ROOT });
    } catch (e) {
      return bail("Failed to create virtual environment.");
    }
  }

  // 3. Upgrade pip
  log("Upgrading pip...");
  try {
    execSync(`"${PYTHON_VENV}" -m pip install --upgrade pip --quiet`, {
      stdio: "inherit",
      cwd: ROOT,
    });
  } catch {
    // non-fatal, continue
  }

  // 4. Install Python dependencies
  log("Installing Python dependencies...");
  try {
    execSync(`"${PIP}" install -e . --quiet`, {
      stdio: "inherit",
      cwd: ROOT,
    });
  } catch (e) {
    return bail("Failed to install Python dependencies.");
  }

  // 5. Done
  console.log("");
  log("\x1b[32mAutonoma installed successfully!\x1b[0m\n");
  log("Next steps:");
  log("  1. cp .env.example .env");
  log("  2. Edit .env — add your API key");
  log("  3. Run: autonoma\n");
}

try {
  main();
} catch (e) {
  error("Unexpected postinstall error: " + (e && e.message ? e.message : e));
  warn("Continuing without Python setup. Run `npm rebuild autonoma-ai` after installing Python.");
  process.exit(0);
}
