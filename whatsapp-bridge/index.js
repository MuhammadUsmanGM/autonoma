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
 */

const http = require("http");
const { Client, LocalAuth } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");

const PORT = parseInt(process.env.BRIDGE_PORT || "3001", 10);
const WEBHOOK_URL =
  process.env.AUTONOMA_WEBHOOK_URL ||
  "http://localhost:8766/webhook/whatsapp";

let isReady = false;

// --- WhatsApp Client ---

const puppeteerOpts = {
  headless: true,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
};

if (process.env.PUPPETEER_EXECUTABLE_PATH) {
  puppeteerOpts.executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
}

const client = new Client({
  authStrategy: new LocalAuth(),
  puppeteer: puppeteerOpts,
});

client.on("qr", (qr) => {
  console.log("\n--- Scan this QR code with WhatsApp ---\n");
  qrcode.generate(qr, { small: true });
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
    const status = isReady ? "ready" : "disconnected";
    return sendJSON(200, { status });
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
