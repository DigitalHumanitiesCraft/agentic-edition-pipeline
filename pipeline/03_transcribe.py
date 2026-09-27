"""Transcribe document images via an LLM provider (step 3).

Flat script-pipeline regime. Reads data/inventory.json, resolves each
document's page images through config.ordered_page_images, assembles the
layered prompt (base rules, optional material profile, inventory metadata,
optional per-object instructions) and writes
data/processed/transcriptions/{id}.json according to
knowledge/08_DATA_CONTRACT.md.

Every document runs through the same chunk loop, also when it fits into one
chunk. A chunk is served from a verified chunk-cache entry or sent to the
provider; an unparseable answer gets one retry with a JSON hint, a truncated
answer gets none, because a second call would be cut off at the same limit.
Each chunk answer must satisfy the contract for exactly its page range
before it is cached, and the chunks are always merged, so confidence and
notes follow one rule regardless of the chunk count. The assembled file is
checked once more against the full contract before it is written. Its
metadata is the authoritative inventory metadata alone: the prompt asks the
model for none, and a model-proposed title would otherwise reach the TEI
title unmarked.

Helpers raise config.ItemFailure(stage, message); transcribe_document turns
it into the error record, and main collects the records through finish_run.
Call records land in data/processed/llm-calls/{id}/ and verified chunks in
data/processed/chunk-cache/{id}/ (knowledge/provider-records.md).

Usage:
    uv run python pipeline/03_transcribe.py --object ID [--force]
    uv run python pipeline/03_transcribe.py --all --sample 2 [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import contract
from call_records import recording
from config import (
    BATCH_DELAY,
    CHUNK_CACHE_DIR,
    CHUNK_SIZE,
    INVENTORY_PATH,
    LLM_CALLS_DIR,
    PROMPTS_DIR,
    TEMPERATURE,
    TRANSCRIPTION_MODEL,
    TRANSCRIPTION_PROVIDER,
    TRANSCRIPTIONS_DIR,
    ItemFailure,
    add_selection_args,
    configure_console,
    ensure_dirs,
    finish_run,
    load_prompt,
    ordered_page_images,
    provenance_meta,
    read_json,
    redact_secrets,
    require_provider,
    select_ids,
    source_image_state,
    source_image_state_hash,
    write_json_atomic,
)
from contract import compute_quality_signals
from llm import TruncatedResponseError, call_llm, parse_json_response

PROMPT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CACHE_VERSION = 1
JSON_RETRY_SUFFIX = "\n\nIMPORTANT: Respond with valid JSON only."
# Contract vocabulary of the confidence field, weakest first. A merge across
# chunks keeps the weakest declared value, because a document is only as
# reliable as its worst chunk.
CONFIDENCE_ORDER = ("low", "medium", "high")


@dataclass(frozen=True)
class PreparedDocument:
    """Everything a document run needs once its inputs have passed the checks."""

    doc_id: str
    metadata: dict
    images: list[Path]
    image_state: list[dict]
    prompt: str
    prompt_info: dict


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


def _processed_path(directory: Path, doc_id: str) -> Path:
    """Return the per-object folder of directory beside the transcriptions.

    executed_prompts[].record is relative to the processed root, so the chunk
    cache and the call records follow TRANSCRIPTIONS_DIR's parent and stay
    together with the transcriptions when that directory is redirected.
    """
    return TRANSCRIPTIONS_DIR.parent / directory.name / doc_id


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


def _prompt_component(value: object, field: str) -> str:
    """Return a path-safe prompt key or raise at the prompt trust boundary."""
    if not isinstance(value, str) or not PROMPT_KEY.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def assemble_prompt(doc: dict, base_prompt: str) -> tuple[str, dict]:
    """Build the runtime prompt from profile, metadata and object layers.

    The manifest selects a profile explicitly. A declared profile without
    its own file fails the document instead of silently falling back to the
    base prompt; profiles/README.md documents the folder and is no profile.
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
        if profile.casefold() == "readme":
            raise ValueError(
                "prompt_profile 'README' names the profile folder's documentation"
            )
        if not profile_path.is_file():
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
    info = {"prompt_layers": layers, "prompt_hash": contract.text_hash(prompt)}
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


def _prepare(doc: dict, base_prompt: str) -> PreparedDocument:
    """Check the inventory record, find its images and assemble its prompt."""
    doc_id = doc.get("id")
    if not contract.valid_object_id(doc_id):
        raise ItemFailure(
            "contract", "inventory object_id is not a path-safe identifier"
        )
    metadata = doc.get("metadata", {})
    problems = contract.metadata_violations(metadata, prefix="inventory metadata")
    if problems:
        raise ItemFailure(
            "contract", "Input violates the data contract: " + "; ".join(problems)
        )
    try:
        images = find_images_for_document(doc)
        image_state = source_image_state(images)
    except (OSError, ValueError) as exc:
        raise ItemFailure("discovery", str(exc)) from exc
    if not images:
        raise ItemFailure("discovery", "No images found")
    try:
        prompt, prompt_info = assemble_prompt(doc, base_prompt)
    except (OSError, ValueError) as exc:
        raise ItemFailure("prompt", str(exc)) from exc
    return PreparedDocument(doc_id, metadata, images, image_state, prompt, prompt_info)


def _existing_output_is_current(
    out_path: Path,
    prepared: PreparedDocument,
    provider: str,
    model: str,
    force: bool,
) -> bool:
    """Decide what an existing transcription allows before any provider call.

    Returns True when a non-forced run can keep it, False when there is none
    or --force may replace it. Raises ItemFailure when it is unreadable,
    stale, or carries human review history that --force would destroy.
    """
    if not out_path.exists():
        return False
    try:
        existing = read_json(out_path)
    except (OSError, ValueError) as exc:
        raise ItemFailure(
            "stale",
            f"Existing transcription is unreadable: {exc}; retain and repair or "
            "rename it before starting a new model run",
        ) from exc
    problems = contract.file_violations(existing)
    if force:
        if problems:
            raise ItemFailure(
                "stale",
                "Refusing --force because the existing transcription is not "
                "contract-conformant; retain and repair or rename it",
            )
        if _has_review_history(existing):
            raise ItemFailure(
                "review_history",
                "Refusing --force because the existing transcription contains "
                "human review history; retain it and use a new object identifier "
                "for a new model run",
            )
        return False
    meta = existing.get("_meta", {}) if isinstance(existing, dict) else {}
    info = prepared.prompt_info
    current = (
        not problems
        and existing.get("object_id") == prepared.doc_id
        and meta.get("pipeline_step") == 3
        and meta.get("provider") == provider
        and meta.get("model") == model
        and meta.get("prompt_hash") == info["prompt_hash"]
        and meta.get("prompt_layers") == info["prompt_layers"]
        and meta.get("prompt_profile") == info.get("prompt_profile")
        and meta.get("source_images_hash")
        == source_image_state_hash(prepared.image_state)
        and meta.get("source_metadata_hash")
        == contract.canonical_hash(prepared.metadata)
    )
    if current:
        return True
    raise ItemFailure(
        "stale", "Existing transcription is stale or invalid; rerun with --force"
    )


def transcribe_chunk(
    images: list[Path],
    system_prompt: str,
    provider: str,
    model: str,
    doc_id: str,
    chunk_index: int,
    start_page: int,
    provider_calls: list[dict] | None = None,
) -> tuple[dict | list | None, list[dict]]:
    """Call the provider for one chunk and log every executed prompt.

    Returns the parsed answer (None when even the JSON retry is unparseable)
    and the call entries for _meta.executed_prompts. Each call is appended
    to provider_calls before it starts. Provider failures raise ItemFailure
    with stage "api_call", a truncated answer with stage "truncated".
    """
    end_page = start_page + len(images) - 1
    pages = list(range(start_page, end_page + 1))
    full_prompt = (
        f"{system_prompt}\n\nDocument: {doc_id}, chunk {chunk_index + 1}, source "
        f"pages {start_page}-{end_page}. Number the returned pages from {start_page}."
    )
    image_state = source_image_state(images)
    calls: list[dict] = []

    def execute(prompt: str) -> str:
        path = _processed_path(LLM_CALLS_DIR, doc_id) / f"{uuid.uuid4().hex}.json"
        call = {
            "chunk": chunk_index + 1,
            "pages": list(pages),
            "attempt": len(calls) + 1,
            "prompt_hash": contract.text_hash(prompt),
            "record": f"{LLM_CALLS_DIR.name}/{doc_id}/{path.name}",
        }
        calls.append(call)
        if provider_calls is not None:
            provider_calls.append(call)
        metadata = {
            "provider": provider,
            "model": model,
            "temperature": TEMPERATURE,
            "prompt": prompt,
            "images": image_state,
            **call,
        }
        # "from None" keeps the unredacted provider message out of the chain.
        try:
            with recording(path, metadata) as record:
                record["answer"] = call_llm(provider, model, prompt, images)
        except TruncatedResponseError as exc:
            raise ItemFailure(
                "truncated", f"chunk {chunk_index + 1}: {redact_secrets(str(exc))}"
            ) from None
        except Exception as exc:
            raise ItemFailure("api_call", redact_secrets(str(exc))) from None
        return record["answer"]

    result = parse_json_response(execute(full_prompt))
    if result is None:
        result = parse_json_response(execute(full_prompt + JSON_RETRY_SUFFIX))
    return result, calls


def _chunk_violations(result: object, expected: list[int]) -> list[str]:
    """Check one chunk answer against the contract for its page range.

    Beyond contract.response_violations it rejects confidence values outside
    the vocabulary (letter case aside) and non-string notes, so merge_chunks
    never has to drop or guess a value.
    """
    problems = contract.response_violations(
        result, expected_pages=len(expected), expected_numbers=expected
    )
    if not isinstance(result, dict):
        return problems
    confidence = result.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, str)
        or confidence.strip().lower() not in contract.CONFIDENCE_VALUES
    ):
        problems.append(f"confidence has an unknown value: {confidence!r}")
    notes = result.get("confidence_notes")
    if notes is not None and not isinstance(notes, str):
        problems.append("confidence_notes is not a string")
    return problems


def _cached_chunk(
    prepared: PreparedDocument,
    chunk_images: list[Path],
    index: int,
    start: int,
    provider: str,
    model: str,
    force: bool,
    provider_calls: list[dict] | None,
) -> tuple[dict, list[dict]]:
    """Return one verified chunk answer from the cache or from a provider call.

    The cache identity binds prompt, metadata, provider, model, temperature,
    image bytes and page range. An unreadable or contradictory entry blocks
    the document (stage "cache") rather than triggering a paid call.
    """
    expected = list(range(start, start + len(chunk_images)))
    identity = {
        "cache_version": CACHE_VERSION,
        "provider": provider,
        "model": model,
        "temperature": TEMPERATURE,
        "prompt": prepared.prompt,
        "metadata": prepared.metadata,
        "images": source_image_state(chunk_images),
        "object_id": prepared.doc_id,
        "chunk": index,
        "start": start,
    }
    path = (
        _processed_path(CHUNK_CACHE_DIR, prepared.doc_id)
        / f"{contract.canonical_hash(identity, length=None)}.json"
    )
    if path.exists() and not force:
        try:
            cached = read_json(path)
        except (OSError, ValueError) as exc:
            raise ItemFailure(
                "cache", f"{exc}; retain the chunk cache and rerun with --force"
            ) from exc
        content = cached.get("content") if isinstance(cached, dict) else None
        if (
            not isinstance(content, dict)
            or cached.get("identity") != identity
            or cached.get("sha256") != contract.canonical_hash(content, length=None)
            or not isinstance(content.get("calls"), list)
            or _chunk_violations(content.get("result"), expected)
        ):
            raise ItemFailure(
                "cache", f"Invalid chunk cache {path}; retain it and rerun with --force"
            )
        return content["result"], content["calls"]

    result, calls = transcribe_chunk(
        chunk_images,
        prepared.prompt,
        provider,
        model,
        prepared.doc_id,
        index,
        start,
        provider_calls=provider_calls,
    )
    if result is None:
        raise ItemFailure(
            "parse", f"JSON parse failed for chunk {index + 1} after retry"
        )
    problems = _chunk_violations(result, expected)
    if problems:
        raise ItemFailure(
            "contract",
            f"Chunk {index + 1} violates the data contract: " + "; ".join(problems),
        )
    # Bytes that changed during the call must not be cached under the old
    # identity; _build_output then rejects the whole document.
    if source_image_state(chunk_images) == identity["images"]:
        content = {"result": result, "calls": calls}
        try:
            write_json_atomic(
                path,
                {
                    "_meta": provenance_meta(script="03_transcribe.py", step=3),
                    "identity": identity,
                    "content": content,
                    "sha256": contract.canonical_hash(content, length=None),
                },
            )
        except OSError as exc:
            raise ItemFailure("cache", f"cannot write chunk cache: {exc}") from exc
    return result, calls


def merge_chunks(chunks: list[dict]) -> dict:
    """Merge verified chunk answers into one document answer.

    Page arrays concatenate, the notes of all chunks are kept and confidence
    becomes the weakest declared value in lower case. Model-proposed metadata
    is not taken over.
    """
    pages: list[dict] = []
    notes: list[str] = []
    declared: list[str] = []
    for chunk in chunks:
        pages.extend(chunk["pages"])
        confidence = chunk.get("confidence")
        if isinstance(confidence, str) and confidence.strip():
            declared.append(confidence.strip().lower())
        note = chunk.get("confidence_notes")
        if isinstance(note, str) and note.strip():
            notes.append(note.strip())
    return {
        "pages": pages,
        "confidence": min(declared, key=CONFIDENCE_ORDER.index) if declared else "",
        "confidence_notes": "\n".join(notes),
    }


def _transcribe_chunks(
    prepared: PreparedDocument,
    provider: str,
    model: str,
    chunk_size: int,
    force: bool,
    provider_calls: list[dict] | None,
) -> tuple[dict, list[dict]]:
    """Run every chunk of the document and merge the verified answers."""
    results: list[dict] = []
    executed: list[dict] = []
    for index, offset in enumerate(range(0, len(prepared.images), chunk_size)):
        result, calls = _cached_chunk(
            prepared,
            prepared.images[offset : offset + chunk_size],
            index,
            offset + 1,
            provider,
            model,
            force,
            provider_calls,
        )
        results.append(result)
        executed.extend(calls)
    return merge_chunks(results), executed


def _build_output(
    prepared: PreparedDocument,
    merged: dict,
    executed: list[dict],
    provider: str,
    model: str,
) -> dict:
    """Assemble the contract file and check it once as a whole."""
    try:
        final_state = source_image_state(prepared.images)
    except OSError as exc:
        raise ItemFailure("source_state", str(exc)) from exc
    if final_state != prepared.image_state:
        raise ItemFailure("source_state", "Source images changed during transcription")

    pages = initialize_machine_pages(merged["pages"])
    meta = provenance_meta(
        script="03_transcribe.py",
        provider=provider,
        model=model,
        prompt_template="transcription.md",
        step=3,
    )
    meta.update(prepared.prompt_info)
    meta["executed_prompts"] = executed
    meta["source_images"] = prepared.image_state
    meta["source_images_hash"] = source_image_state_hash(prepared.image_state)
    meta["source_metadata_hash"] = contract.canonical_hash(prepared.metadata)
    meta["raw_transcription_hash"] = contract.raw_transcription_state_hash(
        {"pages": pages}
    )
    output = {
        "_meta": meta,
        "object_id": prepared.doc_id,
        "source_images": [image.name for image in prepared.images],
        "metadata": prepared.metadata,
        "pages": pages,
        "confidence": merged["confidence"],
        "confidence_notes": merged["confidence_notes"],
        "quality_signals": compute_quality_signals(
            {"pages": pages}, len(prepared.images)
        ),
    }
    problems = contract.file_violations(output)
    if problems:
        raise ItemFailure(
            "contract",
            "Assembled transcription violates the data contract: "
            + "; ".join(problems),
        )
    return output


def transcribe_document(
    doc: dict,
    base_prompt: str,
    provider: str,
    model: str,
    chunk_size: int,
    force: bool,
    provider_calls: list[dict] | None = None,
) -> dict | None:
    """Transcribe one document; return its error record, or None on success.

    provider_calls, when given, collects every provider call actually
    started, so the caller can pace only after real calls.
    """
    try:
        prepared = _prepare(doc, base_prompt)
        out_path = TRANSCRIPTIONS_DIR / f"{prepared.doc_id}.json"
        if _existing_output_is_current(out_path, prepared, provider, model, force):
            print(
                f"  SKIP {prepared.doc_id} (transcription matches prompt and source state)"
            )
            return None
        print(f"  Processing {prepared.doc_id} ({len(prepared.images)} page(s)) ...")
        merged, executed = _transcribe_chunks(
            prepared, provider, model, chunk_size, force, provider_calls
        )
        output = _build_output(prepared, merged, executed, provider, model)
        try:
            write_json_atomic(out_path, output)
        except OSError as exc:
            raise ItemFailure("write", str(exc)) from exc
    except ItemFailure as failure:
        return {
            "object_id": str(doc.get("id")),
            "error": failure.message,
            "stage": failure.stage,
        }
    except Exception as exc:
        # A programming error must not pass for a provider failure; the type
        # name and the stage tell the two apart in errors.json.
        return {
            "object_id": str(doc.get("id")),
            "error": redact_secrets(f"{type(exc).__name__}: {exc}"),
            "stage": "internal",
        }

    quality = output["quality_signals"]
    status = "REVIEW" if quality["needs_review"] else "OK"
    print(
        f"  {status} {prepared.doc_id} ({quality['total_chars']} chars, "
        f"{quality['content_pages']}/{len(prepared.images)} content pages)"
    )
    return None


def load_inventory() -> list[dict]:
    """Return the inventory's document records or exit 1 pointing to step 2."""
    try:
        inventory = read_json(INVENTORY_PATH)
    except FileNotFoundError:
        print(
            f"ERROR: {INVENTORY_PATH} not found. Run 02_analyze.py first.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read {INVENTORY_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)
    documents = inventory.get("documents") if isinstance(inventory, dict) else None
    if not isinstance(documents, list) or not all(
        isinstance(doc, dict) for doc in documents
    ):
        print(
            f"ERROR: {INVENTORY_PATH} carries no list of document objects; "
            "rerun 02_analyze.py.",
            file=sys.stderr,
        )
        sys.exit(1)
    return documents


def select_documents(
    documents: list[dict], object_id: str | None, all_flag: bool, sample: int | None
) -> list[dict]:
    """Select inventory records; exit 1 on an invalid or empty selection.

    Records that step 2 marks transcribable: false (text, XML, DOCX or
    transcription sources without page images) are left out and named, so
    --sample counts only documents this step can read.
    """
    excluded = [doc for doc in documents if doc.get("transcribable") is False]
    if object_id is not None and any(doc.get("id") == object_id for doc in excluded):
        print(
            f"ERROR: {object_id} has no page images for step 3 "
            "(inventory marks it transcribable: false).",
            file=sys.stderr,
        )
        sys.exit(1)
    candidates = [doc for doc in documents if doc.get("transcribable") is not False]
    ids = select_ids([doc.get("id") for doc in candidates], object_id, all_flag, sample)
    if all_flag:
        for doc in excluded:
            print(
                f"  SKIP {doc.get('id')} (source_type {doc.get('source_type')!r} "
                "has no page images for step 3)"
            )
    by_id = {doc["id"]: doc for doc in candidates}
    return [by_id[doc_id] for doc_id in ids]


def dry_run(
    docs: list[dict], base_prompt: str, provider: str, model: str, force: bool
) -> None:
    """List what a run would do without provider calls; exit 1 if any would fail."""
    print("DRY RUN, no provider calls:\n")
    blocked = 0
    for doc in docs:
        try:
            prepared = _prepare(doc, base_prompt)
            out_path = TRANSCRIPTIONS_DIR / f"{prepared.doc_id}.json"
            current = _existing_output_is_current(
                out_path, prepared, provider, model, force
            )
        except ItemFailure as failure:
            blocked += 1
            print(f"  [{failure.stage.upper()}] {doc.get('id')}: {failure.message}")
            continue
        status = "CURRENT" if current else "PENDING"
        print(f"  [{status}] {prepared.doc_id}: {len(prepared.images)} image(s)")
    if blocked:
        print(
            f"\n{blocked} of {len(docs)} document(s) would fail with these options.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(description="Transcribe document images via LLM.")
    add_selection_args(parser)
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing transcriptions"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check inputs and existing outputs without calling the provider",
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
        help=f"Seconds after a document that called the provider (default {BATCH_DELAY})",
    )
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error("--chunk-size must be at least 1")
    if args.delay < 0:
        parser.error("--delay must not be negative")

    ensure_dirs()
    docs = select_documents(load_inventory(), args.object, args.all, args.sample)
    provider = TRANSCRIPTION_PROVIDER
    model = TRANSCRIPTION_MODEL
    base_prompt = load_prompt("transcription.md")

    print(f"Transcription: {len(docs)} document(s), provider={provider}, model={model}")
    print(f"Chunk size={args.chunk_size}, delay={args.delay}s\n")
    if args.dry_run:
        dry_run(docs, base_prompt, provider, model, args.force)
        return
    require_provider(provider, model)

    errors: list[dict] = []
    for index, doc in enumerate(docs):
        provider_calls: list[dict] = []
        error = transcribe_document(
            doc,
            base_prompt,
            provider,
            model,
            args.chunk_size,
            args.force,
            provider_calls=provider_calls,
        )
        if error:
            errors.append(error)
        # Rate-limit courtesy, owed only after a real provider call and not
        # after the last document.
        if provider_calls and index < len(docs) - 1:
            time.sleep(args.delay)

    finish_run(
        errors,
        TRANSCRIPTIONS_DIR,
        len(docs),
        "03_transcribe.py",
        summary=f"Done. {len(docs) - len(errors)}/{len(docs)} document(s) transcribed or current.",
    )


if __name__ == "__main__":
    main()
