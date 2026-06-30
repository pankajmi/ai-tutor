import { useState, useRef, useEffect, useCallback } from "react";
import { VoiceSessionContext } from "./VoiceSessionContext";
import VoiceStateOrb from "./VoiceStateOrb";
import ConversationCanvas from "./ConversationCanvas";
import TranscriptDrawer from "./TranscriptDrawer";
import { AudioStreamer } from "./AudioStreamer";
import { AudioPlayer } from "./AudioPlayer";

const WS_URL = `ws://${location.host}/ws`;
const RECONNECT_BASE_MS = 1000;
const BG_COLOR = "#1a1a2e";

let _textIdCounter = 0;
function nextTextId() {
  return `t_${++_textIdCounter}`;
}

function normalize(cmd) {
  const n = { ...cmd };
  if (n.type === "arrow") {
    if (Array.isArray(n.from)) {
      n.from_x = n.from[0];
      n.from_y = n.from[1];
    }
    if (Array.isArray(n.to)) {
      n.to_x = n.to[0];
      n.to_y = n.to[1];
    }
  }
  return n;
}

export default function VoiceSessionShell({ childId }) {
  // ── Core state ───────────────────────────────────────────────────
  const [voiceState, setVoiceState] = useState("idle");
  const [connected, setConnected] = useState(false);
  const [micActive, setMicActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [messages, setMessages] = useState([]);
  const [items, setItems] = useState([]);
  const [processing, setProcessing] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const [canvasExpanded, setCanvasExpanded] = useState(false);

  // ── Refs ─────────────────────────────────────────────────────────
  const wsRef = useRef(null);
  const streamerRef = useRef(null);
  const playerRef = useRef(null);
  const mountedRef = useRef(true);
  const reconnectTimerRef = useRef(null);
  const sessionStartedRef = useRef(false);
  const placedTextsRef = useRef([]);
  const queueRef = useRef([]);
  const processingRef = useRef(false);
  const stageRef = useRef(null);

  // Automatically mark "listening" when mic level is active (child
  // speaking) while in idle state.
  const listeningThreshold = 0.04;
  const listeningHoldRef = useRef(0);

  // ── WebSocket ────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (!childId) return;
    if (!mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    _stopAudio();

    const url = `${WS_URL}/${childId}`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    sessionStartedRef.current = false;

    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setConnected(true);
      ws.send(
        JSON.stringify({
          type: "session_start",
          child_id: childId,
          subject: "Math",
          topic: "",
        })
      );
      sessionStartedRef.current = true;
      _startAudio(ws);
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;
      if (typeof ev.data === "string") {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "tutor_speech" && msg.text) {
            setMessages((prev) => [
              ...prev,
              { role: "nova", text: msg.text, time: Date.now() },
            ]);
            setVoiceState("speaking");
          }
          if (msg.type === "whiteboard" && Array.isArray(msg.commands)) {
            enqueueCommands(msg.commands);
          }
          if (msg.type === "transcription" && msg.text) {
            setMessages((prev) => [
              ...prev,
              { role: "you", text: msg.text, time: Date.now() },
            ]);
          }
          if (msg.type === "emotion") {
            if (msg.signal === "encouraging" || msg.signal === "redirecting") {
              setVoiceState("speaking");
            }
          }
        } catch {
          // ignore malformed
        }
      } else {
        if (playerRef.current) {
          playerRef.current.enqueue(ev.data);
          setVoiceState("speaking");
        }
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      setConnected(false);
      setMicActive(false);
      setVoiceState("idle");
      wsRef.current = null;
      if (!mountedRef.current) return;
      reconnectTimerRef.current = setTimeout(() => connect(), RECONNECT_BASE_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [childId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      _stopAudio();
      wsRef.current?.close();
    };
  }, [connect]);

  // ── Audio pipeline ───────────────────────────────────────────────
  async function _startAudio(ws) {
    try {
      playerRef.current = new AudioPlayer();
      await playerRef.current.start();

      streamerRef.current = new AudioStreamer(ws, (level) => setMicLevel(level));
      await streamerRef.current.start();
      setMicActive(true);
      setVoiceState("idle");
    } catch (err) {
      console.warn("Audio pipeline init failed:", err);
      setMicActive(false);
    }
  }

  function _stopAudio() {
    if (streamerRef.current) {
      streamerRef.current.stop();
      streamerRef.current = null;
    }
    if (playerRef.current) {
      playerRef.current.stop();
      playerRef.current = null;
    }
    setMicActive(false);
  }

  function toggleMic() {
    if (micActive) {
      _stopAudio();
      setVoiceState("idle");
    } else {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        _startAudio(ws);
      }
    }
  }

  // ── Listening inference ──────────────────────────────────────────
  // When idle + mic level is consistently above threshold, show
  // "listening" state (child is speaking). Decay back to idle after
  // sustained silence.
  useEffect(() => {
    if (voiceState === "idle" || voiceState === "listening") {
      if (micLevel > listeningThreshold) {
        listeningHoldRef.current = 0;
        setVoiceState("listening");
      } else {
        listeningHoldRef.current++;
        // After ~500ms of silence while listening, revert to idle
        if (listeningHoldRef.current > 5 && voiceState === "listening") {
          setVoiceState("idle");
        }
      }
    }
  }, [micLevel, voiceState]);

  // ── Speaking → idle drain detection ─────────────────────────────
  useEffect(() => {
    if (voiceState === "speaking") {
      const check = setInterval(() => {
        if (playerRef.current && !playerRef.current.playing) {
          setVoiceState("idle");
          clearInterval(check);
        }
      }, 200);
      setTimeout(() => clearInterval(check), 10000);
    }
  }, [voiceState]);

  // ── Send message ─────────────────────────────────────────────────
  function sendMessage(text) {
    const msg = text.trim();
    if (!msg) return;
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setMessages((prev) => [
        ...prev,
        {
          role: "nova",
          text: "Connecting to server... please wait.",
          time: Date.now(),
        },
      ]);
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "speech", text: msg }));
    setMessages((prev) => [...prev, { role: "you", text: msg, time: Date.now() }]);
    setVoiceState("thinking");
  }

  // ── Command queue (Konva draw commands) ──────────────────────────
  function enqueueCommands(commands) {
    queueRef.current.push(...commands.map(normalize));
    setProcessing(true);
    setCanvasExpanded(true);
    if (!processingRef.current) processNext();
  }

  // Expose for demo.html toolbar (no WebSocket needed for draw test)
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.__enqueueCommands = enqueueCommands;
    }
    return () => {
      if (typeof window !== "undefined") {
        delete window.__enqueueCommands;
      }
    };
  }, []);

  function processNext() {
    if (!mountedRef.current) return;
    const cmd = queueRef.current.shift();
    if (!cmd) {
      processingRef.current = false;
      setProcessing(false);
      return;
    }
    processingRef.current = true;
    setTimeout(() => {
      if (!mountedRef.current) return;
      applyCommand(cmd);
      processNext();
    }, cmd.delay_ms ?? 0);
  }

  function applyCommand(cmd) {
    const { type } = cmd;
    if (type === "clear") {
      placedTextsRef.current = [];
      setItems([]);
      return;
    }
    if (type === "write") {
      const id = nextTextId();
      const fontSize = cmd.font_size ?? 28;
      const color = cmd.color ?? "#f0f0e8";
      setItems((prev) => [
        ...prev,
        {
          id,
          type: "text",
          text: cmd.content,
          x: cmd.x,
          y: cmd.y,
          fontSize,
          fill: color,
          fontFamily: "'Courier New', Courier, 'Georgia', serif",
        },
      ]);
      placedTextsRef.current.push({
        id,
        text: cmd.content,
        x: cmd.x,
        y: cmd.y,
        width: fontSize * cmd.content.length * 0.6,
        height: fontSize * 1.4,
        fontSize,
      });
      return;
    }
    if (type === "highlight") {
      const target = cmd.target_text;
      const color = cmd.color ?? "#ffe066";
      const pad = 6;
      const match = placedTextsRef.current.find((p) => p.text === target);
      const targets = match
        ? [match]
        : placedTextsRef.current.filter((p) => p.text.includes(target));
      setItems((prev) => [
        ...prev,
        ...targets.map((p) => ({
          id: `hl_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          type: "rect",
          x: p.x - pad,
          y: p.y - pad,
          width: p.width + pad * 2,
          height: p.height + pad * 2,
          fill: color,
          opacity: 0.35,
          cornerRadius: 4,
        })),
      ]);
      return;
    }
    if (type === "arrow") {
      setItems((prev) => [
        ...prev,
        {
          id: `arr_${Date.now()}`,
          type: "arrow",
          points: [
            cmd.from_x ?? 0,
            cmd.from_y ?? 0,
            cmd.to_x ?? 0,
            cmd.to_y ?? 0,
          ],
          stroke: cmd.color ?? "#7ec8e3",
          strokeWidth: 3,
          fill: cmd.color ?? "#7ec8e3",
          pointerLength: 10,
          pointerWidth: 8,
        },
      ]);
      return;
    }
    if (type === "circle") {
      const color = cmd.color ?? "#ffe066";
      setItems((prev) => [
        ...prev,
        {
          id: `circ_${Date.now()}`,
          type: "circle",
          x: cmd.cx,
          y: cmd.cy,
          radius: cmd.r,
          stroke: color,
          strokeWidth: 3,
          fill: color + "22",
        },
      ]);
      return;
    }
    if (type === "box") {
      const color = cmd.color ?? "#7ec8e3";
      setItems((prev) => [
        ...prev,
        {
          id: `box_${Date.now()}`,
          type: "rect",
          x: cmd.x,
          y: cmd.y,
          width: cmd.width,
          height: cmd.height,
          stroke: color,
          strokeWidth: 3,
          fill: color + "18",
          cornerRadius: cmd.cornerRadius ?? 0,
        },
      ]);
    }
  }

  // ── Auto-collapse canvas after idle ──────────────────────────────
  useEffect(() => {
    if (!canvasExpanded) return;
    const timer = setTimeout(() => {
      if (!processingRef.current) {
        setCanvasExpanded(false);
      }
    }, 5000);
    return () => clearTimeout(timer);
  }, [canvasExpanded, items]);

  // ── Context value ────────────────────────────────────────────────
  const ctxValue = {
    voiceState,
    connected,
    micActive,
    micLevel,
    messages,
    items,
    processing,
    showTranscript,
    canvasExpanded,
    stageRef,
    sendMessage,
    toggleMic,
    setShowTranscript,
  };

  // ── Render ────────────────────────────────────────────────────────
  return (
    <VoiceSessionContext.Provider value={ctxValue}>
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: BG_COLOR,
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Main area: orb centered */}
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            position: "relative",
            minHeight: 0,
          }}
        >
          <VoiceStateOrb />

          {/* Transcript toggle — top-right corner */}
          <button
            onClick={() => setShowTranscript((v) => !v)}
            style={{
              position: "absolute",
              top: 16,
              right: 16,
              background: "rgba(255,255,255,0.06)",
              border: "1px solid #333",
              borderRadius: 8,
              color: "#888",
              cursor: "pointer",
              fontSize: 20,
              padding: "8px 10px",
              lineHeight: 1,
              zIndex: 10,
            }}
            title={showTranscript ? "Hide chat" : "Show chat"}
          >
            {showTranscript ? "✕" : "💬"}
          </button>

          {/* "Type instead" affordance — bottom-center, visible when drawer closed */}
          {!showTranscript && (
            <button
              onClick={() => setShowTranscript(true)}
              style={{
                position: "absolute",
                bottom: 16,
                background: "none",
                border: "none",
                color: "#555",
                cursor: "pointer",
                fontSize: 11,
                letterSpacing: "0.04em",
                opacity: 0.6,
                transition: "opacity 0.2s",
              }}
              onMouseEnter={(e) => (e.target.style.opacity = 1)}
              onMouseLeave={(e) => (e.target.style.opacity = 0.6)}
            >
              Type instead ⌨️
            </button>
          )}
        </div>

        {/* Bottom strip: conversation canvas */}
        <ConversationCanvas />

        {/* Slide-out transcript drawer */}
        <TranscriptDrawer />
      </div>
    </VoiceSessionContext.Provider>
  );
}
