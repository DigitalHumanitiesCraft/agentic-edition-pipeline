"""Runnable checks for step 3: chunk merge, contract gate, error reporting.

Covers the ways a transcription run can lose or invent information silently:
a chunk merge that drops or guesses object-level fields, model-proposed
metadata reaching the output, a model answer written to disk although it
carries no usable pages, an error mislabelled by stage, and an API failure
whose message would otherwise carry the key into errors.json.
"""

import json
import re
import sys

import pytest

from conftest import load_step

step3 = load_step("03_transcribe")
config = load_step("config")
llm = load_step("llm")

SECRET = "AIzaTESTKEY0123456789"


def _image_paths(tmp_path, count=1):
    paths = []
    for number in range(1, count + 1):
        path = tmp_path / f"p{number}.png"
        path.write_bytes(f"image-{number}".encode())
        paths.append(path)
    return paths


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


def test_merge_confidence_stays_the_contract_vocabulary():
    merged = step3.merge_chunks(
        [
            {"pages": [], "confidence": "medium"},
            {"pages": [], "confidence": "high"},
        ]
    )
    assert merged["confidence"] == "medium"

    undeclared = step3.merge_chunks([{"pages": []}, {"pages": []}])
    assert undeclared["confidence"] == ""

    assert step3.merge_chunks([{"pages": [], "confidence": " High"}])["confidence"] == (
        "high"
    )


def test_unusable_model_response_becomes_an_error_not_an_empty_file(
    monkeypatch, tmp_path
):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: ({"summary": "kein Text"}, []),
    )

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err is not None
    assert err["stage"] == "contract"
    assert not (out_dir / "doc1.json").exists()


def test_usable_model_response_is_written(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Text"}], "confidence": "high"},
            [{"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}],
        ),
    )

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err is None
    written = json.loads((out_dir / "doc1.json").read_text(encoding="utf-8"))
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
    without_public_names = json.loads(json.dumps(written))
    del without_public_names["source_images"]
    assert any(
        "no top-level source_images" in problem
        for problem in step3.contract.file_violations(without_public_names)
    )


def test_invalid_inventory_metadata_blocks_model_call(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("model call reached")

    monkeypatch.setattr(step3, "transcribe_chunk", should_not_run)

    error = step3.transcribe_document(
        {"id": "doc1", "metadata": {"title": 42}},
        "prompt",
        "gemini",
        "m",
        20,
        False,
    )

    assert error is not None and error["stage"] == "contract"
    assert "inventory metadata.title" in error["error"]


def test_unsafe_inventory_id_is_rejected_before_path_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")

    def should_not_run(_doc):
        raise AssertionError("image discovery reached")

    monkeypatch.setattr(step3, "find_images_for_document", should_not_run)

    error = step3.transcribe_document(
        {"id": "../outside"}, "prompt", "gemini", "m", 20, False
    )

    assert error is not None and error["stage"] == "contract"
    assert not (tmp_path / "outside.json").exists()


@pytest.mark.parametrize(
    "documents",
    [[{"id": "../outside"}], [{"id": "Doc"}, {"id": "doc"}], ["doc1"]],
    ids=["unsafe", "casefold-collision", "not-an-object"],
)
def test_inventory_selection_rejects_invalid_records(monkeypatch, tmp_path, documents):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"documents": documents}), encoding="utf-8")
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


@pytest.mark.parametrize(
    "model_result",
    [
        {
            "pages": [{"page": 1, "transcription": "Text"}],
            "confidence": "certain",
        },
        {
            "pages": [{"page": 1, "transcription": "Text"}],
            "confidence": 3,
        },
        {
            "pages": [{"page": 1, "transcription": "Text"}],
            "confidence_notes": ["not", "text"],
        },
    ],
)
def test_invalid_model_fields_are_rejected(monkeypatch, tmp_path, model_result):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (model_result, []),
    )

    error = step3.transcribe_document(
        {"id": "doc1"}, "prompt", "gemini", "m", 20, False
    )

    assert error is not None and error["stage"] == "contract"
    assert not (out_dir / "doc1.json").exists()


@pytest.mark.parametrize("page_count, chunk_size", [(1, 20), (2, 1)])
def test_confidence_case_and_metadata_follow_one_rule_for_any_chunk_count(
    monkeypatch, tmp_path, page_count, chunk_size
):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path, page_count)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def answer(_provider, _model, prompt, _images):
        start, end = map(int, re.search(r"source pages (\d+)-(\d+)", prompt).groups())
        pages = [
            {"page": number, "transcription": "Text"}
            for number in range(start, end + 1)
        ]
        return json.dumps(
            {"pages": pages, "confidence": "High", "metadata": {"title": "Invented"}}
        )

    monkeypatch.setattr(step3, "call_llm", answer)
    doc = {"id": "doc1", "metadata": {"title": "Catalogue title"}}

    error = step3.transcribe_document(doc, "prompt", "gemini", "m", chunk_size, True)

    assert error is None
    written = json.loads((out_dir / "doc1.json").read_text(encoding="utf-8"))
    assert written["confidence"] == "high"
    assert written["metadata"] == {"title": "Catalogue title"}


def test_source_image_change_during_call_blocks_the_output(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def mutate_source(*_args, **_kwargs):
        images[0].write_bytes(b"changed")
        return ({"pages": [{"page": 1, "transcription": "Text"}]}, [])

    monkeypatch.setattr(step3, "transcribe_chunk", mutate_source)

    error = step3.transcribe_document(
        {"id": "doc1"}, "prompt", "gemini", "m", 20, False
    )

    assert error is not None and error["stage"] == "source_state"
    assert not (out_dir / "doc1.json").exists()


def test_nonforced_transcription_rejects_changed_source_state(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Text"}]},
            [{"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}],
        ),
    )
    assert (
        step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, True)
        is None
    )
    images[0].write_bytes(b"changed source")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("stale output must block before the model call")

    monkeypatch.setattr(step3, "transcribe_chunk", should_not_run)
    error = step3.transcribe_document(
        {"id": "doc1"}, "prompt", "gemini", "m", 20, False
    )

    assert error is not None and error["stage"] == "stale"


def test_nonforced_transcription_rejects_changed_authoritative_metadata(
    monkeypatch, tmp_path
):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Text"}]},
            [{"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}],
        ),
    )
    first = {"id": "doc1", "metadata": {"repository": "Archive A"}}
    assert step3.transcribe_document(first, "prompt", "gemini", "m", 20, True) is None

    error = step3.transcribe_document(
        {"id": "doc1", "metadata": {"repository": "Archive B"}},
        "prompt",
        "gemini",
        "m",
        20,
        False,
    )

    assert error is not None and error["stage"] == "stale"


def test_nonforced_transcription_rejects_changed_prompt_profile_identity(
    monkeypatch, tmp_path
):
    out_dir = tmp_path / "transcriptions"
    prompts = tmp_path / "prompts"
    (prompts / "profiles").mkdir(parents=True)
    (prompts / "objects").mkdir()
    for name in ("letters-a", "letters-b"):
        (prompts / "profiles" / f"{name}.md").write_text(
            "Same instructions.", encoding="utf-8"
        )
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "PROMPTS_DIR", prompts)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Text"}]},
            [{"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}],
        ),
    )
    first = {"id": "doc1", "prompt_profile": "letters-a"}
    assert step3.transcribe_document(first, "prompt", "gemini", "m", 20, True) is None

    error = step3.transcribe_document(
        {"id": "doc1", "prompt_profile": "letters-b"},
        "prompt",
        "gemini",
        "m",
        20,
        False,
    )

    assert error is not None and error["stage"] == "stale"


def test_nonforced_transcription_rejects_changed_model_raw_text(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Original"}]},
            [{"chunk": 1, "pages": [1], "attempt": 1, "prompt_hash": "a" * 12}],
        ),
    )
    doc = {"id": "doc1"}
    assert step3.transcribe_document(doc, "prompt", "gemini", "m", 20, True) is None
    path = out_dir / "doc1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pages"][0]["transcription_raw"] = "Manipulated"
    data["pages"][0]["transcription"] = "Manipulated"
    path.write_text(json.dumps(data), encoding="utf-8")

    error = step3.transcribe_document(doc, "prompt", "gemini", "m", 20, False)

    assert error is not None and error["stage"] == "stale"


def test_force_refuses_to_destroy_existing_review_history(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    out_dir.mkdir()
    images = _image_paths(tmp_path)
    existing = {
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
                    "history": [
                        {
                            "from_status": "machine_unreviewed",
                            "status": "in_review",
                            "actor": "editor@example.org",
                            "timestamp": "2026-08-27T10:00:00+02:00",
                        }
                    ],
                },
            }
        ],
    }
    path = out_dir / "doc1.json"
    original = json.dumps(existing)
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("reviewed output must block before the model call")

    monkeypatch.setattr(step3, "transcribe_chunk", should_not_run)

    error = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, True)

    assert error is not None and error["stage"] == "review_history"
    assert path.read_text(encoding="utf-8") == original


def test_force_refuses_to_replace_an_unreadable_existing_output(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    out_dir.mkdir()
    path = out_dir / "doc1.json"
    original = "{ damaged review state"
    path.write_text(original, encoding="utf-8")
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("unreadable output must block before the model call")

    monkeypatch.setattr(step3, "transcribe_chunk", should_not_run)

    error = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, True)

    assert error is not None and error["stage"] == "stale"
    assert path.read_text(encoding="utf-8") == original


def test_force_refuses_json_valid_but_malformed_review_state(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    out_dir.mkdir()
    path = out_dir / "doc1.json"
    existing = {
        "object_id": "doc1",
        "pages": {
            "1": {
                "review": {
                    "history": [
                        {
                            "actor": "editor@example.org",
                            "status": "in_review",
                        }
                    ]
                }
            }
        },
    }
    original = json.dumps(existing)
    path.write_text(original, encoding="utf-8")
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("malformed existing output must block the model call")

    monkeypatch.setattr(step3, "transcribe_chunk", should_not_run)

    error = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, True)

    assert error is not None and error["stage"] == "stale"
    assert path.read_text(encoding="utf-8") == original


def test_page_count_mismatch_fails_the_contract_gate(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(
        step3,
        "find_images_for_document",
        lambda _doc: _image_paths(tmp_path, 2),
    )
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: (
            {"pages": [{"page": 1, "transcription": "Text"}]},
            [],
        ),
    )

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err is not None and err["stage"] == "contract"
    assert "1 pages for 2 source images" in err["error"]
    assert not (out_dir / "doc1.json").exists()


def test_each_chunk_must_return_its_declared_page_number(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(
        step3,
        "find_images_for_document",
        lambda _doc: _image_paths(tmp_path, 2),
    )

    def duplicate_page(*args, **_kwargs):
        start_page = args[-1]
        page = 1 if start_page == 2 else start_page
        return ({"pages": [{"page": page, "transcription": "Text"}]}, [])

    monkeypatch.setattr(step3, "transcribe_chunk", duplicate_page)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 1, False)

    assert err is not None and err["stage"] == "contract"
    assert "expected [2]" in err["error"]


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

    assert "Base rules." in prompt
    assert "Keep columns." in prompt
    assert "Title: Account book" in prompt
    assert "Extent: 4 page(s)" in prompt
    assert "Read the marginal hand." in prompt
    assert info["prompt_profile"] == "ledger"
    assert info["prompt_layers"] == [
        "transcription.md",
        "profiles/ledger.md",
        "inventory:metadata",
        "objects/doc1.md",
    ]
    assert len(info["prompt_hash"]) == 12


@pytest.mark.parametrize("profile", ["README", "readme", "missing"])
def test_profile_without_its_own_file_is_refused(monkeypatch, tmp_path, profile):
    prompts = tmp_path / "prompts"
    (prompts / "profiles").mkdir(parents=True)
    (prompts / "profiles" / "README.md").write_text("Folder notes.", encoding="utf-8")
    monkeypatch.setattr(step3, "PROMPTS_DIR", prompts)

    with pytest.raises((ValueError, FileNotFoundError)):
        step3.assemble_prompt({"id": "doc1", "prompt_profile": profile}, "Base.")


def test_api_failure_never_writes_the_key_into_the_error_record(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(config, "GEMINI_API_KEY", SECRET)
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def boom(*a, **k):
        raise RuntimeError(f"call failed: https://host/m:generateContent?key={SECRET}")

    monkeypatch.setattr(step3, "call_llm", boom)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err["stage"] == "api_call"
    assert SECRET not in err["error"]

    config.write_errors([err], out_dir, "03_transcribe.py")
    assert SECRET not in (out_dir / "errors.json").read_text(encoding="utf-8")
    for record in (tmp_path / "llm-calls" / "doc1").glob("*.json"):
        assert SECRET not in record.read_text(encoding="utf-8")


def test_truncated_answer_fails_the_chunk_without_json_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    calls = []

    def truncated(*_args, **_kwargs):
        calls.append(1)
        raise llm.TruncatedResponseError("stopped at the output token limit")

    monkeypatch.setattr(step3, "call_llm", truncated)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err["stage"] == "truncated"
    assert calls == [1]


def test_programming_error_is_not_labelled_as_a_provider_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "transcribe_chunk",
        lambda *a, **k: ({"pages": [{"page": 1, "transcription": "Text"}]}, []),
    )

    def broken(_chunks):
        raise KeyError("pages")

    monkeypatch.setattr(step3, "merge_chunks", broken)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err["stage"] == "internal"
    assert err["error"].startswith("KeyError")


def test_unreadable_chunk_cache_is_a_cache_error(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)
    monkeypatch.setattr(
        step3,
        "call_llm",
        lambda *a, **k: json.dumps({"pages": [{"page": 1, "transcription": "Text"}]}),
    )
    assert (
        step3.transcribe_document({"id": "doc1"}, "p", "gemini", "m", 20, False) is None
    )
    (out_dir / "doc1.json").unlink()
    for cached in (tmp_path / "chunk-cache" / "doc1").glob("*.json"):
        cached.write_text("{ damaged", encoding="utf-8")

    err = step3.transcribe_document({"id": "doc1"}, "p", "gemini", "m", 20, False)

    assert err["stage"] == "cache"


def _prepare_main(monkeypatch, tmp_path, *arguments, ids=("doc1",)):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"documents": [{"id": doc_id} for doc_id in ids]}),
        encoding="utf-8",
    )
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


def test_sample_zero_is_refused_before_any_provider_call(monkeypatch, tmp_path):
    _prepare_main(monkeypatch, tmp_path, "--all", "--sample", "0")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("no document may be processed")

    monkeypatch.setattr(step3, "transcribe_document", should_not_run)

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
        ids=("skipped", "called", "failed", "last"),
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


def test_dry_run_reports_discovery_errors_and_stale_outputs(
    monkeypatch, tmp_path, capsys
):
    _prepare_main(monkeypatch, tmp_path, "--all", "--dry-run", ids=("broken", "old"))
    images = _image_paths(tmp_path)

    def find(doc):
        if doc["id"] == "broken":
            raise ValueError("broken has 2 page images; inventory declares 3")
        return images

    monkeypatch.setattr(step3, "find_images_for_document", find)
    out_dir = tmp_path / "transcriptions"
    out_dir.mkdir()
    (out_dir / "old.json").write_text("{}", encoding="utf-8")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("dry run must not call the provider")

    monkeypatch.setattr(step3, "call_llm", should_not_run)

    with pytest.raises(SystemExit) as exc:
        step3.main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "[DISCOVERY] broken" in output
    assert "[STALE] old" in output
