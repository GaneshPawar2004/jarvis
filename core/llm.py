"""Shared Gemini access: one client, with fallback down config.MODELS on overload or limits."""
import re
import time

from google import genai
from google.genai import errors, types

import config

RETRYABLE = {404, 429, 500, 503, 504}
MAX_QUOTA_WAIT = 60  # seconds to wait for the free tier's per-minute limit to reset
_client: genai.Client | None = None


class QuotaExhausted(RuntimeError):
    pass


def client() -> genai.Client:
    """Gemini client: the user's own Gemini key if they added one, else the server's."""
    global _client
    if _client is None:
        key = config.GEMINI_API_KEY
        try:
            from core import keys

            key = (keys.get("gemini") or (key, ""))[0]
        except Exception:
            pass  # no database yet: use the configured key
        if not key:
            raise RuntimeError("GEMINI_API_KEY is missing from .env")
        _client = genai.Client(api_key=key)
    return _client


def reset_client() -> None:
    """Call after the Gemini key changes."""
    global _client
    _client = None


def _retry_after(error: errors.APIError) -> float:
    """Seconds Gemini asked us to wait (from 'retry in 56.4s'), or 0."""
    found = re.search(r"retry in ([\d.]+)s", str(error), re.IGNORECASE)
    return float(found.group(1)) if found else 0.0


def generate(
    contents: list[types.Content], cfg: types.GenerateContentConfig | None = None, light: bool = False
) -> tuple[types.GenerateContentResponse, str]:
    """Call the first available model; returns (response, model used). If every model is
    over the free per-minute limit, waits for it to reset once before giving up."""
    if not light:  # the user's chosen chat provider first; Gemini is always the fallback
        from core import keys, providers

        route = keys.setting("chat_provider", "gemini")
        if route != "gemini" and not providers.has_media(contents):
            try:
                return providers.generate(route, contents, cfg)
            except Exception as e:
                print(f"[llm] {route} failed ({type(e).__name__}: {str(e)[:120]}); using Gemini")
    models = list(reversed(config.MODELS)) if light else config.MODELS  # light = background work: cheapest model first
    last_error = None
    waited_for_quota = False
    attempt = 0
    while attempt < 3:
        quota_waits, overloaded = [], False
        for model in models:
            try:
                return client().models.generate_content(model=model, contents=contents, config=cfg), model
            except errors.APIError as e:
                if e.code not in RETRYABLE:
                    raise
                last_error = e
                if e.code == 429:
                    quota_waits.append(_retry_after(e))
                elif e.code != 404:  # 404 = a retired model; it doesn't change what we should do
                    overloaded = True
        if quota_waits and not overloaded:  # every usable model is rate-limited
            wait = max(quota_waits) + 1
            if waited_for_quota or wait > MAX_QUOTA_WAIT:
                raise QuotaExhausted(
                    "I've reached the free AI usage limit for the moment. Please try again in a minute or two."
                )
            time.sleep(wait)
            waited_for_quota = True
            continue
        time.sleep(2 * (attempt + 1))
        attempt += 1
    raise RuntimeError(f"All models are unavailable right now: {last_error}")
