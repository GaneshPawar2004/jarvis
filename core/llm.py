"""Shared Gemini access: one client, with fallback down config.MODELS on overload or limits."""
import time

from google import genai
from google.genai import errors, types

import config

RETRYABLE = {404, 429, 500, 503, 504}
_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is missing from .env")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def generate(
    contents: list[types.Content], cfg: types.GenerateContentConfig | None = None
) -> tuple[types.GenerateContentResponse, str]:
    """Call the first available model; returns (response, model used)."""
    last_error = None
    for attempt in range(3):
        for model in config.MODELS:
            try:
                return client().models.generate_content(model=model, contents=contents, config=cfg), model
            except errors.APIError as e:
                if e.code not in RETRYABLE:
                    raise
                last_error = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"All models are unavailable right now: {last_error}")
