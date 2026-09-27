"""Runnable checks for the schema validation runner (ADR-005).

Covers: the per-fork validation target in config, per-file valid/invalid
reporting, the clear failure when the configured schema file is absent, and
the offline path from a transcription file through steps 4 and 5 to TEI that
validates against the shipped default schema.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import load_step

config = load_step("config")
vs = load_step("validate_schema")
step4 = load_step("04_validate")
step5 = load_step("05_annotate_tei")

FIXTURES = Path(__file__).parent / "fixtures" / "evaluation"

MINI_RNG = """<grammar xmlns="http://relaxng.org/ns/structure/1.0">
  <start>
    <element name="doc">
      <oneOrMore><element name="p"><text/></element></oneOrMore>
    </element>
  </start>
</grammar>
"""


def test_default_target_comes_from_config():
    assert Path(config.VALIDATION_SCHEMA).parent == config.SCHEMAS_DIR
    assert Path(config.VALIDATION_SCHEMA).exists()


def test_compiled_schema_is_reused_until_the_file_changes(tmp_path):
    schema = tmp_path / "mini.rng"
    schema.write_text(MINI_RNG, encoding="utf-8")

    first = vs.load_schema(schema)
    assert vs.load_schema(schema) is first

    schema.write_text(MINI_RNG.replace('name="p"', 'name="q"'), encoding="utf-8")
    os.utime(schema, ns=(0, schema.stat().st_mtime_ns + 1_000_000_000))
    changed = vs.load_schema(schema)

    assert changed is not first
    doc = tmp_path / "doc.xml"
    doc.write_text("<doc><q>x</q></doc>", encoding="utf-8")
    assert vs.validate_files(schema, [doc])[0].valid


def test_invalid_schema_raises_value_error_naming_the_path(tmp_path):
    schema = tmp_path / "broken.rng"
    schema.write_text(
        "<grammar xmlns='http://relaxng.org/ns/structure/1.0'/>", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="broken"):
        vs.validate_files(schema, [])


def test_valid_and_invalid_files_are_reported(tmp_path):
    schema = tmp_path / "mini.rng"
    schema.write_text(MINI_RNG, encoding="utf-8")
    good = tmp_path / "good.xml"
    good.write_text("<doc><p>x</p></doc>", encoding="utf-8")
    bad = tmp_path / "bad.xml"
    bad.write_text("<doc><q/></doc>", encoding="utf-8")

    results = vs.validate_files(schema, [good, bad])
    by_name = {r.path.name: r for r in results}
    assert by_name["good.xml"].valid
    assert not by_name["bad.xml"].valid
    assert by_name["bad.xml"].errors


def test_missing_schema_fails_with_pointer(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        vs.validate_files(tmp_path / "absent.rng", [])
    assert "VALIDATION_SCHEMA" in str(exc.value)


def test_offline_path_produces_tei_valid_against_the_default_schema(tmp_path):
    """Fixture into data/processed/transcriptions/, then steps 4 and 5.

    This is the path a fork walks without any API key: a contract-conformant
    transcription file, deterministic validation, deterministic TEI. Its
    output has to validate against the schema the template ships as default.
    """
    dirs = {
        name: tmp_path / name
        for name in ("transcriptions", "validated", "results_tei", "reports")
    }
    for path in dirs.values():
        path.mkdir()
    shutil.copyfile(
        FIXTURES / "transcription.json", dirs["transcriptions"] / "synthetic1.json"
    )

    step4.validate_one(
        "synthetic1",
        None,
        force=True,
        transcriptions_dir=dirs["transcriptions"],
        validated_dir=dirs["validated"],
    )
    step5.annotate_one(
        "synthetic1",
        {},
        validate_only=False,
        force=True,
        validated_dir=dirs["validated"],
        tei_dir=dirs["results_tei"],
        reports_dir=dirs["reports"],
    )

    tei_path = dirs["results_tei"] / "synthetic1.xml"
    assert json.loads(
        (dirs["reports"] / "synthetic1_validation.json").read_text(encoding="utf-8")
    )["well_formed"]

    results = vs.validate_files(config.VALIDATION_SCHEMA, [tei_path])
    assert results[0].valid, results[0].errors
