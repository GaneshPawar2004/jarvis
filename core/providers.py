"""Other AI providers for JARVIS's brain: Anthropic Claude and OpenAI-compatible services
(OpenAI, Groq, OpenRouter). The brain speaks Gemini's format; these adapters translate the
conversation and tools out, and the answer back, so any provider can think for JARVIS."""
import json
import re

import httpx
from google.genai import types

from core import keys

OPENAI_STYLE = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
# Preferred models, best first; the first one the key can use is picked when it's added.
PREFERRED = {
    "anthropic": [r"sonnet", r"opus", r"haiku"],
    "openai": [r"^gpt-5(\.\d+)?-mini$", r"^gpt-5(\.\d+)?$", r"^gpt-4\.1-mini$", r"^gpt-4o-mini$"],
    "groq": [r"gpt-oss-120b", r"llama-4", r"llama-3\.3-70b"],
    "openrouter": [r":free$"],
}
TIMEOUT = 120

_declaration_cache: dict[str, types.FunctionDeclaration] = {}


# ---------------- tools: Gemini declarations -> JSON schema ----------------

def _schema(schema: types.Schema | None) -> dict:
    if schema is None:
        return {"type": "object", "properties": {}}
    out: dict = {}
    if schema.type:
        out["type"] = schema.type.value.lower()
    if schema.description:
        out["description"] = schema.description
    if schema.enum:
        out["enum"] = schema.enum
    if schema.properties:
        out["properties"] = {name: _schema(s) for name, s in schema.properties.items()}
    if schema.required:
        out["required"] = schema.required
    if schema.items:
        out["items"] = _schema(schema.items)
    if schema.any_of:
        out["anyOf"] = [_schema(s) for s in schema.any_of]
        out.pop("type", None)
    if out.get("type") == "object":
        out.setdefault("properties", {})
    return out


def _declarations(cfg: types.GenerateContentConfig | None) -> list[types.FunctionDeclaration]:
    from core import llm

    found = []
    for tool in (cfg.tools or []) if cfg else []:
        if callable(tool):
            name = tool.__name__
            if name not in _declaration_cache:
                _declaration_cache[name] = types.FunctionDeclaration.from_callable(client=llm.client()._api_client, callable=tool)
            found.append(_declaration_cache[name])
        elif isinstance(tool, types.Tool) and tool.function_declarations:
            found.extend(tool.function_declarations)
    return found


def _system(cfg: types.GenerateContentConfig | None) -> str:
    instruction = cfg.system_instruction if cfg else None
    if instruction is None:
        return ""
    if isinstance(instruction, str):
        return instruction
    parts = getattr(instruction, "parts", None) or []
    return "\n".join(p.text for p in parts if getattr(p, "text", None))


def has_media(contents: list[types.Content]) -> bool:
    """Files and images (resume PDFs, screenshots) stay with Gemini."""
    return any(p.inline_data or p.file_data for c in contents for p in (c.parts or []))


# ---------------- conversation translation ----------------

def _turns(contents: list[types.Content]):
    """Yield (role, items) with ids paired: a model's tool calls and the results after them."""
    pending: list[str] = []
    counter = 0
    for content in contents:
        items = []
        for part in content.parts or []:
            if part.function_call:
                counter += 1
                call_id = part.function_call.id or f"call_{counter}"
                pending.append(call_id)
                items.append(("call", call_id, part.function_call.name, dict(part.function_call.args or {})))
            elif part.function_response:
                response = part.function_response.response or {}
                call_id = pending.pop(0) if pending else None
                items.append(("result", call_id, part.function_response.name, response))
            elif part.text:
                items.append(("text", None, None, part.text))
        if content.role == "model":
            pending = [i[1] for i in items if i[0] == "call"]
        if items:
            yield ("model" if content.role == "model" else "user"), items


def _to_anthropic(contents):
    messages = []
    for role, items in _turns(contents):
        blocks = []
        for kind, call_id, name, value in items:
            if kind == "text":
                blocks.append({"type": "text", "text": value})
            elif kind == "call":
                blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": value})
            elif call_id:
                blocks.append({"type": "tool_result", "tool_use_id": call_id, "content": json.dumps(value, default=str)[:20000]})
            else:  # a result whose call was trimmed away: keep it as plain text
                blocks.append({"type": "text", "text": f"(Result of {name}: {json.dumps(value, default=str)[:4000]})"})
        anthropic_role = "assistant" if role == "model" else "user"
        if messages and messages[-1]["role"] == anthropic_role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": anthropic_role, "content": blocks})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def _to_openai(contents, system: str):
    messages = [{"role": "system", "content": system}] if system else []
    for role, items in _turns(contents):
        if role == "model":
            text = "".join(v for k, _, _, v in items if k == "text") or None
            calls = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(v, default=str)}}
                     for k, i, n, v in items if k == "call"]
            message = {"role": "assistant", "content": text}
            if calls:
                message["tool_calls"] = calls
            messages.append(message)
        else:
            for kind, call_id, name, value in items:
                if kind == "result" and call_id:
                    messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(value, default=str)[:20000]})
                elif kind == "result":
                    messages.append({"role": "user", "content": f"(Result of {name}: {json.dumps(value, default=str)[:4000]})"})
                else:
                    messages.append({"role": "user", "content": value})
    return messages


def _response(parts: list[types.Part]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=parts or [types.Part(text="")]))])


# ---------------- calling the providers ----------------

def model_for(provider: str) -> str:
    return keys.setting(f"model:{provider}")


def generate(provider: str, contents: list[types.Content], cfg: types.GenerateContentConfig | None):
    """One model turn from another provider, returned in Gemini's response format."""
    found = keys.get(provider)
    model = model_for(provider)
    if not found or not model:
        raise RuntimeError(f"{provider} isn't set up")
    key = found[0]
    tools = _declarations(cfg)
    if provider == "anthropic":
        body = {"model": model, "max_tokens": 4096, "messages": _to_anthropic(contents)}
        if (system := _system(cfg)):
            body["system"] = system
        if tools:
            body["tools"] = [{"name": d.name, "description": d.description or "", "input_schema": _schema(d.parameters)} for d in tools]
        reply = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=TIMEOUT,
                           headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        reply.raise_for_status()
        parts = []
        for block in reply.json().get("content", []):
            if block.get("type") == "text":
                parts.append(types.Part(text=block["text"]))
            elif block.get("type") == "tool_use":
                parts.append(types.Part(function_call=types.FunctionCall(id=block["id"], name=block["name"], args=block.get("input") or {})))
        return _response(parts), f"{provider}:{model}"

    body = {"model": model, "messages": _to_openai(contents, _system(cfg))}
    if tools:
        body["tools"] = [{"type": "function", "function": {"name": d.name, "description": d.description or "",
                                                            "parameters": _schema(d.parameters)}} for d in tools]
    reply = httpx.post(f"{OPENAI_STYLE[provider]}/chat/completions", json=body, timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {key}"})
    reply.raise_for_status()
    message = reply.json()["choices"][0]["message"]
    parts = [types.Part(text=message["content"])] if message.get("content") else []
    for call in message.get("tool_calls") or []:
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        parts.append(types.Part(function_call=types.FunctionCall(id=call["id"], name=call["function"]["name"], args=args)))
    return _response(parts), f"{provider}:{model}"


# ---------------- checking a key when it's added ----------------

def check(provider: str, key: str, extra: str = "") -> str:
    """Test the key with a free call and pick the model to use. Returns the chosen model or a
    short description; raises ValueError with a friendly reason if the key doesn't work."""
    try:
        if provider == "anthropic":
            reply = httpx.get("https://api.anthropic.com/v1/models", timeout=30,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        elif provider in OPENAI_STYLE:
            reply = httpx.get(f"{OPENAI_STYLE[provider]}/models", timeout=30, headers={"Authorization": f"Bearer {key}"})
            if provider == "openrouter" and reply.status_code == 200:  # the model list is public; check the key itself
                auth = httpx.get("https://openrouter.ai/api/v1/key", timeout=30, headers={"Authorization": f"Bearer {key}"})
                if auth.status_code != 200:
                    reply = auth
        elif provider == "cloudflare":
            if not extra.strip():
                raise ValueError("Cloudflare also needs your Account ID (on the right of the Cloudflare dashboard).")
            reply = httpx.get("https://api.cloudflare.com/client/v4/user/tokens/verify", timeout=30,
                              headers={"Authorization": f"Bearer {key}"})
            if reply.status_code == 200:
                return "@cf/black-forest-labs/flux-1-schnell"
        elif provider == "gemini":
            reply = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", timeout=30)
            if reply.status_code == 200:
                return "gemini"
        else:
            raise ValueError("This provider doesn't use a key.")
    except httpx.HTTPError as e:
        raise ValueError(f"Couldn't reach {provider}: {type(e).__name__}")
    if reply.status_code in (401, 403):
        raise ValueError("The key was rejected. Check you copied all of it.")
    if reply.status_code != 200:
        raise ValueError(f"{provider} answered with an error ({reply.status_code}).")
    data = reply.json().get("data", [])
    if provider == "openrouter":  # free models that can use tools
        data = [m for m in data if "tools" in (m.get("supported_parameters") or [])]
    ids = [m.get("id", "") for m in data]
    for pattern in PREFERRED.get(provider, []):
        for model_id in ids:
            if re.search(pattern, model_id):
                return model_id
    if ids:
        return ids[0]
    raise ValueError("The key works but no usable model was found.")
