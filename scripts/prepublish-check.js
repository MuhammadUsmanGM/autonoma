#!/usr/bin/env node

/**
 * Autonoma — prepublish sanity check.
 * Verifies the tarball is not about to ship something broken.
 * Runs offline, fast. Bails with a non-zero exit if anything is wrong.
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const pkg = require(path.join(ROOT, "package.json"));

const failures = [];
function fail(msg) {
  failures.push(msg);
}
function ok(msg) {
  console.log(`  \x1b[32m✓\x1b[0m ${msg}`);
}

console.log(`\n[autonoma prepublish] ${pkg.name}@${pkg.version}\n`);

// 1. Required runtime files must exist on disk.
const required = [
  "bin/autonoma.js",
  "scripts/install.js",
  "scripts/prepack.js",
  "autonoma/__init__.py",
  "autonoma/__main__.py",
  "dashboard/dist/index.html",
  "dashboard/dist/assets",
  "whatsapp-bridge/index.js",
  "whatsapp-bridge/package.json",
  "pyproject.toml",
  "README.md",
  "LICENSE",
  ".env.example",
];
for (const rel of required) {
  const abs = path.join(ROOT, rel);
  if (!fs.existsSync(abs)) fail(`missing required file: ${rel}`);
  else ok(rel);
}

// 2. Node scripts must be syntactically valid.
const scripts = ["bin/autonoma.js", "scripts/install.js", "scripts/prepack.js"];
for (const s of scripts) {
  try {
    execSync(`node --check "${path.join(ROOT, s)}"`, { stdio: "pipe" });
    ok(`syntax ok: ${s}`);
  } catch (e) {
    fail(`syntax error in ${s}: ${e.message}`);
  }
}

// 3. package.json invariants.
if (!pkg.bin || !pkg.bin.autonoma) fail("package.json: missing bin.autonoma");
else ok("bin.autonoma wired");

if (!pkg.files || pkg.files.length === 0) fail("package.json: empty files array");
else ok(`files whitelist has ${pkg.files.length} entries`);

if (!pkg.engines || !pkg.engines.node) fail("package.json: missing engines.node");
else ok(`engines.node = ${pkg.engines.node}`);

// 4. Version sanity — don't republish the same version by accident.
if (!/^\d+\.\d+\.\d+/.test(pkg.version)) {
  fail(`package.json: version "${pkg.version}" is not semver`);
} else {
  ok(`version ${pkg.version}`);
}

// 5. Critical secret files must NOT be in the tarball.
try {
  const out = execSync("npm pack --dry-run --json", {
    cwd: ROOT,
    stdio: ["pipe", "pipe", "pipe"],
    encoding: "utf-8",
  });
  const data = JSON.parse(out);
  const entries = (data[0] && data[0].files) || [];
  const paths = entries.map((f) => f.path);
  const banned = [
    /^\.env$/,
    /\.env\.local$/,
    /node_modules\//,
    /\.wwebjs_auth/,
    /\.wwebjs_cache/,
    /__pycache__/,
    /\.pyc$/,
  ];
  for (const rx of banned) {
    const hit = paths.find((p) => rx.test(p));
    if (hit) fail(`tarball contains forbidden path: ${hit} (matched ${rx})`);
  }
  ok(`tarball clean (${paths.length} files)`);
} catch (e) {
  fail(`npm pack --dry-run failed: ${e.message}`);
}

if (failures.length) {
  console.error(`\n\x1b[31m[autonoma prepublish] ${failures.length} issue(s):\x1b[0m`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  console.error("");
  process.exit(1);
}

console.log(`\n\x1b[32m[autonoma prepublish] all checks passed\x1b[0m\n`);
