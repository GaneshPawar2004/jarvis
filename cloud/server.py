"""JARVIS cloud server: the brain on the internet (Render), so the user can chat or talk from
their phone even when the laptop is off. Password-protected; HTTPS is provided by Render.

Run locally:  uvicorn cloud.server:app --port 8780
On Render:    uvicorn cloud.server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips=*
"""
import asyncio
import hashlib
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.genai import types
from starlette.concurrency import run_in_threadpool

import config
from core import db, history, memory
from core.brain import Brain
from interfaces.hud import auth
from interfaces.hud import login as pages
from cloud.agents import Agents, create_device, device_name
from interfaces.hud.session import ask_brain, serve_chat
from skills import cloud_tools

STATIC = Path(__file__).resolve().parent.parent / "interfaces" / "hud" / "static"
PUBLIC_PATHS = {"/login", "/healthz", "/api/pair", "/static/manifest.json", "/static/icon-192.png", "/static/icon-512.png"}
COOKIE = "jarvis_cloud_session"
SESSION_DAYS = 30
GLOBAL_FAILURE_LIMIT = 10  # wrong passwords from anywhere within the window lock all logins
GLOBAL_WINDOW = 15 * 60

def _context(laptop: bool, phone: bool) -> str:
    """Where JARVIS is running and which devices it can reach right now."""
    parts = ["now running on a cloud server, so the user can reach you even when their laptop "
             "is off; they are probably talking to you from their phone"]
    if phone:
        parts.append("The JARVIS app on the user's Android phone is CONNECTED: the phone_* tools act "
                     "directly on the phone (no laptop needed). The user may be looking at the "
                     "phone screen while you work")
    if laptop:
        parts.append("The user's Windows laptop is ONLINE: you can control it with the laptop tools"
                     + ("" if phone else ", and the phone through the laptop with the phone_* tools "
                        "(the phone must be on the same Wi-Fi as the laptop)"))
    else:
        parts.append("The user's laptop is OFFLINE, so laptop tools are unavailable; if asked, say so")
    if not laptop and not phone:
        parts.append("The phone can't be controlled right now either (no JARVIS app or laptop connected)")
    return ". ".join(parts)


CLOUD_CONTEXT = _context(laptop=False, phone=False)

PASSWORD = os.getenv("JARVIS_PASSWORD", "")
ALLOWED_HOSTS = {
    h.strip()
    for h in [os.getenv("RENDER_EXTERNAL_HOSTNAME", ""), *os.getenv("JARVIS_ALLOWED_HOSTS", "").split(",")]
    if h.strip()
} | {"localhost:8780", "127.0.0.1:8780"}

brain: Brain | None = None
brain_lock = asyncio.Lock()
_global_failures: list[float] = []


async def _devices_changed(event: str) -> None:
    """Give the brain the tools of whichever devices are connected right now. When the
    phone app is connected, its phone_* tools replace the laptop's ADB-based ones."""
    async with brain_lock:
        tools, handlers, declared = cloud_tools(), {}, []
        for kind in ("phone", "laptop"):
            agent = agents.devices.get(kind)
            if agent is None:
                continue
            fresh = [d for d in agent.declarations if d.name not in handlers
                     # with the phone app connected, the laptop's ADB phone tools would be a confusing duplicate
                     and not (kind == "laptop" and agents.phone and d.name.startswith("phone_"))]
            declared += fresh
            handlers |= {d.name: agents.proxy(d.name, kind) for d in fresh}
        if declared:
            tools = tools + [types.Tool(function_declarations=declared)]
        brain.set_tools(tools, _context(agents.laptop is not None, agents.phone is not None), handlers)
        brain.note(event)


async def _app_chat(agent, text: str, on_tool, ask_user) -> dict:
    return await ask_brain(brain, brain_lock, text, on_tool, ask_user)


agents = Agents(on_change=_devices_changed, on_chat=_app_chat)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain
    if len(PASSWORD) < 12:
        raise RuntimeError("Set JARVIS_PASSWORD (at least 12 characters) before starting the cloud server.")
    brain = await run_in_threadpool(Brain, None, cloud_tools(), CLOUD_CONTEXT)
    yield
    await run_in_threadpool(brain.close)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _valid_session(token: str | None) -> bool:
    if not token:
        return False
    found = db.rows("SELECT expires FROM sessions WHERE token_hash = ?", (_hash(token),))
    return bool(found and found[0][0] > time.time())


def _new_session() -> str:
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    db.execute("INSERT INTO sessions (token_hash, expires) VALUES (?, ?)",
               (_hash(token), time.time() + SESSION_DAYS * 86400))
    return token


def _globally_locked() -> int:
    now = time.time()
    _global_failures[:] = [t for t in _global_failures if t > now - GLOBAL_WINDOW]
    if len(_global_failures) >= GLOBAL_FAILURE_LIMIT:
        return int(_global_failures[0] + GLOBAL_WINDOW - now) + 1
    return 0


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.headers.get("host") not in ALLOWED_HOSTS:  # blocks DNS-rebinding tricks
        return JSONResponse({"error": "unknown host"}, status_code=400)
    path = request.url.path
    if path in PUBLIC_PATHS or await run_in_threadpool(_valid_session, request.cookies.get(COOKIE)):
        response = await call_next(request)
    elif path == "/":
        response = RedirectResponse("/login")
    else:
        response = JSONResponse({"error": "login required"}, status_code=401)
    response.headers.update({
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        # not "no-referrer": that makes browsers send "Origin: null" on the login form,
        # which the origin check (rightly) rejects
        "Referrer-Policy": "same-origin",
        "Strict-Transport-Security": "max-age=31536000",
    })
    return response


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login_page(error: str = "") -> HTMLResponse:
    return HTMLResponse(pages.password_page(error))


async def _check_password(request: Request, attempt: str) -> str | None:
    """None if the password is right, otherwise the message to show."""
    ip = request.client.host if request.client else "unknown"
    wait = max(auth.locked_out(ip), _globally_locked())
    if wait:
        return f"Too many wrong passwords. Try again in {(wait + 59) // 60} min."
    if not hmac.compare_digest(attempt.encode(), PASSWORD.encode()):
        auth.record_failure(ip)
        _global_failures.append(time.time())
        await asyncio.sleep(1)  # slow down guessing
        return "Wrong password."
    return None


@app.post("/login")
async def login(request: Request):
    if not auth.same_origin(request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    attempt = parse_qs((await request.body()).decode()).get("password", [""])[0]
    problem = await _check_password(request, attempt)
    if problem:
        return login_page(problem)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, await run_in_threadpool(_new_session), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=True, samesite="strict")
    return response


@app.post("/api/pair")
async def pair(request: Request):
    """A device (the laptop agent) trades the password, once, for its own device key."""
    if not auth.same_origin(request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("not an object")
    except Exception:
        return JSONResponse({"error": "expected JSON with password and name"}, status_code=400)
    problem = await _check_password(request, str(body.get("password", "")))
    if problem:
        return JSONResponse({"error": problem}, status_code=401)
    token = await run_in_threadpool(create_device, str(body.get("name", "laptop")))
    return {"token": token}


@app.get("/api/stats")
def stats() -> dict:
    # no laptop gauges in cloud mode; the page hides that panel
    return {"cloud": True, "laptop_online": agents.laptop is not None, "phone_online": agents.phone is not None}


@app.get("/api/memory")
def memory_view() -> dict:
    return {
        "user": config.USER_NAME,
        "facts": memory.all_facts(),
        "summaries": [{"when": w, "text": t} for w, t in history.recent_summaries(limit=8)],
    }


@app.websocket("/ws")
async def chat(ws: WebSocket) -> None:
    if (
        ws.headers.get("host") not in ALLOWED_HOSTS
        or not auth.same_origin(ws.headers.get("origin"), ws.headers.get("host"))
        or not await run_in_threadpool(_valid_session, ws.cookies.get(COOKIE))
    ):
        await ws.close(code=1008)
        return
    await ws.accept()
    await serve_chat(ws, brain, brain_lock)


@app.websocket("/agent")
async def agent_link(ws: WebSocket) -> None:
    """The laptop agent's connection. Authenticated by its device key in the Authorization
    header, which browsers can't set, so web pages can't open this socket."""
    header = ws.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None
    name = await run_in_threadpool(device_name, token)
    if ws.headers.get("host") not in ALLOWED_HOSTS or name is None:
        await ws.close(code=1008)
        return
    await ws.accept()
    await agents.serve(ws, name)
