"""TEI conformance check: well-formedness, TEI header, RelaxNG validity.

The RelaxNG schema is a mandatory parameter; there is no default target
because the validation schema is a per-project decision (ADR-005). Generic
TEI validity against the named schema and project-specific editorial
conformance stay separate statements; this module only makes the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
MAX_ERRORS = 20


@dataclass
class TeiCheckResult:
    path: Path
    schema_path: Path
    well_formed: bool
    has_tei_header: bool
    valid: bool
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "valid" if self.valid else "invalid"

    def to_dict(self) -> dict:
        return {
            "well_formed": self.well_formed,
            "has_tei_header": self.has_tei_header,
            "schema": self.schema_path.name,
            "errors": self.errors[:MAX_ERRORS],
            "error_count": len(self.errors),
        }


def load_schema(schema_path: Path) -> etree.RelaxNG:
    """Parse a RelaxNG schema; a missing or unparsable schema is a fail-fast error."""
    if not schema_path.exists():
        raise FileNotFoundError(f"RelaxNG schema not found: {schema_path}")
    try:
        return etree.RelaxNG(etree.parse(str(schema_path)))
    except (etree.XMLSyntaxError, etree.RelaxNGParseError) as exc:
        raise ValueError(f"invalid RelaxNG schema {schema_path}: {exc}") from exc


def check_tei(
    path: Path, schema_path: Path, schema: etree.RelaxNG | None = None
) -> TeiCheckResult:
    """Check one file; `schema` may be passed pre-parsed to avoid re-parsing
    a large schema for every file of a fixture set."""
    rng = schema if schema is not None else load_schema(schema_path)
    try:
        doc = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        return TeiCheckResult(
            path, schema_path, False, False, False, [f"not well-formed: {exc}"]
        )
    root = doc.getroot()
    has_header = any(etree.QName(el).localname == "teiHeader" for el in root.iter())
    if rng.validate(doc):
        return TeiCheckResult(path, schema_path, True, has_header, True)
    errors = [f"line {e.line}: {e.message}" for e in rng.error_log]
    return TeiCheckResult(path, schema_path, True, has_header, False, errors)
