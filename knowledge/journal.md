---
title: Entwicklungsjournal
description: Protokoll jeder Arbeitssession mit Datum, Ziel und Ergebnis
tags: [journal, sessions]
---

# Entwicklungsjournal

Protokoll jeder Arbeitssession. Claude Code traegt hier am Ende jeder Session Datum, Ziel und Ergebnis ein.

## Format

```
### YYYY-MM-DD Sessiontitel

**Ziel:** Was sollte erreicht werden?
**Ergebnis:** Was wurde erreicht?
**Probleme:** Was hat nicht funktioniert?
**Naechste Schritte:** Was steht als naechstes an?
```

## Sessions

### 2026-07-18 Reparatur-Lauf nach den Fork-Testlaeufen

**Ziel:** Alle in den Testlaeufen zbz und szd dokumentierten Template-Bugs beheben und die Doku vereinheitlichen.
**Ergebnis:** Datenvertrag der Transkriptions-JSON festgeschrieben ([[08_DATA_CONTRACT]]) und in Schritt 3 bis 6 plus Prompt durchgesetzt; Metadaten-Durchreichung in Schritt 4; API-Key-Gate mit klarer Abbruchmeldung in Schritt 3, 4, 5; zentrale Bildwurzel-Aufloesung in `config.py` mit Faksimile-Kopie nach `docs/images/`; Remote-Faksimiles als deklarierter Fall (`metadata.image_urls`, `<facsimile>`/`graphic url`, `fetch_facsimiles.py`); Seiten-Gates (`page_type`), Fremdtext-Abgrenzung und `<lb/>` fuer den diplomatischen Editionstyp in Schritt 5; Whitespace-Normalisierung und pb-Attribut-Parsing in Schritt 6; `.json` als Quellentyp mit Seitenzaehlung in Schritt 2; Statusmodell entschaerft (`needs_review` nicht mehr `problematic`); Umbenennung auf `journal.md`/`decisions.md`; Testabdeckung unter `tests/` (pytest, alle gruen). Entscheidungen in ADR-002 bis ADR-004.
**Probleme:** Das alte pb-Regex in Schritt 6 verlor das `facs`-Attribut bei der Attributreihenfolge `n` vor `facs`; durch attributweises Parsen ersetzt.
**Naechste Schritte:** Ersten Produktiv-Fork mit korpusspezifisch iterierten Prompts aufsetzen (SETUP.md Abschnitt 5); LLM-Annotationspass in Schritt 5 implementieren, sobald ein Fork ihn braucht.

### 2026-07-18 Verifikationsbefund der Leitstelle, DTABf-Strengpruefung

**Ziel:** Nachpruefung des Reparatur-Laufs (Test-Nachlauf, Git-Anker) und der offenen Frage, ob die neuen note-Typen (`gate`, `foreign`, `empty`) streng DTABf-konform sind.
**Ergebnis:** Test-Nachlauf 14/14 gruen, Commits und Umbenennungen bestaetigt. Die RelaxNG-Pruefung eines generierten TEI gegen `schemas/basisformat.rng` schlaegt fehl, allerdings an vorbestehenden Header-Strukturen (title-Attribute, `projectDesc`, `revisionDesc`, `facsimile` an dieser Position werden vom strengen Basisformat nicht akzeptiert), nicht an den neuen note-Typen. Das deterministische TEI war demnach nie streng DTABf-valide; es ist wohlgeformtes TEI, das sich am Basisformat orientiert.
**Probleme:** Keine neuen; der Befund ist eine Praezisierung der in `schemas/README.md` angelegten Rollentrennung zwischen Encoding-Profil und Validierung.
**Naechste Schritte:** Entscheiden, ob der deterministische Modus TEI-All als Validierungsziel deklariert (Doku-Aenderung) oder der Header auf strenge Basisformat-Konformitaet gezogen wird (Code-Aenderung); bis dahin gilt die Orientierungs-Formulierung.

### 2026-07-18 Validierungsziel konfigurierbar gemacht (ADR-005)

**Ziel:** Den offenen Validierungsziel-Entscheid umsetzen; Operator-Entscheid: das Schema muss projektweise waehlbar sein.
**Ergebnis:** `VALIDATION_SCHEMA` in `pipeline/config.py` als einzige Konfigurationsstelle; `pipeline/validate_schema.py` als lauffaehiger Pruefer (klare Meldung bei fehlendem Schema, Datei-Report, Exit-Code); drei neue Tests (17/17 gruen). Empirisch belegt: alle vier zbz-Testlauf-TEI sind TEI-All-valide, der DTABf-Fehlschlag reproduziert exakt an den Header-Strukturen aus dem Vortagesbefund. schemas/README.md und SETUP.md Abschnitt 6 auf die Projektentscheidung umgestellt, DTABf als Beispielprofil mit Header-Caveat. ADR-005.
**Probleme:** Keine.
**Naechste Schritte:** Ersten Produktiv-Fork aufsetzen; dort das Validierungsziel explizit setzen und den Header bei Bedarf profilkonform ziehen.

### 2026-08-22 Evaluationsmodul aep_eval v0.1 (Leitstelle, T-026)

**Ziel:** Erste ausfuehrbare Scheibe des Evaluationsvertrags der Forschungsleitstelle (Pilot Agentic Edition Evaluation): Fixture-Manifest mit JSON-Schema, CER unter den Profilen `hsa-strict` und `zbz-fidelity`, parametrisierte RelaxNG-Pruefung, gemeinsames Ergebnisschema, JSON- und Markdown-Bericht, synthetische Tests, reale Regressionen gegen Schuchardt und Hersch read-only.
**Ergebnis:** Paket `aep_eval/` (profiles, cer, tei_check, manifest, results, runner, CLI), `schemas/evaluation-fixture.schema.json` und `schemas/evaluation-result.schema.json`, 39 neue Tests in `tests/test_aep_eval_*.py` mit Fixtures unter `tests/fixtures/evaluation/` (Gesamtsuite 56 gruen), README-Abschnitt, ADR-006, `jsonschema` und `rapidfuzz` in requirements.txt. Regression Schuchardt (18 Briefe, Fork a28dee27): hsa-strict char-gewichtet 0,059821 gegen eingefrorenes 0,0598, jedes Objekt in Referenzlaenge und Distanz identisch mit results/reports/cer.json; 18/18 valide gegen tei_all.rng. Regression Hersch (25 Referenzdokumente, zbz-ocr-tei c0cc7417): zbz-fidelity Fixture-Mittel 0,020804 gegen publiziertes 0,020804, je Dokument Fidelity, Full und Scope innerhalb 5e-7 der publizierten Werte, Zerlegung ueberall konsistent. Manifeste und Laufberichte liegen ausserhalb des Repos im Leitstellen-Arbeitsbereich; die Fixture-Repositories blieben unveraendert.
**Probleme:** Keine im Modul. Offen bleibt, dass die Hersch-Quelldatei `cer_statistics.json` auf einem unsauberen Worktree erzeugt wurde (Provenienz im Manifest vermerkt); die TEI-Extraktion mirrort die Quellalgorithmen auf xml.etree, damit die Zahlen auditierbar bleiben (siehe Modul-Docstring).
**Naechste Schritte:** Unabhaengige Pruefung durch die Leitstelle (T-027); danach Struktur- und Entity-Evaluator auf demselben Vertrag (M10) und die Integration als Pipeline-Schritt.
