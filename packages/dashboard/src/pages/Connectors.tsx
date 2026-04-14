import { useState, useEffect, useCallback } from "react";
import { useAPI, apiPost } from "../hooks/useAPI";
import {
  MessageCircle,
  Send,
  Hash,
  Slack,
  Globe,
  Mail,
  QrCode,
  RefreshCw,
  Power,
  PowerOff,
  Loader2,
  Check,
  X,
  Eye,
  EyeOff,
} from "lucide-react";

interface ConnectorData {
  name: string;
  type: string;
  connected: boolean;
  status: {
    state: string;
    qr?: string;
    phoneNumber?: string;
    pushName?: string;
    botUsername?: string;
    guildCount?: number;
    botName?: string;
    teamName?: string;
    email?: string;
    error?: string;
  };
}

interface ConnectorsResponse {
  connectors: ConnectorData[];
}

const PLATFORMS: Record<
  string,
  {
    icon: typeof MessageCircle;
    color: string;
    label: string;
    description: string;
    fields: Array<{ key: string; label: string; placeholder: string; secret?: boolean }>;
    setupNote: string;
  }
> = {
  whatsapp: {
    icon: MessageCircle,
    color: "#25d366",
    label: "WhatsApp",
    description: "Scan QR code with your phone to connect",
    fields: [], // No fields — just QR scan
    setupNote: "Open WhatsApp > Settings > Linked Devices > Link a Device",
  },
  telegram: {
    icon: Send,
    color: "#0088cc",
    label: "Telegram",
    description: "Connect via Bot Token from @BotFather",
    fields: [{ key: "botToken", label: "Bot Token", placeholder: "123456:ABC-DEF...", secret: true }],
    setupNote: "Open Telegram, message @BotFather, send /newbot, and copy the token",
  },
  discord: {
    icon: Hash,
    color: "#5865f2",
    label: "Discord",
    description: "Connect via Bot Token from Developer Portal",
    fields: [{ key: "botToken", label: "Bot Token", placeholder: "MTIz...", secret: true }],
    setupNote: "Go to discord.com/developers > New Application > Bot > Copy Token. Enable Message Content Intent.",
  },
  slack: {
    icon: Slack,
    color: "#4a154b",
    label: "Slack",
    description: "Connect via Socket Mode (no public URL needed)",
    fields: [
      { key: "botToken", label: "Bot Token", placeholder: "xoxb-...", secret: true },
      { key: "appToken", label: "App Token", placeholder: "xapp-...", secret: true },
    ],
    setupNote: "Create a Slack App at api.slack.com/apps. Enable Socket Mode. Add bot scopes: chat:write, channels:history, im:history.",
  },
  gmail: {
    icon: Mail,
    color: "#ea4335",
    label: "Gmail",
    description: "Connect with email and app password",
    fields: [
      { key: "email", label: "Email Address", placeholder: "you@gmail.com" },
      { key: "password", label: "App Password", placeholder: "xxxx xxxx xxxx xxxx", secret: true },
    ],
    setupNote: "Go to myaccount.google.com > Security > 2-Step Verification > App Passwords. Generate a password for 'Mail'.",
  },
  webchat: {
    icon: Globe,
    color: "#6366f1",
    label: "Web Chat",
    description: "Built-in chat — always available in the dashboard",
    fields: [],
    setupNote: "Web Chat is always available. Go to the Chat page to start talking.",
  },
};

export function Connectors() {
  const { data, refetch } = useAPI<ConnectorsResponse>("/connectors");
  const [setupModal, setSetupModal] = useState<string | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [whatsappQR, setWhatsappQR] = useState<string | null>(null);
  const [pollingQR, setPollingQR] = useState(false);

  // Poll for WhatsApp QR when waiting
  const pollWhatsAppQR = useCallback(async () => {
    setPollingQR(true);
    const interval = setInterval(async () => {
      try {
        const res = await fetch("/api/connectors/whatsapp/qr");
        const json = await res.json();
        if (json.qr) {
          setWhatsappQR(json.qr);
        }
        // Check if connected
        const statusRes = await fetch("/api/connectors/whatsapp/status");
        const statusJson = await statusRes.json();
        if (statusJson.status?.state === "connected") {
          clearInterval(interval);
          setPollingQR(false);
          setSetupModal(null);
          setWhatsappQR(null);
          refetch();
        }
      } catch {
        // ignore
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [refetch]);

  const openSetup = (name: string) => {
    setSetupModal(name);
    setCredentials({});
    setError(null);
    setWhatsappQR(null);
  };

  const connectPlatform = async (name: string) => {
    setConnecting(true);
    setError(null);

    try {
      if (name === "whatsapp") {
        // WhatsApp: start connection, then poll for QR
        await apiPost("/connectors/whatsapp/start", {});
        pollWhatsAppQR();
      } else {
        await apiPost(`/connectors/${name}/connect`, { credentials });
        setSetupModal(null);
        refetch();
      }
    } catch (err: any) {
      setError(err.message ?? "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  const disconnectPlatform = async (name: string) => {
    try {
      await apiPost(`/connectors/${name}/disconnect`, {});
      refetch();
    } catch {
      // ignore
    }
  };

  const getStatusBadge = (connector: ConnectorData) => {
    const state = connector.status?.state ?? (connector.connected ? "connected" : "disconnected");
    switch (state) {
      case "connected":
        return <span className="badge badge-success"><Check size={12} style={{ marginRight: 4 }} />Connected</span>;
      case "connecting":
      case "qr":
        return <span className="badge badge-warning"><Loader2 size={12} className="spin" style={{ marginRight: 4 }} />Connecting</span>;
      case "error":
        return <span className="badge badge-danger"><X size={12} style={{ marginRight: 4 }} />Error</span>;
      default:
        return <span className="badge" style={{ background: "rgba(136,136,160,0.1)", color: "var(--text-secondary)" }}>Not connected</span>;
    }
  };

  const getStatusDetail = (connector: ConnectorData): string | null => {
    const s = connector.status;
    if (!s) return null;
    if (s.phoneNumber) return `Phone: ${s.phoneNumber}${s.pushName ? ` (${s.pushName})` : ""}`;
    if (s.botUsername) return `@${s.botUsername}${s.guildCount ? ` — ${s.guildCount} servers` : ""}`;
    if (s.botName) return `${s.botName}${s.teamName ? ` — ${s.teamName}` : ""}`;
    if (s.email) return s.email;
    if (s.error) return `Error: ${s.error}`;
    return null;
  };

  return (
    <div>
      <div className="page-header">
        <h2>Connectors</h2>
        <p>Connect Autonoma to your messaging platforms</p>
      </div>

      <div className="card-grid">
        {data?.connectors.map((conn) => {
          const platform = PLATFORMS[conn.type] ?? PLATFORMS.webchat;
          const Icon = platform.icon;
          const detail = getStatusDetail(conn);

          return (
            <div className="card" key={conn.name}>
              <div className="card-header">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div
                    className="connector-icon"
                    style={{ background: `${platform.color}20`, color: platform.color }}
                  >
                    <Icon size={20} />
                  </div>
                  <div>
                    <span className="card-title">{platform.label}</span>
                    <p style={{ color: "var(--text-secondary)", fontSize: 12, marginTop: 2 }}>
                      {platform.description}
                    </p>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 12 }}>
                {getStatusBadge(conn)}
                {detail && (
                  <p style={{ color: "var(--text-secondary)", fontSize: 12, marginTop: 8 }}>{detail}</p>
                )}
              </div>

              {conn.type !== "webchat" && (
                <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                  {!conn.connected ? (
                    <button className="btn btn-primary" onClick={() => openSetup(conn.name)}>
                      <Power size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
                      Connect
                    </button>
                  ) : (
                    <button className="btn" onClick={() => disconnectPlatform(conn.name)} style={{ borderColor: "var(--danger)", color: "var(--danger)" }}>
                      <PowerOff size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
                      Disconnect
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Setup Modal */}
      {setupModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={() => { if (!connecting && !pollingQR) setSetupModal(null); }}
        >
          <div
            className="card"
            style={{ maxWidth: 480, width: "100%", margin: 20 }}
            onClick={(e) => e.stopPropagation()}
          >
            {(() => {
              const connector = data?.connectors.find((c) => c.name === setupModal);
              const platform = PLATFORMS[connector?.type ?? ""] ?? PLATFORMS.webchat;
              const Icon = platform.icon;

              return (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                    <div
                      className="connector-icon"
                      style={{ background: `${platform.color}20`, color: platform.color }}
                    >
                      <Icon size={24} />
                    </div>
                    <div>
                      <h3>Connect {platform.label}</h3>
                      <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>{platform.description}</p>
                    </div>
                  </div>

                  {/* WhatsApp QR Flow */}
                  {connector?.type === "whatsapp" && (
                    <div>
                      {whatsappQR ? (
                        <div className="qr-container">
                          <img src={whatsappQR} alt="WhatsApp QR Code" width={260} height={260} style={{ borderRadius: 12 }} />
                          <p style={{ color: "var(--text-secondary)", fontSize: 13, textAlign: "center", marginTop: 8 }}>
                            {platform.setupNote}
                          </p>
                        </div>
                      ) : pollingQR ? (
                        <div style={{ textAlign: "center", padding: 40, color: "var(--text-secondary)" }}>
                          <Loader2 size={32} className="spin" />
                          <p style={{ marginTop: 12 }}>Generating QR code...</p>
                        </div>
                      ) : (
                        <div style={{ textAlign: "center" }}>
                          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 16 }}>
                            {platform.setupNote}
                          </p>
                          <button
                            className="btn btn-primary"
                            onClick={() => connectPlatform("whatsapp")}
                            disabled={connecting}
                          >
                            <QrCode size={16} style={{ marginRight: 8, verticalAlign: "middle" }} />
                            {connecting ? "Starting..." : "Show QR Code"}
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Token-based Flows */}
                  {connector?.type !== "whatsapp" && platform.fields.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      <div
                        style={{
                          background: "var(--bg-hover)",
                          borderRadius: 8,
                          padding: 12,
                          fontSize: 13,
                          color: "var(--text-secondary)",
                          lineHeight: 1.5,
                        }}
                      >
                        {platform.setupNote}
                      </div>

                      {platform.fields.map((field) => (
                        <div key={field.key}>
                          <label style={{ fontSize: 13, color: "var(--text-secondary)", display: "block", marginBottom: 4 }}>
                            {field.label}
                          </label>
                          <div style={{ position: "relative" }}>
                            <input
                              type={field.secret && !showSecrets[field.key] ? "password" : "text"}
                              placeholder={field.placeholder}
                              value={credentials[field.key] ?? ""}
                              onChange={(e) => setCredentials({ ...credentials, [field.key]: e.target.value })}
                              style={{
                                width: "100%",
                                padding: "10px 40px 10px 12px",
                                borderRadius: 8,
                                border: "1px solid var(--border)",
                                background: "var(--bg-card)",
                                color: "var(--text-primary)",
                                fontSize: 14,
                                outline: "none",
                                boxSizing: "border-box",
                              }}
                            />
                            {field.secret && (
                              <button
                                onClick={() => setShowSecrets({ ...showSecrets, [field.key]: !showSecrets[field.key] })}
                                style={{
                                  position: "absolute",
                                  right: 8,
                                  top: "50%",
                                  transform: "translateY(-50%)",
                                  background: "none",
                                  border: "none",
                                  color: "var(--text-secondary)",
                                  cursor: "pointer",
                                  padding: 4,
                                }}
                              >
                                {showSecrets[field.key] ? <EyeOff size={16} /> : <Eye size={16} />}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}

                      {error && (
                        <div style={{ color: "var(--danger)", fontSize: 13, padding: "8px 12px", background: "rgba(239,68,68,0.1)", borderRadius: 8 }}>
                          {error}
                        </div>
                      )}

                      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                        <button
                          className="btn btn-primary"
                          style={{ flex: 1 }}
                          onClick={() => connectPlatform(setupModal)}
                          disabled={connecting || platform.fields.some((f) => !credentials[f.key])}
                        >
                          {connecting ? (
                            <><Loader2 size={14} className="spin" style={{ marginRight: 6 }} /> Connecting...</>
                          ) : (
                            <><Power size={14} style={{ marginRight: 6 }} /> Connect</>
                          )}
                        </button>
                        <button className="btn" onClick={() => setSetupModal(null)} disabled={connecting}>
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
