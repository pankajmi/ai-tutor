import { useState, useEffect } from "react";

const STATE_COLORS = {
  idle: { primary: "#7ddf7d", pulse: "#7ddf7d44", label: "Listening" },
  speaking: { primary: "#a78bfa", pulse: "#a78bfa44", label: "Speaking" },
  thinking: { primary: "#f59e0b", pulse: "#f59e0b44", label: "Thinking" },
};

/**
 * Animated voice-state indicator — a pulsing orb that changes color
 * based on Nova's current state, plus a mic level bar.
 *
 * Props:
 *   state: "idle" | "speaking" | "thinking"
 *   onToggleMic: () => void
 *   micActive: boolean
 *   childId: string
 *   micLevel: number (0-1, peak amplitude from AudioStreamer)
 */
export default function VoiceStateIndicator({ state, onToggleMic, micActive, childId, micLevel = 0 }) {
  const colors = STATE_COLORS[state] || STATE_COLORS.idle;

  const [pulseKey, setPulseKey] = useState(0);
  useEffect(() => {
    setPulseKey((k) => k + 1);
  }, [state]);

  // Smooth the mic level display
  const [displayLevel, setDisplayLevel] = useState(0);
  useEffect(() => {
    if (micLevel > displayLevel) {
      setDisplayLevel(micLevel);
    } else {
      const decay = setInterval(() => {
        setDisplayLevel((prev) => Math.max(prev * 0.85, 0));
      }, 50);
      return () => clearInterval(decay);
    }
  }, [micLevel, displayLevel]);

  const barWidth = Math.min(displayLevel * 40, 40);
  const barColor = displayLevel > 0.1 ? "#7ddf7d" : "#333";

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 4,
      padding: "12px 0",
    }}>
      {/* Orb */}
      <div
        key={pulseKey}
        style={{
          width: 44,
          height: 44,
          borderRadius: "50%",
          background: micActive ? colors.primary : "#444",
          boxShadow: micActive ? `0 0 20px ${colors.pulse}` : "none",
          animation: micActive ? "novaPulse 1.5s ease-in-out infinite" : "none",
          transition: "background 0.3s, box-shadow 0.3s",
          cursor: "pointer",
          opacity: micActive ? 1 : 0.5,
        }}
        onClick={onToggleMic}
        title={micActive ? "Mute mic" : "Unmute mic"}
      />

      {/* Mic level bar */}
      <div style={{
        width: 40, height: 3,
        background: "#222",
        borderRadius: 2,
        overflow: "hidden",
      }}>
        <div style={{
          width: barWidth,
          height: "100%",
          background: barColor,
          borderRadius: 2,
          transition: "width 0.1s, background 0.2s",
        }} />
      </div>

      {/* State label */}
      <div style={{
        fontSize: 10,
        color: micActive ? colors.primary : "#555",
        fontWeight: 600,
        letterSpacing: "0.05em",
        textTransform: "uppercase",
        transition: "color 0.3s",
      }}>
        {micActive ? colors.label : "MIC OFF"}
      </div>

      <style>{`
        @keyframes novaPulse {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50% { transform: scale(1.12); opacity: 1; }
        }
      `}</style>
    </div>
  );
}
