"""Materialize remote facsimiles as local image files.

Flat script-pipeline regime, not a numbered step. Remote-facsimile corpora
reference their images as URLs, and this utility downloads them to
data/processed/images/{object_id}/ with a manifest.json that binds every URL
to the saved filename and SHA-256, so that vision-based transcription and
verification read verified local bytes. Check the licence of the image
provider before materializing.

Three source modes select where the URLs come from:
    --from-manifest        data/inventory.json (metadata.image_urls), the
                           entry path before step 3
    --from-transcriptions  data/processed/transcriptions/*.json
                           (metadata.image_urls)
    (default)              results/tei/*.xml (<facsimile><graphic url>),
                           for imported or generated TEI before step 6

Downloads are paced by FETCH_DELAY_SECONDS, transient failures (429, 5xx,
connection errors) are retried with bounded backoff, and a response larger
than FETCH_MAX_BYTES is refused while it streams. Downloaded bytes must
decode as JPEG, PNG or TIFF. Idempotent: a page whose file, URL and hash
still match the previous manifest is skipped unless --force.

Usage:
    uv run python pipeline/fetch_facsimiles.py --all --from-manifest
    uv run python pipeline/fetch_facsimiles.py --object ID [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import time
from pathlib import Path

import requests
from lxml import etree
from PIL import Image, UnidentifiedImageError

import contract
from config import (
    IMAGE_SUFFIXES,
    IMAGES_DIR,
    INVENTORY_PATH,
    NS,
    RESULTS_TEI_DIR,
    TRANSCRIPTIONS_DIR,
    XML_NS,
    add_selection_args,
    configure_console,
    finish_run,
    provenance_meta,
    read_json,
    safe_xml_parser,
    select_ids,
    write_bytes_atomic,
    write_json_atomic,
)

FETCH_TIMEOUT = 60
FETCH_DELAY_SECONDS = float(os.environ.get("FETCH_DELAY_SECONDS", "0.5"))
FETCH_MAX_RETRIES = int(os.environ.get("FETCH_MAX_RETRIES", "3"))
FETCH_BACKOFF_SECONDS = float(os.environ.get("FETCH_BACKOFF_SECONDS", "1.0"))
# Upper bound for one downloaded facsimile, held in memory before it is
# verified. An uncompressed 600-dpi A3 RGB TIFF (7020 x 9900 pixels) is about
# 208 MB and fits; an endless or hostile response is cut off.
FETCH_MAX_BYTES = int(os.environ.get("FETCH_MAX_BYTES", str(256 * 1024 * 1024)))
FETCH_USER_AGENT = (
    "agentic-edition-pipeline "
    "(+https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline/issues)"
)
IMAGE_FORMAT_SUFFIX = {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif"}
CONTENT_TYPE_SUFFIX = {"image/jpeg": ".jpg", "image/png": ".png", "image/tiff": ".tif"}


def _error(object_id: str, stage: str, message: str, **context: object) -> dict:
    """Build one error record; context adds fields such as page and url."""
    return {"object_id": object_id, **context, "error": message, "stage": stage}


def _validated_image_suffix(content: bytes) -> str:
    """Verify image bytes and return their canonical suffix.

    PIL's DecompressionBombError is no OSError, so it is caught by name; a
    pixel bomb would otherwise abort the run before errors.json is written.
    """
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"response is not a valid supported image: {exc}") from exc
    if image_format not in IMAGE_FORMAT_SUFFIX:
        raise ValueError(f"unsupported image format: {image_format}")
    return IMAGE_FORMAT_SUFFIX[image_format]


def _existing_digest(path: Path) -> str:
    """Return the SHA-256 of a valid local image, or "" when it is unusable.

    The file is read once for both the validity check and the digest.
    """
    try:
        content = path.read_bytes()
        _validated_image_suffix(content)
    except (OSError, ValueError):
        return ""
    return hashlib.sha256(content).hexdigest()


def _read_limited(response: requests.Response) -> bytes:
    """Read a streamed response body, refusing more than FETCH_MAX_BYTES."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > FETCH_MAX_BYTES:
        raise ValueError(
            f"response declares {declared} bytes; limit is {FETCH_MAX_BYTES}"
        )
    content = bytearray()
    for block in response.iter_content(chunk_size=1024 * 1024):
        content.extend(block)
        if len(content) > FETCH_MAX_BYTES:
            raise ValueError(f"response exceeds the limit of {FETCH_MAX_BYTES} bytes")
    return bytes(content)


def _request_with_retry(
    session: requests.Session,
    url: str,
    previous_request_at: float,
) -> tuple[requests.Response, float]:
    """Fetch one URL with host-friendly pacing and bounded transient retries.

    Only 429, 5xx and connection-level errors are retried; any other HTTP
    error raises at once. The response is streamed, and the caller reads it
    with _read_limited and closes it.
    """
    attempt = 0
    request_at = previous_request_at
    while True:
        remaining_delay = FETCH_DELAY_SECONDS - (time.monotonic() - request_at)
        if request_at and remaining_delay > 0:
            time.sleep(remaining_delay)
        request_at = time.monotonic()
        final = attempt == FETCH_MAX_RETRIES
        response: requests.Response | None = None
        try:
            response = session.get(url, timeout=FETCH_TIMEOUT, stream=True)
        except requests.RequestException:
            if final:
                raise
        else:
            status = getattr(response, "status_code", 200)
            if final or not (status == 429 or 500 <= status < 600):
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    response.close()
                    raise
                return response, request_at
        retry_after = (
            response.headers.get("retry-after", "") if response is not None else ""
        )
        if response is not None:
            response.close()
        try:
            server_delay = float(retry_after)
        except (TypeError, ValueError):
            server_delay = 0.0
        backoff = max(server_delay, FETCH_BACKOFF_SECONDS * (2**attempt))
        if backoff > 0:
            time.sleep(backoff)
        attempt += 1


def _pairs_from_image_urls(urls: object) -> list[tuple[int, str]]:
    """Return sorted (page, url) pairs from a metadata.image_urls value."""
    pairs: list[tuple[int, str]] = []
    if isinstance(urls, dict):
        for key, url in urls.items():
            if str(key).isdigit() and str(url).startswith("http"):
                pairs.append((int(key), str(url)))
    elif isinstance(urls, list):
        for index, url in enumerate(urls, start=1):
            if str(url).startswith("http"):
                pairs.append((index, str(url)))
    return sorted(pairs)


def urls_from_tei(tei_path: Path) -> list[tuple[int, str]]:
    """Extract (page_number, url) pairs from a TEI <facsimile> block.

    Page numbers come from pb/@facs pointers (#id) with a numeric @n;
    graphics without a matching pb keep their position.
    """
    root = etree.parse(str(tei_path), safe_xml_parser()).getroot()
    id_to_page: dict[str, int] = {}
    for pb in root.findall(".//tei:body//tei:pb", NS):
        facs = pb.get("facs", "")
        n = pb.get("n", "")
        if facs.startswith("#") and n.isdigit():
            id_to_page[facs[1:]] = int(n)

    pairs: list[tuple[int, str]] = []
    for index, graphic in enumerate(
        root.findall(".//tei:facsimile/tei:graphic", NS), start=1
    ):
        url = graphic.get("url", "")
        if url.startswith("http"):
            graphic_id = graphic.get(f"{{{XML_NS}}}id", "")
            pairs.append((id_to_page.get(graphic_id, index), url))
    return pairs


def urls_from_transcription(json_path: Path) -> list[tuple[int, str]]:
    """Extract (page_number, url) pairs from metadata.image_urls."""
    data = read_json(json_path)
    metadata = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(metadata, dict):
        return []
    return _pairs_from_image_urls(metadata.get("image_urls"))


def objects_from_inventory(json_path: Path) -> list[tuple[str, list[tuple[int, str]]]]:
    """Read remote facsimile declarations from the generated inventory."""
    data = read_json(json_path)
    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list):
        raise ValueError("inventory carries no documents list")

    objects: list[tuple[str, list[tuple[int, str]]]] = []
    for doc in documents:
        if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
            continue
        metadata = doc.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        pairs = _pairs_from_image_urls(metadata.get("image_urls"))
        if pairs:
            objects.append((doc["id"], pairs))
    return objects


def fetch_object(
    object_id: str, pairs: list[tuple[int, str]], force: bool
) -> list[dict]:
    """Download all facsimiles for one object. Returns a list of error dicts."""
    if not contract.valid_object_id(object_id):
        return [
            _error(
                str(object_id),
                "contract",
                "facsimile object_id is not a path-safe identifier",
            )
        ]
    image_root = IMAGES_DIR.resolve()
    out_dir = (IMAGES_DIR / object_id).resolve()
    if image_root not in out_dir.parents:
        return [
            _error(
                object_id,
                "contract",
                "facsimile output escaped the configured image root",
            )
        ]
    page_numbers = [page for page, _url in pairs]
    if page_numbers != list(range(1, len(pairs) + 1)):
        return [
            _error(
                object_id,
                "contract",
                f"facsimile pages are {page_numbers}; expected consecutive pages from 1",
            )
        ]
    previous_pages: dict[int, dict] = {}
    try:
        previous_manifest = read_json(out_dir / "manifest.json")
        if isinstance(previous_manifest, dict):
            for previous_page in previous_manifest.get("pages", []):
                if isinstance(previous_page, dict) and isinstance(
                    previous_page.get("page"), int
                ):
                    previous_pages[previous_page["page"]] = previous_page
    except (OSError, ValueError, TypeError):
        previous_pages = {}

    errors: list[dict] = []
    manifest_pages: list[dict] = []
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
                message = "multiple local facsimile files exist for one page"
                errors.append(_error(object_id, "contract", message, page=page_num))
                manifest_pages.append(
                    {"page": page_num, "image_url": url, "error": message}
                )
                continue
            existing_digest = (
                _existing_digest(existing[0]) if existing and not force else ""
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
                response, previous_request_at = _request_with_retry(
                    session, url, previous_request_at
                )
                try:
                    content = _read_limited(response)
                finally:
                    response.close()
                content_type = response.headers.get("content-type", "").split(";")[0]
                ext = _validated_image_suffix(content)
                declared_ext = CONTENT_TYPE_SUFFIX.get(content_type)
                if declared_ext and declared_ext != ext:
                    raise ValueError(
                        f"response image format {ext} conflicts with content type {content_type}"
                    )
                out_path = out_dir / f"{object_id}_p{page_num:03d}{ext}"
                write_bytes_atomic(out_path, content)
                for stale in existing:
                    if stale != out_path:
                        stale.unlink()
                manifest_pages.append(
                    {
                        "page": page_num,
                        "filename": out_path.name,
                        "image_url": url,
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                print(f"  OK   {out_path.name} ({len(content) // 1024} KB from {url})")
            except (requests.RequestException, OSError, ValueError) as exc:
                errors.append(
                    _error(object_id, "fetch", str(exc), page=page_num, url=url)
                )
                manifest_pages.append(
                    {"page": page_num, "image_url": url, "error": str(exc)}
                )
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
        errors.append(_error(object_id, "write", str(exc)))
    return errors


def _read_sources(
    from_manifest: bool, from_transcriptions: bool
) -> tuple[list[tuple[str, list[tuple[int, str]]]], list[dict]]:
    """Collect (object_id, pairs) per source record and per-file read errors."""
    if from_manifest:
        try:
            return objects_from_inventory(INVENTORY_PATH), []
        except FileNotFoundError:
            print(
                f"ERROR: no inventory at {INVENTORY_PATH}. Run 02_analyze.py first.",
                file=sys.stderr,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read {INVENTORY_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)

    if from_transcriptions:
        source_dir, pattern, extractor = (
            TRANSCRIPTIONS_DIR,
            "*.json",
            urls_from_transcription,
        )
    else:
        source_dir, pattern, extractor = RESULTS_TEI_DIR, "*.xml", urls_from_tei
    sources: list[tuple[str, list[tuple[int, str]]]] = []
    errors: list[dict] = []
    for path in sorted(source_dir.glob(pattern)):
        if path.stem == "errors":
            continue
        try:
            sources.append((path.stem, extractor(path)))
        except (OSError, ValueError, etree.XMLSyntaxError) as exc:
            errors.append(_error(path.stem, "read", str(exc)))
    return sources, errors


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Download remote facsimiles to data/processed/images/."
    )
    add_selection_args(parser)
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

    sources, source_errors = _read_sources(args.from_manifest, args.from_transcriptions)
    if not sources and source_errors:
        finish_run(source_errors, IMAGES_DIR, len(source_errors), "fetch_facsimiles.py")
    pairs_by_id = dict(sources)
    selected = select_ids(
        [object_id for object_id, _pairs in sources],
        args.object,
        args.all,
        args.sample,
    )

    errors: list[dict] = list(source_errors)
    fetched = 0
    for object_id in selected:
        pairs = pairs_by_id[object_id]
        if not pairs:
            continue
        fetched += 1
        print(f"{object_id}: {len(pairs)} facsimile URL(s)")
        errors.extend(fetch_object(object_id, pairs, args.force))

    finish_run(
        errors,
        IMAGES_DIR,
        len(selected) + len(source_errors),
        "fetch_facsimiles.py",
        summary=f"Done. {fetched} object(s) with remote facsimile URLs processed.",
    )


if __name__ == "__main__":
    main()
