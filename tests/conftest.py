"""Shared test setup: import the numbered pipeline scripts as modules."""
import importlib
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).parent.parent / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))


def load_step(name: str):
    """Import a pipeline module by filename stem (works for 04_validate etc.)."""
    return importlib.import_module(name)


@pytest.fixture
def fixture_transcription() -> dict:
    """A small contract-conformant transcription covering all page cases."""
    return {
        "_meta": {"script": "test", "timestamp": "2026-07-18T00:00:00+00:00", "pipeline_step": 3},
        "object_id": "fixture1",
        "metadata": {
            "title": "Brief vom 22. Mai 1901",
            "language": "fr",
            "date": "1901-05-22",
            "object_type": "Korrespondenz",
            "repository": "Example Archive",
            "image_urls": {
                "1": "https://example.org/o:fixture1/IMG.1",
                "2": "https://example.org/o:fixture1/IMG.2",
                "3": "https://example.org/o:fixture1/IMG.3",
                "4": "https://example.org/o:fixture1/IMG.4",
                "5": "https://example.org/o:fixture1/IMG.5",
            },
        },
        "pages": [
            {
                "page": 1,
                "transcription": "Erste Zeile\nZweite Zeile\n\nZweiter Absatz\n\nFremder Absatz",
                "notes": "",
                "foreign_paragraphs": [2],
            },
            {"page": 2, "transcription": "", "notes": "Farbkarte", "page_type": "blank"},
            {"page": 3, "transcription": "Anderer Beitrag", "page_type": "foreign_text"},
            {
                "page": 4,
                "transcription": "",
                "notes": "Doppelseiten-Scan, Satz zu klein",
                "page_type": "gate_low_resolution",
            },
            {"page": 5, "transcription": ""},
        ],
        "confidence": "high",
        "confidence_notes": "",
        "quality_signals": {
            "page_types": ["content", "blank", "foreign_text", "gate_low_resolution", "blank"],
            "total_chars": 60,
            "chars_per_page": 12.0,
            "blank_pages": 2,
            "gate_pages": 1,
            "foreign_pages": 1,
            "content_pages": 1,
            "needs_review": True,
        },
    }
