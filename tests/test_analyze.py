"""Runnable checks for the inventory scan (step 2).

Facsimiles arrive as JPG from pipeline/fetch_facsimiles.py and as PNG from
the PDF extraction, so the inventory must count and label whatever image
type a document directory actually holds.
"""
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
        "doc1_p001.jpg", "doc1_p002.jpg", "doc1_p003.jpg",
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

    assert documents["doc3"]["extracted_pages"] == 4
