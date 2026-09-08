"""Validate edit chains and expose explicitly bound dependency state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI}


def edit_violations(page: dict) -> list[str]:
    """Check the optional chain without inventing a pre-existing raw state."""
    edits = page.get("edits", [])
    if not isinstance(edits, list):
        return ["edits is not a list"]
    problems = []
    previous = None
    previous_time = None
    ids = set()
    for edit in edits:
        if not isinstance(edit, dict):
            return ["edit is not an object"]
        try:
            UUID(edit["id"])
            timestamp = datetime.fromisoformat(edit["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError("timestamp requires timezone")
            if previous_time is not None and timestamp < previous_time:
                problems.append("edit timestamps are not chronological")
            previous_time = timestamp
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append("edit requires a UUID and timezone-aware timestamp")
        identifier = edit.get("id")
        if not isinstance(identifier, str):
            return [*problems, "edit id is not a string"]
        if identifier in ids:
            problems.append("duplicate edit id")
        ids.add(identifier)
        if not isinstance(edit.get("actor_kind"), str) or edit["actor_kind"] not in {
            "human",
            "agent",
        }:
            problems.append("unknown edit actor_kind")
        for key in ("actor", "note"):
            if not isinstance(edit.get(key), str) or not edit[key].strip():
                problems.append(f"edit {key} is required")
        for key in ("before", "after"):
            value = edit.get(key)
            if not isinstance(value, dict) or set(value) != {"transcription", "notes"}:
                return [*problems, f"edit {key} requires transcription and notes"]
            if not all(isinstance(text, str) for text in value.values()):
                return [*problems, f"edit {key} must contain strings"]
        if previous is not None and edit["before"] != previous:
            problems.append("edit chain is discontinuous")
        if edit["before"] == edit["after"]:
            problems.append("edit does not change the page")
        previous = edit["after"]
    if edits and previous != {
        "transcription": page.get("transcription"),
        "notes": page.get("notes", ""),
    }:
        problems.append("edit chain does not match current page")
    return problems


def canonical_sha256(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def dependencies(root: Path, object_id: str, data: dict) -> list[dict]:
    path = root / "data/annotations" / f"{object_id}.json"
    if not path.exists() and not path.is_symlink():
        return []
    state = "unbound"
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Linked annotation file")
        annotations = json.loads(path.read_bytes())
        binding = annotations.get("_meta", {}).get("transcription_sha256")
        if binding:
            state = "current" if binding == canonical_sha256(data) else "stale"
    except (OSError, ValueError, AttributeError):
        state = "unreadable"
    return [
        {
            "id": "annotations",
            "status": state,
            "detail": "Annotationen sind nur bei passender Textbindung aktuell.",
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
    root = etree.fromstring(
        xml.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True)
    )
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
