"""Runnable checks for the provider layer without network access.

An API key must never reach a URL, an error string, or a file on disk. The
checks pin the request shape of every adapter, the transient-failure retry
policy, the detection of answers cut off at the token limit, and the
deterministic JSON repair of model output. Synthetic payloads stand in for
provider responses, because the tests must not call a provider.
"""

import os
import socket

import pytest
import requests

import config
import llm
from conftest import API_KEY_NAMES, FakeResponse, NetworkBlocked

SECRET = "AIzaTESTKEY0123456789"


def test_the_suite_cannot_reach_a_provider_or_an_external_host():
    for name in API_KEY_NAMES:
        assert getattr(config, name) == ""
        assert name not in os.environ
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    with pytest.raises(NetworkBlocked):
        requests.get("https://192.0.2.1/", timeout=1)
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)
    with pytest.raises(NetworkBlocked):
        llm.call_llm("ollama", "m", "prompt")
    with (
        socket.create_server(("127.0.0.1", 0)) as server,
        socket.create_connection(server.getsockname(), timeout=1),
    ):
        pass


def _all_keys(monkeypatch) -> None:
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setattr(config, name, SECRET)


ANSWERS = {
    "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    "openai": {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
    "anthropic": {
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
    },
    "ollama": {"response": "ok", "done_reason": "stop"},
}


@pytest.mark.parametrize(
    ("provider", "url", "key_header", "temperature_path"),
    [
        (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
            ("x-goog-api-key", SECRET),
            ("generationConfig", "temperature"),
        ),
        (
            "openai",
            "https://api.openai.com/v1/chat/completions",
            ("Authorization", f"Bearer {SECRET}"),
            ("temperature",),
        ),
        (
            "anthropic",
            "https://api.anthropic.com/v1/messages",
            ("x-api-key", SECRET),
            ("temperature",),
        ),
        ("ollama", None, None, ("options", "temperature")),
    ],
)
def test_request_shape_per_provider(
    monkeypatch, provider, url, key_header, temperature_path
):
    captured: dict = {}

    def fake_request(method, request_url, **kwargs):
        captured.update(method=method, url=request_url, **kwargs)
        return FakeResponse(payload=ANSWERS[provider])

    _all_keys(monkeypatch)
    monkeypatch.setattr(llm, "_request_with_retry", fake_request)

    assert llm.call_llm(provider, "m", "prompt") == "ok"

    assert captured["method"] == "POST"
    assert captured["url"] == (url or f"{config.OLLAMA_BASE_URL}/api/generate")
    assert "key=" not in captured["url"]
    assert SECRET not in captured["url"]
    headers = captured.get("headers", {})
    if key_header:
        assert headers[key_header[0]] == key_header[1]
    else:
        assert SECRET not in str(headers)
    value = captured["json"]
    for key in temperature_path:
        value = value[key]
    assert value == config.TEMPERATURE
    if provider != "gemini":
        assert captured["json"]["model"] == "m"


def test_missing_key_fails_before_any_request(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(
        llm, "_request_with_retry", lambda *a, **k: pytest.fail("request sent")
    )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        llm.call_llm("openai", "m", "prompt")


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unknown provider"):
        llm.call_llm("mistral", "m", "prompt")


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        (
            "gemini",
            {
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "{"}]},
                    }
                ]
            },
        ),
        (
            "openai",
            {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]},
        ),
        (
            "anthropic",
            {"content": [{"type": "text", "text": "{"}], "stop_reason": "max_tokens"},
        ),
        ("ollama", {"response": "{", "done_reason": "length"}),
    ],
)
def test_truncated_answer_raises_a_distinct_error(monkeypatch, provider, payload):
    _all_keys(monkeypatch)
    monkeypatch.setattr(
        llm, "_request_with_retry", lambda *a, **k: FakeResponse(payload=payload)
    )

    with pytest.raises(llm.TruncatedResponseError, match=provider.capitalize()[:4]):
        llm.call_llm(provider, "m", "prompt")


def _scripted_requests(monkeypatch, outcomes: list) -> list[float]:
    """Replace the network with a fixed sequence of responses or exceptions."""
    sleeps: list[float] = []
    queue = list(outcomes)

    def fake_request(method, url, **kwargs):
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(llm.requests, "request", fake_request)
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    return sleeps


def test_transient_failures_are_retried_with_backoff_and_retry_after(monkeypatch):
    sleeps = _scripted_requests(
        monkeypatch,
        [
            FakeResponse(status_code=429, headers={"Retry-After": "30"}),
            FakeResponse(status_code=503),
            requests.exceptions.ConnectionError("reset"),
            requests.exceptions.Timeout("slow"),
            FakeResponse(payload={"ok": True}),
        ],
    )

    response = llm._request_with_retry("POST", "https://host/api")

    assert response.json() == {"ok": True}
    base = llm.BACKOFF_BASE
    assert sleeps == [30.0, base * 2, base * 4, base * 8]


def test_retry_after_is_capped(monkeypatch):
    sleeps = _scripted_requests(
        monkeypatch,
        [
            FakeResponse(status_code=429, headers={"Retry-After": "86400"}),
            FakeResponse(payload={}),
        ],
    )

    llm._request_with_retry("POST", "https://host/api")

    assert sleeps == [llm.MAX_RETRY_WAIT]


def test_client_errors_are_not_retried(monkeypatch):
    sleeps = _scripted_requests(monkeypatch, [FakeResponse(status_code=400)])

    with pytest.raises(RuntimeError, match="400"):
        llm._request_with_retry("POST", "https://host/api")

    assert sleeps == []


def test_retries_are_bounded(monkeypatch):
    sleeps = _scripted_requests(
        monkeypatch,
        [FakeResponse(status_code=500)] * (llm.MAX_RETRIES + 1),
    )

    with pytest.raises(RuntimeError, match="500"):
        llm._request_with_retry("POST", "https://host/api")

    assert len(sleeps) == llm.MAX_RETRIES


def test_exhausted_connection_errors_are_redacted(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", SECRET)
    _scripted_requests(
        monkeypatch,
        [requests.exceptions.ConnectionError(f"refused ?key={SECRET}")]
        * (llm.MAX_RETRIES + 1),
    )

    with pytest.raises(RuntimeError) as exc:
        llm._request_with_retry("POST", "https://host/api")

    assert SECRET not in str(exc.value)
    assert exc.value.__cause__ is None


def test_redact_removes_query_key_and_known_key_value(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", SECRET)
    text = f"401 for https://host/v1beta/models/m:generateContent?key={SECRET}&alt=json"

    out = config.redact_secrets(text)

    assert SECRET not in out
    assert "key=[redacted]" in out
    assert "alt=json" in out


def test_redact_removes_a_bare_key_value_without_query_syntax(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", SECRET)
    assert SECRET not in config.redact_secrets(f"header x-api-key: {SECRET} rejected")


def test_http_error_from_provider_is_reraised_without_the_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", SECRET)
    error = requests.exceptions.HTTPError(
        f"401 Client Error for url: https://host/m:generateContent?key={SECRET}"
    )
    monkeypatch.setattr(
        llm.requests,
        "request",
        lambda *a, **k: FakeResponse(status_code=401, error=error),
    )

    with pytest.raises(RuntimeError) as exc:
        llm._request_with_retry("POST", "https://host/m:generateContent")

    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value.__cause__)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"pages": []}', {"pages": []}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("```\n[1, 2]\n```", [1, 2]),
        ('{\n"text": "erste\nzweite"\n}', {"text": "erste\nzweite"}),
        ("Keine JSON-Antwort", None),
    ],
)
def test_parse_json_response_repairs_fences_and_raw_newlines(text, expected):
    assert llm.parse_json_response(text) == expected
