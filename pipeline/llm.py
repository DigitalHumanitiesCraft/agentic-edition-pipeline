"""Multi-provider LLM abstraction. Supports Gemini, OpenAI, Anthropic, Ollama.

Uses raw HTTP via requests instead of provider SDKs to minimize dependencies;
requests is the deliberate exception to stdlib HTTP because of its timeout
and error types. Adapted from co-ocr-htr llm.js provider patterns and
szd-htr retry logic.

Every adapter receives config.TEMPERATURE, so the value recorded in call
records is the value sent. Transient failures (429, 5xx, timeouts, connection
errors) are retried with bounded backoff; any other HTTP error stops at once.
An answer the provider cut off at its output-token limit raises
TruncatedResponseError instead of reaching the JSON parser, because a
truncated JSON would otherwise fail parsing and trigger a second paid call.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import requests

import config
from call_records import response_data
from config import redact_secrets

CLOUD_TIMEOUT = 240
LOCAL_TIMEOUT = 480

MAX_RETRIES = 4
BACKOFF_BASE = 5
# Upper bound for one wait, including a server's Retry-After, so a hostile
# or misconfigured header cannot stall a batch run indefinitely.
MAX_RETRY_WAIT = 120


class TruncatedResponseError(RuntimeError):
    """The provider stopped at its output-token limit; the answer is incomplete."""


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
) -> str:
    """Send a prompt (with optional images) to an LLM provider and return the text response.

    Raises ValueError for an unknown provider or a missing API key,
    TruncatedResponseError for an answer cut off at the token limit and
    RuntimeError for other API errors.
    """
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise ValueError(
            f"Unknown provider '{provider}'. Use gemini, openai, anthropic, or ollama."
        )
    missing = config.missing_api_key(provider)
    if missing:
        raise ValueError(f"{missing} is not set. Add it to .env")
    return adapter(model, prompt, images, config.TEMPERATURE)


def parse_json_response(text: str) -> dict | list | None:
    """Parse a JSON response from an LLM, handling markdown code blocks and escape issues.

    Adapted from szd-htr transcribe.py parse_api_response pattern.
    Returns the parsed object, or None if parsing fails.
    """
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Models often emit raw newlines inside JSON strings; escape them all,
    # then restore the structural ones around brackets and commas.
    try:
        fixed = cleaned.replace("\n", "\\n")
        fixed = fixed.replace("{\\n", "{\n").replace("\\n}", "\n}")
        fixed = fixed.replace("[\\n", "[\n").replace("\\n]", "\n]")
        fixed = fixed.replace(",\\n", ",\n")
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


def _truncated(provider: str, field: str, value: str) -> TruncatedResponseError:
    return TruncatedResponseError(
        f"{provider} stopped at the output token limit ({field} {value}); "
        "the answer is incomplete"
    )


def _call_gemini(
    model: str, prompt: str, images: list[Path] | None, temperature: float
) -> str:
    # The key travels as a header, never as a query parameter: a URL reaches
    # proxy logs, redirects and exception messages, a header does not.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": config.GEMINI_API_KEY}

    parts = [{"text": prompt}]
    for img_path in images or []:
        b64, mime = encode_image(img_path)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": temperature},
    }

    resp = _request_with_retry(
        "POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT
    )
    data = response_data(resp)

    if "candidates" not in data or not data["candidates"]:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:500]}")
    candidate = data["candidates"][0]
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise _truncated("Gemini", "finishReason", "MAX_TOKENS")
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(
        part["text"]
        for part in parts
        if isinstance(part.get("text"), str) and not part.get("thought")
    )
    if not text:
        raise RuntimeError("Gemini returned no answer text")
    return text


def _call_openai(
    model: str, prompt: str, images: list[Path] | None, temperature: float
) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    content = [{"type": "text", "text": prompt}]
    for img_path in images or []:
        b64, mime = encode_image(img_path)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    resp = _request_with_retry(
        "POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT
    )
    data = response_data(resp)

    if "choices" not in data or not data["choices"]:
        raise RuntimeError(f"OpenAI returned no choices: {json.dumps(data)[:500]}")
    choice = data["choices"][0]
    if choice.get("finish_reason") == "length":
        raise _truncated("OpenAI", "finish_reason", "length")
    text = choice.get("message", {}).get("content")
    if not isinstance(text, str) or not text:
        raise RuntimeError("OpenAI returned no answer text")
    return text


def _call_anthropic(
    model: str, prompt: str, images: list[Path] | None, temperature: float
) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    content = []
    for img_path in images or []:
        b64, mime = encode_image(img_path)
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            }
        )
    content.append({"type": "text", "text": prompt})

    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
    }

    resp = _request_with_retry(
        "POST", url, headers=headers, json=body, timeout=CLOUD_TIMEOUT
    )
    data = response_data(resp)

    if data.get("stop_reason") == "max_tokens":
        raise _truncated("Anthropic", "stop_reason", "max_tokens")
    if "content" not in data or not data["content"]:
        raise RuntimeError(f"Anthropic returned no content: {json.dumps(data)[:500]}")
    text = "".join(
        part["text"]
        for part in data["content"]
        if part.get("type") == "text" and isinstance(part.get("text"), str)
    )
    if not text:
        raise RuntimeError("Anthropic returned no answer text")
    return text


def _call_ollama(
    model: str, prompt: str, images: list[Path] | None, temperature: float
) -> str:
    url = f"{config.OLLAMA_BASE_URL}/api/generate"

    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if images:
        body["images"] = [encode_image(img_path)[0] for img_path in images]

    resp = _request_with_retry("POST", url, json=body, timeout=LOCAL_TIMEOUT)
    data = response_data(resp)

    if data.get("done_reason") == "length":
        raise _truncated("Ollama", "done_reason", "length")
    if "response" not in data:
        raise RuntimeError(f"Ollama returned no response: {json.dumps(data)[:500]}")
    return data["response"]


_ADAPTERS: dict[str, Callable[[str, str, list[Path] | None, float], str]] = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "ollama": _call_ollama,
}


def _retry_wait(response: requests.Response | None, attempt: int) -> float:
    """Exponential backoff, lengthened by a numeric Retry-After, capped."""
    headers = getattr(response, "headers", None) or {}
    try:
        server_delay = float(headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        server_delay = 0.0
    return min(max(server_delay, BACKOFF_BASE * (2**attempt)), MAX_RETRY_WAIT)


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Send one provider request, retrying only transient failures.

    Every error that leaves this function is a RuntimeError with a redacted
    message; "from None" drops the chained original, whose message and
    traceback would carry the unredacted request back out.
    """
    for attempt in range(MAX_RETRIES + 1):
        final = attempt == MAX_RETRIES
        response = None
        try:
            response = requests.request(method, url, **kwargs)
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            if final:
                raise RuntimeError(redact_secrets(str(exc))) from None
            reason = type(exc).__name__
        else:
            status = response.status_code
            if final or not (status == 429 or 500 <= status < 600):
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as exc:
                    raise RuntimeError(redact_secrets(str(exc))) from None
                return response
            reason = f"HTTP {status}"
        wait = _retry_wait(response, attempt)
        print(
            f"  WARNING {reason}; retrying in {wait:g}s "
            f"(attempt {attempt + 1}/{MAX_RETRIES})",
            file=sys.stderr,
        )
        time.sleep(wait)
