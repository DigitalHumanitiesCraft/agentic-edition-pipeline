"""Analyze source data and produce an inventory (step 2).

Flat script-pipeline regime. Walks data/sources/, merges the optional source
manifest data/sources/manifest.json and adds materialized page images from
data/processed/images/ to build data/inventory.json. The inventory is the
single source of truth for downstream steps, which read it to know what to
process rather than scanning the filesystem themselves.

Each document carries a transcribable flag. Only page images (PDF, image
folders, remote or extracted facsimiles) reach step 3. Text, XML, DOCX and
transcription-JSON sources are inventoried, but no supplied step converts
them, so step 3 leaves documents flagged false out of its selection.

Optionally updates knowledge/02_DATA.md with a human-readable summary between
INVENTAR_START / INVENTAR_END markers, so the knowledge document stays in sync.

Usage:
    uv run python pipeline/02_analyze.py [--update-knowledge] [--format markdown]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

import contract
from config import (
    IMAGES_DIR,
    INVENTORY_PATH,
    KNOWLEDGE_DIR,
    PROCESSED_DIR,
    SOURCES_DIR,
    configure_console,
    ensure_dirs,
    list_page_images,
    provenance_meta,
    read_image_manifest,
    read_json,
    write_json_atomic,
    write_text_atomic,
)

SOURCE_MANIFEST_NAME = "manifest.json"
# File extensions grouped by source type
EXT_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tif": "image",
    ".tiff": "image",
    ".txt": "text",
    ".xml": "xml",
    ".docx": "docx",
    ".json": "transcription",
}
# Source types whose pages step 3 can read as images once they are local.
IMAGE_SOURCE_TYPES = frozenset({"pdf", "image", "remote_images", "extracted_image"})


def _check_collision(known: Iterable[str], doc_id: str) -> None:
    """Raise when doc_id differs from a known ID only by letter case."""
    folded = doc_id.casefold()
    for other in known:
        if other != doc_id and other.casefold() == folded:
            raise ValueError(
                f"source document ids collide across filesystems: {other!r}, {doc_id!r}"
            )


def _count_json_pages(path: Path) -> int:
    """Page count for a structured transcription JSON (data contract).

    Reads the top-level pages array; a file without one counts as one page.
    See reference/data-contract.md for the schema.
    """
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return 1
    if not isinstance(data, dict):
        return 1
    pages = data.get("pages")
    if isinstance(pages, list) and pages:
        return len(pages)
    return 1


def scan_sources() -> dict[str, dict]:
    """Walk data/sources/ and collect per-document info.

    Documents are identified by stem name. A PDF counts as one document;
    a directory of images counts as one document per directory.
    """
    documents: dict[str, dict] = {}

    if not SOURCES_DIR.exists():
        return documents

    for path in sorted(SOURCES_DIR.rglob("*")):
        if path.is_dir():
            continue
        if path == SOURCES_DIR / SOURCE_MANIFEST_NAME:
            continue
        ext = path.suffix.lower()
        source_type = EXT_MAP.get(ext)
        if source_type is None:
            continue

        # Derive doc_id: for PDFs use stem; for files inside subdirectories use
        # the immediate parent folder name (e.g., data/sources/images/doc1/page.png -> doc1)
        if source_type == "pdf":
            doc_id = path.stem
        else:
            # If file is directly in sources/, use stem; otherwise use parent dir name
            rel = path.relative_to(SOURCES_DIR)
            if len(rel.parts) > 2:
                doc_id = rel.parts[1]
            elif len(rel.parts) == 2:
                doc_id = (
                    rel.parts[0]
                    if rel.parts[0] not in ("images", "text", "pdf")
                    else path.stem
                )
            else:
                doc_id = path.stem

        if not contract.valid_object_id(doc_id):
            raise ValueError(
                f"invalid source document id derived from {path}: {doc_id!r}"
            )

        _check_collision(documents, doc_id)

        if doc_id not in documents:
            documents[doc_id] = {
                "id": doc_id,
                "source_type": source_type,
                "pages": 0,
                "format": ext.lstrip("."),
                "path": str(path.parent.relative_to(SOURCES_DIR)),
                "files": [],
            }
        documents[doc_id]["files"].append(path.name)
        # Transcription JSONs carry several pages per file; every other
        # source type counts one page per file.
        if source_type == "transcription":
            documents[doc_id]["pages"] += _count_json_pages(path)
        else:
            documents[doc_id]["pages"] += 1

    return documents


def _manifest_image_urls(record: dict) -> dict[str, str]:
    """Normalize page image URLs declared in one manifest document."""
    pages = record.get("pages", [])
    if pages is None:
        raise ValueError(f"manifest document {record.get('id')!r} has null pages")
    if not isinstance(pages, list):
        raise ValueError(f"manifest document {record.get('id')!r} has no pages list")

    image_urls: dict[str, str] = {}
    page_numbers: list[int] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError(f"manifest page {index} is not an object")
        page_number = page.get("page")
        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
        ):
            raise ValueError(f"manifest page {index} has no page number from 1")
        page_numbers.append(page_number)
        url = page.get("image_url")
        if url is not None:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                raise ValueError(
                    f"manifest page {page_number} has an invalid image_url"
                )
            image_urls[str(page_number)] = url
    if page_numbers != list(range(1, len(pages) + 1)):
        raise ValueError(
            "manifest pages must be ordered and numbered consecutively from 1"
        )
    if image_urls and len(image_urls) != len(pages):
        raise ValueError(
            "manifest pages must either all declare image_url or all use local images"
        )
    return image_urls


def merge_source_manifest(documents: dict[str, dict]) -> dict[str, dict]:
    """Add explicit document metadata, prompt profiles and remote pages.

    The source manifest is the entry point for corpora whose catalogue and
    facsimiles live outside the repository. Local files remain discoverable
    without it, while a matching manifest record enriches the same document.
    """
    manifest_path = SOURCES_DIR / SOURCE_MANIFEST_NAME
    if not manifest_path.exists():
        return documents

    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read source manifest {manifest_path}: {exc}") from exc
    records = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("version") != "0.1":
        raise ValueError("source manifest version must be '0.1'")
    if not isinstance(records, list):
        raise ValueError("source manifest must contain a documents list")

    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("every source manifest document must be an object")
        doc_id = record.get("id")
        if not contract.valid_object_id(doc_id):
            raise ValueError(f"invalid source manifest document id: {doc_id!r}")
        if doc_id in seen:
            raise ValueError(f"duplicate source manifest document id: {doc_id}")
        # Every earlier manifest record is already an entry of documents.
        _check_collision(documents, doc_id)
        seen.add(doc_id)

        metadata = record.get("metadata", {})
        metadata_problems = contract.metadata_violations(
            metadata,
            prefix=f"metadata for {doc_id}",
        )
        if metadata_problems:
            raise ValueError("; ".join(metadata_problems))
        image_urls = _manifest_image_urls(record)
        declared_pages = len(record.get("pages", []))
        declared_urls = metadata.get("image_urls")
        if declared_urls is not None and not isinstance(declared_urls, (dict, list)):
            raise ValueError(
                f"metadata.image_urls for {doc_id} is not an object or list"
            )
        if image_urls:
            metadata = {**metadata, "image_urls": image_urls}

        if doc_id not in documents:
            page_count = len(record.get("pages", []))
            if not page_count and isinstance(metadata.get("image_urls"), dict):
                page_count = len(metadata["image_urls"])
            if not page_count and isinstance(metadata.get("image_urls"), list):
                page_count = len(metadata["image_urls"])
            documents[doc_id] = {
                "id": doc_id,
                "source_type": record.get("source_type", "remote_images"),
                "pages": page_count,
                "format": record.get("format", "remote"),
                "path": SOURCE_MANIFEST_NAME,
                "files": [],
            }

        entry = documents[doc_id]
        if declared_pages:
            entry["declared_pages"] = declared_pages
            local_pages = entry.get("pages", 0)
            if entry.get("source_type") == "image" and local_pages != declared_pages:
                raise ValueError(
                    f"{doc_id} has {local_pages} local pages; source manifest declares "
                    f"{declared_pages}"
                )
        existing_metadata = entry.get("metadata", {})
        entry["metadata"] = {**existing_metadata, **metadata}
        if record.get("prompt_profile"):
            profile = record["prompt_profile"]
            if not contract.valid_object_id(profile):
                raise ValueError(f"invalid prompt_profile for {doc_id}: {profile!r}")
            entry["prompt_profile"] = profile

    return documents


def _dominant_format(doc_dir: Path) -> str:
    """File extension of the first page image in a directory, without the dot."""
    images = list_page_images(doc_dir)
    return images[0].suffix.lstrip(".") if images else "png"


def scan_extracted_images(documents: dict[str, dict]) -> dict[str, dict]:
    """Augment documents with info from data/processed/images/ (extracted PDFs).

    Each subdirectory under IMAGES_DIR corresponds to a document. A manifest
    is verified by config.read_image_manifest, including the page hashes, and
    gives the page count; without one the page images are counted. The image
    type follows the directory, because PDF extraction writes PNG while
    fetch_facsimiles.py writes JPG.
    """
    if not IMAGES_DIR.exists():
        return documents

    for doc_dir in sorted(IMAGES_DIR.iterdir()):
        if not doc_dir.is_dir():
            continue
        doc_id = doc_dir.name
        if not contract.valid_object_id(doc_id):
            raise ValueError(f"invalid processed image document id: {doc_id!r}")
        _check_collision(documents, doc_id)
        if (doc_dir / "manifest.json").exists():
            page_count = len(read_image_manifest(doc_dir)[1])
        else:
            page_count = len(list_page_images(doc_dir))

        if doc_id in documents:
            declared_pages = documents[doc_id].get("declared_pages")
            if declared_pages is not None and page_count != declared_pages:
                raise ValueError(
                    f"{doc_id} has {page_count} materialized pages; source manifest declares "
                    f"{declared_pages}"
                )
            documents[doc_id]["materialized_pages"] = page_count
        else:
            # Extracted images without a source PDF (unusual but possible)
            documents[doc_id] = {
                "id": doc_id,
                "source_type": "extracted_image",
                "pages": page_count,
                "format": _dominant_format(doc_dir),
                "path": str(doc_dir.relative_to(PROCESSED_DIR)),
                "files": [f.name for f in list_page_images(doc_dir)],
            }

    return documents


def build_summary(documents: dict[str, dict]) -> dict:
    source_types: dict[str, int] = {}
    total_pages = 0
    for doc in documents.values():
        st = doc["source_type"]
        source_types[st] = source_types.get(st, 0) + 1
        total_pages += doc.get(
            "declared_pages", doc.get("materialized_pages", doc["pages"])
        )

    return {
        "total_documents": len(documents),
        "total_pages": total_pages,
        "source_types": source_types,
        "languages": [],  # Filled in by the human or later analysis
    }


def build_inventory(documents: dict[str, dict]) -> dict:
    summary = build_summary(documents)
    # Strip internal 'files' list from document entries -- keep inventory lean.
    # Downstream scripts use the manifest or scan the directory.
    doc_list = []
    for doc in sorted(documents.values(), key=lambda d: d["id"]):
        entry = {
            "id": doc["id"],
            "source_type": doc["source_type"],
            "pages": doc.get(
                "declared_pages", doc.get("materialized_pages", doc["pages"])
            ),
            "format": doc["format"],
            "path": doc["path"],
        }
        if doc.get("metadata"):
            entry["metadata"] = doc["metadata"]
        if doc.get("prompt_profile"):
            entry["prompt_profile"] = doc["prompt_profile"]
        entry["transcribable"] = (
            doc["source_type"] in IMAGE_SOURCE_TYPES
            or bool(doc.get("materialized_pages"))
            or bool(doc.get("metadata", {}).get("image_urls"))
        )
        doc_list.append(entry)

    return {
        "_meta": provenance_meta(script="02_analyze.py", step=2),
        "summary": summary,
        "documents": doc_list,
    }


def inventory_to_markdown(inventory: dict) -> str:
    s = inventory["summary"]
    lines = [
        "| Property | Value |",
        "|---|---|",
        f"| Documents | {s['total_documents']} |",
        f"| Pages | {s['total_pages']} |",
        f"| Source types | {', '.join(f'{k} ({v})' for k, v in s['source_types'].items())} |",
        f"| Languages | {', '.join(s['languages']) if s['languages'] else '(not yet determined)'} |",
        "",
        "### Documents",
        "",
        "| ID | Type | Pages | Format | Path | Step 3 |",
        "|---|---|---|---|---|---|",
    ]
    for doc in inventory["documents"]:
        step3 = "yes" if doc["transcribable"] else "no, no page images"
        lines.append(
            f"| {doc['id']} | {doc['source_type']} | {doc['pages']} | {doc['format']} "
            f"| {doc['path']} | {step3} |"
        )
    return "\n".join(lines)


def update_knowledge(markdown_block: str) -> None:
    """Insert summary between INVENTAR_START / INVENTAR_END markers in 02_DATA.md."""
    data_md_path = KNOWLEDGE_DIR / "02_DATA.md"
    if not data_md_path.exists():
        print(f"  WARNING: {data_md_path} not found, skipping knowledge update")
        return

    content = data_md_path.read_text(encoding="utf-8")
    start_marker = "<!-- INVENTAR_START -->"
    end_marker = "<!-- INVENTAR_END -->"

    if start_marker not in content or end_marker not in content:
        print(
            f"  WARNING: Markers {start_marker} / {end_marker} not found in 02_DATA.md, skipping"
        )
        return

    start_idx = content.index(start_marker) + len(start_marker)
    end_idx = content.index(end_marker)
    new_content = content[:start_idx] + "\n" + markdown_block + "\n" + content[end_idx:]
    write_text_atomic(data_md_path, new_content)
    print(f"  Updated {data_md_path}")


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Analyze source data and create inventory."
    )
    parser.add_argument(
        "--update-knowledge",
        action="store_true",
        help="Update knowledge/02_DATA.md with inventory summary",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format for stdout (default: json). Inventory file is always JSON.",
    )
    args = parser.parse_args()

    ensure_dirs()

    try:
        print("Scanning data/sources/ ...")
        documents = scan_sources()
        print(f"  Found {len(documents)} document(s) in sources")
        documents = merge_source_manifest(documents)
        print("Scanning data/processed/images/ ...")
        documents = scan_extracted_images(documents)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"  Total {len(documents)} document(s) after image scan")

    inventory = build_inventory(documents)

    write_json_atomic(INVENTORY_PATH, inventory)
    print(f"\nInventory written to {INVENTORY_PATH}")

    md = inventory_to_markdown(inventory)

    if args.update_knowledge:
        update_knowledge(md)

    # Print to stdout in requested format
    if args.format == "markdown":
        print(f"\n{md}")
    else:
        print(json.dumps(inventory, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
