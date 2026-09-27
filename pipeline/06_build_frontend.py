"""Build the static frontend from TEI-XML files.

Scans results/tei/ for TEI files, extracts metadata and text content using
lxml, and writes JSON data files that the viewer reads at runtime. The viewer
itself (HTML/CSS/JS in docs/) is static and pre-existing -- this script only
generates the data layer.

Outputs:
  docs/data/catalog.json   -- project-level index of all objects
  docs/data/{object_id}.json -- per-object data with pages, text, image paths
  docs/tei/{object_id}.xml -- downloadable mirror of the gated TEI candidate
  docs/images/{object_id}/ -- verified local facsimile snapshots

object_record, catalog_entry, catalog_digest and catalog_document are the
single builders of these records; the local review server calls them too, so
a review save and a later build write identical bytes. Objects are ordered by
casefolded ID on every operating system.

A TEI candidate whose step-5 report (results/reports/{id}_validation.json)
names another validation_state_hash than the TEI's derivation is left over
from a failed regeneration and is not published. External TEI without a
report is published. The run's errors.json goes to results/frontend/, not to
docs/data/, because it is a local diagnostic: Pages publishes docs/, and a
failing build never deploys anyway.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import re
import shutil
import sys
from pathlib import Path

from lxml import etree

import contract
from config import (
    DOCS_DIR,
    RESULTS_DIR,
    RESULTS_REPORTS_DIR,
    RESULTS_TEI_DIR,
    TEI_NS,
    ItemFailure,
    configure_console,
    ensure_dirs,
    finish_run,
    is_link_or_reparse_point,
    json_bytes,
    list_page_images,
    ordered_page_images,
    project_info,
    read_json,
    safe_path,
    safe_xml_parser,
    source_image_state,
    source_image_state_hash,
    write_bytes_atomic,
)
from review_state import workflow

ERRORS_DIR = RESULTS_DIR / "frontend"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _text_of(element: etree._Element | None) -> str:
    """Get the text content of an element, or empty string if None."""
    if element is None:
        return ""
    return (element.text or "").strip()


def extract_metadata(root: etree._Element) -> dict:
    """Extract catalog metadata and the human review status from teiHeader."""
    meta: dict[str, str] = {}
    meta["title"] = _text_of(root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title"))

    date_el = root.find(f".//{{{TEI_NS}}}origDate")
    if date_el is None:
        date_el = root.find(f".//{{{TEI_NS}}}sourceDesc//{{{TEI_NS}}}date")
    if date_el is None:
        date_el = root.find(f".//{{{TEI_NS}}}date")
    meta["date"] = (
        (date_el.get("when", "") or _text_of(date_el)) if date_el is not None else ""
    )

    lang_el = root.find(f".//{{{TEI_NS}}}langUsage/{{{TEI_NS}}}language")
    meta["language"] = (
        (lang_el.get("ident", "") or _text_of(lang_el)) if lang_el is not None else ""
    )

    revision = root.find(f".//{{{TEI_NS}}}revisionDesc")
    meta["status"] = revision.get("status", "") if revision is not None else ""
    signature = root.find(
        f".//{{{TEI_NS}}}msIdentifier/{{{TEI_NS}}}idno[@type='shelfmark']"
    )
    meta["signature"] = _text_of(signature)
    change = root.find(f".//{{{TEI_NS}}}revisionDesc/{{{TEI_NS}}}change")
    change_text = "" if change is None else "".join(change.itertext())
    meta["input_state_timestamp"] = change.get("when", "") if change is not None else ""
    for key in ("source_images_hash", "validation_state_hash"):
        found = re.search(rf"\b{key}=([0-9a-f]{{12}})\b", change_text)
        meta[key] = found.group(1) if found else ""
    return meta


def _normalize_page_text(text: str) -> str:
    """Normalize display whitespace collected from the parsed XML tree."""
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _local_name(element: etree._Element) -> str:
    """Return the namespace-independent local name of an XML element."""
    return etree.QName(element).localname


def extract_facsimile_urls(root: etree._Element) -> dict[str, str]:
    """Map '#xml:id' references to remote URLs from the <facsimile> block."""
    urls: dict[str, str] = {}
    for graphic in root.findall(f".//{{{TEI_NS}}}facsimile/{{{TEI_NS}}}graphic"):
        gid = graphic.get(XML_ID, "")
        url = graphic.get("url", "")
        if gid and url:
            urls[f"#{gid}"] = url
    return urls


def extract_pages(root: etree._Element) -> list[dict]:
    """Extract pages in document order from any namespace-prefix spelling.

    TEI ``pb/@n`` is an arbitrary source label, so the viewer uses document
    order as its numeric sequence and preserves ``@n`` separately as label.
    A TEI body without page breaks becomes one viewer page.
    """
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        return []

    facs_urls = extract_facsimile_urls(root)

    page_parts: list[list[str]] = []
    pages: list[dict] = []
    current_parts: list[str] | None = None

    def start_page(page_break: etree._Element | None = None) -> None:
        nonlocal current_parts
        sequence = len(pages) + 1
        label = page_break.get("n", "") if page_break is not None else ""
        facs_pointer = page_break.get("facs", "") if page_break is not None else ""
        current_parts = []
        page_parts.append(current_parts)
        pages.append(
            {
                "page": sequence,
                "label": label or str(sequence),
                "text": "",
                "image": facs_urls.get(facs_pointer, facs_pointer),
            }
        )

    def append_text(value: str | None) -> None:
        if current_parts is not None and value:
            current_parts.append(value)

    def walk(element: etree._Element) -> None:
        append_text(element.text)
        for child in element:
            name = _local_name(child)
            if name == "pb":
                start_page(child)
            elif name == "lb":
                append_text("\n")
            else:
                walk(child)
                if name in {"p", "ab", "head", "item", "note"}:
                    append_text("\n\n")
            append_text(child.tail)

    has_page_breaks = any(_local_name(element) == "pb" for element in body.iter())
    if not has_page_breaks:
        start_page()
    walk(body)

    for page, parts in zip(pages, page_parts, strict=True):
        page["text"] = _normalize_page_text("".join(parts))
    return pages


def publication_dir(*parts: str, docs_dir: Path | None = None) -> Path:
    """Return a directory below docs/ reached without any link or reparse point.

    docs_dir defaults to DOCS_DIR at call time. The directory need not exist.
    """
    docs_dir = docs_dir or DOCS_DIR
    target = "/".join(parts)
    if is_link_or_reparse_point(docs_dir):
        raise ValueError(
            f"refusing publication through symlink or reparse point: {docs_dir}"
        )
    try:
        return safe_path(docs_dir, Path(*parts))
    except ValueError as exc:
        raise ValueError(
            f"refusing publication path docs/{target} through symlink or "
            f"reparse point or outside docs: {exc}"
        ) from exc


def _facsimiles(
    object_id: str, pages: list[dict], expected_source_hash: str, docs_dir: Path
) -> dict[str, bytes]:
    """Set each page's viewer image and return the files docs/images/{id}/ needs.

    Remote URLs (from <facsimile> graphic url) are kept when the TEI binds no
    image hash; the viewer renders them directly. Local images from the
    shared image resolver, or the committed snapshot under docs/images/{id}/
    in a clean checkout, are mapped to pages by order. A TEI that binds a
    source-image hash accepts only exactly those bytes.
    """
    image_dir = publication_dir("images", object_id, docs_dir=docs_dir)
    local_files = ordered_page_images(object_id)
    if not local_files and image_dir.is_dir():
        local_files = list_page_images(image_dir)
    state = source_image_state(local_files)
    if expected_source_hash and source_image_state_hash(state) != expected_source_hash:
        raise ValueError(
            "current facsimiles differ from the transcription source state"
        )

    files: dict[str, bytes] = {}
    for index, page in enumerate(pages):
        if not expected_source_hash and page["image"].startswith(
            ("http://", "https://")
        ):
            continue
        if index >= len(local_files):
            page["image"] = ""
            continue
        source = local_files[index]
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != state[index]["sha256"]:
            raise ValueError(f"facsimile changed while it was being read: {source}")
        page["image"] = f"images/{object_id}/{source.name}"
        files[source.name] = content
    return files


def object_record(
    object_id: str, source: bytes, docs_dir: Path | None = None
) -> tuple[dict, dict[str, bytes]]:
    """Build the viewer record of one TEI document without writing anything.

    Returns the record for docs/data/{id}.json and the facsimile files, by
    name, that docs/images/{id}/ must hold for it. Raises ItemFailure with
    stage "read" for unparseable TEI and "source_state" when the facsimiles
    do not match the TEI's bound image state.
    """
    try:
        root = etree.fromstring(source, safe_xml_parser())
    except etree.XMLSyntaxError as exc:
        raise ItemFailure("read", f"XML parse error: {exc}") from exc
    meta = extract_metadata(root)
    pages = extract_pages(root)
    try:
        images = _facsimiles(
            object_id, pages, meta["source_images_hash"], docs_dir or DOCS_DIR
        )
    except (OSError, ValueError) as exc:
        raise ItemFailure("source_state", f"facsimile contract: {exc}") from exc
    record = {
        "_meta": {
            "script": "06_build_frontend.py",
            "source_hash": hashlib.sha256(source).hexdigest()[:12],
            "input_state_timestamp": meta["input_state_timestamp"],
        },
        "id": object_id,
        # The viewer falls back to the ID itself, so the record keeps the
        # TEI's actual (possibly empty) title.
        "title": meta["title"],
        "date": meta["date"],
        "language": meta["language"],
        "signature": meta["signature"],
        "status": meta["status"],
        "pages": pages,
        "has_images": any(page["image"] for page in pages),
        "workflow": workflow(root),
    }
    return record, images


def catalog_entry(record: dict) -> dict:
    """The catalog row of one object record."""
    return {
        "id": record["id"],
        "title": record["title"],
        "date": record["date"],
        "language": record["language"],
        "signature": record["signature"],
        "status": record["status"],
        "page_count": len(record["pages"]),
        "has_images": record["has_images"],
    }


def _object_order(object_id: str) -> str:
    return object_id.casefold()


def catalog_digest(project_title: str, sources: dict[str, bytes]) -> str:
    """Hash the project title and every published TEI in catalog order."""
    digest = hashlib.sha256(project_title.encode("utf-8"))
    for object_id in sorted(sources, key=_object_order):
        digest.update(f"{object_id}.xml".encode())
        digest.update(sources[object_id])
    return digest.hexdigest()[:12]


def catalog_document(
    project: dict, records: list[dict], sources: dict[str, bytes]
) -> dict:
    """Assemble catalog.json from the published records and their TEI bytes.

    project is the project_info() mapping; sources maps each record's ID to
    the TEI bytes it was built from.
    """
    title = project.get("title", "Digital Edition")
    ordered = sorted(records, key=lambda record: _object_order(record["id"]))
    return {
        "_meta": {
            "script": "06_build_frontend.py",
            "source_hash": catalog_digest(title, sources),
            "input_state_timestamp": max(
                (record["_meta"]["input_state_timestamp"] for record in ordered),
                default="",
            ),
        },
        "project": title,
        "objects": [catalog_entry(record) for record in ordered],
    }


def _check_current_derivation(object_id: str, source: bytes) -> None:
    """Refuse TEI that an unsuccessful later step-5 run left behind."""
    report_path = RESULTS_REPORTS_DIR / f"{object_id}_validation.json"
    if not report_path.exists() and not report_path.is_symlink():
        return
    try:
        report = read_json(report_path)
        expected = report["_meta"]["validation_state_hash"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ItemFailure(
            "stale", f"cannot read step-5 report {report_path}: {exc}"
        ) from exc
    try:
        root = etree.fromstring(source, safe_xml_parser())
    except etree.XMLSyntaxError as exc:
        raise ItemFailure("read", f"XML parse error: {exc}") from exc
    if extract_metadata(root)["validation_state_hash"] != expected:
        raise ItemFailure(
            "stale",
            "TEI does not derive from the validated state its step-5 report "
            "names; regenerate it with step 5 before publishing",
        )


def _publish_images(object_id: str, files: dict[str, bytes]) -> None:
    """Make docs/images/{id}/ hold exactly the given facsimile files."""
    image_dir = publication_dir("images", object_id)
    if files:
        image_dir.mkdir(parents=True, exist_ok=True)
        image_dir = publication_dir("images", object_id)
    for name, content in files.items():
        target = image_dir / name
        if not target.is_file() or target.read_bytes() != content:
            write_bytes_atomic(target, content)
    if not image_dir.is_dir():
        return
    for stale in image_dir.iterdir():
        if is_link_or_reparse_point(stale) or not stale.is_file():
            raise ValueError(f"refusing unexpected facsimile publication path: {stale}")
        if stale.name not in files:
            stale.unlink()


def _write_if_changed(path: Path, content: bytes) -> bool:
    """Replace a publication file unless it already has these bytes."""
    if is_link_or_reparse_point(path):
        raise ValueError(f"refusing publication file through link: {path}")
    if path.is_file() and path.read_bytes() == content:
        return False
    write_bytes_atomic(path, content)
    return True


def _process_tei(tei_path: Path) -> tuple[dict, bytes]:
    object_id = tei_path.stem
    if not contract.valid_object_id(object_id):
        raise ItemFailure("contract", "object ID is not path-safe")
    try:
        source = tei_path.read_bytes()
    except OSError as exc:
        raise ItemFailure("read", str(exc)) from exc
    _check_current_derivation(object_id, source)
    record, images = object_record(object_id, source)
    try:
        _publish_images(object_id, images)
    except (OSError, ValueError) as exc:
        raise ItemFailure("publish", f"facsimile publication: {exc}") from exc
    return record, source


def process_tei(tei_path: Path) -> dict:
    """Publish one TEI candidate's facsimiles and return its viewer record.

    Raises ItemFailure naming the cause (stages contract, read, stale,
    source_state, publish).
    """
    return _process_tei(tei_path)[0]


def _publish_object(tei_path: Path) -> tuple[dict, bytes]:
    """Publish one object's facsimiles, TEI download and data file."""
    record, source = _process_tei(tei_path)
    try:
        _write_if_changed(publication_dir("tei") / tei_path.name, source)
        changed = _write_if_changed(
            publication_dir("data") / f"{record['id']}.json", json_bytes(record)
        )
    except (OSError, ValueError) as exc:
        raise ItemFailure("publish", str(exc)) from exc
    print(
        f"  {'OK  ' if changed else 'SKIP'} {record['id']} ({len(record['pages'])} "
        f"pages, images={'yes' if record['has_images'] else 'no'})"
    )
    return record, source


def _remove_stale_assets(published_ids: set[str]) -> None:
    """Remove object data, TEI downloads and facsimiles this build did not publish."""
    for name, suffix in (("data", ".json"), ("tei", ".xml")):
        directory = publication_dir(name)
        directory.mkdir(parents=True, exist_ok=True)
        for asset in publication_dir(name).glob(f"*{suffix}"):
            if asset.stem in published_ids or asset.name == "catalog.json":
                continue
            if is_link_or_reparse_point(asset) or not asset.is_file():
                raise ValueError(f"refusing stale publication path: {asset}")
            asset.unlink()

    images_root = publication_dir("images")
    if not images_root.is_dir():
        return
    for object_dir in images_root.iterdir():
        if object_dir.name in published_ids:
            continue
        if is_link_or_reparse_point(object_dir):
            raise ValueError(f"refusing stale frontend image path: {object_dir}")
        if not object_dir.is_dir():
            continue
        for descendant in object_dir.rglob("*"):
            if is_link_or_reparse_point(descendant):
                raise ValueError(
                    f"refusing linked stale frontend image path: {descendant}"
                )
        shutil.rmtree(object_dir)


def _write_catalog(records: list[dict], sources: dict[str, bytes]) -> Path:
    catalog_path = publication_dir("data") / "catalog.json"
    _write_if_changed(
        catalog_path, json_bytes(catalog_document(project_info(), records, sources))
    )
    return catalog_path


def build_all() -> tuple[list[dict], int]:
    """Publish every TEI candidate and write the catalog.

    Returns the item-level error records and the candidate count, so a
    missing object cannot look like a clean build and one broken input does
    not suppress the remaining objects. Raises ValueError when the candidate
    set itself is unusable (no TEI, colliding IDs).
    """
    tei_files = sorted(
        RESULTS_TEI_DIR.glob("*.xml"), key=lambda path: _object_order(path.stem)
    )
    if not tei_files:
        _remove_stale_assets(set())
        raise ValueError(f"No TEI files found in {RESULTS_TEI_DIR}")
    id_problems = contract.unique_object_id_violations(
        [path.stem for path in tei_files]
    )
    if id_problems:
        raise ValueError("; ".join(id_problems))

    print(f"Building frontend data from {len(tei_files)} TEI file(s)\n")
    records: list[dict] = []
    sources: dict[str, bytes] = {}
    errors: list[dict] = []
    for tei_path in tei_files:
        try:
            record, source = _publish_object(tei_path)
        except ItemFailure as failure:
            errors.append(
                {
                    "object_id": tei_path.stem,
                    "error": failure.message,
                    "stage": failure.stage,
                }
            )
            continue
        records.append(record)
        sources[record["id"]] = source

    _remove_stale_assets(set(sources))
    catalog_path = _write_catalog(records, sources)
    print(f"\nCatalog written to {catalog_path} ({len(records)} objects)")
    return errors, len(tei_files)


def serve(port: int = 8080) -> None:
    """Serve docs/ on the loopback interface only."""
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(DOCS_DIR)
    )
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    print(f"\nServing docs/ at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Build static frontend from TEI-XML files."
    )
    parser.add_argument(
        "--serve", action="store_true", help="Start local HTTP server on port 8080"
    )
    args = parser.parse_args()

    ensure_dirs()
    try:
        errors, total = build_all()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    # A TEI file that could not be published leaves a hole in the edition,
    # so the run fails instead of serving an incomplete one.
    finish_run(
        errors,
        ERRORS_DIR,
        total,
        "06_build_frontend.py",
        summary=f"\nDone. {total - len(errors)} of {total} object(s) published.",
    )
    if args.serve:
        serve()


if __name__ == "__main__":
    main()
