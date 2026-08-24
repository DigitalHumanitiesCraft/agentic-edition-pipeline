"""Multi-provider LLM abstraction. Supports Gemini, OpenAI, Anthropic, Ollama.

Uses raw HTTP via requests instead of provider SDKs to minimize dependencies.
Adapted from co-ocr-htr llm.js provider patterns and szd-htr retry logic.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from pathlib import Path

import requests

from config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    OLLAMA_BASE_URL,
    OPENAI_API_KEY,
)

# Timeouts: 240s for cloud APIs, 480s for local Ollama
CLOUD_TIMEOUT = 240
LOCAL_TIMEOUT = 480

MAX_RETRIES = 4
BACKOFF_BASE = 5

# Key redaction. Provider errors quote the request URL and the request
# headers, so an unredacted message ends up in a console log or in
# errors.json. Every error string that carries a URL or a provider
# exception text passes through redact_secrets first.
REDACTED = "[redacted]"
_QUERY_KEY_RE = re.compile(
    r"([?&](?:key|api[_-]?key|access[_-]?token)=)[^&\s\"']+", re.IGNORECASE
)


def redact_secrets(text: str) -> str:
    """Remove key query parameters and configured key values from a message."""
    if not text:
        return ""
    cleaned = _QUERY_KEY_RE.sub(rf"\g<1>{REDACTED}", text)
    for secret in (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY):
        if secret:
            cleaned = cleaned.replace(secret, REDACTED)
    return cleaned


def encode_image(path: Path) -> tuple[str, str]:
    """Read an image file and return (base64_string, mime_type)."""
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/jpeg"
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8"), mime


def call_llm(
    provider: str,
    model: str,
    prompt: str,
    images: list[Path] | None = None,
    temperature: float = 0.1,
) -> str:
    """Send a prompt (with optional images) to an LLM provider and return the text response.

    Raises ValueError for missing API keys, RuntimeError for API errors.
    """
    if provider == "gemini":
        return _call_gemini(model, prompt, images, temperature)
    elif provider == "openai":
        return _call_openai(model, prompt, images, temperature)
    elif provider == "anthropic":
        return _call_anthropic(model, prompt, images, temperature)
    elif provider == "ollama":
        return _call_ollama(model, prompt, images, temperature)
    else:
        raise ValueError(f"Unknown provider '{provider}'. Use gemini, openai, anthropic, or ollama.")


def parse_json_response(text: str) -> dict | list | None:
    """Parse a JSON response from an LLM, handling markdown code blocks and escape issues.

    Adapted from szd-htr transcribe.py parse_api_response pattern.
    Returns the parsed object, or None if parsing fails.
    """
    # Strip markdown code blocks
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    # First attempt: direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Second attempt: fix common escape issues (unescaped newlines in strings)
    try:
        fixed = cleaned.replace("\n", "\\n")
        # Restore structural newlines
        fixed = fixed.replace("{\\n", "{\n").replace("\\n}", "\n}")
        fixed = fixed.replace("[\\n", "[\n").replace("\\n]", "\n]")
        fixed = fixed.replace(",\\n", ",\n")
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


# --- Provider implementations ---

def _call_gemini(model: str, prompt: str, images: list[Path] | None, temperature: float) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set. Add it to .env")

    # The key travels as a header, never as a query parameter: a URL reaches
    # proxy logs, redirects and exception messages, a header does not.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY}

    parts = [{"text": prompt}]
    if images:
        for img_path in images:
            b64, mime = encode_image(img_path)
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature},
    }

    resp = _request_with_retry("POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT)
    data = resp.json()

    if "candidates" not in data or not data["candidates"]:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:500]}")
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai(model: str, prompt: str, images: list[Path] | None, temperature: float) -> str:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set. Add it to .env")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    content = [{"type": "text", "text": prompt}]
    if images:
        for img_path in images:
            b64, mime = encode_image(img_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })

    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    resp = _request_with_retry("POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT)
    data = resp.json()

    if "choices" not in data or not data["choices"]:
        raise RuntimeError(f"OpenAI returned no choices: {json.dumps(data)[:500]}")
    return data["choices"][0]["message"]["content"]


def _call_anthropic(model: str, prompt: str, images: list[Path] | None, temperature: float) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to .env")

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    content = []
    if images:
        for img_path in images:
            b64, mime = encode_image(img_path)
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
    content.append({"type": "text", "text": prompt})

    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    resp = _request_with_retry("POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT)
    data = resp.json()

    if "content" not in data or not data["content"]:
        raise RuntimeError(f"Anthropic returned no content: {json.dumps(data)[:500]}")
    return data["content"][0]["text"]


def _call_ollama(model: str, prompt: str, images: list[Path] | None, temperature: float) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"

    image_list = []
    if images:
        for img_path in images:
            b64, _ = encode_image(img_path)
            image_list.append(b64)

    body = {
        "model": model,
        "prompt": prompt,
        "images": image_list if image_list else None,
        "stream": False,
        "options": {"temperature": temperature},
    }
    # Remove None values
    body = {k: v for k, v in body.items() if v is not None}

    resp = _request_with_retry("POST", url, json=body, timeout=LOCAL_TIMEOUT)
    data = resp.json()

    if "response" not in data:
        raise RuntimeError(f"Ollama returned no response: {json.dumps(data)[:500]}")
    return data["response"]


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """HTTP request with exponential backoff on rate limit errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code == 429 and attempt < MAX_RETRIES:
                wait = BACKOFF_BASE * (2 ** attempt)
                print(f"  Rate limited. Waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            try:
                resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                # "from None" suppresses the chained original, whose message
                # and traceback would carry the unredacted request back out.
                raise RuntimeError(redact_secrets(str(exc))) from None
            return resp
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE * (2 ** attempt)
                print(f"  Timeout. Retrying in {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"All {MAX_RETRIES} retries exhausted for {redact_secrets(url)}")
