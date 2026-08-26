"""Integration and target-ownership checks for the offline quickstart."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from lxml import etree

REPOSITORY_ROOT = Path(__file__).parent.parent
RUNNER_PATH = REPOSITORY_ROOT / "examples" / "offline-quickstart" / "run.py"
EXPECTED_IDS = ["example-letter-001", "example-note-002"]

spec = importlib.util.spec_from_file_location("offline_quickstart", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


def _block_sockets_in_subprocesses(tmp_path: Path) -> dict[str, str]:
    blocker = tmp_path / "socket-blocker"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(
        """import socket

def _blocked(*_args, **_kwargs):
    raise RuntimeError("network access blocked by offline quickstart test")

socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    for name in runner.OFFLINE_ENVIRONMENT:
        environment[name] = "must-be-cleared"
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(blocker) + (
        os.pathsep + existing_pythonpath if existing_pythonpath else ""
    )
    return environment


def _stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner,
        "_copy_runtime",
        lambda target: (target / "runtime-copied").write_text("ok", encoding="utf-8"),
    )
    monkeypatch.setattr(runner, "_run_pipeline", lambda _target: None)
    monkeypatch.setattr(runner, "_verify_outputs", lambda _target: {"objects": []})


def _fixture(object_id: str) -> dict:
    return json.loads(
        (RUNNER_PATH.parent / "corpus" / f"{object_id}.json").read_text(
            encoding="utf-8"
        )
    )


def _http_get(server: ThreadingHTTPServer, path: str) -> bytes:
    host, port = server.server_address
    with urllib.request.urlopen(f"http://{host}:{port}/{path}", timeout=5) as response:
        assert response.status == 200
        return response.read()


def test_offline_quickstart_builds_verified_frontend_in_fresh_process(
    tmp_path: Path,
) -> None:
    target = tmp_path / "quickstart-project"
    completed = subprocess.run(
        (sys.executable, str(RUNNER_PATH), "--target", str(target)),
        cwd=REPOSITORY_ROOT,
        env=_block_sockets_in_subprocesses(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((target / "quickstart-report.json").read_text(encoding="utf-8"))
    assert report["objects"] == EXPECTED_IDS
    assert report["network_used"] is False
    assert report["validation_schema"] == "schemas/tei_all.rng"
    assert report["ownership_sentinel"] == runner.OWNERSHIP_SENTINEL
    assert all(report["checks"].values())
    assert runner._has_valid_ownership_marker(target)

    catalog = json.loads(
        (target / "docs" / "data" / "catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["project"] == "Offline Quickstart Edition"
    assert [item["id"] for item in catalog["objects"]] == EXPECTED_IDS
    assert all(item["has_images"] is False for item in catalog["objects"])

    catalog_by_id = {item["id"]: item for item in catalog["objects"]}
    namespace = {"tei": "http://www.tei-c.org/ns/1.0"}
    for object_id in EXPECTED_IDS:
        fixture = _fixture(object_id)
        expected_metadata = fixture["metadata"]
        validated = json.loads(
            (
                target / "data" / "processed" / "validated" / f"{object_id}.json"
            ).read_text(encoding="utf-8")
        )
        assert validated["metadata"] == expected_metadata
        assert validated["pages"] == fixture["pages"]

        tei_path = target / "results" / "tei" / f"{object_id}.xml"
        root = etree.parse(str(tei_path))
        assert root.find(".//tei:body", namespace) is not None
        assert (
            root.findtext(".//tei:publicationStmt/tei:publisher", namespaces=namespace)
            == "Digital Humanities Craft"
        )
        assert root.findtext(".//tei:repository", namespaces=namespace) == (
            "Synthetic example corpus"
        )
        date = root.find(".//tei:origDate", namespace)
        assert date is not None
        assert date.get("when") == expected_metadata["date"]
        assert "[TODO]" not in tei_path.read_text(encoding="utf-8")

        validation = json.loads(
            (target / "results" / "reports" / f"{object_id}_validation.json").read_text(
                encoding="utf-8"
            )
        )
        assert validation["well_formed"]
        assert validation["required_elements"]
        assert validation["plaintext_similarity"] == 1.0

        frontend = json.loads(
            (target / "docs" / "data" / f"{object_id}.json").read_text(encoding="utf-8")
        )
        assert frontend["title"] == expected_metadata["title"]
        assert frontend["date"] == expected_metadata["date"]
        assert frontend["language"] == expected_metadata["language"]
        assert [page["text"] for page in frontend["pages"]] == [
            page["transcription"] for page in fixture["pages"]
        ]

        catalog_item = catalog_by_id[object_id]
        assert catalog_item["title"] == expected_metadata["title"]
        assert catalog_item["date"] == expected_metadata["date"]
        assert catalog_item["language"] == expected_metadata["language"]
        search_basis = " ".join(
            catalog_item[field] for field in ("title", "date", "language")
        ).lower()
        assert expected_metadata["title"].lower() in search_basis
        assert expected_metadata["date"] in search_basis
        assert expected_metadata["language"] in search_basis

    handler = partial(_QuietHandler, directory=str(target / "docs"))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert b"Offline Quickstart Edition" in _http_get(
                server, "data/catalog.json"
            )
            app_js = _http_get(server, "js/app.js").decode("utf-8")
            assert 'a.href = "tei/" + encodeURIComponent(id) + ".xml"' in app_js
            assert "r.textContent.toLowerCase().indexOf(q)" in app_js
            for object_id in EXPECTED_IDS:
                downloaded = _http_get(server, f"tei/{object_id}.xml")
                assert (
                    downloaded
                    == (target / "results" / "tei" / f"{object_id}.xml").read_bytes()
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_force_rejects_external_foreign_directory(tmp_path: Path) -> None:
    target = tmp_path / "foreign-directory"
    target.mkdir()
    protected = target / "keep.txt"
    protected.write_text("foreign", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty unowned target"):
        runner.build(target, force=True)

    assert protected.read_text(encoding="utf-8") == "foreign"
    assert not (target / runner.OWNERSHIP_SENTINEL).exists()


def test_force_rejects_nonempty_unmarked_quickstart_shaped_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "unmarked"
    (target / "docs" / "data").mkdir(parents=True)
    protected = target / "docs" / "data" / "catalog.json"
    protected.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty unowned target"):
        runner.build(target, force=True)

    assert protected.read_text(encoding="utf-8") == "{}"


def test_force_replaces_marked_quickstart_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_pipeline(monkeypatch)
    target = tmp_path / "owned"
    target.mkdir()
    runner._write_ownership_marker(target)
    old_file = target / "old-output.txt"
    old_file.write_text("replaceable", encoding="utf-8")

    runner.build(target, force=True)

    assert not old_file.exists()
    assert (target / "runtime-copied").read_text(encoding="utf-8") == "ok"
    assert runner._has_valid_ownership_marker(target)


def test_force_rejects_canonical_default_without_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / ".aep-quickstart"
    monkeypatch.setattr(runner, "DEFAULT_TARGET", target)
    target.mkdir()
    protected = target / "foreign-at-canonical-target.txt"
    protected.write_text("must remain", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty unowned target"):
        runner.build(target, force=True)

    assert protected.read_text(encoding="utf-8") == "must remain"
    assert not (target / runner.OWNERSHIP_SENTINEL).exists()


def test_force_replaces_marked_canonical_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_pipeline(monkeypatch)
    target = tmp_path / ".aep-quickstart"
    monkeypatch.setattr(runner, "DEFAULT_TARGET", target)
    target.mkdir()
    runner._write_ownership_marker(target)
    old_file = target / "old-output.txt"
    old_file.write_text("runner-owned", encoding="utf-8")

    runner.build(target, force=True)

    assert not old_file.exists()
    assert runner._has_valid_ownership_marker(target)


def test_target_reparse_check_runs_before_path_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "linked-target"
    reparse_component = tmp_path / "junction"
    monkeypatch.setattr(
        runner, "_find_reparse_component", lambda _target: reparse_component
    )

    def unexpected_resolve(_path: Path, *_args: object, **_kwargs: object) -> Path:
        raise AssertionError("Path.resolve() must not run before the reparse check")

    monkeypatch.setattr(runner.Path, "resolve", unexpected_resolve)

    with pytest.raises(ValueError, match="symlink or reparse point"):
        runner._validated_target(target)


def test_target_validation_rejects_real_symbolic_link(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "linked-target"
    try:
        link.symlink_to(destination, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        runner._validated_target(link)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "foreign-owner"),
        ("sentinel_version", 999),
        ("target", "C:/different/target"),
    ],
)
def test_force_rejects_manipulated_ownership_sentinel(
    field: str, value: object, tmp_path: Path
) -> None:
    target = tmp_path / f"manipulated-{field}"
    target.mkdir()
    payload = runner._ownership_payload(target)
    payload[field] = value
    (target / runner.OWNERSHIP_SENTINEL).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    protected = target / "keep.txt"
    protected.write_text("protected", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty unowned target"):
        runner.build(target, force=True)

    assert protected.read_text(encoding="utf-8") == "protected"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("script", "different-runner.py"),
        ("timestamp", "not-a-timestamp"),
        ("timestamp", "2026-08-26T12:00:00"),
    ],
)
def test_force_rejects_sentinel_with_manipulated_provenance(
    field: str, value: str, tmp_path: Path
) -> None:
    target = tmp_path / f"manipulated-provenance-{field}-{len(value)}"
    target.mkdir()
    payload = runner._ownership_payload(target)
    payload["_meta"][field] = value
    (target / runner.OWNERSHIP_SENTINEL).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    protected = target / "keep.txt"
    protected.write_text("protected", encoding="utf-8")

    with pytest.raises(ValueError, match="non-empty unowned target"):
        runner.build(target, force=True)

    assert protected.read_text(encoding="utf-8") == "protected"


def test_existing_empty_external_target_is_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_pipeline(monkeypatch)
    target = tmp_path / "empty"
    target.mkdir()

    runner.build(target)

    assert (target / "runtime-copied").read_text(encoding="utf-8") == "ok"
    assert runner._has_valid_ownership_marker(target)


def test_pipeline_processes_receive_cleared_provider_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[dict[str, str]] = []

    def capture_run(*_args: object, **kwargs: object) -> None:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        received.append(environment)

    for name in runner.OFFLINE_ENVIRONMENT:
        monkeypatch.setenv(name, "secret-or-provider")
    monkeypatch.setattr(runner.subprocess, "run", capture_run)

    runner._run_pipeline(tmp_path)

    assert len(received) == len(runner.PIPELINE_STEPS)
    for environment in received:
        assert all(environment[name] == "" for name in runner.OFFLINE_ENVIRONMENT)


def test_schema_step_names_explicit_reported_schema() -> None:
    schema_step = next(
        step for step in runner.PIPELINE_STEPS if step.label == "RelaxNG validation"
    )
    assert schema_step.arguments == (
        "pipeline/validate_schema.py",
        "--schema",
        runner.VALIDATION_SCHEMA,
    )
