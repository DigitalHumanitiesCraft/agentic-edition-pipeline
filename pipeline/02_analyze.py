"""Analyze source data and produce an inventory.

Walks data/sources/ and data/processed/images/ to build a structured inventory
of all documents in the project. The inventory is the single source of truth
for downstream pipeline steps -- they read inventory.json to know what to
process, rather than scanning the filesystem themselves.

Optionally updates knowledge/02_DATA.md with a human-readable summary between
INVENTAR_START / INVENTAR_END markers, so the knowledge document stays in sync.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import (
    DATA_DIR,
    IMAGES_DIR,
    KNOWLEDGE_DIR,
    PROCESSED_DIR,
    SOURCES_DIR,
    ensure_dirs,
    list_page_images,
    provenance_meta,
)

INVENTORY_PATH = DATA_DIR / "inventory.json"

# File extensions grouped by source type
EXT_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".tif": "image", ".tiff": "image",
    ".txt": "text", ".xml": "xml", ".docx": "docx",
    ".json": "transcription",
}


def _count_json_pages(path: Path) -> int:
    """Page count for a structured transcription JSON (data contract).

    Reads the top-level pages array; a file without one counts as one page.
    See knowledge/08_DATA_CONTRACT.md for the schema.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
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
                doc_id = rel.parts[0] if rel.parts[0] not in ("images", "text", "pdf") else path.stem
            else:
                doc_id = path.stem

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


def _dominant_format(doc_dir: Path) -> str:
    """File extension of the first page image in a directory, without the dot."""
    images = list_page_images(doc_dir)
    return images[0].suffix.lstrip(".") if images else "png"


def scan_extracted_images(documents: dict[str, dict]) -> dict[str, dict]:
    """Augment documents with info from data/processed/images/ (extracted PDFs).

    Each subdirectory under IMAGES_DIR corresponds to a document. If a manifest
    exists, use it for page count; otherwise count the page images. The image
    type follows the directory, because PDF extraction writes PNG while
    fetch_facsimiles.py writes JPG.
    """
    if not IMAGES_DIR.exists():
        return documents

    for doc_dir in sorted(IMAGES_DIR.iterdir()):
        if not doc_dir.is_dir():
            continue
        doc_id = doc_dir.name
        manifest_path = doc_dir / "manifest.json"

        page_count = 0
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                page_count = len(manifest.get("pages", []))
            except (json.JSONDecodeError, KeyError):
                page_count = len(list_page_images(doc_dir))
        else:
            page_count = len(list_page_images(doc_dir))

        if doc_id in documents:
            # Update existing entry with extracted image info
            documents[doc_id]["extracted_pages"] = page_count
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
        total_pages += doc.get("extracted_pages", doc["pages"])

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
            "pages": doc.get("extracted_pages", doc["pages"]),
            "format": doc["format"],
            "path": doc["path"],
        }
        doc_list.append(entry)

    return {
        "_meta": provenance_meta(script="02_analyze.py", step=2),
        "summary": summary,
        "documents": doc_list,
    }


def inventory_to_markdown(inventory: dict) -> str:
    s = inventory["summary"]
    lines = [
        "| Eigenschaft | Wert |",
        "|---|---|",
        f"| Dokumente gesamt | {s['total_documents']} |",
        f"| Seiten gesamt | {s['total_pages']} |",
        f"| Quellentypen | {', '.join(f'{k} ({v})' for k, v in s['source_types'].items())} |",
        f"| Sprachen | {', '.join(s['languages']) if s['languages'] else '(noch nicht bestimmt)'} |",
        "",
        "### Dokumente",
        "",
        "| ID | Typ | Seiten | Format | Pfad |",
        "|---|---|---|---|---|",
    ]
    for doc in inventory["documents"]:
        lines.append(f"| {doc['id']} | {doc['source_type']} | {doc['pages']} | {doc['format']} | {doc['path']} |")
    return "\n".join(lines)


def update_knowledge(markdown_block: str):
    """Insert summary between INVENTAR_START / INVENTAR_END markers in 02_DATA.md."""
    data_md_path = KNOWLEDGE_DIR / "02_DATA.md"
    if not data_md_path.exists():
        print(f"  WARNING: {data_md_path} not found, skipping knowledge update")
        return

    content = data_md_path.read_text(encoding="utf-8")
    start_marker = "<!-- INVENTAR_START -->"
    end_marker = "<!-- INVENTAR_END -->"

    if start_marker not in content or end_marker not in content:
        print(f"  WARNING: Markers {start_marker} / {end_marker} not found in 02_DATA.md, skipping")
        return

    start_idx = content.index(start_marker) + len(start_marker)
    end_idx = content.index(end_marker)
    new_content = content[:start_idx] + "\n" + markdown_block + "\n" + content[end_idx:]
    data_md_path.write_text(new_content, encoding="utf-8")
    print(f"  Updated {data_md_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze source data and create inventory.")
    parser.add_argument(
        "--update-knowledge", action="store_true",
        help="Update knowledge/02_DATA.md with inventory summary",
    )
    parser.add_argument(
        "--format", choices=["json", "markdown"], default="json",
        help="Output format for stdout (default: json). Inventory file is always JSON.",
    )
    args = parser.parse_args()

    ensure_dirs()

    print("Scanning data/sources/ ...")
    documents = scan_sources()
    print(f"  Found {len(documents)} document(s) in sources")

    print("Scanning data/processed/images/ ...")
    documents = scan_extracted_images(documents)
    print(f"  Total {len(documents)} document(s) after image scan")

    inventory = build_inventory(documents)

    # Always write inventory.json
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_PATH.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
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
