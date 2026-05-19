import os
import hmac
import hashlib
import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timezone
from pywebpush import webpush, WebPushException
from py_vapid import Vapid

app = FastAPI()

APP_PASSWORD = os.environ.get("APP_PASSWORD", "belletje")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {"sub": "mailto:app@phone-availability.app"}

vapid = Vapid.from_string(VAPID_PRIVATE_KEY) if VAPID_PRIVATE_KEY else None

available_users: dict[str, str] = {}
connections: list[WebSocket] = []
push_subscriptions: list[dict] = []


def make_token(password: str) -> str:
    return hmac.new(password.encode(), b"phone-availability", hashlib.sha256).hexdigest()


def valid_token(token: str) -> bool:
    expected = make_token(APP_PASSWORD)
    return hmac.compare_digest(token, expected)


class PasswordRequest(BaseModel):
    password: str


class SubscribeRequest(BaseModel):
    token: str
    subscription: dict


@app.post("/verify")
async def verify(req: PasswordRequest):
    if req.password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="Ongeldig wachtwoord")
    return {"token": make_token(req.password)}


@app.post("/subscribe")
async def subscribe(req: SubscribeRequest):
    if not valid_token(req.token):
        raise HTTPException(status_code=401)
    for existing in push_subscriptions:
        if existing.get("endpoint") == req.subscription.get("endpoint"):
            push_subscriptions.remove(existing)
            break
    push_subscriptions.append(req.subscription)
    print(f"[PUSH] Subscription geregistreerd. Totaal: {len(push_subscriptions)}")
    return {"ok": True}


async def send_push(title: str, body: str, skip_endpoint: str = None):
    if not vapid:
        print("[PUSH] Geen VAPID sleutel ingesteld")
        return
    print(f"[PUSH] Versturen naar {len(push_subscriptions)} apparaten...")
    data = json.dumps({"title": title, "body": body})
    for sub in push_subscriptions[:]:
        if skip_endpoint and sub.get("endpoint") == skip_endpoint:
            continue
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=sub,
                data=data,
                vapid_private_key=vapid,
                vapid_claims=VAPID_CLAIMS,
            )
            print("[PUSH] Succesvol verstuurd")
        except WebPushException as e:
            print(f"[PUSH] Fout: {e.response.status_code if e.response else e}")
            if e.response and e.response.status_code in (404, 410):
                push_subscriptions.remove(sub)
        except Exception as e:
            print(f"[PUSH] Onverwachte fout: {e}")


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
        await websocket.accept()
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
                asyncio.create_task(send_push(
                    f"📞 {name} is beschikbaar!",
                    f"{name} is nu beschikbaar voor een belletje."
                ))
            elif msg["type"] == "unavailable":
                available_users.pop(name, None)
                await broadcast({"type": "unavailable", "name": name})

    except WebSocketDisconnect:
        connections.remove(websocket)


@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
