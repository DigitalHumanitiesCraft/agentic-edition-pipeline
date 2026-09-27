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
import importlib
import io
import json
import secrets
import sys
import tempfile
import threading
import uuid
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import contract
from config import (
    PROJECT_ROOT,
    VALIDATION_SCHEMA,
    ItemFailure,
    configure_console,
    json_bytes,
    project_info,
    safe_path,
    write_bytes_atomic,
)
from review_assets import prepare_viewer
from review_state import BACKUP_DIR, PENDING_MARKER, dependencies, repository_writer
from update_review import update_page_review
from validate_schema import validate_files

validator = importlib.import_module("04_validate")
annotator = importlib.import_module("05_annotate_tei")

MAX_BODY = 2 * 1024 * 1024
# Far above one manuscript page and far below MAX_BODY, so an oversized
# field gets a precise 400 instead of an opaque contract failure.
MAX_TEXT_CHARS = 200_000
MAX_NOTE_CHARS = 10_000
MAX_ACTOR_CHARS = 200
# The only targets recovery may restore or remove; a snapshot naming any
# other path is refused.
RECOVERABLE_PREFIXES = (
    "data/processed/",
    "results/tei/",
    "results/reports/",
    "docs/data/",
    "docs/tei/",
)
# The meta CSP of docs/index.html, plus frame-ancestors, which only takes
# effect as a header.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' http: https:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _json_bytes(value: object) -> bytes:
    return json_bytes(value)


def prepare_artifacts(root: Path, object_id: str, data: dict) -> dict[Path, bytes]:
    """Run steps 4 to 6 without model calls on a staged copy of one document."""
    try:
        return _prepare_artifacts(root, object_id, data)
    except ItemFailure as failure:
        raise ValueError(failure.message) from failure


def _prepare_artifacts(root: Path, object_id: str, data: dict) -> dict[Path, bytes]:
    project = project_info(root / "knowledge/01_PROJECT.md")
    existing = safe_path(root, Path(f"results/tei/{object_id}.xml"))
    if existing.exists():
        validated_path = safe_path(
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
        transcriptions_dir = stage / "data/processed/transcriptions"
        validated_dir = stage / "data/processed/validated"
        tei_dir = stage / "results/tei"
        transcriptions_dir.mkdir(parents=True)
        write_bytes_atomic(transcriptions_dir / f"{object_id}.json", _json_bytes(data))
        validator.validate_one(
            object_id,
            None,
            True,
            transcriptions_dir=transcriptions_dir,
            validated_dir=validated_dir,
            calls_dir=stage / "data/processed/llm-calls",
        )
        annotator.annotate_one(
            object_id,
            project,
            validate_only=False,
            force=True,
            validated_dir=validated_dir,
            tei_dir=tei_dir,
            reports_dir=stage / "results/reports",
        )
        tei_path = tei_dir / f"{object_id}.xml"
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
            safe_path(self.root, Path("docs/data/catalog.json")).read_text(
                encoding="utf-8"
            )
        )
        ids = [item["id"] for item in catalog["objects"]]
        problems = contract.unique_object_id_violations(ids)
        if problems:
            raise ValueError("Invalid catalog identifiers: " + "; ".join(problems))
        self.object_ids = frozenset(ids)
        self.marker = safe_path(self.root, PENDING_MARKER)

    def _canonical_path(self, object_id: str) -> Path:
        if object_id not in self.object_ids or not contract.valid_object_id(object_id):
            raise FileNotFoundError("Unknown document")
        return safe_path(
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
        """Read stored proposals; an unreadable one is reported, not fatal."""
        directory = safe_path(self.root, Path(f"data/review-proposals/{object_id}"))
        proposals = []
        for path in sorted(directory.glob("*.json")):
            try:
                proposal = json.loads(
                    safe_path(self.root, path.relative_to(self.root)).read_bytes()
                )
                if not isinstance(proposal, dict):
                    raise ValueError("not a JSON object")
            except (OSError, ValueError) as exc:
                proposal = {"id": path.stem, "error": f"Unreadable proposal: {exc}"}
            proposals.append(proposal)
        return proposals

    def recover(self) -> None:
        """Restore the interrupted transaction's snapshot, then unlock writes.

        Raises LookupError when no transaction is pending.
        """
        with self.lock:
            try:
                marker = json.loads(self.marker.read_bytes())
            except FileNotFoundError:
                raise LookupError(
                    "No interrupted review transaction to recover"
                ) from None
            backup = safe_path(self.root, Path(marker["backup"]))
            if not backup.is_relative_to(self.root / BACKUP_DIR):
                raise ValueError("Invalid recovery snapshot path")
            raw = backup.read_bytes()
            if hashlib.sha256(raw).hexdigest() != marker["sha256"]:
                raise ValueError("Recovery snapshot hash mismatch")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                entries = {
                    safe_path(self.root, Path(name)): archive.read(name)
                    for name in archive.namelist()
                    if name != "manifest.json"
                }
                absent = [
                    safe_path(self.root, Path(name)) for name in manifest["absent"]
                ]
            for target in [*entries, *absent]:
                relative = target.relative_to(self.root).as_posix()
                if not relative.startswith(RECOVERABLE_PREFIXES):
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
        if (
            not isinstance(actor_kind, str)
            or actor_kind not in {"human", "agent"}
            or not request["actor"].strip()
        ):
            raise ValueError("An actor and actor_kind human or agent are required")
        if not request["note"].strip():
            raise ValueError("A reason for the correction is required")
        if (
            len(request["actor"]) > MAX_ACTOR_CHARS
            or len(request["note"]) > MAX_NOTE_CHARS
        ):
            raise ValueError("Actor or change note exceeds the limit")
        if (
            len(request["transcription"]) > MAX_TEXT_CHARS
            or len(request["notes"]) > MAX_TEXT_CHARS
        ):
            raise ValueError(
                f"Transcription or notes exceed {MAX_TEXT_CHARS} characters"
            )
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
                raise ValueError("No change to save")
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
                destination = safe_path(
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
                    actor_kind,
                )
                page = next(page for page in data["pages"] if page["page"] == number)
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
                quality = contract.compute_quality_signals(data, len(data["pages"]))
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
                safe_path(self.root, relative): content
                for relative, content in artifacts.items()
            }
            previous = {
                path: path.read_bytes() if path.exists() else None for path in targets
            }
            if canonical_path.read_bytes() != raw:
                raise FileExistsError(
                    "Document changed during validation; reload before saving"
                )
            backup = safe_path(
                self.root, BACKUP_DIR / object_id / f"{uuid.uuid4().hex[:16]}.zip"
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
            # A failed write rolls back through the same hash-checked snapshot
            # path as --recover; an interrupted process leaves the marker.
            try:
                for path, content in targets.items():
                    write_bytes_atomic(path, content)
            except Exception as error:
                try:
                    self.recover()
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Rollback incomplete; run review_server.py --recover: "
                        f"{rollback_error}"
                    ) from error
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
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
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
        safe_path(self.server.store.root / "docs", Path(*route))

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
    configure_console()
    with repository_writer(PROJECT_ROOT):
        if args.recover:
            try:
                ReviewStore(PROJECT_ROOT).recover()
            except (LookupError, OSError, ValueError) as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)
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
