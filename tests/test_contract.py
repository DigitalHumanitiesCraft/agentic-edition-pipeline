"""Runnable checks for the runtime contract validator (pipeline/contract.py).

The validator is the single source for the field rules of
knowledge/08_DATA_CONTRACT.md; step 3 gates model answers with it and the
contract tests check finished files with the same functions.
"""
from conftest import load_step

contract = load_step("contract")


def test_conformant_fixture_has_no_violations(fixture_transcription):
    assert contract.file_violations(fixture_transcription) == []


def test_missing_top_level_keys_are_named():
    problems = contract.file_violations({"pages": [{"page": 1, "transcription": "x"}]})
    assert any("object_id" in p for p in problems)


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


def test_response_page_needs_number_and_transcription():
    assert contract.response_violations({"pages": [{"transcription": "x"}]})
    assert contract.response_violations({"pages": [{"page": 1}]})
    assert contract.response_violations({"pages": [{"page": 0, "transcription": "x"}]})
    assert contract.response_violations({"pages": [{"page": 1, "transcription": 42}]})


def test_declared_blank_page_stays_usable():
    assert contract.response_violations({"pages": [{"page": 1, "transcription": ""}]}) == []
