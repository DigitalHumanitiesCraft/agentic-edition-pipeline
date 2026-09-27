"""Hybrid validation of transcriptions: deterministic rules + optional LLM judge.

Phase 1 runs always and applies fast, rule-based checks (uncertain markers,
illegible markers, OCR artifacts, whitespace anomalies). Phase 2 sends each
page through an LLM judge for deeper assessment -- this only runs when
VALIDATION_PROVIDER is configured and --no-llm is not set. Every judge call
leaves a record under data/processed/llm-calls/{id}/ with provider, model,
temperature, executed prompt and answer, and the output's executed_prompts
point to it.

The two phases feed into a single overall_status per object:
  "confident"    -- no significant issues
  "needs_review" -- minor issues or LLM says "likely"
  "problematic"  -- serious issues or LLM says "uncertain"

An existing output that matches the input state and the judge configuration
is skipped; a stale or unreadable one fails the object until --force
reassesses it, so old findings never pass for the current text.
"""

from __future__ import annotations

import argparse
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import contract
from call_records import recording
from config import (
    LLM_CALLS_DIR,
    TEMPERATURE,
    TRANSCRIPTIONS_DIR,
    VALIDATED_DIR,
    VALIDATION_MODEL,
    VALIDATION_PROVIDER,
    ItemFailure,
    add_selection_args,
    configure_console,
    ensure_dirs,
    finish_run,
    load_checked_json,
    load_prompt,
    provenance_meta,
    read_json,
    redact_secrets,
    require_provider,
    select_ids,
    write_json_atomic,
)
from markers import ILLEGIBLE, UNCERTAIN, strip_markers

PROMPT_TEMPLATE = "validation.md"
# Appended by run_llm_judge between the prompt block and the page text;
# pipeline/prompts/validation.md describes it to the prompt's maintainers.
TRANSCRIPTION_SEPARATOR = "\n\n--- Transcription ---\n\n"

# Phase 1: deterministic rule checks


def _count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text))


def _rule_uncertain_markers(text: str) -> dict:
    """Count [?] markers that the transcription step inserted for low-confidence readings."""
    count = _count_pattern(text, UNCERTAIN)
    severity = "error" if count > 10 else "warning" if count > 3 else "info"
    return {"name": "uncertain_markers", "count": count, "severity": severity}


def _rule_illegible_markers(text: str) -> dict:
    """Count [...] and [... ~N chars] markers for passages that could not be read."""
    count = _count_pattern(text, ILLEGIBLE)
    severity = "error" if count > 5 else "warning" if count > 1 else "info"
    return {"name": "illegible_markers", "count": count, "severity": severity}


def _rule_ocr_artifacts(text: str) -> dict:
    """Detect isolated punctuation clusters that typically come from OCR noise.

    Looks for sequences of 3+ punctuation characters not part of standard
    conventions (ellipsis, dashes, repeated dots in a table of contents).
    The edition-convention markers are removed first: [?] and the bracket
    forms are punctuation clusters by shape, and counting them here would
    report a correctly marked reading as machine noise.
    """
    # Match 3+ punctuation chars that are NOT just dots or dashes
    scanned = strip_markers(text)
    count = _count_pattern(scanned, r"(?<!\.)(?<![—–-])[^\w\s.—–\-]{3,}(?![\.)—–-])")
    severity = "error" if count > 3 else "warning" if count > 0 else "info"
    return {"name": "ocr_artifacts", "count": count, "severity": severity}


def _rule_double_spaces(text: str) -> dict:
    """Count double (or more) spaces that suggest alignment problems."""
    count = _count_pattern(text, r"  +")
    severity = "warning" if count > 10 else "info"
    return {"name": "double_spaces", "count": count, "severity": severity}


ALL_RULES = [
    _rule_uncertain_markers,
    _rule_illegible_markers,
    _rule_ocr_artifacts,
    _rule_double_spaces,
]


def run_deterministic(pages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run all deterministic rules across all pages.

    Returns (rule_results, per_page_stats).
    """
    # Concatenate all page texts for corpus-level rule counts
    full_text = "\n\n".join(p.get("transcription", "") for p in pages)
    rule_results = [rule(full_text) for rule in ALL_RULES]

    return rule_results, contract.page_stats(pages)


# Phase 2: LLM judge (optional)

# Verdict placeholder for a page the judge could not be asked about. It is
# not a confidence value of the judge's vocabulary and never counts as one.
JUDGE_UNREVIEWED = "unreviewed"
JUDGE_CONFIDENCE = frozenset({"confident", "likely", "uncertain"})
# The vocabulary of pipeline/prompts/validation.md, which is canonical; a
# test holds these sets equal to the enums in the prompt's fenced block.
JUDGE_ISSUE_TYPES = frozenset(
    {
        "spelling",
        "punctuation",
        "abbreviation",
        "marker",
        "ocr_artifact",
        "historical",
        "structural",
        "plausibility",
    }
)
JUDGE_PERSPECTIVES = frozenset(
    {"orthographic", "linguistic", "conventions", "structural"}
)


@dataclass(frozen=True)
class Judge:
    """The judge configuration of one run: provider, model and loaded prompt."""

    provider: str
    model: str
    template: str
    prompt_hash: str

    @property
    def vocabulary_hash(self) -> str:
        """Identify the answer vocabulary this run accepts from the judge.

        A verdict accepted under other rules is not current, even when the
        prompt text is unchanged.
        """
        return contract.canonical_hash(
            {
                "confidence": sorted(JUDGE_CONFIDENCE),
                "issue_types": sorted(JUDGE_ISSUE_TYPES),
                "perspectives": sorted(JUDGE_PERSPECTIVES),
            }
        )


def judge_config(use_llm: bool) -> Judge | None:
    """Return the configured judge, or None for a deterministic-only run.

    Reads VALIDATION_PROVIDER, VALIDATION_MODEL and the prompt at call time.
    """
    if not (use_llm and VALIDATION_PROVIDER):
        return None
    template = load_prompt(PROMPT_TEMPLATE)
    return Judge(
        VALIDATION_PROVIDER, VALIDATION_MODEL, template, contract.text_hash(template)
    )


def _valid_judge_result(value: object) -> bool:
    """Check the text judge's bounded JSON response vocabulary."""
    if not isinstance(value, dict):
        return False
    if value.get("confidence") not in JUDGE_CONFIDENCE:
        return False
    if not isinstance(value.get("summary"), str):
        return False
    issues = value.get("issues")
    return isinstance(issues, list) and all(
        isinstance(issue, dict)
        and all(
            isinstance(issue.get(field), str)
            for field in ("type", "text", "suggestion", "perspective")
        )
        and issue["type"] in JUDGE_ISSUE_TYPES
        and issue["perspective"] in JUDGE_PERSPECTIVES
        for issue in issues
    )


def _empty_page_result(page: dict) -> dict:
    """Verdict for a page without text, which is never sent to the judge."""
    declared_blank = page.get("page_type") == "blank"
    return {
        "page": page["page"],
        "confidence": "confident" if declared_blank else JUDGE_UNREVIEWED,
        "issues": [],
        "summary": (
            "Declared blank page, nothing to validate."
            if declared_blank
            else "Empty page without a declared blank-page classification."
        ),
    }


def run_llm_judge(
    pages: list[dict], judge: Judge, object_id: str, calls_dir: Path
) -> tuple[list[dict], list[dict]]:
    """Send each text page through the LLM validation judge.

    Returns (results, executed_prompts). Each call is recorded under
    calls_dir/{object_id}/ and its executed_prompts entry names the record
    relative to calls_dir's parent (data/processed/ in a pipeline run).

    A judge that could not be reached says nothing about the transcription,
    so the page gets its own state (JUDGE_UNREVIEWED) instead of a negative
    verdict. An answer that arrived but could not be parsed is a verdict the
    judge failed to deliver and stays uncertain. A call whose record could
    not be written fails the object, because its provenance would be lost.
    The provider layer is imported here so a deterministic run never loads it.
    """
    from llm import call_llm, parse_json_response

    results: list[dict] = []
    calls: list[dict] = []
    for page in pages:
        text = page.get("transcription", "")
        if not text.strip():
            results.append(_empty_page_result(page))
            continue

        prompt = judge.template + TRANSCRIPTION_SEPARATOR + text
        prompt_hash = contract.text_hash(prompt)
        path = calls_dir / object_id / f"{uuid.uuid4().hex}.json"
        call = {
            "page": page["page"],
            "prompt_hash": prompt_hash,
            "record": path.relative_to(calls_dir.parent).as_posix(),
        }
        calls.append(call)
        try:
            with recording(
                path,
                {
                    "provider": judge.provider,
                    "model": judge.model,
                    "temperature": TEMPERATURE,
                    "prompt": prompt,
                    **call,
                },
            ) as record:
                raw = call_llm(judge.provider, judge.model, prompt)
                record["answer"] = raw
        except Exception as exc:
            result = {
                "confidence": JUDGE_UNREVIEWED,
                "issues": [],
                "summary": f"LLM judge not reached: {redact_secrets(str(exc))}",
            }
        else:
            parsed = parse_json_response(raw)
            if _valid_judge_result(parsed):
                result = parsed
            else:
                result = {
                    "confidence": "uncertain",
                    "issues": [],
                    "summary": "LLM response violated the validation contract.",
                    "_raw_response": raw[:500],
                }
        if not path.is_file():
            raise ItemFailure("record", f"Judge call record was not written: {path}")
        results.append({**result, "page": page["page"], "_prompt_hash": prompt_hash})

    return results, calls


# Aggregation


def compute_overall_status(
    rules: list[dict],
    quality_signals: dict | None,
    llm_pages: list[dict] | None,
    gate_pages: int = 0,
    transcription_confidence: str = "",
) -> str:
    """Derive a single status from all validation signals.

    Priority order (highest to lowest):
      problematic > needs_review > confident

    The needs_review quality signal means "unverified transcription", not
    "serious reading errors" -- it maps to needs_review, never problematic.
    Pages gated as not transcribable (page_type gate_low_resolution) also
    cap the status at needs_review so the data gap stays visible. A page the
    judge could not be asked about is unverified in the same sense and caps
    the status at needs_review rather than pulling it to problematic.
    """
    error_count = sum(1 for r in rules if r["severity"] == "error")
    warning_count = sum(1 for r in rules if r["severity"] == "warning")

    # Check transcription-step quality signals (stored during step 03)
    needs_review_from_signals = False
    if quality_signals:
        needs_review_from_signals = quality_signals.get("needs_review", False)

    # Check LLM judge verdicts across all pages
    llm_uncertain = False
    llm_likely = False
    llm_unreviewed = False
    if llm_pages:
        for lp in llm_pages:
            conf = lp.get("confidence", "")
            if conf == "uncertain":
                llm_uncertain = True
            elif conf == "likely":
                llm_likely = True
            elif conf == JUDGE_UNREVIEWED:
                llm_unreviewed = True

    # Decision tree
    if llm_uncertain or error_count > 2:
        return "problematic"
    if (
        llm_likely
        or llm_unreviewed
        or warning_count > 0
        or needs_review_from_signals
        or gate_pages > 0
        or transcription_confidence == "low"
    ):
        return "needs_review"
    return "confident"


# Main processing


def _existing_is_current(
    existing: object, data: dict, object_id: str, judge: Judge | None
) -> bool:
    """Whether a stored validation still describes this input and judge setup."""
    if contract.validated_file_violations(existing):
        return False
    assert isinstance(existing, dict)
    meta = existing["_meta"]
    return (
        existing.get("object_id") == object_id
        and meta.get("input_state_hash") == contract.transcription_state_hash(data)
        and meta.get("provider", "") == (judge.provider if judge else "")
        and meta.get("model", "") == (judge.model if judge else "")
        and meta.get("prompt_hash", "") == (judge.prompt_hash if judge else "")
        and meta.get("judge_vocabulary_hash", "")
        == (judge.vocabulary_hash if judge else "")
    )


def _build_output(
    data: dict,
    judge: Judge | None,
    judged: tuple[list[dict], list[dict]] | None,
) -> dict:
    """Assemble the step-4 file: the unchanged input plus findings and status.

    judged is the (results, executed_prompts) pair of run_llm_judge, or None
    without a judge. metadata and pages pass through unchanged (data
    contract, steps 3-6).
    """
    pages = data["pages"]
    quality_signals = data.get("quality_signals")
    unverified_pages = sum(
        1
        for page in pages
        if page.get("page_type") == "gate_low_resolution"
        or (not page["transcription"].strip() and page.get("page_type") != "blank")
    )
    rules, per_page_stats = run_deterministic(pages)
    llm_results = judged[0] if judged else None

    meta = provenance_meta(
        script="04_validate.py",
        provider=judge.provider if judge else "",
        model=judge.model if judge else "",
        prompt_template=PROMPT_TEMPLATE if judge else "",
        step=4,
    )
    meta["input_state_hash"] = contract.transcription_state_hash(data)
    if judge and judged is not None:
        meta["prompt_hash"] = judge.prompt_hash
        meta["judge_vocabulary_hash"] = judge.vocabulary_hash
        meta["executed_prompts"] = judged[1]
    output = {
        "_meta": meta,
        "object_id": data["object_id"],
        "transcription_meta": data.get("transcription_meta", data.get("_meta", {})),
        "metadata": data.get("metadata", {}),
        "pages": pages,
        "validation": {
            "rules": rules,
            "per_page_stats": per_page_stats,
            "total_characters": sum(s["char_count"] for s in per_page_stats),
        },
    }
    for key in ("quality_signals", "confidence", "confidence_notes", "source_images"):
        if key in data:
            output[key] = data[key]

    if llm_results is not None:
        output["validation"]["llm_judge"] = llm_results
        unreviewed = sum(
            1 for r in llm_results if r.get("confidence") == JUDGE_UNREVIEWED
        )
        if unreviewed:
            output["validation"]["llm_judge_unreviewed_pages"] = unreviewed

    output["overall_status"] = compute_overall_status(
        rules,
        quality_signals,
        llm_results,
        unverified_pages,
        data.get("confidence", ""),
    )
    meta["validation_result_hash"] = contract.validation_result_hash(output)
    return output


def validate_one(
    object_id: str,
    judge: Judge | None,
    force: bool,
    *,
    transcriptions_dir: Path | None = None,
    validated_dir: Path | None = None,
    calls_dir: Path | None = None,
) -> str:
    """Validate one transcription and return its overall_status.

    judge is the result of judge_config, None for a deterministic run. The
    directories default at call time to the module globals TRANSCRIPTIONS_DIR,
    VALIDATED_DIR and LLM_CALLS_DIR. A current existing output is kept and
    its status returned. Raises ItemFailure (stages contract, read, stale,
    record, write) when the object cannot be validated.
    """
    transcriptions_dir = transcriptions_dir or TRANSCRIPTIONS_DIR
    validated_dir = validated_dir or VALIDATED_DIR
    calls_dir = calls_dir or LLM_CALLS_DIR
    data = load_checked_json(transcriptions_dir, object_id, contract.file_violations)
    dst = validated_dir / f"{object_id}.json"

    if dst.exists() and not force:
        try:
            existing = read_json(dst)
        except (OSError, ValueError) as exc:
            raise ItemFailure(
                "stale", f"Existing validation is unreadable: {exc}; rerun with --force"
            ) from exc
        if not _existing_is_current(existing, data, object_id, judge):
            raise ItemFailure(
                "stale", "Existing validation is stale or invalid; rerun with --force"
            )
        print(f"  SKIP {object_id} (validation matches input and configuration)")
        return existing["overall_status"]

    judged = None
    if judge:
        print(
            f"  LLM  {object_id} ({len(data['pages'])} page(s) via "
            f"{judge.provider}/{judge.model})"
        )
        judged = run_llm_judge(data["pages"], judge, object_id, calls_dir)
    output = _build_output(data, judge, judged)

    try:
        write_json_atomic(dst, output)
    except OSError as exc:
        raise ItemFailure("write", str(exc)) from exc
    status = output["overall_status"]
    label = {"confident": "OK  ", "needs_review": "WARN"}.get(status, "PROB")
    print(f"  {label} {object_id} -> {status}")
    return status


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Validate transcriptions (deterministic rules + optional LLM judge)."
    )
    add_selection_args(parser)
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip LLM judge (Phase 2)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-validate even if output exists"
    )
    args = parser.parse_args()

    # Deterministic-only mode (empty VALIDATION_PROVIDER or --no-llm) needs no key.
    judge = judge_config(not args.no_llm)
    if judge:
        require_provider(
            judge.provider,
            judge.model,
            ", or run with --no-llm for deterministic validation",
        )

    ensure_dirs()
    candidates = [
        path.stem
        for path in sorted(TRANSCRIPTIONS_DIR.glob("*.json"))
        if path.stem != "errors"
    ]
    objects = select_ids(candidates, args.object, args.all, args.sample)

    mode = (
        f"deterministic + LLM ({judge.provider}/{judge.model})"
        if judge
        else "deterministic only"
    )
    print(f"Validating {len(objects)} object(s) [{mode}]\n")

    errors: list[dict] = []
    counts = dict.fromkeys(sorted(contract.VALIDATION_STATUSES), 0)
    for object_id in objects:
        try:
            counts[validate_one(object_id, judge, args.force)] += 1
        except ItemFailure as failure:
            errors.append(
                {
                    "object_id": object_id,
                    "error": failure.message,
                    "stage": failure.stage,
                }
            )

    # Only processing errors fail the run; a problematic status is a finding.
    finish_run(
        errors,
        VALIDATED_DIR,
        len(objects),
        "04_validate.py",
        summary=(
            f"\nDone. {len(objects)} object(s): {counts['confident']} confident, "
            f"{counts['needs_review']} needs_review, {counts['problematic']} "
            f"problematic, {len(errors)} failed."
        ),
    )


if __name__ == "__main__":
    main()
