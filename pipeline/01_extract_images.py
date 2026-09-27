"""Extract page images from PDFs using PyMuPDF (fitz), step 1.

Flat script-pipeline regime. Each PDF data/sources/pdf/{id}.pdf becomes
data/processed/images/{id}/ with one PNG per page plus a manifest.json that
records the source PDF hash, the DPI and the SHA-256 of every page image, so
downstream steps read the pages through config.read_image_manifest instead
of scanning the directory.

Idempotent: a document whose manifest still matches the PDF bytes, the DPI
and the page files is skipped unless --force.

Usage:
    uv run python pipeline/01_extract_images.py --all
    uv run python pipeline/01_extract_images.py --object ID [--dpi 300] [--force]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz  # PyMuPDF

from config import (
    IMAGE_DPI,
    IMAGES_DIR,
    SOURCES_DIR,
    add_selection_args,
    configure_console,
    ensure_dirs,
    file_sha256,
    finish_run,
    provenance_meta,
    read_image_manifest,
    select_ids,
    write_bytes_atomic,
    write_json_atomic,
)

PDF_DIR = SOURCES_DIR / "pdf"


def doc_id_from_path(pdf_path: Path) -> str:
    return pdf_path.stem


def _complete_existing_extraction(out_dir: Path, pdf_path: Path, dpi: int) -> bool:
    """Return whether an existing manifest fully represents this PDF run."""
    try:
        manifest, _images = read_image_manifest(out_dir)
    except ValueError:
        return False
    return (
        manifest.get("source_pdf") == pdf_path.name
        and manifest.get("source_sha256") == file_sha256(pdf_path)
        and manifest.get("dpi") == dpi
    )


def _failure(pdf_path: Path, stage: str, message: str) -> dict:
    return {
        "object_id": doc_id_from_path(pdf_path),
        "file": str(pdf_path),
        "error": message,
        "stage": stage,
    }


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
        document = fitz.open(pdf_path)
    except Exception as exc:
        return _failure(pdf_path, "open", str(exc))

    pages: list[dict] = []
    # fitz renders at 72 DPI by default; the zoom matrix scales to the target.
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    # The context manager closes the document on any exit, so a failed run
    # does not leave the PDF locked on Windows.
    with document:
        for page_num in range(len(document)):
            filename = f"{did}_p{page_num + 1:03d}.png"
            out_path = out_dir / filename
            try:
                pix = document[page_num].get_pixmap(matrix=matrix)
                write_bytes_atomic(out_path, pix.tobytes("png"))
                pages.append(
                    {
                        "page": page_num + 1,
                        "filename": filename,
                        "sha256": file_sha256(out_path),
                    }
                )
            except Exception as exc:
                # A page-level error is recorded in the manifest, and the
                # remaining pages still render.
                pages.append(
                    {"page": page_num + 1, "filename": filename, "error": str(exc)}
                )

    manifest = {
        "_meta": provenance_meta(script="01_extract_images.py", step=1),
        "source_pdf": pdf_path.name,
        "source_sha256": file_sha256(pdf_path),
        "dpi": dpi,
        "pages": pages,
    }
    try:
        write_json_atomic(out_dir / "manifest.json", manifest)
    except OSError as exc:
        return _failure(pdf_path, "write", str(exc))

    err_count = sum(1 for page in pages if "error" in page)
    if err_count:
        return _failure(
            pdf_path,
            "render",
            f"{err_count} of {len(pages)} pages could not be rendered",
        )
    try:
        current_names = {page["filename"] for page in pages}
        for stale in out_dir.glob(f"{did}_p*.png"):
            if stale.name not in current_names:
                stale.unlink()
    except OSError as exc:
        return _failure(pdf_path, "write", str(exc))
    print(f"  OK   {did} ({len(pages)} pages)")
    return None


def collect_pdfs(
    object_id: str | None, all_flag: bool, sample: int | None
) -> list[Path]:
    """Select PDFs from data/sources/pdf/ by ID; exit 1 on an invalid selection."""
    pdfs = {path.stem: path for path in sorted(PDF_DIR.glob("*.pdf"))}
    return [pdfs[doc_id] for doc_id in select_ids(pdfs, object_id, all_flag, sample)]


def main() -> None:
    configure_console()
    parser = argparse.ArgumentParser(
        description="Extract page images from PDFs in data/sources/pdf/."
    )
    add_selection_args(parser)
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
    pdfs = collect_pdfs(args.object, args.all, args.sample)
    print(f"Extracting images from {len(pdfs)} PDF(s) at {args.dpi} DPI\n")

    errors: list[dict] = []
    for pdf_path in pdfs:
        error = extract_one(pdf_path, args.dpi, args.force)
        if error:
            errors.append(error)

    finish_run(
        errors,
        IMAGES_DIR,
        len(pdfs),
        "01_extract_images.py",
        summary=f"Done. Processed {len(pdfs)} PDF(s), {len(errors)} failed.",
    )


if __name__ == "__main__":
    main()
