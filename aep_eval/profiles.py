"""Text readers and normalisation profiles for the CER evaluator.

Data flow: a fixture names a hypothesis and a reference, each with a `kind`
(`text`, `transcription-json`, `tei`, `tei-edition`). The profile decides how
TEI is turned into comparison text and which normalisation both sides get
before scoring. There is no universal profile; each one ports a documented
project contract so that its frozen numbers stay reproducible:

- `hsa-strict` ports tools/evaluate_cer.py of the Schuchardt fork: whitespace
  collapsed, case and punctuation kept, editorial notes dropped from an
  edition reference, transcription conventions resolved in the hypothesis,
  aggregate char-weighted over fixtures.
- `zbz-fidelity` ports extract_text_for_comparison and
  normalize_for_comparison of zbz-ocr-tei (scripts/eval/evaluate_ocr.py):
  choice/corr, footnotes excluded, lb/pb handling, symmetric quote, dash and
  French punctuation normalisation, NFC; per fixture the fidelity share of the
  Levenshtein distance, aggregate as the unweighted mean over fixtures.

The TEI readers use xml.etree deliberately: they mirror the source
algorithms line by line (namespace stripping, tail handling) so the ported
numbers can be audited against the originals; RelaxNG checking lives in
tei_check.py on lxml.
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

KINDS = frozenset({"text", "transcription-json", "tei", "tei-edition"})


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    tei_extraction: str  # "itertext" or "comparison"
    aggregate: str  # "char-weighted" or "fixture-mean"
    value_field: str  # "cer" or "cer_fidelity"
    source: str


PROFILES: dict[str, Profile] = {
    "hsa-strict": Profile(
        name="hsa-strict",
        description=(
            "Whitespace collapsed, case and punctuation kept; editorial notes removed "
            "from an edition reference; transcription conventions resolved in the "
            "hypothesis; full Levenshtein; aggregate char-weighted."
        ),
        tei_extraction="itertext",
        aggregate="char-weighted",
        value_field="cer",
        source="hsa-letters-pipeline tools/evaluate_cer.py",
    ),
    "zbz-fidelity": Profile(
        name="zbz-fidelity",
        description=(
            "TEI body text with choice/corr, footnotes excluded, lb and pb handled; "
            "quotes, dashes and French punctuation normalised symmetrically, NFC; "
            "fidelity share of the Levenshtein distance (insertions of 50 or more "
            "characters count as scope surplus); aggregate unweighted fixture mean."
        ),
        tei_extraction="comparison",
        aggregate="fixture-mean",
        value_field="cer_fidelity",
        source="zbz-ocr-tei scripts/eval/evaluate_ocr.py",
    ),
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; known profiles: {known}") from None


# --- normalisation ---------------------------------------------------------


def normalise_whitespace(text: str) -> str:
    """Collapse all whitespace to single spaces and strip (hsa-strict)."""
    return " ".join(text.split())


def _zbz_base(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text.strip()


def normalise_zbz(text: str, casefold: bool = False) -> str:
    """Symmetric normalisation of zbz-ocr-tei, applied to both sides."""
    text = text.replace("\u00ab", '"').replace("\u00bb", '"').replace("\u201e", '"')
    text = text.replace("\u2039", "'").replace("\u203a", "'")
    text = text.replace("\u0060", "'").replace("\u00b4", "'")
    for dash in ("\u2010", "\u2011", "\u2013", "\u2014", "\u2012"):
        text = text.replace(dash, "-")
    text = text.replace("\u00ad", "")
    text = re.sub(r" +([;:?!])", r"\1", text)
    if casefold:
        text = text.casefold()
    text = _zbz_base(text)
    return unicodedata.normalize("NFC", text)


def normalise(profile: Profile, text: str) -> str:
    if profile.name == "zbz-fidelity":
        return normalise_zbz(text)
    return normalise_whitespace(text)


# --- readers ---------------------------------------------------------------


def _strip_namespaces(root: ET.Element) -> None:
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}")[1]
        for key in list(elem.attrib):
            if "}" in key:
                elem.attrib[key.split("}")[1]] = elem.attrib.pop(key)


def _parse(path: Path) -> ET.Element | None:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError:
        return None
    _strip_namespaces(root)
    return root


def read_tei_itertext(path: Path, drop_editorial_notes: bool) -> str:
    """Raw body text; optionally without note[@type='editorial'] (hsa-strict).

    Removing an element drops its tail, so the tail is handed to the previous
    sibling or the parent first, as the Schuchardt evaluator does.
    """
    root = _parse(path)
    if root is None:
        raise ValueError(f"not well-formed XML: {path}")
    body = root.find(".//body")
    if body is None:
        return ""
    if drop_editorial_notes:
        parents = {child: parent for parent in body.iter() for child in parent}
        for note in [n for n in body.iter("note") if n.get("type") == "editorial"]:
            parent = parents[note]
            index = list(parent).index(note)
            tail = note.tail or ""
            if index == 0:
                parent.text = (parent.text or "") + tail
            else:
                sibling = list(parent)[index - 1]
                sibling.tail = (sibling.tail or "") + tail
            parent.remove(note)
    return "".join(body.itertext())


def read_tei_comparison(path: Path, include_footnotes: bool = False) -> str:
    """Body text as zbz-ocr-tei extracts it for CER: choice takes corr, footnotes
    are excluded, lb without break='no' becomes a space, pb a paragraph break.
    A non-well-formed file falls back to tag stripping, as in the source."""
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except ET.ParseError:
        return re.sub(r"<[^>]+>", "", path.read_text(encoding="utf-8"))
    _strip_namespaces(root)
    body = root.find(".//body")
    if body is None:
        return ""

    def collect(elem: ET.Element) -> str:
        parts: list[str] = []
        if elem.tag == "choice":
            corr = elem.find("corr")
            target = corr if corr is not None else elem.find("sic")
            return collect(target) if target is not None else ""
        if elem.tag == "note" and elem.get("place") == "foot" and not include_footnotes:
            return ""
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            if child.tag == "lb":
                if child.get("break") != "no":
                    parts.append(" ")
            elif child.tag == "pb":
                parts.append("\n\n")
            else:
                parts.append(collect(child))
            if child.tail:
                parts.append(child.tail)
        return "".join(parts)

    return collect(body)


def read_transcription_json(path: Path, pages: list[int] | None) -> str:
    """Pipeline transcription JSON (data contract): page texts in scope order
    with the template's transcription conventions resolved to the reading they
    assert ([?], [...], ~~deletion~~, {insertion})."""
    record = json.loads(path.read_text(encoding="utf-8"))
    by_number = {int(p.get("page", 0)): p for p in record.get("pages", [])}
    order = pages if pages is not None else sorted(by_number)
    text = "\n".join(
        by_number[n].get("transcription", "") for n in order if n in by_number
    )
    text = re.sub(r"\[\?\]", "", text)
    text = re.sub(r"\[\.\.\.[^\]]*\]", "", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"\{(.*?)\}", r"\1", text)
    return text


def read_side(
    profile: Profile, kind: str, path: Path, pages: list[int] | None = None
) -> str:
    """Comparison text of one side of a fixture, normalised for the profile."""
    if kind not in KINDS:
        raise ValueError(
            f"unknown kind {kind!r}; known kinds: {', '.join(sorted(KINDS))}"
        )
    if kind == "text":
        raw = path.read_text(encoding="utf-8")
    elif kind == "transcription-json":
        raw = read_transcription_json(path, pages)
    elif profile.tei_extraction == "comparison":
        raw = read_tei_comparison(path)
    else:
        raw = read_tei_itertext(path, drop_editorial_notes=(kind == "tei-edition"))
    return normalise(profile, raw)
