"""Generate TEI-XML from validated transcriptions.

Generation is deterministic: well-formed TEI from string templates (no lxml
builder), which keeps the output predictable and diffable. No model runs in
this step, so it needs no API key, and the validation report documents the
deterministic origin (operator decision, 2026-08-24). Entity annotation by a
model is a separate concern and is not part of this script.

Every generated file is validated for well-formedness and plaintext
preservation. A validation report is written to results/reports/.

Outputs go to two locations: data/processed/tei/ (working copy the pipeline
reads in later steps) and results/tei/ (candidate copy for project gates).

Idempotent: existing TEI files are skipped unless --force.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import date as calendar_date
from pathlib import Path

import contract
from config import (
    RESULTS_REPORTS_DIR,
    RESULTS_TEI_DIR,
    TEI_DIR,
    VALIDATED_DIR,
    ensure_dirs,
    ordered_page_images,
    provenance_meta,
    read_knowledge,
    source_image_state,
    source_image_state_hash,
    write_errors,
    write_json_atomic,
    write_text_atomic,
)

# ---------------------------------------------------------------------------
# XML escaping -- used throughout instead of an XML builder
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    """Escape the four XML-significant characters. Handles None gracefully."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
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


def _stable_hash(value: object) -> str:
    """Hash one JSON-compatible configuration value deterministically."""
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


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
    transcription_meta: dict,
    input_state_timestamp: str,
    validation_state_hash: str,
    review_status: str,
) -> str:
    """Build the <teiHeader> as a string."""
    title = _esc(doc_meta.get("title") or object_id)
    editor = _esc(project.get("editor", ""))
    publisher = _esc(project.get("publisher", ""))
    license_text = _esc(project.get("license", ""))
    lang = _esc(language or doc_meta.get("language") or "de")
    repository = _esc(doc_meta.get("repository", ""))
    signature = _esc(doc_meta.get("signature", ""))
    date_value = str(doc_meta.get("date", "") or "")
    date = _esc(date_value)
    date_when = _esc(_date_when(date_value))
    provenance_fields = (
        ("provider", "provider"),
        ("model", "model"),
        ("prompt", "prompt_template"),
        ("profile", "prompt_profile"),
        ("instruction_hash", "prompt_hash"),
        ("source_images_hash", "source_images_hash"),
    )
    details = [
        f"{label}={_esc(str(transcription_meta[key]))}"
        for label, key in provenance_fields
        if transcription_meta.get(key) not in (None, "")
    ]
    if transcription_meta.get("executed_prompts"):
        details.append(
            "executed_prompts_hash="
            + _stable_hash(transcription_meta["executed_prompts"])
        )
    details.append("validation_state_hash=" + validation_state_hash)
    details.append("project_config_hash=" + _stable_hash(project))
    change_text = "Deterministic TEI generation from the supplied transcription."
    if details:
        change_text += " Transcription provenance: " + "; ".join(details) + "."
    change_text += (
        " The timestamp identifies the validated input state used for derivation."
    )
    when_attr = (
        f' when="{_esc(input_state_timestamp)}"' if input_state_timestamp else ""
    )

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
        lines.append(
            f"        <availability><licence>{license_text}</licence></availability>"
        )
    lines += [
        "      </publicationStmt>",
        "      <sourceDesc>",
        "        <msDesc>",
        "          <msIdentifier>",
    ]
    if repository:
        lines.append(f"            <repository>{repository}</repository>")
    if signature:
        lines.append(f'            <idno type="shelfmark">{signature}</idno>')
    lines += [
        f'            <idno type="object-id">{_esc(object_id)}</idno>',
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
        f'    <revisionDesc status="{_esc(review_status)}">',
        f'      <change{when_attr} status="{_esc(review_status)}">{change_text}</change>',
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


MARKER_PATTERN = re.compile(
    r"~~(?P<deletion>.+?)~~"
    r"|\{(?P<addition>.+?)\}"
    r"|(?P<illegible>\[\.\.\.(?:\s*~\s*(?P<quantity>\d+)\s*chars?)?\])"
    r"|(?P<unclear>[^\s{}\[\]~]+)\[\?\]"
)


def _marker_xml(text: str) -> str:
    """Map the shared transcription markers to conservative TEI elements."""
    parts: list[str] = []
    cursor = 0
    for match in MARKER_PATTERN.finditer(text):
        parts.append(_esc(text[cursor : match.start()]))
        if match.group("deletion") is not None:
            parts.append(f"<del>{_esc(match.group('deletion'))}</del>")
        elif match.group("addition") is not None:
            parts.append(f"<add>{_esc(match.group('addition'))}</add>")
        elif match.group("illegible") is not None:
            quantity = match.group("quantity")
            extent = f' quantity="{quantity}" unit="character"' if quantity else ""
            parts.append(f'<gap reason="illegible"{extent}/>')
        else:
            parts.append(f"<unclear>{_esc(match.group('unclear'))}</unclear>")
        cursor = match.end()
    parts.append(_esc(text[cursor:]))
    return "".join(parts)


def _paragraph_xml(para: str, diplomatic: bool) -> str:
    """Render one paragraph and map the shared transcription markers."""
    if diplomatic:
        lines = [_marker_xml(line.strip()) for line in para.split("\n") if line.strip()]
        return "<lb/>".join(lines)
    return _marker_xml(re.sub(r"\s*\n\s*", " ", para).strip())


def _build_body(
    pages: list[dict],
    object_id: str,
    source_images: list[str],
    facs_ids: dict,
    diplomatic: bool,
) -> str:
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

        # Page break points only to a declared remote or actual local image.
        if page_num in facs_ids:
            facs = f"#{facs_ids[page_num]}"
        elif 1 <= page_num <= len(source_images):
            filename = source_images[page_num - 1]
            facs = (
                f"../images/{_esc(object_id)}/{_esc(filename)}"
                if Path(filename).name == filename
                else ""
            )
        else:
            facs = ""
        facs_attr = f' facs="{facs}"' if facs else ""
        body_lines.append(f'        <pb n="{page_num}"{facs_attr}/>')

        if page_type == "foreign_text":
            for paragraph in re.split(r"\n{2,}", text.strip()):
                content = _paragraph_xml(paragraph, diplomatic)
                if content:
                    body_lines.append(f'        <note type="foreign">{content}</note>')
            continue

        if page_type == "gate_low_resolution":
            reason = (
                notes.strip()
                or "Image resolution insufficient for diplomatic transcription."
            )
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


REVIEW_STATUS_ORDER = (
    "machine_unreviewed",
    "in_review",
    "human_verified",
    "accepted",
)


def document_review_status(pages: list[dict]) -> str:
    """Return the least mature declared page status for the TEI header."""
    statuses = []
    for page in pages:
        review = page.get("review", {})
        status = review.get("status") if isinstance(review, dict) else None
        if status not in REVIEW_STATUS_ORDER:
            status = "machine_unreviewed"
        statuses.append(status)
    if not statuses:
        return "machine_unreviewed"
    return min(statuses, key=REVIEW_STATUS_ORDER.index)


def generate_tei(object_id: str, data: dict, project: dict) -> str:
    """Assemble the complete TEI-XML document as a string."""
    pages = data.get("pages", [])
    doc_meta = data.get("metadata", {})
    language = doc_meta.get("language") or "de"

    # Keep transcription provenance distinct from this deterministic stage.
    meta = data.get("_meta", {})
    transcription_meta = data.get("transcription_meta", meta)
    input_state_timestamp = meta.get("timestamp", "")
    validation_state_hash = _stable_hash(data)
    review_status = document_review_status(pages)

    # Line breaks are meaning-bearing in a diplomatic transcription; only a
    # declared normalised edition type joins lines with spaces.
    edition_type = project.get("edition_type", "").lower()
    diplomatic = "normalis" not in edition_type

    header = _build_tei_header(
        object_id,
        doc_meta,
        project,
        language,
        transcription_meta,
        input_state_timestamp,
        validation_state_hash,
        review_status,
    )
    facsimile, facs_ids = _build_facsimile(pages, doc_meta)
    source_images = data.get("source_images", [])
    if not isinstance(source_images, list) or not all(
        isinstance(filename, str) for filename in source_images
    ):
        source_images = []
    body = _build_body(pages, object_id, source_images, facs_ids, diplomatic)

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


def _local_name(tag: str) -> str:
    """Return an XML local name without importing a second tree library."""
    return tag.rsplit("}", 1)[-1]


def _inline_with_markers(element) -> str:
    """Reconstruct the transcription marker syntax from a TEI element."""
    parts = [element.text or ""]
    for child in element:
        name = _local_name(child.tag)
        if name == "lb":
            rendered = "\n"
        elif name == "del":
            rendered = f"~~{_inline_with_markers(child)}~~"
        elif name == "add":
            rendered = f"{{{_inline_with_markers(child)}}}"
        elif name == "unclear":
            rendered = f"{_inline_with_markers(child)}[?]"
        elif name == "gap" and child.get("reason") == "illegible":
            quantity = child.get("quantity")
            rendered = f"[... ~{quantity} chars]" if quantity else "[...]"
        else:
            rendered = _inline_with_markers(child)
        parts.append(rendered)
        parts.append(child.tail or "")
    return "".join(parts)


def _tei_page_texts(body) -> list[tuple[int, str]]:
    """Extract ordered page texts while excluding generated verification notes."""
    pages: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    for element in body.iter():
        if element is body:
            continue
        name = _local_name(element.tag)
        if name == "pb":
            number = element.get("n", "")
            if not number.isdigit():
                continue
            current = []
            pages.append((int(number), current))
            continue
        if current is None or name not in {"p", "note"}:
            continue
        if name == "note" and element.get("type") in {"gate", "empty"}:
            continue
        current.append(_inline_with_markers(element).strip())
    return [
        (number, "\n\n".join(part for part in parts if part)) for number, parts in pages
    ]


def _comparison_text(text: str, preserve_line_breaks: bool) -> str:
    """Normalize incidental whitespace while preserving declared text structure."""
    text = re.sub(
        r"\[\.\.\.\s*~\s*(\d+)\s*chars?\]",
        lambda match: f"[... ~{match.group(1)} chars]",
        text,
    )
    if not preserve_line_breaks:
        return re.sub(r"\s+", " ", text).strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(
        re.sub(r"[\t \f\v]+", " ", line).strip() for line in text.split("\n")
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def validate_tei(
    xml_str: str,
    original_pages: list[dict],
    preserve_line_breaks: bool = True,
) -> dict:
    """Check well-formedness, required elements, and plaintext preservation.

    Returns a report dict with pass/fail for each check.
    """
    report: dict = {
        "well_formed": False,
        "required_elements": False,
        "plaintext_exact": False,
        "plaintext_similarity": 0.0,
    }

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

    # Plaintext preservation: compare every page as an ordered character
    # sequence after layout-whitespace normalization. Marker elements are
    # reconstructed to the shared transcription syntax before comparison.
    body = root.find(".//tei:body", ns)
    tei_pages = _tei_page_texts(body) if body is not None else []
    original = [
        (
            page.get("page"),
            _comparison_text(page.get("transcription", ""), preserve_line_breaks),
        )
        for page in original_pages
    ]
    generated = [
        (number, _comparison_text(text, preserve_line_breaks))
        for number, text in tei_pages
    ]
    report["plaintext_exact"] = original == generated
    report["page_count_original"] = len(original)
    report["page_count_tei"] = len(generated)
    report["mismatched_pages"] = [
        number
        for (number, source), generated_page in zip(original, generated, strict=False)
        if generated_page != (number, source)
    ]
    if len(original) != len(generated):
        report["mismatched_pages"].extend(
            number for number, _text in original[len(generated) :]
        )
        report["mismatched_pages"].extend(
            number for number, _text in generated[len(original) :]
        )

    original_text = "\n\f\n".join(text for _number, text in original)
    tei_text = "\n\f\n".join(text for _number, text in generated)
    report["plaintext_similarity"] = difflib.SequenceMatcher(
        None, original_text, tei_text, autojunk=False
    ).ratio()
    report["original_character_count"] = len(original_text)
    report["tei_character_count"] = len(tei_text)

    return report


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def _find_input(object_id: str) -> Path | None:
    """Locate the validated input JSON required by the TEI checkpoint."""
    validated = VALIDATED_DIR / f"{object_id}.json"
    if validated.exists():
        return validated
    return None


def _existing_outputs_match(xml_str: str, paths: tuple[Path, Path]) -> bool:
    """Check that both stored TEI copies are identical and well formed."""
    expected = xml_str.encode("utf-8")
    try:
        from lxml import etree

        for path in paths:
            if path.read_bytes() != expected:
                return False
            etree.parse(str(path))
    except (FileNotFoundError, OSError, etree.XMLSyntaxError):
        return False
    return True


def annotate_one(
    object_id: str,
    project: dict,
    validate_only: bool,
    force: bool,
) -> dict | None:
    """Generate TEI for one object. Returns error dict on failure, None on success."""
    if not contract.valid_object_id(object_id):
        return {
            "object_id": str(object_id),
            "error": "object_id is not a path-safe identifier",
            "stage": "contract",
        }
    src = _find_input(object_id)
    if src is None:
        return {
            "object_id": object_id,
            "error": f"No validated input found in {VALIDATED_DIR}",
            "stage": "read",
        }

    dst_working = TEI_DIR / f"{object_id}.xml"
    dst_final = RESULTS_TEI_DIR / f"{object_id}.xml"

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"object_id": object_id, "error": str(exc), "stage": "read"}

    violations = contract.validated_file_violations(data)
    if isinstance(data, dict) and data.get("object_id") != object_id:
        violations.append(
            f"object_id {data.get('object_id')!r} does not match filename {object_id!r}"
        )
    if violations:
        return {
            "object_id": object_id,
            "error": "Input violates the data contract: " + "; ".join(violations),
            "stage": "contract",
        }

    transcription_meta = data.get("transcription_meta", {})
    declared_image_state = transcription_meta.get("source_images")
    if declared_image_state is not None:
        try:
            current_images = ordered_page_images(
                object_id,
                expected_pages=len(declared_image_state),
            )
            current_image_state = source_image_state(current_images)
        except (OSError, ValueError) as exc:
            return {
                "object_id": object_id,
                "error": f"Cannot verify transcription facsimiles: {exc}",
                "stage": "source_state",
            }
        if current_image_state != declared_image_state or source_image_state_hash(
            current_image_state
        ) != transcription_meta.get("source_images_hash"):
            return {
                "object_id": object_id,
                "error": "Current facsimiles differ from the transcription source state",
                "stage": "source_state",
            }

    try:
        xml_str = generate_tei(object_id, data, project)
        pages = data.get("pages", [])
        preserve_line_breaks = "normalis" not in project.get("edition_type", "").lower()
        report = validate_tei(xml_str, pages, preserve_line_breaks)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        return {
            "object_id": object_id,
            "error": f"TEI generation failed: {exc}",
            "stage": "generate",
        }
    report["object_id"] = object_id
    report["source"] = str(src)
    # No provider, model or prompt template: the TEI is generated
    # deterministically, and the report says only what actually ran.
    report["_meta"] = provenance_meta(script="05_annotate_tei.py", step=5)
    report["_meta"]["project_config_hash"] = _stable_hash(project)
    report["_meta"]["validation_state_hash"] = _stable_hash(data)

    # Write validation report
    report_path = RESULTS_REPORTS_DIR / f"{object_id}_validation.json"
    try:
        write_json_atomic(report_path, report)
    except OSError as exc:
        return {"object_id": object_id, "error": str(exc), "stage": "write"}

    if validate_only:
        valid = (
            report["well_formed"]
            and report["required_elements"]
            and report["plaintext_exact"]
        )
        status = "VALID" if valid else "INVALID"
        print(
            f"  {status} {object_id} (similarity={report['plaintext_similarity']:.2%})"
        )
        if valid:
            return None
        return {
            "object_id": object_id,
            "error": "Generated TEI failed deterministic validation",
            "stage": "validate",
        }

    if not report["well_formed"]:
        return {
            "object_id": object_id,
            "error": f"Generated TEI is not well-formed: {report.get('well_formed_error', '?')}",
            "stage": "validate",
        }
    if not report["required_elements"] or not report["plaintext_exact"]:
        return {
            "object_id": object_id,
            "error": "Generated TEI does not preserve the ordered page transcription",
            "stage": "validate",
        }

    if not force and _existing_outputs_match(xml_str, (dst_working, dst_final)):
        print(f"  SKIP {object_id} (outputs match the validated input)")
        return None

    # Write TEI to both locations
    dst_working.parent.mkdir(parents=True, exist_ok=True)
    dst_final.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_text_atomic(dst_working, xml_str)
        write_text_atomic(dst_final, xml_str)
    except OSError as exc:
        return {
            "object_id": object_id,
            "error": (
                f"Could not write synchronized TEI outputs {dst_working} and "
                f"{dst_final}: {exc}"
            ),
            "stage": "write",
        }

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

    candidates = {
        path.stem for path in VALIDATED_DIR.glob("*.json") if path.stem != "errors"
    }

    ids = sorted(candidates)
    if not ids:
        print(f"No validated input files found in {VALIDATED_DIR}", file=sys.stderr)
        sys.exit(1)
    problems = contract.unique_object_id_violations(ids)
    if problems:
        print("ERROR: " + "; ".join(problems), file=sys.stderr)
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
    group.add_argument(
        "--all", action="store_true", help="Process all available objects"
    )
    group.add_argument(
        "--sample", metavar="N", type=int, help="Process first N objects (for testing)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Generate and validate but do not write TEI",
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate even if output exists"
    )
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

    write_errors(errors, TEI_DIR)
    if errors:
        print(f"\n{len(errors)} error(s) written to {TEI_DIR / 'errors.json'}")

    ok = len(objects) - len(errors)
    print(f"\nDone. {len(objects)} object(s): {ok} succeeded, {len(errors)} failed.")

    # An object whose TEI could not be produced is a failed run, not a result.
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
