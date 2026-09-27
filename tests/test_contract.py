"""Runnable checks for the runtime contract validator (pipeline/contract.py).

The validator is the single source for the field rules of
knowledge/08_DATA_CONTRACT.md; step 3 gates model answers with it and the
contract tests check finished files with the same functions.
"""

import copy
import hashlib

import pytest

from conftest import load_step

contract = load_step("contract")


def test_conformant_fixture_has_no_violations(fixture_transcription):
    assert contract.file_violations(fixture_transcription) == []


def test_missing_top_level_keys_are_named():
    problems = contract.file_violations({"pages": [{"page": 1, "transcription": "x"}]})
    assert any("object_id" in p for p in problems)


def test_object_ids_are_portable_across_filesystems():
    assert contract.valid_object_id("doc-1")
    assert not contract.valid_object_id("CON")
    assert not contract.valid_object_id("nul.txt")
    assert not contract.valid_object_id("name.")


def test_object_id_sets_are_case_insensitively_unique():
    problems = contract.unique_object_id_violations(["Doc", "doc"])

    assert any("not case-insensitively unique" in problem for problem in problems)


def test_missing_provenance_block_is_named():
    problems = contract.file_violations(
        {"object_id": "d", "pages": [{"page": 1, "transcription": "x"}]}
    )
    assert any("_meta" in p for p in problems)


def test_response_without_usable_pages_is_rejected():
    assert contract.response_violations({"summary": "nichts gefunden"})
    assert contract.response_violations({"pages": []})
    assert contract.response_violations({"pages": "kein Array"})
    assert contract.response_violations("not a dict")
    assert contract.response_violations(None)


def test_finished_file_cannot_claim_an_empty_document():
    problems = contract.file_violations(
        {
            "_meta": {
                "script": "manual",
                "timestamp": "2026-08-27T00:00:00+00:00",
            },
            "object_id": "empty",
            "pages": [],
        }
    )

    assert "pages is empty" in problems


def test_response_page_needs_number_and_transcription():
    assert contract.response_violations({"pages": [{"transcription": "x"}]})
    assert contract.response_violations({"pages": [{"page": 1}]})
    assert contract.response_violations({"pages": [{"page": 0, "transcription": "x"}]})
    assert contract.response_violations({"pages": [{"page": 1, "transcription": 42}]})


def test_declared_blank_page_stays_usable():
    assert (
        contract.response_violations({"pages": [{"page": 1, "transcription": ""}]})
        == []
    )


def test_finished_file_requires_auditable_review_state(fixture_transcription):
    del fixture_transcription["pages"][0]["review"]
    assert any(
        "human review state" in problem
        for problem in contract.file_violations(fixture_transcription)
    )


def test_contract_rejects_unsafe_optional_fields(fixture_transcription):
    broken = copy.deepcopy(fixture_transcription)
    broken["_meta"]["timestamp"] = "yesterday"
    broken["metadata"]["title"] = 42
    broken["metadata"]["image_urls"]["1"] = 42
    broken["pages"][0]["page_type"] = "alien"
    broken["pages"][0]["notes"] = 7
    broken["pages"][0]["foreign_paragraphs"] = "1"

    problems = contract.file_violations(broken)

    assert any("timestamp" in problem for problem in problems)
    assert any("metadata.title" in problem for problem in problems)
    assert any("invalid URL" in problem for problem in problems)
    assert any("page_type" in problem for problem in problems)
    assert any("notes" in problem for problem in problems)
    assert any("foreign_paragraphs" in problem for problem in problems)


def test_blank_page_cannot_carry_transcription_text():
    problems = contract.response_violations(
        {
            "pages": [{"page": 1, "transcription": "Text", "page_type": "blank"}],
        }
    )
    assert any("declares blank" in problem for problem in problems)


def test_cross_step_objects_are_typed_before_consumers_use_them(
    fixture_transcription,
):
    broken = copy.deepcopy(fixture_transcription)
    broken["quality_signals"] = "yes"
    broken["transcription_meta"] = "old provenance"

    problems = contract.file_violations(broken)

    assert "quality_signals is not an object" in problems
    assert "transcription_meta is not a provenance object" in problems


def test_validated_contract_rejects_stale_text_statistics(fixture_validated):
    fixture_validated["pages"][0]["transcription"] += " changed"

    problems = contract.validated_file_violations(fixture_validated)

    assert any("char_count is stale" in problem for problem in problems)
    assert any("total_characters is stale" in problem for problem in problems)


def test_validated_hash_rejects_equal_length_text_change(fixture_validated):
    original = fixture_validated["pages"][0]["transcription"]
    fixture_validated["pages"][0]["transcription"] = "X" + original[1:]

    problems = contract.validated_file_violations(fixture_validated)

    assert any("state hash does not match" in problem for problem in problems)


def test_validated_result_hash_rejects_changed_findings(fixture_validated):
    fixture_validated["overall_status"] = "confident"
    fixture_validated["validation"]["rules"] = [
        {"name": f"error-{index}", "count": 1, "severity": "error"}
        for index in range(3)
    ]

    problems = contract.validated_file_violations(fixture_validated)

    assert any("result hash does not match" in problem for problem in problems)


def test_validated_contract_checks_all_page_statistics(fixture_validated):
    fixture_validated["validation"]["per_page_stats"][0]["word_count"] = 999
    fixture_validated["validation"]["per_page_stats"][0]["line_count"] = 999

    problems = contract.validated_file_violations(fixture_validated)

    assert any("word_count is stale" in problem for problem in problems)
    assert any("line_count is stale" in problem for problem in problems)


def test_review_status_must_match_nonempty_history(fixture_transcription):
    fixture_transcription["pages"][0]["review"] = {
        "status": "machine_unreviewed",
        "history": [
            {
                "from_status": "machine_unreviewed",
                "status": "accepted",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:00:00+02:00",
            }
        ],
    }

    assert any(
        "latest history entry" in problem
        for problem in contract.file_violations(fixture_transcription)
    )


def test_foreign_paragraph_indices_must_exist():
    problems = contract.response_violations(
        {
            "pages": [
                {
                    "page": 1,
                    "transcription": "First\n\nSecond",
                    "foreign_paragraphs": [2],
                }
            ],
        }
    )

    assert any("out-of-range" in problem for problem in problems)


def test_machine_model_output_requires_unchanged_raw_text(fixture_transcription):
    fixture_transcription["_meta"].update(
        {
            "pipeline_step": 3,
            "provider": "gemini",
            "model": "m",
            "prompt_template": "transcription.md",
            "prompt_hash": "a" * 12,
            "source_metadata_hash": "c" * 12,
            "executed_prompts": [
                {
                    "chunk": 1,
                    "pages": [1, 2, 3, 4, 5],
                    "attempt": 1,
                    "prompt_hash": "b" * 12,
                }
            ],
            "source_images": [
                {
                    "page": page,
                    "filename": f"page{page}.png",
                    "sha256": f"{page:064x}",
                }
                for page in range(1, 6)
            ],
        }
    )
    serialized = __import__("json").dumps(
        fixture_transcription["_meta"]["source_images"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fixture_transcription["_meta"]["source_images_hash"] = (
        __import__("hashlib").sha256(serialized.encode()).hexdigest()[:12]
    )

    problems = contract.file_violations(fixture_transcription)

    assert sum("raw model transcription" in problem for problem in problems) == 5


def test_claimed_step_three_requires_complete_provenance(fixture_transcription):
    fixture_transcription["_meta"]["pipeline_step"] = 3

    problems = contract.file_violations(fixture_transcription)

    assert any("provider is missing" in problem for problem in problems)
    assert any("executed_prompts" in problem for problem in problems)
    assert any("source_images is missing" in problem for problem in problems)


def test_step_three_profile_must_match_its_prompt_layer(fixture_transcription):
    fixture_transcription["_meta"].update(
        {
            "pipeline_step": 3,
            "provider": "gemini",
            "model": "m",
            "prompt_template": "transcription.md",
            "prompt_hash": "a" * 12,
            "prompt_profile": "letters",
            "prompt_layers": ["transcription.md"],
        }
    )

    problems = contract.file_violations(fixture_transcription)

    assert any("does not match prompt_profile" in problem for problem in problems)


def test_step_three_prompt_log_must_cover_all_pages(fixture_transcription):
    meta = fixture_transcription["_meta"]
    meta.update(
        {
            "pipeline_step": 3,
            "provider": "gemini",
            "model": "m",
            "prompt_template": "transcription.md",
            "prompt_hash": "a" * 12,
            "source_metadata_hash": "c" * 12,
            "executed_prompts": [
                {
                    "chunk": 1,
                    "pages": [999],
                    "attempt": 1,
                    "prompt_hash": "b" * 12,
                }
            ],
            "source_images": [
                {
                    "page": page,
                    "filename": f"page{page}.png",
                    "sha256": f"{page:064x}",
                }
                for page in range(1, 6)
            ],
        }
    )
    serialized = __import__("json").dumps(
        meta["source_images"], sort_keys=True, separators=(",", ":")
    )
    meta["source_images_hash"] = (
        __import__("hashlib").sha256(serialized.encode()).hexdigest()[:12]
    )

    problems = contract.file_violations(fixture_transcription)

    assert any("do not cover every page" in problem for problem in problems)


def test_source_image_names_must_match_bound_byte_state(fixture_validated):
    fixture_validated["source_images"] = ["other.png"] * 5
    fixture_validated["transcription_meta"]["source_images"] = [
        {
            "page": page,
            "filename": f"page{page}.png",
            "sha256": f"{page:064x}",
        }
        for page in range(1, 6)
    ]
    serialized = __import__("json").dumps(
        fixture_validated["transcription_meta"]["source_images"],
        sort_keys=True,
        separators=(",", ":"),
    )
    fixture_validated["transcription_meta"]["source_images_hash"] = (
        __import__("hashlib").sha256(serialized.encode()).hexdigest()[:12]
    )

    problems = contract.validated_file_violations(fixture_validated)

    assert any("filenames do not match" in problem for problem in problems)


def test_step_four_model_provenance_and_page_calls_are_complete(fixture_validated):
    fixture_validated["_meta"].update(
        {
            "provider": "gemini",
            "model": "m",
            "prompt_template": "validation.md",
            "prompt_hash": "a" * 12,
            "executed_prompts": [{"page": 999, "prompt_hash": "b" * 12}],
        }
    )
    fixture_validated["validation"]["llm_judge"] = [
        {"page": page["page"], "confidence": "confident", "issues": []}
        for page in fixture_validated["pages"]
    ]

    problems = contract.validated_file_violations(fixture_validated)

    assert any("do not cover all text pages" in problem for problem in problems)


def test_validated_model_text_cannot_change_before_review(fixture_validated):
    fixture_validated["transcription_meta"].update(
        {
            "provider": "gemini",
            "model": "m",
        }
    )
    for page in fixture_validated["pages"]:
        page["transcription_raw"] = page["transcription"]
    fixture_validated["pages"][0]["transcription"] = (
        "X" + fixture_validated["pages"][0]["transcription"][1:]
    )

    problems = contract.validated_file_violations(fixture_validated)

    assert any("changed before a human review transition" in p for p in problems)


def test_review_history_timestamps_must_be_chronological(fixture_transcription):
    fixture_transcription["pages"][0]["review"] = {
        "status": "human_verified",
        "history": [
            {
                "from_status": "machine_unreviewed",
                "status": "in_review",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:00:00+02:00",
            },
            {
                "from_status": "in_review",
                "status": "human_verified",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T09:00:00+02:00",
            },
        ],
    }

    problems = contract.file_violations(fixture_transcription)

    assert any("earlier than the previous event" in problem for problem in problems)


def test_accepted_review_is_bound_to_the_exact_transcription(fixture_transcription):
    page = fixture_transcription["pages"][0]
    page_hash = contract.review_page_state_hash(page)
    page["review"] = {
        "status": "accepted",
        "history": [
            {
                "from_status": "machine_unreviewed",
                "status": "in_review",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:00:00+02:00",
            },
            {
                "from_status": "in_review",
                "status": "human_verified",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:01:00+02:00",
                "page_state_hash": page_hash,
            },
            {
                "from_status": "human_verified",
                "status": "accepted",
                "actor": "editor@example.org",
                "timestamp": "2026-08-27T10:02:00+02:00",
                "page_state_hash": page_hash,
            },
        ],
    }
    assert contract.file_violations(fixture_transcription) == []

    page["transcription"] += " changed after acceptance"

    assert any(
        "decision does not match the current page state" in problem
        for problem in contract.file_violations(fixture_transcription)
    )

    page["transcription"] = page["transcription"].removesuffix(
        " changed after acceptance"
    )
    page["foreign_paragraphs"] = [0]

    assert any(
        "decision does not match the current page state" in problem
        for problem in contract.file_violations(fixture_transcription)
    )


def test_canonical_hashes_keep_the_stored_serialisation():
    """Golden digests produced by the former per-module hash copies.

    Every stored hash (source images, metadata, review decisions, chunk cache)
    depends on this serialisation, so a change must fail here first.
    """
    text = "Grüße " + chr(0x2013) + " " + chr(0x201E) + "Zitat" + chr(0x201C)
    sample = {
        "z": [1, 2.5, None, True],
        "ä": text + " " + chr(0x1D11E),
        "a": {"b": "x", "a": ""},
    }
    page = {
        "page": 1,
        "transcription": "Grüße\n\nZeile",
        "notes": "n",
        "page_type": "",
        "foreign_paragraphs": [1],
    }
    data = {
        "object_id": "o",
        "_meta": {"x": 1},
        "pages": [{"page": 1, "transcription_raw": "Grüße"}],
        "overall_status": "confident",
        "validation": {"rules": []},
    }
    state = [{"page": 1, "filename": "a.png", "sha256": "0" * 64}]

    assert contract.canonical_hash(sample) == "c4c191559025"
    assert contract.canonical_hash(sample, length=None) == (
        "c4c191559025d8fd2e44bb8e7782403bd08e0e292fefb563ca9fe449d4097bbd"
    )
    assert contract.canonical_hash(state) == "bb9190704006"
    assert contract.review_page_state_hash(page) == (
        "74e80bada371444b2ed579aadfd6af5394fe5fe27314d87a46e2f1beb0364984"
    )
    assert contract.raw_transcription_state_hash(data) == "88173c057a58"
    assert contract.transcription_state_hash(data) == "bf4d29a9f2d7"
    assert contract.validation_result_hash(data) == "50cd2e0483f3"
    assert contract.text_hash("prompt") == hashlib.sha256(b"prompt").hexdigest()[:12]


def test_reserved_pipeline_file_names_are_not_object_ids():
    for name in ("errors", "Errors", "CATALOG", "catalog"):
        assert not contract.valid_object_id(name)
    assert contract.valid_object_id("errors-1901")
    assert contract.valid_object_id("catalog.v2")


MALFORMED = [
    {"object_id": "a", "pages": None},
    {"object_id": "a", "pages": "x"},
    {"object_id": "a", "pages": [None, 1, "x"]},
    {"pages": [{"page": 1, "transcription": 5, "foreign_paragraphs": [0]}]},
    {"pages": [{"page": 1, "transcription": "x", "notes": 3, "page_type": ["b"]}]},
    {"pages": [{"page": [1], "transcription": "x", "edits": [{"id": 5}]}]},
    {
        "pages": [
            {
                "page": 1,
                "transcription": "x",
                "review": {"status": ["x"], "history": [None, {"status": {}}]},
            }
        ]
    },
    {
        "_meta": {"pipeline_step": 3, "provider": "g", "executed_prompts": 5},
        "pages": [{"page": 1, "transcription": "x"}],
    },
    {
        "_meta": {
            "pipeline_step": 3,
            "provider": "g",
            "executed_prompts": [{"chunk": 1, "attempt": 1, "pages": 7}],
            "source_images": "x",
        },
        "pages": [{"page": 1, "transcription": "x"}],
        "source_images": [1],
    },
    {
        "transcription_meta": {
            "pipeline_step": 3,
            "model": "m",
            "executed_prompts": [{"chunk": [1], "attempt": 1, "pages": None}],
        },
        "pages": None,
    },
    {
        "_meta": {"pipeline_step": 4, "provider": "g", "executed_prompts": 7},
        "pages": [{"page": 1, "transcription": 5}],
        "validation": {
            "per_page_stats": [{}],
            "llm_judge": [{"page": [1]}],
            "total_characters": 1,
        },
        "overall_status": ["x"],
    },
    {
        "_meta": {
            "pipeline_step": 4,
            "provider": "g",
            "executed_prompts": [{"page": [1]}],
        },
        "pages": [{"page": 1, "transcription": "x"}],
        "validation": {"llm_judge": [{"page": {}}], "per_page_stats": "x"},
    },
    {
        "pages": [],
        "quality_signals": {"page_types": [[1]]},
        "confidence": ["low"],
        "overall_status": {},
        "metadata": {"image_urls": {"a": 1}},
    },
]


@pytest.mark.parametrize("value", MALFORMED)
@pytest.mark.parametrize(
    "check",
    [
        contract.file_violations,
        contract.response_violations,
        contract.validated_file_violations,
    ],
)
def test_violation_functions_report_instead_of_raising(check, value):
    problems = check(copy.deepcopy(value))

    assert isinstance(problems, list)
    assert all(isinstance(problem, str) for problem in problems)
    # A model response is judged by its pages alone; the file checks must
    # name every shape above as a violation.
    if check is not contract.response_violations:
        assert problems


def test_integer_transcription_in_validated_input_is_reported(fixture_validated):
    fixture_validated["pages"][0]["transcription"] = 5

    problems = contract.validated_file_violations(fixture_validated)

    assert "pages[0] has no transcription string" in problems


@pytest.mark.parametrize("field", ["transcription", "notes"])
def test_characters_outside_xml_are_rejected(fixture_transcription, field):
    page = fixture_transcription["pages"][0]
    page[field] = "Zeile" + chr(1) + "Ende"
    page["transcription_raw"] = page["transcription"]
    expected = f"pages[0].{field} contains a character not allowed in XML"

    assert expected in contract.file_violations(fixture_transcription)
    response_page = {"page": 1, "transcription": "x", field: "a" + chr(0xFFFE)}
    assert f"pages[0].{field} contains a character not allowed in XML" in (
        contract.response_violations({"pages": [response_page]})
    )
    for allowed in ("Tab" + chr(9), "Grüße", chr(0x1D11E), "Zeile" + chr(13) + chr(10)):
        page[field] = allowed
        page["transcription_raw"] = page["transcription"]
        assert expected not in contract.file_violations(fixture_transcription)


def test_page_stats_describe_the_current_text():
    pages = [
        {"page": 1, "transcription": "eins zwei\ndrei"},
        {"page": 2, "transcription": ""},
    ]

    assert contract.page_stats(pages) == [
        {"char_count": 14, "word_count": 3, "line_count": 2, "page": 1},
        {"char_count": 0, "word_count": 0, "line_count": 0, "page": 2},
    ]


def test_review_statuses_are_ordered_from_least_mature():
    assert contract.REVIEW_STATUSES == (
        "machine_unreviewed",
        "in_review",
        "human_verified",
        "accepted",
    )
    assert set(contract.REVIEW_TRANSITIONS) == set(contract.REVIEW_STATUSES)
