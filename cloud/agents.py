"""Device agents connected to the cloud brain: the laptop agent and the JARVIS Android app.
Each agent announces its kind and tools; the brain calls them through proxies, and their
Allow/Deny questions are relayed to whoever is chatting. The Android app can also chat
over the same connection."""
import asyncio
import hashlib
import secrets
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types
from starlette.concurrency import run_in_threadpool

import config
from core import confirm, db, memory

CALL_TIMEOUT = 90  # seconds a single device action may take
CONFIRM_TIMEOUT = 120
KINDS = ("laptop", "phone", "client")  # client = chat only (laptop chat/voice/HUD), offers no tools


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
    def __init__(self, ws: WebSocket, kind: str, name: str, declarations: list[types.FunctionDeclaration]):
        self.ws = ws
        self.kind = kind
        self.name = name
        self.declarations = declarations
        self.pending: dict[str, asyncio.Future] = {}  # tool calls and confirmations awaiting a reply

    async def request(self, message: dict, timeout: float):
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.ws.send_json({**message, "id": request_id})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(request_id, None)

    def resolve(self, message: dict) -> None:
        future = self.pending.get(message.get("id"))
        if future and not future.done():
            future.set_result(message)

    def fail_all(self, reason: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))


class Agents:
    """Tracks connected devices and keeps the brain's tool list in sync with them."""

    def __init__(self, on_change, on_chat, on_reset):
        self.devices: dict[str, Agent] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.on_change = on_change  # async callable(event: str) -> updates the brain
        self.on_chat = on_chat  # async callable(agent, text, on_tool, ask_user) -> reply event
        self.on_reset = on_reset  # async callable() -> starts a fresh conversation

    @property
    def laptop(self) -> Agent | None:
        return self.devices.get("laptop")

    @property
    def phone(self) -> Agent | None:
        return self.devices.get("phone")

    def proxy(self, tool: str, kind: str):
        """A plain function the brain can call from its worker thread."""
        def run(**args):
            agent = self.devices.get(kind)
            if agent is None:
                raise RuntimeError(f"The {kind} is not connected, so this can't be done right now.")
            outcome = asyncio.run_coroutine_threadsafe(
                agent.request({"type": "call", "tool": tool, "args": args}, CALL_TIMEOUT), self.loop
            ).result(CALL_TIMEOUT + 5)
            if "error" in outcome:
                raise RuntimeError(outcome["error"])
            return outcome.get("result")
        run.__name__ = tool
        return run

    async def _chat(self, agent: Agent, message: dict) -> None:
        """A chat message typed or spoken in the Android app."""
        def on_tool(name: str, args: dict) -> None:  # worker thread
            asyncio.run_coroutine_threadsafe(agent.ws.send_json({"type": "tool", "name": name, "args": args}), self.loop)

        def ask_user(question: str) -> bool:  # worker thread: the app shows Allow/Deny
            reply = asyncio.run_coroutine_threadsafe(
                agent.request({"type": "confirm", "text": question}, CONFIRM_TIMEOUT), self.loop
            )
            try:
                return bool(reply.result(CONFIRM_TIMEOUT + 5).get("approved"))
            except Exception:
                return False

        event = await self.on_chat(agent, str(message.get("text", "")).strip(), on_tool, ask_user)
        try:
            await agent.ws.send_json({**event, "type": "chat_" + event["type"], "id": message.get("id")})
        except Exception:
            pass  # the app disconnected mid-answer

    async def _memory(self, agent: Agent, message: dict) -> None:
        """List, add, edit or delete long-term memories for the app's Memory screen."""
        action = message.get("action")
        try:
            if action == "add":
                result = {"message": await run_in_threadpool(memory.add, str(message.get("text", "")),
                                                              message.get("kind", "fact"), "", int(message.get("importance", 3)), "app")}
            elif action == "update":
                result = {"ok": await run_in_threadpool(memory.update, int(message["memory_id"]), message.get("text"),
                                                        message.get("importance"), message.get("kind"))}
            elif action == "delete":
                result = {"ok": await run_in_threadpool(memory.delete, int(message["memory_id"]))}
            else:
                result = {}
            result["items"] = await run_in_threadpool(memory.items)
        except Exception as e:
            result = {"error": str(e)}
        await agent.ws.send_json({"type": "memory_result", "id": message.get("id"), **result})

    async def serve(self, ws: WebSocket, name: str) -> None:
        """Run one device connection until it drops."""
        self.loop = asyncio.get_running_loop()
        hello = await ws.receive_json()
        kind = hello.get("kind", "laptop")
        if hello.get("type") != "hello" or kind not in KINDS:
            await ws.close(code=1008)
            return
        declarations = [types.FunctionDeclaration.model_validate(d) for d in hello.get("tools", [])]
        agent = Agent(ws, kind, name, declarations)
        if kind == "client":  # chat only: doesn't change what the brain can do
            await ws.send_json({"type": "welcome", "laptop_online": self.laptop is not None,
                                "phone_online": self.phone is not None})
        else:
            if kind in self.devices:  # a newer connection from the same kind of device replaces the old one
                self.devices[kind].fail_all(f"The {kind} reconnected.")
            self.devices[kind] = agent
            await self.on_change(f"The {kind} just connected.")

        async def relay_confirm(message: dict) -> None:
            approved = await run_in_threadpool(confirm.ask, str(message.get("text", "")))
            await ws.send_json({"type": "confirm_reply", "id": message.get("id"), "approved": approved})

        try:
            while True:
                message = await ws.receive_json()
                kind_of = message.get("type")
                if kind_of in ("result", "confirm_reply"):
                    agent.resolve(message)
                elif kind_of == "confirm":  # the device needs a yes from whoever is chatting
                    asyncio.create_task(relay_confirm(message))
                elif kind_of == "chat":
                    asyncio.create_task(self._chat(agent, message))
                elif kind_of == "memory":  # the app's Memory screen
                    asyncio.create_task(self._memory(agent, message))
                elif kind_of == "reset":
                    await self.on_reset()
                    await ws.send_json({"type": "reset_done", "id": message.get("id")})
        except WebSocketDisconnect:
            pass
        finally:
            agent.fail_all(f"The {kind} disconnected.")
            if self.devices.get(kind) is agent:
                del self.devices[kind]
                await self.on_change(f"The {kind} just disconnected.")
