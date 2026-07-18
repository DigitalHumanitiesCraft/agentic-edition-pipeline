"""Materialize remote facsimiles as local image files.

Remote-facsimile corpora reference their images as URLs, either in the
transcription JSON (metadata.image_urls, see knowledge/08_DATA_CONTRACT.md)
or in generated TEI (<facsimile><graphic url="..."/>). This utility downloads
those images to data/processed/images/{object_id}/ so that vision-based
transcription and verification can read the files locally. Check the licence
of the image provider before materializing.

Not a numbered pipeline step: run it whenever local copies are needed,
typically before step 3 (agentic transcription needs the file on disk,
a URL fetch alone does not reach the vision input) or before step 6.

Idempotent: existing files are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from config import (
    IMAGES_DIR,
    RESULTS_TEI_DIR,
    TRANSCRIPTIONS_DIR,
    write_errors,
)

FETCH_TIMEOUT = 60


def _extension_from_response(url: str, content_type: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/tiff": ".tif",
    }
    if content_type in mapping:
        return mapping[content_type]
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
        return suffix
    return ".jpg"


def urls_from_tei(tei_path: Path) -> list[tuple[int, str]]:
    """Extract (page_number, url) pairs from a TEI <facsimile> block."""
    from lxml import etree

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    root = etree.parse(str(tei_path)).getroot()

    # Page numbers come from pb/@facs pointers (#facs_N); graphics without a
    # matching pb keep their position index.
    id_to_page: dict[str, int] = {}
    for pb in root.findall(".//tei:body//tei:pb", ns):
        facs = pb.get("facs", "")
        n = pb.get("n", "")
        if facs.startswith("#") and n.isdigit():
            id_to_page[facs[1:]] = int(n)

    pairs: list[tuple[int, str]] = []
    for i, graphic in enumerate(root.findall(".//tei:facsimile/tei:graphic", ns)):
        url = graphic.get("url", "")
        gid = graphic.get(xml_id, "")
        if url.startswith("http"):
            pairs.append((id_to_page.get(gid, i + 1), url))
    return pairs


def urls_from_transcription(json_path: Path) -> list[tuple[int, str]]:
    """Extract (page_number, url) pairs from metadata.image_urls."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    urls = data.get("metadata", {}).get("image_urls")
    pairs: list[tuple[int, str]] = []
    if isinstance(urls, dict):
        for key, url in urls.items():
            if str(key).isdigit() and str(url).startswith("http"):
                pairs.append((int(key), url))
    elif isinstance(urls, list):
        for i, url in enumerate(urls):
            if str(url).startswith("http"):
                pairs.append((i + 1, url))
    return sorted(pairs)


def fetch_object(object_id: str, pairs: list[tuple[int, str]], force: bool) -> list[dict]:
    """Download all facsimiles for one object. Returns a list of error dicts."""
    out_dir = IMAGES_DIR / object_id
    errors: list[dict] = []

    for page_num, url in pairs:
        try:
            resp = requests.get(url, timeout=FETCH_TIMEOUT)
            resp.raise_for_status()
            ext = _extension_from_response(url, resp.headers.get("content-type", "").split(";")[0])
            out_path = out_dir / f"{object_id}_p{page_num:03d}{ext}"
            if out_path.exists() and not force:
                print(f"  SKIP {out_path.name} (exists, use --force)")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(resp.content)
            print(f"  OK   {out_path.name} ({len(resp.content) // 1024} KB from {url})")
        except requests.RequestException as exc:
            errors.append({
                "object_id": object_id, "page": page_num, "url": url,
                "error": str(exc), "stage": "fetch",
            })
            print(f"  FAIL page {page_num}: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Download remote facsimiles to data/processed/images/.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Fetch a single object by ID")
    group.add_argument("--all", action="store_true", help="Fetch all objects with remote URLs")
    parser.add_argument(
        "--from-transcriptions", action="store_true",
        help="Read URLs from data/processed/transcriptions/ instead of results/tei/",
    )
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    args = parser.parse_args()

    if args.from_transcriptions:
        source_dir, suffix, extractor = TRANSCRIPTIONS_DIR, "*.json", urls_from_transcription
    else:
        source_dir, suffix, extractor = RESULTS_TEI_DIR, "*.xml", urls_from_tei

    files = sorted(source_dir.glob(suffix))
    if args.object:
        files = [f for f in files if f.stem == args.object]
    files = [f for f in files if f.stem != "errors"]

    if not files:
        print(f"No source files found in {source_dir}", file=sys.stderr)
        sys.exit(1)

    all_errors: list[dict] = []
    fetched_any = False
    for f in files:
        pairs = extractor(f)
        if not pairs:
            continue
        fetched_any = True
        print(f"{f.stem}: {len(pairs)} facsimile URL(s)")
        all_errors.extend(fetch_object(f.stem, pairs, args.force))

    if not fetched_any:
        print("No remote facsimile URLs found.")
    if all_errors:
        write_errors(all_errors, IMAGES_DIR)
        print(f"\n{len(all_errors)} error(s) written to {IMAGES_DIR / 'errors.json'}")


if __name__ == "__main__":
    main()
