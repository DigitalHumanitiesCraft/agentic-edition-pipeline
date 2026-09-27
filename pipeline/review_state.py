"""Expose explicitly bound dependency state and record review edits in TEI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lxml import etree

import contract
from config import NS, safe_xml_parser
from config import TEI_NS as TEI
from config import XML_NS as XML


def canonical_sha256(data: dict) -> str:
    return contract.canonical_hash(data, length=None)


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
