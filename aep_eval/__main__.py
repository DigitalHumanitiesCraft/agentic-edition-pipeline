"""CLI: `python -m aep_eval MANIFEST --out DIR [--fail-fast] [--strict]`.

Exit codes: 0 clean run, 1 at least one fixture error (or an invalid TEI
under --strict), 2 manifest unusable. Inputs are never written.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .runner import run


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m aep_eval",
        description="Evaluate a fixture manifest: CER under declared profiles and RelaxNG "
        "conformance; writes results.json and report.md into --out.",
    )
    parser.add_argument("manifest", type=Path, help="fixture manifest (JSON)")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--fail-fast", action="store_true", help="stop at the first fixture error"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when any TEI file is invalid against its schema",
    )
    parser.add_argument(
        "--version", action="version", version=f"aep_eval {__version__}"
    )
    args = parser.parse_args(argv)
    return run(args.manifest, args.out, fail_fast=args.fail_fast, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
