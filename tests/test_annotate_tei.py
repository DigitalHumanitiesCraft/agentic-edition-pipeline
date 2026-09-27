"""Runnable checks for step 5: honest provenance, declared header values, exit code.

Step 5 generates TEI deterministically. The validation report must say so
and must not name a provider, a model, or a prompt template that no run
used. The header carries only declared values, and both publicationStmt
variants stay valid against the shipped schema. A document that could not
be processed has to reach the shell as a non-zero exit code.
"""

import hashlib
import importlib
import sys

import pytest
from lxml import etree

import config
import contract
from conftest import (
    NS,
    CasefoldCollidingDir,
    page_images,
    read_json,
    reseal_validated,
    review_event,
    write_json,
)

step5 = importlib.import_module("05_annotate_tei")


@pytest.fixture
def dirs(step5_dirs, fixture_validated):
    """step5_dirs holding the validated fixture as its input."""
    _write_input(step5_dirs, fixture_validated)
    return step5_dirs


def _write_input(dirs, data):
    write_json(dirs["validated_dir"] / f"{data['object_id']}.json", data)


def _annotate(dirs, project=None, validate_only=False, force=True):
    step5.annotate_one(
        "fixture1", project or {}, validate_only=validate_only, force=force, **dirs
    )
    return etree.parse(str(dirs["tei_dir"] / "fixture1.xml"))


def _failure(dirs, force=True, object_id="fixture1") -> config.ItemFailure:
    with pytest.raises(config.ItemFailure) as failure:
        step5.annotate_one(object_id, {}, False, force, **dirs)
    return failure.value


def _report(dirs) -> dict:
    return read_json(dirs["reports_dir"] / "fixture1_validation.json")


def _assert_schema_valid(root, schema):
    assert schema.validate(root), schema.error_log


def _regenerate(dirs, data):
    reseal_validated(data)
    _write_input(dirs, data)


def test_report_meta_documents_deterministic_generation(dirs, fixture_validated):
    _annotate(dirs)

    meta = _report(dirs)["_meta"]
    assert meta["script"] == "05_annotate_tei.py"
    assert meta["pipeline_step"] == 5
    assert not {"provider", "model", "prompt_template"} & set(meta)
    assert meta["validation_state_hash"] == contract.canonical_hash(fixture_validated)


def test_only_the_results_candidate_is_written(tmp_path, dirs):
    _annotate(dirs)

    written = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert written == [
        "reports/fixture1_validation.json",
        "tei/fixture1.xml",
        "validated/fixture1.json",
    ]


def test_header_maps_object_date_and_repository(dirs):
    root = _annotate(dirs)

    date = root.find(".//tei:origDate", NS)
    assert date is not None
    assert date.get("when") == "1901-05-22"
    assert date.text == "1901-05-22"
    assert root.findtext(".//tei:repository", namespaces=NS) == "Example Archive"
    assert root.findtext(".//tei:idno[@type='shelfmark']", namespaces=NS) == "A 1"
    assert root.findtext(".//tei:idno[@type='object-id']", namespaces=NS) == "fixture1"


def test_undeclared_language_omits_lang_usage(dirs, fixture_validated, tei_all):
    fixture_validated["metadata"]["title"] = ""
    fixture_validated["metadata"]["language"] = ""
    _regenerate(dirs, fixture_validated)

    root = _annotate(dirs)

    assert root.findtext(".//tei:titleStmt/tei:title", namespaces=NS) == "fixture1"
    assert root.find(".//tei:profileDesc", NS) is None
    _assert_schema_valid(root, tei_all)


def test_project_language_applies_when_the_document_declares_none(
    dirs, fixture_validated
):
    del fixture_validated["metadata"]["language"]
    _regenerate(dirs, fixture_validated)

    root = _annotate(dirs, {"language": "la"})

    language = root.find(".//tei:langUsage/tei:language", NS)
    assert language is not None
    assert (language.get("ident"), language.text) == ("la", "la")


def test_document_language_takes_precedence_over_the_project(dirs):
    root = _annotate(dirs, {"language": "la"})

    assert root.find(".//tei:langUsage/tei:language", NS).get("ident") == "fr"


def test_declared_publisher_and_licence_are_schema_valid(dirs, tei_all):
    root = _annotate(dirs, {"publisher": "Example Press", "license": "CC BY 4.0"})

    statement = root.find(".//tei:publicationStmt", NS)
    assert statement.findtext("tei:publisher", namespaces=NS) == "Example Press"
    assert (
        statement.findtext("tei:availability/tei:licence", namespaces=NS) == "CC BY 4.0"
    )
    _assert_schema_valid(root, tei_all)


def test_missing_publisher_is_stated_not_invented(dirs, tei_all):
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
    _assert_schema_valid(root, tei_all)


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
    dirs, fixture_validated, date_value, expected_when, tei_all
):
    fixture_validated["metadata"]["date"] = date_value
    _regenerate(dirs, fixture_validated)

    root = _annotate(dirs)

    date = root.find(".//tei:origDate", NS)
    assert date is not None
    assert date.text == date_value
    assert date.get("when") == expected_when
    _assert_schema_valid(root, tei_all)


def test_xml_illegal_metadata_is_rejected_before_generation(dirs, fixture_validated):
    fixture_validated["metadata"]["signature"] = "A\x0b1"
    _regenerate(dirs, fixture_validated)

    failure = _failure(dirs)

    assert failure.stage == "contract"
    assert "metadata.signature" in failure.message
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


def test_validate_only_writes_the_report_but_no_tei(dirs):
    step5.annotate_one("fixture1", {}, validate_only=True, force=False, **dirs)

    assert (dirs["reports_dir"] / "fixture1_validation.json").is_file()
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


# Overwrite guard


def test_nonforced_run_leaves_identical_tei_untouched(dirs):
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    expected = tei_path.read_bytes()
    before = tei_path.stat()

    _annotate(dirs, force=False)

    after = tei_path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    assert tei_path.read_bytes() == expected


def test_report_records_the_digest_of_the_written_tei(dirs):
    _annotate(dirs)
    digest = hashlib.sha256((dirs["tei_dir"] / "fixture1.xml").read_bytes()).hexdigest()

    assert _report(dirs)["_meta"]["tei_sha256"] == digest
    step5.annotate_one("fixture1", {}, validate_only=True, force=False, **dirs)
    assert _report(dirs)["_meta"]["tei_sha256"] == digest


def test_nonforced_run_refuses_to_replace_an_edited_tei(dirs):
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    enriched = tei_path.read_text(encoding="utf-8").replace(
        "Erste Zeile", "<persName>Erste</persName> Zeile"
    )
    tei_path.write_text(enriched, encoding="utf-8")

    assert _failure(dirs, force=False).stage == "write"
    assert tei_path.read_text(encoding="utf-8") == enriched
    # The refused run must keep the guard armed for the next one.
    assert _failure(dirs, force=False).stage == "write"


def test_existing_tei_without_recorded_digest_is_refused(dirs):
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    tei_path.write_text("<external/>", encoding="utf-8")

    assert _failure(dirs, force=False).stage == "write"
    assert tei_path.read_text(encoding="utf-8") == "<external/>"


def test_nonforced_run_replaces_its_own_tei_when_inputs_change(dirs, fixture_validated):
    _annotate(dirs)
    fixture_validated["metadata"]["title"] = "Changed title"
    _regenerate(dirs, fixture_validated)

    root = _annotate(dirs, force=False)

    assert root.findtext(".//tei:titleStmt/tei:title", namespaces=NS) == (
        "Changed title"
    )


def test_force_replaces_an_edited_tei(dirs):
    tei_path = dirs["tei_dir"] / "fixture1.xml"
    _annotate(dirs)
    expected = tei_path.read_bytes()
    tei_path.write_text("<edited/>", encoding="utf-8")

    _annotate(dirs, force=True)

    assert tei_path.read_bytes() == expected


# Input trust boundary


def test_unsafe_object_id_is_rejected_before_validated_path_use(tmp_path, step5_dirs):
    failure = _failure(step5_dirs, object_id="../outside")

    assert failure.stage == "contract"
    assert not (tmp_path / "outside.xml").exists()


def test_validation_state_hash_binds_human_review_history(dirs, fixture_validated):
    _annotate(dirs)
    first = _report(dirs)["_meta"]["validation_state_hash"]

    fixture_validated["pages"][0]["review"] = {
        "status": "in_review",
        "history": [review_event("machine_unreviewed", "in_review")],
    }
    _regenerate(dirs, fixture_validated)
    _annotate(dirs)

    assert _report(dirs)["_meta"]["validation_state_hash"] != first


def test_nonforced_run_blocks_unvalidated_input_changes(dirs, fixture_validated):
    _annotate(dirs)
    fixture_validated["metadata"]["title"] = "Changed title"
    _write_input(dirs, fixture_validated)

    assert _failure(dirs, force=False).stage == "contract"
    root = etree.parse(str(dirs["tei_dir"] / "fixture1.xml"))
    assert (
        root.findtext(".//tei:titleStmt/tei:title", namespaces=NS)
        == "Brief vom 22. Mai 1901"
    )


def test_tei_generation_blocks_changed_transcription_facsimiles(
    monkeypatch, tmp_path, dirs, fixture_validated
):
    images = page_images(tmp_path / "sources", 5, "fixture1_p{page:03d}.png")
    state = config.source_image_state(images)
    fixture_validated["source_images"] = [image.name for image in images]
    fixture_validated["transcription_meta"]["source_images"] = state
    fixture_validated["transcription_meta"]["source_images_hash"] = (
        config.source_image_state_hash(state)
    )
    _regenerate(dirs, fixture_validated)
    monkeypatch.setattr(step5, "ordered_page_images", lambda *_args, **_kwargs: images)
    images[0].write_bytes(b"changed")

    assert _failure(dirs).stage == "source_state"
    assert not (dirs["tei_dir"] / "fixture1.xml").exists()


# Command line and exit code


def _prepare_main(monkeypatch, step5_dirs, *arguments):
    monkeypatch.setattr(step5, "VALIDATED_DIR", step5_dirs["validated_dir"])
    monkeypatch.setattr(step5, "RESULTS_TEI_DIR", step5_dirs["tei_dir"])
    monkeypatch.setattr(step5, "RESULTS_REPORTS_DIR", step5_dirs["reports_dir"])
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "project_info", lambda: {"title": "Projekt"})
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", *(arguments or ("--all",))])
    return step5_dirs


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, step5_dirs):
    dirs = _prepare_main(monkeypatch, step5_dirs)
    (dirs["validated_dir"] / "broken.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1
    errors = read_json(dirs["reports_dir"] / "errors.json")["errors"]
    assert [(error["object_id"], error["stage"]) for error in errors] == [
        ("broken", "read")
    ]


def test_main_returns_cleanly_when_every_object_succeeds(monkeypatch, dirs):
    _prepare_main(monkeypatch, dirs)

    step5.main()

    assert (dirs["tei_dir"] / "fixture1.xml").exists()
    assert read_json(dirs["reports_dir"] / "errors.json")["errors"] == []


def test_main_sample_combines_with_all(monkeypatch, dirs):
    _prepare_main(monkeypatch, dirs, "--all", "--sample", "1")
    (dirs["validated_dir"] / "zz-later.json").write_text("{ not json", encoding="utf-8")

    step5.main()

    assert (dirs["tei_dir"] / "fixture1.xml").exists()


def test_main_rejects_casefold_collisions(monkeypatch, step5_dirs):
    _prepare_main(monkeypatch, step5_dirs)
    monkeypatch.setattr(step5, "VALIDATED_DIR", CasefoldCollidingDir(".json"))

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1
