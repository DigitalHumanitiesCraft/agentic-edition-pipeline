"""Runnable checks for step 6: every unpublishable TEI is a reported failure.

The frontend build skipped unparseable files and still exited 0, so a
missing object in the catalog looked like a clean run. Failures now carry
their cause into results/frontend/errors.json, never into docs/.
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
    monkeypatch.setattr(step6, "RESULTS_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(step6, "ERRORS_DIR", tmp_path / "frontend")
    monkeypatch.setattr(step6, "DOCS_DIR", docs)
    monkeypatch.setattr(step6, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step6, "project_info", lambda: {"title": "Projekt"})
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
    errors = json.loads(
        (tmp_path / "frontend" / "errors.json").read_text(encoding="utf-8")
    )["errors"]
    assert errors[0]["stage"] == "read"
    assert "XML parse error" in errors[0]["error"]
    assert not (tmp_path / "project" / "docs" / "data" / "errors.json").exists()


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
    docs = tmp_path / "project" / "docs"
    docs_tei = docs / "tei"
    tei.mkdir()
    docs_tei.mkdir(parents=True)
    (docs_tei / "stale.xml").write_text("stale download", encoding="utf-8")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", tei)
    monkeypatch.setattr(step6, "DOCS_DIR", docs)

    with pytest.raises(ValueError, match="No TEI files"):
        step6.build_all()

    assert not (docs_tei / "stale.xml").exists()


def test_build_rejects_casefold_collisions_before_publication(monkeypatch):
    class Candidates:
        def glob(self, _pattern):
            return [Path("Doc.xml"), Path("doc.xml")]

        def __str__(self):
            return "results/tei"

    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", Candidates())

    with pytest.raises(ValueError, match="case"):
        step6.build_all()


def test_download_copy_errors_are_reported_and_propagated(monkeypatch, tmp_path):
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

    write = step6.write_bytes_atomic

    def fail_tei_copy(path, content):
        if path.parent.name == "tei":
            raise OSError("publication copy failed")
        write(path, content)

    monkeypatch.setattr(step6, "write_bytes_atomic", fail_tei_copy)

    errors, total = step6.build_all()

    assert (errors, total) == (
        [
            {
                "object_id": "doc1",
                "error": "publication copy failed",
                "stage": "publish",
            }
        ],
        1,
    )
    assert not stale_asset.exists()
    assert not (data / "doc1.json").exists()


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

    assert '{key: "page_count", label: "Seiten"}' in script
    assert (
        'for (const key of ["signature", "date", "language", "page_count"])' in script
    )


def _attach(object_id, pages, expected):
    files = step6._facsimiles(object_id, pages, expected, step6.DOCS_DIR)
    step6._publish_images(object_id, files)


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
        _attach(
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

    _attach("doc1", pages, expected)

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

    _attach("doc1", pages, expected)

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

    _attach("doc1", pages, expected)

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
    monkeypatch.setattr(step6, "DOCS_DIR", docs)

    step6._remove_stale_assets(set())

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

    with pytest.raises(config.ItemFailure) as failure:
        step6.process_tei(tei_path)

    assert failure.value.stage == "contract"


def _make_directory_link(link, destination):
    if os.name == "nt":
        completed = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(link), str(destination)),
            capture_output=True,
            text=True,
            errors="replace",
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
            _attach("doc1", [], "")
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
    monkeypatch.setattr(step6, "DOCS_DIR", docs)

    try:
        with pytest.raises(ValueError, match="symlink or reparse point"):
            if operation == "cleanup":
                step6._remove_stale_assets(set())
            else:
                step6._write_if_changed(
                    step6.publication_dir("tei") / "doc1.xml", MINIMAL_TEI.encode()
                )
    finally:
        remove_link()

    assert protected.read_text(encoding="utf-8") == "external content"


def _report(tmp_path, object_id: str, state_hash: str) -> None:
    reports = tmp_path / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{object_id}_validation.json").write_text(
        json.dumps({"_meta": {"validation_state_hash": state_hash}}),
        encoding="utf-8",
    )


DERIVED_TEI = MINIMAL_TEI.replace(
    "</sourceDesc></fileDesc></teiHeader>",
    '</sourceDesc></fileDesc><revisionDesc><change when="2026-09-01T00:00:00+00:00">'
    "validation_state_hash=aaaaaaaaaaaa.</change></revisionDesc></teiHeader>",
)


def test_tei_left_behind_by_a_failed_regeneration_is_not_published(
    monkeypatch, tmp_path
):
    data, docs_tei = _prepare(monkeypatch, tmp_path, "doc1.xml", DERIVED_TEI)
    _report(tmp_path, "doc1", "bbbbbbbbbbbb")

    errors, _ = step6.build_all()

    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("doc1", "stale")
    ]
    assert not (data / "doc1.json").exists()
    assert not (docs_tei / "doc1.xml").exists()


def test_tei_matching_its_report_and_external_tei_are_published(monkeypatch, tmp_path):
    data, _ = _prepare(monkeypatch, tmp_path, "doc1.xml", DERIVED_TEI)
    (tmp_path / "tei" / "external.xml").write_text(MINIMAL_TEI, encoding="utf-8")
    _report(tmp_path, "doc1", "aaaaaaaaaaaa")

    errors, total = step6.build_all()

    assert (errors, total) == ([], 2)
    assert (data / "doc1.json").is_file()
    assert (data / "external.json").is_file()


def test_catalog_order_is_casefolded_and_stable(monkeypatch, tmp_path):
    data, _ = _prepare(monkeypatch, tmp_path, "beta.xml", MINIMAL_TEI)
    for name in ("Alpha.xml", "gamma.xml"):
        (tmp_path / "tei" / name).write_text(MINIMAL_TEI, encoding="utf-8")

    step6.build_all()
    first = (data / "catalog.json").read_bytes()
    step6.build_all()

    catalog = json.loads(first)
    assert [entry["id"] for entry in catalog["objects"]] == ["Alpha", "beta", "gamma"]
    assert "source_hash" not in catalog
    assert (data / "catalog.json").read_bytes() == first


def test_preview_server_binds_only_the_loopback_interface(monkeypatch):
    bound = []

    class FakeServer:
        def __init__(self, address, _handler):
            bound.append(address)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(step6.http.server, "HTTPServer", FakeServer)

    step6.serve(8123)

    assert bound == [("127.0.0.1", 8123)]
