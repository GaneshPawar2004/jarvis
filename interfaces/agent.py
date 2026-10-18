"""Laptop agent: keeps the laptop connected to cloud JARVIS so it can run laptop (and phone)
skills when asked from anywhere. Pair once with --pair, then run with --agent (or install it
to start automatically at Windows login with --agent-install)."""
import asyncio
import getpass
import json
import logging
import socket
import sys
import urllib.error
import urllib.request

import websockets
from google.genai import types

import config
from core import confirm, llm, vault
from core.reminders import _powershell
from skills import cloud_tools, local_tools

CREDENTIALS = config.DATA_DIR / "cloud_device.bin"  # encrypted with the Windows login (DPAPI)
LOG_FILE = config.DATA_DIR / "agent.log"
TASK_NAME = "JARVIS Laptop Agent"
CONFIRM_TIMEOUT = 130

log = logging.getLogger("jarvis.agent")


def _save_credentials(url: str, token: str) -> None:
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS.write_bytes(vault._crypt(json.dumps({"url": url, "token": token}).encode(), encrypt=True))


def _load_credentials() -> dict | None:
    if not CREDENTIALS.exists():
        return None
    return json.loads(vault._crypt(CREDENTIALS.read_bytes(), encrypt=False))


def pair() -> None:
    """Ask for the cloud password once and store the device key it returns."""
    url = input(f"Cloud JARVIS address [{config.CLOUD_URL}]: ").strip().rstrip("/") or config.CLOUD_URL
    password = getpass.getpass("JARVIS password (hidden, not saved): ")
    request = urllib.request.Request(
        url + "/api/pair",
        data=json.dumps({"password": password, "name": socket.gethostname()}).encode(),
        headers={"Content-Type": "application/json"},
    )
    print("Connecting (a sleeping free server can take up to a minute to wake)…")
    try:
        token = json.loads(urllib.request.urlopen(request, timeout=120).read())["token"]
    except urllib.error.HTTPError as e:
        print("Pairing failed:", json.loads(e.read() or b"{}").get("error", e.reason))
        return
    _save_credentials(url, token)
    print("Paired. Start the agent with: jarvis.bat → 6, or install it to start at login.")


def _declarations(tools: list) -> list[dict]:
    api = llm.client()._api_client
    return [
        types.FunctionDeclaration.from_callable(client=api, callable=fn).model_dump(mode="json", exclude_none=True)
        for fn in tools
    ]


def laptop_only_tools() -> list:
    shared = {fn.__name__ for fn in cloud_tools()}  # the cloud already has these itself
    return [fn for fn in local_tools() if fn.__name__ not in shared]


async def _session(url: str, token: str, tools: dict, declarations: list[dict]) -> None:
    ws_url = url.replace("https://", "wss://").replace("http://", "ws://") + "/agent"
    async with websockets.connect(ws_url, additional_headers={"Authorization": f"Bearer {token}"},
                                  open_timeout=120, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "hello", "kind": "laptop", "tools": declarations}))
        log.info("Connected to %s with %d laptop tools", url, len(declarations))
        loop = asyncio.get_running_loop()
        answers: dict[str, asyncio.Future] = {}

        async def ask_async(question: str) -> bool:
            ask_id = f"c{len(answers)}-{loop.time()}"
            answers[ask_id] = loop.create_future()
            await ws.send(json.dumps({"type": "confirm", "id": ask_id, "text": question}))
            try:
                return await asyncio.wait_for(answers[ask_id], CONFIRM_TIMEOUT)
            except asyncio.TimeoutError:
                return False
            finally:
                answers.pop(ask_id, None)

        # Risky laptop actions ask whoever is chatting with cloud JARVIS (usually the phone).
        confirm.set_handler(lambda q: asyncio.run_coroutine_threadsafe(ask_async(q), loop).result(CONFIRM_TIMEOUT + 5))

        async def run_call(message: dict) -> None:
            name, args = message["tool"], message.get("args") or {}
            log.info("Running %s(%s)", name, ", ".join(f"{k}={v!r}" for k, v in args.items()))
            fn = tools.get(name)
            try:
                if fn is None:
                    raise RuntimeError(f"Unknown laptop tool {name}")
                reply = {"result": await asyncio.to_thread(fn, **args)}
            except Exception as e:
                reply = {"error": f"{type(e).__name__}: {e}"}
            await ws.send(json.dumps({"type": "result", "id": message["id"], **reply}, default=str))

        async for raw in ws:
            message = json.loads(raw)
            if message.get("type") == "call":
                asyncio.create_task(run_call(message))
            elif message.get("type") == "confirm_reply":
                future = answers.get(message.get("id"))
                if future and not future.done():
                    future.set_result(bool(message.get("approved")))


async def _run_forever() -> None:
    credentials = _load_credentials()
    if credentials is None:
        log.error("Not paired yet. Run: python main.py --pair")
        return
    tools = laptop_only_tools()
    declarations = _declarations(tools)
    by_name = {fn.__name__: fn for fn in tools}
    delay = 5
    while True:
        try:
            await _session(credentials["url"], credentials["token"], by_name, declarations)
            delay = 5
        except websockets.InvalidStatus as e:
            if e.response.status_code in (401, 403):
                log.error("Cloud JARVIS rejected this laptop's key. Pair again with --pair.")
                return
            log.warning("Cloud refused the connection (%s); retrying in %ss", e.response.status_code, delay)
        except Exception as e:
            log.warning("Disconnected (%s: %s); retrying in %ss", type(e).__name__, e, delay)
        finally:
            confirm.set_handler(None)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


def run() -> None:
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stdout and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=handlers)
    log.info("JARVIS laptop agent starting (Ctrl+C to stop)")
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        log.info("Agent stopped.")


def install() -> None:
    """Start the agent silently every time the user logs in to Windows."""
    pythonw = config.ROOT / ".venv" / "Scripts" / "pythonw.exe"
    result = _powershell(
        f"$a = New-ScheduledTaskAction -Execute '{pythonw}' -Argument 'main.py --agent' -WorkingDirectory '{config.ROOT}'; "
        "$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); "
        f"Register-ScheduledTask -TaskPath '\\JARVIS\\' -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s -Force | Out-Null; "
        f"Start-ScheduledTask -TaskPath '\\JARVIS\\' -TaskName '{TASK_NAME}'"
    )
    print("Installed: the agent now starts at login (and is running now)." if result.returncode == 0
          else f"Could not install: {result.stderr.strip()[:300]}")


def uninstall() -> None:
    _powershell(f"Stop-ScheduledTask -TaskPath '\\JARVIS\\' -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
                f"Unregister-ScheduledTask -TaskPath '\\JARVIS\\' -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue")
    print("Removed: the agent no longer starts at login.")
