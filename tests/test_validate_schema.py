"""Runnable checks for the schema validation runner (ADR-005).

Covers: the per-fork validation target in config, per-file valid/invalid
reporting, and the clear failure when the configured schema file is absent.
"""
from pathlib import Path

import pytest

from conftest import load_step

config = load_step("config")
vs = load_step("validate_schema")

MINI_RNG = """<grammar xmlns="http://relaxng.org/ns/structure/1.0">
  <start>
    <element name="doc">
      <oneOrMore><element name="p"><text/></element></oneOrMore>
    </element>
  </start>
</grammar>
"""


def test_default_target_comes_from_config():
    assert vs.default_schema() == config.VALIDATION_SCHEMA
    assert Path(config.VALIDATION_SCHEMA).parent == config.SCHEMAS_DIR


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
