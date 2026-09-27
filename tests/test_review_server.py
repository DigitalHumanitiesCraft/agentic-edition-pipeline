"""Exercise local write boundaries and rollback without touching the corpus."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import re
import sys
import threading
import zipfile
from pathlib import Path

import pytest

import review_server
from update_review import update_page_review


@pytest.fixture
def review_root(tmp_path: Path, fixture_transcription: dict) -> Path:
    """Use the contract fixture for local HTTP and filesystem failure cases."""
    data = copy.deepcopy(fixture_transcription)
    data["pages"] = data["pages"][:1]
    data["pages"][0]["foreign_paragraphs"] = []
    data["pages"][0]["transcription_raw"] = data["pages"][0]["transcription"]
    data.pop("quality_signals")
    data["metadata"]["image_urls"] = {"1": "https://example.org/image.jpg"}
    files = {
        "data/processed/transcriptions/fixture1.json": review_server._json_bytes(data),
        "docs/data/catalog.json": review_server._json_bytes(
            {"project": "Fixture", "objects": [{"id": "fixture1"}]}
        ),
        "docs/index.html": b"<!doctype html><title>Local fixture</title>",
        "knowledge/01_PROJECT.md": b"# Fixture\n",
        ".env": b"PRIVATE_SENTINEL=not_for_http",
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return tmp_path


def _payload(store: review_server.ReviewStore, **extra) -> dict:
    return {
        "version": store.document("fixture1")["version"],
        "transcription": "Korrigierte Zeile",
        "notes": "Bildprüfung",
        "actor": "Reviewer",
        "note": "Lesung anhand Faksimile",
        **extra,
    }


def test_persists_real_stages_and_preserves_original(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    path = review_root / "data/processed/transcriptions/fixture1.json"
    before = path.read_bytes()
    original = json.loads(before)
    result = store.save("fixture1", 1, _payload(store, actor_kind="agent"))
    after = json.loads(path.read_bytes())
    assert result["version"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert after["_meta"] == original["_meta"]
    assert (
        after["pages"][0]["transcription_raw"]
        == original["pages"][0]["transcription_raw"]
    )
    assert after["pages"][0]["review"]["status"] == "in_review"
    assert after["pages"][0]["edits"][0]["actor_kind"] == "agent"
    with zipfile.ZipFile(
        next((review_root / "results/review-backups").rglob("*.zip"))
    ) as archive:
        assert archive.read("data/processed/transcriptions/fixture1.json") == before
    tei = (review_root / "results/tei/fixture1.xml").read_bytes()
    assert tei == (review_root / "docs/tei/fixture1.xml").read_bytes()
    assert not (review_root / "data/processed/tei").exists()
    assert not (review_root / "docs/txt").exists()
    frontend = json.loads((review_root / "docs/data/fixture1.json").read_bytes())
    assert frontend["workflow"]["corrections"] == 1
    assert frontend["workflow"]["human_review"] == "in_review"
    assert (
        json.loads((review_root / "docs/data/catalog.json").read_bytes())["objects"][0][
            "status"
        ]
        == "in_review"
    )


def test_reopens_accepted_and_rejects_stale_version(review_root: Path) -> None:
    path = review_root / "data/processed/transcriptions/fixture1.json"
    data = json.loads(path.read_bytes())
    for status in ("in_review", "human_verified", "accepted"):
        data = update_page_review(data, 1, status, "Prior reviewer")
    path.write_bytes(review_server._json_bytes(data))
    store = review_server.ReviewStore(review_root)
    payload = _payload(store)
    result = store.save("fixture1", 1, payload)
    history = result["pages"][0]["review"]["history"]
    assert history[-1]["from_status"] == "accepted"
    assert history[-1]["status"] == "in_review"
    with pytest.raises(FileExistsError):
        store.save("fixture1", 1, payload)


def test_failed_gate_preserves_all_originals(review_root: Path) -> None:
    def fail(root: Path, object_id: str, data: dict) -> dict:
        raise ValueError("Injected validation failure")

    before = {
        path: path.read_bytes() for path in review_root.rglob("*") if path.is_file()
    }
    store = review_server.ReviewStore(review_root, builder=fail)
    with pytest.raises(ValueError, match="validation failure"):
        store.save("fixture1", 1, _payload(store))
    assert before == {
        path: path.read_bytes() for path in review_root.rglob("*") if path.is_file()
    }


def test_write_failure_rolls_back_published_files(
    review_root: Path, monkeypatch
) -> None:
    store = review_server.ReviewStore(review_root)
    before = {
        path: path.read_bytes() for path in review_root.rglob("*") if path.is_file()
    }
    original_write = review_server.write_bytes_atomic
    failed = False

    def fail_once(path: Path, content: bytes) -> None:
        nonlocal failed
        if path == review_root / "docs/tei/fixture1.xml" and not failed:
            failed = True
            raise OSError("Injected publication failure")
        original_write(path, content)

    monkeypatch.setattr(review_server, "write_bytes_atomic", fail_once)
    with pytest.raises(OSError, match="publication failure"):
        store.save("fixture1", 1, _payload(store))
    current = {
        path: path.read_bytes()
        for path in review_root.rglob("*")
        if path.is_file() and "review-backups" not in path.parts
    }
    assert current == before


@pytest.fixture
def running_server(review_root: Path):
    store = review_server.ReviewStore(review_root)
    server = review_server.ReviewServer(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _request(
    server,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict | None = None,
) -> tuple[int, bytes]:
    # Saves include full schema validation and rebuilding derived assets.
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=60
    )
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_http_security_and_version_conflict(running_server) -> None:
    server = running_server
    status, body = _request(server, "GET", "/api/session")
    assert status == 200
    token = json.loads(body)["token"]
    payload = review_server._json_bytes(_payload(server.store))
    headers = {"Content-Type": "application/json", "X-Review-Token": token}
    assert (
        _request(server, "POST", "/api/documents/fixture1/pages/1", payload)[0] == 403
    )
    assert (
        _request(server, "GET", "/api/session", headers={"Host": "evil.example"})[0]
        == 403
    )
    assert (
        _request(
            server, "GET", "/api/session", headers={"Origin": "https://evil.example"}
        )[0]
        == 403
    )
    assert (
        _request(
            server, "GET", "/api/session", headers={"Sec-Fetch-Site": "cross-site"}
        )[0]
        == 403
    )
    for path in (
        "/.env",
        "/%2e%2e/.env",
        "/../.env",
        "/data/",
        "/api/documents/unknown",
    ):
        status, body = _request(server, "GET", path)
        assert status == 404
        assert b"PRIVATE_SENTINEL" not in body
    assert (
        _request(server, "POST", "/api/documents/fixture1/pages/1", payload, headers)[0]
        == 200
    )
    assert (
        _request(server, "POST", "/api/documents/fixture1/pages/1", payload, headers)[0]
        == 409
    )
    unchanged = review_server._json_bytes(_payload(server.store))
    status, body = _request(
        server, "POST", "/api/documents/fixture1/pages/1", unchanged, headers
    )
    assert (status, json.loads(body)) == (400, {"error": "No change to save"})
    wrong_kind = review_server._json_bytes(
        _payload(server.store, transcription="Andere Lesung", actor_kind=["human"])
    )
    assert (
        _request(
            server, "POST", "/api/documents/fixture1/pages/1", wrong_kind, headers
        )[0]
        == 400
    )
    headers["Content-Length"] = str(review_server.MAX_BODY + 1)
    assert (
        _request(server, "POST", "/api/documents/fixture1/pages/1", b"", headers)[0]
        == 413
    )


def test_parallel_saves_allow_only_one_version(review_root: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    store = review_server.ReviewStore(review_root)
    payload = _payload(store)

    def save() -> str:
        try:
            store.save("fixture1", 1, payload)
        except FileExistsError:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: save(), range(2))) == ["conflict", "saved"]


def test_proposal_leaves_canonical_and_tei_unchanged(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    before = store.document("fixture1")
    result = store.save(
        "fixture1", 1, _payload(store, actor_kind="agent"), proposal=True
    )
    assert result["version"] == before["version"]
    assert result["pages"] == before["pages"]
    assert result["proposals"][0]["actor_kind"] == "agent"
    assert not (review_root / "results/tei/fixture1.xml").exists()


def test_blank_reason_and_unknown_fields_are_rejected(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    for extra in (
        {"note": "  "},
        {"status": "accepted"},
        {"transcription_raw": "changed"},
    ):
        with pytest.raises(ValueError):
            store.save("fixture1", 1, _payload(store, **extra))


def test_repository_writer_is_exclusive_and_releases(review_root: Path) -> None:
    with (
        review_server.repository_writer(review_root),
        pytest.raises(RuntimeError, match="Another review server"),
        review_server.repository_writer(review_root),
    ):
        pass
    with review_server.repository_writer(review_root):
        pass


def test_model_bound_source_and_raw_survive_edit(
    review_root: Path, monkeypatch
) -> None:
    import importlib

    import config

    step3 = importlib.import_module("03_transcribe")
    source_dir = review_root / "data/sources/images"
    source = source_dir / "fixture1/page.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic-source-bytes")
    snapshot = review_root / "docs/images/fixture1/page.png"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(source.read_bytes())
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", source_dir)
    monkeypatch.setattr(config, "IMAGES_DIR", review_root / "data/processed/images")
    canonical_dir = review_root / "data/processed/transcriptions"
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", canonical_dir)
    monkeypatch.setattr(step3, "find_images_for_document", lambda doc: [source])
    monkeypatch.setattr(
        step3,
        "call_llm",
        lambda *a, **k: json.dumps(
            {"pages": [{"page": 1, "transcription": "Original model text"}]}
        ),
    )
    assert (
        step3.transcribe_document(
            {"id": "fixture1"}, "synthetic prompt", "gemini", "mock", 1, True
        )
        is None
    )
    store = review_server.ReviewStore(review_root)
    original = store.document("fixture1")
    result = store.save("fixture1", 1, _payload(store))
    assert result["pages"][0]["transcription_raw"] == "Original model text"
    assert result["origin"] == original["origin"]
    frontend = json.loads((review_root / "docs/data/fixture1.json").read_bytes())
    assert frontend["pages"][0]["image"] == "images/fixture1/page.png"
    snapshot.write_bytes(b"wrong facsimile")
    with pytest.raises(ValueError, match="facsimile"):
        store.save("fixture1", 1, _payload(store, transcription="Another reading"))


def test_generated_assets_are_blocked_during_recovery(running_server) -> None:
    server = running_server
    server.store.marker.parent.mkdir(parents=True, exist_ok=True)
    server.store.marker.write_text("{}", encoding="utf-8")
    assert _request(server, "GET", "/index.html")[0] == 503
    assert _request(server, "HEAD", "/index.html")[0] == 503
    status, body = _request(server, "GET", "/api/session")
    assert status == 200 and not json.loads(body)["writable"]


def test_reserved_model_fields_cannot_create_edit_history() -> None:
    import contract

    for field in ("review", "edits", "transcription_raw"):
        response = {"pages": [{"page": 1, "transcription": "Text", field: []}]}
        assert any(
            "reserved" in problem for problem in contract.response_violations(response)
        )


def test_interrupted_transaction_blocks_writes_and_recovers(
    review_root: Path, monkeypatch
) -> None:
    store = review_server.ReviewStore(review_root)
    original = store.document("fixture1")
    write = review_server.write_bytes_atomic

    def crash(path, content):
        if path == review_root / "docs/tei/fixture1.xml":
            raise KeyboardInterrupt("Simulated process interruption")
        write(path, content)

    monkeypatch.setattr(review_server, "write_bytes_atomic", crash)
    with pytest.raises(KeyboardInterrupt):
        store.save("fixture1", 1, _payload(store))
    assert store.marker.exists()
    restarted = review_server.ReviewStore(review_root)
    assert not restarted.document("fixture1")["writable"]
    with pytest.raises(ValueError, match="Interrupted"):
        restarted.save("fixture1", 1, _payload(restarted))
    monkeypatch.setattr(review_server, "write_bytes_atomic", write)
    restarted.recover()
    assert restarted.document("fixture1")["version"] == original["version"]
    assert not restarted.marker.exists()


def test_enriched_tei_is_preserved(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store))
    path = review_root / "results/tei/fixture1.xml"
    enriched = path.read_text(encoding="utf-8").replace(
        "Korrigierte Zeile", "<name>Korrigierte Zeile</name>"
    )
    path.write_text(enriched, encoding="utf-8")
    before = store.document("fixture1")["version"]
    with pytest.raises(ValueError, match="annotation workflow"):
        store.save("fixture1", 1, _payload(store, transcription="Another change"))
    assert path.read_text(encoding="utf-8") == enriched
    assert store.document("fixture1")["version"] == before


def test_manual_transcription_uses_the_published_local_facsimile(
    review_root: Path,
) -> None:
    from review_assets import prepare_viewer

    source = review_root / "data/processed/transcriptions/fixture1.json"
    data = json.loads(source.read_bytes())
    del data["metadata"]["image_urls"]
    source.write_bytes(review_server._json_bytes(data))
    image = review_root / "docs/images/fixture1/local.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"synthetic")
    validated_dir = review_root / "staged-validated"
    review_server.validator.validate_one(
        "fixture1",
        None,
        True,
        transcriptions_dir=source.parent,
        validated_dir=validated_dir,
        calls_dir=review_root / "staged-calls",
    )
    validated = json.loads((validated_dir / "fixture1.json").read_bytes())
    xml = review_server.annotator.generate_tei("fixture1", validated, {})
    result = prepare_viewer("fixture1", xml, data, review_root)
    assert (
        json.loads(result[Path("docs/data/fixture1.json")])["pages"][0]["image"]
        == "images/fixture1/local.png"
    )
    assert set(result) == {
        Path("docs/data/fixture1.json"),
        Path("docs/tei/fixture1.xml"),
        Path("docs/data/catalog.json"),
    }


def test_optional_annotations_become_stale(review_root: Path) -> None:
    from review_state import canonical_sha256

    store = review_server.ReviewStore(review_root)
    source = json.loads(
        (review_root / "data/processed/transcriptions/fixture1.json").read_bytes()
    )
    annotation = review_root / "data/annotations/fixture1.json"
    annotation.parent.mkdir(parents=True)
    annotation.write_bytes(
        review_server._json_bytes(
            {"_meta": {"transcription_sha256": canonical_sha256(source)}}
        )
    )
    assert store.document("fixture1")["dependencies"][0]["status"] == "current"
    result = store.save("fixture1", 1, _payload(store))
    assert result["dependencies"][0]["status"] == "stale"


def test_edit_chain_and_page_targets(review_root: Path) -> None:
    from lxml import etree

    import contract

    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store))
    store.save("fixture1", 1, _payload(store, transcription="Noch eine Lesung"))
    data = json.loads(
        (review_root / "data/processed/transcriptions/fixture1.json").read_bytes()
    )
    assert not contract.file_violations(data)
    broken = copy.deepcopy(data)
    broken["pages"][0]["edits"][1]["before"]["transcription"] = "lost"
    assert any(
        "discontinuous" in problem for problem in contract.file_violations(broken)
    )
    tree = etree.parse(str(review_root / "results/tei/fixture1.xml"))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    edits = tree.findall(".//t:change[@type='transcription-correction']", ns)
    assert len(edits) == 2
    ids = tree.xpath("//@xml:id")
    assert all(
        edit.get("target")[1:] in ids and edit.get("who")[1:] in ids for edit in edits
    )


def test_configured_schema_can_block_save(
    review_root: Path, monkeypatch, tmp_path
) -> None:
    schema = tmp_path / "reject.rng"
    schema.write_text(
        '<element xmlns="http://relaxng.org/ns/structure/1.0" name="unsupported"><empty/></element>',
        encoding="utf-8",
    )
    monkeypatch.setattr(review_server, "VALIDATION_SCHEMA", schema)
    store = review_server.ReviewStore(review_root)
    before = store.document("fixture1")["version"]
    with pytest.raises(ValueError, match="RelaxNG"):
        store.save("fixture1", 1, _payload(store))
    assert store.document("fixture1")["version"] == before


def test_responses_carry_the_page_content_security_policy(running_server) -> None:
    connection = http.client.HTTPConnection(
        "127.0.0.1", running_server.server_address[1], timeout=60
    )
    try:
        connection.request("GET", "/index.html")
        response = connection.getresponse()
        response.read()
        policy = response.getheader("Content-Security-Policy")
    finally:
        connection.close()
    page = Path(__file__).parent.parent / "docs/index.html"
    meta = re.search(
        r'http-equiv="Content-Security-Policy" content="([^"]+)"',
        page.read_text(encoding="utf-8"),
    )
    assert meta is not None
    assert policy == meta.group(1) + "; frame-ancestors 'none'"


def test_oversized_text_and_non_string_actor_kind_are_rejected(
    review_root: Path,
) -> None:
    store = review_server.ReviewStore(review_root)
    too_long = "x" * (review_server.MAX_TEXT_CHARS + 1)
    for extra in (
        {"actor_kind": ["human"]},
        {"transcription": too_long},
        {"notes": too_long},
    ):
        with pytest.raises(ValueError):
            store.save("fixture1", 1, _payload(store, **extra))


def test_unchanged_save_is_rejected(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    page = store.document("fixture1")["pages"][0]
    with pytest.raises(ValueError, match="No change"):
        store.save(
            "fixture1",
            1,
            _payload(store, transcription=page["transcription"], notes=page["notes"]),
        )


def test_recover_without_pending_transaction_exits_with_a_message(
    review_root: Path, monkeypatch, capsys
) -> None:
    with pytest.raises(LookupError):
        review_server.ReviewStore(review_root).recover()
    monkeypatch.setattr(review_server, "PROJECT_ROOT", review_root)
    monkeypatch.setattr(sys, "argv", ["review_server.py", "--recover"])
    with pytest.raises(SystemExit) as exit_info:
        review_server.main()
    assert exit_info.value.code == 1
    assert "No interrupted review transaction" in capsys.readouterr().err


def test_corrupt_proposal_is_reported_without_blocking_the_document(
    review_root: Path,
) -> None:
    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store, actor_kind="agent"), proposal=True)
    broken = review_root / "data/review-proposals/fixture1/broken.json"
    broken.write_text("{", encoding="utf-8")

    proposals = store.document("fixture1")["proposals"]

    failed = [item for item in proposals if "error" in item]
    assert len(proposals) == 2
    assert [item["id"] for item in failed] == ["broken"]
    assert failed[0]["error"].startswith("Unreadable proposal")


def test_review_save_and_frontend_build_write_identical_data(
    review_root: Path, monkeypatch
) -> None:
    import importlib

    import config

    step6 = importlib.import_module("06_build_frontend")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", review_root / "results/tei")
    monkeypatch.setattr(step6, "RESULTS_REPORTS_DIR", review_root / "results/reports")
    monkeypatch.setattr(step6, "DOCS_DIR", review_root / "docs")
    monkeypatch.setattr(
        step6,
        "project_info",
        lambda: config.project_info(review_root / "knowledge/01_PROJECT.md"),
    )
    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store))
    # A second, external object sorts before fixture1 only under casefold.
    (review_root / "results/tei/Alpha.xml").write_bytes(
        (review_root / "results/tei/fixture1.xml")
        .read_bytes()
        .replace(b"Korrigierte Zeile", b"Andere Quelle")
        .replace(b"validation_state_hash=", b"external_state=")
    )
    assert step6.build_all()[0] == []
    catalog = json.loads((review_root / "docs/data/catalog.json").read_bytes())
    assert [entry["id"] for entry in catalog["objects"]] == ["Alpha", "fixture1"]

    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store, transcription="Zweite Lesung"))
    saved = {path: path.read_bytes() for path in (review_root / "docs/data").rglob("*")}
    assert step6.build_all()[0] == []
    assert saved == {
        path: path.read_bytes() for path in (review_root / "docs/data").rglob("*")
    }
