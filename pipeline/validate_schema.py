"""Validate generated TEI against the fork's chosen RelaxNG schema.

The validation target is a per-project decision (ADR-005): set
VALIDATION_SCHEMA in pipeline/config.py or pass --schema. The default is
schemas/tei_all.rng, which the deterministic generator's output satisfies as
shipped. The DTABf profile (schemas/basisformat.rng) also ships, but the
generator's header does not pass it (journal, 2026-07-18), so a strict-DTABf
fork adapts the header template first (see schemas/README.md).

Compiling tei_all.rng takes seconds, and the review server validates on
every save, so compiled validators are cached per process and keyed by the
schema's resolved path, modification time and size; editing the schema file
invalidates its entry. A lxml validator keeps its error log on the instance,
so a shared validator is used under a lock.

Usage:
    uv run python pipeline/validate_schema.py                    # all results/tei/*.xml
    uv run python pipeline/validate_schema.py FILE [FILE ...]
    uv run python pipeline/validate_schema.py --schema schemas/tei_all.rng
"""

import argparse
import sys
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import etree

import config

_VALIDATION_LOCK = threading.Lock()


@dataclass
class FileResult:
    path: Path
    valid: bool
    errors: list = field(default_factory=list)


@lru_cache(maxsize=4)
def _compiled_schema(path: str, _mtime_ns: int, _size: int) -> etree.RelaxNG:
    try:
        return etree.RelaxNG(etree.parse(path, config.safe_xml_parser()))
    except (etree.XMLSyntaxError, etree.RelaxNGParseError) as exc:
        raise ValueError(f"invalid RelaxNG schema {path}: {exc}") from exc


def load_schema(schema_path: Path) -> etree.RelaxNG:
    """Return the compiled RelaxNG validator for a schema file.

    Raises FileNotFoundError with a configuration pointer when the file is
    absent and ValueError naming the path when it is not a valid schema.
    """
    schema_path = Path(schema_path)
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema not found: {schema_path}. Set VALIDATION_SCHEMA in "
            "pipeline/config.py to the RelaxNG schema your project validates "
            "against, or pass --schema. Available targets are documented in "
            "schemas/README.md (TEI All, DTABf, own RNG/ODD)."
        )
    resolved = schema_path.resolve()
    status = resolved.stat()
    return _compiled_schema(str(resolved), status.st_mtime_ns, status.st_size)


def validate_files(schema_path: Path, files: list) -> list:
    rng = load_schema(schema_path)
    results = []
    for f in files:
        f = Path(f)
        try:
            doc = etree.parse(str(f), config.safe_xml_parser())
        except (etree.XMLSyntaxError, OSError) as e:
            results.append(FileResult(f, False, [f"not well-formed: {e}"]))
            continue
        with _VALIDATION_LOCK:
            valid = rng.validate(doc)
            errors = [f"line {e.line}: {e.message}" for e in rng.error_log]
        results.append(FileResult(f, True) if valid else FileResult(f, False, errors))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate TEI files against the project's RelaxNG schema."
    )
    parser.add_argument(
        "files", nargs="*", help="TEI files (default: results/tei/*.xml)"
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="RelaxNG schema (default: config.VALIDATION_SCHEMA)",
    )
    args = parser.parse_args()

    schema = args.schema or config.VALIDATION_SCHEMA
    files = [Path(f) for f in args.files] or sorted(
        config.RESULTS_TEI_DIR.glob("*.xml")
    )
    if not files:
        print(f"No TEI files found in {config.RESULTS_TEI_DIR}. Run step 5 first.")
        return 1

    try:
        results = validate_files(schema, files)
    except (FileNotFoundError, ValueError) as e:
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
