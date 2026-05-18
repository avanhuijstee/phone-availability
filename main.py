import os
import hmac
import hashlib
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import json
from datetime import datetime, timezone

app = FastAPI()

APP_PASSWORD = os.environ.get("APP_PASSWORD", "belletje")

available_users: dict[str, str] = {}
connections: list[WebSocket] = []


def make_token(password: str) -> str:
    return hmac.new(password.encode(), b"phone-availability", hashlib.sha256).hexdigest()


def valid_token(token: str) -> bool:
    expected = make_token(APP_PASSWORD)
    return hmac.compare_digest(token, expected)


class PasswordRequest(BaseModel):
    password: str


@app.post("/verify")
async def verify(req: PasswordRequest):
    if req.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Ongeldig wachtwoord")
    return {"token": make_token(req.password)}


async def broadcast(message: dict):
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
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    if not valid_token(token):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    connections.append(websocket)

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
