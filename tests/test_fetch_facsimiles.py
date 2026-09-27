"""Checks for the remote-facsimile entry point and its three URL sources."""

import hashlib
import sys
from io import BytesIO

import pytest
import requests
from PIL import Image

import fetch_facsimiles as fetch
from conftest import (
    FakeResponse,
    forbid,
    install_session,
    read_json,
    write_image_manifest,
    write_json,
)

P1 = "https://example.org/p1.png"


def _image_bytes(image_format="PNG", size=(1, 1)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color="white").save(buffer, format=image_format)
    return buffer.getvalue()


PNG = _image_bytes()
JPEG = _image_bytes("JPEG")


def _image_response(content=PNG, content_type="image/png"):
    return FakeResponse(content=content, headers={"content-type": content_type})


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr(fetch, "FETCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch, "FETCH_BACKOFF_SECONDS", 0)


@pytest.fixture
def image_root(monkeypatch, tmp_path):
    root = tmp_path / "images"
    monkeypatch.setattr(fetch, "IMAGES_DIR", root)
    return root


def _existing_page(image_root, name, content, **manifest_page):
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True, exist_ok=True)
    image = object_dir / name
    image.write_bytes(content)
    if manifest_page:
        write_image_manifest(object_dir, [{"filename": name, **manifest_page}])
    return image


# URL sources


def test_inventory_exposes_remote_facsimiles_before_transcription(tmp_path):
    inventory = write_json(
        tmp_path / "inventory.json",
        {
            "documents": [
                {
                    "id": "doc1",
                    "metadata": {
                        "image_urls": {
                            "2": "https://example.org/p2.jpg",
                            "1": "https://example.org/p1.jpg",
                        },
                    },
                },
                {"id": "local", "metadata": {}},
            ],
        },
    )

    assert fetch.objects_from_inventory(inventory) == [
        (
            "doc1",
            [(1, "https://example.org/p1.jpg"), (2, "https://example.org/p2.jpg")],
        ),
    ]


def test_urls_from_tei_bind_graphics_to_page_breaks(tmp_path):
    tei = tmp_path / "doc1.xml"
    tei.write_text(
        """<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <facsimile>
    <graphic xml:id="f2" url="https://example.org/p2.jpg"/>
    <graphic xml:id="f1" url="https://example.org/p1.jpg"/>
    <graphic xml:id="local" url="images/p3.jpg"/>
    <graphic url="https://example.org/unbound.jpg"/>
  </facsimile>
  <text><body><pb n="1" facs="#f1"/><pb n="2" facs="#f2"/></body></text>
</TEI>""",
        encoding="utf-8",
    )

    assert fetch.urls_from_tei(tei) == [
        (2, "https://example.org/p2.jpg"),
        (1, "https://example.org/p1.jpg"),
        (4, "https://example.org/unbound.jpg"),
    ]


def test_urls_from_tei_refuses_external_entities(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("https://example.org/leak.jpg", encoding="utf-8")
    tei = tmp_path / "doc1.xml"
    tei.write_text(
        f"""<!DOCTYPE TEI [<!ENTITY leak SYSTEM "{secret.as_uri()}">]>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <facsimile><graphic url="&leak;"/></facsimile>
</TEI>""",
        encoding="utf-8",
    )

    with pytest.raises(fetch.etree.XMLSyntaxError, match="external entity"):
        fetch.urls_from_tei(tei)


@pytest.mark.parametrize(
    "image_urls",
    [
        {"2": "https://example.org/p2.jpg", "1": "https://example.org/p1.jpg"},
        ["https://example.org/p1.jpg", "https://example.org/p2.jpg"],
    ],
    ids=["mapping", "list"],
)
def test_urls_from_transcription_read_both_declaration_forms(tmp_path, image_urls):
    path = write_json(
        tmp_path / "doc1.json",
        {"object_id": "doc1", "metadata": {"image_urls": image_urls}},
    )

    assert fetch.urls_from_transcription(path) == [
        (1, "https://example.org/p1.jpg"),
        (2, "https://example.org/p2.jpg"),
    ]


# Materialization of one object


def test_existing_page_is_skipped_before_any_http_request(monkeypatch, image_root):
    _existing_page(
        image_root, "doc1_p001.png", PNG, image_url="https://example.org/p1.jpg"
    )
    session = install_session(monkeypatch)

    errors = fetch.fetch_object("doc1", [(1, "https://example.org/p1.jpg")], False)

    assert errors == []
    assert session.calls == []
    manifest = read_json(image_root / "doc1" / "manifest.json")
    assert manifest["pages"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()


def test_changed_remote_url_refetches_instead_of_misattributing_old_bytes(
    monkeypatch, image_root
):
    old = _existing_page(
        image_root, "doc1_p001.jpg", JPEG, image_url="https://example.org/old.jpg"
    )
    install_session(monkeypatch, _image_response())

    errors = fetch.fetch_object("doc1", [(1, P1)], force=False)

    assert errors == []
    assert not old.exists()
    manifest = read_json(image_root / "doc1" / "manifest.json")
    assert manifest["pages"][0]["image_url"] == P1
    assert manifest["pages"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()


def test_corrupt_existing_page_is_refetched_and_replaced(monkeypatch, image_root):
    corrupt = _existing_page(image_root, "doc1_p001.jpg", b"not an image")
    install_session(monkeypatch, _image_response())

    errors = fetch.fetch_object("doc1", [(1, P1)], force=False)

    assert errors == []
    assert not corrupt.exists()
    assert (image_root / "doc1" / "doc1_p001.png").read_bytes() == PNG


def test_force_fetch_removes_old_suffix_and_orphaned_pages(monkeypatch, image_root):
    for name in ("doc1_p001.jpg", "doc1_p002.jpg", "doc1_p003.jpg"):
        _existing_page(image_root, name, JPEG)
    install_session(monkeypatch, _image_response())

    errors = fetch.fetch_object(
        "doc1", [(1, P1), (2, "https://example.org/p2.png")], force=True
    )

    assert errors == []
    assert sorted(path.name for path in (image_root / "doc1").glob("doc1_p*.*")) == [
        "doc1_p001.png",
        "doc1_p002.png",
    ]
    manifest = read_json(image_root / "doc1" / "manifest.json")
    assert [page["page"] for page in manifest["pages"]] == [1, 2]


def test_nonobject_existing_manifest_is_treated_as_missing(monkeypatch, image_root):
    (image_root / "doc1").mkdir(parents=True)
    (image_root / "doc1" / "manifest.json").write_text("[]", encoding="utf-8")
    install_session(monkeypatch, _image_response())

    assert fetch.fetch_object("doc1", [(1, P1)], force=False) == []


def test_unsafe_object_id_is_rejected_before_network_or_filesystem_use(
    monkeypatch, tmp_path, image_root
):
    monkeypatch.setattr(
        requests, "Session", forbid("network session must not be created")
    )

    errors = fetch.fetch_object("../outside", [(1, P1)], force=True)

    assert errors[0]["stage"] == "contract"
    assert not (tmp_path / "outside").exists()


def test_transient_remote_failure_is_retried(monkeypatch, image_root):
    session = install_session(
        monkeypatch,
        FakeResponse(status_code=429, headers={"retry-after": "0"}),
        _image_response(),
    )

    errors = fetch.fetch_object("doc1", [(1, P1)], force=True)

    assert errors == []
    assert session.calls == [P1, P1]


def test_permanent_http_error_is_not_retried(monkeypatch, image_root):
    session = install_session(monkeypatch, FakeResponse(status_code=404))

    errors = fetch.fetch_object("doc1", [(1, P1)], force=True)

    assert errors[0]["stage"] == "fetch"
    assert session.calls == [P1]


def test_decompression_bomb_becomes_a_page_error(monkeypatch, image_root):
    monkeypatch.setattr(fetch.Image, "MAX_IMAGE_PIXELS", 10)
    install_session(monkeypatch, _image_response(_image_bytes(size=(10, 10))))

    errors = fetch.fetch_object("doc1", [(1, P1)], True)

    assert errors[0]["stage"] == "fetch"
    assert "not a valid supported image" in errors[0]["error"]


def test_oversized_response_is_refused_while_streaming(monkeypatch, image_root):
    monkeypatch.setattr(fetch, "FETCH_MAX_BYTES", 10)
    install_session(monkeypatch, _image_response())

    errors = fetch.fetch_object("doc1", [(1, P1)], True)

    assert "exceeds the limit" in errors[0]["error"]
    assert not list((image_root / "doc1").glob("*.png"))


def test_declared_content_type_must_match_the_image_bytes(monkeypatch, image_root):
    install_session(monkeypatch, _image_response(PNG, "image/jpeg"))

    errors = fetch.fetch_object("doc1", [(1, P1)], True)

    assert "conflicts with content type" in errors[0]["error"]


# Command line


def _run_main(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["fetch_facsimiles.py", *arguments])
    fetch.main()


def test_main_materializes_every_inventory_object(
    monkeypatch, tmp_path, image_root, capsys
):
    inventory = write_json(
        tmp_path / "inventory.json",
        {
            "documents": [
                {"id": "doc1", "metadata": {"image_urls": {"1": P1}}},
                {
                    "id": "doc2",
                    "metadata": {"image_urls": ["https://example.org/q.png"]},
                },
            ]
        },
    )
    monkeypatch.setattr(fetch, "INVENTORY_PATH", inventory)
    session = install_session(monkeypatch, _image_response())

    _run_main(monkeypatch, "--all", "--from-manifest")

    assert session.calls == [P1, "https://example.org/q.png"]
    assert read_json(image_root / "errors.json")["errors"] == []
    for object_id in ("doc1", "doc2"):
        pages = read_json(image_root / object_id / "manifest.json")["pages"]
        assert pages[0]["filename"] == f"{object_id}_p001.png"
    assert "2 object(s)" in capsys.readouterr().out


def test_main_reads_urls_from_transcriptions(monkeypatch, tmp_path, image_root):
    transcriptions = tmp_path / "transcriptions"
    write_json(
        transcriptions / "doc1.json",
        {"object_id": "doc1", "metadata": {"image_urls": [P1]}},
    )
    write_json(transcriptions / "errors.json", {"errors": []})
    monkeypatch.setattr(fetch, "TRANSCRIPTIONS_DIR", transcriptions)
    install_session(monkeypatch, _image_response())

    _run_main(monkeypatch, "--object", "doc1", "--from-transcriptions")

    assert (image_root / "doc1" / "doc1_p001.png").read_bytes() == PNG


def test_main_without_inventory_points_to_step_two(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fetch, "INVENTORY_PATH", tmp_path / "absent.json")

    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, "--all", "--from-manifest")

    assert exc.value.code == 1
    assert "02_analyze.py" in capsys.readouterr().err


def test_inventory_fetch_rejects_casefold_collisions_before_writing(
    monkeypatch, tmp_path
):
    inventory = write_json(
        tmp_path / "inventory.json",
        {
            "documents": [
                {"id": object_id, "metadata": {"image_urls": {"1": P1}}}
                for object_id in ("Doc", "doc")
            ]
        },
    )
    monkeypatch.setattr(fetch, "INVENTORY_PATH", inventory)
    monkeypatch.setattr(
        fetch, "fetch_object", forbid("colliding IDs must block before materialization")
    )

    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, "--all", "--from-manifest")

    assert exc.value.code == 1


def test_unreadable_tei_source_is_recorded_not_raised(
    monkeypatch, tmp_path, image_root
):
    tei_dir = tmp_path / "tei"
    tei_dir.mkdir()
    (tei_dir / "broken.xml").write_text("<TEI><unclosed>", encoding="utf-8")
    monkeypatch.setattr(fetch, "RESULTS_TEI_DIR", tei_dir)

    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, "--all")

    assert exc.value.code == 1
    assert read_json(image_root / "errors.json")["errors"][0]["stage"] == "read"
