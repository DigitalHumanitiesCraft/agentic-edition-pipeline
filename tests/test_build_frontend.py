"""Runnable checks for step 6: a TEI file that cannot be parsed is a failure.

The frontend build skipped unparseable files and still exited 0, so a
missing object in the catalog looked like a clean run.
"""
import json
import sys

import pytest

from conftest import load_step

step6 = load_step("06_build_frontend")

TEI_NS = "http://www.tei-c.org/ns/1.0"

MINIMAL_TEI = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<TEI xmlns="{TEI_NS}"><teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
    "<publicationStmt><publisher>p</publisher></publicationStmt>"
    "<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>"
    '<text><body><div><pb n="1"/><p>Text</p></div></body></text></TEI>'
)


def _prepare(monkeypatch, tmp_path, name: str, content: str):
    tei = tmp_path / "tei"
    data = tmp_path / "docs_data"
    tei.mkdir()
    data.mkdir()
    (tei / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", tei)
    monkeypatch.setattr(step6, "DOCS_DATA_DIR", data)
    monkeypatch.setattr(step6, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(step6, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step6, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(step6, "resolve_image_dir", lambda _id: None)
    monkeypatch.setattr(sys, "argv", ["06_build_frontend.py"])
    return data


def test_main_exits_nonzero_when_a_tei_file_cannot_be_parsed(monkeypatch, tmp_path):
    _prepare(monkeypatch, tmp_path, "broken.xml", "<TEI><unclosed>")

    with pytest.raises(SystemExit) as exc:
        step6.main()

    assert exc.value.code == 1


def test_main_returns_cleanly_for_a_parseable_corpus(monkeypatch, tmp_path):
    data = _prepare(monkeypatch, tmp_path, "doc1.xml", MINIMAL_TEI)

    step6.main()

    catalog = json.loads((data / "catalog.json").read_text(encoding="utf-8"))
    assert [o["id"] for o in catalog["objects"]] == ["doc1"]
