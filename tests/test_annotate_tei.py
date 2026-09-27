"""Runnable checks for step 5: honest provenance, declared header values, exit code.

Step 5 generates TEI deterministically. The validation report must say so
and must not name a provider, a model, or a prompt template that no run
used. The header carries only declared values, and both publicationStmt
variants stay valid against the shipped schema. A document that could not
be processed has to reach the shell as a non-zero exit code.
"""

import json
import sys
from pathlib import Path

import pytest
from lxml import etree

from conftest import load_step

step5 = load_step("05_annotate_tei")
config = load_step("config")
contract = load_step("contract")
vs = load_step("validate_schema")

NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _reseal_validation(data):
    data["_meta"]["input_state_hash"] = contract.transcription_state_hash(data)


def _dirs(tmp_path, data=None) -> dict:
    dirs = {
        "validated_dir": tmp_path / "validated",
        "tei_dir": tmp_path / "results_tei",
        "reports_dir": tmp_path / "reports",
    }
    for path in dirs.values():
        path.mkdir()
    if data is not None:
        _write_input(dirs, data)
    return dirs


def _write_input(dirs, data):
    (dirs["validated_dir"] / f"{data['object_id']}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _annotate(dirs, project=None, validate_only=False, force=True):
    step5.annotate_one(
        "fixture1", project or {}, validate_only=validate_only, force=force, **dirs
    )
    return etree.parse(str(dirs["tei_dir"] / "fixture1.xml"))


def _assert_schema_valid(root):
    schema = vs.load_schema(config.VALIDATION_SCHEMA)
    assert schema.validate(root), schema.error_log


def test_report_meta_documents_deterministic_generation(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    _annotate(dirs)

    report = json.loads(
        (dirs["reports_dir"] / "fixture1_validation.json").read_text(encoding="utf-8")
    )
    assert report["_meta"]["script"] == "05_annotate_tei.py"
    assert report["_meta"]["pipeline_step"] == 5
    assert "provider" not in report["_meta"]
    assert "model" not in report["_meta"]
    assert "prompt_template" not in report["_meta"]
    assert report["_meta"]["validation_state_hash"] == contract.canonical_hash(
        fixture_validated
    )


def test_only_the_results_candidate_is_written(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    _annotate(dirs)

    written = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert written == [
        "reports/fixture1_validation.json",
        "results_tei/fixture1.xml",
        "validated/fixture1.json",
    ]


def test_header_maps_object_date_and_repository(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs)

    date = root.find(".//tei:origDate", NS)
    assert date is not None
    assert date.get("when") == "1901-05-22"
    assert date.text == "1901-05-22"
    assert root.findtext(".//tei:repository", namespaces=NS) == "Example Archive"
    assert root.findtext(".//tei:idno[@type='shelfmark']", namespaces=NS) == "A 1"
    assert root.findtext(".//tei:idno[@type='object-id']", namespaces=NS) == "fixture1"


def test_undeclared_language_omits_lang_usage(tmp_path, fixture_validated):
    fixture_validated["metadata"]["title"] = ""
    fixture_validated["metadata"]["language"] = ""
    _reseal_validation(fixture_validated)
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs)

    assert root.findtext(".//tei:titleStmt/tei:title", namespaces=NS) == "fixture1"
    assert root.find(".//tei:profileDesc", NS) is None
    _assert_schema_valid(root)


def test_project_language_applies_when_the_document_declares_none(
    tmp_path, fixture_validated
):
    del fixture_validated["metadata"]["language"]
    _reseal_validation(fixture_validated)
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs, {"language": "la"})

    language = root.find(".//tei:langUsage/tei:language", NS)
    assert language is not None
    assert (language.get("ident"), language.text) == ("la", "la")


def test_document_language_takes_precedence_over_the_project(
    tmp_path, fixture_validated
):
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs, {"language": "la"})

    assert root.find(".//tei:langUsage/tei:language", NS).get("ident") == "fr"


def test_declared_publisher_and_licence_are_schema_valid(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs, {"publisher": "Example Press", "license": "CC BY 4.0"})

    statement = root.find(".//tei:publicationStmt", NS)
    assert statement.findtext("tei:publisher", namespaces=NS) == "Example Press"
    assert (
        statement.findtext("tei:availability/tei:licence", namespaces=NS) == "CC BY 4.0"
    )
    _assert_schema_valid(root)


def test_missing_publisher_is_stated_not_invented(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs, {"license": "CC BY 4.0"})

    statement = root.find(".//tei:publicationStmt", NS)
    assert statement.find("tei:publisher", NS) is None
    assert [p.text for p in statement.findall("tei:p", NS)] == [
        "No publisher is declared in knowledge/01_PROJECT.md.",
        "Licence: CC BY 4.0",
    ]
    assert "agentic-edition-pipeline" not in etree.tostring(
        statement, encoding="unicode"
    )
    _assert_schema_valid(root)


@pytest.mark.parametrize(
    ("date_value", "expected_when"),
    [
        ("1901-03", "1901-03"),
        ("ca. 1901", None),
        ("1901/03/12", None),
        ('ca. 1901 & before <revision> "A"', None),
    ],
)
def test_header_only_normalizes_valid_tei_dates(
    tmp_path, fixture_validated, date_value, expected_when
):
    fixture_validated["metadata"]["date"] = date_value
    _reseal_validation(fixture_validated)
    dirs = _dirs(tmp_path, fixture_validated)

    root = _annotate(dirs)

    date = root.find(".//tei:origDate", NS)
    assert date is not None
    assert date.text == date_value
    assert date.get("when") == expected_when
    _assert_schema_valid(root)


def test_xml_illegal_metadata_is_rejected_before_generation(
    tmp_path, fixture_validated
):
    fixture_validated["metadata"]["signature"] = "A\x0b1"
    _reseal_validation(fixture_validated)
    dirs = _dirs(tmp_path, fixture_validated)

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("fixture1", {}, False, True, **dirs)

    assert failure.value.stage == "contract"
    assert "metadata.signature" in failure.value.message
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


def test_validate_only_writes_the_report_but_no_tei(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)

    step5.annotate_one("fixture1", {}, validate_only=True, force=False, **dirs)

    assert (dirs["reports_dir"] / "fixture1_validation.json").is_file()
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


def test_nonforced_run_skips_only_identical_tei(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _dirs(tmp_path, fixture_validated)
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    expected = tei_path.read_bytes()
    writes = []
    write_tei = step5._write_tei
    monkeypatch.setattr(
        step5,
        "_write_tei",
        lambda path, xml: (writes.append(path), write_tei(path, xml)),
    )

    _annotate(dirs, force=False)
    assert writes == []
    assert tei_path.read_bytes() == expected


def _tei_digest(dirs) -> str:
    report = dirs["reports_dir"] / "fixture1_validation.json"
    return json.loads(report.read_text(encoding="utf-8"))["_meta"]["tei_sha256"]


def test_report_records_the_digest_of_the_written_tei(tmp_path, fixture_validated):
    import hashlib

    dirs = _dirs(tmp_path, fixture_validated)
    _annotate(dirs)
    written = (dirs["tei_dir"] / "fixture1.xml").read_bytes()

    assert _tei_digest(dirs) == hashlib.sha256(written).hexdigest()
    step5.annotate_one("fixture1", {}, validate_only=True, force=False, **dirs)
    assert _tei_digest(dirs) == hashlib.sha256(written).hexdigest()


def test_nonforced_run_refuses_to_replace_an_edited_tei(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    enriched = tei_path.read_text(encoding="utf-8").replace(
        "Erste Zeile", "<persName>Erste</persName> Zeile"
    )
    tei_path.write_text(enriched, encoding="utf-8")

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("fixture1", {}, False, False, **dirs)

    assert failure.value.stage == "write"
    assert tei_path.read_text(encoding="utf-8") == enriched
    with pytest.raises(config.ItemFailure):
        step5.annotate_one("fixture1", {}, False, False, **dirs)


def test_existing_tei_without_recorded_digest_is_refused(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    tei_path.write_text("<external/>", encoding="utf-8")

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("fixture1", {}, False, False, **dirs)

    assert failure.value.stage == "write"
    assert tei_path.read_text(encoding="utf-8") == "<external/>"


def test_nonforced_run_replaces_its_own_tei_when_inputs_change(
    tmp_path, fixture_validated
):
    dirs = _dirs(tmp_path, fixture_validated)
    _annotate(dirs)
    fixture_validated["metadata"]["title"] = "Changed title"
    _reseal_validation(fixture_validated)
    _write_input(dirs, fixture_validated)

    root = _annotate(dirs, force=False)

    assert root.findtext(".//tei:titleStmt/tei:title", namespaces=NS) == (
        "Changed title"
    )


def test_force_replaces_an_edited_tei(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    expected = tei_path.read_bytes()
    tei_path.write_text("<edited/>", encoding="utf-8")

    _annotate(dirs, force=True)

    assert tei_path.read_bytes() == expected


def test_unsafe_object_id_is_rejected_before_validated_path_use(tmp_path):
    dirs = _dirs(tmp_path)

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("../outside", {}, False, True, **dirs)

    assert failure.value.stage == "contract"
    assert not (tmp_path / "outside.xml").exists()


def test_validation_state_hash_binds_human_review_history(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)
    report_path = dirs["reports_dir"] / "fixture1_validation.json"
    _annotate(dirs)
    first = json.loads(report_path.read_text(encoding="utf-8"))["_meta"][
        "validation_state_hash"
    ]

    fixture_validated["pages"][0]["review"] = {
        "status": "in_review",
        "history": [
            {
                "from_status": "machine_unreviewed",
                "status": "in_review",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:00:00+02:00",
            }
        ],
    }
    _reseal_validation(fixture_validated)
    _write_input(dirs, fixture_validated)
    _annotate(dirs)
    second = json.loads(report_path.read_text(encoding="utf-8"))["_meta"][
        "validation_state_hash"
    ]

    assert first != second


def test_nonforced_run_blocks_unvalidated_input_changes(tmp_path, fixture_validated):
    dirs = _dirs(tmp_path, fixture_validated)
    _annotate(dirs)

    fixture_validated["metadata"]["title"] = "Changed title"
    _write_input(dirs, fixture_validated)

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("fixture1", {}, False, False, **dirs)

    assert failure.value.stage == "contract"
    root = etree.parse(str(dirs["tei_dir"] / "fixture1.xml"))
    assert (
        root.findtext(".//tei:titleStmt/tei:title", namespaces=NS)
        == "Brief vom 22. Mai 1901"
    )


def test_tei_generation_blocks_changed_transcription_facsimiles(
    monkeypatch, tmp_path, fixture_validated
):
    images = []
    for page in range(1, 6):
        image = tmp_path / f"fixture1_p{page:03d}.png"
        image.write_bytes(f"original-{page}".encode())
        images.append(image)
    state = config.source_image_state(images)
    fixture_validated["source_images"] = [image.name for image in images]
    fixture_validated["transcription_meta"]["source_images"] = state
    fixture_validated["transcription_meta"]["source_images_hash"] = (
        config.source_image_state_hash(state)
    )
    _reseal_validation(fixture_validated)
    dirs = _dirs(tmp_path, fixture_validated)
    monkeypatch.setattr(step5, "ordered_page_images", lambda *_args, **_kwargs: images)
    images[0].write_bytes(b"changed")

    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one("fixture1", {}, False, True, **dirs)

    assert failure.value.stage == "source_state"
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


# Command line and exit code


def _prepare_main(monkeypatch, tmp_path, *arguments):
    dirs = _dirs(tmp_path)
    monkeypatch.setattr(step5, "VALIDATED_DIR", dirs["validated_dir"])
    monkeypatch.setattr(step5, "RESULTS_TEI_DIR", dirs["tei_dir"])
    monkeypatch.setattr(step5, "RESULTS_REPORTS_DIR", dirs["reports_dir"])
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "project_info", lambda: {"title": "Projekt"})
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", *(arguments or ("--all",))])
    return dirs


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, tmp_path):
    dirs = _prepare_main(monkeypatch, tmp_path)
    (dirs["validated_dir"] / "broken.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1
    errors = json.loads(
        (dirs["reports_dir"] / "errors.json").read_text(encoding="utf-8")
    )["errors"]
    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("broken", "read")
    ]


def test_main_returns_cleanly_when_every_object_succeeds(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_main(monkeypatch, tmp_path)
    _write_input(dirs, fixture_validated)

    step5.main()

    assert (dirs["tei_dir"] / "fixture1.xml").exists()
    assert (
        json.loads((dirs["reports_dir"] / "errors.json").read_text(encoding="utf-8"))[
            "errors"
        ]
        == []
    )


def test_main_sample_combines_with_all(monkeypatch, tmp_path, fixture_validated):
    dirs = _prepare_main(monkeypatch, tmp_path, "--all", "--sample", "1")
    _write_input(dirs, fixture_validated)
    (dirs["validated_dir"] / "zz-later.json").write_text("{ not json", encoding="utf-8")

    step5.main()

    assert (dirs["tei_dir"] / "fixture1.xml").exists()


def test_main_rejects_casefold_collisions(monkeypatch, tmp_path):
    class Inputs:
        def glob(self, _pattern):
            return [Path("Doc.json"), Path("doc.json")]

    _prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(step5, "VALIDATED_DIR", Inputs())

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1
