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
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import contract
from config import (
    BATCH_DELAY,
    CHUNK_SIZE,
    DATA_DIR,
    PROMPTS_DIR,
    TRANSCRIPTION_MODEL,
    TRANSCRIPTION_PROVIDER,
    TRANSCRIPTIONS_DIR,
    ensure_dirs,
    load_prompt,
    missing_api_key,
    ordered_page_images,
    provenance_meta,
    provider_config_error,
    source_image_state,
    source_image_state_hash,
    write_errors,
    write_json_atomic,
)
from llm import call_llm, parse_json_response, redact_secrets

INVENTORY_PATH = DATA_DIR / "inventory.json"
PROMPT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _metadata_hash(metadata: dict) -> str:
    """Hash the complete authoritative inventory metadata."""
    serialized = json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def _has_review_history(data: object) -> bool:
    """Return whether an existing object contains any human review event."""
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        return False
    return any(
        isinstance(page, dict)
        and isinstance(page.get("review"), dict)
        and bool(page["review"].get("history"))
        for page in data["pages"]
    )


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------


def find_images_for_document(doc: dict) -> list[Path]:
    """Locate page images through the shared manifest-aware resolver."""
    expected_pages = doc.get("pages")
    if not isinstance(expected_pages, int) or isinstance(expected_pages, bool):
        expected_pages = None
    urls = doc.get("metadata", {}).get("image_urls")
    expected_urls: list[str] | None = None
    if isinstance(urls, dict):
        expected_urls = [urls[str(page)] for page in range(1, len(urls) + 1)]
    elif isinstance(urls, list):
        expected_urls = urls
    return ordered_page_images(
        doc["id"],
        expected_pages=expected_pages,
        expected_urls=expected_urls,
    )


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _prompt_component(value: object, field: str) -> str:
    """Return a path-safe prompt key or raise at the prompt trust boundary."""
    if not isinstance(value, str) or not PROMPT_KEY.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def assemble_prompt(doc: dict, base_prompt: str) -> tuple[str, dict]:
    """Build the runtime prompt from profile, metadata and object layers.

    The manifest selects a profile explicitly. Missing declared profile files
    fail the document instead of silently falling back to the base prompt.
    """
    doc_id = _prompt_component(doc.get("id"), "document id")
    metadata = doc.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError(f"metadata for {doc_id} is not an object")

    sections = [base_prompt]
    layers = ["transcription.md"]
    profile = doc.get("prompt_profile", "")
    if profile:
        profile = _prompt_component(profile, "prompt_profile")
        profile_path = PROMPTS_DIR / "profiles" / f"{profile}.md"
        if not profile_path.exists():
            raise FileNotFoundError(
                f"declared prompt profile not found: {profile_path}"
            )
        sections.append(
            "## Document-type profile\n\n"
            + profile_path.read_text(encoding="utf-8").strip()
        )
        layers.append(f"profiles/{profile}.md")

    context_fields = (
        ("Title", "title"),
        ("Signature / Identifier", "signature"),
        ("Date", "date"),
        ("Language", "language"),
        ("Object type", "object_type"),
        ("Extent", "extent"),
    )
    context_lines = [
        f"- {label}: {metadata[key]}"
        for label, key in context_fields
        if metadata.get(key) not in (None, "")
    ]
    if not any(line.startswith("- Extent:") for line in context_lines) and doc.get(
        "pages"
    ):
        context_lines.append(f"- Extent: {doc['pages']} page(s)")
    if context_lines:
        sections.append("## Document metadata\n\n" + "\n".join(context_lines))
        layers.append("inventory:metadata")

    override_path = PROMPTS_DIR / "objects" / f"{doc_id}.md"
    if override_path.exists():
        sections.append(
            "## Object-specific instructions\n\n"
            + override_path.read_text(encoding="utf-8").strip()
        )
        layers.append(f"objects/{doc_id}.md")

    prompt = "\n\n".join(section.strip() for section in sections if section.strip())
    info = {
        "prompt_layers": layers,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
    }
    if profile:
        info["prompt_profile"] = profile
    return prompt, info


def initialize_machine_pages(pages: list[dict]) -> list[dict]:
    """Create the immutable machine layer and initial human-review state."""
    initialized: list[dict] = []
    for page in pages:
        item = dict(page)
        item["transcription_raw"] = item["transcription"]
        item["review"] = {"status": "machine_unreviewed", "history": []}
        initialized.append(item)
    return initialized


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
    start_page: int,
) -> tuple[dict | None, list[dict]]:
    """Transcribe one chunk and record every executed prompt hash."""
    end_page = start_page + len(images) - 1
    context = (
        f"Document: {doc_id}, chunk {chunk_index + 1}, source pages "
        f"{start_page}-{end_page}. Number the returned pages from {start_page}."
    )
    full_prompt = f"{system_prompt}\n\n{context}"

    calls = [
        {
            "chunk": chunk_index + 1,
            "pages": list(range(start_page, end_page + 1)),
            "attempt": 1,
            "prompt_hash": hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()[:12],
        }
    ]
    raw = call_llm(provider, model, full_prompt, images)
    result = parse_json_response(raw)

    if result is None:
        # Retry once with an explicit JSON hint -- some models need the nudge
        retry_prompt = full_prompt + "\n\nIMPORTANT: Respond with valid JSON only."
        calls.append(
            {
                "chunk": chunk_index + 1,
                "pages": list(range(start_page, end_page + 1)),
                "attempt": 2,
                "prompt_hash": hashlib.sha256(retry_prompt.encode("utf-8")).hexdigest()[
                    :12
                ],
            }
        )
        raw = call_llm(provider, model, retry_prompt, images)
        result = parse_json_response(raw)

    return result, calls


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
    undeclared_empty_pages = 0
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
        elif not text.strip():
            page_types.append("undeclared_empty")
            undeclared_empty_pages += 1
        else:
            page_types.append("content")

    page_count = len(pages)
    chars_per_page = total_chars / page_count if page_count > 0 else 0

    # Flag for review if images exist but transcription is empty
    needs_review = undeclared_empty_pages > 0 or (
        image_count > 0 and blank_pages == image_count
    )

    return {
        "page_types": page_types,
        "total_chars": total_chars,
        "chars_per_page": round(chars_per_page, 1),
        "blank_pages": blank_pages,
        "undeclared_empty_pages": undeclared_empty_pages,
        "gate_pages": gate_pages,
        "foreign_pages": foreign_pages,
        "content_pages": (
            page_count
            - blank_pages
            - undeclared_empty_pages
            - gate_pages
            - foreign_pages
        ),
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------


def transcribe_document(
    doc: dict,
    base_prompt: str,
    provider: str,
    model: str,
    chunk_size: int,
    force: bool,
) -> dict | None:
    """Transcribe a single document. Returns error dict on failure, None on success."""
    doc_id = doc.get("id")
    if not contract.valid_object_id(doc_id):
        return {
            "object_id": str(doc_id),
            "error": "inventory object_id is not a path-safe identifier",
            "stage": "contract",
        }
    out_path = TRANSCRIPTIONS_DIR / f"{doc_id}.json"

    source_metadata = doc.get("metadata", {})
    metadata_problems = contract.metadata_violations(
        source_metadata,
        prefix="inventory metadata",
    )
    if metadata_problems:
        return {
            "object_id": doc_id,
            "error": "Input violates the data contract: "
            + "; ".join(metadata_problems),
            "stage": "contract",
        }

    try:
        images = find_images_for_document(doc)
    except (OSError, ValueError) as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "discovery"}
    if not images:
        return {"object_id": doc_id, "error": "No images found", "stage": "discovery"}

    try:
        image_state = source_image_state(images)
    except OSError as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "discovery"}

    try:
        system_prompt, prompt_info = assemble_prompt(doc, base_prompt)
    except (FileNotFoundError, ValueError) as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "prompt"}

    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "object_id": doc_id,
                "error": (
                    f"Existing transcription is unreadable: {exc}; retain and "
                    "repair or rename it before starting a new model run"
                ),
                "stage": "stale",
            }
        if force:
            existing_problems = contract.file_violations(existing)
            if existing_problems:
                return {
                    "object_id": doc_id,
                    "error": (
                        "Refusing --force because the existing transcription is "
                        "not contract-conformant; retain and repair or rename it"
                    ),
                    "stage": "stale",
                }
            if _has_review_history(existing):
                return {
                    "object_id": doc_id,
                    "error": (
                        "Refusing --force because the existing transcription contains "
                        "human review history; retain it and use a new object identifier "
                        "for a new model run"
                    ),
                    "stage": "review_history",
                }
            existing = None
        else:
            assert isinstance(existing, dict)
            existing_meta = existing.get("_meta", {})
            current_source_hash = source_image_state_hash(image_state)
            current = (
                not contract.file_violations(existing)
                and existing.get("object_id") == doc_id
                and existing_meta.get("pipeline_step") == 3
                and existing_meta.get("provider") == provider
                and existing_meta.get("model") == model
                and existing_meta.get("prompt_hash") == prompt_info["prompt_hash"]
                and existing_meta.get("prompt_layers") == prompt_info["prompt_layers"]
                and existing_meta.get("prompt_profile")
                == prompt_info.get("prompt_profile")
                and existing_meta.get("source_images_hash") == current_source_hash
                and existing_meta.get("source_metadata_hash")
                == _metadata_hash(source_metadata)
            )
            if current:
                print(
                    f"  SKIP {doc_id} (transcription matches prompt and source state)"
                )
                return None
            return {
                "object_id": doc_id,
                "error": "Existing transcription is stale or invalid; rerun with --force",
                "stage": "stale",
            }

    print(f"  Processing {doc_id} ({len(images)} page(s)) ...", end="", flush=True)

    try:
        executed_prompts: list[dict] = []
        # Split into chunks if needed
        if len(images) <= chunk_size:
            result, calls = transcribe_chunk(
                images, system_prompt, provider, model, doc_id, 0, 1
            )
            executed_prompts.extend(calls)
            if result is None:
                return {
                    "object_id": doc_id,
                    "error": "JSON parse failed after retry",
                    "stage": "parse",
                }
            violations = contract.response_violations(
                result,
                expected_pages=len(images),
                expected_numbers=list(range(1, len(images) + 1)),
            )
            if violations:
                return {
                    "object_id": doc_id,
                    "error": "Model response violates the data contract: "
                    + "; ".join(violations),
                    "stage": "contract",
                }
        else:
            chunk_results: list[dict] = []
            for i in range(0, len(images), chunk_size):
                chunk_imgs = images[i : i + chunk_size]
                chunk_result, calls = transcribe_chunk(
                    chunk_imgs,
                    system_prompt,
                    provider,
                    model,
                    doc_id,
                    i // chunk_size,
                    i + 1,
                )
                executed_prompts.extend(calls)
                if chunk_result is None:
                    return {
                        "object_id": doc_id,
                        "error": f"JSON parse failed for chunk {i // chunk_size}",
                        "stage": "parse",
                    }
                expected_numbers = list(range(i + 1, i + len(chunk_imgs) + 1))
                violations = contract.response_violations(
                    chunk_result,
                    expected_pages=len(chunk_imgs),
                    expected_numbers=expected_numbers,
                )
                if violations:
                    return {
                        "object_id": doc_id,
                        "error": f"Chunk {i // chunk_size + 1} violates the data contract: "
                        + "; ".join(violations),
                        "stage": "contract",
                    }
                chunk_results.append(chunk_result)
            result = merge_chunks(chunk_results)

    except (FileNotFoundError, ValueError) as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "prompt"}
    except Exception as exc:
        return {
            "object_id": doc_id,
            "error": redact_secrets(str(exc)),
            "stage": "api_call",
        }

    # Contract gate before writing: an answer without a usable pages structure
    # would otherwise produce a file that claims an empty but reviewed
    # transcription (needs_review false), which no later step can distinguish
    # from a genuinely blank document.
    violations = contract.response_violations(
        result,
        expected_pages=len(images),
        expected_numbers=list(range(1, len(images) + 1)),
    )
    if violations:
        return {
            "object_id": doc_id,
            "error": "Model response violates the data contract: "
            + "; ".join(violations),
            "stage": "contract",
        }

    pages = initialize_machine_pages(result.get("pages", []))
    quality = compute_quality_signals({"pages": pages}, len(images))

    model_metadata = result.get("metadata", {})
    if not isinstance(model_metadata, dict):
        model_metadata = {}
    metadata = {**model_metadata, **source_metadata}

    meta = provenance_meta(
        script="03_transcribe.py",
        provider=provider,
        model=model,
        prompt_template="transcription.md",
        step=3,
    )
    meta.update(prompt_info)
    meta["executed_prompts"] = executed_prompts
    try:
        final_image_state = source_image_state(images)
    except OSError as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "source_state"}
    if image_state != final_image_state:
        return {
            "object_id": doc_id,
            "error": "Source images changed during transcription",
            "stage": "source_state",
        }
    meta["source_images"] = image_state
    meta["source_images_hash"] = source_image_state_hash(image_state)
    meta["source_metadata_hash"] = _metadata_hash(source_metadata)
    meta["raw_transcription_hash"] = contract.raw_transcription_state_hash(
        {"pages": pages}
    )

    # Output follows the pipeline data contract (knowledge/08_DATA_CONTRACT.md):
    # pages at the top level, object metadata under "metadata". Steps 4-6 pass
    # both through unchanged. Manifest metadata is authoritative over any
    # metadata proposed by the model.
    output = {
        "_meta": meta,
        "object_id": doc_id,
        "source_images": [img.name for img in images],
        "metadata": metadata,
        "pages": pages,
        "confidence": result.get("confidence", ""),
        "confidence_notes": result.get("confidence_notes", ""),
        "quality_signals": quality,
    }

    violations = contract.file_violations(output)
    if violations:
        return {
            "object_id": doc_id,
            "error": "Assembled transcription violates the data contract: "
            + "; ".join(violations),
            "stage": "contract",
        }

    try:
        write_json_atomic(out_path, output)
    except OSError as exc:
        return {"object_id": doc_id, "error": str(exc), "stage": "write"}

    status = "REVIEW" if quality["needs_review"] else "OK"
    print(
        f" {status} ({quality['total_chars']} chars, {quality['content_pages']}/{len(images)} content pages)"
    )
    return None


# ---------------------------------------------------------------------------
# CLI and batch orchestration
# ---------------------------------------------------------------------------


def load_inventory() -> dict:
    if not INVENTORY_PATH.exists():
        print(
            f"ERROR: {INVENTORY_PATH} not found. Run 02_analyze.py first.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read {INVENTORY_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)
    documents = inventory.get("documents") if isinstance(inventory, dict) else None
    if not isinstance(documents, list) or any(
        not isinstance(doc, dict)
        or not isinstance(doc.get("id"), str)
        or not contract.valid_object_id(doc["id"])
        for doc in documents
    ):
        print(
            "ERROR: inventory must contain documents with path-safe string IDs.",
            file=sys.stderr,
        )
        sys.exit(1)
    id_problems = contract.unique_object_id_violations([doc["id"] for doc in documents])
    if id_problems:
        print("ERROR: " + "; ".join(id_problems), file=sys.stderr)
        sys.exit(1)
    return inventory


def select_documents(
    inventory: dict, object_id: str | None, all_flag: bool, sample: int | None
) -> list[dict]:
    docs = inventory.get("documents", [])

    if object_id:
        matches = [d for d in docs if d["id"] == object_id]
        if not matches:
            print(
                f"ERROR: Object '{object_id}' not found in inventory.", file=sys.stderr
            )
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
    group.add_argument(
        "--object", metavar="ID", help="Transcribe a single document by ID"
    )
    group.add_argument(
        "--all", action="store_true", help="Transcribe all documents in inventory"
    )
    parser.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="Process only first N documents (with --all)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing transcriptions"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List documents without calling API"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Max images per API call (default {CHUNK_SIZE})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=BATCH_DELAY,
        help=f"Seconds between documents (default {BATCH_DELAY})",
    )
    args = parser.parse_args()

    ensure_dirs()
    inventory = load_inventory()
    docs = select_documents(inventory, args.object, args.all, args.sample)
    provider = TRANSCRIPTION_PROVIDER
    model = TRANSCRIPTION_MODEL

    # Fail fast instead of producing empty or partial results without a key.
    if not args.dry_run:
        config_error = provider_config_error(provider, model)
        if config_error:
            print(f"ERROR: {config_error}.", file=sys.stderr)
            sys.exit(1)
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
        err = transcribe_document(
            doc, system_prompt, provider, model, args.chunk_size, args.force
        )
        if err:
            errors.append(err)
            print(f"  FAIL {err['object_id']}: {err['error']}")

        # Rate-limit courtesy delay between documents (not after the last one)
        if i < len(docs) - 1:
            time.sleep(args.delay)

    write_errors(errors, TRANSCRIPTIONS_DIR)
    if errors:
        print(
            f"\n{len(errors)} error(s) written to {TRANSCRIPTIONS_DIR / 'errors.json'}"
        )

    succeeded = len(docs) - len(errors)
    print(f"\nDone. {succeeded}/{len(docs)} document(s) transcribed successfully.")

    # A document that could not be processed is a failed run, not a result.
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
