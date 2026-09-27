"""Runnable checks for the runtime contract validator (pipeline/contract.py).

The validator is the single source for the field rules of
reference/data-contract.md; step 3 gates model answers with it and the
contract tests check finished files with the same functions.
"""

import copy

import pytest

import config
import contract
from conftest import review_event


def assert_violation(problems: list[str], *needles: str) -> None:
    for needle in needles:
        assert any(needle in problem for problem in problems), (needle, problems)


def _source_image_state() -> list[dict]:
    return [
        {"page": page, "filename": f"page{page}.png", "sha256": f"{page:064x}"}
        for page in range(1, 6)
    ]


def _claim_step_three(data: dict, executed_pages: list[int], **extra) -> None:
    """Give a transcription complete step-3 provenance for executed_pages."""
    state = _source_image_state()
    data["_meta"].update(
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
                    "pages": executed_pages,
                    "attempt": 1,
                    "prompt_hash": "b" * 12,
                }
            ],
            "source_images": state,
            "source_images_hash": config.source_image_state_hash(state),
            **extra,
        }
    )


def test_conformant_fixture_has_no_violations(fixture_transcription):
    assert contract.file_violations(fixture_transcription) == []


@pytest.mark.parametrize(
    ("name", "valid"),
    [
        ("doc-1", True),
        ("errors-1901", True),
        ("catalog.v2", True),
        ("CON", False),
        ("nul.txt", False),
        ("name.", False),
        ("errors", False),
        ("Errors", False),
        ("CATALOG", False),
        ("catalog", False),
    ],
)
def test_object_ids_are_portable_and_leave_pipeline_names_free(name, valid):
    assert contract.valid_object_id(name) is valid


def test_object_id_sets_are_case_insensitively_unique():
    assert_violation(
        contract.unique_object_id_violations(["Doc", "doc"]),
        "not case-insensitively unique",
    )


# Finished transcription files


def _set_meta(field, value):
    return lambda data: data["_meta"].__setitem__(field, value)


def _set_metadata(field, value):
    return lambda data: data["metadata"].__setitem__(field, value)


def _set_page(field, value):
    return lambda data: data["pages"][0].__setitem__(field, value)


def _set_review(*history):
    status = history[-1]["status"] if history else "machine_unreviewed"

    def mutate(data):
        data["pages"][0]["review"] = {"status": status, "history": list(history)}

    return mutate


def _review_disagrees_with_history(data):
    _set_review(review_event("machine_unreviewed", "accepted"))(data)
    data["pages"][0]["review"]["status"] = "machine_unreviewed"


FILE_CASES = {
    "missing-object-id": (lambda d: d.pop("object_id"), ["object_id"]),
    "missing-provenance": (lambda d: d.pop("_meta"), ["_meta"]),
    "empty-document": (lambda d: d.__setitem__("pages", []), ["pages is empty"]),
    "missing-review-state": (
        lambda d: d["pages"][0].pop("review"),
        ["human review state"],
    ),
    "timestamp": (_set_meta("timestamp", "yesterday"), ["timestamp"]),
    "metadata-title": (_set_metadata("title", 42), ["metadata.title"]),
    "image-url": (
        lambda d: d["metadata"]["image_urls"].__setitem__("1", 42),
        ["invalid URL"],
    ),
    "page-type": (_set_page("page_type", "alien"), ["page_type"]),
    "notes": (_set_page("notes", 7), ["notes"]),
    "foreign-paragraphs": (
        _set_page("foreign_paragraphs", "1"),
        ["foreign_paragraphs"],
    ),
    "quality-signals": (
        lambda d: d.__setitem__("quality_signals", "yes"),
        ["quality_signals is not an object"],
    ),
    "transcription-meta": (
        lambda d: d.__setitem__("transcription_meta", "old provenance"),
        ["transcription_meta is not a provenance object"],
    ),
    "status-behind-history": (
        _review_disagrees_with_history,
        ["latest history entry"],
    ),
    "history-out-of-order": (
        _set_review(
            review_event(
                "machine_unreviewed", "in_review", "2026-08-27T10:00:00+02:00"
            ),
            review_event("in_review", "human_verified", "2026-08-27T09:00:00+02:00"),
        ),
        ["earlier than the previous event"],
    ),
    "incomplete-step-three": (
        _set_meta("pipeline_step", 3),
        ["provider is missing", "executed_prompts", "source_images is missing"],
    ),
    "profile-without-layer": (
        lambda d: _claim_step_three(
            d,
            [1, 2, 3, 4, 5],
            prompt_profile="letters",
            prompt_layers=["transcription.md"],
        ),
        ["does not match prompt_profile"],
    ),
    "prompt-log-gap": (
        lambda d: _claim_step_three(d, [999]),
        ["do not cover every page"],
    ),
}


@pytest.mark.parametrize(
    ("mutate", "needles"), list(FILE_CASES.values()), ids=list(FILE_CASES)
)
def test_file_violations_name_the_broken_field(fixture_transcription, mutate, needles):
    mutate(fixture_transcription)

    assert_violation(contract.file_violations(fixture_transcription), *needles)


def test_machine_model_output_requires_unchanged_raw_text(fixture_transcription):
    _claim_step_three(fixture_transcription, [1, 2, 3, 4, 5])

    problems = contract.file_violations(fixture_transcription)

    assert sum("raw model transcription" in problem for problem in problems) == 5


def test_accepted_review_is_bound_to_the_exact_transcription(fixture_transcription):
    page = fixture_transcription["pages"][0]
    page_hash = contract.review_page_state_hash(page)
    page["review"] = {
        "status": "accepted",
        "history": [
            review_event(
                "machine_unreviewed", "in_review", "2026-08-27T10:00:00+02:00"
            ),
            review_event(
                "in_review",
                "human_verified",
                "2026-08-27T10:01:00+02:00",
                page_state_hash=page_hash,
            ),
            review_event(
                "human_verified",
                "accepted",
                "2026-08-27T10:02:00+02:00",
                page_state_hash=page_hash,
            ),
        ],
    }
    assert contract.file_violations(fixture_transcription) == []
    stale = "decision does not match the current page state"

    changed_text = copy.deepcopy(fixture_transcription)
    changed_text["pages"][0]["transcription"] += " changed after acceptance"
    assert_violation(contract.file_violations(changed_text), stale)

    page["foreign_paragraphs"] = [0]
    assert_violation(contract.file_violations(fixture_transcription), stale)


@pytest.mark.parametrize("field", ["transcription", "notes"])
def test_characters_outside_xml_are_rejected(fixture_transcription, field):
    page = fixture_transcription["pages"][0]
    page[field] = "Zeile" + chr(1) + "Ende"
    page["transcription_raw"] = page["transcription"]
    expected = f"pages[0].{field} contains a character not allowed in XML"

    assert expected in contract.file_violations(fixture_transcription)
    response_page = {"page": 1, "transcription": "x", field: "a" + chr(0xFFFE)}
    assert expected in contract.response_violations({"pages": [response_page]})
    for allowed in ("Tab" + chr(9), "Grüße", chr(0x1D11E), "Zeile" + chr(13) + chr(10)):
        page[field] = allowed
        page["transcription_raw"] = page["transcription"]
        assert expected not in contract.file_violations(fixture_transcription)


@pytest.mark.parametrize("field", ["title", "signature", "date", "repository"])
def test_metadata_characters_outside_xml_are_rejected(fixture_transcription, field):
    fixture_transcription["metadata"][field] = "A" + chr(0x0B) + "1"
    expected = f"metadata.{field} contains a character not allowed in XML"

    assert expected in contract.file_violations(fixture_transcription)
    assert expected in contract.metadata_violations(fixture_transcription["metadata"])
    fixture_transcription["metadata"][field] = "Grüße" + chr(9) + chr(0x1D11E)
    assert contract.metadata_violations(fixture_transcription["metadata"]) == []


# Model responses


def _page(**fields) -> dict:
    return {"pages": [fields]}


RESPONSE_CASES = {
    "no-pages": ({"summary": "nichts gefunden"}, ""),
    "empty-pages": ({"pages": []}, ""),
    "pages-not-a-list": ({"pages": "kein Array"}, ""),
    "not-an-object": ("not a dict", ""),
    "none": (None, ""),
    "page-without-number": (_page(transcription="x"), ""),
    "page-without-text": (_page(page=1), ""),
    "page-zero": (_page(page=0, transcription="x"), ""),
    "non-string-text": (_page(page=1, transcription=42), ""),
    "blank-with-text": (
        _page(page=1, transcription="Text", page_type="blank"),
        "declares blank",
    ),
    "foreign-index-out-of-range": (
        _page(page=1, transcription="First\n\nSecond", foreign_paragraphs=[2]),
        "out-of-range",
    ),
    "reserved-review": (_page(page=1, transcription="Text", review=[]), "reserved"),
    "reserved-edits": (_page(page=1, transcription="Text", edits=[]), "reserved"),
    "reserved-raw-text": (
        _page(page=1, transcription="Text", transcription_raw=[]),
        "reserved",
    ),
}


@pytest.mark.parametrize(
    ("response", "needle"), list(RESPONSE_CASES.values()), ids=list(RESPONSE_CASES)
)
def test_response_violations_reject_unusable_answers(response, needle):
    problems = contract.response_violations(response)

    assert problems
    assert_violation(problems, needle)


def test_declared_blank_page_stays_usable():
    assert contract.response_violations(_page(page=1, transcription="")) == []


# Validated files


def _change_first_text(data):
    data["pages"][0]["transcription"] += " changed"


def _change_first_letter(data):
    data["pages"][0]["transcription"] = "X" + data["pages"][0]["transcription"][1:]


def _claim_confident_despite_errors(data):
    data["overall_status"] = "confident"
    data["validation"]["rules"] = [
        {"name": f"error-{index}", "count": 1, "severity": "error"}
        for index in range(3)
    ]


def _inflate_page_stats(data):
    data["validation"]["per_page_stats"][0].update(word_count=999, line_count=999)


def _rename_source_images(data):
    state = _source_image_state()
    data["source_images"] = ["other.png"] * 5
    data["transcription_meta"]["source_images"] = state
    data["transcription_meta"]["source_images_hash"] = config.source_image_state_hash(
        state
    )


def _judge_misses_pages(data):
    data["_meta"].update(
        {
            "provider": "gemini",
            "model": "m",
            "prompt_template": "validation.md",
            "prompt_hash": "a" * 12,
            "executed_prompts": [{"page": 999, "prompt_hash": "b" * 12}],
        }
    )
    data["validation"]["llm_judge"] = [
        {"page": page["page"], "confidence": "confident", "issues": []}
        for page in data["pages"]
    ]


def _edit_model_text_without_review(data):
    data["transcription_meta"].update({"provider": "gemini", "model": "m"})
    for page in data["pages"]:
        page["transcription_raw"] = page["transcription"]
    _change_first_letter(data)


VALIDATED_CASES = {
    "stale-text-statistics": (
        _change_first_text,
        ["char_count is stale", "total_characters is stale"],
    ),
    "equal-length-change": (_change_first_letter, ["state hash does not match"]),
    "changed-findings": (
        _claim_confident_despite_errors,
        ["result hash does not match"],
    ),
    "stale-word-and-line-counts": (
        _inflate_page_stats,
        ["word_count is stale", "line_count is stale"],
    ),
    "renamed-source-images": (_rename_source_images, ["filenames do not match"]),
    "judge-calls-miss-pages": (_judge_misses_pages, ["do not cover all text pages"]),
    "model-text-edited-before-review": (
        _edit_model_text_without_review,
        ["changed before a human review transition"],
    ),
    "integer-transcription": (
        _set_page("transcription", 5),
        ["pages[0] has no transcription string"],
    ),
}


@pytest.mark.parametrize(
    ("mutate", "needles"), list(VALIDATED_CASES.values()), ids=list(VALIDATED_CASES)
)
def test_validated_file_violations_name_the_broken_binding(
    fixture_validated, mutate, needles
):
    mutate(fixture_validated)

    assert_violation(contract.validated_file_violations(fixture_validated), *needles)


# Robustness against arbitrary shapes

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


# Shared hashes and derived values


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
    assert config.source_image_state_hash(state) == "bb9190704006"
    assert contract.review_page_state_hash(page) == (
        "74e80bada371444b2ed579aadfd6af5394fe5fe27314d87a46e2f1beb0364984"
    )
    assert contract.raw_transcription_state_hash(data) == "88173c057a58"
    assert contract.transcription_state_hash(data) == "bf4d29a9f2d7"
    assert contract.validation_result_hash(data) == "50cd2e0483f3"
    assert contract.text_hash("prompt") == "cf07194ee232"


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
