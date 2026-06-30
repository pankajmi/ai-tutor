# backend

FastAPI application: WebSocket endpoint (voice/whiteboard streaming) + REST
endpoints (parent dashboard). Implementation begins at Build Layer 9.

Expected layout (not yet created):
```
backend/
  app/
    main.py          # FastAPI app instance, startup/shutdown
    websocket.py      # ws://localhost:8000/ws/{child_id}
    routes/           # REST endpoints
    db/                # SQLAlchemy models, session, migrations (Alembic)
    voice/             # STT / VAD / TTS managers
```
