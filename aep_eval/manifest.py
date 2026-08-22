"""Fixture manifest: loading, JSON Schema validation, path resolution.

A manifest names fixtures with hypothesis, reference, scope, reference class,
maturity tier, Git anchor and file hashes (schemas/evaluation-fixture.schema.json).
Relative paths resolve against the manifest's directory, so a manifest can live
outside the repositories it points into and still reference them read-only.

Trust boundary: a manifest that fails the schema, names an unknown profile or
an unknown kind is rejected as a whole (ManifestError). Missing files and hash
mismatches are fixture-level findings the runner collects, so one bad fixture
does not hide the others.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import profiles

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
FIXTURE_SCHEMA = SCHEMA_DIR / "evaluation-fixture.schema.json"
RESULT_SCHEMA = SCHEMA_DIR / "evaluation-result.schema.json"


class ManifestError(ValueError):
    """The manifest as a whole is unusable."""


@dataclass(frozen=True)
class Side:
    kind: str
    path: Path
    sha256: str | None = None
    pages: tuple[int, ...] | None = None


@dataclass
class Fixture:
    id: str
    checks: tuple[str, ...]
    profile: str | None
    hypothesis: Side | None
    reference: Side | None
    tei_path: Path | None
    tei_sha256: str | None
    relaxng_schema: Path | None
    scope: str
    reference_class: str
    maturity: str
    git_anchor: str | None
    notes: str | None


@dataclass
class Manifest:
    path: Path
    name: str
    created: str
    profile: str | None
    relaxng_schema: Path | None
    git_anchors: dict = field(default_factory=dict)
    fixtures: list[Fixture] = field(default_factory=list)
    sha256: str = ""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_against_schema(instance: dict, schema_path: Path) -> list[str]:
    """Return human-readable schema violations (empty list means valid)."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "jsonschema is required for aep_eval (pip install jsonschema)"
        ) from exc
    validator = jsonschema.Draft202012Validator(load_json_schema(schema_path))
    problems = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in error.path) or "<root>"
        problems.append(f"{where}: {error.message}")
    return problems


def _side(data: dict | None, base: Path) -> Side | None:
    if data is None:
        return None
    pages = data.get("pages")
    return Side(
        kind=data["kind"],
        path=(base / data["path"]).resolve()
        if not Path(data["path"]).is_absolute()
        else Path(data["path"]),
        sha256=data.get("sha256"),
        pages=tuple(int(p) for p in pages) if pages is not None else None,
    )


def _resolve(value: str | None, base: Path) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_manifest(path: Path) -> Manifest:
    """Load and validate a manifest; raises ManifestError with every violation."""
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {path}: {exc}") from exc
    problems = validate_against_schema(data, FIXTURE_SCHEMA)
    if problems:
        raise ManifestError(
            "manifest violates evaluation-fixture.schema.json:\n  "
            + "\n  ".join(problems)
        )

    base = path.parent
    default_profile = data.get("profile")
    if default_profile is not None:
        profiles.get_profile(default_profile)
    fixtures: list[Fixture] = []
    seen: set[str] = set()
    for item in data["fixtures"]:
        if item["id"] in seen:
            raise ManifestError(f"duplicate fixture id {item['id']!r}")
        seen.add(item["id"])
        profile_name = item.get("profile", default_profile)
        if "cer" in item["checks"]:
            if profile_name is None:
                raise ManifestError(
                    f"fixture {item['id']!r}: cer check needs a profile"
                )
            try:
                profiles.get_profile(profile_name)
            except ValueError as exc:
                raise ManifestError(f"fixture {item['id']!r}: {exc}") from exc
            if "hypothesis" not in item or "reference" not in item:
                raise ManifestError(
                    f"fixture {item['id']!r}: cer check needs hypothesis and reference"
                )
        tei = item.get("tei") or {}
        tei_path = _resolve(tei.get("path"), base)
        hypothesis = _side(item.get("hypothesis"), base)
        if "relaxng" in item["checks"]:
            if (
                tei_path is None
                and hypothesis is not None
                and hypothesis.kind in ("tei", "tei-edition")
            ):
                tei_path = hypothesis.path
            if tei_path is None:
                raise ManifestError(
                    f"fixture {item['id']!r}: relaxng check needs a tei path"
                )
        schema = _resolve(tei.get("relaxng_schema"), base) or _resolve(
            data.get("relaxng_schema"), base
        )
        if "relaxng" in item["checks"] and schema is None:
            raise ManifestError(
                f"fixture {item['id']!r}: relaxng check needs a relaxng_schema"
            )
        fixtures.append(
            Fixture(
                id=item["id"],
                checks=tuple(item["checks"]),
                profile=profile_name,
                hypothesis=hypothesis,
                reference=_side(item.get("reference"), base),
                tei_path=tei_path,
                tei_sha256=tei.get("sha256"),
                relaxng_schema=schema,
                scope=item.get("scope", "all"),
                reference_class=item.get("reference_class", "none"),
                maturity=item["maturity"],
                git_anchor=item.get("git_anchor"),
                notes=item.get("notes"),
            )
        )
    return Manifest(
        path=path,
        name=data["name"],
        created=data["created"],
        profile=default_profile,
        relaxng_schema=_resolve(data.get("relaxng_schema"), base),
        git_anchors=data.get("git_anchors", {}),
        fixtures=fixtures,
        sha256=sha256_of(path),
    )
