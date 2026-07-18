"""Configuration and shared utilities for the edition pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
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
ANNOTATION_PROVIDER = os.environ.get("ANNOTATION_PROVIDER", "")
ANNOTATION_MODEL = os.environ.get("ANNOTATION_MODEL", "")

# --- Processing ---
BATCH_DELAY = float(os.environ.get("BATCH_DELAY", "2.0"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "20"))
IMAGE_DPI = int(os.environ.get("IMAGE_DPI", "150"))


def ensure_dirs():
    """Create all output directories if they do not exist."""
    for d in [IMAGES_DIR, TRANSCRIPTIONS_DIR, VALIDATED_DIR, TEI_DIR,
              RESULTS_TEI_DIR, RESULTS_REPORTS_DIR, DOCS_DATA_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# --- Image root resolution ---
# One resolver for all pipeline steps. Supplied scans in data/sources/images/
# take precedence over extracted or fetched images in data/processed/images/,
# so a corpus delivered as image files never depends on step 1.
IMAGE_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff")


def list_page_images(directory: Path) -> list[Path]:
    """Return all page images in a directory, sorted by filename."""
    images: list[Path] = []
    for pattern in IMAGE_EXTENSIONS:
        images.extend(directory.glob(pattern))
    return sorted(images)


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


def load_prompt(filename: str) -> str:
    """Load prompt text from a markdown file, extracting content from code blocks.

    Follows the szd-htr pattern: if the markdown contains fenced code blocks,
    return the content of the first block. Otherwise return the full text.
    """
    path = PROMPTS_DIR / filename
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[0].strip()
    return text.strip()


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


def write_errors(errors: list[dict], output_dir: Path):
    """Append errors to errors.json in the given output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    errors_file = output_dir / "errors.json"
    existing = []
    if errors_file.exists():
        try:
            existing = json.loads(errors_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    existing.extend(errors)
    errors_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
