"""Runnable checks for the provider layer: key transport and key redaction.

An API key must never reach a URL, an error string, or a file on disk. These
checks pin down the Gemini header transport and the redaction helper that
every error path in llm.py routes through.
"""
import pytest
import requests

from conftest import load_step

llm = load_step("llm")

SECRET = "AIzaTESTKEY0123456789"


class _FakeResponse:
    """Minimal stand-in for requests.Response: status, payload, failure mode."""

    def __init__(self, status_code: int = 200, payload: dict | None = None, error=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._error = error

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error


def test_gemini_sends_the_key_as_header_not_query(monkeypatch):
    captured: dict = {}

    def fake_request(method, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return _FakeResponse(payload={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    monkeypatch.setattr(llm, "GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(llm, "_request_with_retry", fake_request)

    assert llm._call_gemini("m", "prompt", None, 0.1) == "ok"
    assert "key=" not in captured["url"]
    assert SECRET not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == SECRET


def test_redact_removes_query_key_and_known_key_value(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_API_KEY", SECRET)
    text = f"401 for https://host/v1beta/models/m:generateContent?key={SECRET}&alt=json"

    out = llm.redact_secrets(text)

    assert SECRET not in out
    assert "key=[redacted]" in out
    assert "alt=json" in out


def test_redact_removes_a_bare_key_value_without_query_syntax(monkeypatch):
    monkeypatch.setattr(llm, "ANTHROPIC_API_KEY", SECRET)
    assert SECRET not in llm.redact_secrets(f"header x-api-key: {SECRET} rejected")


def test_http_error_from_provider_is_reraised_without_the_key(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_API_KEY", SECRET)
    error = requests.exceptions.HTTPError(
        f"401 Client Error for url: https://host/m:generateContent?key={SECRET}"
    )
    monkeypatch.setattr(
        llm.requests, "request", lambda *a, **k: _FakeResponse(status_code=401, error=error)
    )

    with pytest.raises(RuntimeError) as exc:
        llm._request_with_retry("POST", "https://host/m:generateContent")

    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value.__cause__)
