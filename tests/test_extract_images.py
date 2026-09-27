"""Runnable checks for step 1: PDF pages become hash-bound page images.

The PDFs are generated in memory with PyMuPDF, so the checks exercise real
rendering without a corpus file.
"""

import importlib
import sys

import fitz
import pytest
from PIL import Image

import config
from conftest import CasefoldCollidingDir, read_json

step1 = importlib.import_module("01_extract_images")


def _pdf(path, pages=2):
    with fitz.open() as document:
        for number in range(1, pages + 1):
            document.new_page(width=200, height=100).insert_text(
                (20, 50), f"Seite {number}"
            )
        document.save(path)
    return path


@pytest.fixture
def images_dir(monkeypatch, tmp_path):
    directory = tmp_path / "images"
    monkeypatch.setattr(step1, "IMAGES_DIR", directory)
    return directory


def test_extraction_writes_one_verified_png_per_page(tmp_path, images_dir):
    pdf = _pdf(tmp_path / "doc1.pdf")

    assert step1.extract_one(pdf, 72, force=False) is None

    manifest, images = config.read_image_manifest(images_dir / "doc1")
    assert [image.name for image in images] == ["doc1_p001.png", "doc1_p002.png"]
    assert all(image.read_bytes().startswith(b"\x89PNG") for image in images)
    assert (manifest["source_pdf"], manifest["dpi"]) == ("doc1.pdf", 72)
    assert manifest["source_sha256"] == config.file_sha256(pdf)
    assert manifest["_meta"]["pipeline_step"] == 1


def test_dpi_scales_the_rendered_page(tmp_path, images_dir):
    pdf = _pdf(tmp_path / "doc1.pdf", pages=1)

    step1.extract_one(pdf, 144, force=False)

    # The 200 x 100 pt page at 144 DPI is twice its 72-DPI pixel size.
    with Image.open(images_dir / "doc1" / "doc1_p001.png") as image:
        assert image.size == (400, 200)


def test_complete_extraction_is_kept_until_pdf_or_dpi_change(tmp_path, images_dir):
    pdf = _pdf(tmp_path / "doc1.pdf")
    step1.extract_one(pdf, 72, force=False)
    page = images_dir / "doc1" / "doc1_p001.png"
    before = page.stat()

    step1.extract_one(pdf, 72, force=False)
    after = page.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)

    step1.extract_one(pdf, 96, force=False)
    assert read_json(images_dir / "doc1" / "manifest.json")["dpi"] == 96


def test_shorter_reextraction_removes_pages_of_the_former_pdf(tmp_path, images_dir):
    pdf = _pdf(tmp_path / "doc1.pdf", pages=3)
    step1.extract_one(pdf, 72, force=False)
    _pdf(pdf, pages=1)

    assert step1.extract_one(pdf, 72, force=False) is None

    assert sorted(path.name for path in (images_dir / "doc1").glob("*.png")) == [
        "doc1_p001.png"
    ]


def test_unreadable_pdf_is_an_open_error(tmp_path, images_dir):
    pdf = tmp_path / "doc1.pdf"
    pdf.write_bytes(b"not a pdf")

    error = step1.extract_one(pdf, 72, force=True)

    assert (error["object_id"], error["stage"]) == ("doc1", "open")


def test_empty_output_directory_is_not_a_complete_pdf_extraction(tmp_path):
    pdf = tmp_path / "doc1.pdf"
    pdf.write_bytes(b"pdf-state")
    (tmp_path / "doc1").mkdir()

    assert step1._complete_existing_extraction(tmp_path / "doc1", pdf, 300) is False


def test_interrupted_extraction_closes_the_pdf(monkeypatch, tmp_path, images_dir):
    pdf = _pdf(tmp_path / "doc1.pdf", pages=1)

    def interrupt(_path, _content):
        raise KeyboardInterrupt

    monkeypatch.setattr(step1, "write_bytes_atomic", interrupt)
    opened = []
    real_open = step1.fitz.open

    def tracking_open(path):
        opened.append(real_open(path))
        return opened[-1]

    monkeypatch.setattr(step1.fitz, "open", tracking_open)

    with pytest.raises(KeyboardInterrupt):
        step1.extract_one(pdf, 72, force=True)

    assert opened[0].is_closed


# Selection and command line


def test_pdf_collection_rejects_casefold_collisions(monkeypatch):
    monkeypatch.setattr(step1, "PDF_DIR", CasefoldCollidingDir(".pdf"))

    with pytest.raises(SystemExit) as exc:
        step1.collect_pdfs(None, True, None)

    assert exc.value.code == 1


def test_pdf_collection_selects_by_object_id_and_sample(tmp_path, monkeypatch):
    for name in ("b", "a", "c"):
        (tmp_path / f"{name}.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(step1, "PDF_DIR", tmp_path)

    assert step1.collect_pdfs("c", False, None) == [tmp_path / "c.pdf"]
    assert step1.collect_pdfs(None, True, 2) == [tmp_path / "a.pdf", tmp_path / "b.pdf"]


def test_main_extracts_every_pdf_and_fails_on_a_broken_one(
    monkeypatch, tmp_path, images_dir
):
    pdfs = tmp_path / "pdf"
    pdfs.mkdir()
    _pdf(pdfs / "good.pdf", pages=1)
    (pdfs / "broken.pdf").write_bytes(b"not a pdf")
    monkeypatch.setattr(step1, "PDF_DIR", pdfs)
    monkeypatch.setattr(step1, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", ["01_extract_images.py", "--all", "--dpi", "72"])

    with pytest.raises(SystemExit) as exc:
        step1.main()

    assert exc.value.code == 1
    assert config.read_image_manifest(images_dir / "good")[1]
    errors = read_json(images_dir / "errors.json")["errors"]
    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("broken", "open")
    ]
