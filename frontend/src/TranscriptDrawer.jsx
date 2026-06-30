import { useEffect, useRef, useState } from "react";
import { useVoiceSession } from "./VoiceSessionContext";

const DRAWER_WIDTH = 340;

export default function TranscriptDrawer() {
  const { showTranscript, messages, connected, sendMessage } =
    useVoiceSession();
  const chatRef = useRef(null);
  const [inputText, setInputText] = useState("");
  const [showTextInput, setShowTextInput] = useState(false);

  // Auto-scroll
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (inputText.trim()) {
        sendMessage(inputText);
        setInputText("");
      }
    }
  }

  return (
    <>
      {/* Overlay backdrop when drawer is open */}
      {showTranscript && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.3)",
            zIndex: 90,
          }}
          onClick={() => {}}
        />
      )}

      {/* Drawer */}
      <div
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: DRAWER_WIDTH,
          height: "100%",
          background: "rgba(20, 20, 35, 0.98)",
          borderLeft: "1px solid #333",
          display: "flex",
          flexDirection: "column",
          transform: showTranscript ? "translateX(0)" : "translateX(100%)",
          transition: "transform 0.25s ease",
          zIndex: 100,
          boxShadow: showTranscript ? "-4px 0 24px rgba(0,0,0,0.4)" : "none",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderBottom: "1px solid #333",
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: "#a78bfa" }}>
            💬 Chat
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            {/* "Type instead" toggle */}
            <button
              onClick={() => setShowTextInput((v) => !v)}
              style={{
                background: "none",
                border: "1px solid #444",
                borderRadius: 6,
                color: "#888",
                cursor: "pointer",
                fontSize: 11,
                padding: "4px 8px",
              }}
              title={showTextInput ? "Hide text input" : "Type instead of speaking"}
            >
              ⌨️
            </button>
          </div>
        </div>

        {/* Messages */}
        <div
          ref={chatRef}
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {messages.length === 0 && (
            <div
              style={{
                color: "#666",
                fontSize: 12,
                textAlign: "center",
                marginTop: 40,
              }}
            >
              Speak or type to start.
              <br />
              Nova will respond.
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === "you" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                padding: "8px 12px",
                borderRadius: 12,
                fontSize: 13,
                lineHeight: 1.4,
                background: m.role === "you" ? "#6d28d9" : "#2d2d4a",
                color: "#eee",
              }}
            >
              <div
                style={{
                  fontSize: 10,
                  color: "#888",
                  marginBottom: 2,
                }}
              >
                {m.role === "you" ? "You" : "Nova"}
              </div>
              {m.text}
            </div>
          ))}
        </div>

        {/* TextFallbackInput (tucked, shown only when ⌨️ is toggled) */}
        {showTextInput && (
          <div
            style={{
              padding: "8px 10px",
              borderTop: "1px solid #333",
              display: "flex",
              gap: 6,
              alignItems: "center",
            }}
          >
            <input
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={connected ? "Type a message..." : "Connecting..."}
              autoFocus
              style={{
                flex: 1,
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid #444",
                background: "#1a1a2e",
                color: "#eee",
                fontSize: 12,
                outline: "none",
              }}
            />
            <button
              onClick={() => {
                if (inputText.trim()) {
                  sendMessage(inputText);
                  setInputText("");
                }
              }}
              disabled={!inputText.trim()}
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: "none",
                background: "#7c3aed",
                color: "#fff",
                fontSize: 12,
                cursor: "pointer",
                opacity: connected ? 1 : 0.5,
              }}
            >
              Send
            </button>
          </div>
        )}
      </div>
    </>
  );
}
