"""Publication cannot approve an interrupted or stale local review state."""

import json
from types import SimpleNamespace

import check_publication
import config
import validate_schema
from review_state import canonical_sha256


def test_pending_transaction_blocks_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    marker = tmp_path / "results/review-backups/pending.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    assert (
        "interrupted"
        in check_publication.publication_problems(
            [tmp_path / "doc.xml"], tmp_path / "schema.rng"
        )[0]
    )


def test_annotations_need_verifiable_current_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    tei = tmp_path / "doc.xml"
    tei.write_text(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><revisionDesc status="accepted"/></teiHeader></TEI>',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        validate_schema,
        "validate_files",
        lambda schema, files: [SimpleNamespace(valid=True, path=tei)],
    )
    annotation = tmp_path / "data/annotations/doc.json"
    annotation.parent.mkdir(parents=True)
    canonical = tmp_path / "data/processed/transcriptions/doc.json"
    canonical.parent.mkdir(parents=True)
    data = {"pages": [{"transcription": "Text"}]}
    annotation.write_text(
        json.dumps({"_meta": {"transcription_sha256": canonical_sha256(data)}}),
        encoding="utf-8",
    )
    assert check_publication.publication_problems([tei], tmp_path / "schema.rng")
    canonical.write_text(json.dumps(data), encoding="utf-8")
    assert not check_publication.publication_problems([tei], tmp_path / "schema.rng")
    canonical.write_text(
        json.dumps({"pages": [{"transcription": "Changed"}]}), encoding="utf-8"
    )
    assert (
        "stale"
        in check_publication.publication_problems([tei], tmp_path / "schema.rng")[0]
    )
