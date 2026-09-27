"""Shared fixtures, builders and the offline guard for the test suite.

pyproject.toml puts the repository root and pipeline/ on the import path, so
shared modules import by name and the digit-named step scripts through
importlib.import_module.
"""

import copy
import importlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from requests.structures import CaseInsensitiveDict

import config
import contract
import validate_schema

REPOSITORY_ROOT = Path(__file__).parent.parent
TEI_NS = config.TEI_NS
NS = config.NS
# Tests that need a schema pin the shipped TEI All grammar; config's
# VALIDATION_SCHEMA is a per-fork decision and may name another target.
TEI_ALL_SCHEMA = config.SCHEMAS_DIR / "tei_all.rng"
EVALUATION_FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures" / "evaluation"
API_KEY_NAMES = ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


# Offline guard


class NetworkBlocked(RuntimeError):
    """Raised when a test reaches for a non-loopback host.

    A RuntimeError, not an OSError, so neither requests nor the pipeline's
    retry and error-collection code can swallow it as a transient failure.
    """


_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo


def _ip_address(host: object) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0])
    except ValueError:
        return None


def _is_loopback(host: object) -> bool:
    if host in ("localhost", b"localhost"):
        return True
    address = _ip_address(host)
    return address is not None and address.is_loopback


def _is_ip_literal(host: object) -> bool:
    return _ip_address(host) is not None


def _check_address(address: object) -> None:
    # AF_UNIX addresses are paths, not hosts.
    if isinstance(address, tuple) and not _is_loopback(address[0]):
        raise NetworkBlocked(f"test attempted a network connection to {address!r}")


def _guarded_connect(sock: socket.socket, address: object) -> None:
    _check_address(address)
    return _REAL_CONNECT(sock, address)


def _guarded_connect_ex(sock: socket.socket, address: object) -> int:
    _check_address(address)
    return _REAL_CONNECT_EX(sock, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    # An IP literal resolves locally; a host name would send a DNS query.
    if host is not None and not _is_loopback(host) and not _is_ip_literal(host):
        raise NetworkBlocked(f"test attempted to resolve the host name {host!r}")
    return _REAL_GETADDRINFO(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Keep every test away from providers and external hosts.

    config runs load_dotenv() on import, so a fork's .env puts live keys into
    this process. Blanking them and blocking non-loopback sockets turns a
    forgotten provider stub into a failing test instead of a paid call.
    """
    for name in API_KEY_NAMES:
        monkeypatch.setattr(config, name, "")
        monkeypatch.delenv(name, raising=False)
    # A local Ollama server would answer on loopback; a TEST-NET-1 address
    # (RFC 5737) sends a forgotten stub into the guard instead.
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://192.0.2.1:11434")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


# Small builders


def forbid(message: str):
    """Return a stand-in that fails the test whenever it is called."""

    def guard(*_args, **_kwargs):
        raise AssertionError(message)

    return guard


class CasefoldCollidingDir:
    """Directory stand-in whose glob yields two names differing only in case.

    A case-insensitive filesystem cannot hold both files, so the collision
    check is exercised through this fake on every platform.
    """

    def __init__(self, suffix: str) -> None:
        self.suffix = suffix

    def glob(self, _pattern: str) -> list[Path]:
        return [Path(f"Doc{self.suffix}"), Path(f"doc{self.suffix}")]

    def __str__(self) -> str:
        return "casefold-colliding-directory"


def write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def page_images(directory: Path, count: int, name: str = "p{page}.png") -> list[Path]:
    """Write count page files with distinct bytes; name formats {page}."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for page in range(1, count + 1):
        path = directory / name.format(page=page)
        path.write_bytes(f"image-{page}".encode())
        paths.append(path)
    return paths


def write_image_manifest(directory: Path, pages: list, **fields) -> dict:
    """Write directory/manifest.json as step 1 and the fetcher do.

    Each page is a filename or a dict. Pages are numbered from 1 and carry
    the SHA-256 of the file's current bytes unless the entry sets its own
    value or records an error.
    """
    entries = []
    for number, page in enumerate(pages, start=1):
        entry = {"filename": page} if isinstance(page, str) else dict(page)
        entry.setdefault("page", number)
        image = directory / entry["filename"]
        if "sha256" not in entry and "error" not in entry and image.is_file():
            entry["sha256"] = config.file_sha256(image)
        entries.append(entry)
    manifest = {**fields, "pages": entries}
    write_json(directory / "manifest.json", manifest)
    return manifest


def review_event(
    from_status: str,
    status: str,
    timestamp: str = "2026-08-27T10:00:00+02:00",
    actor: str = "editor@example.org",
    **extra,
) -> dict:
    """One entry of a page's review history."""
    return {
        "from_status": from_status,
        "status": status,
        "actor": actor,
        "timestamp": timestamp,
        **extra,
    }


def make_transcription(pages=("Text",), object_id: str = "doc1", **extra) -> dict:
    """A minimal contract-conformant transcription with one page per text."""
    return {
        "_meta": {"script": "manual", "timestamp": "2026-08-27T00:00:00+00:00"},
        "object_id": object_id,
        "pages": [
            {
                "page": number,
                "transcription": text,
                "review": {"status": "machine_unreviewed", "history": []},
            }
            for number, text in enumerate(pages, start=1)
        ],
        **extra,
    }


def minimal_tei(page_break: str = '<pb n="1"/>', revision_desc: str = "") -> str:
    """A small TEI document with the header fields step 6 reads."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<TEI xmlns="{TEI_NS}"><teiHeader><fileDesc>'
        "<titleStmt><title>t</title></titleStmt>"
        "<publicationStmt><publisher>p</publisher></publicationStmt>"
        f"<sourceDesc><p>s</p></sourceDesc></fileDesc>{revision_desc}</teiHeader>"
        f"<text><body><div>{page_break}<p>Text</p></div></body></text></TEI>"
    )


MINIMAL_TEI = minimal_tei()


@pytest.fixture
def directory_link():
    """Create directory links that are removed, without their targets, afterwards.

    Windows gets a junction, which needs no symlink privilege and is a
    reparse point like a symlink; other platforms get a symbolic link.
    """
    links: list[Path] = []

    def create(link: Path, target: Path) -> Path:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
        links.append(link)
        return link

    yield create
    for link in reversed(links):
        # rmdir and unlink remove the link itself and never recurse into it.
        if sys.platform == "win32":
            link.rmdir()
        else:
            link.unlink()


@pytest.fixture(scope="session")
def tei_all():
    """The shipped TEI All grammar, compiled once for the whole session.

    Compiling it takes seconds, and validate_schema's small cache may evict
    it while other tests compile their own grammars.
    """
    return validate_schema.load_schema(TEI_ALL_SCHEMA)


# Step directories


@pytest.fixture
def step4_dirs(tmp_path) -> dict[str, Path]:
    """Keyword directories of 04_validate.validate_one."""
    dirs = {
        "transcriptions_dir": tmp_path / "transcriptions",
        "validated_dir": tmp_path / "validated",
        "calls_dir": tmp_path / "llm-calls",
    }
    dirs["transcriptions_dir"].mkdir(exist_ok=True)
    dirs["validated_dir"].mkdir(exist_ok=True)
    return dirs


@pytest.fixture
def step5_dirs(tmp_path) -> dict[str, Path]:
    """Keyword directories of 05_annotate_tei.annotate_one.

    validated_dir is the directory step4_dirs writes to, so a test can chain
    both steps.
    """
    dirs = {
        "validated_dir": tmp_path / "validated",
        "tei_dir": tmp_path / "tei",
        "reports_dir": tmp_path / "reports",
    }
    for path in dirs.values():
        path.mkdir(exist_ok=True)
    return dirs


def point_step6_at(monkeypatch, root: Path, project: dict | None = None) -> None:
    """Redirect step 6 and the shared image resolver to a repository-shaped root.

    Without a project mapping, step 6 reads root/knowledge/01_PROJECT.md.
    """
    step6 = importlib.import_module("06_build_frontend")
    monkeypatch.setattr(config, "SOURCE_IMAGES_DIR", root / "data/sources/images")
    monkeypatch.setattr(config, "IMAGES_DIR", root / "data/processed/images")
    monkeypatch.setattr(step6, "RESULTS_TEI_DIR", root / "results/tei")
    monkeypatch.setattr(step6, "RESULTS_REPORTS_DIR", root / "results/reports")
    monkeypatch.setattr(step6, "ERRORS_DIR", root / "results/frontend")
    monkeypatch.setattr(step6, "DOCS_DIR", root / "docs")
    monkeypatch.setattr(step6, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        step6,
        "project_info",
        lambda: (
            project
            if project is not None
            else config.project_info(root / "knowledge/01_PROJECT.md")
        ),
    )


# Fake HTTP


class FakeResponse:
    """Stand-in for requests.Response with a JSON payload or streamed bytes."""

    def __init__(
        self,
        status_code: int = 200,
        payload: object = None,
        content: bytes = b"",
        headers: dict | None = None,
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = content
        self.headers = CaseInsensitiveDict(headers or {})
        self._error = error

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self) -> None:
        return None


class FakeSession:
    """Stand-in for requests.Session serving scripted outcomes in order.

    The last outcome repeats; an exception outcome is raised. Every requested
    URL is recorded in calls.
    """

    def __init__(self, *outcomes) -> None:
        self.headers: dict = {}
        self.calls: list[str] = []
        self._outcomes = list(outcomes)

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def get(self, url: str, **_kwargs):
        self.calls.append(url)
        if not self._outcomes:
            raise AssertionError(f"unexpected HTTP request for {url}")
        outcome = (
            self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def install_session(monkeypatch, *outcomes) -> FakeSession:
    """Make requests.Session() return one FakeSession serving outcomes."""
    session = FakeSession(*outcomes)
    monkeypatch.setattr(requests, "Session", lambda: session)
    return session


# Frontend rendering

# A minimal DOM, enough for docs/js/app.js to render the catalog and the
# viewer header under Node. fetch reads files below the data root. The shim
# fails loudly when app.js starts using a DOM API it does not provide.
_FRONTEND_HARNESS = r"""
import {readFile} from "node:fs/promises";
import path from "node:path";
import {pathToFileURL} from "node:url";

const scenario = JSON.parse(process.env.AEP_FRONTEND_SCENARIO);

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parent = null;
    this.ownText = "";
    this.className = "";
    this.attributes = {};
    this.dataset = {};
    this.listeners = {};
    this.hidden = false;
    this.value = "";
  }
  get textContent() { return this.ownText + this.children.map(c => c.textContent).join(""); }
  set textContent(value) { this.ownText = String(value); this.children = []; }
  get isConnected() { return true; }
  get classList() {
    const node = this;
    return {toggle(name, on) {
      const names = new Set(node.className.split(" ").filter(Boolean));
      if (on) names.add(name); else names.delete(name);
      node.className = [...names].join(" ");
    }};
  }
  append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  replaceChildren(...nodes) { this.ownText = ""; this.children = []; this.append(...nodes); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, listener) { (this.listeners[type] ??= []).push(listener); }
  dispatch(type) { for (const listener of this.listeners[type] ?? []) listener({}); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  querySelectorAll(selector) {
    let found = [this];
    for (const part of selector.trim().split(/\s+/)) {
      const next = [];
      for (const root of found) {
        for (const node of descendants(root)) if (matches(node, part) && !next.includes(node)) next.push(node);
      }
      found = next;
    }
    return found;
  }
}

function* descendants(node) {
  for (const child of node.children) { yield child; yield* descendants(child); }
}

function matches(node, part) {
  if (part.startsWith(".")) return node.className.split(" ").includes(part.slice(1));
  if (/^[a-z][a-z0-9]*$/i.test(part)) return node.tagName === part.toUpperCase();
  throw new Error("harness selector not supported: " + part);
}

const byId = {app: new FakeElement("main"), notice: new FakeElement("p"), "project-title": new FakeElement("h1")};
const windowListeners = {};
globalThis.document = {
  baseURI: "https://edition.example/",
  body: new FakeElement("body"),
  title: "",
  createElement: tag => new FakeElement(tag),
  getElementById: id => byId[id],
  querySelectorAll: () => [],
};
globalThis.window = {addEventListener: (type, listener) => (windowListeners[type] ??= []).push(listener), confirm: () => true};
globalThis.location = {hash: "#catalog", hostname: "edition.example"};
globalThis.history = {replaceState() {}};
globalThis.fetch = async url => {
  try {
    const body = await readFile(path.join(scenario.dataRoot, decodeURIComponent(url)), "utf-8");
    return {ok: true, status: 200, json: async () => JSON.parse(body)};
  } catch {
    return {ok: false, status: 404, json: async () => ({})};
  }
};

const app = byId.app;
const settle = async (done) => {
  for (let i = 0; i < 200 && !done(); i++) await new Promise(resolve => setTimeout(resolve, 5));
  if (!done()) throw new Error("frontend did not render: " + app.textContent);
};
const rows = () => app.querySelectorAll(".catalog-table tbody tr");

await import(pathToFileURL(scenario.appJs).href);
await settle(() => rows().length > 0);
const result = {
  headers: app.querySelectorAll(".catalog-table thead th").map(th => th.textContent),
  rows: rows().map(row => row.children.map(cell => cell.textContent)),
};
if (scenario.query !== null) {
  const input = app.querySelector(".search-input");
  input.value = scenario.query;
  input.dispatch("input");
  await new Promise(resolve => setTimeout(resolve, 300));
  result.visible = rows().filter(row => !row.hidden).map(row => row.children[0].textContent);
}
if (scenario.viewer !== null) {
  location.hash = "#viewer/" + encodeURIComponent(scenario.viewer);
  for (const listener of windowListeners.hashchange ?? []) listener();
  await settle(() => app.querySelector("h2") !== null);
  result.title = app.querySelector("h2").textContent;
  result.links = app.querySelectorAll("a").map(a => ({text: a.textContent, href: a.href, download: a.download ?? null}));
}
process.stdout.write(JSON.stringify(result));
"""


def render_frontend(
    app_js: Path,
    data_root: Path,
    query: str | None = None,
    viewer: str | None = None,
) -> dict:
    """Render the static frontend under Node and describe what it shows.

    Returns the catalog headers and row cells, the titles left visible by a
    search query, and the viewer title and links of one object.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    scenario = {
        "appJs": str(app_js),
        "dataRoot": str(data_root),
        "query": query,
        "viewer": viewer,
    }
    completed = subprocess.run(
        (node, "--input-type=module", "-"),
        input=_FRONTEND_HARNESS,
        env={**os.environ, "AEP_FRONTEND_SCENARIO": json.dumps(scenario)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


# Contract fixtures


@pytest.fixture
def fixture_transcription() -> dict:
    """A small contract-conformant transcription covering all page cases."""
    return {
        "_meta": {
            "script": "manual",
            "timestamp": "2026-07-18T00:00:00+00:00",
            "pipeline_step": 0,
        },
        "object_id": "fixture1",
        "metadata": {
            "title": "Brief vom 22. Mai 1901",
            "language": "fr",
            "date": "1901-05-22",
            "object_type": "Korrespondenz",
            "repository": "Example Archive",
            "signature": "A 1",
            "image_urls": {
                str(page): f"https://example.org/o:fixture1/IMG.{page}"
                for page in range(1, 6)
            },
        },
        "pages": [
            {
                "page": 1,
                "transcription": "Erste Zeile\nZweite Zeile\n\nZweiter Absatz\n\nFremder Absatz",
                "notes": "",
                "foreign_paragraphs": [2],
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 2,
                "transcription": "",
                "notes": "Farbkarte",
                "page_type": "blank",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 3,
                "transcription": "Anderer Beitrag",
                "page_type": "foreign_text",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 4,
                "transcription": "",
                "notes": "Doppelseiten-Scan, Satz zu klein",
                "page_type": "gate_low_resolution",
                "review": {"status": "machine_unreviewed", "history": []},
            },
            {
                "page": 5,
                "transcription": "",
                "review": {"status": "machine_unreviewed", "history": []},
            },
        ],
        "confidence": "high",
        "confidence_notes": "",
        "quality_signals": {
            "page_types": [
                "content",
                "blank",
                "foreign_text",
                "gate_low_resolution",
                "undeclared_empty",
            ],
            "total_chars": 60,
            "chars_per_page": 12.0,
            "blank_pages": 1,
            "undeclared_empty_pages": 1,
            "gate_pages": 1,
            "foreign_pages": 1,
            "content_pages": 1,
            "needs_review": True,
        },
    }


@pytest.fixture
def fixture_validated(fixture_transcription) -> dict:
    """A step-4 output that is admissible at the TEI trust boundary."""
    validated = copy.deepcopy(fixture_transcription)
    validated["transcription_meta"] = validated["_meta"]
    validated["_meta"] = {
        "script": "04_validate.py",
        "timestamp": "2026-07-18T00:01:00+00:00",
        "pipeline_step": 4,
    }
    validated["overall_status"] = "needs_review"
    validated["validation"] = {
        "rules": [],
        "per_page_stats": contract.page_stats(validated["pages"]),
        "total_characters": sum(
            len(page["transcription"]) for page in validated["pages"]
        ),
    }
    reseal_validated(validated)
    return validated


def reseal_validated(validated: dict) -> None:
    """Recompute the step-4 hashes after a test changed the validated input."""
    validated["_meta"]["input_state_hash"] = contract.transcription_state_hash(
        validated
    )
    validated["_meta"]["validation_result_hash"] = contract.validation_result_hash(
        validated
    )
