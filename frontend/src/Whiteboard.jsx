import { useState, useEffect, useRef, useCallback } from "react";
import { Stage, Layer, Text, Arrow as KonvaArrow, Circle, Rect } from "react-konva";

const WS_URL = `ws://${location.host}/ws`;
const RECONNECT_BASE_MS = 1000;

const BG_COLOR = "#1a1a2e";
const CHALK = "#f0f0e8";
const CHALK_YELLOW = "#ffe066";
const CHALK_BLUE = "#7ec8e3";
const CHALK_RED = "#ff6b6b";
const CHALK_GREEN = "#7ddf7d";

const FONT_FAMILY = "'Courier New', Courier, 'Georgia', serif";

let _textIdCounter = 0;
function nextTextId() {
  return `t_${++_textIdCounter}`;
}

export default function Whiteboard({ childId }) {
  const containerRef = useRef(null);
  const stageRef = useRef(null);
  const inputRef = useRef(null);
  const chatRef = useRef(null);
  const [dims, setDims] = useState({ width: 800, height: 600 });
  const [items, setItems] = useState([]);
  const [processing, setProcessing] = useState(false);
  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState("");
  const [connected, setConnected] = useState(false);

  const placedTextsRef = useRef([]);
  const queueRef = useRef([]);
  const processingRef = useRef(false);
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const mountedRef = useRef(true);

  // ── Container sizing ──────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observe = () => {
      const rect = el.getBoundingClientRect();
      setDims({ width: rect.width, height: rect.height });
    };
    observe();
    const ro = new ResizeObserver(observe);
    ro.observe(el);
    window.addEventListener("resize", observe);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", observe);
    };
  }, []);

  // Auto-scroll chat
  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  // ── WebSocket ─────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (!childId) return;
    if (!mountedRef.current) {
      console.log("[WS] skipped — not mounted");
      return;
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = `${WS_URL}/${childId}`;
    console.log("[WS] connecting to", url);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      console.log("[WS] connected");
      setConnected(true);
      ws.send(JSON.stringify({
        type: "session_start",
        child_id: childId,
        subject: "Math",
        topic: "",
      }));
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "whiteboard" && Array.isArray(msg.commands)) {
          enqueueCommands(msg.commands);
        }
        if (msg.type === "tutor_speech" && msg.text) {
          setMessages((prev) => [
            ...prev,
            { role: "nova", text: msg.text, time: Date.now() },
          ]);
        }
      } catch {
        // ignore malformed
      }
    };

    ws.onclose = (ev) => {
      if (wsRef.current !== ws) return;
      console.log("[WS] closed code=%d reason=%s", ev.code, ev.reason);
      setConnected(false);
      wsRef.current = null;
      if (!mountedRef.current) return;
      reconnectTimerRef.current = setTimeout(() => connect(), RECONNECT_BASE_MS);
    };

    ws.onerror = (err) => {
      if (wsRef.current !== ws) return;
      console.warn("[WS] error", err);
      ws.close();
    };
  }, [childId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ── Send message ──────────────────────────────────────────────────
  function sendMessage(text) {
    const msg = (text || inputText).trim();
    if (!msg) return;
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setMessages((prev) => [...prev, { role: "nova", text: "Connecting to server... please wait.", time: Date.now() }]);
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "speech", text: msg }));
    setMessages((prev) => [...prev, { role: "you", text: msg, time: Date.now() }]);
    setInputText("");
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── Browser voice input (Web Speech API) ──────────────────────────
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef(null);

  function toggleMic() {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setMessages((prev) => [...prev, { role: "nova", text: "Voice input is not supported in this browser. Try Chrome.", time: Date.now() }]);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (e) => {
      const transcript = e.results[0][0].transcript;
      sendMessage(transcript);
      setListening(false);
    };

    recognition.onerror = () => setListening(false);
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }

  // ── Command queue processing ──────────────────────────────────────
  function normalize(cmd) {
    const n = { ...cmd };
    if (n.type === "arrow") {
      if (Array.isArray(n.from)) { n.from_x = n.from[0]; n.from_y = n.from[1]; }
      if (Array.isArray(n.to)) { n.to_x = n.to[0]; n.to_y = n.to[1]; }
    }
    return n;
  }

  function enqueueCommands(commands) {
    queueRef.current.push(...commands.map(normalize));
    setProcessing(true);
    if (!processingRef.current) processNext();
  }

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
      const color = cmd.color ?? CHALK;
      setItems((prev) => [...prev, { id, type: "text", text: cmd.content, x: cmd.x, y: cmd.y, fontSize, fill: color, fontFamily: FONT_FAMILY }]);
      placedTextsRef.current.push({ id, text: cmd.content, x: cmd.x, y: cmd.y, width: fontSize * cmd.content.length * 0.6, height: fontSize * 1.4, fontSize });
      return;
    }
    if (type === "highlight") {
      const target = cmd.target_text;
      const color = cmd.color ?? CHALK_YELLOW;
      const pad = 6;
      const match = placedTextsRef.current.find((p) => p.text === target);
      const targets = match ? [match] : placedTextsRef.current.filter((p) => p.text.includes(target));
      setItems((prev) => [
        ...prev,
        ...targets.map((p) => ({
          id: `hl_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          type: "rect",
          x: p.x - pad, y: p.y - pad,
          width: p.width + pad * 2, height: p.height + pad * 2,
          fill: color, opacity: 0.35, cornerRadius: 4,
        })),
      ]);
      return;
    }
    if (type === "arrow") {
      setItems((prev) => [...prev, {
        id: `arr_${Date.now()}`, type: "arrow",
        points: [cmd.from_x ?? 0, cmd.from_y ?? 0, cmd.to_x ?? 0, cmd.to_y ?? 0],
        stroke: cmd.color ?? CHALK_BLUE, strokeWidth: 3, fill: cmd.color ?? CHALK_BLUE,
        pointerLength: 10, pointerWidth: 8,
      }]);
      return;
    }
    if (type === "circle") {
      const color = cmd.color ?? CHALK_YELLOW;
      setItems((prev) => [...prev, {
        id: `circ_${Date.now()}`, type: "circle",
        x: cmd.cx, y: cmd.cy, radius: cmd.r,
        stroke: color, strokeWidth: 3, fill: color + "22",
      }]);
      return;
    }
    if (type === "box") {
      const color = cmd.color ?? CHALK_BLUE;
      setItems((prev) => [...prev, {
        id: `box_${Date.now()}`, type: "rect",
        x: cmd.x, y: cmd.y, width: cmd.width, height: cmd.height,
        stroke: color, strokeWidth: 3, fill: color + "18",
        cornerRadius: cmd.cornerRadius ?? 0,
      }]);
    }
  }

  // ── Render ────────────────────────────────────────────────────────
  const CHAT_WIDTH = 320;
  const INPUT_H = 56;
  const indicatorY = dims.height - 40;

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%", position: "relative", background: BG_COLOR }}>
      {/* Konva canvas */}
      <Stage ref={stageRef} width={dims.width} height={dims.height} style={{ background: BG_COLOR }}>
        <Layer>
          <Rect x={0} y={0} width={dims.width} height={dims.height} fill={BG_COLOR} />
          {items.map((item) => {
            switch (item.type) {
              case "text":
                return <Text key={item.id} x={item.x} y={item.y} text={item.text} fontSize={item.fontSize} fill={item.fill} fontFamily={item.fontFamily} />;
              case "rect":
                return <Rect key={item.id} x={item.x} y={item.y} width={item.width} height={item.height} fill={item.fill} opacity={item.opacity ?? 1} cornerRadius={item.cornerRadius ?? 0} stroke={item.stroke} strokeWidth={item.strokeWidth} />;
              case "circle":
                return <Circle key={item.id} x={item.x} y={item.y} radius={item.radius} stroke={item.stroke} strokeWidth={item.strokeWidth} fill={item.fill} />;
              case "arrow":
                return <KonvaArrow key={item.id} points={item.points} stroke={item.stroke} strokeWidth={item.strokeWidth} fill={item.fill} pointerLength={item.pointerLength} pointerWidth={item.pointerWidth} />;
              default:
                return null;
            }
          })}
          {processing && (
            <Text x={20} y={indicatorY} text="✦ Nova is explaining..." fontSize={16} fill={CHALK_GREEN} fontFamily={FONT_FAMILY} opacity={0.85} />
          )}
        </Layer>
      </Stage>

      {/* Connection indicator */}
      <div style={{
        position: "absolute", top: 12, right: CHAT_WIDTH + 24,
        display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: connected ? "#7ddf7d" : "#ef4444",
      }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: connected ? "#7ddf7d" : "#ef4444", display: "inline-block" }} />
        {connected ? "Connected" : "Disconnected"}
      </div>

      {/* Chat panel */}
      <div style={{
        position: "absolute", top: 0, right: 0, width: CHAT_WIDTH, height: "100%",
        display: "flex", flexDirection: "column", borderLeft: "1px solid #333",
        background: "rgba(20, 20, 35, 0.95)",
      }}>
        {/* Header */}
        <div style={{ padding: "12px 14px", borderBottom: "1px solid #333", fontSize: 13, fontWeight: 600, color: "#a78bfa" }}>
          💬 Chat with Nova
        </div>

        {/* Messages */}
        <div ref={chatRef} style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
          {messages.length === 0 && (
            <div style={{ color: "#666", fontSize: 12, textAlign: "center", marginTop: 40 }}>
              Type a message to start chatting.<br />
              Nova will respond with speech and drawings.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{
              alignSelf: m.role === "you" ? "flex-end" : "flex-start",
              maxWidth: "85%",
              padding: "8px 12px",
              borderRadius: 12,
              fontSize: 13,
              lineHeight: 1.4,
              background: m.role === "you" ? "#6d28d9" : "#2d2d4a",
              color: "#eee",
            }}>
              <div style={{ fontSize: 10, color: "#888", marginBottom: 2 }}>
                {m.role === "you" ? "You" : "Nova"}
              </div>
              {m.text}
            </div>
          ))}
        </div>

        {/* Input */}
        <div style={{ padding: "8px 10px", borderTop: "1px solid #333", display: "flex", gap: 6, alignItems: "center" }}>
          <input
            ref={inputRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={connected ? "Type or tap the mic..." : "Connecting..."}
            disabled={false}
            style={{
              flex: 1, padding: "10px 12px", borderRadius: 10, border: "1px solid #444",
              background: "#1a1a2e", color: "#eee", fontSize: 13, outline: "none",
            }}
          />
          <button
            onClick={toggleMic}
            disabled={false}
            title={!connected ? "Waiting for connection..." : listening ? "Stop recording" : "Speak via mic"}
            style={{
              width: 38, height: 38, borderRadius: "50%", border: "none",
              background: listening ? "#dc2626" : "#374151",
              color: "#fff", fontSize: 18, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "background 0.2s", opacity: connected ? 1 : 0.5,
            }}
          >
            {listening ? "■" : "🎤"}
          </button>
          <button
            onClick={() => sendMessage()}
            disabled={!inputText.trim()}
            style={{
              padding: "10px 14px", borderRadius: 10, border: "none",
              background: "#7c3aed", color: "#fff",
              fontSize: 13, cursor: "pointer", opacity: connected ? 1 : 0.5,
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
