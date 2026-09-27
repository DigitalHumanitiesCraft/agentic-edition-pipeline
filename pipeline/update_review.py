"""Record one explicit review transition in canonical transcription JSON.

The CLI holds the same repository writer lock as the local review server and
refuses to write while an interrupted review transaction awaits recovery,
because recovery would restore the snapshot and silently drop the transition.
"""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import UTC, datetime

import contract
from config import (
    PROJECT_ROOT,
    TRANSCRIPTIONS_DIR,
    configure_console,
    read_json,
    write_json_atomic,
)
from review_state import PENDING_MARKER, repository_writer

ACTOR_KINDS = frozenset({"human", "agent"})


def update_page_review(
    data: dict,
    page_number: int,
    status: str,
    actor: str,
    note: str = "",
    timestamp: str | None = None,
    actor_kind: str | None = None,
) -> dict:
    """Return a copy with one auditable review transition applied.

    actor_kind, when given, is recorded with the event; an agent can reopen
    or return a page but cannot record human_verified or accepted.
    """
    violations = contract.file_violations(data)
    if violations:
        raise ValueError("input violates the data contract: " + "; ".join(violations))
    if status not in contract.REVIEW_STATUSES:
        raise ValueError(f"unknown review status: {status}")
    if not actor.strip():
        raise ValueError("actor must identify the reviewer")
    if actor_kind is not None and actor_kind not in ACTOR_KINDS:
        raise ValueError("actor_kind must be human or agent")
    if actor_kind == "agent" and status in contract.HUMAN_DECISIONS:
        raise ValueError(f"an agent cannot record the human decision {status}")

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
    if actor_kind is not None:
        event["actor_kind"] = actor_kind
    if status in contract.HUMAN_DECISIONS:
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
    configure_console()
    parser = argparse.ArgumentParser(
        description="Record a review transition on one transcription page."
    )
    parser.add_argument("--object", required=True, help="Object identifier")
    parser.add_argument("--page", required=True, type=int, help="Page number from 1")
    parser.add_argument(
        "--status",
        required=True,
        choices=sorted(contract.REVIEW_STATUSES),
        help="New review status; human_verified and accepted are human decisions",
    )
    parser.add_argument("--actor", required=True, help="Reviewer identifier")
    parser.add_argument("--note", default="", help="Optional transition note")
    args = parser.parse_args()

    if not contract.valid_object_id(args.object):
        print(f"ERROR: invalid object identifier {args.object!r}", file=sys.stderr)
        sys.exit(1)
    path = TRANSCRIPTIONS_DIR / f"{args.object}.json"
    try:
        with repository_writer(PROJECT_ROOT):
            if (PROJECT_ROOT / PENDING_MARKER).exists():
                raise ValueError(
                    "an interrupted review transaction is pending; run "
                    "`uv run python pipeline/review_server.py --recover` first"
                )
            updated = update_page_review(
                read_json(path), args.page, args.status, args.actor, args.note
            )
            write_json_atomic(path, updated)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Updated {args.object} page {args.page}: {args.status}. "
        "Re-run step 4 with --force, then steps 5 and 6, to propagate the "
        "reviewed state."
    )


if __name__ == "__main__":
    main()
