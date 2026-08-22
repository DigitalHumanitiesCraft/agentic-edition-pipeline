"""Synthetic checks for the RelaxNG conformance check."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aep_eval import tei_check  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "evaluation"
MINI = FIXTURES / "mini.rng"


def test_valid_file_passes_and_reports_header():
    result = tei_check.check_tei(FIXTURES / "good.xml", MINI)
    assert result.valid and result.well_formed and result.has_tei_header
    assert result.status == "valid" and result.errors == []


def test_invalid_file_fails_with_located_errors():
    result = tei_check.check_tei(FIXTURES / "bad.xml", MINI)
    assert not result.valid and result.well_formed and result.has_tei_header
    assert result.status == "invalid"
    assert any("line" in e for e in result.errors)
    assert result.to_dict()["error_count"] == len(result.errors)


def test_not_well_formed_is_reported(tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<TEI><open>", encoding="utf-8")
    result = tei_check.check_tei(path, MINI)
    assert not result.well_formed and not result.valid and not result.has_tei_header
    assert result.errors[0].startswith("not well-formed")


def test_missing_schema_is_fail_fast(tmp_path):
    with pytest.raises(FileNotFoundError, match="RelaxNG schema not found"):
        tei_check.check_tei(FIXTURES / "good.xml", tmp_path / "none.rng")


def test_invalid_schema_is_fail_fast(tmp_path):
    bad_schema = tmp_path / "bad.rng"
    bad_schema.write_text(
        "<grammar xmlns='http://relaxng.org/ns/structure/1.0'><start/></grammar>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid RelaxNG schema"):
        tei_check.load_schema(bad_schema)


def test_header_detection_without_namespace(tmp_path):
    path = tmp_path / "plain.xml"
    path.write_text(
        "<TEI><teiHeader/><text><body><p>x</p></body></text></TEI>", encoding="utf-8"
    )
    result = tei_check.check_tei(path, MINI)
    assert result.has_tei_header and not result.valid
