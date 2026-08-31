"""Runnable checks for step 3: chunk merge, contract gate, error reporting.

Covers the three ways a transcription run can lose information silently: a
multi-chunk merge that drops object-level fields, a model answer written to
disk although it carries no usable pages, and an API failure whose message
would otherwise carry the key into errors.json.
"""

import json
import sys

import pytest

from conftest import load_step

step3 = load_step("03_transcribe")
llm = load_step("llm")

SECRET = "AIzaTESTKEY0123456789"


def _image_paths(tmp_path, count=1):
    paths = []
    for number in range(1, count + 1):
        path = tmp_path / f"p{number}.png"
        path.write_bytes(f"image-{number}".encode())
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# Chunk merge
# ---------------------------------------------------------------------------


def test_merge_keeps_metadata_and_concatenates_notes():
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

    assert merged["metadata"] == {"title": "Brief", "language": "de"}
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


# ---------------------------------------------------------------------------
# Contract gate before writing
# ---------------------------------------------------------------------------


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


def test_inventory_loader_rejects_unsafe_ids(monkeypatch, tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"documents": [{"id": "../outside"}]}), encoding="utf-8"
    )
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)

    with pytest.raises(SystemExit) as exc:
        step3.load_inventory()

    assert exc.value.code == 1


def test_inventory_loader_rejects_casefold_collisions(monkeypatch, tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"documents": [{"id": "Doc"}, {"id": "doc"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)

    with pytest.raises(SystemExit) as exc:
        step3.load_inventory()

    assert exc.value.code == 1


@pytest.mark.parametrize(
    "model_result",
    [
        {
            "metadata": {"title": 42},
            "pages": [{"page": 1, "transcription": "Text"}],
        },
        {
            "pages": [{"page": 1, "transcription": "Text"}],
            "confidence": "certain",
        },
    ],
)
def test_invalid_assembled_model_fields_are_rejected(
    monkeypatch, tmp_path, model_result
):
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


# ---------------------------------------------------------------------------
# Key redaction on the error path
# ---------------------------------------------------------------------------


def test_api_failure_never_writes_the_key_into_the_error_record(monkeypatch, tmp_path):
    out_dir = tmp_path / "transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", out_dir)
    monkeypatch.setattr(llm, "GEMINI_API_KEY", SECRET)
    images = _image_paths(tmp_path)
    monkeypatch.setattr(step3, "find_images_for_document", lambda _doc: images)

    def boom(*a, **k):
        raise RuntimeError(f"call failed: https://host/m:generateContent?key={SECRET}")

    monkeypatch.setattr(step3, "transcribe_chunk", boom)

    err = step3.transcribe_document({"id": "doc1"}, "prompt", "gemini", "m", 20, False)

    assert err["stage"] == "api_call"
    assert SECRET not in err["error"]

    step3.write_errors([err], out_dir)
    assert SECRET not in (out_dir / "errors.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------


def _prepare_main(monkeypatch, tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"documents": [{"id": "doc1"}]}), encoding="utf-8")
    monkeypatch.setattr(step3, "INVENTORY_PATH", inventory)
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", tmp_path / "transcriptions")
    monkeypatch.setattr(step3, "ensure_dirs", lambda: None)
    monkeypatch.setattr(step3, "missing_api_key", lambda _provider: None)
    monkeypatch.setattr(step3, "load_prompt", lambda _name: "prompt")
    monkeypatch.setattr(sys, "argv", ["03_transcribe.py", "--all"])


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
