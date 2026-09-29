"""
Jarvis hub: lets Friday (the phone app) use the same brain as desktop Jarvis.

Binds to localhost only. Expose it to your own devices with `tailscale serve`,
which adds HTTPS and restricts access to your tailnet. Every request also needs
the FRIDAY_TOKEN from .env.

Run from ~/desktopjarvis:  python server.py
"""
import os
import secrets
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic

import brain

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
API_KEY = os.getenv("ANTHROPIC_API_KEY")
TOKEN = os.getenv("FRIDAY_TOKEN")
SPEAKER = os.getenv("FRIDAY_SPEAKER")  # same name as your entry in household_voiceprints.json
PORT = int(os.getenv("JARVIS_HUB_PORT", "8765"))
SESSION_IDLE_SECONDS = 15 * 60

missing = [k for k, v in {"ANTHROPIC_API_KEY": API_KEY, "FRIDAY_TOKEN": TOKEN,
                          "FRIDAY_SPEAKER": SPEAKER}.items() if not v]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")

brain.ensure_dirs()
client = Anthropic(api_key=API_KEY)

app = FastAPI(title="Jarvis hub", docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()
_session = None


class ChatIn(BaseModel):
    text: str
    new_session: bool = False


class ChatOut(BaseModel):
    reply: str
    actions: list = []


def _check_token(authorization):
    expected = f"Bearer {TOKEN}"
    if not authorization or not secrets.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    _check_token(authorization)
    return {"ok": True}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, authorization: str | None = Header(default=None)):
    _check_token(authorization)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    global _session
    with _lock:
        stale = _session is None or (time.time() - _session.last_active) > SESSION_IDLE_SECONDS
        if body.new_session or stale:
            _session = brain.Session(client, SPEAKER, "household", persona="friday", device="phone")
        print(f"[phone] {SPEAKER}: {text}")
        try:
            notice, reply = _session.handle(text)
        except Exception as e:
            print(f"[phone] error: {e}")
            raise HTTPException(status_code=502, detail=f"Brain error: {e}")
        print(f"[phone] Friday: {reply}")
        actions = _session.pending_actions

    return ChatOut(
        reply=" ".join(part for part in (notice, reply) if part),
        actions=actions,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)
