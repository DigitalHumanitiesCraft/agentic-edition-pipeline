"""Checks for the shared configuration helpers of pipeline/config.py.

Covers atomic output, page-order and manifest boundaries, prompt and
knowledge loading, the project field table, repository-bound paths and the
shared run scaffolding.
"""

import argparse
from pathlib import Path

import pytest

import config
from conftest import page_images, read_json, write_image_manifest


@pytest.fixture
def image_roots(monkeypatch, tmp_path):
    """Point the shared image resolver at tmp_path; returns the processed root."""
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "IMAGES_DIR", tmp_path / "images")
    return tmp_path / "images"


# Atomic output and JSON


def test_atomic_text_write_preserves_old_target_when_replace_fails(
    monkeypatch, tmp_path
):
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_self, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        config.write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_json_serialisation_is_byte_stable(tmp_path):
    value = {"b": "Grüße", "a": [1, None]}
    expected = '{\n  "b": "Grüße",\n  "a": [\n    1,\n    null\n  ]\n}\n'.encode()

    assert config.json_bytes(value) == expected
    config.write_json_atomic(tmp_path / "v.json", value)
    assert (tmp_path / "v.json").read_bytes() == expected
    config.write_text_atomic(tmp_path / "t.txt", "a\r\nb")
    assert (tmp_path / "t.txt").read_bytes() == b"a\r\nb"


def test_read_json_names_the_path_of_invalid_content(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ValueError, match="broken"):
        config.read_json(path)
    with pytest.raises(FileNotFoundError):
        config.read_json(tmp_path / "absent.json")


# Page images and manifests


def test_source_images_use_natural_page_order(tmp_path):
    directory = tmp_path / "doc1"
    directory.mkdir()
    for name in ("page10.png", "page2.png", "page1.png"):
        (directory / name).write_bytes(name.encode())

    assert [path.name for path in config.list_page_images(directory)] == [
        "page1.png",
        "page2.png",
        "page10.png",
    ]


def test_source_image_discovery_is_case_insensitive(tmp_path):
    directory = tmp_path / "doc1"
    directory.mkdir()
    (directory / "PAGE001.JPG").write_bytes(b"jpg")
    (directory / "PAGE002.TIFF").write_bytes(b"tiff")

    assert [path.name for path in config.list_page_images(directory)] == [
        "PAGE001.JPG",
        "PAGE002.TIFF",
    ]


def test_manifest_error_page_blocks_image_discovery(image_roots):
    page_images(image_roots / "doc1", 1, "doc1_p{page:03d}.png")
    write_image_manifest(
        image_roots / "doc1",
        ["doc1_p001.png", {"filename": "doc1_p002.png", "error": "render failed"}],
    )

    with pytest.raises(ValueError, match="extraction error"):
        config.ordered_page_images("doc1", expected_pages=2)


def test_manifest_hash_blocks_changed_facsimile(image_roots):
    (image,) = page_images(image_roots / "doc1", 1, "doc1_p{page:03d}.png")
    write_image_manifest(image_roots / "doc1", [image.name])
    image.write_bytes(b"changed")

    with pytest.raises(ValueError, match="changed after creation"):
        config.ordered_page_images("doc1")


def test_materialized_remote_url_must_match_inventory(image_roots):
    (image,) = page_images(image_roots / "doc1", 1, "doc1_p{page:03d}.png")
    write_image_manifest(
        image_roots / "doc1",
        [{"filename": image.name, "image_url": "https://example.org/a.png"}],
    )

    with pytest.raises(ValueError, match="differs from the inventory"):
        config.ordered_page_images("doc1", expected_urls=["https://example.org/b.png"])


def test_manifest_page_without_hash_is_rejected(tmp_path):
    (image,) = page_images(tmp_path, 1)
    write_image_manifest(tmp_path, [{"filename": image.name, "sha256": None}])

    with pytest.raises(ValueError, match="SHA-256"):
        config.read_image_manifest(tmp_path)

    manifest = write_image_manifest(tmp_path, [image.name])
    assert config.read_image_manifest(tmp_path) == (manifest, [image])


# Prompts and knowledge


def test_prompt_prefers_its_first_fenced_block(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    (tmp_path / "fenced.md").write_text(
        "# Notes for editors\n\n```\nTranscribe exactly.\n```\n\n```\nsecond\n```\n",
        encoding="utf-8",
    )
    (tmp_path / "plain.md").write_text("\n  Plain prompt.  \n", encoding="utf-8")

    assert config.load_prompt("fenced.md") == "Transcribe exactly."
    assert config.load_prompt("plain.md") == "Plain prompt."


def test_read_knowledge_returns_empty_text_for_an_absent_document(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(config, "KNOWLEDGE_DIR", tmp_path)
    (tmp_path / "02_DATA.md").write_text("Inventar", encoding="utf-8")

    assert config.read_knowledge("02_DATA.md") == "Inventar"
    assert config.read_knowledge("absent.md") == ""


# Project field table

PROJECT_TEMPLATE = config.KNOWLEDGE_DIR / "01_PROJECT.md"


def test_unfilled_project_template_yields_no_values():
    assert config.project_info(PROJECT_TEMPLATE) == {}


def test_filled_project_table_yields_every_field(tmp_path):
    filled = {
        "Title": "Briefedition",
        "Editor": "Editionsteam",
        "Institution": "Stadtarchiv",
        "Edition type": "Normalisierte Transkription",
        "Language": "de",
        "License": "CC BY 4.0",
    }
    text = PROJECT_TEMPLATE.read_text(encoding="utf-8")
    for label, value in filled.items():
        row = f"| {label} | [TODO] |"
        assert row in text
        text = text.replace(row, f"| {label} | {value} |")
    path = tmp_path / "01_PROJECT.md"
    path.write_text(text, encoding="utf-8")

    assert config.project_info(path) == {
        "title": "Briefedition",
        "editor": "Editionsteam",
        "publisher": "Stadtarchiv",
        "edition_type": "Normalisierte Transkription",
        "language": "de",
        "license": "CC BY 4.0",
    }


def test_project_labels_match_exactly_not_by_substring(tmp_path):
    path = tmp_path / "01_PROJECT.md"
    path.write_text(
        "# Title from a heading\n\n"
        "| Feld | Wert |\n|---|---|\n"
        "| Untertitel | Nebentitel |\n"
        "| Langzeitarchivierung | GAMS |\n"
        "| Sprachen des Korpus | Latein |\n"
        "| Lizenzhinweis | Bildrechte |\n"
        "| TITLE | [TODO: Titel eintragen] |\n"
        "| Editor |  |\n",
        encoding="utf-8",
    )
    assert config.project_info(path) == {}

    path.write_text("| Titel | Erster |\n| title | Zweiter |\n", encoding="utf-8")
    assert config.project_info(path) == {"title": "Erster"}
    assert config.project_info(tmp_path / "absent.md") == {}


# Repository-bound paths


def test_safe_path_stays_inside_root_and_refuses_links(tmp_path, directory_link):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)

    assert config.safe_path(root, Path("docs/a.json")) == root / "docs" / "a.json"
    for relative in (Path("../outside.json"), (tmp_path / "abs.json").resolve()):
        with pytest.raises(ValueError):
            config.safe_path(root, relative)

    directory_link(root / "alias", root / "docs")
    assert config.is_link_or_reparse_point(root / "alias")
    assert not config.is_link_or_reparse_point(root / "docs")
    assert not config.is_link_or_reparse_point(root / "missing")
    with pytest.raises(ValueError, match="Linked"):
        config.safe_path(root, Path("alias/a.json"))


# Run scaffolding


def _load_failure(directory, object_id, violations=lambda _data: []):
    with pytest.raises(config.ItemFailure) as failure:
        config.load_checked_json(directory, object_id, violations)
    return failure.value


def test_load_checked_json_returns_a_conforming_input(tmp_path):
    (tmp_path / "doc1.json").write_text('{"object_id": "doc1"}', encoding="utf-8")
    seen = []

    data = config.load_checked_json(tmp_path, "doc1", lambda d: seen.append(d) or [])

    assert data == {"object_id": "doc1"} == seen[0]


def test_load_checked_json_names_the_failing_stage(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "other.json").write_text('{"object_id": "doc9"}', encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"object_id": "bad"}', encoding="utf-8")

    unsafe = _load_failure(tmp_path, "../doc1")
    assert (unsafe.stage, unsafe.message) == (
        "contract",
        "object_id is not a path-safe identifier",
    )
    assert _load_failure(tmp_path, "absent").stage == "read"
    broken = _load_failure(tmp_path, "broken")
    assert broken.stage == "read" and "broken.json" in broken.message
    mismatch = _load_failure(tmp_path, "other")
    assert mismatch.stage == "contract"
    assert "'doc9' does not match filename 'other'" in mismatch.message
    violation = _load_failure(tmp_path, "bad", lambda _data: ["pages is empty"])
    assert violation.message == "Input violates the data contract: pages is empty"


def test_provenance_meta_does_not_invent_a_prompt_hash():
    meta = config.provenance_meta("s.py", prompt_template="transcription.md", step=3)
    assert "prompt_hash" not in meta


def test_selection_arguments_require_one_mode_and_a_positive_sample():
    parser = argparse.ArgumentParser()
    config.add_selection_args(parser)

    args = parser.parse_args(["--all", "--sample", "2"])
    assert (args.object, args.all, args.sample) == (None, True, 2)
    for argv in ([], ["--object", "a", "--all"], ["--all", "--sample", "0"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)


@pytest.mark.parametrize(
    ("candidates", "object_id", "all_flag", "sample", "expected"),
    [
        (["a", "b", "c"], None, True, None, ["a", "b", "c"]),
        (["a", "b", "c"], None, True, 2, ["a", "b"]),
        (["a", "b", "c"], "b", False, None, ["b"]),
    ],
)
def test_select_ids_returns_the_selection(
    candidates, object_id, all_flag, sample, expected
):
    assert config.select_ids(candidates, object_id, all_flag, sample) == expected


@pytest.mark.parametrize(
    ("candidates", "object_id", "all_flag", "sample", "message"),
    [
        (["a", "errors"], None, True, None, "invalid object identifier"),
        (["Doc", "doc"], None, True, None, "case-insensitively unique"),
        (["a"], "b", False, None, "not found"),
        (["a"], "a", False, 1, "--sample requires --all"),
        ([], None, True, None, "no objects available"),
    ],
)
def test_select_ids_exits_on_problems(
    capsys, candidates, object_id, all_flag, sample, message
):
    with pytest.raises(SystemExit) as exc:
        config.select_ids(candidates, object_id, all_flag, sample)

    assert exc.value.code == 1
    assert message in capsys.readouterr().err


def test_finish_run_records_errors_and_fails_the_run(capsys, tmp_path):
    errors = [{"object_id": "a", "error": "boom", "stage": "read"}]

    with pytest.raises(SystemExit) as exc:
        config.finish_run(errors, tmp_path, 3, "04_validate.py", "Done.")

    assert exc.value.code == 1
    state = read_json(tmp_path / "errors.json")
    assert state["errors"] == errors
    assert state["_meta"]["script"] == "04_validate.py"
    err = capsys.readouterr().err
    assert "FAIL a: boom" in err
    assert "Done." in err
    assert "1 of 3" in err


def test_finish_run_clears_the_error_state_on_success(capsys, tmp_path):
    config.finish_run([], tmp_path, 2, "04_validate.py", "Done.")

    assert read_json(tmp_path / "errors.json")["errors"] == []
    assert capsys.readouterr().out.strip() == "Done."


def test_require_provider_stops_before_a_call(capsys):
    with pytest.raises(SystemExit):
        config.require_provider("mistral", "m")
    assert "unknown provider" in capsys.readouterr().err

    # The offline guard in conftest leaves every provider key empty.
    with pytest.raises(SystemExit):
        config.require_provider("openai", "m", hint=", or run with --no-llm")
    assert "OPENAI_API_KEY in .env for provider 'openai', or run with --no-llm." in (
        capsys.readouterr().err
    )

    assert config.require_provider("ollama", "local-model") is None
