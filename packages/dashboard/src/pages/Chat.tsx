import { useState, useRef, useEffect } from "react";
import { Send } from "lucide-react";
import { apiPost } from "../hooks/useAPI";

interface ChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: Date;
}

export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const data = await apiPost<{ response: { content: string } }>("/chat", {
        content: userMsg.content,
      });

      const agentMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "agent",
        content: data.response.content,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, agentMsg]);
    } catch {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "agent",
        content: "Sorry, something went wrong. Please check if the agent is running.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Web Chat</h2>
        <p>Talk to your Autonoma directly</p>
      </div>

      <div className="chat-container">
        <div className="chat-messages">
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-secondary)", marginTop: 60 }}>
              <p style={{ fontSize: 16 }}>Send a message to start chatting with your Autonoma</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`chat-message ${msg.role}`}>
              {msg.content}
            </div>
          ))}
          {loading && (
            <div className="chat-message agent" style={{ opacity: 0.6 }}>
              Thinking...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="chat-input">
          <input
            type="text"
            placeholder="Type a message..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            disabled={loading}
          />
          <button className="btn btn-primary" onClick={sendMessage} disabled={loading}>
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}
