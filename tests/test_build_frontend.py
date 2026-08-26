"""Runnable checks for step 6: a TEI file that cannot be parsed is a failure.

The frontend build skipped unparseable files and still exited 0, so a
missing object in the catalog looked like a clean run.
"""
import json
import os
import subprocess
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
    project = tmp_path / "project"
    docs = project / "docs"
    data = docs / "data"
    docs_tei = docs / "tei"
    tei.mkdir()
    data.mkdir(parents=True)
    (tei / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", tei)
    monkeypatch.setattr(step6, "DOCS_DATA_DIR", data)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", docs_tei)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)
    monkeypatch.setattr(step6, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step6, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(step6, "resolve_image_dir", lambda _id: None)
    monkeypatch.setattr(sys, "argv", ["06_build_frontend.py"])
    return data, docs_tei


def test_main_exits_nonzero_when_a_tei_file_cannot_be_parsed(monkeypatch, tmp_path):
    _, docs_tei = _prepare(monkeypatch, tmp_path, "broken.xml", "<TEI><unclosed>")
    docs_tei.mkdir()
    (docs_tei / "broken.xml").write_text("stale download", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        step6.main()

    assert exc.value.code == 1
    assert not (docs_tei / "broken.xml").exists()


def test_main_returns_cleanly_for_a_parseable_corpus(monkeypatch, tmp_path):
    data, docs_tei = _prepare(monkeypatch, tmp_path, "doc1.xml", MINIMAL_TEI)
    docs_tei.mkdir()
    (docs_tei / "stale.xml").write_text("stale download", encoding="utf-8")

    step6.main()

    catalog = json.loads((data / "catalog.json").read_text(encoding="utf-8"))
    assert [o["id"] for o in catalog["objects"]] == ["doc1"]
    assert (docs_tei / "doc1.xml").read_text(encoding="utf-8") == MINIMAL_TEI
    assert not (docs_tei / "stale.xml").exists()


def test_build_removes_all_downloads_when_no_tei_sources_exist(
    monkeypatch, tmp_path
):
    tei = tmp_path / "tei"
    project = tmp_path / "project"
    docs = project / "docs"
    docs_tei = docs / "tei"
    tei.mkdir()
    docs_tei.mkdir(parents=True)
    (docs_tei / "stale.xml").write_text("stale download", encoding="utf-8")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", tei)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", docs_tei)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)

    with pytest.raises(SystemExit) as exc:
        step6.build_all(force=True)

    assert exc.value.code == 1
    assert not (docs_tei / "stale.xml").exists()


def test_download_copy_errors_are_reported_and_propagated(
    monkeypatch, tmp_path, capsys
):
    data, docs_tei = _prepare(monkeypatch, tmp_path, "doc1.xml", MINIMAL_TEI)
    (data / "doc1.json").write_text(
        json.dumps(
            {
                "id": "doc1",
                "title": "t",
                "date": "",
                "language": "",
                "pages": [],
                "has_images": False,
            }
        ),
        encoding="utf-8",
    )
    docs_tei.mkdir()
    stale_asset = docs_tei / "doc1.xml"
    stale_asset.write_text("stale download", encoding="utf-8")

    def fail_copy(_source, _destination):
        raise OSError("publication copy failed")

    monkeypatch.setattr(step6.shutil, "copyfileobj", fail_copy)

    with pytest.raises(OSError, match="publication copy failed"):
        step6.build_all(force=False)

    assert "TEI publication copy: publication copy failed" in capsys.readouterr().err
    assert stale_asset.read_text(encoding="utf-8") == "stale download"
    assert not list(docs_tei.glob(".*.tmp"))


def _make_directory_link(link, destination):
    if os.name == "nt":
        completed = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(link), str(destination)),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"Windows junction unavailable: {completed.stderr}")
        return lambda: link.rmdir()

    link.symlink_to(destination, target_is_directory=True)
    return lambda: link.unlink()


@pytest.mark.parametrize("operation", ["cleanup", "copy"])
def test_tei_publication_rejects_linked_directory_without_touching_external_files(
    monkeypatch, tmp_path, operation
):
    project = tmp_path / "project"
    docs = project / "docs"
    external = tmp_path / "external"
    docs.mkdir(parents=True)
    external.mkdir()
    protected = external / "doc1.xml"
    protected.write_text("external content", encoding="utf-8")
    publication_link = docs / "tei"
    remove_link = _make_directory_link(publication_link, external)
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", publication_link)

    try:
        with pytest.raises(ValueError, match="symlink or reparse point"):
            if operation == "cleanup":
                step6._remove_stale_tei_assets(set())
            else:
                source_dir = tmp_path / "source"
                source_dir.mkdir()
                source = source_dir / "doc1.xml"
                source.write_text(MINIMAL_TEI, encoding="utf-8")
                step6._copy_tei_asset(source)
    finally:
        remove_link()

    assert protected.read_text(encoding="utf-8") == "external content"


def test_tei_copy_rejects_legacy_temporary_junction_without_touching_external_files(
    monkeypatch, tmp_path
):
    project = tmp_path / "project"
    docs = project / "docs"
    publication_dir = docs / "tei"
    external = tmp_path / "external"
    publication_dir.mkdir(parents=True)
    external.mkdir()
    protected = external / "keep.xml"
    protected.write_text("external content", encoding="utf-8")
    legacy_temporary = publication_dir / "doc1.xml.tmp"
    remove_link = _make_directory_link(legacy_temporary, external)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "doc1.xml"
    source.write_text(MINIMAL_TEI, encoding="utf-8")
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", publication_dir)

    try:
        with pytest.raises(ValueError, match="publication file through symlink"):
            step6._copy_tei_asset(source)
    finally:
        remove_link()

    assert protected.read_text(encoding="utf-8") == "external content"
    assert not (publication_dir / "doc1.xml").exists()
