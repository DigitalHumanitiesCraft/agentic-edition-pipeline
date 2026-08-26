"""Generate TEI-XML from validated transcriptions.

Generation is deterministic: well-formed TEI from string templates (no lxml
builder), which keeps the output predictable and diffable. No model runs in
this step, so it needs no API key, and the validation report documents the
deterministic origin (operator decision, 2026-08-24). Entity annotation by a
model is a separate concern and is not part of this script.

Every generated file is validated for well-formedness and plaintext
preservation. A validation report is written to results/reports/.

Outputs go to two locations: data/processed/tei/ (working copy the pipeline
reads in later steps) and results/tei/ (publication-ready copy).

Idempotent: existing TEI files are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as calendar_date
from datetime import datetime, timezone
from pathlib import Path

from config import (
    RESULTS_REPORTS_DIR,
    RESULTS_TEI_DIR,
    TEI_DIR,
    TRANSCRIPTIONS_DIR,
    VALIDATED_DIR,
    ensure_dirs,
    provenance_meta,
    read_knowledge,
    write_errors,
)

# ---------------------------------------------------------------------------
# XML escaping -- used throughout instead of an XML builder
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """Escape the four XML-significant characters. Handles None gracefully."""
    if not text:
        return ""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _date_when(value: str) -> str:
    """Return a validated TEI/W3C date value, or empty for free-text dates."""
    year_match = re.fullmatch(r"([0-9]{4})", value)
    if year_match:
        year = int(year_match.group(1))
        return value if 1 <= year <= 9999 else ""

    month_match = re.fullmatch(r"([0-9]{4})-([0-9]{2})", value)
    if month_match:
        year, month = (int(part) for part in month_match.groups())
        return value if 1 <= year <= 9999 and 1 <= month <= 12 else ""

    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return ""
    try:
        calendar_date.fromisoformat(value)
    except ValueError:
        return ""
    return value


# ---------------------------------------------------------------------------
# Project metadata extraction from knowledge/01_PROJECT.md
# ---------------------------------------------------------------------------

def _extract_project_info(md_text: str) -> dict:
    """Pull structured fields out of the 01_PROJECT.md markdown table.

    Looks for key-value rows in markdown tables (| Key | Value |) and
    falls back to the first H1/H2 heading for the title.
    """
    info: dict[str, str] = {}

    # Try to find markdown table rows: | key | value |
    for match in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", md_text, re.MULTILINE):
        key = match.group(1).strip().lower()
        val = match.group(2).strip()
        if val == "---" or key == "---":
            continue
        if "projektname" in key or "title" in key or "titel" in key:
            info["title"] = val
        elif "herausgeber" in key or "editor" in key:
            info["editor"] = val
        elif "institution" in key or "publisher" in key or "verlag" in key:
            info["publisher"] = val
        elif "lizenz" in key or "license" in key:
            info["license"] = val
        elif "sprache" in key or "language" in key or "lang" in key:
            info["language"] = val
        elif "editionstyp" in key or "edition type" in key:
            info["edition_type"] = val

    # Fallback: first heading
    if "title" not in info:
        heading = re.search(r"^#{1,2}\s+(.+)", md_text, re.MULTILINE)
        if heading:
            info["title"] = heading.group(1).strip()

    return info


# ---------------------------------------------------------------------------
# TEI generation (deterministic)
# ---------------------------------------------------------------------------

def _build_tei_header(
    object_id: str,
    doc_meta: dict,
    project: dict,
    language: str,
    model: str,
    prompt_template: str,
) -> str:
    """Build the <teiHeader> as a string."""
    title = _esc(doc_meta.get("title", object_id))
    editor = _esc(project.get("editor", ""))
    publisher = _esc(project.get("publisher", ""))
    license_text = _esc(project.get("license", ""))
    lang = _esc(language or doc_meta.get("language", "de"))
    repository = _esc(doc_meta.get("repository", ""))
    date_value = str(doc_meta.get("date", "") or "")
    date = _esc(date_value)
    date_when = _esc(_date_when(date_value))
    timestamp = datetime.now(timezone.utc).isoformat()

    lines = [
        "  <teiHeader>",
        "    <fileDesc>",
        "      <titleStmt>",
        f"        <title>{title}</title>",
    ]
    if editor:
        lines.append(f"        <editor>{editor}</editor>")
    lines += [
        "      </titleStmt>",
        "      <publicationStmt>",
    ]
    if publisher:
        lines.append(f"        <publisher>{publisher}</publisher>")
    else:
        lines.append("        <publisher>agentic-edition-pipeline</publisher>")
    if license_text:
        lines.append(f"        <availability><licence>{license_text}</licence></availability>")
    lines += [
        "      </publicationStmt>",
        "      <sourceDesc>",
        "        <msDesc>",
        "          <msIdentifier>",
    ]
    if repository:
        lines.append(f"            <repository>{repository}</repository>")
    lines += [
        f"            <idno>{_esc(object_id)}</idno>",
        "          </msIdentifier>",
    ]
    if date:
        orig_date = (
            f'<origDate when="{date_when}">{date}</origDate>'
            if date_when
            else f"<origDate>{date}</origDate>"
        )
        lines += [
            "          <history>",
            "            <origin>",
            f"              {orig_date}",
            "            </origin>",
            "          </history>",
        ]
    lines += [
        "        </msDesc>",
        "      </sourceDesc>",
        "    </fileDesc>",
        "    <profileDesc>",
        f'      <langUsage><language ident="{lang}">{lang}</language></langUsage>',
        "    </profileDesc>",
        "    <encodingDesc>",
        "      <projectDesc><p>Generated by agentic-edition-pipeline.</p></projectDesc>",
        "    </encodingDesc>",
        "    <revisionDesc>",
        f'      <change when="{timestamp}" who="#machine">'
        f"Automated TEI generation (model={_esc(model)}, template={_esc(prompt_template)})"
        f"</change>",
        "    </revisionDesc>",
        "  </teiHeader>",
    ]
    return "\n".join(lines)


def _build_facsimile(pages: list[dict], doc_meta: dict) -> tuple[str, dict]:
    """Build a <facsimile> block from remote image URLs in the metadata.

    metadata.image_urls maps page numbers (JSON keys, as strings) to URLs;
    a plain list aligned with page order is also accepted. Returns the XML
    string (empty when no URLs exist) and a page-number to xml:id map.
    """
    urls = doc_meta.get("image_urls")
    entries: list[tuple[int, str]] = []

    if isinstance(urls, dict):
        for p in pages:
            key = str(p.get("page", ""))
            if urls.get(key):
                entries.append((p.get("page", 0), urls[key]))
    elif isinstance(urls, list):
        for i, p in enumerate(pages):
            if i < len(urls) and urls[i]:
                entries.append((p.get("page", i + 1), urls[i]))

    if not entries:
        return "", {}

    facs_ids: dict[int, str] = {}
    lines = ["  <facsimile>"]
    for page_num, url in entries:
        fid = f"facs_{page_num}"
        facs_ids[page_num] = fid
        lines.append(f'    <graphic xml:id="{fid}" url="{_esc(url)}"/>')
    lines.append("  </facsimile>")
    return "\n".join(lines), facs_ids


def _paragraph_xml(para: str, diplomatic: bool) -> str:
    """Render one paragraph, keeping line breaks as <lb/> for diplomatic editions."""
    if diplomatic:
        lines = [_esc(ln.strip()) for ln in para.split("\n") if ln.strip()]
        return "<lb/>".join(lines)
    return _esc(re.sub(r"\s*\n\s*", " ", para).strip())


def _build_body(pages: list[dict], object_id: str, facs_ids: dict, diplomatic: bool) -> str:
    """Build <text><body>...</body></text> from transcription pages.

    Page-level fields evaluated here (data contract):
      page_type "blank"               -- declared empty page, pb only
      page_type "foreign_text"        -- text of another author, kept out of
                                         the edited body as <note type="foreign">
      page_type "gate_low_resolution" -- image quality gate, marked with a note
      foreign_paragraphs [indices]    -- 0-based paragraph indices excluded as
                                         foreign on an otherwise edited page
    """
    body_lines = ["  <text>", "    <body>", "      <div>"]

    for p in pages:
        page_num = p.get("page", 0)
        text = p.get("transcription", "")
        page_type = p.get("page_type", "")
        notes = p.get("notes", "")

        # Page break: point to the facsimile graphic when one exists,
        # otherwise to the conventional local image path.
        if page_num in facs_ids:
            facs = f"#{facs_ids[page_num]}"
        else:
            facs = f"images/{object_id}/{object_id}_p{page_num:03d}.png"
        body_lines.append(f'        <pb n="{page_num}" facs="{facs}"/>')

        if page_type == "foreign_text":
            if text.strip():
                body_lines.append(
                    f'        <note type="foreign">{_esc(text.strip())}</note>'
                )
            continue

        if page_type == "gate_low_resolution":
            reason = notes.strip() or "Image resolution insufficient for diplomatic transcription."
            body_lines.append(
                f'        <note type="gate" subtype="low_resolution">{_esc(reason)}</note>'
            )
            # Structure-only transcription (if any) still enters the body below.

        if not text.strip():
            # Distinguish a declared blank page from an undeclared empty entry,
            # so verification can tell a real blank from a silent merge gap.
            if page_type not in ("blank", "gate_low_resolution"):
                body_lines.append(
                    '        <note type="empty">Empty page without declared page_type; '
                    "verify against the facsimile.</note>"
                )
            continue

        foreign_idx = set(p.get("foreign_paragraphs", []))
        paragraphs = re.split(r"\n{2,}", text.strip())
        for idx, para in enumerate(paragraphs):
            content = _paragraph_xml(para, diplomatic)
            if not content:
                continue
            if idx in foreign_idx:
                body_lines.append(f'        <note type="foreign">{content}</note>')
            else:
                body_lines.append(f"        <p>{content}</p>")

    body_lines += ["      </div>", "    </body>", "  </text>"]
    return "\n".join(body_lines)


def generate_tei(object_id: str, data: dict, project: dict) -> str:
    """Assemble the complete TEI-XML document as a string."""
    pages = data.get("pages", [])
    doc_meta = data.get("metadata", {})
    language = doc_meta.get("language", "de")

    # Determine model/prompt info for revisionDesc
    meta = data.get("_meta", {})
    model = meta.get("model", "deterministic")
    prompt_template = meta.get("prompt_template", "")

    # Line breaks are meaning-bearing in a diplomatic transcription; only a
    # declared normalised edition type joins lines with spaces.
    edition_type = project.get("edition_type", "").lower()
    diplomatic = "normalis" not in edition_type

    header = _build_tei_header(object_id, doc_meta, project, language, model, prompt_template)
    facsimile, facs_ids = _build_facsimile(pages, doc_meta)
    body = _build_body(pages, object_id, facs_ids, diplomatic)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
        header,
    ]
    if facsimile:
        parts.append(facsimile)
    parts += [body, "</TEI>", ""]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Validation of generated TEI
# ---------------------------------------------------------------------------

def validate_tei(xml_str: str, original_pages: list[dict]) -> dict:
    """Check well-formedness, required elements, and plaintext preservation.

    Returns a report dict with pass/fail for each check.
    """
    report: dict = {"well_formed": False, "required_elements": False, "plaintext_similarity": 0.0}

    # Well-formedness via lxml
    try:
        from lxml import etree
        root = etree.fromstring(xml_str.encode("utf-8"))
        report["well_formed"] = True
    except Exception as exc:
        report["well_formed"] = False
        report["well_formed_error"] = str(exc)
        return report

    # Required elements
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    required = ["tei:teiHeader", ".//tei:fileDesc", ".//tei:text", ".//tei:body"]
    missing = [tag for tag in required if root.find(tag, ns) is None]
    # Also check root tag
    if not root.tag.endswith("}TEI") and root.tag != "TEI":
        missing.append("TEI")
    report["required_elements"] = len(missing) == 0
    if missing:
        report["missing_elements"] = missing

    # Plaintext preservation: compare word sets between original and TEI body
    body = root.find(".//tei:body", ns)
    if body is not None:
        # Extract all text from body
        tei_text = " ".join(body.itertext())
        tei_words = set(tei_text.split())
    else:
        tei_words = set()

    original_text = " ".join(p.get("transcription", "") for p in original_pages)
    original_words = set(original_text.split())

    if original_words or tei_words:
        intersection = original_words & tei_words
        union = original_words | tei_words
        report["plaintext_similarity"] = len(intersection) / len(union) if union else 1.0
    else:
        # Both empty -- that is a valid match
        report["plaintext_similarity"] = 1.0

    report["original_word_count"] = len(original_words)
    report["tei_word_count"] = len(tei_words)

    return report


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def _find_input(object_id: str) -> Path | None:
    """Locate the input JSON, preferring validated/ over transcriptions/."""
    validated = VALIDATED_DIR / f"{object_id}.json"
    if validated.exists():
        return validated
    transcribed = TRANSCRIPTIONS_DIR / f"{object_id}.json"
    if transcribed.exists():
        return transcribed
    return None


def annotate_one(
    object_id: str,
    project: dict,
    validate_only: bool,
    force: bool,
) -> dict | None:
    """Generate TEI for one object. Returns error dict on failure, None on success."""
    src = _find_input(object_id)
    if src is None:
        return {
            "object_id": object_id,
            "error": f"No input found in {VALIDATED_DIR} or {TRANSCRIPTIONS_DIR}",
            "stage": "read",
        }

    dst_working = TEI_DIR / f"{object_id}.xml"
    dst_final = RESULTS_TEI_DIR / f"{object_id}.xml"

    if dst_working.exists() and not force and not validate_only:
        print(f"  SKIP {object_id} (already exists, use --force to regenerate)")
        return None

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"object_id": object_id, "error": str(exc), "stage": "read"}

    # Generate TEI
    xml_str = generate_tei(object_id, data, project)

    # Validate
    pages = data.get("pages", [])
    report = validate_tei(xml_str, pages)
    report["object_id"] = object_id
    report["source"] = str(src)
    # No provider, model or prompt template: the TEI is generated
    # deterministically, and the report says only what actually ran.
    report["_meta"] = provenance_meta(script="05_annotate_tei.py", step=5)

    # Write validation report
    report_path = RESULTS_REPORTS_DIR / f"{object_id}_validation.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if validate_only:
        status = "VALID" if report["well_formed"] and report["required_elements"] else "INVALID"
        print(f"  {status} {object_id} (similarity={report['plaintext_similarity']:.2%})")
        return None

    if not report["well_formed"]:
        return {
            "object_id": object_id,
            "error": f"Generated TEI is not well-formed: {report.get('well_formed_error', '?')}",
            "stage": "validate",
        }

    # Write TEI to both locations
    dst_working.parent.mkdir(parents=True, exist_ok=True)
    dst_final.parent.mkdir(parents=True, exist_ok=True)
    dst_working.write_text(xml_str, encoding="utf-8")
    dst_final.write_text(xml_str, encoding="utf-8")

    sim = report["plaintext_similarity"]
    sim_label = "OK" if sim > 0.95 else "WARN" if sim > 0.80 else "LOW"
    print(f"  OK   {object_id} (similarity={sim:.2%} [{sim_label}])")
    return None


def collect_objects(
    single: str | None,
    all_flag: bool,
    sample: int | None,
) -> list[str]:
    """Resolve which objects to process from CLI arguments."""
    if single:
        return [single]

    # Collect from validated/ first, fall back to transcriptions/
    candidates: set[str] = set()
    for d in [VALIDATED_DIR, TRANSCRIPTIONS_DIR]:
        if d.exists():
            for f in d.glob("*.json"):
                if f.stem != "errors":
                    candidates.add(f.stem)

    ids = sorted(candidates)
    if not ids:
        print(f"No input files found in {VALIDATED_DIR} or {TRANSCRIPTIONS_DIR}", file=sys.stderr)
        sys.exit(1)

    if sample is not None:
        ids = ids[:sample]

    if not all_flag and sample is None:
        print("Specify --object ID, --all, or --sample N", file=sys.stderr)
        sys.exit(1)

    return ids


def main():
    parser = argparse.ArgumentParser(
        description="Generate TEI-XML from validated transcriptions."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Process a single object by ID")
    group.add_argument("--all", action="store_true", help="Process all available objects")
    group.add_argument("--sample", metavar="N", type=int, help="Process first N objects (for testing)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Accepted for compatibility; generation is always deterministic")
    parser.add_argument("--validate-only", action="store_true", help="Generate and validate but do not write TEI")
    parser.add_argument("--force", action="store_true", help="Regenerate even if output exists")
    args = parser.parse_args()

    ensure_dirs()

    # Load project info once
    project_md = read_knowledge("01_PROJECT.md")
    project = _extract_project_info(project_md)

    objects = collect_objects(args.object, args.all, args.sample)

    mode = "validate-only" if args.validate_only else "deterministic"
    print(f"Generating TEI for {len(objects)} object(s) [{mode}]\n")

    errors: list[dict] = []
    for oid in objects:
        err = annotate_one(oid, project, args.validate_only, args.force)
        if err:
            errors.append(err)
            print(f"  FAIL {err['object_id']}: {err['error']}")

    if errors:
        write_errors(errors, TEI_DIR)
        print(f"\n{len(errors)} error(s) written to {TEI_DIR / 'errors.json'}")

    ok = len(objects) - len(errors)
    print(f"\nDone. {len(objects)} object(s): {ok} succeeded, {len(errors)} failed.")

    # An object whose TEI could not be produced is a failed run, not a result.
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
