"""Runnable checks for step 3: chunk merge, contract gate, error reporting.

Covers the three ways a transcription run can lose information silently: a
multi-chunk merge that drops object-level fields, a model answer written to
disk although it carries no usable pages, and an API failure whose message
would otherwise carry the key into errors.json.
"""
import json
import sys

import pytest

from conftest import load_step

step3 = load_step("03_transcribe")
llm = load_step("llm")

SECRET = "AIzaTESTKEY0123456789"


# ---------------------------------------------------------------------------
# Chunk merge
# ---------------------------------------------------------------------------

def test_merge_keeps_metadata_and_concatenates_notes():
    chunks = [
        {
            "metadata": {"title": "Brief", "language": "de"},
            "pages": [{"page": 1, "transcription": "a"}],
            "confidence": "high",
            "confidence_notes": "Erste Haelfte klar.",
        },
        {
            "pages": [{"page": 2, "transcription": "b"}],
            "confidence": "low",
            "confidence_notes": "Zweite Haelfte blass.",
        },
    ]

    merged = step3.merge_chunks(chunks)

    assert merged["metadata"] == {"title": "Brief", "language": "de"}
    assert [p["page"] for p in merged["pages"]] == [1, 2]
    assert merged["confidence"] == "low"
    assert "Erste Haelfte klar." in merged["confidence_notes"]
    assert "Zweite Haelfte blass." in merged["confidence_notes"]


def test_merge_confidence_stays_the_contract_vocabulary():
    merged = step3.merge_chunks([
        {"pages": [], "confidence": "medium"},
        {"pages": [], "confidence": "high"},
    ])
    assert merged["confidence"] == "medium"

    undeclared = step3.merge_chunks([{"pages": []}, {"pages": []}])
    assert undeclared["confidence"] == ""


# ---------------------------------------------------------------------------
# Contract gate before writing
# ---------------------------------------------------------------------------

def test_unusable_model_response_becomes_an_error_not_an_empty_file(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: [tmp_path / "p1.png"])
    monkeypatch.setattr(step3, "transcribe_chunk", lambda *a, **k: {"summary": "kein Text"})

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err is not None
    assert err["stage"] == "contract"
    assert not (out_dir / "doc1.json").exists()


def test_usable_model_response_is_written(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: [tmp_path / "p1.png"])
    monkeypatch.setattr(
        step3, "transcribe_chunk",
        lambda *a, **k: {"pages": [{"page": 1, "transcription": "Text"}], "confidence": "high"},
    )

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err is None
    written = json.loads((out_dir / "doc1.json").read_text(encoding="utf-8"))
    assert written["pages"][0]["transcription"] == "Text"


# ---------------------------------------------------------------------------
# Key redaction on the error path
# ---------------------------------------------------------------------------

def test_api_failure_never_writes_the_key_into_the_error_record(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(llm, "GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: [tmp_path / "p1.png"])

    def boom(*a, **k):
        raise RuntimeError(f"call failed: https://host/m:generateContent?key={SECRET}")

    monkeypatch.setattr(step3, "transcribe_chunk", boom)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err["stage"] == "api_call"
    assert SECRET not in err["error"]

    step3.write_errors([err], out_dir)
    assert SECRET not in (out_dir / "errors.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------

def _prepare_main(monkeypatch, tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"documents": [{"id": "doc1"}]}), encoding="utf-8")
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(step3, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step3, "missing_api_key", lambda _provider: None)
    monkeypatch.setattr(step3, "load_prompt", lambda _name: "prompt")
    monkeypatch.setattr(sys, "argv", ["03_transcribe.py", "--all"])


def test_main_exits_nonzero_when_a_document_fails(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: [])

    with pytest.raises(SystemExit) as exc:
        step3.main()

    assert exc.value.code == 1


def test_main_returns_cleanly_when_every_document_succeeds(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(step3, "transcribe_document", lambda *a, **k: None)

    step3.main()
