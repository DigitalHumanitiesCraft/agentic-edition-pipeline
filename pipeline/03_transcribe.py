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

import contract
from config import (
    BATCH_DELAY,
    CHUNK_SIZE,
    DATA_DIR,
    TRANSCRIPTION_MODEL,
    TRANSCRIPTION_PROVIDER,
    TRANSCRIPTIONS_DIR,
    ensure_dirs,
    list_page_images,
    load_prompt,
    missing_api_key,
    provenance_meta,
    resolve_image_dir,
    write_errors,
)
from llm import call_llm, parse_json_response, redact_secrets

INVENTORY_PATH = DATA_DIR / "inventory.json"


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------

def find_images_for_document(doc: dict) -> list[Path]:
    """Locate page images for a document via the shared image-root resolver.

    Resolution order (config.resolve_image_dir): data/sources/images/{id}/
    first, then data/processed/images/{id}/. When an extraction manifest
    exists it defines page order; otherwise images sort by filename.
    """
    image_dir = resolve_image_dir(doc["id"])
    if image_dir is None:
        return []

    manifest_path = image_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return [image_dir / p["filename"] for p in manifest["pages"]
                    if "error" not in p and (image_dir / p["filename"]).exists()]
        except (json.JSONDecodeError, KeyError):
            pass
    return list_page_images(image_dir)


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


# Contract vocabulary of the confidence field, weakest first. A merge across
# chunks keeps the weakest declared value, because a document is only as
# reliable as its worst chunk.
CONFIDENCE_ORDER = ("low", "medium", "high")


def _worst_confidence(chunks: list[dict]) -> str:
    """The weakest confidence value any chunk declared, or "" if none did."""
    declared = [
        chunk["confidence"].lower()
        for chunk in chunks
        if isinstance(chunk.get("confidence"), str)
        and chunk["confidence"].lower() in CONFIDENCE_ORDER
    ]
    if not declared:
        return ""
    return min(declared, key=CONFIDENCE_ORDER.index)


def merge_chunks(chunks: list[dict]) -> dict:
    """Merge transcription results from multiple chunks into one document.

    Page arrays concatenate. Object-level fields describe the document rather
    than the chunk: metadata comes from the first chunk that carries it, the
    confidence notes of all chunks are kept, and confidence stays in the
    string vocabulary of the data contract instead of becoming a number.
    """
    chunks = [chunk for chunk in chunks if isinstance(chunk, dict)]

    merged_pages: list[dict] = []
    metadata: dict = {}
    notes: list[str] = []

    for chunk in chunks:
        pages = chunk.get("pages", [])
        if isinstance(pages, list):
            merged_pages.extend(pages)
        if not metadata and isinstance(chunk.get("metadata"), dict):
            metadata = chunk["metadata"]
        note = chunk.get("confidence_notes", "")
        if isinstance(note, str) and note.strip():
            notes.append(note.strip())

    return {
        "metadata": metadata,
        "pages": merged_pages,
        "confidence": _worst_confidence(chunks),
        "confidence_notes": "\n".join(notes),
    }


# ---------------------------------------------------------------------------
# Quality signals -- kept deliberately simple for the template.
# The full 7-signal implementation from szd-htr can be added when adapting
# to a specific project. For now: page classification and character stats.
# ---------------------------------------------------------------------------

def compute_quality_signals(transcription: dict, image_count: int) -> dict:
    """Derive quality signals from the page array (data contract key: transcription).

    A page-level page_type declared by the model (blank, foreign_text,
    gate_low_resolution) takes precedence over the character-count inference.
    """
    pages = transcription.get("pages", [])

    total_chars = 0
    blank_pages = 0
    gate_pages = 0
    foreign_pages = 0
    page_types: list[str] = []

    for page in pages:
        text = page.get("transcription", "")
        char_count = len(text.strip())
        total_chars += char_count

        declared = page.get("page_type", "")
        if declared:
            page_types.append(declared)
            if declared == "blank":
                blank_pages += 1
            elif declared == "gate_low_resolution":
                gate_pages += 1
            elif declared == "foreign_text":
                foreign_pages += 1
        elif char_count < 10:
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
        "gate_pages": gate_pages,
        "foreign_pages": foreign_pages,
        "content_pages": page_count - blank_pages - gate_pages - foreign_pages,
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
        return {"object_id": doc_id, "error": redact_secrets(str(exc)), "stage": "api_call"}

    # Contract gate before writing: an answer without a usable pages structure
    # would otherwise produce a file that claims an empty but reviewed
    # transcription (needs_review false), which no later step can distinguish
    # from a genuinely blank document.
    violations = contract.response_violations(result)
    if violations:
        return {
            "object_id": doc_id,
            "error": "Model response violates the data contract: " + "; ".join(violations),
            "stage": "contract",
        }

    quality = compute_quality_signals(result, len(images))

    # Output follows the pipeline data contract (knowledge/08_DATA_CONTRACT.md):
    # pages at the top level, object metadata under "metadata". Steps 4-6 pass
    # both through unchanged. Metadata not delivered by the model (title, date,
    # image URLs) is filled in here from nothing and completed by the operator.
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
        "metadata": result.get("metadata", {}) if isinstance(result.get("metadata"), dict) else {},
        "pages": result.get("pages", []),
        "confidence": result.get("confidence", ""),
        "confidence_notes": result.get("confidence_notes", ""),
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

    # Fail fast instead of producing empty or partial results without a key.
    if not args.dry_run:
        missing = missing_api_key(provider)
        if missing:
            print(
                f"ERROR: no API key configured, this step requires one. "
                f"Set {missing} in .env for provider '{provider}'.",
                file=sys.stderr,
            )
            sys.exit(1)

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

    # A document that could not be processed is a failed run, not a result.
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
