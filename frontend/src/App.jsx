import Whiteboard from "./Whiteboard";

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const childId = params.get("child_id") || "local_child";

  return (
    <div style={{ width: "100%", height: "100%", background: "#1a1a2e" }}>
      <Whiteboard childId={childId} />
    </div>
  );
}
