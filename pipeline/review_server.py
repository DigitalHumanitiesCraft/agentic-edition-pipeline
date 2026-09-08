"""Serve the local review UI and persist versioned page corrections.

Run ``uv run python pipeline/review_server.py --port 8080`` from this repo.
The server binds only 127.0.0.1. It stages deterministic steps 4–6 before
publishing, preserves canonical snapshots, and rolls back failed writes.
The human review contract in knowledge/08_DATA_CONTRACT.md stays in force.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import json
import secrets
import stat
import sys
import tempfile
import threading
import uuid
import zipfile
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

import contract
from config import PROJECT_ROOT, VALIDATION_SCHEMA, write_bytes_atomic
from review_state import dependencies
from update_review import update_page_review
from validate_schema import validate_files

MAX_BODY = 2 * 1024 * 1024


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _load_step(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"review_{name}_{uuid.uuid4().hex}", Path(__file__).parent / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pipeline stage {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe_path(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Path must remain inside the repository")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes the repository")
    for component in (target, *target.parents):
        if component.is_symlink() or (
            component.exists()
            and getattr(component.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("Linked paths are not allowed")
        if component == root:
            break
    return target


def prepare_artifacts(root: Path, object_id: str, data: dict) -> dict[Path, bytes]:
    """Run existing offline stages in isolated output directories."""
    validator = _load_step("04_validate")
    annotator = _load_step("05_annotate_tei")
    from review_assets import prepare_viewer

    project = annotator._extract_project_info(
        (root / "knowledge/01_PROJECT.md").read_text(encoding="utf-8")
    )
    existing = _safe_path(root, Path(f"results/tei/{object_id}.xml"))
    if existing.exists():
        validated_path = _safe_path(
            root, Path(f"data/processed/validated/{object_id}.json")
        )
        validated = json.loads(validated_path.read_bytes())
        if contract.validated_file_violations(validated):
            raise ValueError(
                "Existing validated data is invalid; rebuild or review it first"
            )
        expected = annotator.generate_tei(object_id, validated, project).encode("utf-8")
        if existing.read_bytes() != expected:
            raise ValueError(
                "Existing TEI differs from the base generator. Use the project annotation workflow."
            )
    with tempfile.TemporaryDirectory(prefix="edition-review-") as directory:
        stage = Path(directory)
        validator.TRANSCRIPTIONS_DIR = stage / "data/processed/transcriptions"
        validator.VALIDATED_DIR = stage / "data/processed/validated"
        canonical_relative = Path(f"data/processed/transcriptions/{object_id}.json")
        canonical_path = stage / canonical_relative
        canonical_path.parent.mkdir(parents=True)
        write_bytes_atomic(canonical_path, _json_bytes(data))
        error = validator.validate_one(object_id, use_llm=False, force=True)
        if error:
            raise ValueError(error["error"])
        annotator.VALIDATED_DIR = validator.VALIDATED_DIR
        annotator.TEI_DIR = stage / "data/processed/tei"
        annotator.RESULTS_TEI_DIR = stage / "results/tei"
        annotator.RESULTS_REPORTS_DIR = stage / "results/reports"
        error = annotator.annotate_one(
            object_id, project, validate_only=False, force=True
        )
        if error:
            raise ValueError(error["error"])
        tei_path = annotator.RESULTS_TEI_DIR / f"{object_id}.xml"
        results = validate_files(VALIDATION_SCHEMA, [tei_path])
        if not all(result.valid for result in results):
            raise ValueError("Generated TEI failed RelaxNG validation")
        artifacts = {
            path.relative_to(stage): path.read_bytes()
            for path in stage.rglob("*")
            if path.is_file()
        }
        artifacts.update(
            prepare_viewer(object_id, tei_path.read_text(encoding="utf-8"), data, root)
        )
        return artifacts


class ReviewStore:
    """Keep session credentials and serialize repository transactions."""

    def __init__(self, root: Path, builder=prepare_artifacts) -> None:
        self.root = root.resolve()
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.builder = builder
        catalog = json.loads(
            _safe_path(self.root, Path("docs/data/catalog.json")).read_text(
                encoding="utf-8"
            )
        )
        ids = [item["id"] for item in catalog["objects"]]
        problems = contract.unique_object_id_violations(ids)
        if problems:
            raise ValueError("Invalid catalog identifiers: " + "; ".join(problems))
        self.object_ids = frozenset(ids)
        self.marker = _safe_path(self.root, Path("results/review-backups/pending.json"))

    def _canonical_path(self, object_id: str) -> Path:
        if object_id not in self.object_ids or not contract.valid_object_id(object_id):
            raise FileNotFoundError("Unknown document")
        return _safe_path(
            self.root, Path(f"data/processed/transcriptions/{object_id}.json")
        )

    def document(self, object_id: str) -> dict:
        with self.lock:
            raw = self._canonical_path(object_id).read_bytes()
            data = json.loads(raw)
            problems = contract.file_violations(data)
            if problems or data.get("object_id") != object_id:
                raise ValueError("Invalid canonical transcription")
            return {
                "id": object_id,
                "title": data.get("metadata", {}).get("title", object_id),
                "version": hashlib.sha256(raw).hexdigest(),
                "pages": copy.deepcopy(data["pages"]),
                "origin": copy.deepcopy(data.get("_meta", {})),
                "dependencies": dependencies(self.root, object_id, data),
                "proposals": self.proposals(object_id),
                "writable": not self.marker.exists(),
            }

    def proposals(self, object_id: str) -> list[dict]:
        directory = _safe_path(self.root, Path(f"data/review-proposals/{object_id}"))
        return [
            json.loads(_safe_path(self.root, path.relative_to(self.root)).read_bytes())
            for path in sorted(directory.glob("*.json"))
        ]

    def recover(self) -> None:
        """Restore the interrupted transaction's snapshot, then unlock writes."""
        with self.lock:
            marker = json.loads(self.marker.read_bytes())
            backup = _safe_path(self.root, Path(marker["backup"]))
            if not backup.is_relative_to(self.root / "results/review-backups"):
                raise ValueError("Invalid recovery snapshot path")
            raw = backup.read_bytes()
            if hashlib.sha256(raw).hexdigest() != marker["sha256"]:
                raise ValueError("Recovery snapshot hash mismatch")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                entries = {
                    _safe_path(self.root, Path(name)): archive.read(name)
                    for name in archive.namelist()
                    if name != "manifest.json"
                }
                absent = [
                    _safe_path(self.root, Path(name)) for name in manifest["absent"]
                ]
            allowed = (
                "data/processed/",
                "results/tei/",
                "results/reports/",
                "docs/data/",
                "docs/tei/",
                "docs/txt/",
            )
            for target in [*entries, *absent]:
                if not target.relative_to(self.root).as_posix().startswith(allowed):
                    raise ValueError("Recovery target outside generated artifacts")
            for target, content in entries.items():
                write_bytes_atomic(target, content)
            for target in absent:
                target.unlink(missing_ok=True)
            self.marker.unlink()

    def save(
        self, object_id: str, number: int, request: dict, *, proposal: bool = False
    ) -> dict:
        if not isinstance(request, dict):
            raise ValueError("Expected a JSON object")
        required = ("version", "transcription", "notes", "actor", "note")
        if any(not isinstance(request.get(field), str) for field in required):
            raise ValueError(
                "version, transcription, notes, actor and note must be strings"
            )
        if set(request) - {*required, "actor_kind"}:
            raise ValueError("Unexpected update fields")
        actor_kind = request.get("actor_kind", "human")
        if actor_kind not in {"human", "agent"} or not request["actor"].strip():
            raise ValueError("An actor and actor_kind human or agent are required")
        if not request["note"].strip():
            raise ValueError("A reason for the correction is required")
        if len(request["actor"]) > 200 or len(request["note"]) > 10000:
            raise ValueError("Actor or change note exceeds the limit")
        with self.lock:
            if self.marker.exists():
                raise ValueError(
                    "Interrupted transaction: run --recover before editing"
                )
            canonical_path = self._canonical_path(object_id)
            raw = canonical_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != request["version"]:
                raise FileExistsError("Document changed; reload before saving")
            data = json.loads(raw)
            if contract.file_violations(data):
                raise ValueError("Invalid canonical transcription")
            page = next(
                (page for page in data["pages"] if page["page"] == number), None
            )
            if page is None:
                raise FileNotFoundError("Unknown page")
            before = {
                "transcription": page["transcription"],
                "notes": page.get("notes", ""),
            }
            after = {key: request[key] for key in before}
            if before == after:
                return self.document(object_id)
            timestamp = datetime.now(UTC).isoformat()
            if proposal:
                record = {
                    "_meta": {"script": "review_server.py", "timestamp": timestamp},
                    **request,
                    "actor_kind": actor_kind,
                    "id": uuid.uuid4().hex,
                    "page": number,
                    "timestamp": timestamp,
                }
                destination = _safe_path(
                    self.root,
                    Path(f"data/review-proposals/{object_id}/{record['id']}.json"),
                )
                write_bytes_atomic(destination, _json_bytes(record))
                return self.document(object_id)
            if page.get("foreign_paragraphs"):
                raise ValueError(
                    "Paragraph-index annotations require the project annotation workflow"
                )
            if page["review"]["status"] != "in_review":
                data = update_page_review(
                    data,
                    number,
                    "in_review",
                    request["actor"],
                    request["note"],
                    timestamp,
                )
                page = next(page for page in data["pages"] if page["page"] == number)
                page["review"]["history"][-1]["actor_kind"] = actor_kind
            page.update(after)
            page.setdefault("edits", []).append(
                {
                    "id": str(uuid.uuid4()),
                    "actor": request["actor"].strip(),
                    "actor_kind": actor_kind,
                    "timestamp": timestamp,
                    "note": request["note"],
                    "before": before,
                    "after": after,
                }
            )
            if "quality_signals" in data:
                quality = _load_step("03_transcribe").compute_quality_signals(
                    data, len(data["pages"])
                )
                quality["needs_review"] = True
                data["quality_signals"] = quality
            problems = contract.file_violations(data)
            if problems:
                raise ValueError(
                    "Edited transcription violates contract: " + "; ".join(problems)
                )
            artifacts = self.builder(self.root, object_id, data)
            canonical_relative = canonical_path.relative_to(self.root)
            if artifacts.get(canonical_relative) != _json_bytes(data):
                raise ValueError("Builder did not preserve the canonical edited state")
            targets = {
                _safe_path(self.root, relative): content
                for relative, content in artifacts.items()
            }
            previous = {
                path: path.read_bytes() if path.exists() else None for path in targets
            }
            if canonical_path.read_bytes() != raw:
                raise FileExistsError(
                    "Document changed during validation; reload before saving"
                )
            backup = _safe_path(
                self.root,
                Path("results/review-backups")
                / object_id
                / f"{uuid.uuid4().hex[:16]}.zip",
            )
            snapshot = io.BytesIO()
            with zipfile.ZipFile(
                snapshot, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for path, content in previous.items():
                    if content is not None:
                        archive.writestr(
                            path.relative_to(self.root).as_posix(), content
                        )
                archive.writestr(
                    "manifest.json",
                    _json_bytes(
                        {
                            "timestamp": timestamp,
                            "actor": request["actor"],
                            "actor_kind": actor_kind,
                            "previous_version": request["version"],
                            "absent": [
                                str(path.relative_to(self.root))
                                for path, content in previous.items()
                                if content is None
                            ],
                        }
                    ),
                )
            write_bytes_atomic(backup, snapshot.getvalue())
            write_bytes_atomic(
                self.marker,
                _json_bytes(
                    {
                        "backup": backup.relative_to(self.root).as_posix(),
                        "sha256": hashlib.sha256(snapshot.getvalue()).hexdigest(),
                    }
                ),
            )
            written = []
            try:
                for path, content in targets.items():
                    write_bytes_atomic(path, content)
                    written.append(path)
            except Exception as error:
                rollback_errors = []
                for path in reversed(written):
                    try:
                        content = previous[path]
                        if content is None:
                            path.unlink(missing_ok=True)
                        else:
                            write_bytes_atomic(path, content)
                    except OSError as rollback_error:
                        rollback_errors.append(str(rollback_error))
                if rollback_errors:
                    raise RuntimeError(
                        f"Rollback incomplete; recover from {backup}: "
                        + "; ".join(rollback_errors)
                    ) from error
                self.marker.unlink()
                raise
            self.marker.unlink()
            return self.document(object_id)


class ReviewHandler(SimpleHTTPRequestHandler):
    """Expose only docs assets and the guarded local editing API."""

    def __init__(self, request, client_address, server) -> None:
        super().__init__(
            request, client_address, server, directory=str(server.store.root / "docs")
        )

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        super().end_headers()

    def _json(self, status: int, data: dict) -> None:
        body = _json_bytes(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _trusted(self, write: bool = False) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if (
            len(self.headers.get_all("Host", [])) != 1
            or host not in allowed
            or (origin is not None and origin != f"http://{host}")
        ):
            self._json(403, {"error": "Host or Origin is not this local review server"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._json(403, {"error": "Cross-site requests are not allowed"})
            return False
        if write and not secrets.compare_digest(
            self.headers.get("X-Review-Token", "").encode("utf-8"),
            self.server.store.token.encode("utf-8"),
        ):
            self._json(403, {"error": "Invalid review token"})
            return False
        return True

    def _route(self) -> list[str]:
        return unquote(urlsplit(self.path).path).strip("/").split("/")

    def do_GET(self) -> None:
        if not self._trusted():
            return
        route = self._route()
        try:
            if route == ["api", "session"]:
                self._json(
                    200,
                    {
                        "writable": not self.server.store.marker.exists(),
                        "token": self.server.store.token,
                    },
                )
            elif len(route) == 3 and route[:2] == ["api", "documents"]:
                self._json(200, self.server.store.document(route[2]))
            elif route[0] == "api":
                self._json(404, {"error": "Unknown endpoint"})
            else:
                with self.server.store.lock:
                    if self.server.store.marker.exists():
                        self._json(
                            503,
                            {
                                "error": "Interrupted transaction: recover before reading generated assets"
                            },
                        )
                        return
                    self._check_static()
                    super().do_GET()
        except FileNotFoundError:
            self._json(404, {"error": "Unknown document or asset"})
        except (OSError, ValueError):
            self._json(400, {"error": "Invalid document or asset"})

    def _check_static(self) -> None:
        route = self._route()
        if any(part.startswith(".") or ":" in part or "\\" in part for part in route):
            raise FileNotFoundError("Private asset")
        _safe_path(self.server.store.root / "docs", Path(*route))

    def do_HEAD(self) -> None:
        if not self._trusted():
            return
        try:
            with self.server.store.lock:
                if self.server.store.marker.exists():
                    self.send_error(503)
                    return
                self._check_static()
                super().do_HEAD()
        except (OSError, ValueError):
            self.send_error(404)

    def list_directory(self, path: str):
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def do_POST(self) -> None:
        if not self._trusted(write=True):
            return
        route = self._route()
        if (
            len(route) != 5
            or route[:2] != ["api", "documents"]
            or route[3] not in {"pages", "proposals"}
            or not route[4].isdigit()
        ):
            self._json(404, {"error": "Unknown endpoint"})
            return
        if self.headers.get_content_type() != "application/json" or self.headers.get(
            "Transfer-Encoding"
        ):
            self._json(415, {"error": "Expected application/json with Content-Length"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self._json(413, {"error": "Request exceeds size limit or is empty"})
                return
            request = json.loads(self.rfile.read(length))
            result = self.server.store.save(
                route[2], int(route[4]), request, proposal=route[3] == "proposals"
            )
        except FileExistsError as exc:
            self._json(409, {"error": str(exc)})
        except FileNotFoundError:
            self._json(404, {"error": "Unknown document or page"})
        except (ValueError, UnicodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(
                500,
                {
                    "error": "Save failed. Inspect server and recovery snapshots before retrying."
                },
            )
        else:
            self._json(200, result)


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, store: ReviewStore, port: int = 8080) -> None:
        self.store = store
        super().__init__(("127.0.0.1", port), ReviewHandler)

    def get_request(self) -> tuple:
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


@contextmanager
def repository_writer(root: Path):
    """Keep server and recovery CLI mutually exclusive across processes."""
    path = _safe_path(root.resolve(), Path("results/review-backups/writer.lock"))
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
                    "Another review server or recovery owns this repository"
                ) from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError(
                    "Another review server or recovery owns this repository"
                ) from None
        yield


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the local edition editor with repository persistence."
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Restore an interrupted transaction and exit",
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with repository_writer(PROJECT_ROOT):
        if args.recover:
            ReviewStore(PROJECT_ROOT).recover()
            print("Interrupted transaction restored. Restart the review server.")
            return
        with ReviewServer(ReviewStore(PROJECT_ROOT), args.port) as server:
            print(
                f"Review editor: http://127.0.0.1:{server.server_address[1]}",
                flush=True,
            )
            with suppress(KeyboardInterrupt):
                server.serve_forever()


if __name__ == "__main__":
    main()
