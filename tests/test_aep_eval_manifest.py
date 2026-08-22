"""Synthetic checks for the fixture manifest contract."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aep_eval import manifest as mf  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "evaluation"


def _write(tmp_path: Path, data: dict, name: str = "m.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _minimal(**overrides) -> dict:
    data = {
        "manifest_version": "0.1",
        "name": "t",
        "created": "2026-08-22",
        "profile": "hsa-strict",
        "fixtures": [
            {
                "id": "f1",
                "checks": ["cer"],
                "maturity": "formal-validation",
                "hypothesis": {
                    "kind": "text",
                    "path": str(FIXTURES / "hypothesis.txt"),
                },
                "reference": {"kind": "text", "path": str(FIXTURES / "reference.txt")},
            }
        ],
    }
    data.update(overrides)
    return data


def test_example_manifest_loads_and_resolves_relative_paths():
    m = mf.load_manifest(FIXTURES / "manifest.json")
    assert m.name == "synthetic-example" and len(m.fixtures) == 5
    by_id = {f.id: f for f in m.fixtures}
    assert by_id["text-pair"].hypothesis.path == (FIXTURES / "hypothesis.txt").resolve()
    assert by_id["zbz-pair"].profile == "zbz-fidelity"
    assert by_id["good-tei"].relaxng_schema == (FIXTURES / "mini.rng").resolve()
    assert by_id["edition-vs-transcription"].hypothesis.pages == (1, 2)
    assert len(m.sha256) == 64


def test_schema_violation_is_rejected_with_location(tmp_path):
    path = _write(tmp_path, {"manifest_version": "0.1", "name": "t", "fixtures": []})
    with pytest.raises(mf.ManifestError, match=r"evaluation-fixture\.schema\.json"):
        mf.load_manifest(path)


def test_unknown_profile_is_rejected(tmp_path):
    path = _write(tmp_path, _minimal(profile="unknown-profile"))
    with pytest.raises(mf.ManifestError):
        mf.load_manifest(path)


def test_cer_without_reference_is_rejected(tmp_path):
    data = _minimal()
    del data["fixtures"][0]["reference"]
    with pytest.raises(mf.ManifestError, match="needs hypothesis and reference"):
        mf.load_manifest(_write(tmp_path, data))


def test_relaxng_without_schema_is_rejected(tmp_path):
    data = _minimal()
    data["fixtures"][0] = {
        "id": "t",
        "checks": ["relaxng"],
        "maturity": "formal-validation",
        "tei": {"path": str(FIXTURES / "good.xml")},
    }
    with pytest.raises(mf.ManifestError, match="relaxng_schema"):
        mf.load_manifest(_write(tmp_path, data))


def test_duplicate_ids_are_rejected(tmp_path):
    data = _minimal()
    data["fixtures"].append(dict(data["fixtures"][0]))
    with pytest.raises(mf.ManifestError, match="duplicate"):
        mf.load_manifest(_write(tmp_path, data))


def test_missing_manifest_and_invalid_json(tmp_path):
    with pytest.raises(mf.ManifestError, match="not found"):
        mf.load_manifest(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="not valid JSON"):
        mf.load_manifest(broken)


def test_sha256_of_matches_hashlib():
    import hashlib

    path = FIXTURES / "reference.txt"
    assert mf.sha256_of(path) == hashlib.sha256(path.read_bytes()).hexdigest()
