"""Runnable checks for the edition-convention markers (pipeline/markers.py).

The markers are declared in pipeline/prompts/transcription.md; these checks
hold the module to that declaration and pin the consequence in step 4, where
a marker must not read as OCR noise.
"""

import re

from conftest import load_step

markers = load_step("markers")
step4 = load_step("04_validate")


def _words(text: str) -> str:
    return " ".join(text.split())


def test_strip_removes_every_convention_marker():
    text = "Geburtsort[?] [...] [... ~12 chars] ~~falsch~~ {ergaenzt}"
    assert _words(markers.strip_markers(text)) == "Geburtsort"


def test_resolve_keeps_insertions_and_drops_struck_text():
    assert _words(markers.resolve_markers("~~alt~~ {neu}")) == "neu"
    assert (
        _words(markers.resolve_markers("Wort[?] und [...] weiter")) == "Wort und weiter"
    )


def test_ocr_artifact_rule_ignores_convention_markers():
    result = step4._rule_ocr_artifacts("Lieber Freund[?], die Adresse [...] fehlt.")
    assert result["count"] == 0
    assert result["severity"] == "info"


def test_ocr_artifact_rule_still_flags_real_noise():
    result = step4._rule_ocr_artifacts("Der Satz ##@@ bricht ab")
    assert result["count"] > 0
    assert result["severity"] == "warning"


def test_marker_count_rules_read_the_same_patterns():
    text = "Wort[?] und [?] sowie [...] und [... ~5 chars]"
    assert step4._rule_uncertain_markers(text)["count"] == 2
    assert step4._rule_illegible_markers(text)["count"] == 2


def test_combined_pattern_names_every_tei_marker():
    text = "~~alt~~ {neu} Wort[?] [...] [... ~12 chars] [?] {} ~~~~"
    found = [
        (match.lastgroup, match[0]) for match in markers.MARKER_PATTERN.finditer(text)
    ]
    assert found == [
        ("deletion", "~~alt~~"),
        ("addition", "{neu}"),
        ("unclear", "Wort[?]"),
        ("illegible", "[...]"),
        ("illegible", "[... ~12 chars]"),
    ]
    illegible = [
        match
        for match in markers.MARKER_PATTERN.finditer(text)
        if match["illegible"] is not None
    ]
    assert [match["quantity"] for match in illegible] == [None, "12"]


def test_combined_illegible_group_matches_the_shared_marker():
    for text in ("[...]", "[... ~3 char]", "[...~ 40 chars]"):
        assert markers.MARKER_PATTERN.fullmatch(text)["illegible"] == text
        assert re.fullmatch(markers.ILLEGIBLE, text)
