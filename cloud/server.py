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
from starlette.concurrency import run_in_threadpool

import config
from core import db, history, memory
from core.brain import Brain
from interfaces.hud import auth
from interfaces.hud import login as pages
from interfaces.hud.session import serve_chat
from skills import cloud_tools

STATIC = Path(__file__).resolve().parent.parent / "interfaces" / "hud" / "static"
PUBLIC_PATHS = {"/login", "/healthz", "/static/manifest.json", "/static/icon-192.png", "/static/icon-512.png"}
COOKIE = "jarvis_cloud_session"
SESSION_DAYS = 30
GLOBAL_FAILURE_LIMIT = 10  # wrong passwords from anywhere within the window lock all logins
GLOBAL_WINDOW = 15 * 60

CLOUD_CONTEXT = (
    "now running on a cloud server so the user can reach you from their phone even when "
    "their laptop is off. In this mode you can chat, search the web, check the time and use "
    "your memory, but you cannot control the user's laptop or phone yet (that is coming "
    "soon); if asked, say so briefly instead of trying"
)

PASSWORD = os.getenv("JARVIS_PASSWORD", "")
ALLOWED_HOSTS = {
    h.strip()
    for h in [os.getenv("RENDER_EXTERNAL_HOSTNAME", ""), *os.getenv("JARVIS_ALLOWED_HOSTS", "").split(",")]
    if h.strip()
} | {"localhost:8780", "127.0.0.1:8780"}

brain: Brain | None = None
brain_lock = asyncio.Lock()
_global_failures: list[float] = []


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
        "Referrer-Policy": "no-referrer",
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


@app.post("/login")
async def login(request: Request):
    if not auth.same_origin(request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    ip = request.client.host if request.client else "unknown"
    wait = max(auth.locked_out(ip), _globally_locked())
    if wait:
        return login_page(f"Too many wrong passwords. Try again in {(wait + 59) // 60} min.")
    attempt = parse_qs((await request.body()).decode()).get("password", [""])[0]
    if not hmac.compare_digest(attempt.encode(), PASSWORD.encode()):
        auth.record_failure(ip)
        _global_failures.append(time.time())
        await asyncio.sleep(1)  # slow down guessing
        return login_page("Wrong password.")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, await run_in_threadpool(_new_session), max_age=SESSION_DAYS * 86400,
                        httponly=True, secure=True, samesite="strict")
    return response


@app.get("/api/stats")
def stats() -> dict:
    return {"cloud": True}  # no laptop gauges in cloud mode; the page hides that panel


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
