"""Validate generated TEI against the fork's chosen RelaxNG schema.

The validation target is a per-project decision (ADR-005): set
VALIDATION_SCHEMA in pipeline/config.py or pass --schema. The shipped
schemas/basisformat.rng is the DTABf example profile; the deterministic
generator's header does not pass strict DTABf (journal, 2026-07-18), so
strict-DTABf forks must adapt the header first or validate against
TEI All or their own schema (see schemas/README.md).

Usage:
    python pipeline/validate_schema.py                    # all results/tei/*.xml
    python pipeline/validate_schema.py FILE [FILE ...]
    python pipeline/validate_schema.py --schema schemas/tei_all.rng
"""
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

import config


@dataclass
class FileResult:
    path: Path
    valid: bool
    errors: list = field(default_factory=list)


def default_schema() -> Path:
    return config.VALIDATION_SCHEMA


def validate_files(schema_path: Path, files: list) -> list:
    schema_path = Path(schema_path)
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema not found: {schema_path}. Set VALIDATION_SCHEMA in "
            "pipeline/config.py to the RelaxNG schema your project validates "
            "against, or pass --schema. Available targets are documented in "
            "schemas/README.md (TEI All, DTABf, own RNG/ODD)."
        )
    rng = etree.RelaxNG(etree.parse(str(schema_path)))
    results = []
    for f in files:
        f = Path(f)
        try:
            doc = etree.parse(str(f))
        except etree.XMLSyntaxError as e:
            results.append(FileResult(f, False, [f"not well-formed: {e}"]))
            continue
        if rng.validate(doc):
            results.append(FileResult(f, True))
        else:
            errors = [f"line {e.line}: {e.message}" for e in rng.error_log]
            results.append(FileResult(f, False, errors))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate TEI files against the project's RelaxNG schema."
    )
    parser.add_argument("files", nargs="*", help="TEI files (default: results/tei/*.xml)")
    parser.add_argument("--schema", type=Path, default=None,
                        help="RelaxNG schema (default: config.VALIDATION_SCHEMA)")
    args = parser.parse_args()

    schema = args.schema or default_schema()
    files = [Path(f) for f in args.files] or sorted(config.RESULTS_TEI_DIR.glob("*.xml"))
    if not files:
        print(f"No TEI files found in {config.RESULTS_TEI_DIR}. Run step 5 first.")
        return 1

    try:
        results = validate_files(schema, files)
    except FileNotFoundError as e:
        print(str(e))
        return 2

    invalid = [r for r in results if not r.valid]
    for r in results:
        print(f"{'valid  ' if r.valid else 'INVALID'}  {r.path.name}")
        for err in r.errors[:10]:
            print(f"    {err}")
        if len(r.errors) > 10:
            print(f"    ... {len(r.errors) - 10} further errors")
    print(f"\n{len(results) - len(invalid)}/{len(results)} valid against {schema.name}")
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
