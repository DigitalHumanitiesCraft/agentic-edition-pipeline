"""Checks for the pre-transcription remote-facsimile entry point."""

import json
import sys
from io import BytesIO

import pytest
from PIL import Image

from conftest import load_step

fetch = load_step("fetch_facsimiles")


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


class _Response:
    def __init__(self, content, content_type="image/png"):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
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
    import hashlib

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
    import hashlib

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
    monkeypatch.setattr(fetch, "FETCH_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetch, "FETCH_BACKOFF_SECONDS", 0)

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
    monkeypatch.setattr(fetch, "FETCH_DELAY_SECONDS", 0)

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
