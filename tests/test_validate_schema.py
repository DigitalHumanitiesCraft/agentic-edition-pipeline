"""Runnable checks for the schema validation runner (ADR-005).

Covers: the per-fork validation target in config, per-file valid/invalid
reporting and exit status, the clear failure when the configured schema file
is absent, and the offline path from a transcription file through steps 4
and 5 to TEI that validates against the shipped TEI All schema.
"""

import importlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from lxml import etree

import config
import validate_schema as vs
from conftest import EVALUATION_FIXTURES as FIXTURES
from conftest import read_json

step4 = importlib.import_module("04_validate")
step5 = importlib.import_module("05_annotate_tei")


MINI_RNG = """<grammar xmlns="http://relaxng.org/ns/structure/1.0">
  <start>
    <element name="doc">
      <oneOrMore><element name="p"><text/></element></oneOrMore>
    </element>
  </start>
</grammar>
"""


@pytest.fixture
def mini_schema(tmp_path) -> Path:
    schema = tmp_path / "mini.rng"
    schema.write_text(MINI_RNG, encoding="utf-8")
    return schema


def _documents(tmp_path) -> tuple[Path, Path]:
    good = tmp_path / "good.xml"
    good.write_text("<doc><p>x</p></doc>", encoding="utf-8")
    bad = tmp_path / "bad.xml"
    bad.write_text("<doc><q/></doc>", encoding="utf-8")
    return good, bad


def test_configured_validation_target_exists():
    assert Path(config.VALIDATION_SCHEMA).is_file()


def test_compiled_schema_is_reused_until_the_file_changes(tmp_path, mini_schema):
    first = vs.load_schema(mini_schema)
    assert vs.load_schema(mini_schema) is first

    mini_schema.write_text(MINI_RNG.replace('name="p"', 'name="q"'), encoding="utf-8")
    os.utime(mini_schema, ns=(0, mini_schema.stat().st_mtime_ns + 1_000_000_000))
    changed = vs.load_schema(mini_schema)

    assert changed is not first
    doc = tmp_path / "doc.xml"
    doc.write_text("<doc><q>x</q></doc>", encoding="utf-8")
    assert vs.validate_files(mini_schema, [doc])[0].valid


def test_invalid_schema_raises_value_error_naming_the_path(tmp_path):
    schema = tmp_path / "broken.rng"
    schema.write_text(
        "<grammar xmlns='http://relaxng.org/ns/structure/1.0'/>", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="broken"):
        vs.validate_files(schema, [])


def test_valid_and_invalid_files_are_reported(tmp_path, mini_schema):
    good, bad = _documents(tmp_path)
    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<doc>", encoding="utf-8")

    by_name = {
        r.path.name: r for r in vs.validate_files(mini_schema, [good, bad, malformed])
    }

    assert by_name["good.xml"].valid
    assert not by_name["bad.xml"].valid
    assert by_name["bad.xml"].errors
    assert by_name["malformed.xml"].errors[0].startswith("not well-formed")


def test_missing_schema_fails_with_pointer(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        vs.validate_files(tmp_path / "absent.rng", [])
    assert "VALIDATION_SCHEMA" in str(exc.value)


@pytest.mark.parametrize(
    ("documents", "schema_name", "code"),
    [
        (["good"], "mini.rng", 0),
        (["good", "bad"], "mini.rng", 1),
        (["good"], "absent.rng", 2),
    ],
    ids=["all-valid", "one-invalid", "missing-schema"],
)
def test_main_exit_status_follows_the_results(
    monkeypatch, tmp_path, mini_schema, capsys, documents, schema_name, code
):
    paths = dict(zip(("good", "bad"), _documents(tmp_path), strict=True))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_schema.py",
            *(str(paths[name]) for name in documents),
            "--schema",
            str(tmp_path / schema_name),
        ],
    )

    assert vs.main() == code
    if code == 1:
        assert "INVALID  bad.xml" in capsys.readouterr().out


def test_main_without_tei_points_to_step_five(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RESULTS_TEI_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["validate_schema.py"])

    assert vs.main() == 1


def test_offline_path_produces_tei_valid_against_tei_all(
    step4_dirs, step5_dirs, tei_all
):
    """Fixture into data/processed/transcriptions/, then steps 4 and 5.

    This is the path a fork walks without any API key: a contract-conformant
    transcription file, deterministic validation, deterministic TEI. Its
    output has to validate against the TEI All schema the template ships.
    """
    shutil.copyfile(
        FIXTURES / "transcription.json",
        step4_dirs["transcriptions_dir"] / "synthetic1.json",
    )

    step4.validate_one("synthetic1", None, force=True, **step4_dirs)
    step5.annotate_one("synthetic1", {}, validate_only=False, force=True, **step5_dirs)

    report = read_json(step5_dirs["reports_dir"] / "synthetic1_validation.json")
    assert report["well_formed"]
    tei = etree.parse(str(step5_dirs["tei_dir"] / "synthetic1.xml"))
    assert tei_all.validate(tei), tei_all.error_log
