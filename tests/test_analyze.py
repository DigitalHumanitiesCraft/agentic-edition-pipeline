"""Runnable checks for the inventory scan (step 2).

Facsimiles arrive as JPG from pipeline/fetch_facsimiles.py and as PNG from
the PDF extraction, so the inventory must count and label whatever image
type a document directory actually holds. The source manifest supplies the
catalogue fields that a filesystem scan cannot discover.
"""

import importlib
import sys
from types import SimpleNamespace

import pytest

from conftest import page_images, read_json, write_image_manifest, write_json

step2 = importlib.import_module("02_analyze")


@pytest.fixture
def data(monkeypatch, tmp_path):
    """Step 2 pointed at an empty data/ tree below tmp_path."""
    paths = SimpleNamespace(
        sources=tmp_path / "data/sources",
        processed=tmp_path / "data/processed",
        images=tmp_path / "data/processed/images",
        knowledge=tmp_path / "knowledge",
        inventory=tmp_path / "data/inventory.json",
    )
    paths.sources.mkdir(parents=True)
    monkeypatch.setattr(step2, "SOURCES_DIR", paths.sources)
    monkeypatch.setattr(step2, "PROCESSED_DIR", paths.processed)
    monkeypatch.setattr(step2, "IMAGES_DIR", paths.images)
    monkeypatch.setattr(step2, "KNOWLEDGE_DIR", paths.knowledge)
    monkeypatch.setattr(step2, "INVENTORY_PATH", paths.inventory)
    return paths


def _pages(directory, suffix, count):
    return page_images(directory, count, f"{directory.name}_p{{page:03d}}{suffix}")


def _source_manifest(data, documents, version="0.1"):
    write_json(
        data.sources / "manifest.json", {"version": version, "documents": documents}
    )


@pytest.mark.parametrize(("suffix", "label"), [(".jpg", "jpg"), (".png", "png")])
def test_extracted_pages_are_counted_and_labelled_by_their_type(data, suffix, label):
    _pages(data.images / "doc1", suffix, 3)

    documents = step2.scan_extracted_images({})

    assert documents["doc1"]["pages"] == 3
    assert documents["doc1"]["format"] == label
    assert documents["doc1"]["files"] == [f"doc1_p00{n}{suffix}" for n in (1, 2, 3)]


def test_existing_document_gets_the_extracted_page_count(data):
    _pages(data.images / "doc3", ".jpeg", 4)

    documents = step2.scan_extracted_images({"doc3": {"id": "doc3", "pages": 1}})

    assert documents["doc3"]["materialized_pages"] == 4


def test_extracted_manifest_hashes_are_verified(data):
    _pages(data.images / "doc1", ".png", 1)
    write_image_manifest(
        data.images / "doc1", [{"filename": "doc1_p001.png", "sha256": "0" * 64}]
    )

    with pytest.raises(ValueError, match="changed after creation"):
        step2.scan_extracted_images({})


def test_processed_image_ids_must_be_casefold_unique(data):
    _pages(data.images / "doc", ".png", 1)

    with pytest.raises(ValueError, match="collide across filesystems"):
        step2.scan_extracted_images({"Doc": {"id": "Doc", "pages": 1}})


def test_source_manifest_adds_remote_pages_metadata_and_prompt_profile(data):
    _source_manifest(
        data,
        [
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
    )

    documents = step2.merge_source_manifest(step2.scan_sources())
    document = step2.build_inventory(documents)["documents"][0]

    assert document["id"] == "letter-1"
    assert document["source_type"] == "remote_images"
    assert document["pages"] == 2
    assert document["prompt_profile"] == "correspondence"
    assert document["metadata"]["image_urls"]["2"] == "https://example.org/2.jpg"


def test_source_manifest_is_not_counted_as_a_transcription(data):
    _source_manifest(data, [])

    assert step2.scan_sources() == {}


@pytest.mark.parametrize(
    ("version", "documents", "message"),
    [
        ("9.0", [], "version"),
        ("0.1", [{"id": "doc1", "pages": None}], "null pages"),
        (
            "0.1",
            [
                {
                    "id": "doc1",
                    "pages": [
                        {"page": 1, "image_url": "https://example.org/1.jpg"},
                        {"page": 2},
                    ],
                }
            ],
            "either all declare image_url",
        ),
        (
            "0.1",
            [{"id": "Doc", "pages": []}, {"id": "doc", "pages": []}],
            "collide across filesystems",
        ),
    ],
    ids=["version", "null-pages", "partial-urls", "casefold-collision"],
)
def test_source_manifest_rejects_incompatible_or_partial_records(
    data, version, documents, message
):
    _source_manifest(data, documents, version)

    with pytest.raises(ValueError, match=message):
        step2.merge_source_manifest({})


def test_filesystem_source_ids_are_validated_early(data):
    (data.sources / "text").mkdir()
    (data.sources / "text" / "bad id.txt").write_text("text", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid source document id"):
        step2.scan_sources()


def test_inventory_marks_sources_without_page_images(data):
    (data.sources / "text").mkdir()
    (data.sources / "text" / "notes.txt").write_text("text", encoding="utf-8")
    _pages(data.sources / "images" / "scan", ".png", 1)

    inventory = step2.build_inventory(step2.scan_sources())

    flags = {doc["id"]: doc["transcribable"] for doc in inventory["documents"]}
    assert flags == {"notes": False, "scan": True}
    table = step2.inventory_to_markdown(inventory)
    assert "| notes | text | 1 | txt |" in table
    assert table.count("| no, no page images |") == 1


def test_analyze_counts_json_pages_from_pages_array(data, fixture_transcription):
    write_json(data.sources / "text" / "fixture1.json", fixture_transcription)

    documents = step2.scan_sources()

    assert documents["fixture1"]["source_type"] == "transcription"
    assert documents["fixture1"]["pages"] == 5


# Knowledge update and command line

DATA_DOCUMENT = "# Data\n\n<!-- INVENTAR_START -->\nold table\n<!-- INVENTAR_END -->\n\nNotes stay.\n"


def test_update_knowledge_replaces_only_the_marked_block(data):
    document = data.knowledge / "02_DATA.md"
    data.knowledge.mkdir()
    document.write_text(DATA_DOCUMENT, encoding="utf-8")

    step2.update_knowledge("| new | table |")

    assert document.read_text(encoding="utf-8") == DATA_DOCUMENT.replace(
        "old table", "| new | table |"
    )


@pytest.mark.parametrize("content", [None, "# Data without markers\n"])
def test_update_knowledge_leaves_documents_without_markers_alone(data, capsys, content):
    document = data.knowledge / "02_DATA.md"
    if content is not None:
        data.knowledge.mkdir()
        document.write_text(content, encoding="utf-8")

    step2.update_knowledge("| new | table |")

    assert "WARNING" in capsys.readouterr().out
    if content is None:
        assert not document.exists()
    else:
        assert document.read_text(encoding="utf-8") == content


def test_main_writes_the_inventory_and_the_knowledge_table(monkeypatch, data, capsys):
    _pages(data.sources / "images" / "scan", ".png", 2)
    data.knowledge.mkdir()
    (data.knowledge / "02_DATA.md").write_text(DATA_DOCUMENT, encoding="utf-8")
    monkeypatch.setattr(step2, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["02_analyze.py", "--update-knowledge", "--format", "markdown"],
    )

    step2.main()

    inventory = read_json(data.inventory)
    assert [(doc["id"], doc["pages"]) for doc in inventory["documents"]] == [
        ("scan", 2)
    ]
    table = step2.inventory_to_markdown(inventory)
    assert table in (data.knowledge / "02_DATA.md").read_text(encoding="utf-8")
    assert table in capsys.readouterr().out


def test_main_exits_nonzero_on_an_unusable_source_tree(monkeypatch, data, capsys):
    _source_manifest(data, [], version="9.0")
    monkeypatch.setattr(step2, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", ["02_analyze.py"])

    with pytest.raises(SystemExit) as exc:
        step2.main()

    assert exc.value.code == 1
    assert "version" in capsys.readouterr().err
    assert not data.inventory.exists()
