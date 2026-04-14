import { useState } from "react";
import { useAPI } from "../hooks/useAPI";
import { MessageCircle, Send, Hash, Slack, Globe, QrCode, RefreshCw } from "lucide-react";

interface ConnectorsData {
  connectors: Array<{ name: string; type: string; connected: boolean }>;
}

const PLATFORM_META: Record<string, { icon: typeof MessageCircle; color: string; label: string }> = {
  whatsapp: { icon: MessageCircle, color: "var(--whatsapp)", label: "WhatsApp" },
  telegram: { icon: Send, color: "var(--telegram)", label: "Telegram" },
  discord: { icon: Hash, color: "var(--discord)", label: "Discord" },
  slack: { icon: Slack, color: "var(--slack)", label: "Slack" },
  webchat: { icon: Globe, color: "var(--accent)", label: "Web Chat" },
};

export function Connectors() {
  const { data, refetch } = useAPI<ConnectorsData>("/connectors");
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [qrLoading, setQrLoading] = useState(false);

  const loadQR = async (name: string) => {
    setQrLoading(true);
    try {
      const res = await fetch(`/api/connectors/${name}/qr`);
      const json = await res.json();
      setQrCode(json.qr);
    } catch {
      setQrCode(null);
    } finally {
      setQrLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Connectors</h2>
        <p>Connect your Autonoma to messaging platforms</p>
      </div>

      <div className="card-grid">
        {data?.connectors.map((conn) => {
          const meta = PLATFORM_META[conn.type] ?? {
            icon: Globe,
            color: "var(--text-secondary)",
            label: conn.name,
          };
          const Icon = meta.icon;

          return (
            <div className="card" key={conn.name}>
              <div className="card-header">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div
                    className="connector-icon"
                    style={{ background: `${meta.color}20`, color: meta.color }}
                  >
                    <Icon size={20} />
                  </div>
                  <span className="card-title">{meta.label}</span>
                </div>
                <span className={`badge ${conn.connected ? "badge-success" : "badge-warning"}`}>
                  {conn.connected ? "Connected" : "Disconnected"}
                </span>
              </div>

              <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                {conn.type === "whatsapp" && !conn.connected && (
                  <button className="btn" onClick={() => loadQR(conn.name)}>
                    <QrCode size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
                    Show QR Code
                  </button>
                )}
                <button className="btn" onClick={refetch}>
                  <RefreshCw size={14} style={{ marginRight: 6, verticalAlign: "middle" }} />
                  Refresh
                </button>
              </div>
            </div>
          );
        })}

        {(!data || data.connectors.length === 0) && (
          <div className="card">
            <p style={{ color: "var(--text-secondary)" }}>
              No connectors registered. Add connectors in your config or .env file.
            </p>
          </div>
        )}
      </div>

      {/* QR Code Modal */}
      {qrCode && (
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
          onClick={() => setQrCode(null)}
        >
          <div className="card" style={{ maxWidth: 400, textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginBottom: 16 }}>Scan with WhatsApp</h3>
            <div className="qr-container">
              <img
                src={`https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(qrCode)}`}
                alt="WhatsApp QR Code"
                width={250}
                height={250}
              />
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 12 }}>
              Open WhatsApp on your phone, go to Settings &gt; Linked Devices &gt; Link a Device
            </p>
            <button className="btn" style={{ marginTop: 16 }} onClick={() => setQrCode(null)}>
              Close
            </button>
          </div>
        </div>
      )}

      {qrLoading && (
        <div style={{ textAlign: "center", marginTop: 20, color: "var(--text-secondary)" }}>
          Loading QR code...
        </div>
      )}
    </div>
  );
}
