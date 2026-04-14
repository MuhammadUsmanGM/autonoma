import { useAPI } from "../hooks/useAPI";
import { Brain, User, Lightbulb, MessageSquare, Database } from "lucide-react";

interface MemoryStats {
  users: number;
  facts: number;
  conversations: number;
  totalMessages: number;
}

interface UserProfile {
  id: string;
  platform: string;
  userName: string;
  displayName?: string;
  facts: string[];
  preferences: Record<string, string>;
  firstSeen: string;
  lastSeen: string;
  messageCount: number;
}

interface MemoryFact {
  id: string;
  content: string;
  source: string;
  tags: string[];
  createdAt: string;
}

export function Memory() {
  const { data: stats } = useAPI<MemoryStats>("/memory/stats");
  const { data: usersData } = useAPI<{ users: UserProfile[] }>("/memory/users");
  const { data: factsData } = useAPI<{ facts: MemoryFact[] }>("/memory/facts");

  return (
    <div>
      <div className="page-header">
        <h2>Memory</h2>
        <p>What your Autonoma agent remembers across conversations</p>
      </div>

      {/* Stats */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Known Users</div>
          <div className="stat-value">
            <User size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {stats?.users ?? 0}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Saved Facts</div>
          <div className="stat-value">
            <Lightbulb size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {stats?.facts ?? 0}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Conversations</div>
          <div className="stat-value">
            <MessageSquare size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {stats?.conversations ?? 0}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Messages</div>
          <div className="stat-value">
            <Database size={24} style={{ marginRight: 8, verticalAlign: "middle" }} />
            {stats?.totalMessages ?? 0}
          </div>
        </div>
      </div>

      {/* Users */}
      <div className="page-header" style={{ marginTop: 10 }}>
        <h2 style={{ fontSize: 18 }}>Known Users</h2>
        <p>People your agent has interacted with</p>
      </div>

      {usersData?.users && usersData.users.length > 0 ? (
        <div className="card-grid">
          {usersData.users.map((user) => (
            <div className="card" key={`${user.platform}-${user.id}`}>
              <div className="card-header">
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div
                    className="connector-icon"
                    style={{ background: "var(--accent)20", color: "var(--accent)" }}
                  >
                    <User size={18} />
                  </div>
                  <div>
                    <span className="card-title">{user.userName}</span>
                    <p style={{ color: "var(--text-secondary)", fontSize: 11 }}>
                      {user.platform} &middot; {user.messageCount} messages
                    </p>
                  </div>
                </div>
              </div>

              {user.facts.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>Remembered facts:</p>
                  <ul style={{ fontSize: 13, color: "var(--text-primary)", paddingLeft: 16, display: "flex", flexDirection: "column", gap: 2 }}>
                    {user.facts.slice(-5).map((fact, i) => (
                      <li key={i}>{fact}</li>
                    ))}
                  </ul>
                </div>
              )}

              {Object.keys(user.preferences).length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>Preferences:</p>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {Object.entries(user.preferences).map(([k, v]) => (
                      <span key={k} className="badge badge-success" style={{ fontSize: 11 }}>
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <p style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 10 }}>
                Last seen: {new Date(user.lastSeen).toLocaleString()}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--text-secondary)" }}>
          <User size={40} style={{ opacity: 0.3, marginBottom: 12 }} />
          <p>No users yet. Start chatting on any platform and users will appear here.</p>
        </div>
      )}

      {/* Facts */}
      <div className="page-header" style={{ marginTop: 30 }}>
        <h2 style={{ fontSize: 18 }}>Knowledge Base</h2>
        <p>Facts and knowledge your agent has learned</p>
      </div>

      {factsData?.facts && factsData.facts.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {factsData.facts.slice(0, 20).map((fact) => (
            <div className="card" key={fact.id} style={{ padding: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 14 }}>{fact.content}</p>
                  <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                    {fact.tags.map((tag) => (
                      <span key={tag} className="badge" style={{ background: "rgba(99,102,241,0.1)", color: "var(--accent)", fontSize: 11 }}>
                        #{tag}
                      </span>
                    ))}
                    <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>
                      {fact.source} &middot; {new Date(fact.createdAt).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card" style={{ textAlign: "center", padding: 40, color: "var(--text-secondary)" }}>
          <Brain size={40} style={{ opacity: 0.3, marginBottom: 12 }} />
          <p>No facts yet. Your agent will learn and save facts as it interacts with users.</p>
        </div>
      )}
    </div>
  );
}
