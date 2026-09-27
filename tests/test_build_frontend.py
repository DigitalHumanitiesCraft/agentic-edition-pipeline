"""Runnable checks for step 6: every unpublishable TEI is a reported failure.

The frontend build skipped unparseable files and still exited 0, so a
missing object in the catalog looked like a clean run. Failures now carry
their cause into results/frontend/errors.json, never into docs/.
"""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from conftest import (
    MINIMAL_TEI,
    REPOSITORY_ROOT,
    TEI_NS,
    CasefoldCollidingDir,
    forbid,
    minimal_tei,
    page_images,
    point_step6_at,
    read_json,
    render_frontend,
    write_json,
)

step6 = importlib.import_module("06_build_frontend")

DERIVED_TEI = minimal_tei(
    revision_desc='<revisionDesc><change when="2026-09-01T00:00:00+00:00">'
    "validation_state_hash=aaaaaaaaaaaa.</change></revisionDesc>"
)


@pytest.fixture
def site(monkeypatch, tmp_path):
    """Step 6 pointed at a repository-shaped tmp_path without local images."""
    point_step6_at(monkeypatch, tmp_path, {"title": "Projekt"})
    monkeypatch.setattr(sys, "argv", ["06_build_frontend.py"])
    paths = SimpleNamespace(
        root=tmp_path,
        tei=tmp_path / "results/tei",
        reports=tmp_path / "results/reports",
        errors=tmp_path / "results/frontend",
        docs=tmp_path / "docs",
        data=tmp_path / "docs/data",
        docs_tei=tmp_path / "docs/tei",
    )
    for directory in (paths.tei, paths.data):
        directory.mkdir(parents=True)
    return paths


def _tei(site, name: str, content: str = MINIMAL_TEI) -> Path:
    path = site.tei / name
    path.write_text(content, encoding="utf-8")
    return path


def _stale_download(site, name: str) -> Path:
    site.docs_tei.mkdir(exist_ok=True)
    path = site.docs_tei / name
    path.write_text("stale download", encoding="utf-8")
    return path


def _report(site, object_id: str, state_hash: str) -> None:
    write_json(
        site.reports / f"{object_id}_validation.json",
        {"_meta": {"validation_state_hash": state_hash}},
    )


def _attach(object_id, pages, expected):
    files = step6._facsimiles(object_id, pages, expected, step6.DOCS_DIR)
    step6._publish_images(object_id, files)


def _page(number=1, image=""):
    return {"page": number, "label": str(number), "text": "Text", "image": image}


def _state_hash(images):
    return config.source_image_state_hash(config.source_image_state(images))


# Build and exit status


def test_main_exits_nonzero_when_a_tei_file_cannot_be_parsed(site):
    _tei(site, "broken.xml", "<TEI><unclosed>")
    stale = _stale_download(site, "broken.xml")

    with pytest.raises(SystemExit) as exc:
        step6.main()

    assert exc.value.code == 1
    assert not stale.exists()
    errors = read_json(site.errors / "errors.json")["errors"]
    assert errors[0]["stage"] == "read"
    assert "XML parse error" in errors[0]["error"]
    assert not (site.data / "errors.json").exists()


def test_main_returns_cleanly_for_a_parseable_corpus(site):
    _tei(site, "doc1.xml")
    stale = _stale_download(site, "stale.xml")

    step6.main()

    catalog = read_json(site.data / "catalog.json")
    assert [o["id"] for o in catalog["objects"]] == ["doc1"]
    assert (site.docs_tei / "doc1.xml").read_text(encoding="utf-8") == MINIMAL_TEI
    assert not stale.exists()


def test_build_removes_all_downloads_when_no_tei_sources_exist(site):
    stale = _stale_download(site, "stale.xml")

    with pytest.raises(ValueError, match="No TEI files"):
        step6.build_all()

    assert not stale.exists()


def test_build_rejects_casefold_collisions_before_publication(monkeypatch, site):
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", CasefoldCollidingDir(".xml"))

    with pytest.raises(ValueError, match="case"):
        step6.build_all()

    assert not (site.data / "catalog.json").exists()


def test_download_copy_errors_are_reported_and_propagated(monkeypatch, site):
    _tei(site, "doc1.xml")
    write_json(
        site.data / "doc1.json",
        {
            "id": "doc1",
            "title": "t",
            "date": "",
            "language": "",
            "pages": [],
            "has_images": False,
        },
    )
    stale_asset = _stale_download(site, "doc1.xml")
    write = step6.write_bytes_atomic

    def fail_tei_copy(path, content):
        if path.parent.name == "tei":
            raise OSError("publication copy failed")
        write(path, content)

    monkeypatch.setattr(step6, "write_bytes_atomic", fail_tei_copy)

    errors, total = step6.build_all()

    assert (errors, total) == (
        [{"object_id": "doc1", "error": "publication copy failed", "stage": "publish"}],
        1,
    )
    assert not stale_asset.exists()
    assert not (site.data / "doc1.json").exists()


def test_tei_left_behind_by_a_failed_regeneration_is_not_published(site):
    _tei(site, "doc1.xml", DERIVED_TEI)
    _report(site, "doc1", "bbbbbbbbbbbb")

    errors, _ = step6.build_all()

    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("doc1", "stale")
    ]
    assert not (site.data / "doc1.json").exists()
    assert not (site.docs_tei / "doc1.xml").exists()


def test_tei_matching_its_report_and_external_tei_are_published(site):
    _tei(site, "doc1.xml", DERIVED_TEI)
    _tei(site, "external.xml")
    _report(site, "doc1", "aaaaaaaaaaaa")

    errors, total = step6.build_all()

    assert (errors, total) == ([], 2)
    assert (site.data / "doc1.json").is_file()
    assert (site.data / "external.json").is_file()


def test_catalog_order_is_casefolded_and_stable(site):
    for name in ("beta.xml", "Alpha.xml", "gamma.xml"):
        _tei(site, name)

    step6.build_all()
    first = (site.data / "catalog.json").read_bytes()
    step6.build_all()

    catalog = read_json(site.data / "catalog.json")
    assert [entry["id"] for entry in catalog["objects"]] == ["Alpha", "beta", "gamma"]
    assert "source_hash" not in catalog
    assert (site.data / "catalog.json").read_bytes() == first


def test_catalog_page_count_reaches_the_frontend_table(site):
    _tei(site, "one.xml")
    _tei(site, "two.xml", minimal_tei('<pb n="1"/><p>First</p><pb n="2"/>'))

    assert step6.build_all()[0] == []

    counts = {
        entry["id"]: entry["page_count"]
        for entry in read_json(site.data / "catalog.json")["objects"]
    }
    shown = render_frontend(REPOSITORY_ROOT / "docs/js/app.js", site.docs)
    column = shown["headers"].index("Seiten")
    assert sorted(row[column] for row in shown["rows"]) == sorted(
        str(count) for count in counts.values()
    )
    assert sorted(counts.values()) == [1, 2]


# Page extraction


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

    assert step6.extract_pages(root) == [
        {"page": 1, "label": "1", "text": "Whole text", "image": ""}
    ]


# Facsimiles


def test_frontend_blocks_facsimile_bytes_that_differ_from_tei_provenance(
    monkeypatch, site
):
    image = page_images(site.root / "sources", 1, "doc1_p{page:03d}.png")[0]
    expected = _state_hash([image])
    image.write_bytes(b"changed")
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [image])

    with pytest.raises(ValueError, match="differ from the transcription"):
        _attach("doc1", [_page()], expected)


def test_frontend_uses_verified_committed_images_when_sources_are_absent(site):
    image = page_images(site.docs / "images/doc1", 1, "doc1_p{page:03d}.png")[0]
    pages = [_page(image="remote")]

    _attach("doc1", pages, _state_hash([image]))

    assert pages[0]["image"] == "images/doc1/doc1_p001.png"


def test_frontend_replaces_newer_corrupt_publication_copy_atomically(monkeypatch, site):
    source = page_images(site.root / "sources", 1, "doc1_p{page:03d}.png")[0]
    target = site.docs / "images/doc1" / source.name
    target.parent.mkdir(parents=True)
    target.write_bytes(b"newer corrupt copy")
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: [source])

    _attach("doc1", [_page()], _state_hash([source]))

    assert target.read_bytes() == source.read_bytes()


def test_frontend_removes_stale_pages_from_a_published_object(monkeypatch, site):
    current = page_images(site.root / "sources", 2, "doc1_p{page:03d}.png")
    stale = site.docs / "images/doc1/doc1_p003.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"withdrawn page")
    monkeypatch.setattr(step6, "ordered_page_images", lambda _id: current)

    _attach("doc1", [_page(1), _page(2)], _state_hash(current))

    assert not stale.exists()


def test_withdrawn_object_removes_all_publication_assets(site):
    images = site.docs / "images/withdrawn"
    images.mkdir(parents=True)
    site.docs_tei.mkdir()
    (site.data / "withdrawn.json").write_text("{}", encoding="utf-8")
    (site.docs_tei / "withdrawn.xml").write_text("<TEI/>", encoding="utf-8")
    (images / "page1.png").write_bytes(b"image")

    step6._remove_stale_assets(set())

    assert not (site.data / "withdrawn.json").exists()
    assert not (site.docs_tei / "withdrawn.xml").exists()
    assert not images.exists()


def test_frontend_rejects_unsafe_tei_filename_before_image_resolution(
    monkeypatch, site
):
    tei_path = _tei(site, "...xml")
    monkeypatch.setattr(
        step6, "ordered_page_images", forbid("image resolution reached")
    )

    with pytest.raises(config.ItemFailure) as failure:
        step6.process_tei(tei_path)

    assert failure.value.stage == "contract"


# Linked publication directories


def test_current_facsimile_directory_rejects_links(site, directory_link):
    external = site.root / "external"
    external.mkdir()
    (site.docs / "images").mkdir()
    directory_link(site.docs / "images/doc1", external)

    with pytest.raises(ValueError, match="symlink or reparse point"):
        _attach("doc1", [], "")


@pytest.mark.parametrize("operation", ["cleanup", "copy"])
def test_tei_publication_rejects_linked_directory_without_touching_external_files(
    site, directory_link, operation
):
    external = site.root / "external"
    external.mkdir()
    protected = external / "doc1.xml"
    protected.write_text("external content", encoding="utf-8")
    directory_link(site.docs_tei, external)

    with pytest.raises(ValueError, match="symlink or reparse point"):
        if operation == "cleanup":
            step6._remove_stale_assets(set())
        else:
            step6._write_if_changed(
                step6.publication_dir("tei") / "doc1.xml", MINIMAL_TEI.encode()
            )

    assert protected.read_text(encoding="utf-8") == "external content"


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
