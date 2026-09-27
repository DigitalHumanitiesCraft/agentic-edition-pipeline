"""Generate TEI-XML from validated transcriptions.

Generation is deterministic: well-formed TEI from string templates (no lxml
builder), which keeps the output predictable and diffable. No model runs in
this step, so it needs no API key, and the validation report documents the
deterministic origin (operator decision, 2026-08-24). Entity annotation by a
model is a separate concern and is not part of this script.

Every generated file is validated for well-formedness and plaintext
preservation before it is written. The TEI goes to results/tei/{id}.xml, the
candidate that schema validation, step 6 and the publication check read. The
validation report goes to results/reports/{id}_validation.json, the run's
errors.json to results/reports/.

The header carries only declared values. The language comes from the
document metadata or knowledge/01_PROJECT.md, and langUsage is omitted when
neither declares one. Without a publisher in 01_PROJECT.md the
publicationStmt says so in prose instead of naming an invented publisher.

An existing TEI file with identical bytes is skipped unless --force. The
report records the SHA-256 of the TEI bytes this step last wrote; an existing
file with other bytes, or without a recorded digest, was edited or enriched
elsewhere and is replaced only with --force.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import re
from datetime import date as calendar_date
from pathlib import Path

from lxml import etree

import contract
from config import (
    NS,
    RESULTS_REPORTS_DIR,
    RESULTS_TEI_DIR,
    TEI_NS,
    VALIDATED_DIR,
    ItemFailure,
    add_selection_args,
    configure_console,
    ensure_dirs,
    finish_run,
    load_checked_json,
    ordered_page_images,
    project_info,
    provenance_meta,
    read_json,
    safe_xml_parser,
    select_ids,
    source_image_state,
    source_image_state_hash,
    write_json_atomic,
    write_text_atomic,
)
from markers import MARKER_PATTERN
from review_state import add_tei_edits

# XML escaping, used throughout instead of an XML builder


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


def _derivation_hashes(data: dict, project: dict) -> dict[str, str]:
    """Hashes of the validated input and the project configuration.

    The TEI header and the validation report both carry them and must agree.
    """
    return {
        "validation_state_hash": contract.canonical_hash(data),
        "project_config_hash": contract.canonical_hash(project),
    }


def _diplomatic(project: dict) -> bool:
    """Line breaks are meaning-bearing unless a normalised edition is declared."""
    return "normalis" not in project.get("edition_type", "").lower()


# TEI generation (deterministic)


def _derivation_note(transcription_meta: dict, hashes: dict[str, str]) -> str:
    """The escaped text of the derivation change in revisionDesc."""
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
            + contract.canonical_hash(transcription_meta["executed_prompts"])
        )
    details.append("validation_state_hash=" + hashes["validation_state_hash"])
    details.append("project_config_hash=" + hashes["project_config_hash"])
    return (
        "Deterministic TEI generation from the supplied transcription."
        " Transcription provenance: " + "; ".join(details) + "."
        " The timestamp identifies the validated input state used for derivation."
    )


def _publication_lines(project: dict) -> list[str]:
    """The content of publicationStmt from the declared project fields."""
    publisher = _esc(project.get("publisher", ""))
    license_text = _esc(project.get("license", ""))
    if publisher:
        lines = [f"        <publisher>{publisher}</publisher>"]
        if license_text:
            lines.append(
                f"        <availability><licence>{license_text}</licence></availability>"
            )
        return lines
    # TEI admits availability only after a publishing agency, so without a
    # declared publisher the statement becomes prose and keeps the licence.
    lines = ["        <p>No publisher is declared in knowledge/01_PROJECT.md.</p>"]
    if license_text:
        lines.append(f"        <p>Licence: {license_text}</p>")
    return lines


def _ms_desc_lines(object_id: str, doc_meta: dict) -> list[str]:
    """The msDesc block: repository, shelfmark, object ID and origin date."""
    repository = _esc(doc_meta.get("repository", ""))
    signature = _esc(doc_meta.get("signature", ""))
    date_value = doc_meta.get("date", "")
    lines = ["        <msDesc>", "          <msIdentifier>"]
    if repository:
        lines.append(f"            <repository>{repository}</repository>")
    if signature:
        lines.append(f'            <idno type="shelfmark">{signature}</idno>')
    lines += [
        f'            <idno type="object-id">{_esc(object_id)}</idno>',
        "          </msIdentifier>",
    ]
    if date_value:
        date_when = _esc(_date_when(date_value))
        when_attr = f' when="{date_when}"' if date_when else ""
        lines += [
            "          <history>",
            "            <origin>",
            f"              <origDate{when_attr}>{_esc(date_value)}</origDate>",
            "            </origin>",
            "          </history>",
        ]
    lines.append("        </msDesc>")
    return lines


def _build_tei_header(
    object_id: str,
    doc_meta: dict,
    project: dict,
    transcription_meta: dict,
    input_state_timestamp: str,
    hashes: dict[str, str],
    review_status: str,
) -> str:
    """Build the <teiHeader> as a string."""
    title = _esc(doc_meta.get("title") or object_id)
    editor = _esc(project.get("editor", ""))
    language = _esc(doc_meta.get("language") or project.get("language", ""))
    status = _esc(review_status)

    lines = [
        "  <teiHeader>",
        "    <fileDesc>",
        "      <titleStmt>",
        f"        <title>{title}</title>",
    ]
    if editor:
        lines.append(f"        <editor>{editor}</editor>")
    lines += ["      </titleStmt>", "      <publicationStmt>"]
    lines += _publication_lines(project)
    lines += ["      </publicationStmt>", "      <sourceDesc>"]
    lines += _ms_desc_lines(object_id, doc_meta)
    lines += ["      </sourceDesc>", "    </fileDesc>"]
    if language:
        lines += [
            "    <profileDesc>",
            f'      <langUsage><language ident="{language}">{language}</language></langUsage>',
            "    </profileDesc>",
        ]
    lines += [
        "    <encodingDesc>",
        "      <projectDesc><p>Generated by agentic-edition-pipeline.</p></projectDesc>",
        "    </encodingDesc>",
        f'    <revisionDesc status="{status}">',
        f'      <change when="{_esc(input_state_timestamp)}" status="{status}">'
        f"{_derivation_note(transcription_meta, hashes)}</change>",
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


def _facs_pointer(
    page_num: int, object_id: str, source_images: list[str], facs_ids: dict
) -> str:
    """Point a page break only to a declared remote or actual local image."""
    if page_num in facs_ids:
        return f"#{facs_ids[page_num]}"
    if 1 <= page_num <= len(source_images):
        filename = source_images[page_num - 1]
        if Path(filename).name == filename:
            return f"../images/{_esc(object_id)}/{_esc(filename)}"
    return ""


def _page_lines(page: dict, diplomatic: bool) -> list[str]:
    """The body lines after one page break, by page type (data contract).

    page_type "blank"               -- declared empty page, nothing after pb
    page_type "foreign_text"        -- text of another author, kept out of
                                       the edited body as <note type="foreign">
    page_type "gate_low_resolution" -- image quality gate, marked with a note
    foreign_paragraphs [indices]    -- 0-based paragraph indices excluded as
                                       foreign on an otherwise edited page
    """
    text = page.get("transcription", "")
    page_type = page.get("page_type", "")
    lines: list[str] = []

    if page_type == "foreign_text":
        for paragraph in re.split(r"\n{2,}", text.strip()):
            content = _paragraph_xml(paragraph, diplomatic)
            if content:
                lines.append(f'        <note type="foreign">{content}</note>')
        return lines

    if page_type == "gate_low_resolution":
        reason = (
            page.get("notes", "").strip()
            or "Image resolution insufficient for diplomatic transcription."
        )
        lines.append(
            f'        <note type="gate" subtype="low_resolution">{_esc(reason)}</note>'
        )
        # Structure-only transcription (if any) still enters the body below.

    if not text.strip():
        # Distinguish a declared blank page from an undeclared empty entry,
        # so verification can tell a real blank from a silent merge gap.
        if page_type not in ("blank", "gate_low_resolution"):
            lines.append(
                '        <note type="empty">Empty page without declared page_type; '
                "verify against the facsimile.</note>"
            )
        return lines

    foreign_idx = set(page.get("foreign_paragraphs", []))
    for idx, para in enumerate(re.split(r"\n{2,}", text.strip())):
        content = _paragraph_xml(para, diplomatic)
        if not content:
            continue
        tag, attrs = ("note", ' type="foreign"') if idx in foreign_idx else ("p", "")
        lines.append(f"        <{tag}{attrs}>{content}</{tag}>")
    return lines


def _build_body(
    pages: list[dict],
    object_id: str,
    source_images: list[str],
    facs_ids: dict,
    diplomatic: bool,
) -> str:
    """Build <text><body>...</body></text> from transcription pages."""
    body_lines = ["  <text>", "    <body>", "      <div>"]
    for page in pages:
        page_num = page.get("page", 0)
        facs = _facs_pointer(page_num, object_id, source_images, facs_ids)
        facs_attr = f' facs="{facs}"' if facs else ""
        body_lines.append(f'        <pb n="{page_num}"{facs_attr}/>')
        body_lines += _page_lines(page, diplomatic)
    body_lines += ["      </div>", "    </body>", "  </text>"]
    return "\n".join(body_lines)


REVIEW_STATUS_ORDER = contract.REVIEW_STATUSES


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
    """Assemble the complete TEI-XML document from a validated (step-4) file.

    data must satisfy contract.validated_file_violations; its _meta
    timestamp identifies the validated input state and transcription_meta
    keeps the transcription provenance distinct from this stage.
    """
    pages = data["pages"]
    doc_meta = data.get("metadata", {})
    header = _build_tei_header(
        object_id,
        doc_meta,
        project,
        data["transcription_meta"],
        data["_meta"]["timestamp"],
        _derivation_hashes(data, project),
        document_review_status(pages),
    )
    facsimile, facs_ids = _build_facsimile(pages, doc_meta)
    source_images = data.get("source_images", [])
    if not isinstance(source_images, list) or not all(
        isinstance(filename, str) for filename in source_images
    ):
        source_images = []
    body = _build_body(pages, object_id, source_images, facs_ids, _diplomatic(project))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<TEI xmlns="{TEI_NS}">',
        header,
    ]
    if facsimile:
        parts.append(facsimile)
    parts += [body, "</TEI>", ""]
    return add_tei_edits("\n".join(parts), pages)


# Validation of generated TEI


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


def _canonical_marker(match: re.Match) -> str:
    """Spell an illegible marker as the TEI round trip reconstructs it."""
    if match["illegible"] is None:
        return match[0]
    return f"[... ~{match['quantity']} chars]" if match["quantity"] else "[...]"


def _comparison_text(text: str, preserve_line_breaks: bool) -> str:
    """Normalize incidental whitespace while preserving declared text structure."""
    text = MARKER_PATTERN.sub(_canonical_marker, text)
    if not preserve_line_breaks:
        return re.sub(r"\s+", " ", text).strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(
        re.sub(r"[\t \f\v]+", " ", line).strip() for line in text.split("\n")
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plaintext_report(
    root: etree._Element, original_pages: list[dict], preserve_line_breaks: bool
) -> dict:
    """Compare every page as an ordered character sequence.

    Layout whitespace is normalized first, and marker elements are
    reconstructed to the shared transcription syntax before comparison.
    """
    body = root.find(".//tei:body", NS)
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
    mismatched = [
        number
        for (number, source), generated_page in zip(original, generated, strict=False)
        if generated_page != (number, source)
    ]
    if len(original) != len(generated):
        mismatched.extend(number for number, _text in original[len(generated) :])
        mismatched.extend(number for number, _text in generated[len(original) :])

    original_text = "\n\f\n".join(text for _number, text in original)
    tei_text = "\n\f\n".join(text for _number, text in generated)
    return {
        "plaintext_exact": original == generated,
        "page_count_original": len(original),
        "page_count_tei": len(generated),
        "mismatched_pages": mismatched,
        "plaintext_similarity": difflib.SequenceMatcher(
            None, original_text, tei_text, autojunk=False
        ).ratio(),
        "original_character_count": len(original_text),
        "tei_character_count": len(tei_text),
    }


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
    try:
        root = etree.fromstring(xml_str.encode("utf-8"), safe_xml_parser())
    except etree.XMLSyntaxError as exc:
        report["well_formed_error"] = str(exc)
        return report
    report["well_formed"] = True

    required = ["tei:teiHeader", ".//tei:fileDesc", ".//tei:text", ".//tei:body"]
    missing = [tag for tag in required if root.find(tag, NS) is None]
    if not root.tag.endswith("}TEI") and root.tag != "TEI":
        missing.append("TEI")
    report["required_elements"] = not missing
    if missing:
        report["missing_elements"] = missing

    report.update(_plaintext_report(root, original_pages, preserve_line_breaks))
    return report


# Main processing


def _verify_facsimile_state(object_id: str, transcription_meta: dict) -> None:
    """Raise ItemFailure when the current images differ from the bound state."""
    declared_image_state = transcription_meta.get("source_images")
    if declared_image_state is None:
        return
    try:
        current_images = ordered_page_images(
            object_id, expected_pages=len(declared_image_state)
        )
        current_image_state = source_image_state(current_images)
    except (OSError, ValueError) as exc:
        raise ItemFailure(
            "source_state", f"Cannot verify transcription facsimiles: {exc}"
        ) from exc
    if current_image_state != declared_image_state or source_image_state_hash(
        current_image_state
    ) != transcription_meta.get("source_images_hash"):
        raise ItemFailure(
            "source_state",
            "Current facsimiles differ from the transcription source state",
        )


def _report_failure(report: dict) -> None:
    """Raise ItemFailure when the validation report blocks the TEI output."""
    if not report["well_formed"]:
        raise ItemFailure(
            "validate",
            f"Generated TEI is not well-formed: {report['well_formed_error']}",
        )
    if not report["required_elements"]:
        raise ItemFailure(
            "validate",
            "Generated TEI lacks required elements: "
            + ", ".join(report["missing_elements"]),
        )
    if not report["plaintext_exact"]:
        raise ItemFailure(
            "validate",
            "Generated TEI does not preserve the ordered page transcription",
        )


def _recorded_tei_digest(report_path: Path) -> str:
    """The SHA-256 of the TEI bytes step 5 last wrote, or "" when none is known."""
    try:
        report = read_json(report_path)
    except (OSError, ValueError):
        return ""
    meta = report.get("_meta") if isinstance(report, dict) else None
    digest = meta.get("tei_sha256") if isinstance(meta, dict) else None
    return digest if isinstance(digest, str) else ""


def _write_tei(path: Path, xml_str: str) -> None:
    try:
        write_text_atomic(path, xml_str)
    except OSError as exc:
        raise ItemFailure("write", f"Could not write TEI {path}: {exc}") from exc


def _replace_tei(path: Path, xml_str: str, recorded_digest: str, force: bool) -> str:
    """Write the checked TEI unless that would destroy bytes step 5 did not write.

    Returns the SHA-256 of the TEI now in place. Without force, an existing
    file must carry exactly the bytes whose digest the last report recorded,
    so hand-enriched TEI is never replaced silently.
    """
    generated = xml_str.encode("utf-8")
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise ItemFailure("read", f"Cannot read existing TEI {path}: {exc}") from exc
    if not force and existing == generated:
        print(f"  SKIP {path.stem} (output matches the validated input)")
        return hashlib.sha256(generated).hexdigest()
    if (
        not force
        and existing is not None
        and hashlib.sha256(existing).hexdigest() != recorded_digest
    ):
        raise ItemFailure(
            "write",
            f"Existing TEI {path} is not the file step 5 last wrote (edited, "
            "enriched or without a recorded digest); rerun with --force to "
            "replace it",
        )
    _write_tei(path, xml_str)
    print(f"  OK   {path.stem}")
    return hashlib.sha256(generated).hexdigest()


def annotate_one(
    object_id: str,
    project: dict,
    validate_only: bool,
    force: bool,
    *,
    validated_dir: Path | None = None,
    tei_dir: Path | None = None,
    reports_dir: Path | None = None,
) -> None:
    """Generate, check and write the TEI of one validated object.

    The directories default at call time to the module globals
    VALIDATED_DIR, RESULTS_TEI_DIR and RESULTS_REPORTS_DIR. The validation
    report is written in every mode once the TEI could be generated;
    validate_only stops before the TEI is written. Raises ItemFailure
    (stages contract, read, source_state, generate, validate, write).
    """
    validated_dir = validated_dir or VALIDATED_DIR
    tei_dir = tei_dir or RESULTS_TEI_DIR
    reports_dir = reports_dir or RESULTS_REPORTS_DIR
    report_path = reports_dir / f"{object_id}_validation.json"
    tei_digest = _recorded_tei_digest(report_path)
    data = load_checked_json(
        validated_dir, object_id, contract.validated_file_violations
    )
    _verify_facsimile_state(object_id, data["transcription_meta"])

    try:
        xml_str = generate_tei(object_id, data, project)
        report = validate_tei(xml_str, data["pages"], _diplomatic(project))
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise ItemFailure("generate", f"TEI generation failed: {exc}") from exc
    report["object_id"] = object_id
    report["source"] = str(validated_dir / f"{object_id}.json")
    # No provider, model or prompt template: the TEI is generated
    # deterministically, and the report says only what actually ran.
    report["_meta"] = {
        **provenance_meta(script="05_annotate_tei.py", step=5),
        **_derivation_hashes(data, project),
    }
    # The report is written on every exit, and a run that writes no TEI
    # carries the earlier digest forward so the overwrite guard stays armed.
    try:
        _report_failure(report)
        if validate_only:
            print(f"  VALID {object_id}")
        else:
            tei_digest = _replace_tei(
                tei_dir / f"{object_id}.xml", xml_str, tei_digest, force
            )
    finally:
        if tei_digest:
            report["_meta"]["tei_sha256"] = tei_digest
        try:
            write_json_atomic(report_path, report)
        except OSError as exc:
            raise ItemFailure("write", str(exc)) from exc


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Generate TEI-XML from validated transcriptions."
    )
    add_selection_args(parser)
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
    project = project_info()
    candidates = [
        path.stem
        for path in sorted(VALIDATED_DIR.glob("*.json"))
        if path.stem != "errors"
    ]
    objects = select_ids(candidates, args.object, args.all, args.sample)

    mode = "validate-only" if args.validate_only else "deterministic"
    print(f"Generating TEI for {len(objects)} object(s) [{mode}]\n")

    errors: list[dict] = []
    for object_id in objects:
        try:
            annotate_one(object_id, project, args.validate_only, args.force)
        except ItemFailure as failure:
            errors.append(
                {
                    "object_id": object_id,
                    "error": failure.message,
                    "stage": failure.stage,
                }
            )

    # An object whose TEI could not be produced is a failed run, not a result.
    finish_run(
        errors,
        RESULTS_REPORTS_DIR,
        len(objects),
        "05_annotate_tei.py",
        summary=(
            f"\nDone. {len(objects)} object(s): {len(objects) - len(errors)} "
            f"succeeded, {len(errors)} failed."
        ),
    )


if __name__ == "__main__":
    main()
