"""The version stands in pyproject.toml; the citation files and the README repeat it."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_version_matches_across_metadata():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    citation = re.search(
        r'^version: "([^"]+)"',
        (ROOT / "CITATION.cff").read_text(encoding="utf-8"),
        re.M,
    )
    codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert citation and citation.group(1) == version
    assert codemeta["softwareVersion"] == version
    assert f"version {version}," in readme
    assert f"## {version}," in changelog
