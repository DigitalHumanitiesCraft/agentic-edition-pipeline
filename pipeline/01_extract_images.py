"""Extract page images from PDFs using PyMuPDF (fitz).

Each PDF becomes a directory under data/processed/images/{doc_id}/ containing
one PNG per page plus a manifest.json. The manifest records provenance and maps
page numbers to filenames, so downstream scripts never need to re-inspect the
images directory -- they just read the manifest.

Idempotent: existing document directories are skipped unless --force.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

import contract
from config import (
    IMAGE_DPI,
    IMAGES_DIR,
    SOURCES_DIR,
    ensure_dirs,
    provenance_meta,
    write_bytes_atomic,
    write_errors,
    write_json_atomic,
)

PDF_DIR = SOURCES_DIR / "pdf"


def doc_id_from_path(pdf_path: Path) -> str:
    return pdf_path.stem


def _file_hash(path: Path) -> str:
    """Return a stable digest for source-state comparison."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _complete_existing_extraction(out_dir: Path, pdf_path: Path, dpi: int) -> bool:
    """Return whether an existing manifest fully represents this PDF run."""
    manifest_path = out_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pages = manifest["pages"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, OSError, TypeError):
        return False
    if (
        not isinstance(manifest, dict)
        or manifest.get("source_pdf") != pdf_path.name
        or manifest.get("source_sha256") != _file_hash(pdf_path)
        or manifest.get("dpi") != dpi
        or not isinstance(pages, list)
        or not pages
    ):
        return False
    for number, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page") != number or "error" in page:
            return False
        filename = page.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            return False
        image_path = out_dir / filename
        if not image_path.is_file():
            return False
        if page.get("sha256") != _file_hash(image_path):
            return False
    return True


def extract_one(pdf_path: Path, dpi: int, force: bool) -> dict | None:
    """Extract all pages from a single PDF. Returns error dict on failure, None on success."""
    did = doc_id_from_path(pdf_path)
    out_dir = IMAGES_DIR / did

    if (
        out_dir.exists()
        and not force
        and _complete_existing_extraction(out_dir, pdf_path, dpi)
    ):
        print(f"  SKIP {did} (complete extraction exists, use --force to re-extract)")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {
            "object_id": did,
            "file": str(pdf_path),
            "error": str(exc),
            "stage": "open",
        }

    pages: list[dict] = []
    # DPI conversion: fitz uses a zoom matrix; default render is 72 DPI
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        filename = f"{did}_p{page_num + 1:03d}.png"
        out_path = out_dir / filename
        try:
            pix = doc[page_num].get_pixmap(matrix=matrix)
            write_bytes_atomic(out_path, pix.tobytes("png"))
            pages.append(
                {
                    "page": page_num + 1,
                    "filename": filename,
                    "sha256": _file_hash(out_path),
                }
            )
        except Exception as exc:
            # Log page-level error but keep going with remaining pages
            pages.append(
                {"page": page_num + 1, "filename": filename, "error": str(exc)}
            )

    doc.close()

    # Write manifest so downstream scripts know what was extracted
    manifest = {
        "_meta": provenance_meta(script="01_extract_images.py", step=1),
        "source_pdf": pdf_path.name,
        "source_sha256": _file_hash(pdf_path),
        "dpi": dpi,
        "pages": pages,
    }
    manifest_path = out_dir / "manifest.json"
    try:
        write_json_atomic(manifest_path, manifest)
    except OSError as exc:
        return {
            "object_id": did,
            "file": str(pdf_path),
            "error": str(exc),
            "stage": "write",
        }

    ok_count = sum(1 for p in pages if "error" not in p)
    err_count = len(pages) - ok_count
    status = f"{ok_count} pages"
    if err_count:
        status += f", {err_count} errors"
    if err_count:
        return {
            "object_id": did,
            "file": str(pdf_path),
            "error": f"{err_count} of {len(pages)} pages could not be rendered",
            "stage": "render",
        }
    try:
        current_names = {page["filename"] for page in pages}
        for stale in out_dir.glob(f"{did}_p*.png"):
            if stale.name not in current_names:
                stale.unlink()
    except OSError as exc:
        return {
            "object_id": did,
            "file": str(pdf_path),
            "error": str(exc),
            "stage": "write",
        }
    print(f"  OK   {did} ({status})")
    return None


def collect_pdfs(single: str | None, all_flag: bool) -> list[Path]:
    if single:
        p = Path(single)
        if not p.is_absolute():
            p = PDF_DIR / p
        if not p.exists():
            print(f"ERROR: PDF not found: {p}", file=sys.stderr)
            sys.exit(1)
        pdfs = [p]
        problems = contract.unique_object_id_violations(
            [doc_id_from_path(path) for path in pdfs]
        )
        if problems:
            print("ERROR: " + "; ".join(problems), file=sys.stderr)
            sys.exit(1)
        return pdfs

    if all_flag:
        pdfs = sorted(PDF_DIR.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {PDF_DIR}", file=sys.stderr)
            sys.exit(1)
        problems = contract.unique_object_id_violations(
            [doc_id_from_path(path) for path in pdfs]
        )
        if problems:
            print("ERROR: " + "; ".join(problems), file=sys.stderr)
            sys.exit(1)
        return pdfs

    print("Specify --pdf FILE or --all", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Extract page images from PDFs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", metavar="FILE", help="Process a single PDF")
    group.add_argument(
        "--all", action="store_true", help="Process all PDFs in data/sources/pdf/"
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=IMAGE_DPI,
        help=f"Render resolution (default {IMAGE_DPI})",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-extract even if output exists"
    )
    args = parser.parse_args()

    ensure_dirs()
    pdfs = collect_pdfs(args.pdf, args.all)
    print(f"Extracting images from {len(pdfs)} PDF(s) at {args.dpi} DPI\n")

    errors: list[dict] = []
    for pdf_path in pdfs:
        err = extract_one(pdf_path, args.dpi, args.force)
        if err:
            errors.append(err)
            print(f"  FAIL {err['object_id']}: {err['error']}")

    write_errors(errors, IMAGES_DIR)
    if errors:
        print(f"\n{len(errors)} error(s) written to {IMAGES_DIR / 'errors.json'}")

    print(f"\nDone. Processed {len(pdfs)} PDF(s), {len(errors)} failed.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
