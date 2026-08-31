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
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError

import contract
from config import (
    DATA_DIR,
    IMAGES_DIR,
    RESULTS_TEI_DIR,
    TRANSCRIPTIONS_DIR,
    provenance_meta,
    write_bytes_atomic,
    write_errors,
    write_json_atomic,
)

FETCH_TIMEOUT = 60
FETCH_DELAY_SECONDS = float(os.environ.get("FETCH_DELAY_SECONDS", "0.5"))
FETCH_MAX_RETRIES = int(os.environ.get("FETCH_MAX_RETRIES", "3"))
FETCH_BACKOFF_SECONDS = float(os.environ.get("FETCH_BACKOFF_SECONDS", "1.0"))
INVENTORY_PATH = DATA_DIR / "inventory.json"
FETCH_USER_AGENT = (
    "agentic-edition-pipeline/0.9 "
    "(+https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline/issues)"
)
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff"})
IMAGE_FORMAT_SUFFIX = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif"}


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


def _validated_image_suffix(content: bytes) -> str:
    """Verify downloaded bytes and return their canonical image suffix."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("response is not a valid supported image") from exc
    if image_format not in IMAGE_FORMAT_SUFFIX:
        raise ValueError(f"unsupported image format: {image_format}")
    return IMAGE_FORMAT_SUFFIX[image_format]


def _is_valid_image(path: Path) -> bool:
    """Return whether an existing local file is a supported, readable image."""
    try:
        _validated_image_suffix(path.read_bytes())
    except (OSError, ValueError):
        return False
    return True


def _image_digest(path: Path) -> str:
    """Hash the exact local facsimile bytes used downstream."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_with_retry(
    session: requests.Session,
    url: str,
    previous_request_at: float,
) -> tuple[requests.Response, float]:
    """Fetch one URL with host-friendly pacing and bounded transient retries."""
    request_at = previous_request_at
    for attempt in range(FETCH_MAX_RETRIES + 1):
        remaining_delay = FETCH_DELAY_SECONDS - (time.monotonic() - request_at)
        if request_at and remaining_delay > 0:
            time.sleep(remaining_delay)
        request_at = time.monotonic()
        response: requests.Response | None = None
        try:
            response = session.get(url, timeout=FETCH_TIMEOUT)
            status = getattr(response, "status_code", 200)
            transient = status == 429 or 500 <= status < 600
            if not transient or attempt == FETCH_MAX_RETRIES:
                response.raise_for_status()
                return response, request_at
        except requests.RequestException:
            if attempt == FETCH_MAX_RETRIES:
                raise
        retry_after = (
            response.headers.get("retry-after", "") if response is not None else ""
        )
        try:
            server_delay = float(retry_after)
        except (TypeError, ValueError):
            server_delay = 0.0
        backoff = max(server_delay, FETCH_BACKOFF_SECONDS * (2**attempt))
        if backoff > 0:
            time.sleep(backoff)
    raise RuntimeError("unreachable retry state")


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


def objects_from_inventory(json_path: Path) -> list[tuple[str, list[tuple[int, str]]]]:
    """Read remote facsimile declarations from the generated inventory."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    documents = data.get("documents", [])
    if not isinstance(documents, list):
        raise ValueError("inventory carries no documents list")

    objects: list[tuple[str, list[tuple[int, str]]]] = []
    for doc in documents:
        if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
            continue
        metadata = doc.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        urls = metadata.get("image_urls")
        pairs: list[tuple[int, str]] = []
        if isinstance(urls, dict):
            for key, url in urls.items():
                if str(key).isdigit() and str(url).startswith("http"):
                    pairs.append((int(key), str(url)))
        elif isinstance(urls, list):
            for index, url in enumerate(urls, start=1):
                if str(url).startswith("http"):
                    pairs.append((index, str(url)))
        if pairs:
            objects.append((doc["id"], sorted(pairs)))
    return objects


def fetch_object(
    object_id: str, pairs: list[tuple[int, str]], force: bool
) -> list[dict]:
    """Download all facsimiles for one object. Returns a list of error dicts."""
    if not contract.valid_object_id(object_id):
        return [
            {
                "object_id": str(object_id),
                "error": "facsimile object_id is not a path-safe identifier",
                "stage": "contract",
            }
        ]
    image_root = IMAGES_DIR.resolve()
    out_dir = (IMAGES_DIR / object_id).resolve()
    if image_root not in out_dir.parents:
        return [
            {
                "object_id": object_id,
                "error": "facsimile output escaped the configured image root",
                "stage": "contract",
            }
        ]
    errors: list[dict] = []
    manifest_pages: list[dict] = []
    previous_pages: dict[int, dict] = {}
    try:
        previous_manifest = json.loads(
            (out_dir / "manifest.json").read_text(encoding="utf-8")
        )
        if not isinstance(previous_manifest, dict):
            raise TypeError("image manifest is not an object")
        for previous_page in previous_manifest.get("pages", []):
            if isinstance(previous_page, dict) and isinstance(
                previous_page.get("page"), int
            ):
                previous_pages[previous_page["page"]] = previous_page
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        previous_pages = {}
    page_numbers = [page for page, _url in pairs]
    if page_numbers != list(range(1, len(pairs) + 1)):
        return [
            {
                "object_id": object_id,
                "error": f"facsimile pages are {page_numbers}; expected consecutive pages from 1",
                "stage": "contract",
            }
        ]

    with requests.Session() as session:
        session.headers.update({"User-Agent": FETCH_USER_AGENT})
        previous_request_at = 0.0
        for page_num, url in pairs:
            existing = [
                path
                for path in out_dir.glob(f"{object_id}_p{page_num:03d}.*")
                if path.suffix.lower() in IMAGE_SUFFIXES
            ]
            if len(existing) > 1 and not force:
                errors.append(
                    {
                        "object_id": object_id,
                        "page": page_num,
                        "error": "multiple local facsimile files exist for one page",
                        "stage": "contract",
                    }
                )
                manifest_pages.append(
                    {
                        "page": page_num,
                        "image_url": url,
                        "error": "multiple local facsimile files exist for one page",
                    }
                )
                continue
            existing_digest = (
                _image_digest(existing[0])
                if existing and not force and _is_valid_image(existing[0])
                else ""
            )
            previous = previous_pages.get(page_num, {})
            if (
                existing_digest
                and previous.get("image_url") == url
                and previous.get("filename") == existing[0].name
                and previous.get("sha256") == existing_digest
            ):
                print(f"  SKIP {existing[0].name} (exists, use --force)")
                manifest_pages.append(
                    {
                        "page": page_num,
                        "filename": existing[0].name,
                        "image_url": url,
                        "sha256": existing_digest,
                    }
                )
                continue
            try:
                resp, previous_request_at = _request_with_retry(
                    session,
                    url,
                    previous_request_at,
                )
                content_type = resp.headers.get("content-type", "").split(";")[0]
                declared_ext = _extension_from_response(url, content_type)
                ext = _validated_image_suffix(resp.content)
                if content_type.startswith("image/") and declared_ext != ext:
                    raise ValueError(
                        f"response image format {ext} conflicts with content type {content_type}"
                    )
                out_path = out_dir / f"{object_id}_p{page_num:03d}{ext}"
                write_bytes_atomic(out_path, resp.content)
                for stale in existing:
                    if stale != out_path:
                        stale.unlink()
                manifest_pages.append(
                    {
                        "page": page_num,
                        "filename": out_path.name,
                        "image_url": url,
                        "sha256": hashlib.sha256(resp.content).hexdigest(),
                    }
                )
                print(
                    f"  OK   {out_path.name} ({len(resp.content) // 1024} KB from {url})"
                )
            except (requests.RequestException, OSError, ValueError) as exc:
                errors.append(
                    {
                        "object_id": object_id,
                        "page": page_num,
                        "url": url,
                        "error": str(exc),
                        "stage": "fetch",
                    }
                )
                manifest_pages.append(
                    {
                        "page": page_num,
                        "image_url": url,
                        "error": str(exc),
                    }
                )
                print(f"  FAIL page {page_num}: {exc}")
    try:
        if not errors:
            current_names = {page["filename"] for page in manifest_pages}
            for stale in out_dir.glob(f"{object_id}_p*.*"):
                if (
                    stale.suffix.lower() in IMAGE_SUFFIXES
                    and stale.name not in current_names
                ):
                    stale.unlink()
        write_json_atomic(
            out_dir / "manifest.json",
            {
                "_meta": provenance_meta(script="fetch_facsimiles.py", step=0),
                "source_type": "remote_facsimiles",
                "pages": manifest_pages,
            },
        )
    except OSError as exc:
        errors.append(
            {
                "object_id": object_id,
                "error": str(exc),
                "stage": "write",
            }
        )
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Download remote facsimiles to data/processed/images/."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Fetch a single object by ID")
    group.add_argument(
        "--all", action="store_true", help="Fetch all objects with remote URLs"
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--from-manifest",
        action="store_true",
        help="Read URLs from data/inventory.json after pipeline/02_analyze.py",
    )
    source_group.add_argument(
        "--from-transcriptions",
        action="store_true",
        help="Read URLs from data/processed/transcriptions/ instead of results/tei/",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-download existing files"
    )
    args = parser.parse_args()

    sources: list[tuple[str, list[tuple[int, str]]]] = []
    source_errors: list[dict] = []
    if args.from_manifest:
        if not INVENTORY_PATH.exists():
            print(
                f"No inventory found at {INVENTORY_PATH}. Run 02_analyze.py first.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            sources = objects_from_inventory(INVENTORY_PATH)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            print(f"Cannot read {INVENTORY_PATH}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        if args.from_transcriptions:
            source_dir, suffix, extractor = (
                TRANSCRIPTIONS_DIR,
                "*.json",
                urls_from_transcription,
            )
        else:
            source_dir, suffix, extractor = RESULTS_TEI_DIR, "*.xml", urls_from_tei
        files = [
            path for path in sorted(source_dir.glob(suffix)) if path.stem != "errors"
        ]
        for path in files:
            try:
                sources.append((path.stem, extractor(path)))
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                source_errors.append(
                    {
                        "object_id": path.stem,
                        "error": str(exc),
                        "stage": "read",
                    }
                )

    id_problems = contract.unique_object_id_violations(
        [object_id for object_id, _pairs in sources]
    )
    if id_problems:
        print("ERROR: " + "; ".join(id_problems), file=sys.stderr)
        sys.exit(1)

    if args.object:
        sources = [source for source in sources if source[0] == args.object]
    if not sources:
        if source_errors:
            write_errors(source_errors, IMAGES_DIR)
            print(
                f"No usable source records; {len(source_errors)} read error(s) written to "
                f"{IMAGES_DIR / 'errors.json'}.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("No source records with remote facsimiles found.", file=sys.stderr)
        sys.exit(1)

    all_errors: list[dict] = list(source_errors)
    fetched_any = False
    for object_id, pairs in sources:
        if not pairs:
            continue
        fetched_any = True
        print(f"{object_id}: {len(pairs)} facsimile URL(s)")
        all_errors.extend(fetch_object(object_id, pairs, args.force))

    if not fetched_any:
        print("No remote facsimile URLs found.")
    write_errors(all_errors, IMAGES_DIR)
    if all_errors:
        print(f"\n{len(all_errors)} error(s) written to {IMAGES_DIR / 'errors.json'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
