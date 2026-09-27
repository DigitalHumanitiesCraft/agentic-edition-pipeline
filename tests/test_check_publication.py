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


def _main(monkeypatch, tmp_path, status: str | None) -> int:
    tei_dir = tmp_path / "tei"
    tei_dir.mkdir()
    if status is not None:
        _tei(tei_dir / "doc1.xml", status)
    monkeypatch.setattr(publication.config, "RESULTS_TEI_DIR", tei_dir)
    monkeypatch.setattr(publication.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        publication.validate_schema,
        "validate_files",
        lambda _schema, files: [
            validate_schema.FileResult(path, True) for path in files
        ],
    )
    return publication.main()


def test_main_exit_code_is_zero_only_for_an_accepted_candidate_set(
    monkeypatch, tmp_path, capsys
):
    assert _main(monkeypatch, tmp_path, "accepted") == 0
    assert "Publication gate passed" in capsys.readouterr().out


def test_main_blocks_an_unaccepted_candidate(monkeypatch, tmp_path, capsys):
    assert _main(monkeypatch, tmp_path, "in_review") == 1
    assert "accepted required" in capsys.readouterr().err


def test_main_blocks_an_empty_candidate_set(monkeypatch, tmp_path, capsys):
    assert _main(monkeypatch, tmp_path, None) == 1
    assert "no TEI candidates" in capsys.readouterr().err
