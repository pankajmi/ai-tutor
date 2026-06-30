import { useEffect, useState } from "react";
import { useVoiceSession } from "./VoiceSessionContext";

const STATE_STYLES = {
  idle: {
    primary: "#7ddf7d",
    glow: "#7ddf7d44",
    label: "Nova is listening",
    labelColor: "#7ddf7d",
  },
  listening: {
    primary: "#7ddf7d",
    glow: "#7ddf7daa",
    label: "I hear you",
    labelColor: "#7ddf7d",
  },
  thinking: {
    primary: "#f59e0b",
    glow: "#f59e0b44",
    label: "Nova is thinking",
    labelColor: "#f59e0b",
  },
  speaking: {
    primary: "#a78bfa",
    glow: "#a78bfa66",
    label: "Nova is speaking",
    labelColor: "#a78bfa",
  },
  barge_in: {
    primary: "#f472b6",
    glow: "#f472b644",
    label: "You interrupted!",
    labelColor: "#f472b6",
  },
};

const DISCONNECTED_STYLE = {
  primary: "#ef4444",
  glow: "#ef444444",
  label: "Disconnected",
  labelColor: "#ef4444",
};

const ORB_BASE_SIZE = 120;

export default function VoiceStateOrb() {
  const { voiceState, connected, micActive, micLevel, toggleMic } =
    useVoiceSession();

  const styles = connected
    ? STATE_STYLES[voiceState] || STATE_STYLES.idle
    : DISCONNECTED_STYLE;

  const [pulseKey, setPulseKey] = useState(0);
  useEffect(() => {
    setPulseKey((k) => k + 1);
  }, [voiceState]);

  // Smooth mic level for the level bar
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

  // Size scales up slightly when listening (mic-reactive) or speaking
  const scaleFactor =
    voiceState === "listening"
      ? 1 + displayLevel * 0.3
      : 1;

  const orbSize = ORB_BASE_SIZE * scaleFactor;
  const barWidth = Math.min(displayLevel * 80, 80);
  const ringOpacity = voiceState === "listening"
    ? 0.3 + displayLevel * 0.7
    : voiceState === "speaking"
    ? 0.5
    : 0.3;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        userSelect: "none",
      }}
    >
      {/* Orb + concentric rings */}
      <div style={{ position: "relative", width: ORB_BASE_SIZE * 2.5, height: ORB_BASE_SIZE * 2.5, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {/* Outer ring 3 */}
        <div
          style={{
            position: "absolute",
            width: ORB_BASE_SIZE * 2.2,
            height: ORB_BASE_SIZE * 2.2,
            borderRadius: "50%",
            border: `2px solid ${styles.primary}22`,
            opacity: ringOpacity * 0.3,
          }}
        />
        {/* Outer ring 2 */}
        <div
          style={{
            position: "absolute",
            width: ORB_BASE_SIZE * 1.7,
            height: ORB_BASE_SIZE * 1.7,
            borderRadius: "50%",
            border: `2px solid ${styles.primary}44`,
            opacity: ringOpacity * 0.6,
            animation: connected ? `novaOrbPulse 2s ease-in-out infinite` : "none",
          }}
        />
        {/* Outer ring 1 */}
        <div
          style={{
            position: "absolute",
            width: ORB_BASE_SIZE * 1.3,
            height: ORB_BASE_SIZE * 1.3,
            borderRadius: "50%",
            border: `2px solid ${styles.primary}66`,
            opacity: ringOpacity * 0.8,
            animation: connected && (voiceState === "listening" || voiceState === "speaking")
              ? `novaOrbPulse 1.5s ease-in-out infinite`
              : "none",
          }}
        />
        {/* Core orb */}
        <div
          key={pulseKey}
          style={{
            width: orbSize,
            height: orbSize,
            borderRadius: "50%",
            background: micActive ? styles.primary : "#444",
            boxShadow: micActive ? `0 0 ${40 * scaleFactor}px ${styles.glow}` : "none",
            cursor: "pointer",
            opacity: micActive ? 1 : 0.5,
            transition: "width 0.15s ease, height 0.15s ease, background 0.3s, box-shadow 0.3s",
            zIndex: 1,
            animation: connected
              ? voiceState === "thinking"
                ? "novaThink 0.8s ease-in-out infinite"
                : voiceState === "barge_in"
                ? "novaBargeIn 0.4s ease-in-out 3"
                : `novaPulse 1.5s ease-in-out infinite`
              : "none",
          }}
          onClick={toggleMic}
          title={micActive ? "Mute mic" : "Unmute mic"}
        />
      </div>

      {/* Mic level bar */}
      <div
        style={{
          width: 80,
          height: 4,
          background: "#222",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: barWidth,
            height: "100%",
            background: styles.primary,
            borderRadius: 2,
            transition: "width 0.1s, background 0.2s",
          }}
        />
      </div>

      {/* State label */}
      <div
        style={{
          fontSize: 14,
          color: micActive ? styles.labelColor : "#555",
          fontWeight: 600,
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          transition: "color 0.3s",
        }}
      >
        {micActive ? styles.label : "MIC OFF"}
      </div>

      <style>{`
        @keyframes novaPulse {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50% { transform: scale(1.1); opacity: 1; }
        }
        @keyframes novaThink {
          0%, 100% { transform: scale(1) rotate(0deg); opacity: 0.8; }
          25% { transform: scale(1.05) rotate(90deg); opacity: 0.9; }
          50% { transform: scale(1) rotate(180deg); opacity: 1; }
          75% { transform: scale(1.05) rotate(270deg); opacity: 0.9; }
        }
        @keyframes novaBargeIn {
          0%, 100% { transform: scale(1); opacity: 0.8; }
          50% { transform: scale(1.25); opacity: 1; }
        }
        @keyframes novaOrbPulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.08); opacity: 0.6; }
        }
      `}</style>
    </div>
  );
}


