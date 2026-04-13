import { useAPI } from "../hooks/useAPI";
import { Activity, MessageSquare, Plug, Cpu } from "lucide-react";

interface AgentInfo {
  id: string;
  name: string;
  skills: Array<{ name: string; description: string }>;
}

interface ConnectorsData {
  connectors: Array<{ name: string; type: string; connected: boolean }>;
}

interface ConversationsData {
  conversations: Array<{
    id: string;
    platform: string;
    messageCount: number;
    lastMessage?: { content: string; timestamp: string; userName?: string };
    updatedAt: string;
  }>;
}

export function Dashboard() {
  const { data: agent } = useAPI<AgentInfo>("/agent");
  const { data: connData } = useAPI<ConnectorsData>("/connectors");
  const { data: convData } = useAPI<ConversationsData>("/conversations");

  const connectedCount = connData?.connectors.filter((c) => c.connected).length ?? 0;
  const totalConversations = convData?.conversations.length ?? 0;
  const totalMessages = convData?.conversations.reduce((sum, c) => sum + c.messageCount, 0) ?? 0;

  return (
    <div>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Overview of your Digital FTE agent</p>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Agent Status</div>
          <div className="stat-value" style={{ color: "var(--success)", fontSize: 20 }}>
            <Activity size={20} style={{ marginRight: 8, verticalAlign: "middle" }} />
            Online
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Connected Platforms</div>
          <div className="stat-value">
            <Plug size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {connectedCount}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Conversations</div>
          <div className="stat-value">
            <MessageSquare size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {totalConversations}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Messages Handled</div>
          <div className="stat-value">{totalMessages}</div>
        </div>
      </div>

      <div className="page-header">
        <h2 style={{ fontSize: 18 }}>Loaded Skills</h2>
      </div>
      <div className="card-grid">
        {agent?.skills.map((skill) => (
          <div className="card" key={skill.name}>
            <div className="card-header">
              <span className="card-title">
                <Cpu size={16} style={{ marginRight: 8, verticalAlign: "middle" }} />
                {skill.name}
              </span>
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>{skill.description}</p>
          </div>
        )) ?? (
          <p style={{ color: "var(--text-secondary)" }}>No skills loaded yet.</p>
        )}
      </div>

      {convData && convData.conversations.length > 0 && (
        <>
          <div className="page-header" style={{ marginTop: 30 }}>
            <h2 style={{ fontSize: 18 }}>Recent Conversations</h2>
          </div>
          <div className="card-grid">
            {convData.conversations.slice(0, 6).map((conv) => (
              <div className="card" key={conv.id}>
                <div className="card-header">
                  <span className="card-title" style={{ textTransform: "capitalize" }}>
                    {conv.platform}
                  </span>
                  <span className="badge badge-success">{conv.messageCount} msgs</span>
                </div>
                {conv.lastMessage && (
                  <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                    <strong>{conv.lastMessage.userName}:</strong> {conv.lastMessage.content.slice(0, 80)}
                    {conv.lastMessage.content.length > 80 ? "..." : ""}
                  </p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
