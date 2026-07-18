---
title: Architekturentscheidungen
description: Architecture Decision Records im ADR-Format
tags: [decisions, architecture]
---

# Architekturentscheidungen

Dokumentation aller Architektur- und Designentscheidungen im ADR-Format. Claude Code traegt hier ein, wenn Pipeline-Skripte modifiziert oder Designentscheidungen getroffen werden.

## Format

```
### ADR-NNN Titel

**Datum:** YYYY-MM-DD
**Kontext:** Was ist die Ausgangslage?
**Entscheidung:** Was wurde entschieden?
**Begruendung:** Warum?
**Alternativen:** Was wurde verworfen und warum?
```

## Entscheidungen

### ADR-001 Zweisprachige Dokumentation

**Datum:** 2026-07-17
**Kontext:** Das Template traegt Dokumentation in zwei Sprachen. README und SETUP sind englisch, damit das forkbare Repo fuer ein internationales Publikum zugaenglich ist. Die Wissensdokumente im `knowledge/`-Ordner sind deutsch, weil sie die Promptotyping-Wissensbasis der deutschsprachigen Ausgangsprojekte fortschreiben.
**Entscheidung:** Die Doku-Sprache bleibt zweisprachig. README und SETUP werden englisch gepflegt, die Wissensdokumente in `knowledge/` deutsch. Keine Vereinheitlichung auf eine Sprache.
**Begruendung:** Die beiden Sprachen bedienen zwei verschiedene Adressaten. Das englische README/SETUP richtet sich an Fork-Nutzende, das deutsche `knowledge/` an den Agent und an das deutschsprachige Editionsteam, das die Wissensbasis fuellt. Eine Vereinheitlichung wuerde einen der beiden Adressaten schlechter bedienen.
**Alternativen:** Vollstaendige Umstellung auf Englisch verworfen, weil die Wissensbasis konzeptuell an die deutschsprachigen Quellprojekte anschliesst und das Editionsteam deutsch arbeitet. Vollstaendige Umstellung auf Deutsch verworfen, weil das die internationale Forkbarkeit des Templates einschraenkt.

### ADR-002 Ein Datenvertrag, API-Key-Gate statt Import-Modus

**Datum:** 2026-07-18
**Kontext:** Die beiden Fork-Testlaeufe fanden drei Schluesselvarianten fuer denselben Seitentext (`transcription` im Prompt und in Schritt 4/5, `text` in den Quality-Signals, verschachtelte `pages` in Schritt 3) sowie stillen Metadaten-Verlust in Schritt 4. Zusaetzlich fehlte ein deklarierter Pfad fuer Transkriptionen, die ohne Provider-Key entstehen.
**Entscheidung:** Ein einziger Datenvertrag ([[08_DATA_CONTRACT]]): `pages` auf oberster Ebene, Seitentext unter `transcription`, Objektmetadaten unter `metadata`, von Schritt 3 bis 6 unveraendert durchgereicht. Jede Stufe mit Provider-Aufruf prueft den API-Key am Start und bricht mit klarer Meldung ab. Es gibt keinen Import-Modus in Schritt 3; extern erzeugte Transkriptionen werden vertragskonform direkt nach `data/processed/transcriptions/` geschrieben.
**Begruendung:** Schritt 4 und 5 erwarteten den flachen Vertrag bereits; die Anpassung von Schritt 3 ist der kleinste Eingriff. Ein Import-Modus wuerde eine zweite Eingangstuer mit eigener Validierungslogik schaffen, waehrend der dokumentierte Vertrag dieselbe Faehigkeit ohne Code liefert. Stilles Weiterlaufen ohne Key erzeugte in den Testlaeufen leere Ergebnisse ohne Fehlermeldung.
**Alternativen:** `--import`-Flag fuer Schritt 3 verworfen (zweiter Codepfad fuer denselben Vertrag). Nachladen der Metadaten in Schritt 5 aus `transcriptions/` verworfen, weil das Durchreichen in Schritt 4 den Vertrag durchgaengig haelt.

### ADR-003 Zentrale Bildwurzel-Aufloesung und Remote-Faksimiles

**Datum:** 2026-07-18
**Kontext:** Die Bildpfad-Aufloesung war pro Skript dupliziert und inkonsistent (Schritt 6 pruefte nur `data/processed/images/`, Schritt 3 bevorzugte sie); vorhandene Faksimiles unter `data/sources/images/` blieben im Frontend unsichtbar. Der SZD-Testlauf brachte zudem Korpora mit ausschliesslich remote referenzierten Faksimiles.
**Entscheidung:** Eine Resolver-Funktion `config.resolve_image_dir` (erst `data/sources/images/`, dann `data/processed/images/`), die alle Skripte nutzen. Schritt 6 kopiert lokale Faksimiles nach `docs/images/{id}/` und bindet `has_images` an das tatsaechlich Anzeigbare. Remote-Faksimiles sind deklarierter Fall: `metadata.image_urls` im Datenvertrag, `<facsimile>` mit `graphic url` im deterministischen TEI, direkte URL-Anzeige im Frontend, Materialisierung ueber `pipeline/fetch_facsimiles.py`.
**Begruendung:** Eine einzige Aufloesung beseitigt die Klasse der Pfad-Doppeldeutigkeiten, die beide Testlaeufe unabhaengig fanden. Das statische Frontend kann nur unterhalb von `docs/` ausliefern, deshalb Kopie statt Verweis.
**Alternativen:** Symlinks statt Kopie verworfen (nicht portabel auf Windows und GitHub Pages). Nur-Remote-Anzeige ohne Fetch-Utility verworfen, weil Vision-Transkription und Verifikation lokale Dateien brauchen.

### ADR-004 Konventionsnamen journal.md und decisions.md

**Datum:** 2026-07-18
**Kontext:** Die Promptotyping-Konvention erwartet `journal.md` und `decisions.md`; das Template fuehrte beide nummeriert (`07_JOURNAL.md`, `06_DECISIONS.md`). Nachnutzer, die die Konvention kennen, suchten die Konventionsnamen oder legten Doppel an.
**Entscheidung:** Umbenennung auf `journal.md` und `decisions.md`. Die Lesereihenfolge stellt die Tabelle in [[00_INDEX]] her, nicht das Dateipraefix.
**Begruendung:** Ein Name pro Rolle; die Konvention ist die aeltere und breitere Quelle der Wahrheit.
**Alternativen:** Deklaration der nummerierten Namen als bewusste Abweichung verworfen, weil sie den Konflikt nur dokumentiert statt beseitigt.

### ADR-005 Validierungsziel ist eine Projektentscheidung

**Datum:** 2026-07-18
**Kontext:** Die Leitstellen-Strengpruefung zeigte, dass das deterministisch erzeugte TEI an vorbestehenden Header-Strukturen der DTABf-RNG scheitert (title-Attribute, projectDesc, revisionDesc, facsimile-Position), nicht an den neuen note-Typen. Das Template behauptete implizit DTABf als Validierungsziel, ohne es zu erfuellen. Gegen TEI All validieren alle vier zbz-Testlauf-TEI fehlerfrei (geprueft 2026-07-18).
**Entscheidung:** Das Validierungsziel ist eine Entscheidung des jeweiligen Fork-Projekts, kein Template-Default. Unterschiedliche Projekte brauchen unterschiedliche Schemata (Operator-Entscheid 2026-07-18). Der Fork setzt `VALIDATION_SCHEMA` in `pipeline/config.py` (TEI All, DTABf, eigenes RNG/ODD); `pipeline/validate_schema.py` prueft dagegen. Die DTABf-Dateien bleiben als ausgearbeitetes Beispielprofil im Template, mit dokumentiertem Header-Caveat fuer den strengen Fall.
**Begruendung:** Die beiden urspruenglichen Optionen (TEI All hart dokumentieren oder den Header streng DTABf ziehen) haetten je eine Projektklasse schlechter bedient; die Konfigurierbarkeit loest beide Faelle und macht das behauptete Ziel pruefbar statt implizit.
**Alternativen:** Header streng DTABf-konform ziehen verworfen als alleinige Loesung (bindet alle Forks an ein Profil, das nicht alle brauchen); TEI All als einziges deklariertes Ziel verworfen (verliert die Strenge fuer Projekte, die ein Profil pflegen).
