import { useState, useEffect, useRef, useCallback } from "react";
import { Stage, Layer, Text, Arrow as KonvaArrow, Circle, Rect } from "react-konva";

const WS_URL = "ws://localhost:8000/ws";
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10000;

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
  const [dims, setDims] = useState({ width: 800, height: 600 });
  const [items, setItems] = useState([]);
  const [processing, setProcessing] = useState(false);

  // Mutable refs for command queue processing
  const placedTextsRef = useRef([]); // { id, text, x, y, width, height, fontSize }
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
      mountedRef.current = false;
    };
  }, []);

  // ── WebSocket ─────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (!childId || !mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${WS_URL}/${childId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      // Start the session
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
      } catch {
        // ignore malformed
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      if (!mountedRef.current) return;
      reconnectTimerRef.current = setTimeout(() => connect(), RECONNECT_BASE_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [childId]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ── Command queue processing ──────────────────────────────────────
  // Normalize a command: handle both the user-spec format (from/to arrays)
  // and the backend DrawCommand model_dump() format (from_x/from_y/to_x/to_y).
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

  function enqueueCommands(commands) {
    queueRef.current.push(...commands.map(normalize));
    setProcessing(true);
    if (!processingRef.current) {
      processNext();
    }
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
    const delay = cmd.delay_ms ?? 0;

    setTimeout(() => {
      if (!mountedRef.current) return;

      applyCommand(cmd);
      processNext();
    }, delay);
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
      const newItem = {
        id,
        type: "text",
        text: cmd.content,
        x: cmd.x,
        y: cmd.y,
        fontSize,
        fill: color,
        fontFamily: FONT_FAMILY,
      };
      placedTextsRef.current.push({
        id,
        text: cmd.content,
        x: cmd.x,
        y: cmd.y,
        width: fontSize * cmd.content.length * 0.6,
        height: fontSize * 1.4,
        fontSize,
      });
      setItems((prev) => [...prev, newItem]);
      return;
    }

    if (type === "highlight") {
      const target = cmd.target_text;
      const color = cmd.color ?? CHALK_YELLOW;
      const match = placedTextsRef.current.find((p) => p.text === target);
      if (match) {
        const pad = 6;
        setItems((prev) => [
          ...prev,
          {
            id: `hl_${Date.now()}`,
            type: "rect",
            x: match.x - pad,
            y: match.y - pad,
            width: match.width + pad * 2,
            height: match.height + pad * 2,
            fill: color,
            opacity: 0.35,
            cornerRadius: 4,
          },
        ]);
      } else {
        const partials = placedTextsRef.current.filter((p) =>
          p.text.includes(target),
        );
        const pad = 6;
        setItems((prev) => [
          ...prev,
          ...partials.map((p) => ({
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
      }
      return;
    }

    if (type === "arrow") {
      const color = cmd.color ?? CHALK_BLUE;
      const x1 = cmd.from_x ?? 0;
      const y1 = cmd.from_y ?? 0;
      const x2 = cmd.to_x ?? 0;
      const y2 = cmd.to_y ?? 0;
      setItems((prev) => [
        ...prev,
        {
          id: `arr_${Date.now()}`,
          type: "arrow",
          points: [x1, y1, x2, y2],
          stroke: color,
          strokeWidth: 3,
          fill: color,
          pointerLength: 10,
          pointerWidth: 8,
        },
      ]);
      return;
    }

    if (type === "circle") {
      const color = cmd.color ?? CHALK_YELLOW;
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
          fill: color ? color + "22" : undefined,
        },
      ]);
      return;
    }

    if (type === "box") {
      const color = cmd.color ?? CHALK_BLUE;
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
          fill: color ? color + "18" : undefined,
          cornerRadius: cmd.cornerRadius ?? 0,
        },
      ]);
      return;
    }
  }

  // ── Render ────────────────────────────────────────────────────────
  const indicatorSize = 20;
  const indicatorY = dims.height - 40;

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%" }}>
      <Stage
        ref={stageRef}
        width={dims.width}
        height={dims.height}
        style={{ background: BG_COLOR }}
      >
        <Layer>
          {/* Board background */}
          <Rect
            x={0}
            y={0}
            width={dims.width}
            height={dims.height}
            fill={BG_COLOR}
          />

          {/* Items */}
          {items.map((item) => {
            switch (item.type) {
              case "text":
                return (
                  <Text
                    key={item.id}
                    x={item.x}
                    y={item.y}
                    text={item.text}
                    fontSize={item.fontSize}
                    fill={item.fill}
                    fontFamily={item.fontFamily}
                  />
                );
              case "rect":
                return (
                  <Rect
                    key={item.id}
                    x={item.x}
                    y={item.y}
                    width={item.width}
                    height={item.height}
                    fill={item.fill}
                    opacity={item.opacity ?? 1}
                    cornerRadius={item.cornerRadius ?? 0}
                    stroke={item.stroke}
                    strokeWidth={item.strokeWidth}
                  />
                );
              case "circle":
                return (
                  <Circle
                    key={item.id}
                    x={item.x}
                    y={item.y}
                    radius={item.radius}
                    stroke={item.stroke}
                    strokeWidth={item.strokeWidth}
                    fill={item.fill}
                  />
                );
              case "arrow":
                return (
                  <KonvaArrow
                    key={item.id}
                    points={item.points}
                    stroke={item.stroke}
                    strokeWidth={item.strokeWidth}
                    fill={item.fill}
                    pointerLength={item.pointerLength}
                    pointerWidth={item.pointerWidth}
                  />
                );
              default:
                return null;
            }
          })}

          {/* "Nova is explaining..." indicator */}
          {processing && (
            <Text
              x={20}
              y={indicatorY}
              text="✦ Nova is explaining..."
              fontSize={16}
              fill={CHALK_GREEN}
              fontFamily={FONT_FAMILY}
              opacity={0.85}
            />
          )}
        </Layer>
      </Stage>
    </div>
  );
}
