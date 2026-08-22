"""Run a manifest: read inputs, hash them, evaluate, collect, write.

Multi-fixture processing follows skip-and-log-and-collect: each fixture and
each check runs in its own try block, failures become error records with the
stage that failed, the run continues, and the exit code is non-zero when
anything failed. Inputs are read only; the only writes go to `out_dir`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import cer, profiles, tei_check
from .manifest import Fixture, Manifest, ManifestError, load_manifest, sha256_of
from .results import Record, build_report, write_report

REPO_ROOT = Path(__file__).resolve().parents[1]


def _hash_checked(path: Path, declared: str | None) -> str:
    if not path.exists():
        raise FileNotFoundError(f"input not found: {path}")
    actual = sha256_of(path)
    if declared and declared.lower() != actual:
        raise ValueError(
            f"sha256 mismatch for {path}: manifest {declared}, actual {actual}"
        )
    return actual


def _base_record(fx: Fixture, metric: str) -> Record:
    return Record(
        fixture_id=fx.id,
        metric=metric,
        status="error",
        value=None,
        n=0,
        scope=fx.scope,
        profile=fx.profile if metric == "cer" else None,
        reference_class=fx.reference_class,
        maturity=fx.maturity,
        git_anchor=fx.git_anchor,
    )


def evaluate_cer(fx: Fixture) -> Record:
    rec = _base_record(fx, "cer")
    prof = profiles.get_profile(fx.profile)
    assert fx.hypothesis is not None and fx.reference is not None
    rec.input_hashes = {
        "hypothesis": _hash_checked(fx.hypothesis.path, fx.hypothesis.sha256),
        "reference": _hash_checked(fx.reference.path, fx.reference.sha256),
    }
    pages = list(fx.hypothesis.pages) if fx.hypothesis.pages is not None else None
    hyp = profiles.read_side(prof, fx.hypothesis.kind, fx.hypothesis.path, pages)
    ref = profiles.read_side(prof, fx.reference.kind, fx.reference.path)
    if not ref:
        raise ValueError("reference text is empty after extraction")
    result = cer.score(ref, hyp)
    details = result.to_dict()
    details.update(
        profile_source=prof.source,
        hypothesis_kind=fx.hypothesis.kind,
        reference_kind=fx.reference.kind,
        pages=pages,
    )
    rec.status = "ok"
    rec.value = getattr(result, prof.value_field)
    rec.n = result.reference_chars
    rec.details = details
    return rec


def evaluate_relaxng(fx: Fixture, schema_cache: dict) -> Record:
    rec = _base_record(fx, "relaxng")
    assert fx.tei_path is not None and fx.relaxng_schema is not None
    rec.input_hashes = {
        "tei": _hash_checked(fx.tei_path, fx.tei_sha256),
        "schema": _hash_checked(fx.relaxng_schema, None),
    }
    key = str(fx.relaxng_schema)
    if key not in schema_cache:
        schema_cache[key] = tei_check.load_schema(fx.relaxng_schema)
    result = tei_check.check_tei(fx.tei_path, fx.relaxng_schema, schema_cache[key])
    rec.status = result.status
    rec.value = 1.0 if result.valid else 0.0
    rec.n = 1
    rec.details = result.to_dict()
    return rec


def run_manifest(
    manifest: Manifest, fail_fast: bool = False
) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    errors: list[dict] = []
    schema_cache: dict = {}
    for fx in manifest.fixtures:
        for check in fx.checks:
            try:
                if check == "cer":
                    records.append(evaluate_cer(fx))
                elif check == "relaxng":
                    records.append(evaluate_relaxng(fx, schema_cache))
            except (OSError, ValueError, RuntimeError) as exc:
                message = f"{type(exc).__name__}: {exc}"
                print(f"FEHLER {fx.id} [{check}] {message}", file=sys.stderr)
                errors.append({"fixture_id": fx.id, "stage": check, "message": message})
                rec = _base_record(fx, check)
                rec.message = message
                records.append(rec)
                if fail_fast:
                    return records, errors
            else:
                print(f"OK {fx.id} [{check}]")
    return records, errors


def run(
    manifest_path: Path, out_dir: Path, fail_fast: bool = False, strict: bool = False
) -> int:
    """Exit codes: 0 clean, 1 fixture errors (or invalid TEI with --strict),
    2 manifest unusable."""
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        print(f"FEHLER manifest: {exc}", file=sys.stderr)
        return 2
    records, errors = run_manifest(manifest, fail_fast=fail_fast)
    report = build_report(manifest, records, errors, REPO_ROOT)
    json_path, md_path = write_report(report, out_dir)
    for agg in report["aggregates"]:
        if agg["metric"] == "cer":
            print(
                f"AGGREGATE cer {agg['profile']} ({agg['method']}, n={agg['n_fixtures']}): {agg['value']:.6f}"
            )
        else:
            print(f"AGGREGATE relaxng valid {agg['value']}/{agg['n_fixtures']}")
    print(f"written {json_path}\nwritten {md_path}")
    invalid = any(r.metric == "relaxng" and r.status == "invalid" for r in records)
    if errors:
        print(f"FEHLER {len(errors)} fixture error(s)", file=sys.stderr)
        return 1
    if strict and invalid:
        print("FEHLER invalid TEI under --strict", file=sys.stderr)
        return 1
    return 0
