"""Prepare viewer bytes for an already validated local correction transaction.

The records come from step 6's own builders, so a review save and a later
step-6 run write byte-identical docs/data files. Nothing is written here;
the review server stages the returned bytes in its transaction.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from config import ItemFailure, json_bytes, project_info, read_json, safe_path

frontend = importlib.import_module("06_build_frontend")


def _published_record(root: Path, object_id: str) -> dict:
    """Read another object's published record, as step 6 last wrote it."""
    path = safe_path(root, Path(f"docs/data/{object_id}.json"))
    try:
        record = read_json(path)
        frontend.catalog_entry(record)
        if not isinstance(record["_meta"]["input_state_timestamp"], str):
            raise TypeError("input_state_timestamp is not a string")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Published frontend data of {object_id} is missing or incomplete; "
            "rebuild the frontend with step 6"
        ) from exc
    return record


def prepare_viewer(
    object_id: str, xml: str, canonical: dict, root: Path
) -> dict[Path, bytes]:
    """Return the docs/ files that change when object_id gets this TEI.

    Facsimiles are not part of a correction; their published snapshot must
    already hold exactly the bytes step 6 would publish.
    """
    xml_bytes = xml.encode("utf-8")
    docs_dir = safe_path(root, Path("docs"))
    try:
        record, images = frontend.object_record(object_id, xml_bytes, docs_dir)
    except ItemFailure as failure:
        raise ValueError(failure.message) from failure
    if len(record["pages"]) != len(canonical["pages"]):
        raise ValueError("TEI and canonical page count differ")
    for name, content in images.items():
        path = safe_path(root, Path("docs/images") / object_id / name)
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(
                "Published facsimile differs from its source image; rebuild "
                "the frontend with step 6"
            )

    catalog = read_json(safe_path(root, Path("docs/data/catalog.json")))
    ids = [entry["id"] for entry in catalog["objects"]]
    if ids.count(object_id) != 1:
        raise ValueError("Document must occur exactly once in the catalog")
    records = [record]
    sources = {object_id: xml_bytes}
    for other in ids:
        if other != object_id:
            records.append(_published_record(root, other))
            sources[other] = safe_path(
                root, Path(f"results/tei/{other}.xml")
            ).read_bytes()
    project = project_info(root / "knowledge/01_PROJECT.md")

    return {
        Path(f"docs/data/{object_id}.json"): json_bytes(record),
        Path(f"docs/tei/{object_id}.xml"): xml_bytes,
        Path("docs/data/catalog.json"): json_bytes(
            frontend.catalog_document(project, records, sources)
        ),
    }
