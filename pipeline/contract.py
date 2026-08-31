"""Runtime checks for the pipeline data contract (knowledge/08_DATA_CONTRACT.md).

The contract binds steps 3 to 6: object_id and pages at the top level, a
provenance block under _meta, and per page an integer page number from 1 and
a transcription string. These functions are the single source for those field
rules. Step 3 gates the model answer with response_violations before writing,
and the contract tests check finished files with file_violations, so a rule
change lands in one place instead of two.

Both functions return a list of human-readable problems and an empty list
when the input conforms; they never raise, so a caller can decide whether a
violation is a skipped item or a hard stop.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

REQUIRED_TOP_LEVEL = ("object_id", "pages")
REQUIRED_META = ("script", "timestamp")
REVIEW_STATUSES = frozenset(
    {
        "machine_unreviewed",
        "in_review",
        "human_verified",
        "accepted",
    }
)
REVIEW_TRANSITIONS = {
    "machine_unreviewed": frozenset({"in_review"}),
    "in_review": frozenset({"machine_unreviewed", "human_verified"}),
    "human_verified": frozenset({"in_review", "accepted"}),
    "accepted": frozenset({"in_review"}),
}
PAGE_TYPES = frozenset({"", "blank", "foreign_text", "gate_low_resolution"})
OBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
QUALITY_COUNT_FIELDS = frozenset(
    {
        "total_chars",
        "blank_pages",
        "undeclared_empty_pages",
        "gate_pages",
        "foreign_pages",
        "content_pages",
    }
)
QUALITY_PAGE_TYPES = PAGE_TYPES | {"content", "undeclared_empty"}
VALIDATION_STATUSES = frozenset({"confident", "needs_review", "problematic"})


def valid_object_id(value: object) -> bool:
    """Return whether an identifier is portable across supported filesystems."""
    if not isinstance(value, str) or not OBJECT_ID.fullmatch(value):
        return False
    if value.endswith("."):
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
    payload = {
        "page": page.get("page"),
        "transcription": page.get("transcription"),
        "notes": page.get("notes", ""),
        "page_type": page.get("page_type", ""),
        "foreign_paragraphs": page.get("foreign_paragraphs", []),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def raw_transcription_state_hash(data: dict) -> str:
    """Bind step-3 provenance to the ordered immutable model text."""
    pages = data.get("pages", [])
    payload = [
        {
            "page": page.get("page"),
            "transcription_raw": page.get("transcription_raw"),
        }
        for page in pages
        if isinstance(page, dict)
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def transcription_state_hash(data: dict) -> str:
    """Bind step-4 findings to the exact transcription state they assessed."""
    payload = {
        "object_id": data.get("object_id"),
        "transcription_meta": data.get("transcription_meta", data.get("_meta")),
        "metadata": data.get("metadata", {}),
        "pages": data.get("pages"),
        "confidence": data.get("confidence", ""),
        "confidence_notes": data.get("confidence_notes", ""),
        "quality_signals": data.get("quality_signals"),
        "source_images": data.get("source_images"),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def validation_result_hash(data: dict) -> str:
    """Bind the automatic status to the exact step-4 findings."""
    payload = {
        "overall_status": data.get("overall_status"),
        "validation": data.get("validation"),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def _is_iso_timestamp(value: object) -> bool:
    """Return whether a value is an ISO-8601 timestamp with a timezone."""
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


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
    if status not in REVIEW_STATUSES:
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
        if event.get("status") not in REVIEW_STATUSES:
            problems.append(f"{event_prefix} has an unknown status")
        if event.get("from_status") != previous_status:
            problems.append(f"{event_prefix} does not continue the status history")
        if event.get("status") not in REVIEW_TRANSITIONS.get(previous_status, ()):
            problems.append(f"{event_prefix} is not an allowed review transition")
        if not isinstance(event.get("actor"), str) or not event["actor"].strip():
            problems.append(f"{event_prefix} has no actor")
        target_status = event.get("status")
        if target_status in {"human_verified", "accepted"}:
            state_hash = event.get("page_state_hash")
            if not isinstance(state_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", state_hash
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
        if event.get("status") in REVIEW_STATUSES:
            previous_status = event["status"]

    if status in REVIEW_STATUSES - {"machine_unreviewed"} and not history:
        problems.append(f"{prefix} status {status} has no transition history")
    if (
        history
        and isinstance(history[-1], dict)
        and history[-1].get("status") != status
    ):
        problems.append(f"{prefix} status does not match its latest history entry")
    if (
        status in {"human_verified", "accepted"}
        and history
        and isinstance(history[-1], dict)
        and history[-1].get("page_state_hash") != review_page_state_hash(page)
    ):
        problems.append(f"{prefix} decision does not match the current page state")
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
    if step is not None and (
        not isinstance(step, int) or isinstance(step, bool) or step < 0
    ):
        problems.append(f"{prefix}.pipeline_step is not a non-negative integer")
    executed = value.get("executed_prompts")
    if executed is not None and not isinstance(executed, list):
        problems.append(f"{prefix}.executed_prompts is not a list")
    image_state = value.get("source_images")
    image_hash = value.get("source_images_hash")
    if image_state is not None:
        valid_state = isinstance(image_state, list) and all(
            isinstance(item, dict)
            and item.get("page") == index
            and isinstance(item.get("filename"), str)
            and Path(item["filename"]).name == item["filename"]
            and isinstance(item.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            for index, item in enumerate(image_state, start=1)
        )
        if not valid_state:
            problems.append(f"{prefix}.source_images is not an ordered byte-state list")
        else:
            serialized = json.dumps(
                image_state,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
            if image_hash != expected_hash:
                problems.append(f"{prefix}.source_images_hash does not match its state")
    elif image_hash is not None:
        problems.append(f"{prefix}.source_images_hash has no source_images state")

    if step == 3:
        for field in ("provider", "model", "prompt_template"):
            if not isinstance(value.get(field), str) or not value[field].strip():
                problems.append(f"{prefix}.{field} is missing for pipeline step 3")
        prompt_hash = value.get("prompt_hash")
        if not isinstance(prompt_hash, str) or not re.fullmatch(
            r"[0-9a-f]{12}", prompt_hash
        ):
            problems.append(f"{prefix}.prompt_hash is not a 12-character hash")
        prompt_layers = value.get("prompt_layers")
        if (
            not isinstance(prompt_layers, list)
            or not prompt_layers
            or prompt_layers[0] != "transcription.md"
            or any(
                not isinstance(layer, str) or not layer.strip()
                for layer in prompt_layers
            )
        ):
            problems.append(
                f"{prefix}.prompt_layers is not a complete ordered layer list"
            )
        prompt_profile = value.get("prompt_profile")
        if prompt_profile is not None and not valid_object_id(prompt_profile):
            problems.append(f"{prefix}.prompt_profile is not a path-safe key")
        elif isinstance(prompt_layers, list):
            profile_layers = [
                layer
                for layer in prompt_layers
                if isinstance(layer, str) and layer.startswith("profiles/")
            ]
            expected_profile = (
                f"profiles/{prompt_profile}.md" if prompt_profile is not None else None
            )
            if profile_layers != ([expected_profile] if expected_profile else []):
                problems.append(f"{prefix}.prompt_layers does not match prompt_profile")
        raw_hash = value.get("raw_transcription_hash")
        if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{12}", raw_hash):
            problems.append(
                f"{prefix}.raw_transcription_hash is not a 12-character hash"
            )
        metadata_hash = value.get("source_metadata_hash")
        if not isinstance(metadata_hash, str) or not re.fullmatch(
            r"[0-9a-f]{12}", metadata_hash
        ):
            problems.append(f"{prefix}.source_metadata_hash is not a 12-character hash")
        valid_calls = (
            isinstance(executed, list)
            and bool(executed)
            and all(
                isinstance(call, dict)
                and isinstance(call.get("chunk"), int)
                and not isinstance(call.get("chunk"), bool)
                and call["chunk"] >= 1
                and isinstance(call.get("pages"), list)
                and bool(call["pages"])
                and all(
                    isinstance(page, int) and not isinstance(page, bool) and page >= 1
                    for page in call["pages"]
                )
                and isinstance(call.get("attempt"), int)
                and not isinstance(call.get("attempt"), bool)
                and call["attempt"] >= 1
                and isinstance(call.get("prompt_hash"), str)
                and bool(re.fullmatch(r"[0-9a-f]{12}", call["prompt_hash"]))
                for call in executed or []
            )
        )
        if not valid_calls:
            problems.append(
                f"{prefix}.executed_prompts is not a complete step-3 call log"
            )
        if not image_state:
            problems.append(f"{prefix}.source_images is missing for pipeline step 3")
    if step == 4:
        provider = value.get("provider", "")
        model = value.get("model", "")
        model_run = bool(provider or model)
        if model_run:
            if not isinstance(provider, str) or not provider.strip():
                problems.append(f"{prefix}.provider is missing for model validation")
            if not isinstance(model, str) or not model.strip():
                problems.append(f"{prefix}.model is missing for model validation")
            if (
                not isinstance(value.get("prompt_template"), str)
                or not value["prompt_template"].strip()
            ):
                problems.append(
                    f"{prefix}.prompt_template is missing for model validation"
                )
            prompt_hash = value.get("prompt_hash")
            if not isinstance(prompt_hash, str) or not re.fullmatch(
                r"[0-9a-f]{12}", prompt_hash
            ):
                problems.append(f"{prefix}.prompt_hash is not a 12-character hash")
            valid_calls = isinstance(executed, list) and all(
                isinstance(call, dict)
                and isinstance(call.get("page"), int)
                and not isinstance(call.get("page"), bool)
                and call["page"] >= 1
                and isinstance(call.get("prompt_hash"), str)
                and bool(re.fullmatch(r"[0-9a-f]{12}", call["prompt_hash"]))
                for call in executed
            )
            if not valid_calls:
                problems.append(
                    f"{prefix}.executed_prompts is not a valid step-4 call log"
                )
        elif any(
            key in value
            for key in ("prompt_template", "prompt_hash", "executed_prompts")
        ):
            problems.append(
                f"{prefix} carries model-validation fields without provider and model"
            )
    return problems


def _quality_signal_violations(value: object, page_count: int | None) -> list[str]:
    """Check optional derived quality signals before consumers use them."""
    if not isinstance(value, dict):
        return ["quality_signals is not an object"]

    problems: list[str] = []
    page_types = value.get("page_types")
    if not isinstance(page_types, list) or any(
        page_type not in QUALITY_PAGE_TYPES for page_type in page_types
    ):
        problems.append("quality_signals.page_types is not a list of known page types")
    elif page_count is not None and len(page_types) != page_count:
        problems.append("quality_signals.page_types count does not match pages")

    for field in QUALITY_COUNT_FIELDS:
        number = value.get(field)
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
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
        number = page.get("page")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            problems.append(f"pages[{index}] has no page number from 1")
        if not isinstance(page.get("transcription"), str):
            problems.append(f"pages[{index}] has no transcription string")
        if "transcription_raw" in page and not isinstance(
            page["transcription_raw"], str
        ):
            problems.append(f"pages[{index}].transcription_raw is not a string")
        if page.get("page_type", "") not in PAGE_TYPES:
            problems.append(f"pages[{index}].page_type has an unknown value")
        if page.get("page_type") == "blank" and page.get("transcription"):
            problems.append(
                f"pages[{index}] declares blank but carries transcription text"
            )
        if "notes" in page and not isinstance(page["notes"], str):
            problems.append(f"pages[{index}].notes is not a string")
        foreign = page.get("foreign_paragraphs", [])
        valid_foreign = (
            isinstance(foreign, list)
            and all(
                isinstance(item, int) and not isinstance(item, bool) and item >= 0
                for item in foreign
            )
            and len(foreign) == len(set(foreign))
        )
        if not valid_foreign:
            problems.append(
                f"pages[{index}].foreign_paragraphs is not a unique list of indices"
            )
        elif foreign:
            text = page.get("transcription", "")
            paragraph_count = (
                len(re.split(r"\n{2,}", text.strip())) if text.strip() else 0
            )
            if any(item >= paragraph_count for item in foreign):
                problems.append(
                    f"pages[{index}].foreign_paragraphs contains an out-of-range index"
                )
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

    for key in (
        "title",
        "signature",
        "date",
        "language",
        "object_type",
        "extent",
        "repository",
    ):
        if key in metadata and not isinstance(metadata[key], str):
            problems.append(f"{prefix}.{key} is not a string")
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

    if "object_id" in data and not valid_object_id(data["object_id"]):
        problems.append("object_id is not a path-safe identifier")

    if "pages" in data:
        problems += page_violations(data["pages"], require_review=True)
        transcription_meta = data.get("transcription_meta")
        origin_meta = (
            transcription_meta if isinstance(transcription_meta, dict) else meta
        )
        model_origin = (
            isinstance(origin_meta, dict)
            and origin_meta.get("pipeline_step") == 3
            and (origin_meta.get("provider") or origin_meta.get("model"))
        )
        if model_origin:
            if data.get("source_images") is None:
                problems.append(
                    "step-3 output has no top-level source_images filenames"
                )
            if origin_meta.get(
                "raw_transcription_hash"
            ) != raw_transcription_state_hash(data):
                problems.append(
                    "step-3 raw transcription hash does not match the model text"
                )
            image_state = origin_meta.get("source_images")
            if isinstance(image_state, list) and len(image_state) != len(data["pages"]):
                problems.append("step-3 source image state count does not match pages")
            calls = origin_meta.get("executed_prompts")
            if isinstance(calls, list):
                first_attempts = [
                    call
                    for call in calls
                    if isinstance(call, dict) and call.get("attempt") == 1
                ]
                chunks = [call.get("chunk") for call in first_attempts]
                covered_pages = [
                    page for call in first_attempts for page in call.get("pages", [])
                ]
                if chunks != list(range(1, len(first_attempts) + 1)):
                    problems.append("step-3 prompt chunks are not consecutive from 1")
                if covered_pages != list(range(1, len(data["pages"]) + 1)):
                    problems.append(
                        "step-3 prompt calls do not cover every page exactly once"
                    )
                for chunk in chunks:
                    chunk_calls = [
                        call
                        for call in calls
                        if isinstance(call, dict) and call.get("chunk") == chunk
                    ]
                    if not chunk_calls:
                        continue
                    attempts = [call.get("attempt") for call in chunk_calls]
                    page_ranges = [call.get("pages") for call in chunk_calls]
                    if attempts != list(range(1, len(chunk_calls) + 1)) or any(
                        pages != page_ranges[0] for pages in page_ranges[1:]
                    ):
                        problems.append(
                            f"step-3 prompt retries for chunk {chunk} are inconsistent"
                        )
        for index, page in enumerate(data["pages"]):
            if not isinstance(page, dict):
                continue
            if model_origin and "transcription_raw" not in page:
                problems.append(f"pages[{index}] has no raw model transcription")
            if (
                "transcription_raw" in page
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
    if confidence is not None and confidence not in {"", "low", "medium", "high"}:
        problems.append("confidence has an unknown value")
    if "confidence_notes" in data and not isinstance(data["confidence_notes"], str):
        problems.append("confidence_notes is not a string")

    page_count = len(data["pages"]) if isinstance(data.get("pages"), list) else None
    if "quality_signals" in data:
        problems += _quality_signal_violations(data["quality_signals"], page_count)

    if "transcription_meta" in data:
        problems += _provenance_violations(
            data["transcription_meta"], "transcription_meta"
        )

    if "overall_status" in data and data["overall_status"] not in VALIDATION_STATUSES:
        problems.append("overall_status has an unknown value")
    if "validation" in data and not isinstance(data["validation"], dict):
        problems.append("validation is not an object")

    source_images = data.get("source_images")
    if source_images is not None:
        if not isinstance(source_images, list) or any(
            not isinstance(filename, str) or Path(filename).name != filename
            for filename in source_images
        ):
            problems.append("source_images is not a list of local filenames")
        elif (
            source_images
            and isinstance(data.get("pages"), list)
            and len(source_images) != len(data["pages"])
        ):
            problems.append("source_images count does not match pages")
        origin_meta = (
            data.get("transcription_meta")
            if isinstance(data.get("transcription_meta"), dict)
            else meta
        )
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
    if data.get("overall_status") not in VALIDATION_STATUSES:
        problems.append("validated input has no known overall_status")
    if not isinstance(data.get("validation"), dict):
        problems.append("validated input has no validation object")
    else:
        validation = data["validation"]
        if not isinstance(validation.get("rules"), list):
            problems.append("validated input validation.rules is not a list")
        page_stats = validation.get("per_page_stats")
        if not isinstance(page_stats, list):
            problems.append("validated input validation.per_page_stats is not a list")
        elif isinstance(data.get("pages"), list) and len(page_stats) != len(
            data["pages"]
        ):
            problems.append(
                "validated input validation.per_page_stats count does not match pages"
            )
        elif isinstance(page_stats, list) and isinstance(data.get("pages"), list):
            for index, (stats, page) in enumerate(
                zip(page_stats, data["pages"], strict=True)
            ):
                if not isinstance(stats, dict) or not isinstance(page, dict):
                    problems.append(
                        f"validated input validation.per_page_stats[{index}] is invalid"
                    )
                    continue
                if stats.get("page") != page.get("page"):
                    problems.append(
                        f"validated input validation.per_page_stats[{index}].page is stale"
                    )
                if stats.get("char_count") != len(page.get("transcription", "")):
                    problems.append(
                        f"validated input validation.per_page_stats[{index}].char_count is stale"
                    )
                text = page.get("transcription", "")
                if stats.get("word_count") != len(text.split()):
                    problems.append(
                        f"validated input validation.per_page_stats[{index}].word_count is stale"
                    )
                expected_lines = text.count("\n") + (1 if text else 0)
                if stats.get("line_count") != expected_lines:
                    problems.append(
                        f"validated input validation.per_page_stats[{index}].line_count is stale"
                    )
        total = validation.get("total_characters")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            problems.append(
                "validated input validation.total_characters is not a non-negative integer"
            )
        elif isinstance(data.get("pages"), list):
            current_total = sum(
                len(page.get("transcription", ""))
                for page in data["pages"]
                if isinstance(page, dict)
            )
            if total != current_total:
                problems.append("validated input validation.total_characters is stale")
        if isinstance(meta, dict) and meta.get("provider"):
            judge = validation.get("llm_judge")
            if not isinstance(judge, list) or len(judge) != len(data.get("pages", [])):
                problems.append(
                    "validated input validation.llm_judge does not cover all pages"
                )
            else:
                judge_pages = [
                    result.get("page") if isinstance(result, dict) else None
                    for result in judge
                ]
                expected_pages = [
                    page.get("page") if isinstance(page, dict) else None
                    for page in data.get("pages", [])
                ]
                if judge_pages != expected_pages:
                    problems.append(
                        "validated input validation.llm_judge page order is stale"
                    )
                executed = meta.get("executed_prompts", [])
                executed_pages = [
                    call.get("page") for call in executed if isinstance(call, dict)
                ]
                called_pages = [
                    page.get("page")
                    for page in data.get("pages", [])
                    if isinstance(page, dict) and page.get("transcription", "").strip()
                ]
                if executed_pages != called_pages:
                    problems.append(
                        "validated input executed prompts do not cover all text pages"
                    )
                call_hashes = {
                    call.get("page"): call.get("prompt_hash")
                    for call in executed
                    if isinstance(call, dict)
                }
                if any(
                    isinstance(result, dict)
                    and result.get("page") in call_hashes
                    and result.get("_prompt_hash") != call_hashes[result["page"]]
                    for result in judge
                ):
                    problems.append(
                        "validated input judge results do not match executed prompts"
                    )
        elif "llm_judge" in validation:
            problems.append(
                "validated input carries an LLM judge without model provenance"
            )
    return problems
