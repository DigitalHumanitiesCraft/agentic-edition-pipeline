"""Provider provenance and chunk recovery use mocked calls only."""

import importlib
import json

import pytest

import config
import llm
from call_records import recording
from conftest import FakeResponse, page_images, read_json

step3 = importlib.import_module("03_transcribe")


def test_full_gemini_response_and_multipart_answer(tmp_path, monkeypatch):
    payload = {
        "modelVersion": "mock-model",
        "usageMetadata": {"totalTokenCount": 99},
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "internal", "thought": True},
                        {"text": "one"},
                        {"text": "two"},
                    ]
                },
            }
        ],
    }

    monkeypatch.setattr(config, "GEMINI_API_KEY", "secret-fixture")
    monkeypatch.setattr(
        llm, "_request_with_retry", lambda *a, **k: FakeResponse(payload=payload)
    )
    path = tmp_path / "record.json"
    with recording(path, {"prompt": "A secret-fixture"}) as record:
        record["answer"] = llm.call_llm("gemini", "mock", "Prompt")
    result = read_json(path)
    assert result["answer"] == "onetwo"
    assert result["responses"][0]["body"] == payload
    assert "secret-fixture" not in path.read_text(encoding="utf-8")


def test_failed_call_is_recorded(tmp_path):
    path = tmp_path / "failure.json"
    with pytest.raises(RuntimeError), recording(path, {"model": "mock"}):
        raise RuntimeError("provider unavailable")
    assert read_json(path)["error"] == "provider unavailable"


def test_resume_keeps_successful_chunk_and_invalidates_prompt(tmp_path, monkeypatch):
    images = page_images(tmp_path / "sources", 2)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(step3, "find_images_for_document", lambda doc: images)
    calls = []
    fail_second = True

    def provider(provider, model, prompt, images):
        number = 1 if "source pages 1-1" in prompt else 2
        calls.append(number)
        if number == 2 and fail_second:
            raise RuntimeError("interrupted")
        return json.dumps(
            {"pages": [{"page": number, "transcription": f"Page {number}"}]}
        )

    monkeypatch.setattr(step3, "call_llm", provider)
    args = ({"id": "synthetic"}, "prompt", "gemini", "mock", 1, False)
    assert step3.transcribe_document(*args)["stage"] == "api_call"
    assert calls == [1, 2]
    fail_second = False
    assert step3.transcribe_document(*args) is None
    assert calls == [1, 2, 2]
    data = read_json(tmp_path / "transcriptions/synthetic.json")
    assert not step3.contract.file_violations(data)
    assert len(list((tmp_path / "llm-calls/synthetic").glob("*.json"))) == 3
    assert step3.transcribe_document(*args[:-1], True) is None
    assert calls == [1, 2, 2, 1, 2]


def test_cached_chunk_bound_to_prompt_and_image_bytes(tmp_path, monkeypatch):
    image = tmp_path / "source.png"
    image.write_bytes(b"one")
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(step3, "find_images_for_document", lambda doc: [image, image])
    calls = []

    def provider(provider, model, prompt, images):
        calls.append(prompt)
        if "source pages 2-2" in prompt:
            raise RuntimeError("second fails")
        return json.dumps({"pages": [{"page": 1, "transcription": "Text"}]})

    monkeypatch.setattr(step3, "call_llm", provider)
    for prompt, content in (("first", b"one"), ("second", b"one"), ("second", b"two")):
        image.write_bytes(content)
        assert step3.transcribe_document(
            {"id": "synthetic"}, prompt, "gemini", "mock", 1, False
        )
    assert len(calls) == 6
