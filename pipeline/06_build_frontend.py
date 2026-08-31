"""Build the static frontend from TEI-XML files.

Scans results/tei/ for TEI files, extracts metadata and text content using
lxml, and writes JSON data files that the viewer reads at runtime. The viewer
itself (HTML/CSS/JS in docs/) is static and pre-existing -- this script only
generates the data layer.

Outputs:
  docs/data/catalog.json   -- project-level index of all objects
  docs/data/{object_id}.json -- per-object data with pages, text, image paths
  docs/tei/{object_id}.xml -- downloadable mirror of the gated TEI candidate
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

from lxml import etree

import contract
from config import (
    DOCS_DATA_DIR,
    DOCS_DIR,
    DOCS_TEI_DIR,
    PROJECT_ROOT,
    RESULTS_TEI_DIR,
    ensure_dirs,
    list_page_images,
    ordered_page_images,
    read_knowledge,
    source_image_state_hash,
    write_bytes_atomic,
    write_errors,
    write_json_atomic,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}


# ---------------------------------------------------------------------------
# Project name extraction
# ---------------------------------------------------------------------------


def _extract_project_name(md_text: str) -> str:
    """Get the project name from 01_PROJECT.md.

    Checks for a 'Projektname' row in a markdown table first, then falls
    back to the first heading.
    """
    for match in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", md_text, re.MULTILINE):
        key = match.group(1).strip().lower()
        val = match.group(2).strip()
        if val == "---":
            continue
        if "projektname" in key or "title" in key or "titel" in key:
            return val

    heading = re.search(r"^#{1,2}\s+(.+)", md_text, re.MULTILINE)
    if heading:
        return heading.group(1).strip()

    return "Digital Edition"


# ---------------------------------------------------------------------------
# TEI metadata extraction
# ---------------------------------------------------------------------------


def _text_of(element: etree._Element | None) -> str:
    """Get the text content of an element, or empty string if None."""
    if element is None:
        return ""
    return (element.text or "").strip()


def extract_metadata(root: etree._Element) -> dict:
    """Extract catalog metadata and the human review status from teiHeader."""
    meta: dict[str, str] = {}

    # Title from titleStmt
    title_el = root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title")
    meta["title"] = _text_of(title_el)

    # Date: try origDate first, then sourceDesc, then any date element
    date_el = root.find(f".//{{{TEI_NS}}}origDate")
    if date_el is None:
        date_el = root.find(f".//{{{TEI_NS}}}sourceDesc//{{{TEI_NS}}}date")
    if date_el is None:
        date_el = root.find(f".//{{{TEI_NS}}}date")
    if date_el is not None:
        # Prefer @when attribute over text content
        meta["date"] = date_el.get("when", "") or _text_of(date_el)
    else:
        meta["date"] = ""

    # Language from langUsage
    lang_el = root.find(f".//{{{TEI_NS}}}langUsage/{{{TEI_NS}}}language")
    if lang_el is not None:
        meta["language"] = lang_el.get("ident", "") or _text_of(lang_el)
    else:
        meta["language"] = ""

    revision = root.find(f".//{{{TEI_NS}}}revisionDesc")
    meta["status"] = revision.get("status", "") if revision is not None else ""
    signature = root.find(
        f".//{{{TEI_NS}}}msIdentifier/{{{TEI_NS}}}idno[@type='shelfmark']"
    )
    meta["signature"] = _text_of(signature)
    change = root.find(f".//{{{TEI_NS}}}revisionDesc/{{{TEI_NS}}}change")
    change_text = "" if change is None else "".join(change.itertext())
    meta["input_state_timestamp"] = change.get("when", "") if change is not None else ""
    source_hash = re.search(r"\bsource_images_hash=([0-9a-f]{12})\b", change_text)
    meta["source_images_hash"] = source_hash.group(1) if source_hash else ""

    return meta


# ---------------------------------------------------------------------------
# Text extraction -- split by <pb/> into pages
# ---------------------------------------------------------------------------


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
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    for graphic in root.findall(f".//{{{TEI_NS}}}facsimile/{{{TEI_NS}}}graphic"):
        gid = graphic.get(xml_id, "")
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


# ---------------------------------------------------------------------------
# Build data files
# ---------------------------------------------------------------------------


def _validated_docs_image_dir(object_id: str) -> Path:
    """Resolve one object image directory without following linked components."""
    if not contract.valid_object_id(object_id):
        raise ValueError(f"facsimile object ID is not path-safe: {object_id!r}")
    docs_root = DOCS_DIR.absolute()
    images_root = (DOCS_DIR / "images").absolute()
    object_dir = (images_root / object_id).absolute()
    if docs_root not in images_root.parents or images_root not in object_dir.parents:
        raise ValueError(f"facsimile publication directory escaped docs: {object_dir}")
    for component in (docs_root, images_root, object_dir):
        if _is_link_or_reparse_point(component):
            raise ValueError(
                f"refusing facsimile publication through symlink or reparse point: "
                f"{component}"
            )
    resolved_docs = docs_root.resolve()
    resolved_images = images_root.resolve()
    resolved_object = object_dir.resolve()
    if resolved_docs not in resolved_images.parents:
        raise ValueError(f"facsimile image root escaped docs: {images_root}")
    if resolved_images not in resolved_object.parents:
        raise ValueError(f"facsimile object directory escaped image root: {object_dir}")
    return resolved_object


def _attach_images(
    object_id: str,
    pages: list[dict],
    expected_source_hash: str = "",
) -> None:
    """Resolve page images and make them servable from docs/.

    Remote URLs (from <facsimile> graphic url) are kept as-is; the viewer
    renders them directly. Local images resolved via the shared image-root
    resolver are copied to docs/images/{id}/ because the static frontend
    can only serve files below docs/. Page order maps local files to pages.
    """
    docs_image_dir = _validated_docs_image_dir(object_id)
    local_files = ordered_page_images(object_id)
    if not local_files and docs_image_dir.is_dir():
        local_files = list_page_images(docs_image_dir)
    local_bytes = [path.read_bytes() for path in local_files]
    if expected_source_hash:
        byte_state = [
            {
                "page": page,
                "filename": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for page, (path, content) in enumerate(
                zip(local_files, local_bytes, strict=True), start=1
            )
        ]
        actual_hash = source_image_state_hash(byte_state)
        if actual_hash != expected_source_hash:
            raise ValueError(
                "current facsimiles differ from the transcription source state"
            )

    published_filenames: set[str] = set()
    for i, page in enumerate(pages):
        current = page.get("image", "")
        if not expected_source_hash and current.startswith(("http://", "https://")):
            continue
        if i < len(local_files):
            src = local_files[i]
            docs_image_dir.mkdir(parents=True, exist_ok=True)
            docs_image_dir = _validated_docs_image_dir(object_id)
            dst = docs_image_dir / src.name
            content = local_bytes[i]
            if not dst.exists() or dst.read_bytes() != content:
                write_bytes_atomic(dst, content)
            page["image"] = f"images/{object_id}/{src.name}"
            published_filenames.add(src.name)
        else:
            page["image"] = ""

    if docs_image_dir.is_dir():
        docs_image_dir = _validated_docs_image_dir(object_id)
        for stale in docs_image_dir.iterdir():
            if _is_link_or_reparse_point(stale) or not stale.is_file():
                raise ValueError(
                    f"refusing unexpected facsimile publication path: {stale}"
                )
            if stale.name not in published_filenames:
                stale.unlink()


def process_tei(tei_path: Path) -> dict | None:
    """Parse a TEI file and return its data dict, or None on error."""
    try:
        tree = etree.parse(str(tei_path))
    except (etree.XMLSyntaxError, OSError) as exc:
        print(f"  SKIP {tei_path.stem} (XML parse error: {exc})")
        return None

    root = tree.getroot()
    object_id = tei_path.stem
    if not contract.valid_object_id(object_id):
        print(f"  SKIP {object_id!r} (object ID is not path-safe)")
        return None
    meta = extract_metadata(root)
    pages = extract_pages(root)

    try:
        _attach_images(object_id, pages, meta.get("source_images_hash", ""))
    except (OSError, ValueError) as exc:
        print(f"  SKIP {tei_path.stem} (facsimile contract: {exc})")
        return None
    # has_images reflects what the viewer can actually show: a copied local
    # file or a remote facsimile URL on at least one page.
    has_images = any(p.get("image") for p in pages)

    return {
        "_meta": {
            "script": "06_build_frontend.py",
            "source_hash": hashlib.sha256(tei_path.read_bytes()).hexdigest()[:12],
            "input_state_timestamp": meta.get("input_state_timestamp", ""),
        },
        "id": object_id,
        "title": meta.get("title", object_id),
        "date": meta.get("date", ""),
        "language": meta.get("language", ""),
        "signature": meta.get("signature", ""),
        "status": meta.get("status", ""),
        "pages": pages,
        "has_images": has_images,
    }


def _copy_tei_asset(tei_path: Path) -> None:
    """Copy the canonical TEI into the static publication root."""
    publication_dir = _validated_tei_publication_dir()
    publication_dir.mkdir(parents=True, exist_ok=True)
    destination = publication_dir / tei_path.name
    legacy_temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    destination_exists = _validate_publication_file(destination, publication_dir)
    if _validate_publication_file(legacy_temporary, publication_dir):
        legacy_temporary.unlink()
    try:
        if destination_exists and destination.read_bytes() == tei_path.read_bytes():
            return
    except OSError:
        pass

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{tei_path.name}.", suffix=".tmp", dir=publication_dir
    )
    temporary = Path(temporary_name)
    try:
        _validate_publication_file(temporary, publication_dir)
        with os.fdopen(file_descriptor, "wb") as target_handle:
            file_descriptor = -1
            with tei_path.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())

        _validated_tei_publication_dir()
        _validate_publication_file(destination, publication_dir)
        _validate_publication_file(temporary, publication_dir)
        temporary.replace(destination)
    except Exception:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            if _validate_publication_file(temporary, publication_dir):
                temporary.unlink()
        except (OSError, ValueError):
            pass
        raise


def _publish_tei_asset(tei_path: Path) -> None:
    """Publish one TEI asset and report filesystem failures before raising."""
    try:
        _copy_tei_asset(tei_path)
    except OSError as exc:
        print(f"  FAIL {tei_path.stem} (TEI download mirror: {exc})", file=sys.stderr)
        raise


def _is_well_formed_tei(tei_path: Path) -> bool:
    """Check a skipped TEI before exposing it as a download asset."""
    try:
        etree.parse(str(tei_path))
    except etree.XMLSyntaxError as exc:
        print(f"  SKIP {tei_path.stem} (XML parse error: {exc})")
        return False
    return True


def _is_link_or_reparse_point(path: Path) -> bool:
    """Inspect one existing path component without following it."""
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(reparse_flag & attributes)


def _validate_publication_file(path: Path, publication_dir: Path) -> bool:
    """Validate one publication file by lstat without following links."""
    if path.parent != publication_dir:
        raise ValueError(f"publication file escaped its directory: {path}")
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    if stat.S_ISLNK(path_stat.st_mode) or bool(reparse_flag & attributes):
        raise ValueError(
            f"refusing TEI publication file through symlink or reparse point: {path}"
        )
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"TEI publication path is not a regular file: {path}")
    return True


def _validated_tei_publication_dir() -> Path:
    """Return docs/tei only when its complete repository path is trustworthy."""
    project_root = PROJECT_ROOT.absolute()
    docs_root = DOCS_DIR.absolute()
    publication_dir = DOCS_TEI_DIR.absolute()

    if docs_root == project_root or project_root not in docs_root.parents:
        raise ValueError(f"docs directory is outside the project root: {docs_root}")
    if publication_dir == docs_root or docs_root not in publication_dir.parents:
        raise ValueError(
            f"TEI publication directory is outside the docs root: {publication_dir}"
        )

    current = publication_dir
    while True:
        if _is_link_or_reparse_point(current):
            raise ValueError(
                f"refusing TEI publication through symlink or reparse point: {current}"
            )
        if current == project_root:
            break
        current = current.parent

    resolved_project = project_root.resolve()
    resolved_docs = docs_root.resolve()
    resolved_publication = publication_dir.resolve()
    if resolved_project not in resolved_docs.parents:
        raise ValueError(
            f"resolved docs directory escaped the project root: {docs_root}"
        )
    if resolved_docs not in resolved_publication.parents:
        raise ValueError(
            f"resolved TEI publication directory escaped the docs root: {publication_dir}"
        )
    return resolved_publication


def _remove_stale_tei_assets(published_names: set[str]) -> None:
    """Remove downloads that have no successfully processed source in this build."""
    publication_dir = _validated_tei_publication_dir()
    publication_dir.mkdir(parents=True, exist_ok=True)
    publication_dir = _validated_tei_publication_dir()
    for asset in publication_dir.glob("*.xml"):
        if asset.name not in published_names:
            _validated_tei_publication_dir()
            asset.unlink()


def _remove_stale_frontend_assets(published_ids: set[str]) -> None:
    """Remove object data and facsimiles that are no longer publishable."""
    docs_root = DOCS_DIR.resolve()
    data_root = DOCS_DATA_DIR.resolve()
    if docs_root not in data_root.parents:
        raise ValueError(f"frontend data directory is outside docs: {data_root}")
    DOCS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for asset in DOCS_DATA_DIR.glob("*.json"):
        if asset.name in {"catalog.json", "errors.json"} or asset.stem in published_ids:
            continue
        if _is_link_or_reparse_point(asset) or not asset.is_file():
            raise ValueError(f"refusing stale frontend data path: {asset}")
        asset.unlink()

    images_root = DOCS_DIR / "images"
    if not images_root.exists():
        return
    if _is_link_or_reparse_point(images_root) or not images_root.is_dir():
        raise ValueError(f"refusing frontend image root: {images_root}")
    resolved_images_root = images_root.resolve()
    if docs_root not in resolved_images_root.parents:
        raise ValueError(f"frontend image directory is outside docs: {images_root}")

    for object_dir in images_root.iterdir():
        if not object_dir.is_dir():
            continue
        if _is_link_or_reparse_point(object_dir):
            raise ValueError(f"refusing stale frontend image path: {object_dir}")
        if resolved_images_root not in object_dir.resolve().parents:
            raise ValueError(f"frontend image path escaped its root: {object_dir}")
        if object_dir.name in published_ids:
            continue
        for descendant in object_dir.rglob("*"):
            if _is_link_or_reparse_point(descendant):
                raise ValueError(
                    f"refusing linked stale frontend image path: {descendant}"
                )
            if resolved_images_root not in descendant.resolve().parents:
                raise ValueError(f"frontend image path escaped its root: {descendant}")
        shutil.rmtree(object_dir)


def build_all(force: bool) -> list[dict]:
    """Scan all TEI files and generate frontend data.

    Returns item-level error records, so a missing object cannot look like a
    clean build and one broken input does not suppress the remaining objects.
    """
    tei_files = sorted(RESULTS_TEI_DIR.glob("*.xml"))
    if not tei_files:
        _remove_stale_tei_assets(set())
        _remove_stale_frontend_assets(set())
        print(f"No TEI files found in {RESULTS_TEI_DIR}", file=sys.stderr)
        sys.exit(1)
    id_problems = contract.unique_object_id_violations(
        [tei_path.stem for tei_path in tei_files]
    )
    if id_problems:
        print("ERROR: " + "; ".join(id_problems), file=sys.stderr)
        sys.exit(1)

    _remove_stale_tei_assets({tei_path.name for tei_path in tei_files})

    print(f"Building frontend data from {len(tei_files)} TEI file(s)\n")

    project_md = read_knowledge("01_PROJECT.md")
    project_name = _extract_project_name(project_md)

    catalog_objects: list[dict] = []
    errors: list[dict] = []
    published_tei_names: set[str] = set()
    input_state_timestamps: list[str] = []

    for tei_path in tei_files:
        dst = DOCS_DATA_DIR / f"{tei_path.stem}.json"
        data = process_tei(tei_path)
        if data is None:
            errors.append(
                {
                    "object_id": tei_path.stem,
                    "error": "TEI could not be parsed or its facsimile contract failed",
                    "stage": "read",
                }
            )
            continue

        existing = None
        if dst.exists() and not force:
            try:
                existing = json.loads(dst.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                print(f"  REBUILD {tei_path.stem} (invalid existing frontend data)")
        try:
            _publish_tei_asset(tei_path)
            if existing != data:
                write_json_atomic(dst, data)
        except OSError as exc:
            errors.append(
                {
                    "object_id": tei_path.stem,
                    "error": str(exc),
                    "stage": "publish",
                }
            )
            continue
        published_tei_names.add(tei_path.name)
        timestamp = data.get("_meta", {}).get("input_state_timestamp", "")
        if timestamp:
            input_state_timestamps.append(timestamp)

        action = "SKIP" if existing == data else "OK  "
        print(
            f"  {action} {data['id']} ({len(data['pages'])} pages, "
            f"images={'yes' if data['has_images'] else 'no'})"
        )

        catalog_objects.append(
            {
                "id": data["id"],
                "title": data["title"],
                "date": data["date"],
                "language": data["language"],
                "signature": data["signature"],
                "status": data["status"],
                "page_count": len(data["pages"]),
                "has_images": data["has_images"],
            }
        )

    _remove_stale_tei_assets(published_tei_names)
    _remove_stale_frontend_assets({Path(name).stem for name in published_tei_names})

    # Write catalog
    source_digest = hashlib.sha256()
    source_digest.update(project_name.encode("utf-8"))
    for tei_path in tei_files:
        try:
            source_bytes = tei_path.read_bytes()
        except OSError as exc:
            if not any(error["object_id"] == tei_path.stem for error in errors):
                errors.append(
                    {
                        "object_id": tei_path.stem,
                        "error": str(exc),
                        "stage": "read",
                    }
                )
            continue
        source_digest.update(tei_path.name.encode("utf-8"))
        source_digest.update(source_bytes)
    catalog = {
        "_meta": {
            "script": "06_build_frontend.py",
            "source_hash": source_digest.hexdigest()[:12],
            "input_state_timestamp": max(input_state_timestamps, default=""),
        },
        "project": project_name,
        "source_hash": source_digest.hexdigest()[:12],
        "objects": catalog_objects,
    }
    catalog_path = DOCS_DATA_DIR / "catalog.json"
    write_json_atomic(catalog_path, catalog)
    print(f"\nCatalog written to {catalog_path} ({len(catalog_objects)} objects)")
    return errors


# ---------------------------------------------------------------------------
# Local dev server
# ---------------------------------------------------------------------------


def serve(port: int = 8080) -> None:
    """Start a local HTTP server on the docs/ directory."""
    import functools
    import os

    os.chdir(str(DOCS_DIR))
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(DOCS_DIR)
    )
    server = http.server.HTTPServer(("", port), handler)
    print(f"\nServing docs/ at http://localhost:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build static frontend from TEI-XML files."
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate all data files"
    )
    parser.add_argument(
        "--serve", action="store_true", help="Start local HTTP server on port 8080"
    )
    args = parser.parse_args()

    ensure_dirs()
    errors = build_all(args.force)
    write_errors(errors, DOCS_DATA_DIR)

    # A TEI file that could not be read leaves a hole in the published data,
    # so the run fails instead of serving an incomplete edition.
    if errors:
        failed_ids = ", ".join(error["object_id"] for error in errors)
        print(
            f"\nERROR: {len(errors)} TEI file(s) could not be processed: {failed_ids}",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.serve:
        serve()


if __name__ == "__main__":
    main()
