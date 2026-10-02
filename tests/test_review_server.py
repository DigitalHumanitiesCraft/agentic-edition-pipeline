"""Exercise local write boundaries and rollback without touching the corpus."""

from __future__ import annotations

import copy
import hashlib
import http.client
import importlib
import json
import re
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from lxml import etree

import config
import contract
import review_server
from conftest import NS, REPOSITORY_ROOT, TEI_ALL_SCHEMA, point_step6_at, read_json
from review_assets import prepare_viewer
from review_state import canonical_sha256, repository_writer
from update_review import update_page_review

step3 = importlib.import_module("03_transcribe")
step6 = importlib.import_module("06_build_frontend")

CANONICAL = Path("data/processed/transcriptions/fixture1.json")
PAGE_URL = "/api/documents/fixture1/pages/1"


@pytest.fixture
def review_root(monkeypatch, tmp_path: Path, fixture_transcription: dict) -> Path:
    """A one-page repository copy; schema and image lookup stay inside it."""
    monkeypatch.setattr(review_server, "VALIDATION_SCHEMA", TEI_ALL_SCHEMA)
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", tmp_path / "data/sources/images")
    monkeypatch.setattr(config, "IMAGES_DIR", tmp_path / "data/processed/images")
    data = copy.deepcopy(fixture_transcription)
    data["pages"] = data["pages"][:1]
    data["pages"][0]["foreign_paragraphs"] = []
    data["pages"][0]["transcription_raw"] = data["pages"][0]["transcription"]
    data.pop("quality_signals")
    data["metadata"]["image_urls"] = {"1": "https://example.org/image.jpg"}
    files = {
        CANONICAL: review_server._json_bytes(data),
        Path("docs/data/catalog.json"): review_server._json_bytes(
            {"project": "Fixture", "objects": [{"id": "fixture1"}]}
        ),
        Path("docs/index.html"): b"<!doctype html><title>Local fixture</title>",
        Path("knowledge/01_PROJECT.md"): b"# Fixture\n",
        Path(".env"): b"PRIVATE_SENTINEL=not_for_http",
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


def _snapshot(root: Path, skip_backups: bool = False) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and not (skip_backups and "review-backups" in path.parts)
    }


def _fail_writes_to(monkeypatch, root: Path, relative: str, error: BaseException):
    original = review_server.write_bytes_atomic
    failed = []

    def fail_once(path: Path, content: bytes) -> None:
        if path == root / relative and not failed:
            failed.append(path)
            raise error
        original(path, content)

    monkeypatch.setattr(review_server, "write_bytes_atomic", fail_once)


# Store transactions


def test_persists_real_stages_and_preserves_original(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    path = review_root / CANONICAL
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
        assert archive.read(CANONICAL.as_posix()) == before
    tei = (review_root / "results/tei/fixture1.xml").read_bytes()
    assert tei == (review_root / "docs/tei/fixture1.xml").read_bytes()
    assert not (review_root / "data/processed/tei").exists()
    assert not (review_root / "docs/txt").exists()
    frontend = read_json(review_root / "docs/data/fixture1.json")
    assert frontend["workflow"]["corrections"] == 1
    assert frontend["workflow"]["human_review"] == "in_review"
    catalog = read_json(review_root / "docs/data/catalog.json")
    assert catalog["objects"][0]["status"] == "in_review"


def test_reopens_accepted_and_rejects_stale_version(review_root: Path) -> None:
    path = review_root / CANONICAL
    data = read_json(path)
    for status in ("in_review", "human_verified", "accepted"):
        data = update_page_review(data, 1, status, "Prior reviewer")
    path.write_bytes(review_server._json_bytes(data))
    store = review_server.ReviewStore(review_root)
    payload = _payload(store)

    history = store.save("fixture1", 1, payload)["pages"][0]["review"]["history"]

    assert (history[-1]["from_status"], history[-1]["status"]) == (
        "accepted",
        "in_review",
    )
    with pytest.raises(FileExistsError):
        store.save("fixture1", 1, payload)


def test_failed_gate_preserves_all_originals(review_root: Path) -> None:
    def fail(_root: Path, _object_id: str, _data: dict) -> dict:
        raise ValueError("Injected validation failure")

    before = _snapshot(review_root)
    store = review_server.ReviewStore(review_root, builder=fail)

    with pytest.raises(ValueError, match="validation failure"):
        store.save("fixture1", 1, _payload(store))

    assert _snapshot(review_root) == before


def test_write_failure_rolls_back_published_files(review_root, monkeypatch) -> None:
    store = review_server.ReviewStore(review_root)
    before = _snapshot(review_root)
    _fail_writes_to(
        monkeypatch,
        review_root,
        "docs/tei/fixture1.xml",
        OSError("Injected publication failure"),
    )

    with pytest.raises(OSError, match="publication failure"):
        store.save("fixture1", 1, _payload(store))

    assert _snapshot(review_root, skip_backups=True) == before


def test_interrupted_transaction_blocks_writes_and_recovers(
    review_root: Path, monkeypatch
) -> None:
    store = review_server.ReviewStore(review_root)
    original = store.document("fixture1")
    _fail_writes_to(
        monkeypatch,
        review_root,
        "docs/tei/fixture1.xml",
        KeyboardInterrupt("Simulated process interruption"),
    )

    with pytest.raises(KeyboardInterrupt):
        store.save("fixture1", 1, _payload(store))

    assert store.marker.exists()
    restarted = review_server.ReviewStore(review_root)
    assert not restarted.document("fixture1")["writable"]
    with pytest.raises(ValueError, match="Interrupted"):
        restarted.save("fixture1", 1, _payload(restarted))
    restarted.recover()
    assert restarted.document("fixture1")["version"] == original["version"]
    assert not restarted.marker.exists()


def test_parallel_saves_allow_only_one_version(review_root: Path) -> None:
    """The second save starts while the first holds its transaction open."""
    first_inside = threading.Event()
    second_queued = threading.Event()

    def builder(_root: Path, _object_id: str, data: dict) -> dict:
        if threading.current_thread().name == "first":
            first_inside.set()
            assert second_queued.wait(10), "second save never reached the lock"
        return {CANONICAL: review_server._json_bytes(data)}

    store = review_server.ReviewStore(review_root, builder=builder)
    lock = store.lock

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "second":
                second_queued.set()
            return lock.__enter__()

        def __exit__(self, *exc_info):
            return lock.__exit__(*exc_info)

    store.lock = ObservedLock()
    payload = _payload(store)
    outcomes: dict[str, str] = {}

    def save() -> None:
        name = threading.current_thread().name
        try:
            store.save("fixture1", 1, payload)
        except FileExistsError:
            outcomes[name] = "conflict"
        else:
            outcomes[name] = "saved"

    first = threading.Thread(target=save, name="first")
    second = threading.Thread(target=save, name="second")
    first.start()
    assert first_inside.wait(10)
    second.start()
    for thread in (first, second):
        thread.join(10)
        assert not thread.is_alive()

    assert outcomes == {"first": "saved", "second": "conflict"}


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


@pytest.mark.parametrize(
    "extra",
    [
        {"note": "  "},
        {"status": "accepted"},
        {"transcription_raw": "changed"},
        {"actor_kind": ["human"]},
        {"transcription": "x" * (review_server.MAX_TEXT_CHARS + 1)},
        {"notes": "x" * (review_server.MAX_TEXT_CHARS + 1)},
    ],
    ids=[
        "blank-reason",
        "status-field",
        "raw-text-field",
        "non-string-actor-kind",
        "oversized-text",
        "oversized-notes",
    ],
)
def test_invalid_requests_are_rejected_before_any_write(
    review_root: Path, extra: dict
) -> None:
    store = review_server.ReviewStore(review_root)
    before = _snapshot(review_root)

    with pytest.raises(ValueError):
        store.save("fixture1", 1, _payload(store, **extra))

    assert _snapshot(review_root) == before


def test_unchanged_save_is_rejected(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    page = store.document("fixture1")["pages"][0]

    with pytest.raises(ValueError, match="No change"):
        store.save(
            "fixture1",
            1,
            _payload(store, transcription=page["transcription"], notes=page["notes"]),
        )


def test_repository_writer_is_exclusive_and_releases(review_root: Path) -> None:
    with (
        repository_writer(review_root),
        pytest.raises(RuntimeError, match="Another review server"),
        repository_writer(review_root),
    ):
        pass
    with repository_writer(review_root):
        pass


def test_model_bound_source_and_raw_survive_edit(
    review_root: Path, monkeypatch
) -> None:
    source = review_root / "data/sources/images/fixture1/page.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic-source-bytes")
    snapshot = review_root / "docs/images/fixture1/page.png"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(source.read_bytes())
    monkeypatch.setattr(step3, "TRANSCRIPTIONS_DIR", (review_root / CANONICAL).parent)
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
    frontend = read_json(review_root / "docs/data/fixture1.json")
    assert frontend["pages"][0]["image"] == "images/fixture1/page.png"
    snapshot.write_bytes(b"wrong facsimile")
    with pytest.raises(ValueError, match="facsimile"):
        store.save("fixture1", 1, _payload(store, transcription="Another reading"))


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
    source = review_root / CANONICAL
    data = read_json(source)
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
    validated = read_json(validated_dir / "fixture1.json")
    xml = review_server.annotator.generate_tei("fixture1", validated, {})

    result = prepare_viewer("fixture1", xml, data, review_root)

    viewer = json.loads(result[Path("docs/data/fixture1.json")])
    assert viewer["pages"][0]["image"] == "images/fixture1/local.png"
    assert set(result) == {
        Path("docs/data/fixture1.json"),
        Path("docs/tei/fixture1.xml"),
        Path("docs/data/catalog.json"),
    }


def test_optional_annotations_become_stale(review_root: Path) -> None:
    store = review_server.ReviewStore(review_root)
    source = read_json(review_root / CANONICAL)
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
    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store))
    store.save("fixture1", 1, _payload(store, transcription="Noch eine Lesung"))
    data = read_json(review_root / CANONICAL)

    assert not contract.file_violations(data)
    broken = copy.deepcopy(data)
    broken["pages"][0]["edits"][1]["before"]["transcription"] = "lost"
    assert any(
        "discontinuous" in problem for problem in contract.file_violations(broken)
    )
    tree = etree.parse(str(review_root / "results/tei/fixture1.xml"))
    edits = tree.findall(".//tei:change[@type='transcription-correction']", NS)
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
    point_step6_at(monkeypatch, review_root)
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
    catalog = read_json(review_root / "docs/data/catalog.json")
    assert [entry["id"] for entry in catalog["objects"]] == ["Alpha", "fixture1"]

    store = review_server.ReviewStore(review_root)
    store.save("fixture1", 1, _payload(store, transcription="Zweite Lesung"))
    saved = _snapshot(review_root / "docs/data")

    assert step6.build_all()[0] == []
    assert _snapshot(review_root / "docs/data") == saved


# HTTP interface


@pytest.fixture
def running_server(review_root: Path):
    server = review_server.ReviewServer(review_server.ReviewStore(review_root), 0)
    # A short poll interval keeps shutdown() from waiting half a second.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive(), "review server thread did not stop"


def _request(
    server,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict | None = None,
) -> tuple[int, bytes, http.client.HTTPMessage]:
    # Saves include full schema validation and rebuilding derived assets.
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=60
    )
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read(), response.headers
    finally:
        connection.close()


def _write_headers(server, **extra) -> dict:
    token = json.loads(_request(server, "GET", "/api/session")[1])["token"]
    return {"Content-Type": "application/json", "X-Review-Token": token, **extra}


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
    ids=["foreign-host", "foreign-origin", "cross-site"],
)
def test_foreign_requests_are_forbidden(running_server, headers) -> None:
    assert _request(running_server, "GET", "/api/session", headers=headers)[0] == 403


@pytest.mark.parametrize(
    "path",
    ["/.env", "/%2e%2e/.env", "/../.env", "/data/", "/api/documents/unknown"],
)
def test_private_and_unknown_paths_are_not_found(running_server, path) -> None:
    status, body, _headers = _request(running_server, "GET", path)

    assert status == 404
    assert b"PRIVATE_SENTINEL" not in body


@pytest.mark.parametrize(
    ("path", "headers", "body", "expected"),
    [
        (PAGE_URL, {"Content-Type": "application/json"}, b"{}", 403),
        (PAGE_URL, {"Content-Length": str(review_server.MAX_BODY + 1)}, b"", 413),
        (PAGE_URL, {"Content-Type": "text/plain"}, b"{}", 415),
        ("/api/documents/fixture1/notes/1", {}, b"{}", 404),
        (PAGE_URL, {}, b"{not json", 400),
    ],
    ids=["missing-token", "oversized", "not-json", "unknown-endpoint", "invalid-json"],
)
def test_malformed_writes_are_refused(
    running_server, path, headers, body, expected
) -> None:
    if expected != 403:
        headers = _write_headers(running_server, **headers)

    assert _request(running_server, "POST", path, body, headers)[0] == expected


def test_save_then_conflict_then_no_change(running_server) -> None:
    headers = _write_headers(running_server)
    payload = review_server._json_bytes(_payload(running_server.store))

    assert _request(running_server, "POST", PAGE_URL, payload, headers)[0] == 200
    assert _request(running_server, "POST", PAGE_URL, payload, headers)[0] == 409
    unchanged = review_server._json_bytes(_payload(running_server.store))
    status, body, _headers = _request(
        running_server, "POST", PAGE_URL, unchanged, headers
    )
    assert (status, json.loads(body)) == (400, {"error": "No change to save"})


def test_generated_assets_are_blocked_during_recovery(running_server) -> None:
    marker = running_server.store.marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")

    assert _request(running_server, "GET", "/index.html")[0] == 503
    assert _request(running_server, "HEAD", "/index.html")[0] == 503
    status, body, _headers = _request(running_server, "GET", "/api/session")
    assert status == 200 and not json.loads(body)["writable"]


def test_responses_carry_the_page_content_security_policy(running_server) -> None:
    policy = _request(running_server, "GET", "/index.html")[2][
        "Content-Security-Policy"
    ]

    page = (REPOSITORY_ROOT / "docs/index.html").read_text(encoding="utf-8")
    meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page)
    assert meta is not None
    assert policy == meta.group(1) + "; frame-ancestors 'none'"


def test_static_responses_identify_the_review_service(running_server) -> None:
    # docs/js/review-editor.js calls the API only when this header is present.
    headers = _request(running_server, "GET", "/index.html")[2]

    assert headers["X-Review-Service"] == "local"
