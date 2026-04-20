/**
 * Autonoma WhatsApp Bridge — Node.js sidecar for whatsapp-web.js
 *
 * Connects to WhatsApp Web, shows QR for login, and exposes a local HTTP API
 * so the Python Autonoma agent can send/receive WhatsApp messages.
 *
 * Env vars:
 *   BRIDGE_PORT          — HTTP port (default 3001)
 *   AUTONOMA_WEBHOOK_URL — Python webhook URL (default http://localhost:8766/webhook/whatsapp)
 *   PUPPETEER_EXECUTABLE_PATH — Custom Chromium path (optional)
 *   WHATSAPP_PROXY_URL        — SOCKS5/HTTP proxy (e.g. socks5://154.13.149.118:1080)
 */

const http = require("http");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const PORT = parseInt(process.env.BRIDGE_PORT || "3001", 10);
const WEBHOOK_URL =
  process.env.AUTONOMA_WEBHOOK_URL ||
  "http://localhost:8766/webhook/whatsapp";

let isReady = false;
// Cache the most recent QR string so the TUI / dashboard can fetch it on
// demand via GET /qr. whatsapp-web.js emits 'qr' multiple times (every ~20s
// while the code rotates) — we just keep the latest. Cleared once 'ready'
// fires so stale codes don't linger on the status panel after login.
let lastQr = null;
let lastQrAt = 0;

// --- WhatsApp Client ---

const PROXY_URL = process.env.WHATSAPP_PROXY_URL || "";

const puppeteerOpts = {
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
};

if (PROXY_URL) {
  puppeteerOpts.args.push(`--proxy-server=${PROXY_URL}`);
}

if (process.env.PUPPETEER_EXECUTABLE_PATH) {
  puppeteerOpts.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
}

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: puppeteerOpts,
});

client.on("qr", (qr) => {
  lastQr = qr;
  lastQrAt = Date.now();
  console.log("\n--- Scan this QR code with WhatsApp ---\n");
  qrcode.generate(qr, { small: true });
  console.log(
    "\n[bridge] QR also available at GET /qr for the Autonoma TUI / dashboard.\n"
  );
});

client.on("authenticated", () => {
  console.log("[bridge] Session authenticated");
});

client.on("auth_failure", (msg) => {
  console.error("[bridge] Auth failure:", msg);
  isReady = false;
});

client.on("ready", () => {
  console.log("[bridge] WhatsApp client ready");
  isReady = true;
  // Drop the QR once we're logged in — any client polling /qr should stop
  // seeing stale codes once the session is active.
  lastQr = null;
  lastQrAt = 0;
});

client.on("disconnected", (reason) => {
  console.warn("[bridge] Disconnected:", reason);
  isReady = false;
});

client.on("message", async (msg) => {
  // Skip own messages and non-text
  if (msg.fromMe || !msg.body) return;

  const payload = JSON.stringify({
    from: msg.from,
    body: msg.body,
    pushName: msg._data.notifyName || "",
  });

  // Forward to Python webhook (fire-and-forget)
  try {
    const url = new URL(WEBHOOK_URL);
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
    };

    const req = http.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        if (res.statusCode >= 400) {
          console.error("[bridge] Webhook error:", res.statusCode, data);
        }
      });
    });

    req.on("error", (err) => {
      console.error("[bridge] Webhook request failed:", err.message);
    });

    req.write(payload);
    req.end();
  } catch (err) {
    console.error("[bridge] Failed to forward message:", err.message);
  }
});

// --- HTTP Server ---

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Invalid JSON"));
      }
    });
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  const sendJSON = (status, obj) => {
    const body = JSON.stringify(obj);
    res.writeHead(status, {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    });
    res.end(body);
  };

  // GET /status
  if (req.method === "GET" && req.url === "/status") {
    const status = isReady ? "ready" : lastQr ? "awaiting_scan" : "disconnected";
    return sendJSON(200, {
      status,
      has_qr: Boolean(lastQr),
      qr_age_seconds: lastQrAt ? Math.round((Date.now() - lastQrAt) / 1000) : null,
    });
  }

  // GET /qr — raw QR payload for the Autonoma TUI / dashboard to render. The
  // string is the literal whatsapp:// URL payload; clients can either render
  // it with their own QR library or just paste it into a mobile QR generator.
  if (req.method === "GET" && req.url === "/qr") {
    if (!lastQr) {
      return sendJSON(404, {
        qr: null,
        status: isReady ? "ready" : "waiting",
        message: isReady
          ? "Session already authenticated — no QR required."
          : "Bridge hasn't emitted a QR yet. Wait a few seconds and retry.",
      });
    }
    return sendJSON(200, {
      qr: lastQr,
      status: "awaiting_scan",
      age_seconds: Math.round((Date.now() - lastQrAt) / 1000),
    });
  }

  // POST /send
  if (req.method === "POST" && req.url === "/send") {
    if (!isReady) {
      return sendJSON(503, { success: false, error: "WhatsApp not connected" });
    }

    try {
      const { chatId, text } = await parseBody(req);
      if (!chatId || !text) {
        return sendJSON(400, {
          success: false,
          error: "chatId and text are required",
        });
      }
      await client.sendMessage(chatId, text);
      return sendJSON(200, { success: true });
    } catch (err) {
      console.error("[bridge] Send error:", err.message);
      return sendJSON(500, { success: false, error: err.message });
    }
  }

  // 404
  sendJSON(404, { error: "Not found" });
});

// --- Start ---

server.listen(PORT, () => {
  console.log(`[bridge] HTTP server listening on http://localhost:${PORT}`);
  console.log(`[bridge] Webhook target: ${WEBHOOK_URL}`);
  if (PROXY_URL) console.log(`[bridge] Using proxy: ${PROXY_URL}`);
  console.log("[bridge] Initializing WhatsApp client...\n");
  client.initialize();
});

// Graceful shutdown
function shutdown() {
  console.log("\n[bridge] Shutting down...");
  client
    .destroy()
    .catch(() => {})
    .finally(() => {
      server.close(() => process.exit(0));
      // Force exit after 5s if graceful close hangs
      setTimeout(() => process.exit(0), 5000);
    });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
