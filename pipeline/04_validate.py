"""Hybrid validation of transcriptions: deterministic rules + optional LLM judge.

Phase 1 runs always and applies fast, rule-based checks (uncertain markers,
illegible markers, OCR artifacts, whitespace anomalies). Phase 2 sends each
page through an LLM judge for deeper assessment -- this only runs when
VALIDATION_PROVIDER is configured and --no-llm is not set.

The two phases feed into a single overall_status per object:
  "confident"    -- no significant issues
  "needs_review" -- minor issues or LLM says "likely"
  "problematic"  -- serious issues or LLM says "uncertain"

Idempotent: existing validated files are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import (
    TRANSCRIPTIONS_DIR,
    VALIDATED_DIR,
    VALIDATION_MODEL,
    VALIDATION_PROVIDER,
    ensure_dirs,
    load_prompt,
    missing_api_key,
    provenance_meta,
    write_errors,
)


# ---------------------------------------------------------------------------
# Phase 1 -- deterministic rule checks
# ---------------------------------------------------------------------------

def _count_pattern(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text))


def _rule_uncertain_markers(text: str) -> dict:
    """Count [?] markers that the transcription step inserted for low-confidence readings."""
    count = _count_pattern(text, r"\[\?\]")
    severity = "error" if count > 10 else "warning" if count > 3 else "info"
    return {"name": "uncertain_markers", "count": count, "severity": severity}


def _rule_illegible_markers(text: str) -> dict:
    """Count [...] and [... ~N chars] markers for passages that could not be read."""
    count = _count_pattern(text, r"\[\.\.\.(?:\s*~\d+\s*chars?)?\]")
    severity = "error" if count > 5 else "warning" if count > 1 else "info"
    return {"name": "illegible_markers", "count": count, "severity": severity}


def _rule_ocr_artifacts(text: str) -> dict:
    """Detect isolated punctuation clusters that typically come from OCR noise.

    Looks for sequences of 3+ punctuation characters not part of standard
    conventions (ellipsis, dashes, repeated dots in a table of contents).
    """
    # Match 3+ punctuation chars that are NOT just dots or dashes
    count = _count_pattern(text, r"(?<!\.)(?<![—–-])[^\w\s.—–\-]{3,}(?![\.)—–-])")
    severity = "error" if count > 3 else "warning" if count > 0 else "info"
    return {"name": "ocr_artifacts", "count": count, "severity": severity}


def _rule_double_spaces(text: str) -> dict:
    """Count double (or more) spaces that suggest alignment problems."""
    count = _count_pattern(text, r"  +")
    severity = "warning" if count > 10 else "info"
    return {"name": "double_spaces", "count": count, "severity": severity}


def _page_stats(text: str) -> dict:
    """Basic character and word counts for a single page."""
    return {
        "char_count": len(text),
        "word_count": len(text.split()),
        "line_count": text.count("\n") + (1 if text else 0),
    }


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

    per_page = []
    for p in pages:
        txt = p.get("transcription", "")
        stats = _page_stats(txt)
        stats["page"] = p.get("page", 0)
        per_page.append(stats)

    return rule_results, per_page


# ---------------------------------------------------------------------------
# Phase 2 -- LLM judge (optional)
# ---------------------------------------------------------------------------

def run_llm_judge(pages: list[dict], prompt_template: str) -> list[dict]:
    """Send each page through the LLM validation judge.

    Import is deferred so the script works without network access when --no-llm.
    """
    from llm import call_llm, parse_json_response

    results: list[dict] = []
    for p in pages:
        txt = p.get("transcription", "")
        if not txt.strip():
            results.append({
                "page": p.get("page", 0),
                "confidence": "confident",
                "issues": [],
                "summary": "Empty page, nothing to validate.",
            })
            continue

        prompt = prompt_template + "\n\n--- Transcription ---\n\n" + txt
        try:
            raw = call_llm(VALIDATION_PROVIDER, VALIDATION_MODEL, prompt)
            parsed = parse_json_response(raw)
            if parsed and isinstance(parsed, dict):
                parsed["page"] = p.get("page", 0)
                results.append(parsed)
            else:
                results.append({
                    "page": p.get("page", 0),
                    "confidence": "uncertain",
                    "issues": [],
                    "summary": f"LLM response could not be parsed as JSON.",
                    "_raw_response": raw[:500],
                })
        except Exception as exc:
            results.append({
                "page": p.get("page", 0),
                "confidence": "uncertain",
                "issues": [],
                "summary": f"LLM call failed: {exc}",
            })

    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_overall_status(
    rules: list[dict],
    quality_signals: dict | None,
    llm_pages: list[dict] | None,
    gate_pages: int = 0,
) -> str:
    """Derive a single status from all validation signals.

    Priority order (highest to lowest):
      problematic > needs_review > confident

    The needs_review quality signal means "unverified transcription", not
    "serious reading errors" -- it maps to needs_review, never problematic.
    Pages gated as not transcribable (page_type gate_low_resolution) also
    cap the status at needs_review so the data gap stays visible.
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
    if llm_pages:
        for lp in llm_pages:
            conf = lp.get("confidence", "")
            if conf == "uncertain":
                llm_uncertain = True
            elif conf == "likely":
                llm_likely = True

    # Decision tree
    if llm_uncertain or error_count > 2:
        return "problematic"
    if llm_likely or warning_count > 0 or needs_review_from_signals or gate_pages > 0:
        return "needs_review"
    return "confident"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def validate_one(object_id: str, use_llm: bool, force: bool) -> dict | None:
    """Validate a single transcription file. Returns error dict on failure, None on success."""
    src = TRANSCRIPTIONS_DIR / f"{object_id}.json"
    dst = VALIDATED_DIR / f"{object_id}.json"

    if not src.exists():
        return {"object_id": object_id, "error": f"Transcription not found: {src}", "stage": "read"}

    if dst.exists() and not force:
        print(f"  SKIP {object_id} (already validated, use --force to re-run)")
        return None

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"object_id": object_id, "error": str(exc), "stage": "read"}

    pages = data.get("pages", [])
    quality_signals = data.get("quality_signals", None)
    gate_pages = sum(1 for p in pages if p.get("page_type") == "gate_low_resolution")

    # Phase 1: deterministic
    rules, per_page_stats = run_deterministic(pages)
    total_chars = sum(s["char_count"] for s in per_page_stats)

    # Phase 2: LLM judge
    llm_results = None
    prompt_template_name = "validation.md"
    if use_llm and VALIDATION_PROVIDER:
        print(f"  LLM  {object_id} ({len(pages)} page(s) via {VALIDATION_PROVIDER}/{VALIDATION_MODEL})")
        prompt_template = load_prompt(prompt_template_name)
        llm_results = run_llm_judge(pages, prompt_template)

    overall = compute_overall_status(rules, quality_signals, llm_results, gate_pages)

    # Build output -- keep the original data and add validation block.
    # metadata is passed through unchanged (data contract, steps 3-6).
    output = {
        "_meta": provenance_meta(
            script="04_validate.py",
            provider=VALIDATION_PROVIDER if (use_llm and VALIDATION_PROVIDER) else "",
            model=VALIDATION_MODEL if (use_llm and VALIDATION_PROVIDER) else "",
            prompt_template=prompt_template_name if (use_llm and VALIDATION_PROVIDER) else "",
            step=4,
        ),
        "object_id": object_id,
        "metadata": data.get("metadata", {}),
        "pages": pages,
        "validation": {
            "rules": rules,
            "per_page_stats": per_page_stats,
            "total_characters": total_chars,
        },
    }

    if quality_signals is not None:
        output["quality_signals"] = quality_signals

    if llm_results is not None:
        output["validation"]["llm_judge"] = llm_results

    output["overall_status"] = overall

    dst.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {'OK  ' if overall == 'confident' else 'WARN' if overall == 'needs_review' else 'PROB'} {object_id} -> {overall}")
    return None


def collect_objects(single: str | None, all_flag: bool) -> list[str]:
    """Resolve which objects to process from CLI arguments."""
    if single:
        return [single]

    if all_flag:
        files = sorted(TRANSCRIPTIONS_DIR.glob("*.json"))
        # Exclude errors.json or any meta files
        ids = [f.stem for f in files if f.stem != "errors"]
        if not ids:
            print(f"No transcription files found in {TRANSCRIPTIONS_DIR}", file=sys.stderr)
            sys.exit(1)
        return ids

    print("Specify --object ID or --all", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Validate transcriptions (deterministic rules + optional LLM judge)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Validate a single object by ID")
    group.add_argument("--all", action="store_true", help="Validate all transcriptions")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM judge (Phase 2)")
    parser.add_argument("--force", action="store_true", help="Re-validate even if output exists")
    args = parser.parse_args()

    ensure_dirs()
    use_llm = not args.no_llm

    # Fail fast when the LLM judge is requested but its key is missing.
    # Deterministic-only mode (empty VALIDATION_PROVIDER or --no-llm) needs no key.
    if use_llm and VALIDATION_PROVIDER:
        missing = missing_api_key(VALIDATION_PROVIDER)
        if missing:
            print(
                f"ERROR: no API key configured, this step requires one. "
                f"Set {missing} in .env for provider '{VALIDATION_PROVIDER}', "
                f"or run with --no-llm for deterministic validation.",
                file=sys.stderr,
            )
            sys.exit(1)

    objects = collect_objects(args.object, args.all)

    mode = "deterministic only" if not use_llm or not VALIDATION_PROVIDER else f"deterministic + LLM ({VALIDATION_PROVIDER}/{VALIDATION_MODEL})"
    print(f"Validating {len(objects)} object(s) [{mode}]\n")

    errors: list[dict] = []
    status_counts = {"confident": 0, "needs_review": 0, "problematic": 0, "failed": 0}

    for oid in objects:
        err = validate_one(oid, use_llm, args.force)
        if err:
            errors.append(err)
            status_counts["failed"] += 1
            print(f"  FAIL {err['object_id']}: {err['error']}")
        else:
            # Read back the status to count it
            dst = VALIDATED_DIR / f"{oid}.json"
            if dst.exists():
                try:
                    result = json.loads(dst.read_text(encoding="utf-8"))
                    s = result.get("overall_status", "confident")
                    status_counts[s] = status_counts.get(s, 0) + 1
                except Exception:
                    pass

    if errors:
        write_errors(errors, VALIDATED_DIR)
        print(f"\n{len(errors)} error(s) written to {VALIDATED_DIR / 'errors.json'}")

    print(f"\nDone. {len(objects)} object(s): "
          f"{status_counts['confident']} confident, "
          f"{status_counts['needs_review']} needs_review, "
          f"{status_counts['problematic']} problematic, "
          f"{status_counts['failed']} failed.")


if __name__ == "__main__":
    main()
