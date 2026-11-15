"""Checks for the schema and human-acceptance deployment gate."""

from pathlib import Path

import pytest

import check_publication as publication
import config
import validate_schema
from conftest import accept_pages, make_transcription, minimal_tei, write_json


@pytest.fixture(autouse=True)
def repository(monkeypatch, tmp_path):
    """Isolate the gate from the checkout's own review state and data."""
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RESULTS_TEI_DIR", tmp_path / "results/tei")
    monkeypatch.setattr(
        config, "TRANSCRIPTIONS_DIR", tmp_path / "data/processed/transcriptions"
    )
    # Schema validity has its own tests; here every candidate passes it.
    monkeypatch.setattr(
        validate_schema,
        "validate_files",
        lambda _schema, files: [
            validate_schema.FileResult(path, True) for path in files
        ],
    )
    return tmp_path


def _canonical(repository: Path, data: dict) -> None:
    write_json(repository / "data/processed/transcriptions/doc1.json", data)


def _tei(repository: Path, status: str, accepted_record: bool = True) -> Path:
    if accepted_record:
        _canonical(repository, accept_pages(make_transcription()))
    path = repository / "results/tei/doc1.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        minimal_tei(revision_desc=f'<revisionDesc status="{status}"/>'),
        encoding="utf-8",
    )
    return path


def test_publication_requires_human_acceptance(repository):
    candidate = _tei(repository, "human_verified")

    problems = publication.publication_problems([candidate], repository / "schema.rng")

    assert problems == [
        "doc1.xml has human review status human_verified; accepted required"
    ]


def test_hand_edited_accepted_attribute_does_not_pass_the_gate(repository):
    candidate = _tei(repository, "accepted", accepted_record=False)

    assert publication.publication_problems([candidate], repository / "schema.rng") == [
        "doc1.xml has no readable canonical transcription recording its acceptance"
    ]

    _canonical(repository, make_transcription())
    assert publication.publication_problems([candidate], repository / "schema.rng") == [
        "doc1.xml has pages whose recorded human review is not accepted"
    ]

    forged = accept_pages(make_transcription())
    forged["pages"][0]["transcription"] = "Changed after acceptance"
    _canonical(repository, forged)
    (problem,) = publication.publication_problems(
        [candidate], repository / "schema.rng"
    )
    assert problem.startswith(
        "doc1.xml has a canonical transcription that violates the data contract: "
    )
    assert "current page state" in problem


def test_publication_accepts_schema_valid_accepted_tei(repository):
    candidate = _tei(repository, "accepted")

    assert (
        publication.publication_problems([candidate], repository / "schema.rng") == []
    )


def test_schema_invalid_candidate_blocks_publication(monkeypatch, repository):
    candidate = _tei(repository, "accepted")
    monkeypatch.setattr(
        validate_schema,
        "validate_files",
        lambda _schema, files: [validate_schema.FileResult(files[0], False)],
    )

    assert publication.publication_problems([candidate], Path("tei_all.rng")) == [
        "doc1.xml is invalid against tei_all.rng"
    ]


@pytest.mark.parametrize(
    ("status", "code", "stream", "message"),
    [
        ("accepted", 0, "out", "Publication gate passed"),
        ("in_review", 1, "err", "accepted required"),
        (None, 1, "err", "no TEI candidates"),
    ],
    ids=["accepted", "unaccepted", "empty"],
)
def test_main_exit_code_is_zero_only_for_an_accepted_candidate_set(
    repository, capsys, status, code, stream, message
):
    if status is not None:
        _tei(repository, status)

    assert publication.main() == code
    assert message in getattr(capsys.readouterr(), stream)
