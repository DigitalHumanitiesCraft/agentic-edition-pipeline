"""Configuration and shared utilities for the edition pipeline.

Flat script-pipeline regime: the numbered steps import this module by bare
name from pipeline/. It holds the paths, provider settings and the shared
helpers every step needs at a trust boundary: page-image discovery with
manifest verification, atomic writes, repository-bound path resolution,
secret redaction, the project metadata of knowledge/01_PROJECT.md and the
run scaffolding (object selection, error state, exit status).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from lxml import etree

import contract

load_dotenv()

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
CHUNK_CACHE_DIR = PROCESSED_DIR / "chunk-cache"
LLM_CALLS_DIR = PROCESSED_DIR / "llm-calls"
INVENTORY_PATH = DATA_DIR / "inventory.json"
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_TEI_DIR = RESULTS_DIR / "tei"
RESULTS_REPORTS_DIR = RESULTS_DIR / "reports"
REVIEW_BACKUP_DIR = RESULTS_DIR / "review-backups"
REVIEW_PENDING_MARKER = REVIEW_BACKUP_DIR / "pending.json"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
PROMPTS_DIR = SCRIPT_DIR / "prompts"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"
DOCS_TEI_DIR = DOCS_DIR / "tei"

# Per-fork choice (ADR-005): the RelaxNG schema the project validates
# against (TEI All, DTABf or an own RNG, see schemas/README.md). TEI All is
# the default because the deterministic generator's output validates against
# it as shipped; DTABf (basisformat.rng) needs an adapted header first.
VALIDATION_SCHEMA = SCHEMAS_DIR / "tei_all.rng"

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

TRANSCRIPTION_PROVIDER = os.environ.get("TRANSCRIPTION_PROVIDER", "gemini")
TRANSCRIPTION_MODEL = os.environ.get("TRANSCRIPTION_MODEL", "gemini-2.5-flash")
VALIDATION_PROVIDER = os.environ.get("VALIDATION_PROVIDER", "")
VALIDATION_MODEL = os.environ.get("VALIDATION_MODEL", "")
# Sent with every provider call and recorded in call records and the chunk
# cache identity, so the recorded value is the one actually used.
TEMPERATURE = 0.1

BATCH_DELAY = float(os.environ.get("BATCH_DELAY", "2.0"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "20"))
IMAGE_DPI = int(os.environ.get("IMAGE_DPI", "150"))
SUPPORTED_PROVIDERS = frozenset({"gemini", "openai", "anthropic", "ollama"})

# Provider errors quote the request URL and headers, so an unredacted
# message would end up in a console log or in errors.json.
REDACTED = "[redacted]"
_QUERY_KEY_RE = re.compile(
    r"([?&](?:key|api[_-]?key|access[_-]?token)=)[^&\s\"']+", re.IGNORECASE
)

# Rows of the field table in knowledge/01_PROJECT.md, matched exactly after
# casefold and strip; German labels stay accepted for existing editions.
PROJECT_FIELDS = {
    "title": "title",
    "projektname": "title",
    "titel": "title",
    "editor": "editor",
    "herausgeber": "editor",
    "institution": "publisher",
    "publisher": "publisher",
    "edition type": "edition_type",
    "editionstyp": "edition_type",
    "language": "language",
    "sprache": "language",
    "license": "license",
    "licence": "license",
    "lizenz": "license",
}
_TABLE_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.*?)\s*\|", re.MULTILINE)


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


def safe_xml_parser() -> etree.XMLParser:
    """An lxml parser that neither expands entities nor fetches over the network."""
    return etree.XMLParser(resolve_entities=False, no_network=True)


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


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in blocks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_image_manifest(image_dir: Path) -> tuple[dict, list[Path]]:
    """Read and verify image_dir/manifest.json written by step 1 or the fetcher.

    Returns the manifest object and the page image paths in manifest order.
    Every page must be numbered consecutively from 1, carry no extraction
    error, name an existing file inside image_dir and record the SHA-256 of
    that file's current bytes. Any deviation raises ValueError, because a
    fallback directory scan could silently include stale pages.
    """
    manifest_path = image_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read image manifest {manifest_path}: {exc}") from exc
    pages = manifest.get("pages") if isinstance(manifest, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ValueError(f"image manifest {manifest_path} carries no pages list")

    images: list[Path] = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise ValueError(f"image manifest page {index} is not an object")
        if page.get("page") != index:
            raise ValueError(
                f"image manifest pages must be ordered and numbered from 1; "
                f"entry {index} carries {page.get('page')!r}"
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
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise ValueError(f"image manifest page {index} has no valid SHA-256")
        if file_sha256(image_path) != expected_hash:
            raise ValueError(
                f"image manifest file changed after creation: {image_path}"
            )
        images.append(image_path)
    return manifest, images


def ordered_page_images(
    doc_id: str,
    expected_pages: int | None = None,
    expected_urls: list[str] | None = None,
) -> list[Path]:
    """Return page images in the order declared by the extraction manifest.

    Source-image folders usually have no manifest and fall back to filename
    order. A generated manifest is verified by read_image_manifest.
    """
    image_dir = resolve_image_dir(doc_id)
    if image_dir is None:
        return []

    if not (image_dir / "manifest.json").exists():
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

    manifest, images = read_image_manifest(image_dir)
    if expected_urls is not None:
        if len(expected_urls) != len(images):
            raise ValueError(
                f"{doc_id} has {len(images)} materialized URLs; inventory declares "
                f"{len(expected_urls)}"
            )
        for index, (page, url) in enumerate(
            zip(manifest["pages"], expected_urls, strict=True), start=1
        ):
            if page.get("image_url") != url:
                raise ValueError(
                    f"image manifest URL for page {index} differs from the inventory"
                )
    if expected_pages is not None and len(images) != expected_pages:
        raise ValueError(
            f"{doc_id} has {len(images)} manifest pages; inventory declares {expected_pages}"
        )
    return images


def source_image_state(images: list[Path]) -> list[dict]:
    """Describe the ordered facsimile bytes consumed by a model run."""
    return [
        {"page": page, "filename": image.name, "sha256": file_sha256(image)}
        for page, image in enumerate(images, start=1)
    ]


def source_image_state_hash(state: list[dict]) -> str:
    """Hash a facsimile-state declaration with stable JSON serialization."""
    return contract.canonical_hash(state)


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


def missing_api_key(provider: str) -> str | None:
    """Return the name of the missing env variable for a provider, or None.

    Ollama runs locally without a key; unknown providers fail in
    provider_config_error or llm.call_llm.
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


def redact_secrets(text: str) -> str:
    """Remove key query parameters and configured key values from a message."""
    if not text:
        return ""
    cleaned = _QUERY_KEY_RE.sub(rf"\g<1>{REDACTED}", text)
    for secret in (GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY):
        if secret:
            cleaned = cleaned.replace(secret, REDACTED)
    return cleaned


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


def project_info(path: Path | None = None) -> dict[str, str]:
    """Read the project fields of the field table in knowledge/01_PROJECT.md.

    Only Markdown table rows are read, and a label counts only when it equals
    a PROJECT_FIELDS key after casefold and strip. An empty value or one
    starting with "[TODO" is missing; the first filled row of a field wins.
    Returns only the filled fields (title, editor, publisher, edition_type,
    language, license), so the unfilled template yields an empty dict. A
    missing file also yields an empty dict. path defaults to
    KNOWLEDGE_DIR / "01_PROJECT.md", resolved at call time.
    """
    path = path if path is not None else KNOWLEDGE_DIR / "01_PROJECT.md"
    if not path.exists():
        return {}
    info: dict[str, str] = {}
    for match in _TABLE_ROW.finditer(path.read_text(encoding="utf-8")):
        field = PROJECT_FIELDS.get(match.group(1).strip().casefold())
        value = match.group(2).strip()
        if field and value and not value.startswith("[TODO") and field not in info:
            info[field] = value
    return info


def provenance_meta(
    script: str,
    provider: str = "",
    model: str = "",
    prompt_template: str = "",
    step: int = 0,
) -> dict:
    """Build a _meta provenance block for JSON output files.

    The caller records prompt_hash itself, because only it knows the prompt
    that was actually executed.
    """
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
    return meta


def json_bytes(data: object) -> bytes:
    """Serialize one JSON value exactly as every pipeline JSON file is written."""
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


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


def write_text_atomic(path: Path, text: str) -> None:
    """Replace a UTF-8 text file atomically; newlines are written unchanged."""
    write_bytes_atomic(path, text.encode("utf-8"))


def write_json_atomic(path: Path, data: object) -> None:
    """Serialize one JSON value and replace the target atomically."""
    write_bytes_atomic(path, json_bytes(data))


def read_json(path: Path) -> object:
    """Parse a UTF-8 JSON file; invalid content raises ValueError naming the path.

    A missing or unreadable file raises the underlying OSError unchanged.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def is_link_or_reparse_point(path: Path) -> bool:
    """Inspect one path component without following it.

    Symlinks, Windows junctions and other reparse points count as links; a
    component that does not exist does not.
    """
    try:
        status = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(reparse_flag & attributes)


def safe_path(root: Path, relative: Path) -> Path:
    """Resolve a repository-relative path that cannot leave root.

    Rejects absolute paths, parent references, targets whose resolution
    escapes root, and any link or reparse point on the way from root to the
    target. Raises ValueError; the target itself need not exist.
    """
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Path must remain inside the repository")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes the repository")
    for component in (target, *target.parents):
        if is_link_or_reparse_point(component):
            raise ValueError("Linked paths are not allowed")
        if component == root:
            break
    return target


def write_errors(errors: list[dict], output_dir: Path, stage: str) -> None:
    """Write the complete error state of the current run.

    stage names the script that ran, for example "03_transcribe.py", and
    becomes _meta.script of errors.json.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        output_dir / "errors.json",
        {"_meta": provenance_meta(script=stage, step=0), "errors": errors},
    )


class ItemFailure(Exception):
    """An item-level failure a run records in errors.json and then continues.

    stage is the error record's stage label (for example "read", "contract",
    "api_call"); message is the human-readable reason and str(exception).
    """

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    """Add the shared object selection: --object ID | --all [--sample N]."""
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--object", metavar="ID", help="Process one object by ID")
    group.add_argument("--all", action="store_true", help="Process all objects")
    parser.add_argument(
        "--sample",
        type=_positive_int,
        metavar="N",
        help="With --all, process only the first N objects",
    )


def select_ids(
    candidates: Iterable[str],
    object_id: str | None,
    all_flag: bool,
    sample: int | None,
) -> list[str]:
    """Return the selected object IDs or exit 1 with an ERROR line on stderr.

    candidates are the available IDs in processing order; the caller removes
    non-object files such as errors.json first. All candidates must pass
    contract.unique_object_id_violations, which also rejects the reserved
    names. --object must name a candidate, --sample requires --all and keeps
    the first N candidates, and an empty selection is an error.
    """
    ids = list(candidates)
    problems = contract.unique_object_id_violations(ids)
    if sample is not None and not all_flag:
        problems.append("--sample requires --all")
    if object_id is not None and object_id not in ids:
        problems.append(f"object {object_id!r} not found")
    if not ids:
        problems.append("no objects available")
    if problems:
        print("ERROR: " + "; ".join(problems), file=sys.stderr)
        sys.exit(1)
    if object_id is not None:
        return [object_id]
    return ids[:sample] if sample is not None else ids


def require_provider(provider: str, model: str, hint: str = "") -> None:
    """Exit 1 before any provider call when provider, model or key is missing.

    hint is appended to the missing-key message, for example
    ", or run with --no-llm for deterministic validation".
    """
    config_error = provider_config_error(provider, model)
    if config_error:
        print(f"ERROR: {config_error}.", file=sys.stderr)
        sys.exit(1)
    missing = missing_api_key(provider)
    if missing:
        print(
            f"ERROR: no API key configured, this step requires one. "
            f"Set {missing} in .env for provider '{provider}'{hint}.",
            file=sys.stderr,
        )
        sys.exit(1)


def finish_run(
    errors: list[dict],
    errors_dir: Path,
    total: int,
    stage: str,
    summary: str = "",
) -> None:
    """Record the run's error state and set its exit status.

    Always writes errors_dir/errors.json (an empty list clears an earlier
    failure). Each error record prints as "FAIL {object_id}: {error}" on
    stderr. summary, when given, goes to stdout on success and to stderr on
    failure. With errors, a count line naming errors.json follows on stderr
    and the process exits 1; otherwise the function returns.
    """
    write_errors(errors, errors_dir, stage)
    stream = sys.stderr if errors else sys.stdout
    for error in errors:
        print(
            f"FAIL {error.get('object_id', '?')}: {error.get('error', '')}",
            file=sys.stderr,
        )
    if summary:
        print(summary, file=stream)
    if errors:
        print(
            f"{len(errors)} of {total} item(s) failed; details in "
            f"{errors_dir / 'errors.json'}",
            file=sys.stderr,
        )
        sys.exit(1)


def configure_console() -> None:
    """Make stdout and stderr UTF-8 so redirected cp1252 consoles cannot crash."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
