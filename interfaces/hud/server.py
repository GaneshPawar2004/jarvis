"""HUD: an Iron Man-style browser dashboard, served locally, that talks to the Brain."""
import asyncio
import os
import socket
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

import psutil
import qrcode
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config
from core import history, memory
from core.remote import connect_brain
from interfaces.hud import auth
from interfaces.hud import login as pages
from interfaces.hud.session import serve_chat

PORT = 8765
STATIC = Path(__file__).parent / "static"
PUBLIC_PATHS = {"/login", "/static/manifest.json", "/static/icon-192.png", "/static/icon-512.png"}

brain = None  # the shared cloud brain (or the laptop's own brain when offline)
brain_lock = asyncio.Lock()
_net = {"time": time.monotonic(), "counters": psutil.net_io_counters()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain
    brain, note = await run_in_threadpool(connect_brain)
    print(note)
    yield
    await run_in_threadpool(brain.close)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
allowed_hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}  # LAN address added in Wi-Fi mode


def lan_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the Wi-Fi interface
        return s.getsockname()[0]


def _authorised(client_ip: str | None, cookies: dict) -> bool:
    return auth.is_loopback(client_ip) or auth.valid_session(cookies.get(auth.COOKIE))


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.headers.get("host") not in allowed_hosts:  # blocks DNS-rebinding tricks
        return JSONResponse({"error": "unknown host"}, status_code=400)
    if request.url.path in PUBLIC_PATHS or _authorised(request.client.host, request.cookies):
        return await call_next(request)
    if request.url.path == "/":
        return RedirectResponse("/login")
    return JSONResponse({"error": "login required"}, status_code=401)


@app.get("/login")
def login_page(error: str = "") -> HTMLResponse:
    return HTMLResponse(pages.pin_page(error))


@app.post("/login")
async def login(request: Request):
    if not auth.same_origin(request.headers.get("origin"), request.headers.get("host")):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    ip = request.client.host
    wait = auth.locked_out(ip)
    if wait:
        return login_page(f"Too many wrong PINs. Try again in {(wait + 59) // 60} min.")
    form = parse_qs((await request.body()).decode())
    if not auth.check_pin(ip, form.get("pin", [""])[0]):
        return login_page("Wrong PIN.")
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(auth.COOKIE, auth.new_session(), max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="strict")
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/stats")
def stats() -> dict:
    now, counters = time.monotonic(), psutil.net_io_counters()
    elapsed = max(now - _net["time"], 1e-3)
    down = (counters.bytes_recv - _net["counters"].bytes_recv) / elapsed
    up = (counters.bytes_sent - _net["counters"].bytes_sent) / elapsed
    _net.update(time=now, counters=counters)

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    battery = psutil.sensors_battery()
    top = sorted(
        (p.info for p in psutil.process_iter(["name", "memory_info"]) if p.info["memory_info"]),
        key=lambda i: i["memory_info"].rss,
        reverse=True,
    )[:5]
    return {
        "cpu": psutil.cpu_percent(),
        "memory": mem.percent,
        "memory_used_gb": round(mem.used / 1e9, 1),
        "memory_total_gb": round(mem.total / 1e9, 1),
        "disk": disk.percent,
        "disk_free_gb": round(disk.free / 1e9),
        "battery": round(battery.percent) if battery else None,
        "charging": battery.power_plugged if battery else None,
        "net_down_kbps": round(down / 1024, 1),
        "net_up_kbps": round(up / 1024, 1),
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
        "processes": [{"name": i["name"], "mb": round(i["memory_info"].rss / 1e6)} for i in top],
    }


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
        ws.headers.get("host") not in allowed_hosts
        or not auth.same_origin(ws.headers.get("origin"), ws.headers.get("host"))
        or not _authorised(ws.client.host, ws.cookies)
    ):
        await ws.close(code=1008)
        return
    await ws.accept()
    await serve_chat(ws, brain, brain_lock)


def run(lan: bool = False) -> None:
    """Start the HUD. lan=True also serves it to phones on the same Wi-Fi (PIN required)."""
    local_url = f"http://127.0.0.1:{PORT}"
    host = "127.0.0.1"
    print(f"JARVIS HUD running at {local_url}  (press Ctrl+C to stop)")
    if lan:
        host = "0.0.0.0"
        ip = lan_ip()
        allowed_hosts.add(f"{ip}:{PORT}")
        phone_url = f"http://{ip}:{PORT}"
        qr = qrcode.QRCode(border=1)
        qr.add_data(phone_url)
        print("\nScan with your phone's camera (phone must be on the same Wi-Fi):")
        qr.print_ascii(invert=True)
        print(f"Or open {phone_url} on your phone.   PIN: {auth.pin()}\n")
    threading.Timer(1.5, lambda: webbrowser.open(local_url)).start()
    uvicorn.run(app, host=host, port=PORT, log_level="warning")
