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
    with pytest.raises(ValueError, match="identify the reviewer"):
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


def test_agent_cannot_record_a_human_decision(fixture_transcription):
    in_review = review.update_page_review(
        fixture_transcription, 1, "in_review", "agent-run", actor_kind="agent"
    )
    assert in_review["pages"][0]["review"]["history"][-1]["actor_kind"] == "agent"
    with pytest.raises(ValueError, match="agent cannot"):
        review.update_page_review(
            in_review, 1, "human_verified", "agent-run", actor_kind="agent"
        )


def _cli(monkeypatch, tmp_path, fixture_transcription):
    import json
    import sys

    transcriptions = tmp_path / "data/processed/transcriptions"
    transcriptions.mkdir(parents=True)
    path = transcriptions / "fixture1.json"
    path.write_text(json.dumps(fixture_transcription), encoding="utf-8")
    monkeypatch.setattr(review, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(review, "TRANSCRIPTIONS_DIR", transcriptions)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_review.py",
            "--object",
            "fixture1",
            "--page",
            "1",
            "--status",
            "in_review",
            "--actor",
            "editor@example.org",
        ],
    )
    return path


def test_cli_refuses_while_a_review_transaction_is_pending(
    monkeypatch, tmp_path, capsys, fixture_transcription
):
    path = _cli(monkeypatch, tmp_path, fixture_transcription)
    before = path.read_bytes()
    marker = tmp_path / "results/review-backups/pending.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        review.main()

    assert exit_info.value.code == 1
    assert "--recover" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_cli_refuses_while_another_writer_holds_the_repository(
    monkeypatch, tmp_path, capsys, fixture_transcription
):
    from review_state import repository_writer

    path = _cli(monkeypatch, tmp_path, fixture_transcription)
    before = path.read_bytes()

    with repository_writer(tmp_path), pytest.raises(SystemExit) as exit_info:
        review.main()

    assert exit_info.value.code == 1
    assert "owns this repository" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_cli_records_the_transition(monkeypatch, tmp_path, fixture_transcription):
    import json

    path = _cli(monkeypatch, tmp_path, fixture_transcription)

    review.main()

    assert json.loads(path.read_text(encoding="utf-8"))["pages"][0]["review"][
        "status"
    ] == ("in_review")
