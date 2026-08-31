"""Checks for explicit and auditable human review transitions."""

import pytest

from conftest import load_step

review = load_step("update_review")
contract = load_step("contract")


def test_human_transition_records_actor_timestamp_and_previous_state(
    fixture_transcription,
):
    updated = review.update_page_review(
        fixture_transcription,
        page_number=1,
        status="in_review",
        actor="editor@example.org",
        note="Compared with the facsimile.",
        timestamp="2026-08-27T10:00:00+02:00",
    )

    state = updated["pages"][0]["review"]
    assert state["status"] == "in_review"
    assert state["history"] == [
        {
            "from_status": "machine_unreviewed",
            "status": "in_review",
            "actor": "editor@example.org",
            "timestamp": "2026-08-27T10:00:00+02:00",
            "note": "Compared with the facsimile.",
        }
    ]
    assert contract.file_violations(updated) == []
    assert fixture_transcription["pages"][0]["review"]["status"] == "machine_unreviewed"


def test_transition_rejects_missing_human_actor(fixture_transcription):
    with pytest.raises(ValueError, match="human reviewer"):
        review.update_page_review(
            fixture_transcription,
            page_number=1,
            status="in_review",
            actor=" ",
        )


def test_transition_rejects_skipping_required_review_states(fixture_transcription):
    with pytest.raises(ValueError, match="can transition only"):
        review.update_page_review(
            fixture_transcription,
            page_number=1,
            status="accepted",
            actor="editor@example.org",
        )


def test_review_decisions_bind_text_and_allow_a_documented_return(
    fixture_transcription,
):
    in_review = review.update_page_review(
        fixture_transcription,
        page_number=1,
        status="in_review",
        actor="editor@example.org",
        timestamp="2026-08-27T10:00:00+02:00",
    )
    in_review["pages"][0]["transcription"] += " corrected"
    verified = review.update_page_review(
        in_review,
        page_number=1,
        status="human_verified",
        actor="editor@example.org",
        timestamp="2026-08-27T10:01:00+02:00",
    )
    event = verified["pages"][0]["review"]["history"][-1]
    assert event["page_state_hash"] == contract.review_page_state_hash(
        verified["pages"][0]
    )

    reopened = review.update_page_review(
        verified,
        page_number=1,
        status="in_review",
        actor="editor@example.org",
        timestamp="2026-08-27T10:02:00+02:00",
    )
    returned = review.update_page_review(
        reopened,
        page_number=1,
        status="machine_unreviewed",
        actor="editor@example.org",
        timestamp="2026-08-27T10:03:00+02:00",
    )

    assert contract.file_violations(returned) == []
