"""Image generation: free first (Cloudflare FLUX with the user's free key, then Pollinations
with no key), OpenAI GPT Image if the user added a paid key. Images are saved in the
database and attached to JARVIS's reply as image cards."""
import base64
import threading
import urllib.parse

import httpx

import config
from core import db, keys

# Images made while answering the current message; the server attaches them to the reply.
_pending: list[int] = []
_lock = threading.Lock()


def take_pending() -> list[int]:
    with _lock:
        ids = list(_pending)
        _pending.clear()
        return ids


def _cloudflare(prompt: str) -> bytes:
    key, account = keys.get("cloudflare") or ("", "")
    if not key or not account:
        raise RuntimeError("Cloudflare isn't set up")
    reply = httpx.post(f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                       json={"prompt": prompt, "steps": 4}, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    reply.raise_for_status()
    return base64.b64decode(reply.json()["result"]["image"])


def _pollinations(prompt: str) -> bytes:
    reply = httpx.get("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900]),
                      params={"width": 1024, "height": 1024, "nologo": "true"}, timeout=120, follow_redirects=True)
    reply.raise_for_status()
    if not reply.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("Pollinations didn't return an image")
    return reply.content


def _openai(prompt: str) -> bytes:
    key, _ = keys.get("openai") or ("", "")
    if not key:
        raise RuntimeError("OpenAI isn't set up")
    reply = httpx.post("https://api.openai.com/v1/images/generations", timeout=180,
                       json={"model": keys.setting("image_model:openai", "gpt-image-1-mini"), "prompt": prompt, "size": "1024x1024"},
                       headers={"Authorization": f"Bearer {key}"})
    reply.raise_for_status()
    return base64.b64decode(reply.json()["data"][0]["b64_json"])


MAKERS = {"cloudflare": _cloudflare, "pollinations": _pollinations, "openai": _openai}


def generate_image(prompt: str) -> str:
    """Create a picture from a description and show it to the user in the chat. Write a
    detailed visual prompt in English (subject, style, setting, lighting).

    Args:
        prompt: What the picture should show, e.g. "a futuristic arc reactor glowing blue, studio lighting".
    """
    chosen = keys.setting("image_provider", "auto")
    order = ["cloudflare", "pollinations", "openai"]
    if chosen in MAKERS:
        order = [chosen] + [p for p in order if p != chosen]
    problems = []
    for provider in order:
        try:
            data = MAKERS[provider](prompt)
        except Exception as e:
            problems.append(f"{provider}: {type(e).__name__}")
            continue
        mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        db.execute("INSERT INTO images (prompt, provider, mime, data, created) VALUES (?, ?, ?, ?, ?)",
                   (prompt, provider, mime, data, config.now().isoformat(timespec="seconds")))
        image_id = db.rows("SELECT max(id) FROM images")[0][0]
        with _lock:
            _pending.append(image_id)
        return f"Image {image_id} created with {provider}; it is shown to the user with your reply."
    return "Couldn't create the image right now (" + "; ".join(problems) + ")."


def image(image_id: int) -> tuple[str, bytes] | None:
    found = db.rows("SELECT mime, data FROM images WHERE id = ?", (image_id,))
    return (found[0][0], bytes(found[0][1])) if found else None
