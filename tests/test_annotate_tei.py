"""Runnable checks for step 5: honest provenance and exit code.

Step 5 generates TEI deterministically. The validation report must say so
and must not name a provider, a model, or a prompt template that no run
used. A document that could not be processed has to reach the shell as a
non-zero exit code.
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


def _reseal_validation(data):
    data["_meta"]["input_state_hash"] = contract.transcription_state_hash(data)


def _prepare_dirs(monkeypatch, tmp_path):
    dirs = {
        name: tmp_path / name for name in ("validated", "tei", "results_tei", "reports")
    }
    for path in dirs.values():
        path.mkdir()
    monkeypatch.setattr(step5, "VALIDATED_DIR", dirs["validated"])
    monkeypatch.setattr(step5, "TEI_DIR", dirs["tei"])
    monkeypatch.setattr(step5, "RESULTS_TEI_DIR", dirs["results_tei"])
    monkeypatch.setattr(step5, "RESULTS_REPORTS_DIR", dirs["reports"])
    return dirs


def test_report_meta_documents_deterministic_generation(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    report = json.loads(
        (dirs["reports"] / "fixture1_validation.json").read_text(encoding="utf-8")
    )
    assert report["_meta"]["script"] == "05_annotate_tei.py"
    assert report["_meta"]["pipeline_step"] == 5
    assert "provider" not in report["_meta"]
    assert "model" not in report["_meta"]
    assert "prompt_template" not in report["_meta"]


def test_header_maps_object_date_and_repository(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    fixture_validated["metadata"]["signature"] = "A 1"
    _reseal_validation(fixture_validated)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    root = etree.parse(str(dirs["results_tei"] / "fixture1.xml"))
    date = root.find(".//tei:origDate", namespace)
    assert date is not None
    assert date.get("when") == "1901-05-22"
    assert date.text == "1901-05-22"
    assert root.findtext(".//tei:repository", namespaces=namespace) == "Example Archive"
    assert (
        root.findtext(".//tei:idno[@type='shelfmark']", namespaces=namespace) == "A 1"
    )
    assert (
        root.findtext(".//tei:idno[@type='object-id']", namespaces=namespace)
        == "fixture1"
    )


def test_header_falls_back_for_explicitly_empty_title_and_language(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    fixture_validated["metadata"]["title"] = ""
    fixture_validated["metadata"]["language"] = ""
    _reseal_validation(fixture_validated)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    root = etree.parse(str(dirs["results_tei"] / "fixture1.xml"))
    assert (
        root.findtext(".//tei:titleStmt/tei:title", namespaces=namespace) == "fixture1"
    )
    language = root.find(".//tei:langUsage/tei:language", namespace)
    assert language is not None
    assert language.get("ident") == "de"
    assert language.text == "de"


@pytest.mark.parametrize(
    ("date_value", "expected_when"),
    [
        ("1901-03", "1901-03"),
        ("ca. 1901", None),
        ("1901/03/12", None),
    ],
)
def test_header_only_normalizes_valid_tei_dates(
    monkeypatch, tmp_path, fixture_validated, date_value, expected_when
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    fixture_validated["metadata"]["date"] = date_value
    _reseal_validation(fixture_validated)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    root = etree.parse(str(dirs["results_tei"] / "fixture1.xml"))
    date = root.find(".//tei:origDate", namespace)
    assert date is not None
    assert date.text == date_value
    assert date.get("when") == expected_when
    etree.RelaxNG(etree.parse(str(config.VALIDATION_SCHEMA))).assertValid(root)


def test_header_escapes_free_text_date(monkeypatch, tmp_path, fixture_validated):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    date_value = 'ca. 1901 & before <revision> "A"'
    fixture_validated["metadata"]["date"] = date_value
    _reseal_validation(fixture_validated)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )

    assert step5.annotate_one("fixture1", {}, validate_only=False, force=True) is None

    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    tei_path = dirs["results_tei"] / "fixture1.xml"
    root = etree.parse(str(tei_path))
    date = root.find(".//tei:origDate", namespace)
    assert date is not None
    assert date.text == date_value
    assert date.get("when") is None
    etree.RelaxNG(etree.parse(str(config.VALIDATION_SCHEMA))).assertValid(root)


def test_main_exits_nonzero_on_a_processing_error(monkeypatch, tmp_path):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "broken.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", "--all"])

    with pytest.raises(SystemExit) as exc:
        step5.main()

    assert exc.value.code == 1


def test_unsafe_object_id_is_rejected_before_validated_path_use(monkeypatch, tmp_path):
    dirs = _prepare_dirs(monkeypatch, tmp_path)

    error = step5.annotate_one("../outside", {}, False, True)

    assert error is not None and error["stage"] == "contract"
    assert not (dirs["results_tei"] / "outside.xml").exists()


def test_main_returns_cleanly_when_every_object_succeeds(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(step5, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step5, "read_knowledge", lambda _n: "# Projekt")
    monkeypatch.setattr(sys, "argv", ["05_annotate_tei.py", "--all"])

    step5.main()

    assert (dirs["results_tei"] / "fixture1.xml").exists()


def test_collection_rejects_casefold_collisions(monkeypatch):
    class Inputs:
        def glob(self, _pattern):
            return [Path("Doc.json"), Path("doc.json")]

        def __str__(self):
            return "validated"

    monkeypatch.setattr(step5, "VALIDATED_DIR", Inputs())

    with pytest.raises(SystemExit) as exc:
        step5.collect_objects(None, True, None)

    assert exc.value.code == 1


def test_validation_state_hash_binds_human_review_history(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    source = dirs["validated"] / "fixture1.json"
    source.write_text(json.dumps(fixture_validated), encoding="utf-8")
    assert step5.annotate_one("fixture1", {}, False, True) is None
    first = json.loads(
        (dirs["reports"] / "fixture1_validation.json").read_text(encoding="utf-8")
    )["_meta"]["validation_state_hash"]

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
    source.write_text(json.dumps(fixture_validated), encoding="utf-8")
    assert step5.annotate_one("fixture1", {}, False, True) is None
    second = json.loads(
        (dirs["reports"] / "fixture1_validation.json").read_text(encoding="utf-8")
    )["_meta"]["validation_state_hash"]

    assert first != second


def test_nonforced_run_blocks_unvalidated_input_changes(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
    source = dirs["validated"] / "fixture1.json"
    source.write_text(json.dumps(fixture_validated), encoding="utf-8")
    assert step5.annotate_one("fixture1", {}, False, True) is None

    fixture_validated["metadata"]["title"] = "Changed title"
    source.write_text(json.dumps(fixture_validated), encoding="utf-8")

    error = step5.annotate_one("fixture1", {}, False, False)

    assert error is not None and error["stage"] == "contract"
    root = etree.parse(str(dirs["results_tei"] / "fixture1.xml"))
    assert (
        root.findtext(
            ".//tei:titleStmt/tei:title",
            namespaces={"tei": "http://www.tei-c.org/ns/1.0"},
        )
        == "Brief vom 22. Mai 1901"
    )


def test_tei_generation_blocks_changed_transcription_facsimiles(
    monkeypatch, tmp_path, fixture_validated
):
    dirs = _prepare_dirs(monkeypatch, tmp_path)
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
    (dirs["validated"] / "fixture1.json").write_text(
        json.dumps(fixture_validated), encoding="utf-8"
    )
    monkeypatch.setattr(step5, "ordered_page_images", lambda *_args, **_kwargs: images)
    images[0].write_bytes(b"changed")

    error = step5.annotate_one("fixture1", {}, False, True)

    assert error is not None and error["stage"] == "source_state"
    assert not (dirs["results_tei"] / "fixture1.xml").exists()
