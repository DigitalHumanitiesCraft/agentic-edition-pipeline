"""Shared test setup: import the numbered pipeline scripts as modules."""

import copy
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
        "_meta": {
            "script": "manual",
            "timestamp": "2026-07-18T00:00:00+00:00",
            "pipeline_step": 0,
        },
        "object_id": "fixture1",
        "metadata": {
            "title": "Brief vom 22. Mai 1901",
            "language": "fr",
            "date": "1901-05-22",
            "object_type": "Korrespondenz",
            "repository": "Example Archive",
            "signature": "A 1",
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
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 2,
                "transcription": "",
                "notes": "Farbkarte",
                "page_type": "blank",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 3,
                "transcription": "Anderer Beitrag",
                "page_type": "foreign_text",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 4,
                "transcription": "",
                "notes": "Doppelseiten-Scan, Satz zu klein",
                "page_type": "gate_low_resolution",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 5,
                "transcription": "",
                "review": {"status": "machine_unreviewed", "history": []},
            },
        ],
        "confidence": "high",
        "confidence_notes": "",
        "quality_signals": {
            "page_types": [
                "content",
                "blank",
                "foreign_text",
                "gate_low_resolution",
                "undeclared_empty",
            ],
            "total_chars": 60,
            "chars_per_page": 12.0,
            "blank_pages": 1,
            "undeclared_empty_pages": 1,
            "gate_pages": 1,
            "foreign_pages": 1,
            "content_pages": 1,
            "needs_review": True,
        },
    }


@pytest.fixture
def fixture_validated(fixture_transcription) -> dict:
    """A step-4 output that is admissible at the TEI trust boundary."""
    validated = copy.deepcopy(fixture_transcription)
    transcription_meta = validated["_meta"]
    validated["_meta"] = {
        "script": "04_validate.py",
        "timestamp": "2026-07-18T00:01:00+00:00",
        "pipeline_step": 4,
    }
    validated["transcription_meta"] = transcription_meta
    validated["overall_status"] = "needs_review"
    validated["validation"] = {
        "rules": [],
        "per_page_stats": [
            {
                "page": page["page"],
                "char_count": len(page["transcription"]),
                "word_count": len(page["transcription"].split()),
                "line_count": page["transcription"].count("\n")
                + (1 if page["transcription"] else 0),
            }
            for page in validated["pages"]
        ],
        "total_characters": sum(
            len(page["transcription"]) for page in validated["pages"]
        ),
    }
    validated["_meta"]["input_state_hash"] = load_step(
        "contract"
    ).transcription_state_hash(validated)
    validated["_meta"]["validation_result_hash"] = load_step(
        "contract"
    ).validation_result_hash(validated)
    return validated
