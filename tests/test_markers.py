"""Runnable checks for the edition-convention markers (pipeline/markers.py).

The markers are declared in pipeline/prompts/transcription.md; these checks
hold the module to that declaration and pin the consequence in step 4, where
a marker must not read as OCR noise.
"""

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
