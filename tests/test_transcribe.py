"""Runnable checks for step 3: chunk merge, contract gate, error reporting.

Covers the ways a transcription run can lose or invent information silently:
a chunk merge that drops or guesses object-level fields, model-proposed
metadata reaching the output, a model answer written to disk although it
carries no usable pages, an error mislabelled by stage, and an API failure
whose message would otherwise carry the key into errors.json.
"""

import importlib
import json
import re
import sys

import pytest

import config
import llm
from conftest import (
    forbid,
    page_images,
    read_json,
    review_event,
    write_image_manifest,
    write_json,
)

step3 = importlib.import_module("03_transcribe")

SECRET = "AIzaTESTKEY0123456789"
CALL_RECORD = {"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}


def _use_images(monkeypatch, tmp_path, count):
    images = page_images(tmp_path / "sources", count)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    return images


@pytest.fixture
def out_dir(monkeypatch, tmp_path):
    directory = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", directory)
    return directory


@pytest.fixture
def images(monkeypatch, tmp_path):
    return _use_images(monkeypatch, tmp_path, 1)


def _chunk_answer(monkeypatch, result, calls=(CALL_RECORD,)):
    monkeypatch.setattr(
        step3, "transcribe_chunk", lambda *a, **k: (result, list(calls))
    )


def _text_answer(text="Text"):
    return {"pages": [{"page": 1, "transcription": text}]}


def _obedient_model(extra=None):
    """A fake provider that numbers its pages as the chunk prompt asks."""

    def answer(_provider, _model, prompt, _images):
        start, end = map(int, re.search(r"source pages (\d+)-(\d+)", prompt).groups())
        pages = [
            {"page": number, "transcription": "Text"}
            for number in range(start, end + 1)
        ]
        return json.dumps({"pages": pages, **(extra or {})})

    return answer


def _transcribe(doc=None, force=False, chunk_size=20, prompt="prompt"):
    return step3.transcribe_document(
        doc or {"id": "doc1"}, prompt, "gemini", "m", chunk_size, force
    )


# Chunk merge


def test_merge_drops_model_metadata_and_concatenates_notes():
    chunks = [
        {
            "metadata": {"title": "Brief", "language": "de"},
            "pages": [{"page": 1, "transcription": "a"}],
            "confidence": "high",
            "confidence_notes": "Erste Haelfte klar.",
        },
        {
            "pages": [{"page": 2, "transcription": "b"}],
            "confidence": "low",
            "confidence_notes": "Zweite Haelfte blass.",
        },
    ]

    merged = step3.merge_chunks(chunks)

    assert "metadata" not in merged
    assert [p["page"] for p in merged["pages"]] == [1, 2]
    assert merged["confidence"] == "low"
    assert "Erste Haelfte klar." in merged["confidence_notes"]
    assert "Zweite Haelfte blass." in merged["confidence_notes"]


@pytest.mark.parametrize(
    ("confidences", "expected"),
    [(["medium", "high"], "medium"), ([None, None], ""), ([" High"], "high")],
)
def test_merge_confidence_stays_the_contract_vocabulary(confidences, expected):
    chunks = [
        {"pages": []} if value is None else {"pages": [], "confidence": value}
        for value in confidences
    ]

    assert step3.merge_chunks(chunks)["confidence"] == expected


# Contract gate on model answers


@pytest.mark.parametrize(
    "model_result",
    [
        {"summary": "kein Text"},
        {"pages": [{"page": 1, "transcription": "Text"}], "confidence": "certain"},
        {"pages": [{"page": 1, "transcription": "Text"}], "confidence": 3},
        {
            "pages": [{"page": 1, "transcription": "Text"}],
            "confidence_notes": ["not", "text"],
        },
    ],
    ids=["no-pages", "unknown-confidence", "numeric-confidence", "list-notes"],
)
def test_unusable_model_answer_becomes_an_error_not_a_file(
    monkeypatch, out_dir, images, model_result
):
    _chunk_answer(monkeypatch, model_result, calls=())

    error = _transcribe()

    assert error is not None and error["stage"] == "contract"
    assert not (out_dir / "doc1.json").exists()


def test_usable_model_response_is_written(monkeypatch, out_dir, images):
    _chunk_answer(monkeypatch, _text_answer())

    assert _transcribe() is None

    written = read_json(out_dir / "doc1.json")
    assert written["pages"][0]["transcription"] == "Text"
    assert written["pages"][0]["transcription_raw"] == "Text"
    assert written["pages"][0]["review"] == {
        "status": "machine_unreviewed",
        "history": [],
    }
    assert written["_meta"]["executed_prompts"][0]["pages"] == [1]
    assert written["_meta"]["source_images"][0]["filename"] == "p1.png"
    assert written["_meta"]["source_images_hash"]
    assert written["_meta"]["raw_transcription_hash"]
    del written["source_images"]
    assert any(
        "no top-level source_images" in problem
        for problem in step3.contract.file_violations(written)
    )


def test_invalid_inventory_metadata_blocks_model_call(monkeypatch, out_dir, images):
    monkeypatch.setattr(step3, "transcribe_chunk", forbid("model call reached"))

    error = _transcribe({"id": "doc1", "metadata": {"title": 42}})

    assert error is not None and error["stage"] == "contract"
    assert "inventory metadata.title" in error["error"]


def test_unsafe_inventory_id_is_rejected_before_path_discovery(
    monkeypatch, tmp_path, out_dir
):
    monkeypatch.setattr(
        step3, "find_images_for_document", forbid("image discovery reached")
    )

    error = _transcribe({"id": "../outside"})

    assert error is not None and error["stage"] == "contract"
    assert not (tmp_path / "outside.json").exists()


@pytest.mark.parametrize(
    "documents",
    [[{"id": "../outside"}], [{"id": "Doc"}, {"id": "doc"}], ["doc1"]],
    ids=["unsafe", "casefold-collision", "not-an-object"],
)
def test_inventory_selection_rejects_invalid_records(monkeypatch, tmp_path, documents):
    inventory = write_json(tmp_path / "inventory.json", {"documents": documents})
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)

    with pytest.raises(SystemExit) as exc:
        step3.select_documents(step3.load_inventory(), None, True, None)

    assert exc.value.code == 1


def test_selection_leaves_out_documents_without_page_images(capsys):
    documents = [
        {"id": "notes", "source_type": "text", "transcribable": False},
        {"id": "scan", "source_type": "image", "transcribable": True},
        {"id": "legacy", "source_type": "pdf"},
    ]

    selected = step3.select_documents(documents, None, True, 1)

    assert [doc["id"] for doc in selected] == ["scan"]
    assert "SKIP notes" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        step3.select_documents(documents, "notes", False, None)


@pytest.mark.parametrize(("page_count", "chunk_size"), [(1, 20), (2, 1)])
def test_confidence_case_and_metadata_follow_one_rule_for_any_chunk_count(
    monkeypatch, tmp_path, out_dir, page_count, chunk_size
):
    _use_images(monkeypatch, tmp_path, page_count)
    monkeypatch.setattr(
        step3,
        "call_llm",
        _obedient_model({"confidence": "High", "metadata": {"title": "Invented"}}),
    )
    doc = {"id": "doc1", "metadata": {"title": "Catalogue title"}}

    assert _transcribe(doc, force=True, chunk_size=chunk_size) is None

    written = read_json(out_dir / "doc1.json")
    assert written["confidence"] == "high"
    assert written["metadata"] == {"title": "Catalogue title"}


def test_source_image_change_during_call_blocks_the_output(
    monkeypatch, out_dir, images
):
    def mutate_source(*_args, **_kwargs):
        images[0].write_bytes(b"changed")
        return _text_answer(), []

    monkeypatch.setattr(step3, "transcribe_chunk", mutate_source)

    error = _transcribe()

    assert error is not None and error["stage"] == "source_state"
    assert not (out_dir / "doc1.json").exists()


def test_page_count_mismatch_fails_the_contract_gate(monkeypatch, tmp_path, out_dir):
    _use_images(monkeypatch, tmp_path, 2)
    _chunk_answer(monkeypatch, _text_answer(), calls=())

    error = _transcribe()

    assert error is not None and error["stage"] == "contract"
    assert "1 pages for 2 source images" in error["error"]
    assert not (out_dir / "doc1.json").exists()


def test_each_chunk_must_return_its_declared_page_number(
    monkeypatch, tmp_path, out_dir
):
    _use_images(monkeypatch, tmp_path, 2)

    # Every chunk answers with page 1, so the second chunk repeats a page.
    _chunk_answer(monkeypatch, _text_answer(), calls=())

    error = _transcribe(chunk_size=1)

    assert error is not None and error["stage"] == "contract"
    assert "expected [2]" in error["error"]


def test_undeclared_empty_page_sets_review_signal():
    quality = step3.compute_quality_signals(
        {
            "pages": [
                {"page": 1, "transcription": "Short"},
                {"page": 2, "transcription": ""},
            ]
        },
        image_count=2,
    )

    assert quality["page_types"] == ["content", "undeclared_empty"]
    assert quality["undeclared_empty_pages"] == 1
    assert quality["needs_review"] is True


# Existing outputs: staleness and --force


def _change_source_bytes(images, _out_dir, doc):
    images[0].write_bytes(b"changed source")
    return doc


def _change_repository(_images, _out_dir, doc):
    return {**doc, "metadata": {"repository": "Archive B"}}


def _change_profile(_images, _out_dir, doc):
    return {**doc, "prompt_profile": "letters-b"}


def _change_raw_text(_images, out_dir, doc):
    path = out_dir / "doc1.json"
    data = read_json(path)
    data["pages"][0]["transcription_raw"] = "Manipulated"
    data["pages"][0]["transcription"] = "Manipulated"
    write_json(path, data)
    return doc


@pytest.mark.parametrize(
    ("first_doc", "change"),
    [
        ({"id": "doc1"}, _change_source_bytes),
        ({"id": "doc1", "metadata": {"repository": "Archive A"}}, _change_repository),
        ({"id": "doc1", "prompt_profile": "letters-a"}, _change_profile),
        ({"id": "doc1"}, _change_raw_text),
    ],
    ids=["source-bytes", "authoritative-metadata", "profile-identity", "raw-text"],
)
def test_nonforced_run_rejects_a_stale_output_before_the_model_call(
    monkeypatch, tmp_path, out_dir, images, first_doc, change
):
    prompts = tmp_path / "prompts"
    (prompts / "profiles").mkdir(parents=True)
    # Identical profile texts: only the declared profile identity differs.
    for name in ("letters-a", "letters-b"):
        (prompts / "profiles" / f"{name}.md").write_text(
            "Same instructions.", encoding="utf-8"
        )
    monkeypatch.setattr(step3, "PROMPTS_DIR", prompts)
    _chunk_answer(monkeypatch, _text_answer())
    assert _transcribe(first_doc, force=True) is None
    second_doc = change(images, out_dir, first_doc)
    monkeypatch.setattr(
        step3, "transcribe_chunk", forbid("stale output must block the model call")
    )

    error = _transcribe(second_doc)

    assert error is not None and error["stage"] == "stale"


REVIEWED_OUTPUT = {
    "_meta": {
        "script": "manual-review",
        "timestamp": "2026-08-27T10:00:00+02:00",
        "pipeline_step": 0,
    },
    "object_id": "doc1",
    "pages": [
        {
            "page": 1,
            "transcription": "Reviewed text",
            "review": {
                "status": "in_review",
                "history": [review_event("machine_unreviewed", "in_review")],
            },
        }
    ],
}
MALFORMED_REVIEW_STATE = {
    "object_id": "doc1",
    "pages": {
        "1": {
            "review": {
                "history": [{"actor": "editor@example.org", "status": "in_review"}]
            }
        }
    },
}


@pytest.mark.parametrize(
    ("existing", "stage"),
    [
        (json.dumps(REVIEWED_OUTPUT), "review_history"),
        ("{ damaged review state", "stale"),
        (json.dumps(MALFORMED_REVIEW_STATE), "stale"),
    ],
    ids=["review-history", "unreadable", "malformed-review-state"],
)
def test_force_refuses_to_replace_an_output_it_cannot_safely_discard(
    monkeypatch, out_dir, images, existing, stage
):
    out_dir.mkdir()
    path = out_dir / "doc1.json"
    path.write_text(existing, encoding="utf-8")
    monkeypatch.setattr(
        step3, "transcribe_chunk", forbid("existing output must block the model call")
    )

    error = _transcribe(force=True)

    assert error is not None and error["stage"] == stage
    assert path.read_text(encoding="utf-8") == existing


# Prompt assembly


def test_prompt_assembly_uses_profile_metadata_and_object_override(
    monkeypatch, tmp_path
):
    prompts = tmp_path / "prompts"
    (prompts / "profiles").mkdir(parents=True)
    (prompts / "objects").mkdir()
    (prompts / "profiles" / "ledger.md").write_text("Keep columns.", encoding="utf-8")
    (prompts / "objects" / "doc1.md").write_text(
        "Read the marginal hand.", encoding="utf-8"
    )
    monkeypatch.setattr(step3, "PROMPTS_DIR", prompts)

    prompt, info = step3.assemble_prompt(
        {
            "id": "doc1",
            "pages": 4,
            "prompt_profile": "ledger",
            "metadata": {"title": "Account book", "language": "de"},
        },
        "Base rules.",
    )

    for part in (
        "Base rules.",
        "Keep columns.",
        "Account book",
        "Read the marginal hand.",
    ):
        assert part in prompt
    assert "4 page" in prompt
    assert info["prompt_profile"] == "ledger"
    assert info["prompt_layers"] == [
        "transcription.md",
        "profiles/ledger.md",
        "inventory:metadata",
        "objects/doc1.md",
    ]
    assert info["prompt_hash"] == step3.contract.text_hash(prompt)


@pytest.mark.parametrize("profile", ["README", "readme", "missing"])
def test_profile_without_its_own_file_is_refused(monkeypatch, tmp_path, profile):
    prompts = tmp_path / "prompts"
    (prompts / "profiles").mkdir(parents=True)
    (prompts / "profiles" / "README.md").write_text("Folder notes.", encoding="utf-8")
    monkeypatch.setattr(step3, "PROMPTS_DIR", prompts)

    with pytest.raises((ValueError, FileNotFoundError)):
        step3.assemble_prompt({"id": "doc1", "prompt_profile": profile}, "Base.")


# Provider failures


def test_api_failure_never_writes_the_key_into_the_error_record(
    monkeypatch, tmp_path, out_dir, images
):
    monkeypatch.setattr(config, "GEMINI_API_KEY", SECRET)

    def boom(*a, **k):
        raise RuntimeError(f"call failed: https://host/m:generateContent?key={SECRET}")

    monkeypatch.setattr(step3, "call_llm", boom)

    error = _transcribe()

    assert error["stage"] == "api_call"
    assert SECRET not in error["error"]
    config.write_errors([error], out_dir, "03_transcribe.py")
    assert SECRET not in (out_dir / "errors.json").read_text(encoding="utf-8")
    records = list((tmp_path / "llm-calls" / "doc1").glob("*.json"))
    assert records
    for record in records:
        assert SECRET not in record.read_text(encoding="utf-8")


def test_truncated_answer_fails_the_chunk_without_json_retry(
    monkeypatch, out_dir, images
):
    calls = []

    def truncated(*_args, **_kwargs):
        calls.append(1)
        raise llm.TruncatedResponseError("stopped at the output token limit")

    monkeypatch.setattr(step3, "call_llm", truncated)

    assert _transcribe()["stage"] == "truncated"
    assert calls == [1]


def test_programming_error_is_not_labelled_as_a_provider_failure(
    monkeypatch, out_dir, images
):
    _chunk_answer(monkeypatch, _text_answer(), calls=())

    def broken(_chunks):
        raise KeyError("pages")

    monkeypatch.setattr(step3, "merge_chunks", broken)

    error = _transcribe()

    assert error["stage"] == "internal"
    assert error["error"].startswith("KeyError")


def test_unreadable_chunk_cache_is_a_cache_error(
    monkeypatch, tmp_path, out_dir, images
):
    monkeypatch.setattr(step3, "call_llm", _obedient_model())
    assert _transcribe(prompt="p") is None
    (out_dir / "doc1.json").unlink()
    for cached in (tmp_path / "chunk-cache" / "doc1").glob("*.json"):
        cached.write_text("{ damaged", encoding="utf-8")

    assert _transcribe(prompt="p")["stage"] == "cache"


# Command line


def _prepare_main(monkeypatch, tmp_path, *arguments, documents=({"id": "doc1"},)):
    inventory = write_json(tmp_path / "inventory.json", {"documents": list(documents)})
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(step3, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step3, "require_provider", lambda *_args: None)
    monkeypatch.setattr(step3, "load_prompt", lambda _name: "prompt")
    monkeypatch.setattr(sys, "argv", ["03_transcribe.py", *(arguments or ("--all",))])


def test_main_exits_nonzero_when_a_document_fails(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: [])

    with pytest.raises(SystemExit) as exc:
        step3.main()

    assert exc.value.code == 1


def test_main_returns_cleanly_when_every_document_succeeds(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path)
    monkeypatch.setattr(step3, "transcribe_document", lambda *a, **k: None)

    step3.main()


def test_main_transcribes_only_the_selected_object_from_its_manifest_images(
    monkeypatch, tmp_path
):
    images = tmp_path / "data/processed/images"
    scans = page_images(images / "scan", 2, "scan_p{page:03d}.png")
    write_image_manifest(images / "scan", [path.name for path in scans])
    page_images(images / "other", 1, "other_p{page:03d}.png")
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "data/sources/images")
    monkeypatch.setattr(config, "IMAGES_DIR", images)
    _prepare_main(
        monkeypatch,
        tmp_path,
        "--object",
        "scan",
        "--chunk-size",
        "1",
        "--delay",
        "0",
        documents=(
            {"id": "other", "pages": 1},
            {"id": "scan", "pages": 2},
            {"id": "notes", "transcribable": False},
        ),
    )
    monkeypatch.setattr(step3, "call_llm", _obedient_model())

    step3.main()

    written = sorted(path.name for path in (tmp_path / "transcriptions").glob("*"))
    assert written == ["errors.json", "scan.json"]
    data = read_json(tmp_path / "transcriptions" / "scan.json")
    assert [image["filename"] for image in data["_meta"]["source_images"]] == [
        "scan_p001.png",
        "scan_p002.png",
    ]
    assert [call["pages"] for call in data["_meta"]["executed_prompts"]] == [[1], [2]]


def test_sample_zero_is_refused_before_any_provider_call(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path, "--all", "--sample", "0")
    monkeypatch.setattr(
        step3, "transcribe_document", forbid("no document may be processed")
    )

    with pytest.raises(SystemExit) as exc:
        step3.main()

    assert exc.value.code == 2


def test_delay_follows_only_documents_that_called_the_provider(monkeypatch, tmp_path):
    _prepare_main(
        monkeypatch,
        tmp_path,
        "--all",
        "--delay",
        "0.5",
        documents=[{"id": name} for name in ("skipped", "called", "failed", "last")],
    )
    sleeps = []
    monkeypatch.setattr(step3.time, "sleep", sleeps.append)

    def process(doc, *_args, provider_calls=None, **_kwargs):
        if doc["id"] in ("called", "last"):
            provider_calls.append({"chunk": 1})
        if doc["id"] == "failed":
            return {
                "object_id": "failed",
                "error": "No images found",
                "stage": "discovery",
            }
        return None

    monkeypatch.setattr(step3, "transcribe_document", process)

    with pytest.raises(SystemExit):
        step3.main()

    assert sleeps == [0.5]


def test_dry_run_reports_discovery_errors_stale_and_pending_outputs(
    monkeypatch, tmp_path, capsys
):
    _prepare_main(
        monkeypatch,
        tmp_path,
        "--all",
        "--dry-run",
        documents=[{"id": name} for name in ("broken", "old", "fresh")],
    )
    images = page_images(tmp_path / "sources", 1)

    def find(doc):
        if doc["id"] == "broken":
            raise ValueError("broken has 2 page images; inventory declares 3")
        return images

    monkeypatch.setattr(step3, "find_images_for_document", find)
    write_json(tmp_path / "transcriptions" / "old.json", {})
    monkeypatch.setattr(step3, "call_llm", forbid("dry run must not call the provider"))

    with pytest.raises(SystemExit) as exc:
        step3.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "[DISCOVERY] broken" in output
    assert "[STALE] old" in output
    assert "[PENDING] fresh" in output
