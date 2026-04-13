import { useAPI } from "../hooks/useAPI";
import { Settings, Server } from "lucide-react";

interface HealthData {
  status: string;
  name: string;
  uptime: number;
}

export function SettingsPage() {
  const { data: health } = useAPI<HealthData>("/health");

  const formatUptime = (seconds: number): string => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h}h ${m}m ${s}s`;
  };

  return (
    <div>
      <div className="page-header">
        <h2>Settings</h2>
        <p>Configure your Digital FTE</p>
      </div>

      <div className="card" style={{ maxWidth: 600, marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">
            <Server size={16} style={{ marginRight: 8, verticalAlign: "middle" }} />
            Server Info
          </span>
        </div>
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-secondary)" }}>Status</span>
            <span className="badge badge-success">{health?.status ?? "unknown"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-secondary)" }}>Agent Name</span>
            <span>{health?.name ?? "—"}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-secondary)" }}>Uptime</span>
            <span>{health ? formatUptime(health.uptime) : "—"}</span>
          </div>
        </div>
      </div>

      <div className="card" style={{ maxWidth: 600 }}>
        <div className="card-header">
          <span className="card-title">
            <Settings size={16} style={{ marginRight: 8, verticalAlign: "middle" }} />
            Configuration
          </span>
        </div>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 12 }}>
          Edit your <code style={{ background: "var(--bg-hover)", padding: "2px 6px", borderRadius: 4 }}>digital-fte.config.json</code> or <code style={{ background: "var(--bg-hover)", padding: "2px 6px", borderRadius: 4 }}>.env</code> file to configure:
        </p>
        <ul style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 8, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 4 }}>
          <li>LLM provider and model</li>
          <li>Platform connectors and credentials</li>
          <li>Agent name and system prompt</li>
          <li>Port and data directory</li>
        </ul>
      </div>
    </div>
  );
}
