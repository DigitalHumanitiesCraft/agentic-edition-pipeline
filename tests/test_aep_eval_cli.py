"""End-to-end checks of the aep_eval CLI on the synthetic example manifest:
result schema, Markdown report, exit codes for clean runs, fixture errors and
unusable manifests.
"""

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aep_eval.__main__ import main  # noqa: E402
from aep_eval.manifest import RESULT_SCHEMA, validate_against_schema  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "evaluation"


def _run(manifest: Path, out: Path, *extra: str) -> int:
    return main([str(manifest), "--out", str(out), *extra])


def test_example_manifest_runs_clean_and_validates(tmp_path):
    out = tmp_path / "out"
    assert _run(FIXTURES / "manifest.json", out) == 0
    report = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert validate_against_schema(report, RESULT_SCHEMA) == []
    by_key = {(r["fixture_id"], r["metric"]): r for r in report["results"]}
    assert by_key[("text-pair", "cer")]["status"] == "ok"
    assert by_key[("text-pair", "cer")]["value"] > 0
    assert by_key[("edition-vs-transcription", "cer")]["details"]["pages"] == [1, 2]
    assert by_key[("zbz-pair", "cer")]["value"] == 0.0
    assert by_key[("good-tei", "relaxng")]["status"] == "valid"
    assert by_key[("bad-tei", "relaxng")]["status"] == "invalid"
    assert all(
        len(h) == 64 for r in report["results"] for h in r["input_hashes"].values()
    )
    aggregates = {(a["metric"], a["profile"]): a for a in report["aggregates"]}
    assert aggregates[("cer", "hsa-strict")]["method"] == "char-weighted"
    assert aggregates[("cer", "zbz-fidelity")]["method"] == "fixture-mean"
    assert aggregates[("relaxng", None)]["value"] == 1
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "## Aggregates" in md and "bad-tei" in md and "none" in md


def test_strict_turns_invalid_tei_into_exit_one(tmp_path):
    assert _run(FIXTURES / "manifest.json", tmp_path / "out", "--strict") == 1


def test_missing_input_file_is_collected_and_exits_one(tmp_path):
    data = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    data["fixtures"][0]["hypothesis"]["path"] = "does-not-exist.txt"
    for name in (
        "reference.txt",
        "hypothesis.txt",
        "edition.xml",
        "transcription.json",
        "good.xml",
        "bad.xml",
        "mini.rng",
    ):
        shutil.copy(FIXTURES / name, tmp_path / name)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "out"
    assert _run(manifest, out) == 1
    report = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert report["errors"][0]["fixture_id"] == "text-pair"
    assert "not found" in report["errors"][0]["message"]
    # the other fixtures still ran
    assert any(r["status"] == "ok" for r in report["results"])


def test_hash_mismatch_is_a_fixture_error(tmp_path):
    data = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    data["fixtures"] = [data["fixtures"][0]]
    data["fixtures"][0]["hypothesis"]["sha256"] = "0" * 64
    for name in ("reference.txt", "hypothesis.txt"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert _run(manifest, tmp_path / "out") == 1
    report = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert "sha256 mismatch" in report["errors"][0]["message"]


def test_unusable_manifest_exits_two(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "manifest_version": "0.1",
                "name": "x",
                "created": "2026-08-22",
                "profile": "nope",
                "fixtures": [
                    {
                        "id": "a",
                        "checks": ["cer"],
                        "maturity": "formal-validation",
                        "hypothesis": {"kind": "text", "path": "a"},
                        "reference": {"kind": "text", "path": "b"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _run(bad, tmp_path / "out") == 2
    assert _run(tmp_path / "missing.json", tmp_path / "out") == 2


def test_invalid_relaxng_schema_is_a_fixture_error(tmp_path):
    schema = tmp_path / "bad.rng"
    schema.write_text(
        "<grammar xmlns='http://relaxng.org/ns/structure/1.0'><start/></grammar>",
        encoding="utf-8",
    )
    shutil.copy(FIXTURES / "good.xml", tmp_path / "good.xml")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": "0.1",
                "name": "x",
                "created": "2026-08-22",
                "relaxng_schema": "bad.rng",
                "fixtures": [
                    {
                        "id": "g",
                        "checks": ["relaxng"],
                        "maturity": "formal-validation",
                        "tei": {"path": "good.xml"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _run(manifest, tmp_path / "out") == 1
