"""Gate GitHub Pages deployment on schema validity and human acceptance.

Blocks publication while a review transaction awaits recovery, when a TEI
candidate is schema-invalid, when optional annotations are not bound to the
current canonical transcription, and when revisionDesc/@status is not
accepted. Exit code 0 only when every candidate passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

import config
import validate_schema
from review_state import PENDING_MARKER, dependencies, workflow


def _canonical(object_id: str) -> dict | None:
    try:
        data = config.read_json(config.TRANSCRIPTIONS_DIR / f"{object_id}.json")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def publication_problems(files: list[Path], schema: Path) -> list[str]:
    """Return publication blockers for the complete TEI candidate set."""
    if not files:
        return [f"no TEI candidates found in {config.RESULTS_TEI_DIR}"]
    if (config.PROJECT_ROOT / PENDING_MARKER).exists():
        return ["interrupted review transaction must be recovered before publication"]

    results = validate_schema.validate_files(schema, files)
    problems = [
        f"{result.path.name} is invalid against {schema.name}"
        for result in results
        if not result.valid
    ]
    for path, result in zip(files, results, strict=True):
        if not result.valid:
            continue
        states = dependencies(config.PROJECT_ROOT, path.stem, _canonical(path.stem))
        if any(item["status"] != "current" for item in states):
            problems.append(
                f"{path.name} has stale, unbound or unverifiable annotations"
            )
        root = etree.parse(str(path), config.safe_xml_parser()).getroot()
        status = workflow(root)["human_review"]
        if status != "accepted":
            problems.append(
                f"{path.name} has human review status {status or 'missing'}; accepted required"
            )
    return problems


def main() -> int:
    files = sorted(config.RESULTS_TEI_DIR.glob("*.xml"))
    try:
        problems = publication_problems(files, config.VALIDATION_SCHEMA)
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        print(f"PUBLICATION BLOCKED: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("PUBLICATION BLOCKED", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(
        f"Publication gate passed: {len(files)} TEI file(s) are schema-valid and accepted."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
