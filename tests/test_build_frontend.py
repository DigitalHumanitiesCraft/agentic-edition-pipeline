"""Runnable checks for step 6: a TEI file that cannot be parsed is a failure.

The frontend build skipped unparseable files and still exited 0, so a
missing object in the catalog looked like a clean run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import load_step

step6 = load_step("06_build_frontend")
config = load_step("config")

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
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [])
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


def test_build_removes_all_downloads_when_no_tei_sources_exist(monkeypatch, tmp_path):
    tei = tmp_path / "tei"
    project = tmp_path / "project"
    docs = project / "docs"
    docs_tei = docs / "tei"
    tei.mkdir()
    docs_tei.mkdir(parents=True)
    (docs_tei / "stale.xml").write_text("stale download", encoding="utf-8")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", tei)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", docs_tei)
    monkeypatch.setattr(step6, "DOCS_DATA_DIR", docs / "data")
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)

    with pytest.raises(SystemExit) as exc:
        step6.build_all(force=True)

    assert exc.value.code == 1
    assert not (docs_tei / "stale.xml").exists()


def test_build_rejects_casefold_collisions_before_publication(monkeypatch):
    class Candidates:
        def glob(self, _pattern):
            return [Path("Doc.xml"), Path("doc.xml")]

        def __str__(self):
            return "results/tei"

    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", Candidates())

    with pytest.raises(SystemExit) as exc:
        step6.build_all(force=True)

    assert exc.value.code == 1


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

    errors = step6.build_all(force=False)

    assert errors == [
        {
            "object_id": "doc1",
            "error": "publication copy failed",
            "stage": "publish",
        }
    ]
    assert "TEI download mirror: publication copy failed" in capsys.readouterr().err
    assert not stale_asset.exists()
    assert not list(docs_tei.glob(".*.tmp"))


def test_prefixed_tei_and_leaf_labels_are_extracted_in_document_order():
    xml = (
        f'<tei:TEI xmlns:tei="{TEI_NS}"><tei:text><tei:body><tei:div>'
        '<tei:pb n="1r"/><tei:p>Recto<tei:lb/>line</tei:p>'
        '<tei:pb n="1v"/><tei:p>Verso</tei:p>'
        "</tei:div></tei:body></tei:text></tei:TEI>"
    )
    root = step6.etree.fromstring(xml.encode())

    assert step6.extract_pages(root) == [
        {"page": 1, "label": "1r", "text": "Recto\nline", "image": ""},
        {"page": 2, "label": "1v", "text": "Verso", "image": ""},
    ]


def test_tei_without_page_break_becomes_one_viewer_page():
    root = step6.etree.fromstring(
        f'<TEI xmlns="{TEI_NS}"><text><body><p>Whole text</p></body></text></TEI>'.encode()
    )

    pages = step6.extract_pages(root)

    assert pages == [
        {
            "page": 1,
            "label": "1",
            "text": "Whole text",
            "image": "",
        }
    ]


def test_frontend_client_uses_the_catalog_page_count_contract():
    script = (step6.DOCS_DIR / "js" / "app.js").read_text(encoding="utf-8")

    assert '{ key: "page_count", label: "Seiten" }' in script
    assert "it.page_count != null ? it.page_count" in script


def test_frontend_blocks_facsimile_bytes_that_differ_from_tei_provenance(
    monkeypatch, tmp_path
):
    image = tmp_path / "doc1_p001.png"
    image.write_bytes(b"original")
    expected = config.source_image_state_hash(config.source_image_state([image]))
    image.write_bytes(b"changed")
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [image])
    monkeypatch.setattr(step6, "DOCS_DIR", tmp_path / "docs")

    with pytest.raises(ValueError, match="differ from the transcription"):
        step6._attach_images(
            "doc1",
            [{"page": 1, "label": "1", "text": "Text", "image": ""}],
            expected,
        )


def test_frontend_uses_verified_committed_images_when_sources_are_absent(
    monkeypatch, tmp_path
):
    docs = tmp_path / "docs"
    image_dir = docs / "images" / "doc1"
    image_dir.mkdir(parents=True)
    image = image_dir / "doc1_p001.png"
    image.write_bytes(b"committed publication image")
    expected = config.source_image_state_hash(config.source_image_state([image]))
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [])
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    pages = [{"page": 1, "label": "1", "text": "Text", "image": "remote"}]

    step6._attach_images("doc1", pages, expected)

    assert pages[0]["image"] == "images/doc1/doc1_p001.png"


def test_frontend_replaces_newer_corrupt_publication_copy_atomically(
    monkeypatch, tmp_path
):
    source = tmp_path / "source" / "doc1_p001.png"
    source.parent.mkdir()
    source.write_bytes(b"verified source")
    docs = tmp_path / "docs"
    target = docs / "images" / "doc1" / source.name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"newer corrupt copy")
    expected = config.source_image_state_hash(config.source_image_state([source]))
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [source])
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    pages = [{"page": 1, "label": "1", "text": "Text", "image": ""}]

    step6._attach_images("doc1", pages, expected)

    assert target.read_bytes() == b"verified source"


def test_frontend_removes_stale_pages_from_a_published_object(monkeypatch, tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    current = []
    for page in (1, 2):
        image = sources / f"doc1_p{page:03d}.png"
        image.write_bytes(f"page-{page}".encode())
        current.append(image)
    docs = tmp_path / "docs"
    publication_dir = docs / "images" / "doc1"
    publication_dir.mkdir(parents=True)
    stale = publication_dir / "doc1_p003.png"
    stale.write_bytes(b"withdrawn page")
    expected = config.source_image_state_hash(config.source_image_state(current))
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: current)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    pages = [
        {"page": page, "label": str(page), "text": "Text", "image": ""}
        for page in (1, 2)
    ]

    step6._attach_images("doc1", pages, expected)

    assert not stale.exists()


def test_withdrawn_object_removes_all_publication_assets(monkeypatch, tmp_path):
    project = tmp_path / "project"
    docs = project / "docs"
    data = docs / "data"
    tei = docs / "tei"
    images = docs / "images" / "withdrawn"
    for directory in (data, tei, images):
        directory.mkdir(parents=True, exist_ok=True)
    (data / "withdrawn.json").write_text("{}", encoding="utf-8")
    (tei / "withdrawn.xml").write_text("<TEI/>", encoding="utf-8")
    (images / "page1.png").write_bytes(b"image")
    monkeypatch.setattr(step6, "PROJECT_ROOT", project)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "DOCS_DATA_DIR", data)
    monkeypatch.setattr(step6, "DOCS_TEI_DIR", tei)

    step6._remove_stale_tei_assets(set())
    step6._remove_stale_frontend_assets(set())

    assert not (data / "withdrawn.json").exists()
    assert not (tei / "withdrawn.xml").exists()
    assert not images.exists()


def test_frontend_rejects_unsafe_tei_filename_before_image_resolution(
    monkeypatch, tmp_path
):
    tei_path = tmp_path / "...xml"
    tei_path.write_text(MINIMAL_TEI, encoding="utf-8")

    def should_not_run(_id):
        raise AssertionError("image resolution reached")

    monkeypatch.setattr(step6, "ordered_page_images", should_not_run)

    assert step6.process_tei(tei_path) is None


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


def test_current_facsimile_directory_rejects_links(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    image_root = docs / "images"
    external = tmp_path / "external"
    image_root.mkdir(parents=True)
    external.mkdir()
    link = image_root / "doc1"
    remove_link = _make_directory_link(link, external)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [])

    try:
        with pytest.raises(ValueError, match="symlink or reparse point"):
            step6._attach_images("doc1", [], "")
    finally:
        remove_link()


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
