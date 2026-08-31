"""Checks for the schema and human-acceptance deployment gate."""

from pathlib import Path

from conftest import load_step

publication = load_step("check_publication")
validate_schema = load_step("validate_schema")


def _tei(path: Path, status: str) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        f'<teiHeader><revisionDesc status="{status}"/></teiHeader>'
        "<text><body/></text></TEI>",
        encoding="utf-8",
    )


def test_publication_requires_human_acceptance(monkeypatch, tmp_path):
    candidate = tmp_path / "doc1.xml"
    _tei(candidate, "human_verified")
    monkeypatch.setattr(
        publication.validate_schema,
        "validate_files",
        lambda _schema, files: [validate_schema.FileResult(files[0], True)],
    )

    problems = publication.publication_problems([candidate], tmp_path / "schema.rng")

    assert problems == [
        "doc1.xml has human review status human_verified; accepted required"
    ]


def test_publication_accepts_schema_valid_accepted_tei(monkeypatch, tmp_path):
    candidate = tmp_path / "doc1.xml"
    _tei(candidate, "accepted")
    monkeypatch.setattr(
        publication.validate_schema,
        "validate_files",
        lambda _schema, files: [validate_schema.FileResult(files[0], True)],
    )

    assert publication.publication_problems([candidate], tmp_path / "schema.rng") == []
