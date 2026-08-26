"""Build the synthetic offline example in an isolated local workspace.

The runner copies the actual pipeline, schema, frontend, and knowledge
templates into a disposable project directory. It overlays the filled example
knowledge and contract-conformant transcriptions, then executes steps 4, 5,
schema validation, and 6 through their public command-line interfaces.

Usage:
    python examples/offline-quickstart/run.py
    python examples/offline-quickstart/run.py --target PATH --force

No provider is configured and no network call is made. The target is separate
from the repository's working data, so the template skeleton stays unchanged.
See knowledge/decisions.md, ADR-007.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_TARGET = REPOSITORY_ROOT / ".aep-quickstart"
OWNERSHIP_SENTINEL = ".aep-offline-quickstart-owner.json"
OWNERSHIP_NAME = "agentic-edition-pipeline/offline-quickstart"
OWNERSHIP_VERSION = 1
VALIDATION_SCHEMA = "schemas/tei_all.rng"
OFFLINE_ENVIRONMENT = {
    "GEMINI_API_KEY": "",
    "OPENAI_API_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "OLLAMA_BASE_URL": "",
    "TRANSCRIPTION_PROVIDER": "",
    "TRANSCRIPTION_MODEL": "",
    "VALIDATION_PROVIDER": "",
    "VALIDATION_MODEL": "",
    "ANNOTATION_PROVIDER": "",
    "ANNOTATION_MODEL": "",
}


@dataclass(frozen=True)
class PipelineStep:
    """One real pipeline CLI invocation in the offline path."""

    label: str
    arguments: tuple[str, ...]


PIPELINE_STEPS = (
    PipelineStep(
        "deterministic validation",
        ("pipeline/04_validate.py", "--all", "--no-llm", "--force"),
    ),
    PipelineStep(
        "deterministic TEI generation",
        ("pipeline/05_annotate_tei.py", "--all", "--force"),
    ),
    PipelineStep(
        "RelaxNG validation",
        ("pipeline/validate_schema.py", "--schema", VALIDATION_SCHEMA),
    ),
    PipelineStep("static frontend build", ("pipeline/06_build_frontend.py", "--force")),
)


def _find_reparse_component(target: Path) -> Path | None:
    """Return the first existing symlink or Windows reparse component."""
    absolute = target.absolute()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            return component
        if not component.exists():
            continue
        attributes = getattr(component.lstat(), "st_file_attributes", 0)
        if reparse_flag and attributes & reparse_flag:
            return component
    return None


def _validated_target(target: Path) -> Path:
    """Reject unsafe original paths, then resolve and validate target identity."""
    reparse_component = _find_reparse_component(target)
    if reparse_component is not None:
        raise ValueError(
            f"refusing target through symlink or reparse point: {reparse_component}"
        )

    repository = REPOSITORY_ROOT.resolve()
    example = EXAMPLE_ROOT.resolve()
    resolved = target.resolve()

    if resolved in (repository, example) or resolved in repository.parents:
        raise ValueError(f"unsafe quickstart target: {resolved}")
    if repository in resolved.parents and resolved != DEFAULT_TARGET.resolve():
        raise ValueError(
            "targets inside the repository are limited to the default "
            f"{DEFAULT_TARGET.resolve()}"
        )
    return resolved


def _ownership_payload(target: Path) -> dict:
    """Return the exact marker content that proves runner ownership."""
    return {
        "_meta": {
            "script": "examples/offline-quickstart/run.py",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "owner": OWNERSHIP_NAME,
        "sentinel_version": OWNERSHIP_VERSION,
        "target": str(target.resolve()),
    }


def _write_ownership_marker(target: Path) -> None:
    """Write the safety-critical ownership marker atomically."""
    marker = target / OWNERSHIP_SENTINEL
    temporary = target / f"{OWNERSHIP_SENTINEL}.tmp"
    temporary.write_text(
        json.dumps(_ownership_payload(target), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(marker)


def _has_valid_ownership_marker(target: Path) -> bool:
    """Accept only a regular marker with valid provenance and exact ownership."""
    marker = target / OWNERSHIP_SENTINEL
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, dict) or set(payload) != {
        "_meta",
        "owner",
        "sentinel_version",
        "target",
    }:
        return False
    meta = payload.get("_meta")
    if not isinstance(meta, dict) or set(meta) != {"script", "timestamp"}:
        return False
    if meta.get("script") != "examples/offline-quickstart/run.py":
        return False
    try:
        timestamp = datetime.fromisoformat(str(meta.get("timestamp", "")))
    except ValueError:
        return False
    if timestamp.tzinfo is None:
        return False
    return (
        payload.get("owner") == OWNERSHIP_NAME
        and payload.get("sentinel_version") == OWNERSHIP_VERSION
        and payload.get("target") == str(target.resolve())
    )


def _remove_owned_target(target: Path) -> None:
    """Recursively remove only a target with a valid ownership marker."""
    if target.is_symlink():
        raise ValueError(f"refusing to remove symlink target: {target}")
    if not _has_valid_ownership_marker(target):
        raise ValueError(
            "refusing to replace a non-empty unowned target; choose an empty "
            f"directory or a runner-owned target with {OWNERSHIP_SENTINEL}: {target}"
        )
    shutil.rmtree(target)


def _prepare_target(target: Path, force: bool) -> None:
    """Create or safely replace the target, then establish runner ownership."""
    if target.exists():
        if not target.is_dir():
            raise NotADirectoryError(f"target is not a directory: {target}")
        is_empty = next(iter(target.iterdir()), None) is None
        if not is_empty:
            if not force:
                raise FileExistsError(
                    f"target already exists: {target}; pass --force to replace it"
                )
            _remove_owned_target(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=True)
    try:
        _write_ownership_marker(target)
    except Exception:
        if next(iter(target.iterdir()), None) is None:
            target.rmdir()
        raise


def _copy_runtime(target: Path) -> None:
    """Create a minimal fork workspace from the checked-out repository."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("pipeline", "schemas", "knowledge"):
        shutil.copytree(REPOSITORY_ROOT / name, target / name, ignore=ignore)
    for name in ("pyproject.toml", "requirements.txt", "LICENSE"):
        shutil.copy2(REPOSITORY_ROOT / name, target / name)

    docs_target = target / "docs"
    shutil.copytree(REPOSITORY_ROOT / "docs" / "css", docs_target / "css")
    shutil.copytree(REPOSITORY_ROOT / "docs" / "js", docs_target / "js")
    shutil.copy2(REPOSITORY_ROOT / "docs" / "index.html", docs_target / "index.html")

    for source in sorted((EXAMPLE_ROOT / "knowledge").glob("*.md")):
        shutil.copy2(source, target / "knowledge" / source.name)

    transcription_target = target / "data" / "processed" / "transcriptions"
    transcription_target.mkdir(parents=True)
    for source in sorted((EXAMPLE_ROOT / "corpus").glob("*.json")):
        shutil.copy2(source, transcription_target / source.name)


def _run_pipeline(target: Path) -> None:
    """Execute the offline stages with provider settings disabled."""
    environment = os.environ.copy()
    environment.update(OFFLINE_ENVIRONMENT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    for step in PIPELINE_STEPS:
        print(f"\nRUN  {step.label}", flush=True)
        subprocess.run(
            (sys.executable, *step.arguments),
            cwd=target,
            env=environment,
            check=True,
        )


def _verify_outputs(target: Path) -> dict:
    """Check the complete example result and return a machine-readable report."""
    expected_ids = sorted(
        path.stem for path in (EXAMPLE_ROOT / "corpus").glob("*.json")
    )
    catalog_path = target / "docs" / "data" / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_ids = sorted(item["id"] for item in catalog["objects"])

    checks = {
        "validated_json": all(
            (
                target / "data" / "processed" / "validated" / f"{object_id}.json"
            ).is_file()
            for object_id in expected_ids
        ),
        "tei_xml": all(
            (target / "results" / "tei" / f"{object_id}.xml").is_file()
            for object_id in expected_ids
        ),
        "tei_reports": all(
            (target / "results" / "reports" / f"{object_id}_validation.json").is_file()
            for object_id in expected_ids
        ),
        "frontend_objects": all(
            (target / "docs" / "data" / f"{object_id}.json").is_file()
            for object_id in expected_ids
        ),
        "catalog_complete": catalog_ids == expected_ids,
        "schema_valid": True,
        "offline_provider_environment": all(
            value == "" for value in OFFLINE_ENVIRONMENT.values()
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"offline quickstart verification failed: {', '.join(failed)}"
        )

    report = {
        "_meta": {
            "script": "examples/offline-quickstart/run.py",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_step": "offline_quickstart",
        },
        "objects": expected_ids,
        "checks": checks,
        "validation_schema": VALIDATION_SCHEMA,
        "network_used": False,
        "ownership_sentinel": OWNERSHIP_SENTINEL,
    }
    (target / "quickstart-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def build(target: Path, force: bool = False) -> dict:
    """Build and verify the example workspace at the exact requested path."""
    target = _validated_target(target)
    _prepare_target(target, force)
    try:
        _copy_runtime(target)
        _run_pipeline(target)
        return _verify_outputs(target)
    except Exception:
        with contextlib.suppress(ValueError):
            _remove_owned_target(target)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the synthetic Agentic Edition Pipeline example offline."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help=f"isolated output directory (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace a non-empty target only when its ownership marker is valid",
    )
    args = parser.parse_args()

    try:
        report = build(args.target, force=args.force)
    except (FileExistsError, NotADirectoryError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"ERROR: pipeline command failed with exit code {exc.returncode}",
            file=sys.stderr,
        )
        return exc.returncode or 1

    target = args.target.resolve()
    print(
        f"\nOK   offline quickstart built {len(report['objects'])} objects in {target}"
    )
    print(
        f'PREVIEW  {sys.executable} -m http.server 8080 --directory "{target / "docs"}"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
