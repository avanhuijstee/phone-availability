from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from datetime import datetime, timezone

app = FastAPI()

# In-memory storage: name -> {"since": ISO timestamp}
available_users: dict[str, str] = {}

# Active WebSocket connections
connections: list[WebSocket] = []


async def broadcast(message: dict):
    """Send a message to all connected clients."""
    data = json.dumps(message)
    disconnected = []
    for ws in connections:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connections.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)

    # Send current state to the new connection
    await websocket.send_text(json.dumps({
        "type": "state",
        "users": available_users,
    }))

    try:
        async for raw in websocket.iter_text():
            msg = json.loads(raw)
            name = msg.get("name", "").strip()
            if not name:
                continue

            if msg["type"] == "available":
                available_users[name] = datetime.now(timezone.utc).isoformat()
                await broadcast({"type": "available", "name": name, "since": available_users[name]})

            elif msg["type"] == "unavailable":
                available_users.pop(name, None)
                await broadcast({"type": "unavailable", "name": name})

    except WebSocketDisconnect:
        connections.remove(websocket)


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
