"""
Jarvis hub: lets Friday (the phone app) use the same brain as desktop Jarvis.

Binds to localhost only. Expose it to your own devices with `tailscale serve`,
which adds HTTPS and restricts access to your tailnet.

Trust model: the phone does no voice recognition (Android speech-to-text is
on-device and the hub only receives text), so the tier is decided by WHICH TOKEN
the phone presents, never by anything else in the request:

  FRIDAY_TOKEN        -> household tier, speaker FRIDAY_SPEAKER
  FRIDAY_GUEST_TOKEN  -> guest tier,     speaker FRIDAY_GUEST_SPEAKER ("Phone Guest")

Each tier has its own session, so switching tiers never reuses the other
tier's history.

Note: conversations are printed to stdout, which journald keeps when run as a
service. Read them with `journalctl --user -u jarvis-hub`.

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
TOKEN = os.getenv("FRIDAY_TOKEN")                      # household
SPEAKER = os.getenv("FRIDAY_SPEAKER")                  # same name as your entry in household_voiceprints.json
GUEST_TOKEN = os.getenv("FRIDAY_GUEST_TOKEN")          # guest (optional: unset disables guest access)
GUEST_SPEAKER = os.getenv("FRIDAY_GUEST_SPEAKER", "Phone Guest")
PORT = int(os.getenv("JARVIS_HUB_PORT", "8765"))
SESSION_IDLE_SECONDS = 15 * 60

missing = [k for k, v in {"ANTHROPIC_API_KEY": API_KEY, "FRIDAY_TOKEN": TOKEN,
                          "FRIDAY_SPEAKER": SPEAKER}.items() if not v]
if missing:
    raise SystemExit(f"Missing in .env: {', '.join(missing)}")
if GUEST_TOKEN and GUEST_TOKEN == TOKEN:
    raise SystemExit("FRIDAY_GUEST_TOKEN must be different from FRIDAY_TOKEN.")
if not GUEST_TOKEN:
    print("[hub] FRIDAY_GUEST_TOKEN is not set: guest access from the phone is disabled.")

brain.ensure_dirs()
client = Anthropic(api_key=API_KEY)

app = FastAPI(title="Jarvis hub", docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Lock()
_sessions = {}  # tier -> brain.Session. One per tier, never shared.

SPEAKER_FOR_TIER = {"household": SPEAKER, "guest": GUEST_SPEAKER}


class ChatIn(BaseModel):
    text: str
    new_session: bool = False


class ChatOut(BaseModel):
    reply: str
    actions: list = []


def _tier_for(authorization):
    """Map the bearer token to a tier. The token is the only thing that decides it."""
    supplied = (authorization or "").encode()
    is_household = secrets.compare_digest(supplied, f"Bearer {TOKEN}".encode())
    is_guest = bool(GUEST_TOKEN) and secrets.compare_digest(
        supplied, f"Bearer {GUEST_TOKEN}".encode())
    if is_household:
        return "household"
    if is_guest:
        return "guest"
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    return {"ok": True, "tier": _tier_for(authorization)}


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, authorization: str | None = Header(default=None)):
    tier = _tier_for(authorization)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")

    speaker = SPEAKER_FOR_TIER[tier]
    with _lock:
        session = _sessions.get(tier)
        stale = session is None or (time.time() - session.last_active) > SESSION_IDLE_SECONDS
        if body.new_session or stale:
            session = brain.Session(client, speaker, tier, persona="friday", device="phone")
            _sessions[tier] = session
        print(f"[phone:{tier}] {speaker}: {text}")
        try:
            notice, reply = session.handle(text)
        except Exception as e:
            print(f"[phone:{tier}] error: {e}")
            raise HTTPException(status_code=502, detail=f"Brain error: {e}")
        print(f"[phone:{tier}] Friday: {reply}")
        actions = session.pending_actions

    return ChatOut(
        reply=" ".join(part for part in (notice, reply) if part),
        actions=actions,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)
