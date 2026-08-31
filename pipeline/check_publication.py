"""Gate GitHub Pages deployment on schema validity and human acceptance."""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

import config
import validate_schema

TEI_NS = "http://www.tei-c.org/ns/1.0"


def publication_problems(files: list[Path], schema: Path) -> list[str]:
    """Return publication blockers for the complete TEI candidate set."""
    if not files:
        return [f"no TEI candidates found in {config.RESULTS_TEI_DIR}"]

    results = validate_schema.validate_files(schema, files)
    problems = [
        f"{result.path.name} is invalid against {schema.name}"
        for result in results
        if not result.valid
    ]
    for path, result in zip(files, results, strict=True):
        if not result.valid:
            continue
        root = etree.parse(str(path)).getroot()
        revision = root.find(f".//{{{TEI_NS}}}revisionDesc")
        status = revision.get("status", "") if revision is not None else ""
        if status != "accepted":
            problems.append(
                f"{path.name} has human review status {status or 'missing'}; accepted required"
            )
    return problems


def main() -> int:
    files = sorted(config.RESULTS_TEI_DIR.glob("*.xml"))
    try:
        problems = publication_problems(files, config.VALIDATION_SCHEMA)
    except (
        FileNotFoundError,
        OSError,
        etree.RelaxNGParseError,
        etree.XMLSyntaxError,
    ) as exc:
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
