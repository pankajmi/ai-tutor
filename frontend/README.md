# frontend

React app: Whiteboard (React + Konva.js) and Parent Dashboard.
Implementation begins at Build Layer 10 (Whiteboard) and Layer 11 (Dashboard).

Not yet scaffolded — to be initialized with Vite + React when reached:
```
npm create vite@latest . -- --template react
```

Expected layout (not yet created):
```
frontend/
  src/
    components/
      Whiteboard.jsx     # <Whiteboard childId="abc123" />
      Dashboard.jsx       # Parent-facing session summaries
    lib/
      ws.js                # WebSocket client
      api.js                # REST client
```
