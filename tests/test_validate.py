"""Runnable checks for step 4: judge vocabulary, call records and exit code.

A judge that could not be reached says nothing about the transcription, so
it must not be counted as a negative verdict. Every judge call leaves a call
record. A processing error, in contrast, has to reach the shell as a
non-zero exit code, while a substantive finding (status problematic) is a
normal result.
"""

import json
import re
import sys
from pathlib import Path

import pytest

from conftest import load_step

step4 = load_step("04_validate")
llm = load_step("llm")
config = load_step("config")
contract = load_step("contract")


def _judge(template: str = "prompt") -> object:
    return step4.Judge("gemini", "m", template, contract.text_hash(template))


def _transcription(text: str = "Text", **extra) -> dict:
    return {
        "_meta": {"script": "manual", "timestamp": "2026-08-27T00:00:00+00:00"},
        "object_id": "doc1",
        "pages": [
            {
                "page": 1,
                "transcription": text,
                "review": {"status": "machine_unreviewed", "history": []},
            }
        ],
        **extra,
    }


def _dirs(tmp_path: Path, data: dict | None = None) -> dict:
    dirs = {
        "transcriptions_dir": tmp_path / "transcriptions",
        "validated_dir": tmp_path / "validated",
        "calls_dir": tmp_path / "llm-calls",
    }
    dirs["transcriptions_dir"].mkdir()
    dirs["validated_dir"].mkdir()
    if data is not None:
        (dirs["transcriptions_dir"] / "doc1.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
    return dirs


def _answer(issues: list[dict], confidence: str = "likely") -> str:
    return json.dumps(
        {"confidence": confidence, "summary": "Checked.", "issues": issues}
    )


# Judge vocabulary


def _prompt_enum(field: str) -> set[str]:
    block = config.load_prompt(step4.PROMPT_TEMPLATE)
    match = re.search(rf'"{field}": "([^"]+)"', block)
    assert match, f"{field} enum missing from the prompt block"
    return {value.strip() for value in match.group(1).split("|")}


def test_accepted_vocabulary_equals_the_prompt_block():
    assert _prompt_enum("type") == step4.JUDGE_ISSUE_TYPES
    assert _prompt_enum("perspective") == step4.JUDGE_PERSPECTIVES


def test_prompt_vocabulary_answer_is_a_valid_verdict(monkeypatch, tmp_path):
    issue = {
        "type": "ocr_artifact",
        "text": "##@@",
        "suggestion": "Compare with the facsimile.",
        "perspective": "orthographic",
    }
    monkeypatch.setattr(llm, "call_llm", lambda *_a, **_k: _answer([issue]))

    results, _calls = step4.run_llm_judge(
        [{"page": 1, "transcription": "Text"}], _judge(), "doc1", tmp_path / "calls"
    )

    assert results[0]["confidence"] == "likely"
    assert results[0]["issues"] == [issue]


def test_invalid_judge_vocabulary_becomes_an_uncertain_contract_finding(
    monkeypatch, tmp_path
):
    issue = {
        "type": "reading",
        "text": "x",
        "suggestion": "y",
        "perspective": "internal_consistency",
    }
    monkeypatch.setattr(
        llm, "call_llm", lambda *_a, **_k: _answer([issue], "confident")
    )

    results, _calls = step4.run_llm_judge(
        [{"page": 1, "transcription": "Text"}], _judge(), "doc1", tmp_path / "calls"
    )

    assert results[0]["confidence"] == "uncertain"
    assert results[0]["summary"] == "LLM response violated the validation contract."
    assert results[0]["_prompt_hash"]


# Judge transport failure and call records


def test_transport_failure_marks_the_page_unreviewed(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(llm, "call_llm", boom)

    results, calls = step4.run_llm_judge(
        [{"page": 1, "transcription": "Text"}], _judge(), "doc1", tmp_path / "calls"
    )

    assert results[0]["confidence"] == step4.JUDGE_UNREVIEWED
    record = json.loads((tmp_path / calls[0]["record"]).read_text(encoding="utf-8"))
    assert record["error"] == "connection reset"


def test_every_judge_call_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "call_llm", lambda *_a, **_k: _answer([], "confident"))
    calls_dir = tmp_path / "llm-calls"

    results, calls = step4.run_llm_judge(
        [
            {"page": 1, "transcription": "Erste Seite"},
            {"page": 2, "transcription": "", "page_type": "blank"},
            {"page": 3, "transcription": "Dritte Seite"},
        ],
        _judge("Judge prompt"),
        "doc1",
        calls_dir,
    )

    assert [call["page"] for call in calls] == [1, 3]
    assert [result["page"] for result in results] == [1, 2, 3]
    for call, text in zip(calls, ("Erste Seite", "Dritte Seite"), strict=True):
        assert call["record"].startswith("llm-calls/doc1/")
        record = json.loads((tmp_path / call["record"]).read_text(encoding="utf-8"))
        prompt = "Judge prompt" + step4.TRANSCRIPTION_SEPARATOR + text
        assert record["prompt"] == prompt
        assert (
            record["prompt_hash"] == contract.text_hash(prompt) == call["prompt_hash"]
        )
        assert (record["provider"], record["model"]) == ("gemini", "m")
        assert record["temperature"] == config.TEMPERATURE
        assert json.loads(record["answer"])["confidence"] == "confident"


def test_unwritable_call_record_fails_the_object(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "call_llm", lambda *_a, **_k: _answer([], "confident"))
    blocked = tmp_path / "llm-calls"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(config.ItemFailure) as failure:
        step4.run_llm_judge(
            [{"page": 1, "transcription": "Text"}], _judge(), "doc1", blocked
        )

    assert failure.value.stage == "record"


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
    dirs = _dirs(tmp_path, _transcription())

    assert step4.validate_one("doc1", _judge(), force=True, **dirs) == "needs_review"

    out = json.loads((dirs["validated_dir"] / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "needs_review"
    assert out["validation"]["llm_judge_unreviewed_pages"] == 1
    call = out["_meta"]["executed_prompts"][0]
    assert call["prompt_hash"] == out["validation"]["llm_judge"][0]["_prompt_hash"]
    assert (tmp_path / call["record"]).is_file()
    assert out["_meta"]["prompt_hash"] == contract.text_hash("prompt")
    assert contract.validated_file_violations(out) == []


def test_judge_config_follows_the_configured_provider(monkeypatch):
    monkeypatch.setattr(step4, "VALIDATION_PROVIDER", "gemini")
    monkeypatch.setattr(step4, "VALIDATION_MODEL", "m")
    monkeypatch.setattr(step4, "load_prompt", lambda _name: "prompt")

    assert step4.judge_config(use_llm=True) == _judge()
    assert step4.judge_config(use_llm=False) is None
    monkeypatch.setattr(step4, "VALIDATION_PROVIDER", "")
    assert step4.judge_config(use_llm=True) is None


# Deterministic assessment


def test_undeclared_empty_page_needs_review_without_quality_signals(tmp_path):
    dirs = _dirs(tmp_path, _transcription(""))

    assert step4.validate_one("doc1", None, force=True, **dirs) == "needs_review"


def test_low_transcription_confidence_is_preserved_and_needs_review(tmp_path):
    dirs = _dirs(
        tmp_path,
        _transcription(
            "Formal sauberer Text",
            confidence="low",
            confidence_notes="Vorlage ist sehr blass.",
        ),
    )

    assert step4.validate_one("doc1", None, force=True, **dirs) == "needs_review"

    out = json.loads((dirs["validated_dir"] / "doc1.json").read_text(encoding="utf-8"))
    assert out["confidence"] == "low"
    assert out["confidence_notes"] == "Vorlage ist sehr blass."


def test_nonforced_validation_keeps_a_current_output_and_rejects_a_changed_input(
    tmp_path,
):
    source = _transcription("First text")
    dirs = _dirs(tmp_path, source)
    assert step4.validate_one("doc1", None, force=True, **dirs) == "confident"
    stored = (dirs["validated_dir"] / "doc1.json").read_bytes()

    assert step4.validate_one("doc1", None, force=False, **dirs) == "confident"
    assert (dirs["validated_dir"] / "doc1.json").read_bytes() == stored

    source["pages"][0]["transcription"] = "Other text"
    (dirs["transcriptions_dir"] / "doc1.json").write_text(
        json.dumps(source), encoding="utf-8"
    )
    with pytest.raises(config.ItemFailure) as failure:
        step4.validate_one("doc1", None, force=False, **dirs)

    assert failure.value.stage == "stale"


def test_nonforced_validation_rejects_a_changed_judge_configuration(
    monkeypatch, tmp_path
):
    dirs = _dirs(tmp_path, _transcription())
    assert step4.validate_one("doc1", None, force=True, **dirs) == "confident"
    monkeypatch.setattr(llm, "call_llm", lambda *_a, **_k: _answer([], "confident"))

    with pytest.raises(config.ItemFailure) as failure:
        step4.validate_one("doc1", _judge(), force=False, **dirs)

    assert failure.value.stage == "stale"


def test_judged_output_under_other_acceptance_rules_is_stale(monkeypatch, tmp_path):
    dirs = _dirs(tmp_path, _transcription())
    monkeypatch.setattr(llm, "call_llm", lambda *_a, **_k: _answer([], "confident"))
    step4.validate_one("doc1", _judge(), force=True, **dirs)
    assert step4.validate_one("doc1", _judge(), force=False, **dirs) == "confident"

    monkeypatch.setattr(
        step4, "JUDGE_ISSUE_TYPES", step4.JUDGE_ISSUE_TYPES | {"retired_type"}
    )
    with pytest.raises(config.ItemFailure) as failure:
        step4.validate_one("doc1", _judge(), force=False, **dirs)
    assert failure.value.stage == "stale"

    monkeypatch.undo()
    path = dirs["validated_dir"] / "doc1.json"
    before_identity = json.loads(path.read_text(encoding="utf-8"))
    del before_identity["_meta"]["judge_vocabulary_hash"]
    path.write_text(json.dumps(before_identity), encoding="utf-8")
    with pytest.raises(config.ItemFailure) as failure:
        step4.validate_one("doc1", _judge(), force=False, **dirs)
    assert failure.value.stage == "stale"


def test_filename_and_object_id_must_agree(tmp_path):
    dirs = _dirs(tmp_path)
    (dirs["transcriptions_dir"] / "doc2.json").write_text(
        json.dumps(_transcription()), encoding="utf-8"
    )

    with pytest.raises(config.ItemFailure) as failure:
        step4.validate_one("doc2", None, force=True, **dirs)

    assert failure.value.stage == "contract"
    assert "does not match filename" in failure.value.message


# Command line and exit code


def _prepare_main(monkeypatch, tmp_path, files: dict[str, str], *arguments: str):
    src = tmp_path / "transcriptions"
    dst = tmp_path / "validated"
    src.mkdir()
    dst.mkdir()
    for name, content in files.items():
        (src / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst)
    monkeypatch.setattr(step4, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["04_validate.py", "--no-llm", *(arguments or ("--all",))]
    )
    return dst


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, tmp_path):
    dst = _prepare_main(monkeypatch, tmp_path, {"broken.json": "{ not json"})

    with pytest.raises(SystemExit) as exc:
        step4.main()

    assert exc.value.code == 1
    errors = json.loads((dst / "errors.json").read_text(encoding="utf-8"))["errors"]
    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("broken", "read")
    ]


def test_main_rejects_casefold_collisions(monkeypatch, tmp_path):
    class Inputs:
        def glob(self, _pattern):
            return [Path("Doc.json"), Path("doc.json")]

    _prepare_main(monkeypatch, tmp_path, {})
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", Inputs())

    with pytest.raises(SystemExit) as exc:
        step4.main()

    assert exc.value.code == 1


def test_main_sample_bounds_the_selection(monkeypatch, tmp_path):
    first = _transcription()
    second = {**_transcription(), "object_id": "doc2"}
    dst = _prepare_main(
        monkeypatch,
        tmp_path,
        {"doc1.json": json.dumps(first), "doc2.json": json.dumps(second)},
        "--all",
        "--sample",
        "1",
    )

    step4.main()

    assert (dst / "doc1.json").is_file()
    assert not (dst / "doc2.json").exists()


def test_problematic_finding_is_a_result_not_a_processing_error(monkeypatch, tmp_path):
    noisy = "x[?] " * 11 + "y[...] " * 6 + "z ##@@ " * 4
    dst = _prepare_main(
        monkeypatch, tmp_path, {"doc1.json": json.dumps(_transcription(noisy))}
    )

    step4.main()

    out = json.loads((dst / "doc1.json").read_text(encoding="utf-8"))
    assert out["overall_status"] == "problematic"
    assert json.loads((dst / "errors.json").read_text(encoding="utf-8"))["errors"] == []
