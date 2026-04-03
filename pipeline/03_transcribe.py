"""Transcribe document images via LLM API.

Reads the inventory to discover documents, loads page images, sends them to
the configured LLM provider with a transcription prompt, and writes structured
JSON output per document. Supports chunking for documents with many pages
(API context limits) and includes basic quality signals in the output.

Designed for batch processing with rate-limit awareness: --delay controls
inter-document pause, --chunk-size controls how many images go into one API
call. The retry-with-JSON-hint pattern handles models that occasionally return
prose instead of JSON on the first attempt.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from config import (
    BATCH_DELAY,
    CHUNK_SIZE,
    DATA_DIR,
    IMAGES_DIR,
    SOURCES_DIR,
    TRANSCRIPTIONS_DIR,
    TRANSCRIPTION_MODEL,
    TRANSCRIPTION_PROVIDER,
    ensure_dirs,
    load_prompt,
    provenance_meta,
    write_errors,
)
from llm import call_llm, parse_json_response

INVENTORY_PATH = DATA_DIR / "inventory.json"


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------

def find_images_for_document(doc: dict) -> list[Path]:
    """Locate page images for a document entry from the inventory.

    Checks extracted images first (data/processed/images/{id}/), then falls
    back to source images (data/sources/images/{id}/). Returns sorted list.
    """
    extracted_dir = IMAGES_DIR / doc["id"]
    if extracted_dir.is_dir():
        # If a manifest exists, use its ordering; otherwise glob PNGs
        manifest_path = extracted_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                return [extracted_dir / p["filename"] for p in manifest["pages"]
                        if "error" not in p and (extracted_dir / p["filename"]).exists()]
            except (json.JSONDecodeError, KeyError):
                pass
        return sorted(extracted_dir.glob("*.png"))

    source_dir = SOURCES_DIR / "images" / doc["id"]
    if source_dir.is_dir():
        # Accept common image formats
        images = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff"):
            images.extend(source_dir.glob(ext))
        return sorted(images)

    return []


# ---------------------------------------------------------------------------
# Chunked transcription
# ---------------------------------------------------------------------------

def transcribe_chunk(
    images: list[Path],
    system_prompt: str,
    provider: str,
    model: str,
    doc_id: str,
    chunk_index: int,
) -> dict | None:
    """Transcribe a single chunk of images. Returns parsed JSON or None."""
    # Context line helps the model orient within a multi-chunk document
    context = f"Document: {doc_id}, chunk {chunk_index + 1}, pages {len(images)}"
    full_prompt = f"{system_prompt}\n\n{context}"

    raw = call_llm(provider, model, full_prompt, images)
    result = parse_json_response(raw)

    if result is None:
        # Retry once with an explicit JSON hint -- some models need the nudge
        retry_prompt = full_prompt + "\n\nIMPORTANT: Respond with valid JSON only."
        raw = call_llm(provider, model, retry_prompt, images)
        result = parse_json_response(raw)

    return result


def merge_chunks(chunks: list[dict]) -> dict:
    """Merge transcription results from multiple chunks into one document.

    Concatenates page arrays. Confidence is the minimum across all chunks
    (worst-case represents overall reliability).
    """
    merged_pages: list[dict] = []
    worst_confidence: float = 1.0

    for chunk in chunks:
        if isinstance(chunk, dict):
            pages = chunk.get("pages", [])
            if isinstance(pages, list):
                merged_pages.extend(pages)
            conf = chunk.get("confidence", 1.0)
            if isinstance(conf, (int, float)):
                worst_confidence = min(worst_confidence, conf)

    return {
        "pages": merged_pages,
        "confidence": worst_confidence,
    }


# ---------------------------------------------------------------------------
# Quality signals -- kept deliberately simple for the template.
# The full 7-signal implementation from szd-htr can be added when adapting
# to a specific project. For now: page classification and character stats.
# ---------------------------------------------------------------------------

def compute_quality_signals(transcription: dict, image_count: int) -> dict:
    pages = transcription.get("pages", [])

    total_chars = 0
    blank_pages = 0
    page_types: list[str] = []

    for page in pages:
        text = page.get("text", "")
        char_count = len(text.strip())
        total_chars += char_count
        if char_count < 10:
            page_types.append("blank")
            blank_pages += 1
        else:
            page_types.append("content")

    page_count = len(pages)
    chars_per_page = total_chars / page_count if page_count > 0 else 0

    # Flag for review if images exist but transcription is empty
    needs_review = (image_count > 0 and blank_pages == image_count)

    return {
        "page_types": page_types,
        "total_chars": total_chars,
        "chars_per_page": round(chars_per_page, 1),
        "blank_pages": blank_pages,
        "content_pages": page_count - blank_pages,
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------

def transcribe_document(
    doc: dict,
    system_prompt: str,
    provider: str,
    model: str,
    chunk_size: int,
    force: bool,
) -> dict | None:
    """Transcribe a single document. Returns error dict on failure, None on success."""
    doc_id = doc["id"]
    out_path = TRANSCRIPTIONS_DIR / f"{doc_id}.json"

    if out_path.exists() and not force:
        print(f"  SKIP {doc_id} (exists, use --force)")
        return None

    images = find_images_for_document(doc)
    if not images:
        return {"object_id": doc_id, "error": "No images found", "stage": "discovery"}

    print(f"  Processing {doc_id} ({len(images)} page(s)) ...", end="", flush=True)

    try:
        # Split into chunks if needed
        if len(images) <= chunk_size:
            result = transcribe_chunk(images, system_prompt, provider, model, doc_id, 0)
            if result is None:
                return {"object_id": doc_id, "error": "JSON parse failed after retry", "stage": "parse"}
        else:
            chunk_results: list[dict] = []
            for i in range(0, len(images), chunk_size):
                chunk_imgs = images[i:i + chunk_size]
                chunk_result = transcribe_chunk(
                    chunk_imgs, system_prompt, provider, model, doc_id, i // chunk_size,
                )
                if chunk_result is None:
                    return {
                        "object_id": doc_id,
                        "error": f"JSON parse failed for chunk {i // chunk_size}",
                        "stage": "parse",
                    }
                chunk_results.append(chunk_result)
            result = merge_chunks(chunk_results)

    except Exception as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "api_call"}

    quality = compute_quality_signals(result, len(images))

    output = {
        "_meta": provenance_meta(
            script="03_transcribe.py",
            provider=provider,
            model=model,
            prompt_template="transcription.md",
            step=3,
        ),
        "object_id": doc_id,
        "source_images": [img.name for img in images],
        "transcription": result,
        "quality_signals": quality,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    status = "REVIEW" if quality["needs_review"] else "OK"
    print(f" {status} ({quality['total_chars']} chars, {quality['content_pages']}/{len(images)} content pages)")
    return None


# ---------------------------------------------------------------------------
# CLI and batch orchestration
# ---------------------------------------------------------------------------

def load_inventory() -> dict:
    if not INVENTORY_PATH.exists():
        print(f"ERROR: {INVENTORY_PATH} not found. Run 02_analyze.py first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def select_documents(inventory: dict, object_id: str | None, all_flag: bool, sample: int | None) -> list[dict]:
    docs = inventory.get("documents", [])

    if object_id:
        matches = [d for d in docs if d["id"] == object_id]
        if not matches:
            print(f"ERROR: Object '{object_id}' not found in inventory.", file=sys.stderr)
            sys.exit(1)
        return matches

    if all_flag:
        if sample and sample > 0:
            return docs[:sample]
        return docs

    print("Specify --object ID, --all, or --all --sample N", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Transcribe document images via LLM.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Transcribe a single document by ID")
    group.add_argument("--all", action="store_true", help="Transcribe all documents in inventory")
    parser.add_argument("--sample", type=int, metavar="N", help="Process only first N documents (with --all)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing transcriptions")
    parser.add_argument("--dry-run", action="store_true", help="List documents without calling API")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE,
                        help=f"Max images per API call (default {CHUNK_SIZE})")
    parser.add_argument("--delay", type=float, default=BATCH_DELAY,
                        help=f"Seconds between documents (default {BATCH_DELAY})")
    args = parser.parse_args()

    ensure_dirs()
    inventory = load_inventory()
    docs = select_documents(inventory, args.object, args.all, args.sample)
    provider = TRANSCRIPTION_PROVIDER
    model = TRANSCRIPTION_MODEL

    print(f"Transcription: {len(docs)} document(s), provider={provider}, model={model}")
    print(f"Chunk size={args.chunk_size}, delay={args.delay}s\n")

    if args.dry_run:
        print("DRY RUN -- no API calls will be made:\n")
        for doc in docs:
            images = find_images_for_document(doc)
            out_path = TRANSCRIPTIONS_DIR / f"{doc['id']}.json"
            status = "EXISTS" if out_path.exists() and not args.force else "PENDING"
            print(f"  [{status}] {doc['id']}: {len(images)} image(s)")
        return

    system_prompt = load_prompt("transcription.md")

    errors: list[dict] = []
    for i, doc in enumerate(docs):
        err = transcribe_document(doc, system_prompt, provider, model, args.chunk_size, args.force)
        if err:
            errors.append(err)
            print(f"  FAIL {err['object_id']}: {err['error']}")

        # Rate-limit courtesy delay between documents (not after the last one)
        if i < len(docs) - 1:
            time.sleep(args.delay)

    if errors:
        write_errors(errors, TRANSCRIPTIONS_DIR)
        print(f"\n{len(errors)} error(s) written to {TRANSCRIPTIONS_DIR / 'errors.json'}")

    succeeded = len(docs) - len(errors)
    print(f"\nDone. {succeeded}/{len(docs)} document(s) transcribed successfully.")


if __name__ == "__main__":
    main()
