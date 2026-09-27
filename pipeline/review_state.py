"""Expose explicitly bound dependency state and record review edits in TEI.

Also holds the repository-wide writer lock that the review server, its
recovery CLI and update_review.py share, and the repository-relative paths
of the review transaction marker and snapshots.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from lxml import etree

import contract
from config import (
    NS,
    PROJECT_ROOT,
    REVIEW_BACKUP_DIR,
    REVIEW_PENDING_MARKER,
    safe_path,
    safe_xml_parser,
)
from config import TEI_NS as TEI
from config import XML_NS as XML

# Relative, so every repository root (the real one, a test root) resolves
# the same layout through safe_path.
BACKUP_DIR = REVIEW_BACKUP_DIR.relative_to(PROJECT_ROOT)
PENDING_MARKER = REVIEW_PENDING_MARKER.relative_to(PROJECT_ROOT)


def canonical_sha256(data: dict) -> str:
    return contract.canonical_hash(data, length=None)


def dependencies(root: Path, object_id: str, data: dict | None) -> list[dict]:
    """Report the binding state of optional annotations to the canonical text.

    data is the canonical transcription, or None when it is unavailable; a
    binding that cannot be compared then counts as unreadable.
    """
    path = root / "data/annotations" / f"{object_id}.json"
    if not path.exists() and not path.is_symlink():
        return []
    state = "unbound"
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Linked annotation file")
        annotations = json.loads(path.read_bytes())
        binding = annotations.get("_meta", {}).get("transcription_sha256")
        if binding and data is None:
            raise ValueError("Canonical transcription unavailable")
        if binding:
            state = "current" if binding == canonical_sha256(data) else "stale"
    except (OSError, ValueError, AttributeError):
        state = "unreadable"
    return [
        {
            "id": "annotations",
            "status": state,
        }
    ]


def add_tei_edits(xml: str, pages: list[dict]) -> str:
    """Add only recorded edits; model generation and proposals are not edits."""
    events = [(page["page"], edit) for page in pages for edit in page.get("edits", [])]
    events.sort(
        key=lambda event: (
            datetime.fromisoformat(event[1]["timestamp"]),
            event[1]["id"],
        )
    )
    if not events:
        return xml
    root = etree.fromstring(xml.encode("utf-8"), safe_xml_parser())
    title = root.find(".//tei:titleStmt", NS)
    revision = root.find(".//tei:revisionDesc", NS)
    actors = {}
    for number, edit in events:
        identity = (edit["actor"], edit["actor_kind"])
        if identity not in actors:
            actor_id = f"reviewer-{len(actors) + 1}"
            actors[identity] = actor_id
            statement = etree.SubElement(
                title, f"{{{TEI}}}respStmt", {f"{{{XML}}}id": actor_id}
            )
            etree.SubElement(statement, f"{{{TEI}}}resp").text = (
                "Transcription correction (" + edit["actor_kind"] + ")"
            )
            etree.SubElement(statement, f"{{{TEI}}}name").text = edit["actor"]
        pb = root.find(f".//tei:body//tei:pb[@n='{number}']", NS)
        pb.set(f"{{{XML}}}id", f"review-page-{number}")
        change = etree.SubElement(
            revision,
            f"{{{TEI}}}change",
            {
                f"{{{XML}}}id": "edit-" + edit["id"],
                "type": "transcription-correction",
                "subtype": edit["actor_kind"],
                "when": edit["timestamp"],
                "who": "#" + actors[identity],
                "target": f"#review-page-{number}",
            },
        )
        change.text = edit["note"]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + etree.tostring(root, encoding="unicode")
        + "\n"
    )


def workflow(xml_root) -> dict:
    actors = {
        "#" + node.get(f"{{{XML}}}id", ""): "".join(
            node.find("tei:name", NS).itertext()
        )
        for node in xml_root.findall(".//tei:respStmt", NS)
        if node.find("tei:name", NS) is not None
    }
    changes = [
        {
            "type": node.get("type", "derivation"),
            "actor": actors.get(node.get("who"), ""),
            "actor_kind": node.get("subtype", ""),
            "when": node.get("when", ""),
            "target": node.get("target", ""),
            "text": "".join(node.itertext()),
        }
        for node in xml_root.findall(".//tei:revisionDesc/tei:change", NS)
    ]
    revision = xml_root.find(".//tei:revisionDesc", NS)
    status = revision.get("status", "") if revision is not None else ""
    return {
        "changes": changes,
        "human_review": status,
        "corrections": sum(
            item["type"] == "transcription-correction" for item in changes
        ),
    }


@contextmanager
def repository_writer(root: Path) -> Iterator[None]:
    """Keep review server, recovery and review transitions mutually exclusive.

    An operating-system lock on results/review-backups/writer.lock, released
    when the holding process ends.
    """
    path = safe_path(root.resolve(), BACKUP_DIR / "writer.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if sys.platform == "win32":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError(
                    "Another review server, recovery or review update owns this repository"
                ) from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError(
                    "Another review server, recovery or review update owns this repository"
                ) from None
        yield
