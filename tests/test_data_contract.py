"""Runnable checks for the pipeline data contract (knowledge/08_DATA_CONTRACT.md).

Covers: pages/metadata pass-through in step 4, status mapping, title and
language reaching the TEI header, facsimile graphic url, <lb/> for the
diplomatic edition type, page-type handling, frontend text normalization
and remote image rendering, JSON page counting in step 2, and the API key
gate helper.
"""
import json

from lxml import etree

from conftest import load_step

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}

step2 = load_step("02_analyze")
step4 = load_step("04_validate")
step5 = load_step("05_annotate_tei")
step6 = load_step("06_build_frontend")
config = load_step("config")
contract = load_step("contract")


# ---------------------------------------------------------------------------
# Step 4: contract pass-through and status mapping
# ---------------------------------------------------------------------------

def _run_validate(monkeypatch, tmp_path, fixture):
    src_dir = tmp_path / "transcriptions"
    dst_dir = tmp_path / "validated"
    src_dir.mkdir()
    dst_dir.mkdir()
    (src_dir / "fixture1.json").write_text(
        json.dumps(fixture, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(step4, "TRANSCRIPTIONS_DIR", src_dir)
    monkeypatch.setattr(step4, "VALIDATED_DIR", dst_dir)
    err = step4.validate_one("fixture1", use_llm=False, force=True)
    assert err is None
    return json.loads((dst_dir / "fixture1.json").read_text(encoding="utf-8"))


def test_validate_passes_pages_and_metadata_through(monkeypatch, tmp_path, fixture_transcription):
    out = _run_validate(monkeypatch, tmp_path, fixture_transcription)
    assert out["pages"] == fixture_transcription["pages"]
    assert out["metadata"] == fixture_transcription["metadata"]


def test_step4_output_still_satisfies_the_runtime_contract(
    monkeypatch, tmp_path, fixture_transcription
):
    out = _run_validate(monkeypatch, tmp_path, fixture_transcription)
    assert contract.file_violations(out) == []


def test_needs_review_signal_maps_to_needs_review_not_problematic(
    monkeypatch, tmp_path, fixture_transcription
):
    out = _run_validate(monkeypatch, tmp_path, fixture_transcription)
    assert out["overall_status"] == "needs_review"


def test_status_mapping_decision_tree():
    clean_rules = [{"name": "r", "count": 0, "severity": "info"}]
    assert step4.compute_overall_status(clean_rules, {"needs_review": False}, None) == "confident"
    assert step4.compute_overall_status(clean_rules, {"needs_review": True}, None) == "needs_review"
    assert step4.compute_overall_status(clean_rules, None, None, gate_pages=1) == "needs_review"
    llm_uncertain = [{"page": 1, "confidence": "uncertain"}]
    assert step4.compute_overall_status(clean_rules, None, llm_uncertain) == "problematic"
    three_errors = [{"name": f"r{i}", "count": 9, "severity": "error"} for i in range(3)]
    assert step4.compute_overall_status(three_errors, None, None) == "problematic"


# ---------------------------------------------------------------------------
# Step 5: TEI header, facsimile, body structure
# ---------------------------------------------------------------------------

def _generate_root(fixture, project=None):
    xml = step5.generate_tei("fixture1", fixture, project or {})
    return etree.fromstring(xml.encode("utf-8")), xml


def test_title_and_language_reach_tei_header(fixture_transcription):
    root, _ = _generate_root(fixture_transcription)
    title = root.find(".//tei:titleStmt/tei:title", NS)
    assert title is not None and title.text == "Brief vom 22. Mai 1901"
    lang = root.find(".//tei:langUsage/tei:language", NS)
    assert lang is not None and lang.get("ident") == "fr"


def test_facsimile_graphic_urls_and_pb_pointers(fixture_transcription):
    root, _ = _generate_root(fixture_transcription)
    graphics = root.findall(".//tei:facsimile/tei:graphic", NS)
    urls = {g.get("url") for g in graphics}
    assert "https://example.org/o:fixture1/IMG.1" in urls
    assert len(graphics) == 5
    pb1 = root.find(".//tei:body//tei:pb[@n='1']", NS)
    assert pb1 is not None and pb1.get("facs") == "#facs_1"


def test_diplomatic_line_breaks_as_lb(fixture_transcription):
    root, _ = _generate_root(fixture_transcription)
    first_p = root.find(".//tei:body//tei:p", NS)
    assert first_p is not None
    assert len(first_p.findall("tei:lb", NS)) == 1  # two lines, one break
    assert "".join(first_p.itertext()) == "Erste ZeileZweite Zeile"


def test_normalised_edition_type_joins_lines(fixture_transcription):
    root, _ = _generate_root(fixture_transcription, {"edition_type": "Normalisiert"})
    first_p = root.find(".//tei:body//tei:p", NS)
    assert len(first_p.findall("tei:lb", NS)) == 0
    assert first_p.text == "Erste Zeile Zweite Zeile"


def test_foreign_text_stays_out_of_edited_body(fixture_transcription):
    root, _ = _generate_root(fixture_transcription)
    p_texts = ["".join(p.itertext()) for p in root.findall(".//tei:body//tei:p", NS)]
    assert not any("Anderer Beitrag" in t for t in p_texts)
    assert not any("Fremder Absatz" in t for t in p_texts)
    foreign = ["".join(n.itertext()) for n in root.findall(".//tei:body//tei:note[@type='foreign']", NS)]
    assert any("Anderer Beitrag" in t for t in foreign)
    assert any("Fremder Absatz" in t for t in foreign)


def test_gate_and_empty_page_notes(fixture_transcription):
    root, _ = _generate_root(fixture_transcription)
    gate = root.find(".//tei:body//tei:note[@type='gate']", NS)
    assert gate is not None and gate.get("subtype") == "low_resolution"
    empties = root.findall(".//tei:body//tei:note[@type='empty']", NS)
    assert len(empties) == 1  # page 5 (undeclared), not page 2 (declared blank)


def test_generated_tei_is_well_formed_and_valid_report(fixture_transcription):
    _, xml = _generate_root(fixture_transcription)
    report = step5.validate_tei(xml, fixture_transcription["pages"])
    assert report["well_formed"]
    assert report["required_elements"]


# ---------------------------------------------------------------------------
# Step 6: frontend extraction
# ---------------------------------------------------------------------------

def test_frontend_normalizes_whitespace_and_renders_remote_urls(
    monkeypatch, tmp_path, fixture_transcription
):
    _, xml = _generate_root(fixture_transcription)
    tei_path = tmp_path / "fixture1.xml"
    tei_path.write_text(xml, encoding="utf-8")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    monkeypatch.setattr(step6, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(step6, "resolve_image_dir", lambda _id: None)

    data = step6.process_tei(tei_path)
    assert data["title"] == "Brief vom 22. Mai 1901"
    assert data["language"] == "fr"

    page1 = data["pages"][0]
    # lb becomes a line break, indentation whitespace is gone
    assert "Erste Zeile\nZweite Zeile" in page1["text"]
    assert "  " not in page1["text"]
    # pb facs="#facs_1" resolves to the remote graphic url
    assert page1["image"] == "https://example.org/o:fixture1/IMG.1"
    assert data["has_images"] is True


def test_frontend_copies_local_images_into_docs(monkeypatch, tmp_path):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<TEI xmlns="{TEI_NS}"><teiHeader><fileDesc><titleStmt><title>t</title></titleStmt>'
        "<publicationStmt><publisher>p</publisher></publicationStmt>"
        "<sourceDesc><p>s</p></sourceDesc></fileDesc></teiHeader>"
        '<text><body><div><pb n="1" facs="images/loc1/loc1_p001.png"/><p>Text</p></div></body></text></TEI>'
    )
    tei_path = tmp_path / "loc1.xml"
    tei_path.write_text(xml, encoding="utf-8")

    image_dir = tmp_path / "sources_images" / "loc1"
    image_dir.mkdir(parents=True)
    (image_dir / "loc1_p001.png").write_bytes(b"\x89PNG fake")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    monkeypatch.setattr(step6, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(step6, "resolve_image_dir", lambda _id: image_dir)

    data = step6.process_tei(tei_path)
    assert data["has_images"] is True
    assert data["pages"][0]["image"] == "images/loc1/loc1_p001.png"
    assert (docs_dir / "images" / "loc1" / "loc1_p001.png").exists()


# ---------------------------------------------------------------------------
# Step 2: JSON source type with page counting
# ---------------------------------------------------------------------------

def test_analyze_counts_json_pages_from_pages_array(monkeypatch, tmp_path, fixture_transcription):
    sources = tmp_path / "sources"
    (sources / "text").mkdir(parents=True)
    (sources / "text" / "fixture1.json").write_text(
        json.dumps(fixture_transcription, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(step2, "SOURCES_DIR", sources)

    documents = step2.scan_sources()
    assert "fixture1" in documents
    assert documents["fixture1"]["source_type"] == "transcription"
    assert documents["fixture1"]["pages"] == 5


# ---------------------------------------------------------------------------
# API key gate
# ---------------------------------------------------------------------------

def test_missing_api_key_helper(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert config.missing_api_key("gemini") == "GEMINI_API_KEY"
    monkeypatch.setattr(config, "GEMINI_API_KEY", "k")
    assert config.missing_api_key("gemini") is None
    # Ollama is local and needs no key
    assert config.missing_api_key("ollama") is None
