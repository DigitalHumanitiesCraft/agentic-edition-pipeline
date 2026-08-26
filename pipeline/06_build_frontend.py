"""Build the static frontend from TEI-XML files.

Scans results/tei/ for TEI files, extracts metadata and text content using
lxml, and writes JSON data files that the viewer reads at runtime. The viewer
itself (HTML/CSS/JS in docs/) is static and pre-existing -- this script only
generates the data layer.

Outputs:
  docs/data/catalog.json   -- project-level index of all objects
  docs/data/{object_id}.json -- per-object data with pages, text, image paths
  docs/tei/{object_id}.xml -- downloadable publication copy
"""
from __future__ import annotations

import argparse
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

from config import (
    DOCS_DATA_DIR,
    DOCS_DIR,
    DOCS_TEI_DIR,
    PROJECT_ROOT,
    RESULTS_TEI_DIR,
    ensure_dirs,
    list_page_images,
    read_knowledge,
    resolve_image_dir,
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
    """Extract title, date, and language from teiHeader."""
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

    return meta


# ---------------------------------------------------------------------------
# Text extraction -- split by <pb/> into pages
# ---------------------------------------------------------------------------

def _strip_tags(text: str) -> str:
    """Remove XML tags from a string, keeping only text content."""
    return re.sub(r"<[^>]+>", "", text)


def _normalize_page_text(chunk: str) -> str:
    """Turn a serialized TEI chunk into display text.

    <lb/> becomes a line break, </p> a paragraph break. The indentation
    whitespace that pretty-printed TEI carries into text nodes is stripped
    per line, and blank-line runs collapse to one paragraph separator.
    """
    chunk = re.sub(r"<lb\s*/>", "\n", chunk)
    chunk = re.sub(r"</p>", "\n\n", chunk)
    text = _strip_tags(chunk)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    """Split body content by <pb/> elements into per-page text chunks.

    Each page gets the plain text between its <pb/> and the next <pb/>
    (or end of body). Image references come from the facs attribute on
    <pb/>; a '#facs_N' pointer resolves to the <facsimile> graphic URL.
    """
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        return []

    facs_urls = extract_facsimile_urls(root)

    # Serialize body to string so we can split on <pb/> reliably.
    # This avoids complex tree walking for mixed-content elements.
    body_str = etree.tostring(body, encoding="unicode")

    # Split on <pb .../> -- capture the element to extract attributes
    parts = re.split(r"(<pb\s[^>]*/>)", body_str)

    pages: list[dict] = []
    current_facs = ""
    current_n = ""

    for part in parts:
        if re.match(r"<pb\s", part):
            # Attribute order varies; search each attribute independently.
            n_match = re.search(r'\bn="(\d+)"', part)
            facs_match = re.search(r'\bfacs="([^"]*)"', part)
            current_n = n_match.group(1) if n_match else ""
            current_facs = facs_match.group(1) if facs_match else ""
            continue

        # This is a text chunk belonging to the current page
        if current_n:
            facs = facs_urls.get(current_facs, current_facs)
            pages.append({
                "page": int(current_n),
                "text": _normalize_page_text(part),
                "image": facs,
            })

    return pages


# ---------------------------------------------------------------------------
# Build data files
# ---------------------------------------------------------------------------

def _attach_images(object_id: str, pages: list[dict]):
    """Resolve page images and make them servable from docs/.

    Remote URLs (from <facsimile> graphic url) are kept as-is; the viewer
    renders them directly. Local images resolved via the shared image-root
    resolver are copied to docs/images/{id}/ because the static frontend
    can only serve files below docs/. Page order maps local files to pages.
    """
    image_dir = resolve_image_dir(object_id)
    local_files = list_page_images(image_dir) if image_dir else []
    docs_image_dir = DOCS_DIR / "images" / object_id

    for i, page in enumerate(pages):
        current = page.get("image", "")
        if current.startswith("http://") or current.startswith("https://"):
            continue
        if i < len(local_files):
            src = local_files[i]
            docs_image_dir.mkdir(parents=True, exist_ok=True)
            dst = docs_image_dir / src.name
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
            page["image"] = f"images/{object_id}/{src.name}"
        else:
            page["image"] = ""


def process_tei(tei_path: Path) -> dict | None:
    """Parse a TEI file and return its data dict, or None on error."""
    try:
        tree = etree.parse(str(tei_path))
    except etree.XMLSyntaxError as exc:
        print(f"  SKIP {tei_path.stem} (XML parse error: {exc})")
        return None

    root = tree.getroot()
    object_id = tei_path.stem
    meta = extract_metadata(root)
    pages = extract_pages(root)

    _attach_images(object_id, pages)
    # has_images reflects what the viewer can actually show: a copied local
    # file or a remote facsimile URL on at least one page.
    has_images = any(p.get("image") for p in pages)

    return {
        "id": object_id,
        "title": meta.get("title", object_id),
        "date": meta.get("date", ""),
        "language": meta.get("language", ""),
        "pages": pages,
        "has_images": has_images,
    }


def _copy_tei_asset(tei_path: Path) -> None:
    """Copy the canonical TEI into the static publication root."""
    publication_dir = _validated_tei_publication_dir()
    publication_dir.mkdir(parents=True, exist_ok=True)
    publication_dir = _validated_tei_publication_dir()
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
        print(f"  FAIL {tei_path.stem} (TEI publication copy: {exc})", file=sys.stderr)
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
        raise ValueError(f"resolved docs directory escaped the project root: {docs_root}")
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


def build_all(force: bool) -> list[str]:
    """Scan all TEI files and generate frontend data.

    Returns the ids of the files that could not be processed, so a silently
    missing object does not look like a clean build.
    """
    tei_files = sorted(RESULTS_TEI_DIR.glob("*.xml"))
    if not tei_files:
        _remove_stale_tei_assets(set())
        print(f"No TEI files found in {RESULTS_TEI_DIR}", file=sys.stderr)
        sys.exit(1)

    _remove_stale_tei_assets({tei_path.name for tei_path in tei_files})

    print(f"Building frontend data from {len(tei_files)} TEI file(s)\n")

    project_md = read_knowledge("01_PROJECT.md")
    project_name = _extract_project_name(project_md)

    catalog_objects: list[dict] = []
    failed: list[str] = []
    published_tei_names: set[str] = set()

    for tei_path in tei_files:
        dst = DOCS_DATA_DIR / f"{tei_path.stem}.json"
        if dst.exists() and not force:
            print(f"  SKIP {tei_path.stem} (exists, use --force)")
            if not _is_well_formed_tei(tei_path):
                failed.append(tei_path.stem)
                continue
            try:
                existing = json.loads(dst.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    raise TypeError("expected a JSON object")
                catalog_item = {
                    "id": existing["id"],
                    "title": existing.get("title", ""),
                    "date": existing.get("date", ""),
                    "language": existing.get("language", ""),
                    "page_count": len(existing.get("pages", [])),
                    "has_images": existing.get("has_images", False),
                }
            except (json.JSONDecodeError, KeyError, OSError, TypeError) as exc:
                print(f"  FAIL {tei_path.stem} (existing frontend data: {exc})")
                failed.append(tei_path.stem)
                continue
            catalog_objects.append(catalog_item)
            _publish_tei_asset(tei_path)
            published_tei_names.add(tei_path.name)
            continue

        data = process_tei(tei_path)
        if data is None:
            failed.append(tei_path.stem)
            continue

        _publish_tei_asset(tei_path)
        published_tei_names.add(tei_path.name)

        # Write per-object JSON
        dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  OK   {data['id']} ({len(data['pages'])} pages, images={'yes' if data['has_images'] else 'no'})")

        catalog_objects.append({
            "id": data["id"],
            "title": data["title"],
            "date": data["date"],
            "language": data["language"],
            "page_count": len(data["pages"]),
            "has_images": data["has_images"],
        })

    _remove_stale_tei_assets(published_tei_names)

    # Write catalog
    catalog = {
        "project": project_name,
        "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "objects": catalog_objects,
    }
    catalog_path = DOCS_DATA_DIR / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCatalog written to {catalog_path} ({len(catalog_objects)} objects)")
    return failed


# ---------------------------------------------------------------------------
# Local dev server
# ---------------------------------------------------------------------------

def serve(port: int = 8080):
    """Start a local HTTP server on the docs/ directory."""
    import functools
    import os

    os.chdir(str(DOCS_DIR))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS_DIR))
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

def main():
    parser = argparse.ArgumentParser(description="Build static frontend from TEI-XML files.")
    parser.add_argument("--force", action="store_true", help="Regenerate all data files")
    parser.add_argument("--serve", action="store_true", help="Start local HTTP server on port 8080")
    args = parser.parse_args()

    ensure_dirs()
    failed = build_all(args.force)

    # A TEI file that could not be read leaves a hole in the published data,
    # so the run fails instead of serving an incomplete edition.
    if failed:
        print(f"\nERROR: {len(failed)} TEI file(s) could not be processed: "
              f"{', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    if args.serve:
        serve()


if __name__ == "__main__":
    main()
