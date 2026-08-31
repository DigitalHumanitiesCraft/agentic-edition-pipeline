"""Runnable checks for step 4: judge transport failure and exit code.

A judge that could not be reached says nothing about the transcription, so
it must not be counted as a negative verdict. A processing error, in
contrast, has to reach the shell as a non-zero exit code, while a
substantive finding (status problematic) is a normal result.
"""

import json
import sys
from pathlib import Path

import pytest

from conftest import load_step

step4 = load_step("04_validate")
llm = load_step("llm")


# ---------------------------------------------------------------------------
# LLM judge transport failure
# ---------------------------------------------------------------------------


def test_transport_failure_marks_the_page_unreviewed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(llm, "call_llm", boom)

    results = step4.run_llm_judge([{"page": 1, "transcription": "Text"}], "prompt")

    assert results[0]["confidence"] == step4.JUDGE_UNREVIEWED
    assert results[0]["confidence"] != "uncertain"


def test_invalid_judge_vocabulary_becomes_an_uncertain_contract_finding(monkeypatch):
    monkeypatch.setattr(
        llm,
        "call_llm",
        lambda *_args, **_kwargs: json.dumps(
            {
                "confidence": "confident",
                "summary": "Looks fine.",
                "issues": [
                    {
                        "type": "invented-category",
                        "text": "x",
                        "suggestion": "y",
                        "perspective": "internal_consistency",
                    }
                ],
            }
        ),
    )

    result = step4.run_llm_judge([{"page": 1, "transcription": "Text"}], "prompt")[0]

    assert result["confidence"] == "uncertain"
    assert result["summary"] == "LLM response violated the validation contract."
    assert result["_prompt_hash"]


def test_unreviewed_pages_do_not_make_the_object_problematic():
    clean = [{"name": "r", "count": 0, "severity": "info"}]
    unreviewed = [{"page": 1, "confidence": step4.JUDGE_UNREVIEWED}]

    assert step4.compute_overall_status(clean, None, unreviewed) == "needs_review"


def test_unreachable_judge_leaves_the_object_marked_in_the_output(
    monkeypatch, tmp_path
):
    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(llm, "call_llm", boom)
    monkeypatch.setattr(step4, "VALIDATION_PROVIDER", "gemini")
    monkeypatch.setattr(step4, "VALIDATION_MODEL", "m")
    monkeypatch.setattr(step4, "load_prompt", lambda _n: "prompt")

    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    (src / "doc1.json").write_text(
        json.dumps(
            {
                "_meta": {"script": "test", "timestamp": "2026-08-27T00:00:00+00:00"},
                "object_id": "doc1",
                "pages": [
                    {
                        "page": 1,
                        "transcription": "Text",
                        "review": {"status": "machine_unreviewed", "history": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)

    assert step4.validate_one("doc1", use_llm=True, force=True) is None

    out = json.loads((dst / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "needs_review"
    assert out["validation"]["llm_judge_unreviewed_pages"] == 1
    assert out["_meta"]["executed_prompts"][0]["prompt_hash"]


def test_undeclared_empty_page_needs_review_without_quality_signals(
    monkeypatch, tmp_path
):
    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    (src / "doc1.json").write_text(
        json.dumps(
            {
                "_meta": {
                    "script": "manual",
                    "timestamp": "2026-08-27T00:00:00+00:00",
                },
                "object_id": "doc1",
                "pages": [
                    {
                        "page": 1,
                        "transcription": "",
                        "review": {"status": "machine_unreviewed", "history": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)

    assert step4.validate_one("doc1", use_llm=False, force=True) is None

    out = json.loads((dst / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "needs_review"


def test_low_transcription_confidence_is_preserved_and_needs_review(
    monkeypatch, tmp_path
):
    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    (src / "doc1.json").write_text(
        json.dumps(
            {
                "_meta": {
                    "script": "manual",
                    "timestamp": "2026-08-27T00:00:00+00:00",
                },
                "object_id": "doc1",
                "pages": [
                    {
                        "page": 1,
                        "transcription": "Formal sauberer Text",
                        "review": {"status": "machine_unreviewed", "history": []},
                    }
                ],
                "confidence": "low",
                "confidence_notes": "Vorlage ist sehr blass.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)

    assert step4.validate_one("doc1", use_llm=False, force=True) is None

    out = json.loads((dst / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "needs_review"
    assert out["confidence"] == "low"
    assert out["confidence_notes"] == "Vorlage ist sehr blass."


def test_nonforced_validation_rejects_changed_transcription(monkeypatch, tmp_path):
    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    source_path = src / "doc1.json"
    source = {
        "_meta": {
            "script": "manual",
            "timestamp": "2026-08-27T00:00:00+00:00",
        },
        "object_id": "doc1",
        "pages": [
            {
                "page": 1,
                "transcription": "First text",
                "review": {"status": "machine_unreviewed", "history": []},
            }
        ],
    }
    source_path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)
    assert step4.validate_one("doc1", use_llm=False, force=True) is None
    source["pages"][0]["transcription"] = "Other text"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    error = step4.validate_one("doc1", use_llm=False, force=False)

    assert error is not None and error["stage"] == "stale"


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------


def _prepare_main(monkeypatch, tmp_path, name: str, content: str):
    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    (src / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)
    monkeypatch.setattr(step4, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", ["04_validate.py", "--all", "--no-llm"])


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path, "broken.json", "{ not json")

    with pytest.raises(SystemExit) as exc:
        step4.main()

    assert exc.value.code == 1


def test_collection_rejects_casefold_collisions(monkeypatch):
    class Inputs:
        def glob(self, _pattern):
            return [Path("Doc.json"), Path("doc.json")]

        def __str__(self):
            return "transcriptions"

    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", Inputs())

    with pytest.raises(SystemExit) as exc:
        step4.collect_objects(None, True)

    assert exc.value.code == 1


def test_problematic_finding_is_a_result_not_a_processing_error(monkeypatch, tmp_path):
    noisy = "x[?] " * 11 + "y[...] " * 6 + "z ##@@ " * 4
    _prepare_main(
        monkeypatch,
        tmp_path,
        "doc1.json",
        json.dumps(
            {
                "_meta": {"script": "test", "timestamp": "2026-08-27T00:00:00+00:00"},
                "object_id": "doc1",
                "pages": [
                    {
                        "page": 1,
                        "transcription": noisy,
                        "review": {"status": "machine_unreviewed", "history": []},
                    }
                ],
            }
        ),
    )

    step4.main()

    out = json.loads((tmp_path / "validated" / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "problematic"
