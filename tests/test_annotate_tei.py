"""Runnable checks for step 5: honest provenance and exit code.

Step 5 generates TEI deterministically. The validation report must say so
and must not name a provider, a model, or a prompt template that no run
used. A document that could not be processed has to reach the shell as a
non-zero exit code.
"""
import json
import sys

import pytest

from conftest import load_step

step5 = load_step("05_annotate_tei")


def _prepare_dirs(monkeypatch, tmp_path):
    dirs = {name: tmp_path / name for name in
            ("validated", "transcriptions", "tei", "results_tei", "reports")}
    for path in dirs.values():
        path.mkdir()
    monkeypatch.setattr(step5, "VALIDATED_DIR", dirs["validated"])
    monkeypatch.setattr(step5, "TRANSCRIPTIONS_DIR", dirs["transcriptions"])
    monkeypatch.setattr(step5, "TEI_DIR", dirs["tei"])
    monkeypatch.setattr(step5, "RESULTS_TEI_DIR", dirs["results_tei"])
    monkeypatch.setattr(step5, "RESULTS_REPORTS_DIR", dirs["reports"])
    return dirs


def test_report_meta_documents_deterministic_generation(
    monkeypatch, tmp_path, fixture_transcription
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_transcription, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    report = json.loads(
        (dirs["reports"] / "fixture1_validation.json").read_text(encoding="utf-8")
    )
    assert report["_meta"]["script"] == "05_annotate_tei.py"
    assert report["_meta"]["pipeline_step"] == 5
    assert "provider" not in report["_meta"]
    assert "model" not in report["_meta"]
    assert "prompt_template" not in report["_meta"]


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, tmp_path):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "broken.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", "--all"])

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1


def test_main_returns_cleanly_when_every_object_succeeds(
    monkeypatch, tmp_path, fixture_transcription
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_transcription, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", "--all"])

    step5.main()

    assert (dirs["results_tei"] / "fixture1.xml").exists()
