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

function error(msg) {
  console.error(`\x1b[31m[autonoma]\x1b[0m ${msg}`);
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
  log("Setting up Autonoma...\n");

  // 1. Find Python
  const python = findPython();
  if (!python) {
    error(
      `Python ${MIN_PYTHON.join(".")}+ is required but not found.\n` +
      `Install it from https://www.python.org/downloads/`
    );
    process.exit(1);
  }

  // 2. Create venv (skip if already exists)
  if (fs.existsSync(PYTHON_VENV)) {
    log("Virtual environment already exists, skipping creation.");
  } else {
    log("Creating virtual environment...");
    try {
      execSync(`${python} -m venv "${VENV}"`, { stdio: "inherit", cwd: ROOT });
    } catch (e) {
      error("Failed to create virtual environment.");
      error("Try: pip install virtualenv && python -m venv .venv");
      process.exit(1);
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
    error("Failed to install dependencies.");
    error("Try manually: cd " + ROOT + " && .venv/bin/pip install -e .");
    process.exit(1);
  }

  // 5. Done
  console.log("");
  log("\x1b[32mAutonoma installed successfully!\x1b[0m\n");
  log("Next steps:");
  log("  1. cp .env.example .env");
  log("  2. Edit .env — add your API key");
  log("  3. Run: autonoma\n");
}

main();
