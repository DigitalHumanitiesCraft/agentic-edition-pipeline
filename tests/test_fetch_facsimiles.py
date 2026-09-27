"""Checks for the remote-facsimile entry point and its three URL sources."""

import hashlib
import json
import sys
from io import BytesIO

import pytest
from PIL import Image

from conftest import load_step

fetch = load_step("fetch_facsimiles")
config = load_step("config")


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    monkeypatch.setattr(fetch, "FETCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch, "FETCH_BACKOFF_SECONDS", 0)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


class _Response:
    status_code = 200

    def __init__(self, content, content_type="image/png"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self):
        return None


def _session_returning(content, content_type="image/png"):
    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return _Response(content, content_type)

    return Session


def test_inventory_exposes_remote_facsimiles_before_transcription(tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )

    assert fetch.objects_from_inventory(inventory) == [
        (
            "doc1",
            [
                (1, "https://example.org/p1.jpg"),
                (2, "https://example.org/p2.jpg"),
            ],
        ),
    ]


def test_existing_page_is_skipped_before_any_http_request(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True)
    image = object_dir / "doc1_p001.png"
    image.write_bytes(_png_bytes())
    (object_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "filename": image.name,
                        "image_url": "https://example.org/p1.jpg",
                        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)

    class NoNetworkSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            raise AssertionError("HTTP request should not run for an existing page")

    monkeypatch.setattr(fetch.requests, "Session", NoNetworkSession)

    errors = fetch.fetch_object(
        "doc1", [(1, "https://example.org/p1.jpg")], force=False
    )

    assert errors == []

    manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pages"][0]["sha256"]


def test_changed_remote_url_refetches_instead_of_misattributing_old_bytes(
    monkeypatch, tmp_path
):
    image_root = tmp_path / "images"
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True)
    image = object_dir / "doc1_p001.jpg"
    image.write_bytes(_jpeg_bytes())
    (object_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "filename": image.name,
                        "image_url": "https://example.org/old.jpg",
                        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)
    monkeypatch.setattr(fetch.requests, "Session", _session_returning(_png_bytes()))

    errors = fetch.fetch_object(
        "doc1", [(1, "https://example.org/new.png")], force=False
    )

    assert errors == []
    assert not image.exists()
    manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["pages"][0]["image_url"] == "https://example.org/new.png"
    assert manifest["pages"][0]["sha256"] == hashlib.sha256(_png_bytes()).hexdigest()


def test_corrupt_existing_page_is_refetched_and_replaced(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True)
    corrupt = object_dir / "doc1_p001.jpg"
    corrupt.write_bytes(b"not an image")
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)
    monkeypatch.setattr(fetch.requests, "Session", _session_returning(_png_bytes()))

    errors = fetch.fetch_object(
        "doc1", [(1, "https://example.org/p1.png")], force=False
    )

    assert errors == []
    assert not corrupt.exists()
    assert (object_dir / "doc1_p001.png").read_bytes() == _png_bytes()


def test_force_fetch_removes_old_suffix_and_orphaned_pages(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True)
    (object_dir / "doc1_p001.jpg").write_bytes(_jpeg_bytes())
    (object_dir / "doc1_p002.jpg").write_bytes(_jpeg_bytes())
    orphan = object_dir / "doc1_p003.jpg"
    orphan.write_bytes(_jpeg_bytes())
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)
    monkeypatch.setattr(fetch.requests, "Session", _session_returning(_png_bytes()))

    errors = fetch.fetch_object(
        "doc1",
        [
            (1, "https://example.org/p1.png"),
            (2, "https://example.org/p2.png"),
        ],
        force=True,
    )

    assert errors == []
    assert sorted(path.name for path in object_dir.glob("doc1_p*.*")) == [
        "doc1_p001.png",
        "doc1_p002.png",
    ]
    manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [page["page"] for page in manifest["pages"]] == [1, 2]


def test_unsafe_object_id_is_rejected_before_network_or_filesystem_use(
    monkeypatch, tmp_path
):
    image_root = tmp_path / "images"
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)

    class NoSession:
        def __init__(self):
            raise AssertionError("network session must not be created")

    monkeypatch.setattr(fetch.requests, "Session", NoSession)

    errors = fetch.fetch_object(
        "../outside", [(1, "https://example.org/p1.png")], force=True
    )

    assert errors[0]["stage"] == "contract"
    assert not (tmp_path / "outside").exists()


def test_transient_remote_failure_is_retried(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    calls = []

    class TransientResponse:
        def __init__(self):
            self.status_code = 429
            self.headers = {"retry-after": "0"}

        def raise_for_status(self):
            raise fetch.requests.HTTPError("rate limited")

        def close(self):
            return None

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                return TransientResponse()
            return _Response(_png_bytes())

    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)
    monkeypatch.setattr(fetch.requests, "Session", Session)

    errors = fetch.fetch_object("doc1", [(1, "https://example.org/p1.png")], force=True)

    assert errors == []
    assert len(calls) == 2


def test_nonobject_existing_manifest_is_treated_as_missing(monkeypatch, tmp_path):
    image_root = tmp_path / "images"
    object_dir = image_root / "doc1"
    object_dir.mkdir(parents=True)
    (object_dir / "manifest.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(fetch, "IMAGES_DIR", image_root)
    monkeypatch.setattr(fetch.requests, "Session", _session_returning(_png_bytes()))

    errors = fetch.fetch_object(
        "doc1", [(1, "https://example.org/p1.png")], force=False
    )

    assert errors == []


def test_inventory_fetch_rejects_casefold_collisions_before_writing(
    monkeypatch, tmp_path
):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "id": object_id,
                        "metadata": {"image_urls": {"1": "https://example.org/p1.png"}},
                    }
                    for object_id in ("Doc", "doc")
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fetch, "INVENTORY_PATH", inventory)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("colliding IDs must block before materialization")

    monkeypatch.setattr(fetch, "fetch_object", should_not_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_facsimiles.py", "--all", "--from-manifest"],
    )

    with pytest.raises(SystemExit) as exc:
        fetch.main()

    assert exc.value.code == 1


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
    path = tmp_path / "doc1.json"
    path.write_text(
        json.dumps({"object_id": "doc1", "metadata": {"image_urls": image_urls}}),
        encoding="utf-8",
    )

    assert fetch.urls_from_transcription(path) == [
        (1, "https://example.org/p1.jpg"),
        (2, "https://example.org/p2.jpg"),
    ]


def test_unreadable_tei_source_is_recorded_not_raised(monkeypatch, tmp_path, capsys):
    tei_dir = tmp_path / "tei"
    tei_dir.mkdir()
    (tei_dir / "broken.xml").write_text("<TEI><unclosed>", encoding="utf-8")
    monkeypatch.setattr(fetch, "RESULTS_TEI_DIR", tei_dir)
    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(sys, "argv", ["fetch_facsimiles.py", "--all"])

    with pytest.raises(SystemExit) as exc:
        fetch.main()

    assert exc.value.code == 1
    errors = json.loads((tmp_path / "images" / "errors.json").read_text("utf-8"))
    assert errors["errors"][0]["stage"] == "read"


def test_decompression_bomb_becomes_a_page_error(monkeypatch, tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buffer, format="PNG")
    monkeypatch.setattr(fetch.Image, "MAX_IMAGE_PIXELS", 10)
    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(
        fetch.requests, "Session", _session_returning(buffer.getvalue())
    )

    errors = fetch.fetch_object("doc1", [(1, "https://example.org/p1.png")], True)

    assert errors[0]["stage"] == "fetch"
    assert "not a valid supported image" in errors[0]["error"]


def test_oversized_response_is_refused_while_streaming(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch, "FETCH_MAX_BYTES", 10)
    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(fetch.requests, "Session", _session_returning(_png_bytes()))

    errors = fetch.fetch_object("doc1", [(1, "https://example.org/p1.png")], True)

    assert "exceeds the limit" in errors[0]["error"]
    assert not list((tmp_path / "images" / "doc1").glob("*.png"))


def test_permanent_http_error_is_not_retried(monkeypatch, tmp_path):
    calls = []

    class NotFound(_Response):
        status_code = 404

        def raise_for_status(self):
            raise fetch.requests.HTTPError("404 Not Found")

    class Session:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            calls.append(1)
            return NotFound(b"")

    monkeypatch.setattr(fetch, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(fetch.requests, "Session", Session)

    errors = fetch.fetch_object("doc1", [(1, "https://example.org/p1.png")], True)

    assert errors[0]["stage"] == "fetch"
    assert calls == [1]
