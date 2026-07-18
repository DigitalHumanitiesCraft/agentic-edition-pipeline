"""Build the static frontend from TEI-XML files.

Scans results/tei/ for TEI files, extracts metadata and text content using
lxml, and writes JSON data files that the viewer reads at runtime. The viewer
itself (HTML/CSS/JS in docs/) is static and pre-existing -- this script only
generates the data layer.

Outputs:
  docs/data/catalog.json   -- project-level index of all objects
  docs/data/{object_id}.json -- per-object data with pages, text, image paths
"""
from __future__ import annotations

import argparse
import http.server
import json
import re
import shutil
import sys
from pathlib import Path

from lxml import etree

from config import (
    DOCS_DATA_DIR,
    DOCS_DIR,
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


def build_all(force: bool):
    """Scan all TEI files and generate frontend data."""
    tei_files = sorted(RESULTS_TEI_DIR.glob("*.xml"))
    if not tei_files:
        print(f"No TEI files found in {RESULTS_TEI_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Building frontend data from {len(tei_files)} TEI file(s)\n")

    project_md = read_knowledge("01_PROJECT.md")
    project_name = _extract_project_name(project_md)

    catalog_objects: list[dict] = []

    for tei_path in tei_files:
        dst = DOCS_DATA_DIR / f"{tei_path.stem}.json"
        if dst.exists() and not force:
            print(f"  SKIP {tei_path.stem} (exists, use --force)")
            # Still include in catalog from existing file
            try:
                existing = json.loads(dst.read_text(encoding="utf-8"))
                catalog_objects.append({
                    "id": existing["id"],
                    "title": existing.get("title", ""),
                    "date": existing.get("date", ""),
                    "language": existing.get("language", ""),
                    "page_count": len(existing.get("pages", [])),
                    "has_images": existing.get("has_images", False),
                })
            except Exception:
                pass
            continue

        data = process_tei(tei_path)
        if data is None:
            continue

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

    # Write catalog
    catalog = {
        "project": project_name,
        "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "objects": catalog_objects,
    }
    catalog_path = DOCS_DATA_DIR / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCatalog written to {catalog_path} ({len(catalog_objects)} objects)")


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
    build_all(args.force)

    if args.serve:
        serve()


if __name__ == "__main__":
    main()
