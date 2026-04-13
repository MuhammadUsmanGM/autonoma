import { useAPI } from "../hooks/useAPI";
import { Brain, Zap } from "lucide-react";

interface AgentInfo {
  id: string;
  name: string;
  skills: Array<{ name: string; description: string }>;
}

export function Skills() {
  const { data: agent } = useAPI<AgentInfo>("/agent");

  return (
    <div>
      <div className="page-header">
        <h2>Skills</h2>
        <p>Manage what your Digital FTE can do</p>
      </div>

      <div className="card-grid">
        {agent?.skills.map((skill) => (
          <div className="card" key={skill.name}>
            <div className="card-header">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div
                  className="connector-icon"
                  style={{ background: "var(--accent)20", color: "var(--accent)" }}
                >
                  <Zap size={20} />
                </div>
                <span className="card-title">{skill.name}</span>
              </div>
              <span className="badge badge-success">Active</span>
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 8 }}>
              {skill.description}
            </p>
          </div>
        ))}

        {(!agent?.skills || agent.skills.length === 0) && (
          <div className="card" style={{ gridColumn: "1 / -1" }}>
            <div style={{ textAlign: "center", padding: 40, color: "var(--text-secondary)" }}>
              <Brain size={48} style={{ opacity: 0.3, marginBottom: 16 }} />
              <p>No skills loaded yet.</p>
              <p style={{ fontSize: 13, marginTop: 8 }}>
                Register skills in your Digital FTE configuration to give your agent capabilities.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
