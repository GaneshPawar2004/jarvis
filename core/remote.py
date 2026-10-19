"""Laptop chat, voice and HUD talk to the ONE cloud brain, so every device shares the same
conversation and memory. RemoteBrain looks like core.brain.Brain to the interfaces; if the
cloud can't be reached it falls back to a local brain so JARVIS keeps working."""
import asyncio
import json
import threading
import uuid
from typing import Callable

import websockets

from core import confirm

ASK_TIMEOUT = 360  # long phone tasks can include a one-minute wait for the free AI limit


class RemoteBrain:
    def __init__(self, url: str, token: str, on_tool: Callable[[str, dict], None] | None = None):
        self.url = url.replace("https://", "wss://").replace("http://", "ws://") + "/agent"
        self.token = token
        self.on_tool = on_tool or (lambda name, args: None)
        self.active_model = "cloud"
        self.laptop_online = False
        self.phone_online = False
        self._ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._run(self._connect(), timeout=120)

    # ---- plumbing: one background event loop owns the websocket ----

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _connect(self) -> None:
        self._ws = await websockets.connect(
            self.url, additional_headers={"Authorization": f"Bearer {self.token}"},
            open_timeout=110, max_size=8 * 1024 * 1024,
        )
        await self._ws.send(json.dumps({"type": "hello", "kind": "client", "tools": []}))
        welcome = json.loads(await self._ws.recv())
        self.laptop_online = bool(welcome.get("laptop_online"))
        self.phone_online = bool(welcome.get("phone_online"))
        asyncio.ensure_future(self._reader(self._ws))

    async def _reader(self, ws) -> None:
        try:
            async for raw in ws:
                message = json.loads(raw)
                kind = message.get("type")
                if kind == "tool":
                    self.on_tool(message.get("name", ""), message.get("args") or {})
                elif kind == "confirm":  # a risky action: ask the person at this laptop
                    asyncio.ensure_future(self._answer_confirm(ws, message))
                elif kind in ("chat_reply", "chat_error", "reset_done"):
                    future = self._pending.get(message.get("id"))
                    if future and not future.done():
                        future.set_result(message)
        except Exception:
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Lost the connection to cloud JARVIS."))

    async def _answer_confirm(self, ws, message: dict) -> None:
        approved = await asyncio.to_thread(confirm.ask, str(message.get("text", "")))
        await ws.send(json.dumps({"type": "confirm_reply", "id": message.get("id"), "approved": approved}))

    async def _request(self, message: dict) -> dict:
        if self._ws is None or self._ws.state.name != "OPEN":
            await self._connect()  # the free server may have restarted; reconnect once
        request_id = uuid.uuid4().hex
        future = self._loop.create_future()
        self._pending[request_id] = future
        try:
            await self._ws.send(json.dumps({**message, "id": request_id}))
            return await asyncio.wait_for(future, ASK_TIMEOUT)
        finally:
            self._pending.pop(request_id, None)

    # ---- the Brain interface the laptop interfaces use ----

    def ask(self, text: str) -> str:
        reply = self._run(self._request({"type": "chat", "text": text}), timeout=ASK_TIMEOUT + 5)
        if reply.get("type") == "chat_error":
            raise RuntimeError(reply.get("text", "Cloud JARVIS couldn't answer."))
        self.active_model = reply.get("model", "cloud")
        return reply.get("text", "")

    def reset(self) -> None:
        self._run(self._request({"type": "reset"}), timeout=120)

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._run(self._ws.close(), timeout=5)
            except Exception:
                pass


def connect_brain(on_tool: Callable[[str, dict], None] | None = None):
    """The shared cloud brain when this laptop is paired and the cloud answers; otherwise a
    local brain. Returns (brain, note for the user)."""
    from interfaces.agent import _load_credentials

    credentials = _load_credentials()
    if credentials:
        try:
            brain = RemoteBrain(credentials["url"], credentials["token"], on_tool)
            note = "Connected to cloud JARVIS: same conversation and memory as your phone."
            if not brain.laptop_online:
                note += " Laptop skills need the laptop agent running (jarvis.bat → 6)."
            return brain, note
        except Exception as e:
            reason = f"cloud unreachable ({type(e).__name__})"
    else:
        reason = "this laptop isn't paired with cloud JARVIS (python main.py --pair)"
    from core.brain import Brain

    return Brain(on_tool=on_tool, thread="laptop-offline"), f"Offline mode: {reason}. Using the laptop's own brain."
