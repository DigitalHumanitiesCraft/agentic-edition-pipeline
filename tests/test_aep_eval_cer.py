"""Synthetic checks for aep_eval profiles and CER scoring.

Covers normalisation of both profiles, the readers (edition notes,
transcription conventions and page scope, zbz extraction rules), the
Levenshtein rate and the fidelity/scope decomposition.
"""

import json
import re

import pytest

import markers
from aep_eval import cer, profiles
from aep_eval.manifest import FIXTURE_SCHEMA
from conftest import EVALUATION_FIXTURES as FIXTURES

HSA = profiles.get_profile("hsa-strict")
ZBZ = profiles.get_profile("zbz-fidelity")


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="unknown profile"):
        profiles.get_profile("does-not-exist")


def test_hsa_strict_keeps_case_and_punctuation_but_collapses_whitespace():
    assert HSA.normalise("  A,\n\tb  c ") == "A, b c"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("«Bonjour»", '"Bonjour"'),
        ("„Guten Tag“", '"Guten Tag"'),
        ("Mot : fin ; oui !", "Mot: fin; oui!"),
        ("tire\u2013t\u2014on", "tire-t-on"),
        ("Zu\u00adsammen", "Zusammen"),
        ("é", "é"),
    ],
)
def test_zbz_fidelity_normalises_symmetrically(raw, expected):
    assert ZBZ.normalise(raw) == expected


def test_edition_reader_drops_editorial_notes_and_keeps_tails():
    text = profiles.read_side(HSA, "tei-edition", FIXTURES / "edition.xml")
    assert "Anrede" not in text
    assert "Lieber Freund, ich danke Ihnen." in text
    # itertext keeps sic and corr and footnotes: that is the hsa contract
    assert "bestembesten" in text and "Fußnote" in text


def test_zbz_reader_takes_corr_and_drops_footnotes():
    text = profiles.read_side(ZBZ, "tei", FIXTURES / "edition.xml")
    assert "besten Grüßen." in text
    assert "bestem" not in text
    assert "Fußnote" not in text


def test_zbz_reader_handles_line_and_page_breaks(tmp_path):
    xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>Zei<lb break="no"/>le '
        "eins<lb/>zwei<pb/>drei</p></body></text></TEI>"
    )
    path = tmp_path / "lb.xml"
    path.write_text(xml, encoding="utf-8")
    assert profiles.read_side(ZBZ, "tei", path) == "Zeile eins zwei drei"


def test_transcription_reader_resolves_conventions_and_scope():
    text = profiles.read_side(
        HSA, "transcription-json", FIXTURES / "transcription.json", [1, 2]
    )
    assert text == "Lieber Freund, ich danke Ihnen. Mit bestem besten Grüßen."
    full = profiles.read_side(
        HSA, "transcription-json", FIXTURES / "transcription.json"
    )
    assert full.endswith("Adresse nicht verglichen")


def test_marker_syntax_matches_the_pipeline_definition():
    for name in ("UNCERTAIN", "ILLEGIBLE", "STRIKETHROUGH", "INSERTION"):
        assert getattr(profiles, name) == getattr(markers, name), name


def test_illegible_note_pattern_covers_the_shared_syntax():
    for marker in ("[...]", "[... ~12 chars]", "[...~1 char]"):
        assert re.fullmatch(markers.ILLEGIBLE, marker)
        assert re.fullmatch(profiles.ILLEGIBLE_ANY_NOTE, marker)


def test_manifest_schema_enums_match_profiles_and_kinds():
    defs = json.loads(FIXTURE_SCHEMA.read_text(encoding="utf-8"))["$defs"]
    assert set(defs["profile"]["enum"]) == set(profiles.PROFILES)
    assert set(defs["kind"]["enum"]) == profiles.KINDS


def test_identical_texts_score_zero():
    result = cer.score("abc", "abc")
    assert (
        result.distance == 0 and result.cer == 0.0 and result.decomposition_consistent
    )


def test_known_distance_and_rate():
    result = cer.score("kitten", "sitting")
    assert result.distance == 3
    assert result.cer == pytest.approx(0.5)
    assert result.fidelity_distance == 3 and result.scope_insertion_distance == 0


def test_long_insertion_counts_as_scope_not_fidelity():
    ref = "Der Text der Referenz endet hier."
    hyp = ref + " " + "Masthead " * 10  # 90 inserted characters in one block
    result = cer.score(ref, hyp)
    assert result.scope_insertion_distance >= cer.SCOPE_BLOCK_MIN
    assert result.fidelity_distance == 0
    assert result.cer_fidelity == 0.0
    assert result.decomposition_consistent


def test_short_insertion_counts_as_fidelity():
    result = cer.score("abc def", "abc xdef")
    assert result.fidelity_distance == 1 and result.scope_insertion_distance == 0


def test_cer_may_exceed_one_and_empty_reference_is_defined():
    assert cer.score("ab", "abcdefgh").cer > 1.0
    assert cer.score("", "").cer == 0.0
    assert cer.score("", "x").cer == 1.0


def test_profile_value_fields_differ():
    assert HSA.value_field == "cer" and HSA.aggregate == "char-weighted"
    assert ZBZ.value_field == "cer_fidelity" and ZBZ.aggregate == "fixture-mean"
