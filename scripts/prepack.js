#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

function walk(dir, fn) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      fn(full, true);
      walk(full, fn);
    } else {
      fn(full, false);
    }
  }
}

let removed = 0;
walk(ROOT, (p, isDir) => {
  const base = path.basename(p);
  if (isDir && base === "__pycache__") {
    fs.rmSync(p, { recursive: true, force: true });
    removed++;
    return;
  }
  if (!isDir && (p.endsWith(".pyc") || p.endsWith(".pyo"))) {
    try {
      fs.unlinkSync(p);
      removed++;
    } catch {}
  }
});

console.error(`[autonoma prepack] cleaned ${removed} pycache entries`);
