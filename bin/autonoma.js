#!/usr/bin/env node

/**
 * Autonoma CLI — thin wrapper that invokes Python from the bundled venv.
 * Automatically prompts to install Python 3.12 if not already present on the system.
 */

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");
const https = require("https");
const readline = require("readline");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const IS_LINUX = process.platform === "linux";

const VENV = path.join(ROOT, ".venv");
const PYTHON = IS_WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");

const RED = "\x1b[31m";
const GRN = "\x1b[32m";
const YEL = "\x1b[33m";
const CYN = "\x1b[36m";
const BLD = "\x1b[1m";
const OFF = "\x1b[0m";

const STANDALONE_ROOT = path.join(os.homedir(), ".autonoma", "runtime");
const STANDALONE_DIR = path.join(STANDALONE_ROOT, "python");
const STANDALONE_PYTHON = IS_WIN
  ? path.join(STANDALONE_DIR, "python.exe")
  : path.join(STANDALONE_DIR, "bin", "python3");

function checkPythonExecutable(cmd) {
  try {
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
  } catch {
    // ignore
  }
  return null;
}

function findPython() {
  // 1. Check if standalone runtime was already installed
  if (fs.existsSync(STANDALONE_PYTHON)) {
    const valid = checkPythonExecutable(STANDALONE_PYTHON);
    if (valid) return valid;
  }
  const altStandalone = path.join(STANDALONE_ROOT, "python", "python", IS_WIN ? "python.exe" : "bin/python3");
  if (fs.existsSync(altStandalone)) {
    const valid = checkPythonExecutable(altStandalone);
    if (valid) return valid;
  }

  // 2. Standard PATH candidates
  const candidates = IS_WIN
    ? ["python", "python3", "py -3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    const valid = checkPythonExecutable(cmd);
    if (valid) return valid;
  }

  // 3. Common OS-specific installation paths
  const extraPaths = [];
  if (IS_WIN) {
    const localApp = process.env.LOCALAPPDATA || "";
    const progFiles = process.env.ProgramFiles || "C:\\Program Files";
    extraPaths.push(
      path.join(localApp, "Programs", "Python", "Python312", "python.exe"),
      path.join(localApp, "Programs", "Python", "Python311", "python.exe"),
      path.join(progFiles, "Python312", "python.exe"),
      path.join(progFiles, "Python311", "python.exe")
    );
  } else if (IS_MAC) {
    extraPaths.push(
      "/opt/homebrew/bin/python3.12",
      "/opt/homebrew/bin/python3.11",
      "/usr/local/bin/python3.12",
      "/usr/local/bin/python3.11"
    );
  } else if (IS_LINUX) {
    extraPaths.push(
      "/usr/bin/python3.12",
      "/usr/bin/python3.11",
      "/usr/local/bin/python3.12",
      "/usr/local/bin/python3.11"
    );
  }

  for (const p of extraPaths) {
    if (fs.existsSync(p)) {
      const valid = checkPythonExecutable(p);
      if (valid) return valid;
    }
  }

  return null;
}

/**
 * Bootstrap the Python venv directly, without going through npm.
 */
function tryBootstrapVenv() {
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

function promptUser(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function downloadFile(url, destPath) {
  return new Promise((resolve, reject) => {
    function get(currentUrl, hops = 0) {
      if (hops > 5) return reject(new Error("Too many redirects"));
      https
        .get(currentUrl, { headers: { "User-Agent": "autonoma-installer" } }, (res) => {
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            return get(res.headers.location, hops + 1);
          }
          if (res.statusCode !== 200) {
            return reject(new Error(`Download failed with status HTTP ${res.statusCode}`));
          }
          const totalBytes = parseInt(res.headers["content-length"] || "0", 10);
          let receivedBytes = 0;
          let lastLoggedMb = 0;

          const fileStream = fs.createWriteStream(destPath);
          res.on("data", (chunk) => {
            receivedBytes += chunk.length;
            const mb = Math.floor(receivedBytes / (1024 * 1024));
            if (mb > lastLoggedMb && mb % 5 === 0) {
              lastLoggedMb = mb;
              if (totalBytes > 0) {
                const pct = Math.floor((receivedBytes / totalBytes) * 100);
                process.stderr.write(`\r${YEL}[autonoma]${OFF} Downloading Python... ${mb}MB (${pct}%)`);
              } else {
                process.stderr.write(`\r${YEL}[autonoma]${OFF} Downloading Python... ${mb}MB`);
              }
            }
          });
          res.pipe(fileStream);
          fileStream.on("finish", () => {
            fileStream.close();
            process.stderr.write(`\r${YEL}[autonoma]${OFF} Download complete.                      \n`);
            resolve();
          });
          fileStream.on("error", reject);
        })
        .on("error", reject);
    }
    get(url);
  });
}

async function installStandalonePython() {
  console.log(`${YEL}[autonoma]${OFF} Fetching portable standalone Python runtime...`);

  let assetName = "";
  const arch = process.arch === "arm64" ? "aarch64" : "x86_64";

  if (IS_WIN) {
    assetName = `cpython-3.12.8%2B20241206-${arch === "aarch64" ? "aarch64" : "x86_64"}-pc-windows-msvc-install_only.tar.gz`;
  } else if (IS_MAC) {
    assetName = `cpython-3.12.8%2B20241206-${arch}-apple-darwin-install_only.tar.gz`;
  } else {
    assetName = `cpython-3.12.8%2B20241206-${arch}-unknown-linux-gnu-install_only.tar.gz`;
  }

  const downloadUrl = `https://github.com/astral-sh/python-build-standalone/releases/download/20241206/${assetName}`;
  fs.mkdirSync(STANDALONE_ROOT, { recursive: true });

  const tempArchive = path.join(STANDALONE_ROOT, "python-temp.tar.gz");
  try {
    await downloadFile(downloadUrl, tempArchive);
    console.log(`${YEL}[autonoma]${OFF} Extracting Python runtime...`);
    const tarResult = spawnSync("tar", ["-xzf", tempArchive, "-C", STANDALONE_ROOT], {
      stdio: "inherit",
      shell: IS_WIN,
    });
    try { fs.unlinkSync(tempArchive); } catch {}
    if (tarResult.status !== 0) {
      console.error(`${RED}[autonoma]${OFF} Extraction failed with exit code ${tarResult.status}`);
      return false;
    }
    return true;
  } catch (err) {
    console.error(`${RED}[autonoma]${OFF} Failed to download standalone runtime: ${err.message}`);
    try { if (fs.existsSync(tempArchive)) fs.unlinkSync(tempArchive); } catch {}
    return false;
  }
}

async function installPythonAutomatically() {
  console.log(`\n${CYN}[autonoma]${OFF} Starting Python installation...`);

  // 1. Windows: Try winget first
  if (IS_WIN) {
    const hasWinget = spawnSync("winget", ["--version"], { shell: true }).status === 0;
    if (hasWinget) {
      console.log(`${YEL}[autonoma]${OFF} Installing Python 3.12 via Windows Package Manager (winget)...`);
      const res = spawnSync(
        "winget",
        ["install", "Python.Python.3.12", "--accept-package-agreements", "--accept-source-agreements", "--silent"],
        { stdio: "inherit", shell: true }
      );
      if (res.status === 0 && findPython()) {
        console.log(`${GRN}[autonoma]${OFF} Python 3.12 installed via winget!`);
        return true;
      }
    }
  }

  // 2. macOS: Try Homebrew first
  if (IS_MAC) {
    const hasBrew = spawnSync("which", ["brew"]).status === 0;
    if (hasBrew) {
      console.log(`${YEL}[autonoma]${OFF} Installing Python 3.12 via Homebrew...`);
      const res = spawnSync("brew", ["install", "python@3.12"], { stdio: "inherit" });
      if (res.status === 0 && findPython()) {
        console.log(`${GRN}[autonoma]${OFF} Python 3.12 installed via Homebrew!`);
        return true;
      }
    }
  }

  // 3. Linux: Try native package manager if available
  if (IS_LINUX) {
    const hasApt = spawnSync("which", ["apt-get"]).status === 0;
    const hasDnf = spawnSync("which", ["dnf"]).status === 0;
    const hasPacman = spawnSync("which", ["pacman"]).status === 0;

    if (hasApt) {
      console.log(`${YEL}[autonoma]${OFF} Attempting system package installation via apt...`);
      const res = spawnSync(
        "sudo",
        ["apt-get", "update", "&&", "sudo", "apt-get", "install", "-y", "python3", "python3-venv", "python3-pip"],
        { stdio: "inherit", shell: true }
      );
      if (res.status === 0 && findPython()) {
        console.log(`${GRN}[autonoma]${OFF} Python installed via apt!`);
        return true;
      }
    } else if (hasDnf) {
      console.log(`${YEL}[autonoma]${OFF} Attempting system package installation via dnf...`);
      const res = spawnSync("sudo", ["dnf", "install", "-y", "python3", "python3-pip"], { stdio: "inherit", shell: true });
      if (res.status === 0 && findPython()) {
        console.log(`${GRN}[autonoma]${OFF} Python installed via dnf!`);
        return true;
      }
    } else if (hasPacman) {
      console.log(`${YEL}[autonoma]${OFF} Attempting system package installation via pacman...`);
      const res = spawnSync("sudo", ["pacman", "-S", "--noconfirm", "python", "python-pip"], { stdio: "inherit", shell: true });
      if (res.status === 0 && findPython()) {
        console.log(`${GRN}[autonoma]${OFF} Python installed via pacman!`);
        return true;
      }
    }
  }

  // 4. Universal Fallback: Download standalone runtime
  console.log(`${YEL}[autonoma]${OFF} Using zero-config portable Python runtime...`);
  const ok = await installStandalonePython();
  if (ok && findPython()) {
    console.log(`${GRN}[autonoma]${OFF} Portable Python 3.12 runtime configured successfully!`);
    return true;
  }

  return false;
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

async function main() {
  if (!fs.existsSync(PYTHON)) {
    let python = findPython();
    if (!python) {
      // Python missing: if interactive terminal, prompt user
      if (process.stdin.isTTY) {
        console.log("");
        console.log(`${CYN}┌─────────────────────────────────────────────────────────────┐${OFF}`);
        console.log(`${CYN}│${OFF}                      ${BLD}AUTONOMA SETUP${OFF}                         ${CYN}│${OFF}`);
        console.log(`${CYN}├─────────────────────────────────────────────────────────────┤${OFF}`);
        console.log(`${CYN}│${OFF}  Python 3.11+ is required but was not detected.             ${CYN}│${OFF}`);
        console.log(`${CYN}│${OFF}  Autonoma can install Python automatically for you now.     ${CYN}│${OFF}`);
        console.log(`${CYN}│${OFF}                                                             ${CYN}│${OFF}`);
        console.log(`${CYN}│${OFF}  Target : Python 3.12 runtime (~30 MB)                      ${CYN}│${OFF}`);
        console.log(`${CYN}│${OFF}  Impact : Frictionless, ready in ~30 seconds                ${CYN}│${OFF}`);
        console.log(`${CYN}└─────────────────────────────────────────────────────────────┘${OFF}`);
        console.log("");

        const answer = await promptUser(
          `${YEL}[autonoma]${OFF} Install Python now? [${BLD}Y/n${OFF}]: `
        );
        const shouldInstall = !answer || answer.toLowerCase().startsWith("y");
        if (shouldInstall) {
          const installed = await installPythonAutomatically();
          if (!installed) {
            printMissingPythonHelp();
            process.exit(1);
          }
        } else {
          printMissingPythonHelp();
          process.exit(1);
        }
      } else {
        printMissingPythonHelp();
        process.exit(1);
      }
    }

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
}

main().catch((err) => {
  console.error(`${RED}[autonoma]${OFF} Fatal launcher error: ${err.message}`);
  process.exit(1);
});

