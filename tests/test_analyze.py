"""Runnable checks for the inventory scan (step 2).

Facsimiles arrive as JPG from pipeline/fetch_facsimiles.py and as PNG from
the PDF extraction, so the inventory must count and label whatever image
type a document directory actually holds. The source manifest supplies the
catalogue fields that a filesystem scan cannot discover.
"""

import json

import pytest

from conftest import load_step

step2 = load_step("02_analyze")


def _make_pages(directory, suffix: str, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (directory / f"{directory.name}_p{i:03d}{suffix}").write_bytes(b"fake")


def test_extracted_jpg_pages_are_counted_and_labelled(monkeypatch, tmp_path):
    images = tmp_path / "images"
    _make_pages(images / "doc1", ".jpg", 3)
    monkeypatch.setattr(step2, "IMAGES_DIR", images)
    monkeypatch.setattr(step2, "PROCESSED_DIR", tmp_path)

    documents = step2.scan_extracted_images({})

    assert documents["doc1"]["pages"] == 3
    assert documents["doc1"]["format"] == "jpg"
    assert documents["doc1"]["files"] == [
        "doc1_p001.jpg",
        "doc1_p002.jpg",
        "doc1_p003.jpg",
    ]


def test_extracted_png_pages_keep_their_format(monkeypatch, tmp_path):
    images = tmp_path / "images"
    _make_pages(images / "doc2", ".png", 2)
    monkeypatch.setattr(step2, "IMAGES_DIR", images)
    monkeypatch.setattr(step2, "PROCESSED_DIR", tmp_path)

    documents = step2.scan_extracted_images({})

    assert documents["doc2"]["pages"] == 2
    assert documents["doc2"]["format"] == "png"


def test_existing_document_gets_the_extracted_page_count(monkeypatch, tmp_path):
    images = tmp_path / "images"
    _make_pages(images / "doc3", ".jpeg", 4)
    monkeypatch.setattr(step2, "IMAGES_DIR", images)
    monkeypatch.setattr(step2, "PROCESSED_DIR", tmp_path)

    documents = step2.scan_extracted_images({"doc3": {"id": "doc3", "pages": 1}})

    assert documents["doc3"]["materialized_pages"] == 4


def test_source_manifest_adds_remote_pages_metadata_and_prompt_profile(
    monkeypatch, tmp_path
):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "manifest.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "documents": [
                    {
                        "id": "letter-1",
                        "prompt_profile": "correspondence",
                        "metadata": {"title": "Letter", "language": "de"},
                        "pages": [
                            {"page": 1, "image_url": "https://example.org/1.jpg"},
                            {"page": 2, "image_url": "https://example.org/2.jpg"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    documents = step2.merge_source_manifest(step2.scan_sources())
    inventory = step2.build_inventory(documents)
    document = inventory["documents"][0]

    assert document["id"] == "letter-1"
    assert document["source_type"] == "remote_images"
    assert document["pages"] == 2
    assert document["prompt_profile"] == "correspondence"
    assert document["metadata"]["image_urls"]["2"] == "https://example.org/2.jpg"


def test_source_manifest_is_not_counted_as_a_transcription(monkeypatch, tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "manifest.json").write_text(
        json.dumps({"version": "0.1", "documents": []}), encoding="utf-8"
    )
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    assert step2.scan_sources() == {}


@pytest.mark.parametrize(
    "manifest",
    [
        {"version": "9.0", "documents": []},
        {"version": "0.1", "documents": [{"id": "doc1", "pages": None}]},
        {
            "version": "0.1",
            "documents": [
                {
                    "id": "doc1",
                    "pages": [
                        {"page": 1, "image_url": "https://example.org/1.jpg"},
                        {"page": 2},
                    ],
                }
            ],
        },
    ],
)
def test_source_manifest_rejects_incompatible_or_partial_records(
    monkeypatch, tmp_path, manifest
):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    with pytest.raises(ValueError):
        step2.merge_source_manifest({})


def test_filesystem_source_ids_are_validated_early(monkeypatch, tmp_path):
    sources = tmp_path / "sources"
    (sources / "text").mkdir(parents=True)
    (sources / "text" / "bad id.txt").write_text("text", encoding="utf-8")
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    with pytest.raises(ValueError, match="invalid source document id"):
        step2.scan_sources()


def test_manifest_ids_must_be_casefold_unique(monkeypatch, tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "manifest.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "documents": [
                    {"id": "Doc", "pages": []},
                    {"id": "doc", "pages": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    with pytest.raises(ValueError, match="collide across filesystems"):
        step2.merge_source_manifest({})
