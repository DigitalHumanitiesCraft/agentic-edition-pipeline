"""Integration and target-ownership checks for the offline quickstart."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from lxml import etree

from conftest import NS, render_frontend

REPOSITORY_ROOT = Path(__file__).parent.parent
RUNNER_PATH = REPOSITORY_ROOT / "examples" / "offline-quickstart" / "run.py"
EXPECTED_IDS = ["example-letter-001", "example-note-002"]
OPERATOR_DOCUMENTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "SETUP.md",
    "reference/pipeline.md",
    "reference/evaluation.md",
    "reference/data-contract.md",
    "reference/tei-mapping.md",
    "reference/local-review.md",
    "reference/provider-records.md",
    "knowledge/00_INDEX.md",
    "knowledge/decisions.md",
    "knowledge/journal.md",
    "knowledge/handoff.md",
    "knowledge/template/overview.md",
    "knowledge/template/lineage.md",
)

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
    monkeypatch.setattr(runner, "_run_pipeline", lambda _target, _environment: {})
    monkeypatch.setattr(
        runner, "_verify_outputs", lambda _target, _status, _env: {"objects": []}
    )


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


def _assert_operator_document_links(root: Path) -> None:
    # Knowledge documents link each other by Obsidian wikilink, which
    # resolves by file name anywhere below knowledge/.
    knowledge_names = {path.stem for path in (root / "knowledge").rglob("*.md")}
    for name in OPERATOR_DOCUMENTS:
        path = root / name
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            linked = path.parent / target.split("#", 1)[0]
            assert linked.exists(), f"{name} links to missing {target}"
        for target in re.findall(r"\[\[([^\]|#]+)", text):
            assert target in knowledge_names, f"{name} links to missing [[{target}]]"


def test_operator_document_links_resolve_in_repository() -> None:
    _assert_operator_document_links(REPOSITORY_ROOT)


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
        timeout=600,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((target / "quickstart-report.json").read_text(encoding="utf-8"))
    assert report["objects"] == EXPECTED_IDS
    assert report["network_used"] is False
    assert report["validation_schema"] == "schemas/tei_all.rng"
    assert report["evaluation_manifest"] == runner.EVALUATION_MANIFEST
    assert report["ownership_sentinel"] == runner.OWNERSHIP_SENTINEL
    assert report["exit_status"] == {step.label: 0 for step in runner.PIPELINE_STEPS}
    assert all(report["checks"].values())
    evaluation = json.loads(
        (target / "results" / "evaluation" / "results.json").read_text(encoding="utf-8")
    )
    assert evaluation["errors"] == []
    assert {r["fixture_id"] for r in evaluation["results"]} >= {"text-pair", "good-tei"}
    assert runner._has_valid_ownership_marker(target)

    for name in OPERATOR_DOCUMENTS:
        assert (target / name).read_bytes() == (REPOSITORY_ROOT / name).read_bytes()
    _assert_operator_document_links(target)
    assert (target / "aep_eval" / "__main__.py").is_file()
    assert (target / "tests" / "fixtures" / "evaluation" / "manifest.json").is_file()
    assert (target / "examples" / "offline-quickstart" / "run.py").is_file()
    assert not (target / ".env").exists()

    catalog = json.loads(
        (target / "docs" / "data" / "catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["project"] == "Offline Quickstart Edition"
    assert [item["id"] for item in catalog["objects"]] == EXPECTED_IDS
    assert all(item["has_images"] is False for item in catalog["objects"])

    catalog_by_id = {item["id"]: item for item in catalog["objects"]}
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
        assert root.find(".//tei:body", NS) is not None
        assert (
            root.findtext(".//tei:publicationStmt/tei:publisher", namespaces=NS)
            == "Digital Humanities Craft"
        )
        assert root.findtext(".//tei:repository", namespaces=NS) == (
            "Synthetic example corpus"
        )
        date = root.find(".//tei:origDate", NS)
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

    # The copied frontend renders the built catalog, filters it regardless of
    # letter case and links the viewer to the TEI download served below.
    titles = [catalog_by_id[object_id]["title"] for object_id in EXPECTED_IDS]
    shown = render_frontend(
        target / "docs" / "js" / "app.js",
        target / "docs",
        query=titles[1].upper(),
        viewer=EXPECTED_IDS[0],
    )
    assert [row[0] for row in shown["rows"]] == titles
    assert shown["visible"] == [titles[1]]
    assert shown["title"] == titles[0]
    download = next(link for link in shown["links"] if link["download"])

    handler = partial(_QuietHandler, directory=str(target / "docs"))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert b"Offline Quickstart Edition" in _http_get(
                server, "data/catalog.json"
            )
            assert (
                _http_get(server, download["href"])
                == (target / "results" / "tei" / f"{EXPECTED_IDS[0]}.xml").read_bytes()
            )
            for object_id in EXPECTED_IDS:
                downloaded = _http_get(server, f"tei/{object_id}.xml")
                assert (
                    downloaded
                    == (target / "results" / "tei" / f"{object_id}.xml").read_bytes()
                )
        finally:
            server.shutdown()
            thread.join(timeout=5)


def _files(target: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}


def _sentinel(**changes):
    """Write a runner sentinel whose payload differs by changes."""

    def write(target: Path) -> None:
        payload = runner._ownership_payload(target)
        for field, value in changes.items():
            if field in payload["_meta"]:
                payload["_meta"][field] = value
            else:
                payload[field] = value
        (target / runner.OWNERSHIP_SENTINEL).write_text(
            json.dumps(payload), encoding="utf-8"
        )

    return write


def _quickstart_shaped(target: Path) -> None:
    (target / "docs" / "data").mkdir(parents=True)
    (target / "docs" / "data" / "catalog.json").write_text("{}", encoding="utf-8")


UNOWNED_TARGETS = {
    "foreign-directory": None,
    "quickstart-shaped": _quickstart_shaped,
    "foreign-owner": _sentinel(owner="foreign-owner"),
    "future-version": _sentinel(sentinel_version=999),
    "other-target": _sentinel(target="C:/different/target"),
    "other-script": _sentinel(script="different-runner.py"),
    "invalid-timestamp": _sentinel(timestamp="not-a-timestamp"),
    "naive-timestamp": _sentinel(timestamp="2026-08-26T12:00:00"),
}


@pytest.mark.parametrize("canonical", [False, True], ids=["external", "canonical"])
@pytest.mark.parametrize("operation", ["build", "clean"])
@pytest.mark.parametrize(
    "prepare", list(UNOWNED_TARGETS.values()), ids=list(UNOWNED_TARGETS)
)
def test_nonempty_unowned_target_is_never_replaced_or_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prepare,
    operation: str,
    canonical: bool,
) -> None:
    target = tmp_path / ".aep-quickstart"
    if canonical:
        monkeypatch.setattr(runner, "DEFAULT_TARGET", target)
    target.mkdir()
    if prepare is not None:
        prepare(target)
    (target / "keep.txt").write_text("foreign", encoding="utf-8")
    before = _files(target)

    with pytest.raises(ValueError, match="non-empty unowned target"):
        if operation == "build":
            runner.build(target, force=True)
        else:
            runner.clean(target)

    assert _files(target) == before


@pytest.mark.parametrize("canonical", [False, True], ids=["external", "canonical"])
def test_force_replaces_a_marked_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, canonical: bool
) -> None:
    _stub_pipeline(monkeypatch)
    target = tmp_path / ".aep-quickstart"
    if canonical:
        monkeypatch.setattr(runner, "DEFAULT_TARGET", target)
    target.mkdir()
    runner._write_ownership_marker(target)
    old_file = target / "old-output.txt"
    old_file.write_text("replaceable", encoding="utf-8")

    runner.build(target, force=True)

    assert not old_file.exists()
    assert (target / "runtime-copied").read_text(encoding="utf-8") == "ok"
    assert runner._has_valid_ownership_marker(target)


def test_clean_removes_only_a_runner_owned_target(tmp_path: Path) -> None:
    target = tmp_path / "owned"
    target.mkdir()
    runner._write_ownership_marker(target)
    (target / "generated.txt").write_text("generated", encoding="utf-8")

    assert runner.clean(target) is True

    assert not target.exists()
    assert runner.clean(target) is False


@pytest.mark.parametrize("through", ["link", "linked-parent"])
def test_target_through_a_directory_link_is_refused(
    tmp_path: Path, directory_link, through: str
) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    link = directory_link(tmp_path / "linked", destination)
    target = link if through == "link" else link / "quickstart"

    with pytest.raises(ValueError, match="symlink or reparse point"):
        runner.build(target, force=True)
    with pytest.raises(ValueError, match="symlink or reparse point"):
        runner.clean(target)

    assert list(destination.iterdir()) == []


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

    def capture_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        received.append(environment)
        return subprocess.CompletedProcess(command, 0)

    for name in runner.OFFLINE_ENVIRONMENT:
        monkeypatch.setenv(name, "secret-or-provider")
    monkeypatch.setattr(runner.subprocess, "run", capture_run)

    runner._run_pipeline(tmp_path, runner._offline_environment())

    assert len(received) == len(runner.PIPELINE_STEPS)
    for environment in received:
        assert all(environment[name] == "" for name in runner.OFFLINE_ENVIRONMENT)


def test_failed_check_steps_and_provider_settings_fail_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failing = {"RelaxNG validation", "evaluation fixtures"}

    def fake_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess:
        label = next(
            step.label
            for step in runner.PIPELINE_STEPS
            if command[1:] == step.arguments
        )
        return subprocess.CompletedProcess(command, 1 if label in failing else 0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    exit_status = runner._run_pipeline(tmp_path, {})
    assert exit_status == {
        step.label: 1 if step.label in failing else 0 for step in runner.PIPELINE_STEPS
    }

    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "docs" / "data" / "catalog.json").write_text(
        json.dumps({"objects": [{"id": object_id} for object_id in EXPECTED_IDS]}),
        encoding="utf-8",
    )
    leaked = dict.fromkeys(runner.OFFLINE_ENVIRONMENT, "")
    leaked["OPENAI_API_KEY"] = "secret-or-provider"
    with pytest.raises(RuntimeError) as failure:
        runner._verify_outputs(tmp_path, exit_status, leaked)
    for check in (
        "schema_valid",
        "evaluation_fixtures",
        "offline_provider_environment",
    ):
        assert check in str(failure.value)


def test_schema_step_names_explicit_reported_schema() -> None:
    schema_step = next(
        step for step in runner.PIPELINE_STEPS if step.label == "RelaxNG validation"
    )
    assert schema_step.arguments == (
        "pipeline/validate_schema.py",
        "--schema",
        runner.VALIDATION_SCHEMA,
    )
