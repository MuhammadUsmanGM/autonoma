import { Routes, Route, NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Plug,
  Cpu,
  Settings,
  Brain,
} from "lucide-react";
import { Dashboard } from "./pages/Dashboard";
import { Chat } from "./pages/Chat";
import { Connectors } from "./pages/Connectors";
import { Skills } from "./pages/Skills";
import { SettingsPage } from "./pages/Settings";

export function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <h1>Autonoma</h1>
          <p>AI Agent Platform</p>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end>
            <LayoutDashboard size={18} /> Dashboard
          </NavLink>
          <NavLink to="/chat">
            <MessageSquare size={18} /> Chat
          </NavLink>
          <NavLink to="/connectors">
            <Plug size={18} /> Connectors
          </NavLink>
          <NavLink to="/skills">
            <Brain size={18} /> Skills
          </NavLink>
          <NavLink to="/settings">
            <Settings size={18} /> Settings
          </NavLink>
        </nav>
      </aside>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/connectors" element={<Connectors />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
