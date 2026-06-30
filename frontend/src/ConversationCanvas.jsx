import { useEffect, useRef, useState } from "react";
import { Stage, Layer, Text, Arrow as KonvaArrow, Circle, Rect } from "react-konva";
import { useVoiceSession } from "./VoiceSessionContext";

const FONT_FAMILY = "'Courier New', Courier, 'Georgia', serif";

const CANVAS_COLLAPSED_H = 100;
const CANVAS_EXPANDED_H = 280;

export default function ConversationCanvas() {
  const { items, processing, canvasExpanded } = useVoiceSession();
  const containerRef = useRef(null);
  const [width, setWidth] = useState(600);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observe = () => {
      if (el.offsetWidth > 0) setWidth(el.offsetWidth);
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

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: canvasExpanded ? CANVAS_EXPANDED_H : CANVAS_COLLAPSED_H,
        borderTop: "1px solid #2a2a3e",
        background: "#1a1a2e",
        overflow: "hidden",
        transition: "height 0.4s ease",
        flexShrink: 0,
      }}
    >
      <Stage width={width} height={canvasExpanded ? CANVAS_EXPANDED_H : CANVAS_COLLAPSED_H} style={{ background: "#1a1a2e" }}>
        <Layer>
          <Rect x={0} y={0} width={width} height={canvasExpanded ? CANVAS_EXPANDED_H : CANVAS_COLLAPSED_H} fill="#1a1a2e" />
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
                    fontFamily={FONT_FAMILY}
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
          {processing && (
            <Text
              x={20}
              y={(canvasExpanded ? CANVAS_EXPANDED_H : CANVAS_COLLAPSED_H) - 30}
              text="✦ Nova is explaining..."
              fontSize={16}
              fill="#7ddf7d"
              fontFamily={FONT_FAMILY}
              opacity={0.85}
            />
          )}
        </Layer>
      </Stage>
    </div>
  );
}
