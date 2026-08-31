"""Record one explicit human review transition in canonical transcription JSON."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import UTC, datetime

import contract
from config import TRANSCRIPTIONS_DIR, write_json_atomic


def update_page_review(
    data: dict,
    page_number: int,
    status: str,
    actor: str,
    note: str = "",
    timestamp: str | None = None,
) -> dict:
    """Return a copy with one auditable human review transition applied."""
    violations = contract.file_violations(data)
    if violations:
        raise ValueError("input violates the data contract: " + "; ".join(violations))
    if status not in contract.REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {status}")
    if not actor.strip():
        raise ValueError("actor must identify the human reviewer")

    updated = copy.deepcopy(data)
    page = next(
        (item for item in updated["pages"] if item.get("page") == page_number),
        None,
    )
    if page is None:
        raise ValueError(f"page {page_number} does not exist")

    review = page["review"]
    previous = review["status"]
    if previous == status:
        raise ValueError(f"page {page_number} already has review status {status}")
    if status not in contract.REVIEW_TRANSITIONS[previous]:
        allowed = ", ".join(sorted(contract.REVIEW_TRANSITIONS[previous]))
        raise ValueError(f"review status {previous} can transition only to: {allowed}")

    event = {
        "from_status": previous,
        "status": status,
        "actor": actor.strip(),
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }
    if status in {"human_verified", "accepted"}:
        event["page_state_hash"] = contract.review_page_state_hash(page)
    if note.strip():
        event["note"] = note.strip()
    review["status"] = status
    review["history"].append(event)

    violations = contract.file_violations(updated)
    if violations:
        raise ValueError(
            "transition violates the data contract: " + "; ".join(violations)
        )
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record a human review transition on one transcription page."
    )
    parser.add_argument("--object", required=True, help="Object identifier")
    parser.add_argument("--page", required=True, type=int, help="Page number from 1")
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(contract.REVIEW_STATUSES),
        help="New human review status",
    )
    parser.add_argument("--actor", required=True, help="Human reviewer identifier")
    parser.add_argument("--note", default="", help="Optional transition note")
    args = parser.parse_args()

    if not contract.valid_object_id(args.object):
        print(f"ERROR: invalid object identifier {args.object!r}", file=sys.stderr)
        sys.exit(1)
    path = TRANSCRIPTIONS_DIR / f"{args.object}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        updated = update_page_review(
            data,
            args.page,
            args.status,
            args.actor,
            args.note,
        )
        write_json_atomic(path, updated)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Updated {args.object} page {args.page}: {args.status}. "
        "Re-run steps 4, 5, and 6 with --force to propagate the reviewed state."
    )


if __name__ == "__main__":
    main()
