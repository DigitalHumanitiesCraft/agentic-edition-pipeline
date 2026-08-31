"""Configuration and shared utilities for the edition pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
SOURCES_DIR = DATA_DIR / "sources"
PROCESSED_DIR = DATA_DIR / "processed"
SOURCE_IMAGES_DIR = SOURCES_DIR / "images"
IMAGES_DIR = PROCESSED_DIR / "images"
TRANSCRIPTIONS_DIR = PROCESSED_DIR / "transcriptions"
VALIDATED_DIR = PROCESSED_DIR / "validated"
TEI_DIR = PROCESSED_DIR / "tei"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_TEI_DIR = RESULTS_DIR / "tei"
RESULTS_REPORTS_DIR = RESULTS_DIR / "reports"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
PROMPTS_DIR = SCRIPT_DIR / "prompts"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"
DOCS_TEI_DIR = DOCS_DIR / "tei"

# --- TEI validation target (ADR-005) ---
# Per-fork choice: point this at the RelaxNG schema your project validates
# against (TEI All, DTABf, or your own RNG; see schemas/README.md).
# Checked by pipeline/validate_schema.py. The default is TEI All, because the
# deterministic generator's output validates against it out of the box; the
# stricter DTABf profile (basisformat.rng) needs an adapted header first.
VALIDATION_SCHEMA = SCHEMAS_DIR / "tei_all.rng"

# --- API keys ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# --- Models per pipeline step ---
TRANSCRIPTION_PROVIDER = os.environ.get("TRANSCRIPTION_PROVIDER", "gemini")
TRANSCRIPTION_MODEL = os.environ.get("TRANSCRIPTION_MODEL", "gemini-2.5-flash")
VALIDATION_PROVIDER = os.environ.get("VALIDATION_PROVIDER", "")
VALIDATION_MODEL = os.environ.get("VALIDATION_MODEL", "")

# --- Processing ---
BATCH_DELAY = float(os.environ.get("BATCH_DELAY", "2.0"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "20"))
IMAGE_DPI = int(os.environ.get("IMAGE_DPI", "150"))
SUPPORTED_PROVIDERS = frozenset({"gemini", "openai", "anthropic", "ollama"})


def ensure_dirs() -> None:
    """Create all output directories if they do not exist."""
    for d in [
        IMAGES_DIR,
        TRANSCRIPTIONS_DIR,
        VALIDATED_DIR,
        TEI_DIR,
        RESULTS_TEI_DIR,
        RESULTS_REPORTS_DIR,
        DOCS_DATA_DIR,
        DOCS_TEI_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


# --- Image root resolution ---
# One resolver for all pipeline steps. Supplied scans in data/sources/images/
# take precedence over extracted or fetched images in data/processed/images/,
# so a corpus delivered as image files never depends on step 1.
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})


def list_page_images(directory: Path) -> list[Path]:
    """Return page images in natural filename order."""
    images = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    ]

    def natural_key(path: Path) -> list[tuple[int, int | str]]:
        return [
            (0, int(token)) if token.isdigit() else (1, token.casefold())
            for token in re.split(r"(\d+)", path.name)
        ]

    return sorted(images, key=natural_key)


def ordered_page_images(
    doc_id: str,
    expected_pages: int | None = None,
    expected_urls: list[str] | None = None,
) -> list[Path]:
    """Return page images in the order declared by the extraction manifest.

    Source-image folders usually have no manifest and fall back to filename
    order. A malformed generated manifest is a trust-boundary error because a
    fallback scan could silently include stale pages from an earlier run.
    """
    image_dir = resolve_image_dir(doc_id)
    if image_dir is None:
        return []

    manifest_path = image_dir / "manifest.json"
    if not manifest_path.exists():
        if expected_urls is not None:
            raise ValueError(
                f"{doc_id} declares remote facsimiles but has no materialization manifest"
            )
        images = list_page_images(image_dir)
        if expected_pages is not None and len(images) != expected_pages:
            raise ValueError(
                f"{doc_id} has {len(images)} page images; inventory declares {expected_pages}"
            )
        return images
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"cannot read image manifest {manifest_path}: {exc}") from exc
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list):
        raise ValueError(f"image manifest {manifest_path} carries no pages list")
    if expected_urls is not None and len(expected_urls) != len(pages):
        raise ValueError(
            f"{doc_id} has {len(pages)} materialized URLs; inventory declares "
            f"{len(expected_urls)}"
        )

    images: list[Path] = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise ValueError(f"image manifest page {index} is not an object")
        if page.get("page") != index:
            raise ValueError(
                f"image manifest pages must be ordered and numbered from 1; "
                f"entry {index} carries {page.get('page')!r}"
            )
        if (
            expected_urls is not None
            and page.get("image_url") != expected_urls[index - 1]
        ):
            raise ValueError(
                f"image manifest URL for page {index} differs from the inventory"
            )
        if "error" in page:
            raise ValueError(
                f"image manifest page {index} records an extraction error: {page['error']}"
            )
        filename = page.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"image manifest page {index} has an invalid filename")
        image_path = image_dir / filename
        if not image_path.is_file():
            raise ValueError(f"image manifest file is missing: {image_path}")
        expected_hash = page.get("sha256")
        if expected_hash is not None:
            if not isinstance(expected_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_hash
            ):
                raise ValueError(f"image manifest page {index} has an invalid SHA-256")
            actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(
                    f"image manifest file changed after creation: {image_path}"
                )
        images.append(image_path)
    if expected_pages is not None and len(images) != expected_pages:
        raise ValueError(
            f"{doc_id} has {len(images)} manifest pages; inventory declares {expected_pages}"
        )
    return images


def source_image_state(images: list[Path]) -> list[dict]:
    """Describe the ordered facsimile bytes consumed by a model run."""
    return [
        {
            "page": page,
            "filename": image.name,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        }
        for page, image in enumerate(images, start=1)
    ]


def source_image_state_hash(state: list[dict]) -> str:
    """Hash a facsimile-state declaration with stable JSON serialization."""
    serialized = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def resolve_image_dir(doc_id: str) -> Path | None:
    """Locate the image directory for a document.

    Checks data/sources/images/{doc_id}/ first, then
    data/processed/images/{doc_id}/. Returns None when neither
    contains page images.
    """
    for root in (SOURCE_IMAGES_DIR, IMAGES_DIR):
        candidate = root / doc_id
        if candidate.is_dir() and list_page_images(candidate):
            return candidate
    return None


# --- API key gate ---


def missing_api_key(provider: str) -> str | None:
    """Return the name of the missing env variable for a provider, or None.

    Ollama runs locally without a key; unknown providers fail later in llm.py.
    """
    required = {
        "gemini": ("GEMINI_API_KEY", GEMINI_API_KEY),
        "openai": ("OPENAI_API_KEY", OPENAI_API_KEY),
        "anthropic": ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    }
    if provider in required:
        name, value = required[provider]
        if not value:
            return name
    return None


def provider_config_error(provider: str, model: str) -> str | None:
    """Return one configuration error before any provider call is attempted."""
    if provider not in SUPPORTED_PROVIDERS:
        return f"unknown provider {provider!r}; choose one of " + ", ".join(
            sorted(SUPPORTED_PROVIDERS)
        )
    if not isinstance(model, str) or not model.strip():
        return f"no model configured for provider {provider!r}"
    return None


def load_prompt_path(path: Path) -> str:
    """Load one prompt file, preferring the first fenced code block."""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    return text.strip()


def load_prompt(filename: str) -> str:
    """Load a prompt below the shared prompt directory."""
    return load_prompt_path(PROMPTS_DIR / filename)


def read_knowledge(filename: str) -> str:
    """Read a knowledge document and return its text content."""
    path = KNOWLEDGE_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def provenance_meta(
    script: str,
    provider: str = "",
    model: str = "",
    prompt_template: str = "",
    step: int = 0,
) -> dict:
    """Build a _meta provenance block for JSON output files."""
    meta = {
        "script": script,
        "timestamp": datetime.now(UTC).isoformat(),
        "pipeline_step": step,
    }
    if provider:
        meta["provider"] = provider
    if model:
        meta["model"] = model
    if prompt_template:
        meta["prompt_template"] = prompt_template
        prompt_path = PROMPTS_DIR / prompt_template
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            meta["prompt_hash"] = hashlib.sha256(content.encode()).hexdigest()[:12]
    return meta


def write_text_atomic(path: Path, text: str) -> None:
    """Replace a UTF-8 text file atomically within its target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def write_bytes_atomic(path: Path, content: bytes) -> None:
    """Replace a binary file atomically within its target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data: object) -> None:
    """Serialize one JSON value and replace the target atomically."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    write_text_atomic(path, text)


def write_errors(errors: list[dict], output_dir: Path) -> None:
    """Write the complete error state of the current run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    errors_file = output_dir / "errors.json"
    write_json_atomic(
        errors_file,
        {
            "_meta": provenance_meta(script="pipeline_error_state", step=0),
            "errors": errors,
        },
    )
