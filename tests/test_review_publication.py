"""Publication cannot approve an interrupted or stale local review state."""

import pytest

import check_publication
import config
import validate_schema
from conftest import minimal_tei, write_json
from review_state import canonical_sha256


@pytest.fixture
def repository(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config, "TRANSCRIPTIONS_DIR", tmp_path / "data/processed/transcriptions"
    )
    monkeypatch.setattr(
        validate_schema,
        "validate_files",
        lambda _schema, files: [
            validate_schema.FileResult(path, True) for path in files
        ],
    )
    return tmp_path


def _problems(repository, tei):
    return check_publication.publication_problems([tei], repository / "schema.rng")


def test_pending_transaction_blocks_publication(repository):
    write_json(repository / "results/review-backups/pending.json", {})

    assert "interrupted" in _problems(repository, repository / "doc.xml")[0]


def test_annotations_need_verifiable_current_binding(repository):
    tei = repository / "doc.xml"
    tei.write_text(
        minimal_tei(revision_desc='<revisionDesc status="accepted"/>'),
        encoding="utf-8",
    )
    data = {"pages": [{"transcription": "Text"}]}
    write_json(
        repository / "data/annotations/doc.json",
        {"_meta": {"transcription_sha256": canonical_sha256(data)}},
    )
    canonical = repository / "data/processed/transcriptions/doc.json"

    assert _problems(repository, tei)
    write_json(canonical, data)
    assert not _problems(repository, tei)
    write_json(canonical, {"pages": [{"transcription": "Changed"}]})
    assert "stale" in _problems(repository, tei)[0]
