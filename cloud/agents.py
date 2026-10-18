"""Device agents (the laptop now, the Android app later) connected to the cloud brain.
An agent announces its tools; the brain calls them through a proxy, and the agent's
Allow/Deny questions are relayed to whoever is chatting."""
import asyncio
import hashlib
import secrets
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types
from starlette.concurrency import run_in_threadpool

import config
from core import confirm, db

CALL_TIMEOUT = 90  # seconds a single laptop action may take


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_device(name: str) -> str:
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO devices (token_hash, name, created) VALUES (?, ?, ?)",
               (hash_token(token), name[:60] or "device", config.now().isoformat(timespec="seconds")))
    return token


def device_name(token: str | None) -> str | None:
    if not token:
        return None
    found = db.rows("SELECT name FROM devices WHERE token_hash = ?", (hash_token(token),))
    return found[0][0] if found else None


class Agent:
    def __init__(self, ws: WebSocket, name: str, declarations: list[types.FunctionDeclaration]):
        self.ws = ws
        self.name = name
        self.declarations = declarations
        self.pending: dict[str, asyncio.Future] = {}

    async def call(self, tool: str, args: dict):
        call_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[call_id] = future
        try:
            await self.ws.send_json({"type": "call", "id": call_id, "tool": tool, "args": args})
            return await asyncio.wait_for(future, CALL_TIMEOUT)
        finally:
            self.pending.pop(call_id, None)

    def fail_all(self, reason: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))


class Agents:
    """Tracks the connected laptop and keeps the brain's tool list in sync with it."""

    def __init__(self, on_change):
        self.laptop: Agent | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.on_change = on_change  # async callable(agent or None) -> updates the brain

    def proxy(self, tool: str):
        """A plain function the brain can call from its worker thread."""
        def run(**args):
            agent = self.laptop
            if agent is None:
                raise RuntimeError("The laptop is offline, so this can't be done right now.")
            outcome = asyncio.run_coroutine_threadsafe(agent.call(tool, args), self.loop).result(CALL_TIMEOUT + 5)
            if "error" in outcome:
                raise RuntimeError(outcome["error"])
            return outcome.get("result")
        run.__name__ = tool
        return run

    async def serve(self, ws: WebSocket, name: str) -> None:
        """Run one agent connection until it drops."""
        self.loop = asyncio.get_running_loop()
        hello = await ws.receive_json()
        if hello.get("type") != "hello":
            await ws.close(code=1008)
            return
        declarations = [types.FunctionDeclaration.model_validate(d) for d in hello.get("tools", [])]
        agent = Agent(ws, name, declarations)
        if self.laptop is not None:  # a newer connection from the laptop replaces the old one
            self.laptop.fail_all("The laptop reconnected.")
        self.laptop = agent
        await self.on_change(agent)

        async def relay_confirm(message: dict) -> None:
            approved = await run_in_threadpool(confirm.ask, str(message.get("text", "")))
            await ws.send_json({"type": "confirm_reply", "id": message.get("id"), "approved": approved})

        try:
            while True:
                message = await ws.receive_json()
                if message.get("type") == "result":
                    future = agent.pending.get(message.get("id"))
                    if future and not future.done():
                        future.set_result(message)
                elif message.get("type") == "confirm":
                    asyncio.create_task(relay_confirm(message))
        except WebSocketDisconnect:
            pass
        finally:
            agent.fail_all("The laptop disconnected.")
            if self.laptop is agent:
                self.laptop = None
                await self.on_change(None)
