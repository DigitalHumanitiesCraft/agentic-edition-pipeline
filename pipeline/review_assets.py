"""Prepare viewer bytes for an already validated local correction transaction."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

from lxml import etree

from review_state import dependencies, workflow


def prepare_viewer(
    object_id: str, xml: str, canonical: dict, root: Path
) -> dict[Path, bytes]:
    from review_server import _safe_path

    frontend = importlib.import_module("06_build_frontend")
    xml_bytes = xml.encode("utf-8")
    tree = etree.fromstring(
        xml_bytes, etree.XMLParser(resolve_entities=False, no_network=True)
    )
    meta = frontend.extract_metadata(tree)
    pages = frontend.extract_pages(tree)
    if len(pages) != len(canonical["pages"]):
        raise ValueError("TEI and canonical page count differ")
    expected = canonical.get("_meta", {}).get("source_images", [])
    if expected and len(expected) != len(pages):
        raise ValueError("Bound source image count differs")
    for page, image_state in zip(pages, expected, strict=bool(expected)):
        path = _safe_path(
            root, Path(f"docs/images/{object_id}/{image_state['filename']}")
        )
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != image_state["sha256"]
        ):
            raise ValueError("Published facsimile differs from bound source image")
        page["image"] = f"images/{object_id}/{path.name}"
    if not expected:
        previous_path = _safe_path(root, Path(f"docs/data/{object_id}.json"))
        if previous_path.exists():
            previous = json.loads(previous_path.read_bytes())
            for page, prior in zip(pages, previous.get("pages", []), strict=False):
                image = prior.get("image", "")
                if image.startswith(f"images/{object_id}/"):
                    path = _safe_path(root, Path("docs") / image)
                    if not path.is_file():
                        raise ValueError("Previously published facsimile is missing")
                    page["image"] = image
    data = {
        "_meta": {
            "script": "06_build_frontend.py",
            "source_hash": hashlib.sha256(xml_bytes).hexdigest()[:12],
            "input_state_timestamp": meta.get("input_state_timestamp", ""),
        },
        "id": object_id,
        "pages": pages,
        "has_images": any(page.get("image") for page in pages),
        **{
            key: meta.get(key, "")
            for key in ("title", "date", "language", "signature", "status")
        },
        "workflow": workflow(tree),
        "dependencies": dependencies(root, object_id, canonical),
    }
    catalog = json.loads(_safe_path(root, Path("docs/data/catalog.json")).read_bytes())
    if sum(entry["id"] == object_id for entry in catalog["objects"]) != 1:
        raise ValueError("Document must occur exactly once in the catalog")
    entry = {
        key: data[key]
        for key in (
            "id",
            "title",
            "date",
            "language",
            "signature",
            "status",
            "has_images",
        )
    }
    entry["page_count"] = len(pages)
    catalog["objects"] = [
        entry if item["id"] == object_id else item for item in catalog["objects"]
    ]
    digest = hashlib.sha256(catalog.get("project", "").encode("utf-8"))
    for item in sorted(catalog["objects"], key=lambda item: item["id"]):
        name = f"{item['id']}.xml"
        digest.update(name.encode("utf-8"))
        digest.update(
            xml_bytes
            if item["id"] == object_id
            else _safe_path(root, Path("results/tei") / name).read_bytes()
        )
    catalog["source_hash"] = digest.hexdigest()[:12]
    catalog["_meta"] = {**data["_meta"], "source_hash": catalog["source_hash"]}

    def encode(value: object) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    return {
        Path(f"docs/data/{object_id}.json"): encode(data),
        Path(f"docs/tei/{object_id}.xml"): xml_bytes,
        Path(f"docs/txt/{object_id}.txt"): (
            "\n\n\f\n\n".join(page["transcription"] for page in canonical["pages"])
            + "\n"
        ).encode("utf-8"),
        Path("docs/data/catalog.json"): encode(catalog),
    }
