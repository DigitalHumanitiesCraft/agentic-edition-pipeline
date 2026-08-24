"""Runnable checks for step 4: judge transport failure and exit code.

A judge that could not be reached says nothing about the transcription, so
it must not be counted as a negative verdict. A processing error, in
contrast, has to reach the shell as a non-zero exit code, while a
substantive finding (status problematic) is a normal result.
"""
import json
import sys

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


def test_unreviewed_pages_do_not_make_the_object_problematic():
    clean = [{"name": "r", "count": 0, "severity": "info"}]
    unreviewed = [{"page": 1, "confidence": step4.JUDGE_UNREVIEWED}]

    assert step4.compute_overall_status(clean, None, unreviewed) == "needs_review"


def test_unreachable_judge_leaves_the_object_marked_in_the_output(monkeypatch, tmp_path):
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
        json.dumps({"object_id": "doc1", "pages": [{"page": 1, "transcription": "Text"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)

    assert step4.validate_one("doc1", use_llm=True, force=True) is None

    out = json.loads((dst / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "needs_review"
    assert out["validation"]["llm_judge_unreviewed_pages"] == 1


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


def test_problematic_finding_is_a_result_not_a_processing_error(monkeypatch, tmp_path):
    noisy = "x[?] " * 11 + "y[...] " * 6 + "z ##@@ " * 4
    _prepare_main(
        monkeypatch, tmp_path, "doc1.json",
        json.dumps({"object_id": "doc1", "pages": [{"page": 1, "transcription": noisy}]}),
    )

    step4.main()

    out = json.loads((tmp_path / "validated" / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "problematic"
