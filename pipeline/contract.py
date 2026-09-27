"""Runtime checks for the pipeline data contract (reference/data-contract.md).

The contract binds steps 3 to 6: object_id and pages at the top level, a
provenance block under _meta, and per page an integer page number from 1 and
a transcription string. This module is the single source for those field
rules. Step 3 gates the model answer with response_violations before writing,
steps 4 to 6 and the review server check files with file_violations and
validated_file_violations, so a rule change lands in one place.

Every *_violations function returns a list of human-readable problems and an
empty list when the input conforms. None of them raises on malformed JSON
shapes, so a caller can decide whether a violation is a skipped item or a
hard stop.

The module also holds the deterministic derivations the checks recompute:
the canonical state hashes, the per-page statistics of step 4 and the
quality signals of step 3. Producer and checker share one definition, and the
review server can recompute quality signals without importing step 3 and its
provider layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

REQUIRED_TOP_LEVEL = ("object_id", "pages")
REQUIRED_META = ("script", "timestamp")
# Ordered from least to most mature; step 5 reports the least mature page.
REVIEW_STATUSES = ("machine_unreviewed", "in_review", "human_verified", "accepted")
REVIEW_TRANSITIONS = {
    "machine_unreviewed": frozenset({"in_review"}),
    "in_review": frozenset({"machine_unreviewed", "human_verified"}),
    "human_verified": frozenset({"in_review", "accepted"}),
    "accepted": frozenset({"in_review"}),
}
HUMAN_DECISIONS = frozenset({"human_verified", "accepted"})
PAGE_TYPES = frozenset({"", "blank", "foreign_text", "gate_low_resolution"})
OBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
# errors.json in every step directory and docs/data/catalog.json share the
# directories of the per-object files; an object with one of these names
# would overwrite them or be overwritten.
PIPELINE_RESERVED_NAMES = frozenset({"errors", "catalog"})
QUALITY_COUNT_FIELDS = (
    "total_chars",
    "blank_pages",
    "undeclared_empty_pages",
    "gate_pages",
    "foreign_pages",
    "content_pages",
)
QUALITY_PAGE_TYPES = PAGE_TYPES | {"content", "undeclared_empty"}
VALIDATION_STATUSES = frozenset({"confident", "needs_review", "problematic"})
CONFIDENCE_VALUES = frozenset({"", "low", "medium", "high"})
METADATA_TEXT_FIELDS = (
    "title",
    "signature",
    "date",
    "language",
    "object_type",
    "extent",
    "repository",
)
# Complement of the XML 1.0 Char production. A page text or a metadata field
# with such a character cannot become TEI, so it is rejected before it is stored.
XML_INVALID_CHAR = re.compile(r"[^\t\n\r\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


def canonical_hash(value: object, length: int | None = 12) -> str:
    """Hash a JSON value by its sorted-key compact UTF-8 serialisation.

    Every stored state hash of the pipeline uses this serialisation, so it
    must stay byte-stable. length=None returns the full SHA-256 hex digest.
    """
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]


def text_hash(text: str, length: int | None = 12) -> str:
    """Hash a text by its UTF-8 bytes; length=None returns the full digest."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]


def _is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(f"[0-9a-f]{{{length}}}", value))


def _is_count(value: object, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_text(value: object) -> bool:
    """Return whether a value is a string with visible content."""
    return isinstance(value, str) and bool(value.strip())


def _is_member(value: object, allowed: frozenset | tuple) -> bool:
    """Check membership without hashing an unhashable JSON value."""
    return isinstance(value, str) and value in allowed


def _transcription(page: object) -> str:
    """The page text, or empty when the page shape is already a violation."""
    if not isinstance(page, dict):
        return ""
    text = page.get("transcription", "")
    return text if isinstance(text, str) else ""


def valid_object_id(value: object) -> bool:
    """Return whether an identifier is portable and free for per-object files."""
    if not isinstance(value, str) or not OBJECT_ID.fullmatch(value):
        return False
    if value.endswith("."):
        return False
    if value.casefold() in PIPELINE_RESERVED_NAMES:
        return False
    return value.split(".", 1)[0].casefold() not in WINDOWS_RESERVED_NAMES


def unique_object_id_violations(values: list[object]) -> list[str]:
    """Return portability and case-insensitive uniqueness violations."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for value in values:
        if not valid_object_id(value):
            problems.append(f"invalid object identifier: {value!r}")
            continue
        assert isinstance(value, str)
        folded = value.casefold()
        previous = seen.get(folded)
        if previous is not None:
            problems.append(
                f"object identifiers are not case-insensitively unique: "
                f"{previous!r} and {value!r}"
            )
        else:
            seen[folded] = value
    return problems


def review_page_state_hash(page: dict) -> str:
    """Bind a human review decision to the complete TEI-relevant page state."""
    return canonical_hash(
        {
            "page": page.get("page"),
            "transcription": page.get("transcription"),
            "notes": page.get("notes", ""),
            "page_type": page.get("page_type", ""),
            "foreign_paragraphs": page.get("foreign_paragraphs", []),
        },
        length=None,
    )


def raw_transcription_state_hash(data: dict) -> str:
    """Bind step-3 provenance to the ordered immutable model text."""
    pages = data.get("pages", [])
    return canonical_hash(
        [
            {
                "page": page.get("page"),
                "transcription_raw": page.get("transcription_raw"),
            }
            for page in (pages if isinstance(pages, list) else [])
            if isinstance(page, dict)
        ]
    )


def transcription_state_hash(data: dict) -> str:
    """Bind step-4 findings to the exact transcription state they assessed."""
    return canonical_hash(
        {
            "object_id": data.get("object_id"),
            "transcription_meta": data.get("transcription_meta", data.get("_meta")),
            "metadata": data.get("metadata", {}),
            "pages": data.get("pages"),
            "confidence": data.get("confidence", ""),
            "confidence_notes": data.get("confidence_notes", ""),
            "quality_signals": data.get("quality_signals"),
            "source_images": data.get("source_images"),
        }
    )


def validation_result_hash(data: dict) -> str:
    """Bind the automatic status to the exact step-4 findings."""
    return canonical_hash(
        {
            "overall_status": data.get("overall_status"),
            "validation": data.get("validation"),
        }
    )


def page_stats(pages: list) -> list[dict]:
    """Per-page character, word and line counts as step 4 records them."""
    stats: list[dict] = []
    for page in pages:
        text = _transcription(page)
        stats.append(
            {
                "char_count": len(text),
                "word_count": len(text.split()),
                "line_count": text.count("\n") + (1 if text else 0),
                "page": page.get("page", 0) if isinstance(page, dict) else 0,
            }
        )
    return stats


def compute_quality_signals(transcription: dict, image_count: int) -> dict:
    """Derive quality signals from the page array (data contract key: transcription).

    A page-level page_type declared by the model (blank, foreign_text,
    gate_low_resolution) takes precedence over the character-count inference.
    Kept deliberately simple for the template; a project can extend it.
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
        total_chars += len(text.strip())

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

    # Images without any transcribed page are a review case, not a result.
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


def _is_iso_timestamp(value: object) -> bool:
    """Return whether a value is an ISO-8601 timestamp with a timezone."""
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def edit_violations(page: dict) -> list[str]:
    """Check the optional edit chain without inventing a pre-existing raw state."""
    edits = page.get("edits", [])
    if not isinstance(edits, list):
        return ["edits is not a list"]
    problems = []
    previous = None
    previous_time = None
    ids = set()
    for edit in edits:
        if not isinstance(edit, dict):
            return ["edit is not an object"]
        try:
            UUID(edit["id"])
            timestamp = datetime.fromisoformat(edit["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("timestamp requires timezone")
            if previous_time is not None and timestamp < previous_time:
                problems.append("edit timestamps are not chronological")
            previous_time = timestamp
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append("edit requires a UUID and timezone-aware timestamp")
        identifier = edit.get("id")
        if not isinstance(identifier, str):
            return [*problems, "edit id is not a string"]
        if identifier in ids:
            problems.append("duplicate edit id")
        ids.add(identifier)
        if not _is_member(edit.get("actor_kind"), ("human", "agent")):
            problems.append("unknown edit actor_kind")
        for key in ("actor", "note"):
            if not _is_text(edit.get(key)):
                problems.append(f"edit {key} is required")
        for key in ("before", "after"):
            value = edit.get(key)
            if not isinstance(value, dict) or set(value) != {"transcription", "notes"}:
                return [*problems, f"edit {key} requires transcription and notes"]
            if not all(isinstance(text, str) for text in value.values()):
                return [*problems, f"edit {key} must contain strings"]
        if previous is not None and edit["before"] != previous:
            problems.append("edit chain is discontinuous")
        if edit["before"] == edit["after"]:
            problems.append("edit does not change the page")
        previous = edit["after"]
    if edits and previous != {
        "transcription": page.get("transcription"),
        "notes": page.get("notes", ""),
    }:
        problems.append("edit chain does not match current page")
    return problems


def _review_violations(
    review: object,
    page_index: int,
    page: dict,
) -> list[str]:
    """Check the human review state and its auditable transition history."""
    prefix = f"pages[{page_index}].review"
    if not isinstance(review, dict):
        return [f"{prefix} is not an object"]

    problems: list[str] = []
    status = review.get("status")
    if not _is_member(status, REVIEW_STATUSES):
        problems.append(f"{prefix} has an unknown status")
    history = review.get("history")
    if not isinstance(history, list):
        problems.append(f"{prefix}.history is not a list")
        return problems

    previous_status = "machine_unreviewed"
    previous_timestamp: datetime | None = None
    for event_index, event in enumerate(history):
        event_prefix = f"{prefix}.history[{event_index}]"
        if not isinstance(event, dict):
            problems.append(f"{event_prefix} is not an object")
            continue
        target_status = event.get("status")
        known_status = _is_member(target_status, REVIEW_STATUSES)
        if not known_status:
            problems.append(f"{event_prefix} has an unknown status")
        if event.get("from_status") != previous_status:
            problems.append(f"{event_prefix} does not continue the status history")
        if not known_status or target_status not in REVIEW_TRANSITIONS[previous_status]:
            problems.append(f"{event_prefix} is not an allowed review transition")
        if not _is_text(event.get("actor")):
            problems.append(f"{event_prefix} has no actor")
        if _is_member(target_status, HUMAN_DECISIONS) and not _is_hex(
            event.get("page_state_hash"), 64
        ):
            problems.append(f"{event_prefix} has no valid page_state_hash")
        timestamp = event.get("timestamp")
        if not _is_iso_timestamp(timestamp):
            problems.append(f"{event_prefix} has no timezone-aware ISO timestamp")
        else:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if previous_timestamp is not None and parsed_timestamp < previous_timestamp:
                problems.append(f"{event_prefix} is earlier than the previous event")
            previous_timestamp = parsed_timestamp
        if known_status:
            previous_status = target_status

    if _is_member(status, REVIEW_STATUSES[1:]) and not history:
        problems.append(f"{prefix} status {status} has no transition history")
    latest = history[-1] if history and isinstance(history[-1], dict) else None
    if latest is not None and latest.get("status") != status:
        problems.append(f"{prefix} status does not match its latest history entry")
    if (
        _is_member(status, HUMAN_DECISIONS)
        and latest is not None
        and latest.get("page_state_hash") != review_page_state_hash(page)
    ):
        problems.append(f"{prefix} decision does not match the current page state")
    return problems


def _source_image_state_violations(value: dict, prefix: str) -> list[str]:
    """Check the ordered facsimile byte state and its bound hash."""
    image_state = value.get("source_images")
    image_hash = value.get("source_images_hash")
    if image_state is None:
        if image_hash is not None:
            return [f"{prefix}.source_images_hash has no source_images state"]
        return []
    valid_state = isinstance(image_state, list) and all(
        isinstance(item, dict)
        and item.get("page") == index
        and isinstance(item.get("filename"), str)
        and Path(item["filename"]).name == item["filename"]
        and _is_hex(item.get("sha256"), 64)
        for index, item in enumerate(image_state, start=1)
    )
    if not valid_state:
        return [f"{prefix}.source_images is not an ordered byte-state list"]
    if image_hash != canonical_hash(image_state):
        return [f"{prefix}.source_images_hash does not match its state"]
    return []


def _step3_violations(value: dict, prefix: str) -> list[str]:
    """Check the provenance fields a step-3 model run must record."""
    problems: list[str] = []
    for field in ("provider", "model", "prompt_template"):
        if not _is_text(value.get(field)):
            problems.append(f"{prefix}.{field} is missing for pipeline step 3")
    if not _is_hex(value.get("prompt_hash"), 12):
        problems.append(f"{prefix}.prompt_hash is not a 12-character hash")
    prompt_layers = value.get("prompt_layers")
    if (
        not isinstance(prompt_layers, list)
        or not prompt_layers
        or prompt_layers[0] != "transcription.md"
        or not all(_is_text(layer) for layer in prompt_layers)
    ):
        problems.append(f"{prefix}.prompt_layers is not a complete ordered layer list")
    prompt_profile = value.get("prompt_profile")
    if prompt_profile is not None and not valid_object_id(prompt_profile):
        problems.append(f"{prefix}.prompt_profile is not a path-safe key")
    elif isinstance(prompt_layers, list):
        profile_layers = [
            layer
            for layer in prompt_layers
            if isinstance(layer, str) and layer.startswith("profiles/")
        ]
        expected = [f"profiles/{prompt_profile}.md"] if prompt_profile else []
        if profile_layers != expected:
            problems.append(f"{prefix}.prompt_layers does not match prompt_profile")
    if not _is_hex(value.get("raw_transcription_hash"), 12):
        problems.append(f"{prefix}.raw_transcription_hash is not a 12-character hash")
    if not _is_hex(value.get("source_metadata_hash"), 12):
        problems.append(f"{prefix}.source_metadata_hash is not a 12-character hash")
    executed = value.get("executed_prompts")
    valid_calls = (
        isinstance(executed, list)
        and bool(executed)
        and all(
            isinstance(call, dict)
            and _is_count(call.get("chunk"), 1)
            and isinstance(call.get("pages"), list)
            and bool(call["pages"])
            and all(_is_count(page, 1) for page in call["pages"])
            and _is_count(call.get("attempt"), 1)
            and _is_hex(call.get("prompt_hash"), 12)
            for call in executed
        )
    )
    if not valid_calls:
        problems.append(f"{prefix}.executed_prompts is not a complete step-3 call log")
    if not value.get("source_images"):
        problems.append(f"{prefix}.source_images is missing for pipeline step 3")
    return problems


def _step4_violations(value: dict, prefix: str) -> list[str]:
    """Check that model-validation fields appear together or not at all."""
    provider = value.get("provider", "")
    model = value.get("model", "")
    if not (provider or model):
        if any(
            key in value
            for key in ("prompt_template", "prompt_hash", "executed_prompts")
        ):
            return [
                f"{prefix} carries model-validation fields without provider and model"
            ]
        return []
    problems: list[str] = []
    if not _is_text(provider):
        problems.append(f"{prefix}.provider is missing for model validation")
    if not _is_text(model):
        problems.append(f"{prefix}.model is missing for model validation")
    if not _is_text(value.get("prompt_template")):
        problems.append(f"{prefix}.prompt_template is missing for model validation")
    if not _is_hex(value.get("prompt_hash"), 12):
        problems.append(f"{prefix}.prompt_hash is not a 12-character hash")
    executed = value.get("executed_prompts")
    valid_calls = isinstance(executed, list) and all(
        isinstance(call, dict)
        and _is_count(call.get("page"), 1)
        and _is_hex(call.get("prompt_hash"), 12)
        for call in executed
    )
    if not valid_calls:
        problems.append(f"{prefix}.executed_prompts is not a valid step-4 call log")
    return problems


def _provenance_violations(value: object, prefix: str) -> list[str]:
    """Check a provenance object that crosses a pipeline-step boundary."""
    if not isinstance(value, dict):
        return [f"{prefix} is not a provenance object"]

    problems = [
        f"{prefix} is missing {key}" for key in REQUIRED_META if not value.get(key)
    ]
    if value.get("timestamp") and not _is_iso_timestamp(value["timestamp"]):
        problems.append(f"{prefix}.timestamp is not a timezone-aware ISO timestamp")
    step = value.get("pipeline_step")
    if step is not None and not _is_count(step):
        problems.append(f"{prefix}.pipeline_step is not a non-negative integer")
    executed = value.get("executed_prompts")
    if executed is not None and not isinstance(executed, list):
        problems.append(f"{prefix}.executed_prompts is not a list")
    problems += _source_image_state_violations(value, prefix)
    if step == 3:
        problems += _step3_violations(value, prefix)
    if step == 4:
        problems += _step4_violations(value, prefix)
    return problems


def _quality_signal_violations(value: object, page_count: int | None) -> list[str]:
    """Check optional derived quality signals before consumers use them."""
    if not isinstance(value, dict):
        return ["quality_signals is not an object"]

    problems: list[str] = []
    page_types = value.get("page_types")
    if not isinstance(page_types, list) or not all(
        _is_member(page_type, QUALITY_PAGE_TYPES) for page_type in page_types
    ):
        problems.append("quality_signals.page_types is not a list of known page types")
    elif page_count is not None and len(page_types) != page_count:
        problems.append("quality_signals.page_types count does not match pages")

    for field in QUALITY_COUNT_FIELDS:
        if not _is_count(value.get(field)):
            problems.append(f"quality_signals.{field} is not a non-negative integer")

    average = value.get("chars_per_page")
    if (
        not isinstance(average, (int, float))
        or isinstance(average, bool)
        or average < 0
    ):
        problems.append("quality_signals.chars_per_page is not a non-negative number")
    if not isinstance(value.get("needs_review"), bool):
        problems.append("quality_signals.needs_review is not a boolean")
    return problems


def _page_text_violations(page: dict, index: int) -> list[str]:
    """Check the string fields of one page that become TEI text."""
    problems: list[str] = []
    text = page.get("transcription")
    if not isinstance(text, str):
        problems.append(f"pages[{index}] has no transcription string")
    elif XML_INVALID_CHAR.search(text):
        problems.append(
            f"pages[{index}].transcription contains a character not allowed in XML"
        )
    if "notes" in page:
        notes = page["notes"]
        if not isinstance(notes, str):
            problems.append(f"pages[{index}].notes is not a string")
        elif XML_INVALID_CHAR.search(notes):
            problems.append(
                f"pages[{index}].notes contains a character not allowed in XML"
            )
    if "transcription_raw" in page and not isinstance(page["transcription_raw"], str):
        problems.append(f"pages[{index}].transcription_raw is not a string")
    return problems


def _foreign_paragraph_violations(page: dict, index: int) -> list[str]:
    """Check that excluded paragraph indices exist on the page."""
    foreign = page.get("foreign_paragraphs", [])
    if (
        not isinstance(foreign, list)
        or not all(_is_count(item) for item in foreign)
        or len(foreign) != len(set(foreign))
    ):
        return [f"pages[{index}].foreign_paragraphs is not a unique list of indices"]
    text = _transcription(page).strip()
    paragraph_count = len(re.split(r"\n{2,}", text)) if text else 0
    if any(item >= paragraph_count for item in foreign):
        return [f"pages[{index}].foreign_paragraphs contains an out-of-range index"]
    return []


def page_violations(
    pages: object,
    expected_numbers: list[int] | None = None,
    require_review: bool = False,
) -> list[str]:
    """Check the page array against the contract's mandatory page fields."""
    if not isinstance(pages, list):
        return ["pages is not a list"]
    if not pages:
        return ["pages is empty"]

    problems: list[str] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            problems.append(f"pages[{index}] is not an object")
            continue
        problems.extend(
            f"pages[{index}]: {problem}" for problem in edit_violations(page)
        )
        if not _is_count(page.get("page"), 1):
            problems.append(f"pages[{index}] has no page number from 1")
        problems += _page_text_violations(page, index)
        if not _is_member(page.get("page_type", ""), PAGE_TYPES):
            problems.append(f"pages[{index}].page_type has an unknown value")
        if page.get("page_type") == "blank" and page.get("transcription"):
            problems.append(
                f"pages[{index}] declares blank but carries transcription text"
            )
        problems += _foreign_paragraph_violations(page, index)
        review = page.get("review")
        if review is not None:
            problems.extend(_review_violations(review, index, page))
        elif require_review:
            problems.append(f"pages[{index}] has no human review state")

    expected = (
        expected_numbers
        if expected_numbers is not None
        else list(range(1, len(pages) + 1))
    )
    actual = [page.get("page") if isinstance(page, dict) else None for page in pages]
    if actual != expected:
        problems.append(f"page numbers are {actual}; expected {expected}")
    return problems


def response_violations(
    response: object,
    expected_pages: int | None = None,
    expected_numbers: list[int] | None = None,
) -> list[str]:
    """Check a model answer before step 3 writes it to disk.

    An answer without a usable pages/transcription structure is an error of
    the object, because writing it would produce a file that claims an empty
    but reviewed transcription.
    """
    if not isinstance(response, dict):
        return ["model response is not a JSON object"]
    pages = response.get("pages")
    if not isinstance(pages, list):
        return ["model response carries no pages array"]
    if not pages:
        return ["model response carries an empty pages array"]
    if expected_numbers is None and expected_pages is not None:
        expected_numbers = list(range(1, expected_pages + 1))
    problems = page_violations(pages, expected_numbers=expected_numbers)
    for index, page in enumerate(pages):
        if isinstance(page, dict) and any(
            key in page for key in ("review", "edits", "transcription_raw")
        ):
            problems.append(
                f"model pages[{index}] carries reserved review or raw-text fields"
            )
    if expected_pages is not None and len(pages) != expected_pages:
        problems.append(
            f"model response carries {len(pages)} pages for {expected_pages} source images"
        )
    return problems


def metadata_violations(metadata: object, prefix: str = "metadata") -> list[str]:
    """Check object metadata before it reaches prompts or renderers."""
    if not isinstance(metadata, dict):
        return [f"{prefix} is not an object"]

    problems: list[str] = []
    if "image_urls" in metadata:
        urls = metadata["image_urls"]
        if isinstance(urls, dict):
            expected_keys = [str(number) for number in range(1, len(urls) + 1)]
            if (
                sorted(
                    urls,
                    key=lambda key: int(key) if key.isdigit() else -1,
                )
                != expected_keys
            ):
                problems.append(f"{prefix}.image_urls keys are not consecutive from 1")
            values = list(urls.values())
        elif isinstance(urls, list):
            values = urls
        else:
            values = []
            problems.append(f"{prefix}.image_urls is not an object or list")
        if any(
            not isinstance(value, str) or not value.startswith(("http://", "https://"))
            for value in values
        ):
            problems.append(f"{prefix}.image_urls contains an invalid URL")

    for key in METADATA_TEXT_FIELDS:
        if key not in metadata:
            continue
        if not isinstance(metadata[key], str):
            problems.append(f"{prefix}.{key} is not a string")
        elif XML_INVALID_CHAR.search(metadata[key]):
            problems.append(f"{prefix}.{key} contains a character not allowed in XML")
    return problems


def _step3_call_log_violations(calls: list, page_count: int) -> list[str]:
    """Check that first attempts cover every page once and retries repeat them."""
    problems: list[str] = []
    first_attempts = [
        call for call in calls if isinstance(call, dict) and call.get("attempt") == 1
    ]
    chunks = [call.get("chunk") for call in first_attempts]
    covered_pages = [
        page
        for call in first_attempts
        if isinstance(call.get("pages"), list)
        for page in call["pages"]
    ]
    if chunks != list(range(1, len(first_attempts) + 1)):
        problems.append("step-3 prompt chunks are not consecutive from 1")
    if covered_pages != list(range(1, page_count + 1)):
        problems.append("step-3 prompt calls do not cover every page exactly once")
    for chunk in chunks:
        chunk_calls = [
            call
            for call in calls
            if isinstance(call, dict) and call.get("chunk") == chunk
        ]
        attempts = [call.get("attempt") for call in chunk_calls]
        page_ranges = [call.get("pages") for call in chunk_calls]
        if attempts != list(range(1, len(chunk_calls) + 1)) or any(
            pages != page_ranges[0] for pages in page_ranges[1:]
        ):
            problems.append(f"step-3 prompt retries for chunk {chunk} are inconsistent")
    return problems


def _model_origin_violations(data: dict, origin_meta: dict, pages: list) -> list[str]:
    """Check what a step-3 model run must leave in the finished file."""
    problems: list[str] = []
    if data.get("source_images") is None:
        problems.append("step-3 output has no top-level source_images filenames")
    if origin_meta.get("raw_transcription_hash") != raw_transcription_state_hash(data):
        problems.append("step-3 raw transcription hash does not match the model text")
    image_state = origin_meta.get("source_images")
    if isinstance(image_state, list) and len(image_state) != len(pages):
        problems.append("step-3 source image state count does not match pages")
    calls = origin_meta.get("executed_prompts")
    if isinstance(calls, list):
        problems += _step3_call_log_violations(calls, len(pages))
    for index, page in enumerate(pages):
        if isinstance(page, dict) and "transcription_raw" not in page:
            problems.append(f"pages[{index}] has no raw model transcription")
    return problems


def _source_image_name_violations(
    source_images: object, pages: object, origin_meta: object
) -> list[str]:
    """Check the top-level facsimile filenames against pages and bound state."""
    problems: list[str] = []
    if not isinstance(source_images, list) or any(
        not isinstance(filename, str) or Path(filename).name != filename
        for filename in source_images
    ):
        problems.append("source_images is not a list of local filenames")
    elif source_images and isinstance(pages, list) and len(source_images) != len(pages):
        problems.append("source_images count does not match pages")
    origin_state = (
        origin_meta.get("source_images") if isinstance(origin_meta, dict) else None
    )
    if isinstance(source_images, list) and isinstance(origin_state, list):
        bound_names = [
            item.get("filename") if isinstance(item, dict) else None
            for item in origin_state
        ]
        if source_images != bound_names:
            problems.append(
                "source_images filenames do not match the bound source image state"
            )
    return problems


def file_violations(data: object) -> list[str]:
    """Check a complete transcription or validation file against the contract."""
    if not isinstance(data, dict):
        return ["file content is not a JSON object"]

    problems = [
        f"missing top-level key: {key}" for key in REQUIRED_TOP_LEVEL if key not in data
    ]

    meta = data.get("_meta")
    if meta is None:
        problems.append("missing provenance block: _meta")
    else:
        problems += _provenance_violations(meta, "_meta")
    # A step-4 file carries the step-3 provenance under transcription_meta.
    transcription_meta = data.get("transcription_meta")
    origin_meta = transcription_meta if isinstance(transcription_meta, dict) else meta

    if "object_id" in data and not valid_object_id(data["object_id"]):
        problems.append("object_id is not a path-safe identifier")

    pages = data.get("pages")
    if "pages" in data:
        problems += page_violations(pages, require_review=True)
    if isinstance(pages, list):
        model_origin = (
            isinstance(origin_meta, dict)
            and origin_meta.get("pipeline_step") == 3
            and (origin_meta.get("provider") or origin_meta.get("model"))
        )
        if model_origin:
            problems += _model_origin_violations(data, origin_meta, pages)
        for index, page in enumerate(pages):
            if (
                isinstance(page, dict)
                and "transcription_raw" in page
                and isinstance(page.get("review"), dict)
                and page["review"].get("status") == "machine_unreviewed"
                and not page["review"].get("history")
                and page["transcription_raw"] != page.get("transcription")
            ):
                problems.append(
                    f"pages[{index}] changed before a human review transition"
                )

    metadata = data.get("metadata")
    if metadata is not None:
        problems += metadata_violations(metadata)

    confidence = data.get("confidence")
    if confidence is not None and not _is_member(confidence, CONFIDENCE_VALUES):
        problems.append("confidence has an unknown value")
    if "confidence_notes" in data and not isinstance(data["confidence_notes"], str):
        problems.append("confidence_notes is not a string")

    page_count = len(pages) if isinstance(pages, list) else None
    if "quality_signals" in data:
        problems += _quality_signal_violations(data["quality_signals"], page_count)

    if "transcription_meta" in data:
        problems += _provenance_violations(transcription_meta, "transcription_meta")

    if "overall_status" in data and not _is_member(
        data["overall_status"], VALIDATION_STATUSES
    ):
        problems.append("overall_status has an unknown value")
    if "validation" in data and not isinstance(data["validation"], dict):
        problems.append("validation is not an object")

    if data.get("source_images") is not None:
        problems += _source_image_name_violations(
            data["source_images"], pages, origin_meta
        )

    return problems


def _page_stat_violations(stats: object, pages: list) -> list[str]:
    """Check that recorded per-page statistics describe the current text."""
    prefix = "validated input validation.per_page_stats"
    if not isinstance(stats, list):
        return [f"{prefix} is not a list"]
    if len(stats) != len(pages):
        return [f"{prefix} count does not match pages"]
    problems: list[str] = []
    for index, (recorded, page) in enumerate(zip(stats, pages, strict=True)):
        if not isinstance(recorded, dict) or not isinstance(page, dict):
            problems.append(f"{prefix}[{index}] is invalid")
            continue
        expected = page_stats([page])[0]
        expected["page"] = page.get("page")
        for field in ("page", "char_count", "word_count", "line_count"):
            if recorded.get(field) != expected[field]:
                problems.append(f"{prefix}[{index}].{field} is stale")
    return problems


def _judge_violations(validation: dict, meta: dict, pages: list) -> list[str]:
    """Check that the LLM judge results cover the current text pages."""
    judge = validation.get("llm_judge")
    if not isinstance(judge, list) or len(judge) != len(pages):
        return ["validated input validation.llm_judge does not cover all pages"]
    problems: list[str] = []
    judge_pages = [
        result.get("page") if isinstance(result, dict) else None for result in judge
    ]
    if judge_pages != [
        page.get("page") if isinstance(page, dict) else None for page in pages
    ]:
        problems.append("validated input validation.llm_judge page order is stale")
    executed = meta.get("executed_prompts", [])
    calls = (
        [call for call in executed if isinstance(call, dict)]
        if isinstance(executed, list)
        else []
    )
    called_pages = [
        page.get("page")
        for page in pages
        if isinstance(page, dict) and _transcription(page).strip()
    ]
    if [call.get("page") for call in calls] != called_pages:
        problems.append("validated input executed prompts do not cover all text pages")
    call_hashes = {
        call["page"]: call.get("prompt_hash")
        for call in calls
        if _is_count(call.get("page"))
    }
    if any(
        isinstance(result, dict)
        and _is_count(result.get("page"))
        and result["page"] in call_hashes
        and result.get("_prompt_hash") != call_hashes[result["page"]]
        for result in judge
    ):
        problems.append("validated input judge results do not match executed prompts")
    return problems


def validated_file_violations(data: object) -> list[str]:
    """Check the stricter step-4 output required before TEI generation."""
    problems = file_violations(data)
    if not isinstance(data, dict):
        return problems

    meta = data.get("_meta")
    if not isinstance(meta, dict) or meta.get("pipeline_step") != 4:
        problems.append("validated input _meta.pipeline_step is not 4")
    elif meta.get("input_state_hash") != transcription_state_hash(data):
        problems.append("validated input state hash does not match the transcription")
    if isinstance(meta, dict) and meta.get(
        "validation_result_hash"
    ) != validation_result_hash(data):
        problems.append("validated result hash does not match the validation findings")
    if "transcription_meta" not in data:
        problems.append("validated input has no transcription_meta provenance")
    if not _is_member(data.get("overall_status"), VALIDATION_STATUSES):
        problems.append("validated input has no known overall_status")
    validation = data.get("validation")
    if not isinstance(validation, dict):
        problems.append("validated input has no validation object")
        return problems

    pages = data.get("pages")
    if not isinstance(validation.get("rules"), list):
        problems.append("validated input validation.rules is not a list")
    if isinstance(pages, list):
        problems += _page_stat_violations(validation.get("per_page_stats"), pages)
    elif not isinstance(validation.get("per_page_stats"), list):
        problems.append("validated input validation.per_page_stats is not a list")
    total = validation.get("total_characters")
    if not _is_count(total):
        problems.append(
            "validated input validation.total_characters is not a non-negative integer"
        )
    elif isinstance(pages, list) and total != sum(
        len(_transcription(page)) for page in pages
    ):
        problems.append("validated input validation.total_characters is stale")
    if isinstance(meta, dict) and meta.get("provider"):
        problems += _judge_violations(
            validation, meta, pages if isinstance(pages, list) else []
        )
    elif "llm_judge" in validation:
        problems.append("validated input carries an LLM judge without model provenance")
    return problems
