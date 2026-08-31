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
**Entscheidung:** Das Template konfiguriert TEI All als lauffaehiges technisches Ausgangsziel. Jeder Fork bestaetigt oder ersetzt dieses Ziel durch DTABf, ein eigenes RNG oder ein aus ODD erzeugtes Schema. `VALIDATION_SCHEMA` in `pipeline/config.py` ist die gemeinsame Konfigurationsstelle; `pipeline/validate_schema.py` prueft dagegen. Die DTABf-Dateien bleiben als ausgearbeitetes Beispielprofil im Template, mit dokumentiertem Header-Caveat fuer den strengen Fall.
**Begruendung:** Die beiden urspruenglichen Optionen (TEI All hart dokumentieren oder den Header streng DTABf ziehen) haetten je eine Projektklasse schlechter bedient; die Konfigurierbarkeit loest beide Faelle und macht das behauptete Ziel pruefbar statt implizit.
**Alternativen:** Header streng DTABf-konform ziehen verworfen als alleinige Loesung (bindet alle Forks an ein Profil, das nicht alle brauchen); TEI All als einziges deklariertes Ziel verworfen (verliert die Strenge fuer Projekte, die ein Profil pflegen).

### ADR-006 Evaluationsmodul aep_eval mit deklarierten CER-Profilen

**Datum:** 2026-08-22
**Kontext:** Die Bestandsaufnahme der Forschungsleitstelle (Pilot Agentic Edition Evaluation, T-024) fand drei unvereinbare CER-Rechenwege im Umfeld des Templates: der Schuchardt-Fork misst gegen die publizierte Edition mit Whitespace-Normalisierung, zbz-ocr-tei misst gegen manuelle Referenz-TEIs mit symmetrischer Normalisierung und Fidelity/Scope-Zerlegung, SZD-HTR mit eigener Protokoll-Normalisierung. Das Template selbst hatte keine Evaluation. Die TEI-Pruefung war schemaspezifisch und ohne gemeinsames Ergebnisformat. Der Operator autorisierte die lokale Implementierung einer ersten Scheibe (OP-003, OP-004 der Leitstelle).
**Entscheidung:** Ein eigenstaendiges Paket `aep_eval` (CLI `uv run python -m aep_eval MANIFEST --out DIR`) liest ein JSON-Schema-geprueftes Fixture-Manifest (Hypothese, Referenz, Scope, Referenzklasse, Reifestufe, Git-Anker, Hashes), berechnet CER unter deklarierten Profilen und prueft TEI gegen ein ausdruecklich benanntes RelaxNG-Schema; Ergebnisse als schema-geprueftes JSON und Markdown. v0.1 traegt zwei Profile, `hsa-strict` (Port von tools/evaluate_cer.py des Forks, aggregiert zeichengewichtet) und `zbz-fidelity` (Port von extract_text_for_comparison, normalize_for_comparison und classify_edit_operations aus zbz-ocr-tei, aggregiert als Mittel ueber Fixtures). Jedes Ergebnis fuehrt Profil, Referenzklasse und Reifestufe (beobachtete Funktion, formale Validierung, modellbeurteilt, menschlich geprueft, operatorabgenommen) als Pflichtfelder. Regressionsanker: Schuchardt 0,0598 ueber achtzehn Briefe und 18/18 gegen tei_all.rng; Hersch end_to_end_fidelity.mean 0,020804 ueber 25 Referenzdokumente als technisches Orakel mit dokumentierter Provenienz (Quelldatei auf unsauberem Worktree erzeugt). Eingaben bleiben read-only; Quelltexte und Faksimiles werden nicht in das Template kopiert. Zwei Laufzeitabhaengigkeiten kommen hinzu, jsonschema und rapidfuzz.
**Begruendung:** Ohne deklariertes Normalisierungsprofil sind CER-Werte zwischen Projekten nicht vergleichbar; das Profil als Pflichtfeld macht die Nichtvergleichbarkeit sichtbar statt sie zu verstecken. Die Ports reproduzieren die eingefrorenen Zahlen der Quellprojekte exakt und sind damit gegen die Originale auditierbar. Die Reifestufe trennt technische Konformitaet von fachlicher Validierung, die beim Operator bleibt. rapidfuzz ist noetig, weil die Fidelity-Zerlegung die Opcodes des minimalen Alignments braucht und eine Python-Rueckverfolgung bei Dokumenten mit mehreren hunderttausend Zeichen nicht traegt.
**Alternativen:** Ein universelles Normalisierungsprofil verworfen (es gibt keins, das beide Quellvertraege abbildet). Evaluation als Pipeline-Schritt 07 verworfen fuer v0.1 (erst nach Bestaetigung des Vertrags und mit Struktur- und Entity-Evaluatoren sinnvoll, siehe Leitstellenplan M10). Reine Python-Levenshtein ohne Abhaengigkeit verworfen (Laufzeit und Speicher bei den Hersch-Dokumenten).

### ADR-007 Isolierter Offline-Quickstart mit synthetischem Korpus

**Datum:** 2026-08-26
**Kontext:** Das Template enthielt einen testintern belegten Offline-Pfad, aber kein direkt ausfuehrbares Beispiel fuer Fork-Nutzende. Ein Lauf im Repository-Wurzelverzeichnis wuerde das bewusst ungefuellte Knowledge-Skelett und die Arbeitsdaten des Templates mit Beispieldaten vermischen.
**Entscheidung:** `examples/offline-quickstart/` traegt zwei synthetische, vertragskonforme Transkriptionsdateien, ausgefuelltes Beispielwissen und einen Runner. Der Runner erzeugt einen separaten lokalen Projektordner, kopiert die realen Pipeline- und Frontend-Dateien dorthin und fuehrt Schritt 4 ohne LLM, Schritt 5, die explizite RelaxNG-Pruefung gegen TEI All und Schritt 6 ueber ihre oeffentlichen CLIs aus. Er leert alle Provider- und API-Key-Variablen vor den Kindprozessen. Ein Ownership-Sentinel bindet jedes Ziel an seinen absoluten Pfad. Rekursiver Ersatz setzt auch am kanonischen Default-Ziel einen unveraenderten Sentinel voraus; leere Ziele koennen erstmals befuellt werden. Pfade ueber symbolische Links oder Windows-Reparse-Points werden vor ihrer Aufloesung abgelehnt. Ein maschinenlesbarer Abschlussbericht dokumentiert Objektmenge, Pruefungen, Schema, Sentinel und Offline-Konfiguration.
**Begruendung:** Der Lauf prueft den tatsaechlichen Kommandozeilenpfad in frischen Prozessen. Das Template-Skelett, vorhandene Korpusdaten und Provider-Konfigurationen bleiben unberuehrt. Die fail-closed Zielpruefung verhindert, dass `--force` fremde Verzeichnisinhalte loescht. Synthetische Texte vermeiden Abhaengigkeiten von Bildrechten, externen Diensten und fachlich noch nicht abgenommenen Produktivdaten.
**Alternativen:** Vorgefertigte TEI- und Frontend-Ausgaben wurden verworfen, weil sie die Verarbeitungskette nicht pruefen. Das Kopieren der Fixtures in `data/processed/` des Template-Repositories wurde verworfen, weil Beispiel- und Nutzerdaten dann denselben Arbeitszustand teilen.

### ADR-008 Publikationsmetadaten und TEI-Download im statischen Serving-Root

**Datum:** 2026-08-26
**Kontext:** Der Datenvertrag versprach die Abbildung von Objektdaten auf `origDate`, die deterministische TEI-Erzeugung liess `date` und `repository` jedoch aus. Dadurch verlor der Frontend-Katalog die Datumswerte. Der Download-Button verwies auf `results/tei/`, obwohl der lokale Server und GitHub Pages ausschliesslich `docs/` ausliefern.
**Entscheidung:** Schritt 5 schreibt `metadata.date` als `history/origin/origDate` und `metadata.repository` als `msIdentifier/repository`. Semantisch gueltige Kalenderwerte erhalten `origDate/@when`; freie Datierungen bleiben als sicher maskierter Text ohne Normalisierungsattribut erhalten. Schritt 6 synchronisiert die erfolgreich verarbeiteten kanonischen TEI-Dateien als exakten XML-Spiegel nach `docs/tei/{object_id}.xml`; der Client verwendet diesen relativen Pfad fuer den Download.
**Begruendung:** Die Metadaten bleiben damit entlang des bestehenden Vertrags sichtbar und stellen die statische Filterbasis bereit. Alle publizierten Assets liegen unter demselben statischen Serving-Root und funktionieren lokal sowie im GitHub-Actions-Deployment. Der exakte Spiegel verhindert veraltete Download-Dateien nach einem fehlgeschlagenen oder verkleinerten Korpuslauf.
**Alternativen:** Das Entfernen des Download-Buttons wurde verworfen, weil TEI-Export eine zugesagte Standardfunktion ist. Ein relativer Zugriff auf `results/tei/` wurde verworfen, weil dieser Ordner ausserhalb des publizierten Wurzelverzeichnisses liegt.

### ADR-009 Lineage-Kategorien und deterministische TEI-Grenze

**Datum:** 2026-08-27
**Kontext:** README und Wissensbasis vermischten vier Herkunftsprojekte, geplante Forks, den inzwischen abgeschlossenen Schuchardt-Lauf und eigenständige Projektpipelines. Zugleich versprach die Dokumentation weiterhin einen optionalen LLM-Annotationspfad in Schritt 5, obwohl der Code seit dem Operatorentscheid vom 24.08.2026 ausschließlich deterministisch arbeitet.
**Entscheidung:** [[lineage]] unterscheidet reale Editionsfälle, technische Quellen, Prüfartefakte, direkte Projektinstanzen, architektonische Übertragungen und konzeptionelle Vorläufer. Hersch, SZD und DoCTA sind die drei realen Editionsfälle. Hersch und SZD bilden die empirische und technische Ausgangsbasis der Verallgemeinerung; DoCTA wendet die Architektur in einem eigenständigen Projekt an. Offline-Quickstart und lokaler HSA-Briefe-Fork sind technische Prüfartefakte. Schritt 5 bleibt ein deterministischer Basispfad. Semantische Annotation und komplexe Strukturen werden als projektspezifische deterministische Erweiterung oder als getrennte, dokumentierte Stufe implementiert. Tote Provider-Konfiguration und das ungenutzte Annotationsprompt entfallen.
**Begruendung:** Die Kategorien machen Forschungsbeitrag, Herkunft, Code-Abstammung und Evidenzumfang prüfbar. Die Dokumentation beschreibt damit den ausgeführten Codepfad und verhindert, dass ein Knowledge-Eintrag als bereits implementierte Transformation gelesen wird.
**Alternativen:** DoCTA als wörtlichen Fork zu bezeichnen wurde verworfen, weil keine gemeinsame Git-Abstammung oder Übernahme des Template-Dateivertrags belegt ist. Der alte LLM-Annotationspfad wurde verworfen, weil er keinen Codeleser besitzt und falsche Laufzeit- sowie Provenienzannahmen erzeugt.

### ADR-010 Gemeinsamer Kern aus Hersch/ZBZ, SZD und DoCTA

**Datum:** 2026-08-27
**Kontext:** Der aktuelle Vergleich der drei offiziellen Editionsfälle fand wiederkehrende Anforderungen, die die Vorlage bisher nur dokumentierte oder erst nach der Transkription abbildete. SZD und DoCTA steuern unterschiedliche Materialien mit eigenen Promptmodulen. Alle drei Projekte trennen maschinelle Ergebnisse von menschlich geprüften Textständen. ZBZ und DoCTA führen Statuswerte als kontrollierte Arbeitszustände. Alle drei beziehen Faksimiles aus externen Repositorien. Die Vorlage konnte Remote-Bilder erst aus einer bereits vorhandenen Transkriptionsdatei oder TEI-Datei laden und montierte die beschriebenen Promptschichten 2 bis 4 nicht im ausgeführten Code.
**Entscheidung:** `data/sources/manifest.json` wird der frühe Vertrag für Dokumentmetadaten, Remote-Seiten und Promptprofile. Schritt 2 führt ihn mit lokalen Quellen zusammen. Schritt 3 montiert Basisregeln, Profil, Metadaten und Objektregel und protokolliert Schichten und Hash. Jede erzeugte Seite erhält eine unveränderliche `transcription_raw`, einen bearbeitbaren Text und den menschlich kontrollierten Status `machine_unreviewed`. Die Statusfolge umfasst außerdem `in_review`, `human_verified` und `accepted`. Automatische Qualitätswerte bleiben davon getrennt. Die Modellantwort muss genau eine Seite pro Bild enthalten. Schritt 5 schreibt den niedrigsten Seitenstatus in `revisionDesc` und erzeugt aus derselben validierten Eingabe byte-identisches TEI.
**Begruendung:** Diese Funktionen treten in allen drei Fällen unter unterschiedlichen Bezeichnungen auf und lösen dieselben Vertragsprobleme. Der gemeinsame Kern stellt Herkunft, Vollständigkeit und Reife eines Textstands fest, bevor projektspezifische Annotation oder Publikation beginnt. Die frühe Manifest-Eingabe beseitigt den Zirkelschluss, nach dem Remote-Bilder erst aus einem Ergebnis der Transkription geladen werden konnten.
**Alternativen:** Automatische Ableitung eines Promptprofils aus freien Dokumenttyp-Bezeichnungen wurde verworfen, weil sie undeutliche und schwer reproduzierbare Zuordnungen erzeugt. Ein automatischer Wechsel des menschlichen Prüfstatus durch Qualitätssignale wurde verworfen, weil technische Plausibilität keine fachliche Kontrolle belegt. Layoutregionen, Entitätsmodelle und projektspezifische Markervokabulare bleiben Erweiterungen, weil ihre Verträge zwischen den drei Fällen deutlich abweichen.

### ADR-011 Version 0.9 und zustandsgebundene Vertrauensgrenzen

**Datum:** 2026-08-27
**Kontext:** Die Vorlage trug bereits die Bezeichnung 1.0, obwohl provider- und projektspezifische Läufe, fachliche Prüfung und Nutzerabnahme für den aktuellen Kern ausstanden. Die Prüfung der drei Editionsfälle und des Schuchardt-Laufs zeigte außerdem, dass bloße Dateiexistenz, Seitenzahlen und Zeichenmengen frühere Ergebnisse unzureichend an ihre Quellen banden.
**Entscheidung:** Das Repository bleibt bei Version `0.9.0` und kennzeichnet sich als Vorabversion. Schritt 1 bindet Renderings an PDF-Hash und Auflösung. Der Remote-Fetch bindet URL, Dateiname und Bildhash. Schritt 3 bindet Modell, montierte Anweisung, ausgeführte Chunk-Prompts und Bildbytes. Schritt 4 bindet Eingabe und Validierungsbefunde mit getrennten Zustands-Hashes. Schritt 5 akzeptiert ausschließlich den vollständigen Schritt-4-Vertrag und erzeugt TEI deterministisch. Schritt 6 prüft Faksimilebytes, veröffentlicht atomar und entfernt zurückgezogene oder veraltete Assets. Der Pages-Workflow prüft RelaxNG und den Status `accepted` vor dem Build. Python-Abhängigkeiten werden mit uv und `uv.lock` reproduzierbar installiert; Ruff, Formatprüfung und Pytest bilden das technische Gate.
**Begruendung:** Jede Abschlussaussage verweist damit auf einen benannten und überprüften Zustand. Technische Validierung, beobachtete Funktion, fachliche Prüfung und Nutzerabnahme bleiben unterscheidbar. Version 1.0 setzt eine ausdrückliche Nutzerabnahme sowie mindestens einen aktuellen provider- und projektspezifischen Lauf voraus.
**Alternativen:** Eine sofortige Bezeichnung als 1.0 wurde wegen der ausstehenden Abnahme verworfen. Fortgesetzte Existenz-Skips wurden verworfen, weil geänderte Quellen und Anweisungen sonst alte Ergebnisse als aktuell erscheinen lassen.
