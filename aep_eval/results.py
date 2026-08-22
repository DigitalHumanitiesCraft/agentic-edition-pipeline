"""Result set: the common record shape for CER and RelaxNG findings, the JSON
report validated against schemas/evaluation-result.schema.json, and the
compact Markdown rendering of the same findings.

Every record carries fixture id, metric, status, value, sample size, scope,
profile, reference class, maturity tier, tool version, Git anchor and the
input hashes, as the contract requires; profile-specific detail sits under
`details` so the top level stays comparable across metrics.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .manifest import RESULT_SCHEMA, validate_against_schema

RESULT_VERSION = "0.1"


@dataclass
class Record:
    fixture_id: str
    metric: str  # "cer" | "relaxng"
    status: str  # "ok" | "valid" | "invalid" | "error"
    value: float | None
    n: int
    scope: str
    profile: str | None
    reference_class: str
    maturity: str
    git_anchor: str | None
    input_hashes: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)
    message: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def tool_git_sha(repo_root: Path) -> str | None:
    """HEAD of the repository that carries this module, if Git is available."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def aggregate(records: list[Record]) -> list[dict]:
    """Per-profile CER aggregates and the RelaxNG tally. The aggregation
    method is part of the profile: char-weighted for hsa-strict, unweighted
    fixture mean for zbz-fidelity; both are named in the output."""
    from .profiles import get_profile

    out: list[dict] = []
    by_profile: dict[str, list[Record]] = {}
    for r in records:
        if r.metric == "cer" and r.status == "ok" and r.profile:
            by_profile.setdefault(r.profile, []).append(r)
    for name in sorted(by_profile):
        prof = get_profile(name)
        recs = by_profile[name]
        if prof.aggregate == "char-weighted":
            ref = sum(r.details["reference_chars"] for r in recs)
            dist = sum(r.details["distance"] for r in recs)
            value = dist / ref if ref else 0.0
        else:
            value = sum(r.value for r in recs if r.value is not None) / len(recs)
        out.append(
            {
                "metric": "cer",
                "profile": name,
                "method": prof.aggregate,
                "value_field": prof.value_field,
                "n_fixtures": len(recs),
                "value": value,
            }
        )
    relaxng = [
        r for r in records if r.metric == "relaxng" and r.status in ("valid", "invalid")
    ]
    if relaxng:
        out.append(
            {
                "metric": "relaxng",
                "profile": None,
                "method": "count",
                "value_field": "valid",
                "n_fixtures": len(relaxng),
                "value": sum(1 for r in relaxng if r.status == "valid"),
            }
        )
    return out


def build_report(
    manifest, records: list[Record], errors: list[dict], repo_root: Path
) -> dict:
    report = {
        "result_version": RESULT_VERSION,
        "tool": {
            "name": "aep_eval",
            "version": __version__,
            "git_sha": tool_git_sha(repo_root),
        },
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "manifest": {
            "name": manifest.name,
            "path": str(manifest.path),
            "sha256": manifest.sha256,
            "git_anchors": manifest.git_anchors,
        },
        "aggregates": aggregate(records),
        "results": [r.to_dict() for r in records],
        "errors": errors,
    }
    problems = validate_against_schema(report, RESULT_SCHEMA)
    if problems:
        raise RuntimeError(
            "result violates evaluation-result.schema.json:\n  " + "\n  ".join(problems)
        )
    return report


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def render_markdown(report: dict) -> str:
    lines = [
        f"# Evaluation report: {report['manifest']['name']}",
        "",
        f"Tool aep_eval {report['tool']['version']} (git {report['tool']['git_sha'] or 'n/a'}), "
        f"created {report['created_at']}. Manifest `{report['manifest']['path']}` "
        f"(sha256 `{report['manifest']['sha256']}`).",
        "",
        "## Aggregates",
        "",
        "| Metric | Profile | Method | n | Value |",
        "|---|---|---|---:|---:|",
    ]
    for agg in report["aggregates"]:
        value = (
            _fmt(agg["value"])
            if agg["metric"] == "cer"
            else f"{agg['value']}/{agg['n_fixtures']} valid"
        )
        lines.append(
            f"| {agg['metric']} | {agg['profile'] or ''} | {agg['method']} | {agg['n_fixtures']} | {value} |"
        )
    lines += [
        "",
        "## Results",
        "",
        "| Fixture | Metric | Status | Value | n | Profile | Reference class | Maturity |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['fixture_id']} | {r['metric']} | {r['status']} | {_fmt(r['value'])} | "
            f"{r['n']} | {r['profile'] or ''} | {r['reference_class']} | {r['maturity']} |"
        )
    lines += ["", "## Errors", ""]
    if report["errors"]:
        lines += [
            f"- {e['fixture_id']} ({e['stage']}): {e['message']}"
            for e in report["errors"]
        ]
    else:
        lines.append("none")
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "report.md"
    write_atomic(json_path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    write_atomic(md_path, render_markdown(report))
    return json_path, md_path
