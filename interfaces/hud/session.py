"""One browser chat connection to the Brain, shared by the laptop HUD and the cloud server.
Streams tool activity and relays Allow/Deny prompts while JARVIS works."""
import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from core import confirm
from core.brain import Brain

CONFIRM_TIMEOUT = 120  # seconds to answer an Allow/Deny prompt before it counts as Deny


async def ask_brain(brain: Brain, brain_lock: asyncio.Lock, text: str, on_tool, ask_user) -> dict:
    """One question to the shared brain, with this chat's tool display and Allow/Deny
    prompts. Returns a "reply" or "error" event."""
    async with brain_lock:
        brain.on_tool = on_tool
        confirm.set_handler(ask_user)
        try:
            reply = await run_in_threadpool(brain.ask, text)
            return {"type": "reply", "text": reply, "model": brain.active_model}
        except Exception as e:
            return {"type": "error", "text": str(e)}
        finally:
            confirm.set_handler(None)


async def serve_chat(ws: WebSocket, brain: Brain, brain_lock: asyncio.Lock) -> None:
    """Run an accepted websocket until the user disconnects."""
    loop = asyncio.get_running_loop()
    inbox: asyncio.Queue = asyncio.Queue()
    pending: dict[str, asyncio.Future | None] = {"answer": None}

    def on_tool(name: str, args: dict) -> None:  # called from the worker thread
        asyncio.run_coroutine_threadsafe(ws.send_json({"type": "tool", "name": name, "args": args}), loop)

    async def ask_async(question: str) -> bool:
        pending["answer"] = loop.create_future()
        await ws.send_json({"type": "confirm", "text": question})
        try:
            return await asyncio.wait_for(pending["answer"], CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            return False

    def ask_user(question: str) -> bool:  # called from the worker thread by risky tools
        return asyncio.run_coroutine_threadsafe(ask_async(question), loop).result(CONFIRM_TIMEOUT + 5)

    async def reader() -> None:
        """Keep reading while JARVIS works, so Allow/Deny answers arrive mid-task."""
        try:
            while True:
                message = await ws.receive_json()
                answer = pending["answer"]
                if message.get("type") == "confirm_reply":
                    if answer and not answer.done():
                        answer.set_result(bool(message.get("approved")))
                else:
                    await inbox.put(message)
        finally:
            if pending["answer"] and not pending["answer"].done():
                pending["answer"].set_result(False)

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            next_message = asyncio.create_task(inbox.get())
            done, _ = await asyncio.wait({next_message, reader_task}, return_when=asyncio.FIRST_COMPLETED)
            if reader_task in done:
                next_message.cancel()
                reader_task.result()  # re-raises the disconnect
            text = str(next_message.result().get("text", "")).strip()
            if not text:
                continue
            await ws.send_json({"type": "thinking"})
            event = await ask_brain(brain, brain_lock, text, on_tool, ask_user)
            await ws.send_json(event)  # raises WebSocketDisconnect if the user left mid-task
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
