"""Checks for shared atomic output and page-order boundaries."""

import json
from pathlib import Path

import pytest

from conftest import load_step

config = load_step("config")
step1 = load_step("01_extract_images")


def test_atomic_text_write_preserves_old_target_when_replace_fails(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_self, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        config.write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_manifest_error_page_blocks_image_discovery(monkeypatch, tmp_path):
    images = tmp_path / "images" / "doc1"
    images.mkdir(parents=True)
    (images / "doc1_p001.png").write_bytes(b"image")
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"page": 1, "filename": "doc1_p001.png"},
                    {"page": 2, "filename": "doc1_p002.png", "error": "render failed"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "IMAGES_DIR", tmp_path / "images")

    with pytest.raises(ValueError, match="extraction error"):
        config.ordered_page_images("doc1", expected_pages=2)


def test_source_images_use_natural_page_order(tmp_path):
    directory = tmp_path / "doc1"
    directory.mkdir()
    for name in ("page10.png", "page2.png", "page1.png"):
        (directory / name).write_bytes(name.encode())

    assert [path.name for path in config.list_page_images(directory)] == [
        "page1.png",
        "page2.png",
        "page10.png",
    ]


def test_source_image_discovery_is_case_insensitive(tmp_path):
    directory = tmp_path / "doc1"
    directory.mkdir()
    (directory / "PAGE001.JPG").write_bytes(b"jpg")
    (directory / "PAGE002.TIFF").write_bytes(b"tiff")

    assert [path.name for path in config.list_page_images(directory)] == [
        "PAGE001.JPG",
        "PAGE002.TIFF",
    ]


def test_manifest_hash_blocks_changed_facsimile(monkeypatch, tmp_path):
    images = tmp_path / "images" / "doc1"
    images.mkdir(parents=True)
    image = images / "doc1_p001.png"
    image.write_bytes(b"original")
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "filename": image.name,
                        "sha256": step1._file_hash(image),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "IMAGES_DIR", tmp_path / "images")
    image.write_bytes(b"changed")

    with pytest.raises(ValueError, match="changed after creation"):
        config.ordered_page_images("doc1")


def test_materialized_remote_url_must_match_inventory(monkeypatch, tmp_path):
    images = tmp_path / "images" / "doc1"
    images.mkdir(parents=True)
    image = images / "doc1_p001.png"
    image.write_bytes(b"image")
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page": 1,
                        "filename": image.name,
                        "image_url": "https://example.org/a.png",
                        "sha256": step1._file_hash(image),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "IMAGES_DIR", tmp_path / "images")

    with pytest.raises(ValueError, match="differs from the inventory"):
        config.ordered_page_images(
            "doc1",
            expected_urls=["https://example.org/b.png"],
        )


def test_empty_output_directory_is_not_a_complete_pdf_extraction(tmp_path):
    pdf = tmp_path / "doc1.pdf"
    pdf.write_bytes(b"pdf-state")
    output = tmp_path / "doc1"
    output.mkdir()

    assert step1._complete_existing_extraction(output, pdf, 300) is False


def test_complete_pdf_extraction_requires_matching_source_hash(tmp_path):
    pdf = tmp_path / "doc1.pdf"
    pdf.write_bytes(b"first-state")
    output = tmp_path / "doc1"
    output.mkdir()
    image = output / "doc1_p001.png"
    image.write_bytes(b"image")
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "source_pdf": "doc1.pdf",
                "source_sha256": step1._file_hash(pdf),
                "dpi": 300,
                "pages": [
                    {
                        "page": 1,
                        "filename": image.name,
                        "sha256": step1._file_hash(image),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert step1._complete_existing_extraction(output, pdf, 300) is True
    pdf.write_bytes(b"second-state")
    assert step1._complete_existing_extraction(output, pdf, 300) is False


def test_pdf_collection_rejects_casefold_collisions(monkeypatch):
    class Sources:
        def glob(self, _pattern):
            return [Path("Doc.pdf"), Path("doc.pdf")]

        def __str__(self):
            return "sources/pdf"

    monkeypatch.setattr(step1, "PDF_DIR", Sources())

    with pytest.raises(SystemExit) as exc:
        step1.collect_pdfs(None, True)

    assert exc.value.code == 1
