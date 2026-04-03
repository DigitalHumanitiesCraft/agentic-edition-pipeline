"""Extract page images from PDFs using PyMuPDF (fitz).

Each PDF becomes a directory under data/processed/images/{doc_id}/ containing
one PNG per page plus a manifest.json. The manifest records provenance and maps
page numbers to filenames, so downstream scripts never need to re-inspect the
images directory -- they just read the manifest.

Idempotent: existing document directories are skipped unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF

from config import (
    IMAGES_DIR,
    IMAGE_DPI,
    SOURCES_DIR,
    ensure_dirs,
    provenance_meta,
    write_errors,
)

PDF_DIR = SOURCES_DIR / "pdf"


def doc_id_from_path(pdf_path: Path) -> str:
    return pdf_path.stem


def extract_one(pdf_path: Path, dpi: int, force: bool) -> dict | None:
    """Extract all pages from a single PDF. Returns error dict on failure, None on success."""
    did = doc_id_from_path(pdf_path)
    out_dir = IMAGES_DIR / did

    if out_dir.exists() and not force:
        print(f"  SKIP {did} (already exists, use --force to re-extract)")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {"object_id": did, "file": str(pdf_path), "error": str(exc), "stage": "open"}

    pages: list[dict] = []
    # DPI conversion: fitz uses a zoom matrix; default render is 72 DPI
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        filename = f"{did}_p{page_num + 1:03d}.png"
        out_path = out_dir / filename
        try:
            pix = doc[page_num].get_pixmap(matrix=matrix)
            pix.save(str(out_path))
            pages.append({"page": page_num + 1, "filename": filename})
        except Exception as exc:
            # Log page-level error but keep going with remaining pages
            pages.append({"page": page_num + 1, "filename": filename, "error": str(exc)})

    doc.close()

    # Write manifest so downstream scripts know what was extracted
    manifest = {
        "_meta": provenance_meta(script="01_extract_images.py", step=1),
        "source_pdf": pdf_path.name,
        "dpi": dpi,
        "pages": pages,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    ok_count = sum(1 for p in pages if "error" not in p)
    err_count = len(pages) - ok_count
    status = f"{ok_count} pages"
    if err_count:
        status += f", {err_count} errors"
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
        return [p]

    if all_flag:
        pdfs = sorted(PDF_DIR.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {PDF_DIR}", file=sys.stderr)
            sys.exit(1)
        return pdfs

    print("Specify --pdf FILE or --all", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Extract page images from PDFs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", metavar="FILE", help="Process a single PDF")
    group.add_argument("--all", action="store_true", help="Process all PDFs in data/sources/pdf/")
    parser.add_argument("--dpi", type=int, default=IMAGE_DPI, help=f"Render resolution (default {IMAGE_DPI})")
    parser.add_argument("--force", action="store_true", help="Re-extract even if output exists")
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

    if errors:
        write_errors(errors, IMAGES_DIR)
        print(f"\n{len(errors)} error(s) written to {IMAGES_DIR / 'errors.json'}")

    print(f"\nDone. Processed {len(pdfs)} PDF(s), {len(errors)} failed.")


if __name__ == "__main__":
    main()
