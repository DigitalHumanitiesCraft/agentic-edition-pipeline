---
title: Datenvertrag der Pipeline
description: Verbindliches JSON-Schema der Transkriptionsdaten von Schritt 3 bis Schritt 6
tags: [data-contract, schema, pipeline]
---

# Datenvertrag der Pipeline

Ein einziger Datenvertrag verbindet die Schritte 3 (Transkription), 4 (Validierung), 5 (TEI-Annotation) und 6 (Frontend). Jede Transkriptionsdatei unter `data/processed/transcriptions/{object_id}.json` folgt diesem Schema, gleichgueltig ob sie vom Pipeline-Skript, von Hand oder agentisch erzeugt wurde. Schritt 4 reicht `metadata` und `pages` unveraendert durch, Schritt 5 liest beide aus der validierten Datei, Schritt 6 liest das generierte TEI.

## Schema

```json
{
  "_meta": {
    "script": "03_transcribe.py",
    "timestamp": "ISO-8601",
    "pipeline_step": 3,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "prompt_template": "transcription.md",
    "prompt_profile": "correspondence",
    "prompt_layers": [
      "transcription.md",
      "profiles/correspondence.md",
      "inventory:metadata",
      "objects/doc1.md"
    ],
    "prompt_hash": "abc123def456",
    "source_metadata_hash": "123def456abc",
    "raw_transcription_hash": "456abc123def",
    "executed_prompts": [
      {
        "chunk": 1,
        "pages": [1],
        "attempt": 1,
        "prompt_hash": "def456abc123"
      }
    ],
    "source_images": [
      {
        "page": 1,
        "filename": "doc1_p001.png",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      }
    ],
    "source_images_hash": "789abc123def"
  },
  "object_id": "doc1",
  "source_images": ["doc1_p001.png"],
  "metadata": {
    "title": "Brief an N. N. vom 22. Mai 1901",
    "language": "de",
    "date": "1901-05-22",
    "object_type": "Korrespondenz",
    "image_urls": {
      "1": "https://example.org/o:doc1/IMG.1"
    }
  },
  "pages": [
    {
      "page": 1,
      "transcription": "Erste Zeile\nZweite Zeile\n\nZweiter Absatz",
      "transcription_raw": "Erste Zeile\nZweite Zeile\n\nZweiter Absatz",
      "review": {
        "status": "machine_unreviewed",
        "history": []
      },
      "notes": "",
      "page_type": "",
      "foreign_paragraphs": []
    }
  ],
  "confidence": "high",
  "confidence_notes": "",
  "quality_signals": {
    "page_types": ["content"],
    "total_chars": 42,
    "chars_per_page": 42.0,
    "blank_pages": 0,
    "undeclared_empty_pages": 0,
    "gate_pages": 0,
    "foreign_pages": 0,
    "content_pages": 1,
    "needs_review": false
  }
}
```

## Feldregeln

**Pflichtfelder.** `_meta`, `object_id` und `pages` stehen auf oberster Ebene. `object_id` ist ein portabler Datei- und Objektbezeichner; reservierte Windows-Namen und Bezeichner, die sich nur in der Grossschreibung unterscheiden, sind unzulaessig. Jede Seite traegt `page` (Seitennummer, ganzzahlig, lueckenlos ab 1), `transcription` (der Seitentext, Zeilenumbrueche als `\n`, Absatzgrenzen als Leerzeile) und `review` mit `status` und `history`.

**Textstaende.** Schritt 3 schreibt die unveraenderte erste Modellantwort jeder Seite in `transcription_raw` und denselben Ausgangstext in `transcription`. Ein geordneter `raw_transcription_hash` im Provenienzblock bindet diese Rohtexte an den Modelllauf. Spaetere Korrekturen veraendern ausschließlich `transcription`. `transcription_raw` bleibt erhalten und darf durch einen neuen Modelllauf nur in einer neuen Ausgabedatei ersetzt werden. `--force` verweigert deshalb das Ueberschreiben eines Objekts, sobald eine Seite Review-History traegt; ein neuer Modelllauf erhaelt einen neuen Objektbezeichner und bewahrt den geprueften Vorgaenger.

**Menschlicher Pruefstatus.** `review.status` verwendet die Folge `machine_unreviewed`, `in_review`, `human_verified`, `accepted`. Ein Modelllauf beginnt mit `machine_unreviewed`. Die erlaubten Uebergaenge sind `machine_unreviewed` → `in_review`, `in_review` → `machine_unreviewed` oder `human_verified`, `human_verified` → `in_review` oder `accepted` und `accepted` → `in_review`. Jeder Eintrag in `review.history` nennt Ausgangsstatus, Zielstatus, menschlichen Akteur und einen zeitzonenbezogenen ISO-Zeitstempel; die Eintraege stehen chronologisch. Die Zustaende `human_verified` und `accepted` binden zusaetzlich den vollstaendigen TEI-wirksamen Seitenstand mit `page_state_hash`. Dazu gehoeren Text, Seitentyp, Fremdtextzuordnung und Notizen. Eine spaetere Aenderung macht diese Entscheidung ungueltig und wird vor Schritt 4 blockiert. Der kanonische Befehl lautet `uv run python pipeline/update_review.py --object ID --page N --status STATUS --actor REVIEWER`. Danach werden die Schritte 4 bis 6 mit `--force` erneut ausgefuehrt.

**`metadata`.** Objektmetadaten, die von Schritt 3 bis Schritt 6 unveraendert durchgereicht werden. `title` wird zum TEI `titleStmt/title`, `language` (ISO-Code) zu `langUsage/language`, `date` zu `history/origin/origDate`, `repository` zu `msIdentifier/repository` und `signature` zu `msIdentifier/idno[@type='shelfmark']`. Die `object_id` erhaelt ein eigenes `idno[@type='object-id']`. Kalenderwerte in den Formen `YYYY`, `YYYY-MM` und `YYYY-MM-DD` erhalten nach semantischer Pruefung ein gleichlautendes `origDate/@when`. Freie Datierungen bleiben XML-escaped als Elementtext ohne normalisierendes Attribut erhalten. `image_urls` deklariert Remote-Faksimiles als Seitennummer-zu-URL (JSON-Schluessel sind Strings); eine positionsgleiche Liste wird ebenfalls akzeptiert. Leere oder fehlende Titel und Sprachwerte fallen im TEI auf `object_id` und `de` zurueck. Manifestmetadaten haben Vorrang vor Modellvorschlaegen.

**Seitenfelder optional.** `notes` (Freitext des Transkribierenden), `page_type` und `foreign_paragraphs`:

| `page_type` | Bedeutung | Wirkung in Schritt 4 und 5 |
|---|---|---|
| fehlt oder leer | normale Inhaltsseite | Absaetze als `<p>` |
| `blank` | deklarierte Leerseite | nur `<pb/>`, keine Markierungsnote |
| `gate_low_resolution` | Bildqualitaet reicht fuer diplomatische Transkription nicht | `<note type="gate" subtype="low_resolution">`, Objektstatus hoechstens `needs_review` |
| `foreign_text` | ganze Seite gehoert einem anderen Text/Verfasser | Text als `<note type="foreign">`, nicht im edierten Body |

`foreign_paragraphs` listet auf gemischten Seiten die 0-basierten Absatzindizes, die Fremdtext sind; Schritt 5 setzt diese Absaetze als `<note type="foreign">` statt `<p>`. Eine leere `transcription` ohne deklarierten `page_type` erzeugt in Schritt 5 eine `<note type="empty">`, damit die Verifikation eine echte Leerseite von einer stillen Luecke unterscheiden kann.

**`quality_signals`.** Von Schritt 3 berechnet; bei manuell oder agentisch erzeugten Dateien optional. Wenn der Block vorhanden ist, muessen alle Zaehler, Seitentypen und das boolesche Feld `needs_review` vollstaendig und typisiert sein. `needs_review` bedeutet "unverifizierte Transkription" und fuehrt in Schritt 4 zu `needs_review`. Eine dokumentweite Modellkonfidenz `low` begrenzt den Status ebenfalls auf `needs_review` und bleibt zusammen mit `confidence_notes` erhalten.

**`_meta`.** Provenienzblock, bei jeder erzeugenden Stufe Pflicht. Ein tatsaechlicher Lauf von Schritt 3 dokumentiert Provider, Modell, Basistemplate, das optionale Promptprofil, die verwendeten Promptschichten, den Hash der vollstaendig montierten Anweisung, den Hash der vollstaendigen autoritativen Manifestmetadaten, den Hash der geordneten Modellrohtexte, jeden ausgefuehrten Chunk- und Retry-Prompt sowie den geordneten SHA-256-Zustand der eingelesenen Bilddateien. Die Erstaufrufe decken jede Seite genau einmal ab; Retry-Eintraege wiederholen denselben Chunk. Manuell erzeugte Dateien tragen mindestens `script` und einen zeitzonenbezogenen `timestamp`; sie behaupten keinen Lauf von Schritt 3 und verwenden beispielsweise `pipeline_step: 0`.

**`transcription_meta`.** Schritt 4 setzt seinen eigenen Provenienzblock in `_meta` und bewahrt den Provenienzblock der Transkription unter `transcription_meta`. Sein `input_state_hash` bindet den vollstaendigen geprueften Transkriptionsstand. Der getrennte `validation_result_hash` bindet Regelbefunde, Seitenstatistik, optionales Modellurteil und `overall_status`. Schritt 5 akzeptiert nur einen formal vollstaendigen Schritt-4-Stand, dessen beide Hashes und Statistik weiterhin zu Metadaten, Seiten, Rohtext, Review-Verlauf, Konfidenz und Bildbindung passen. Eine Aenderung am Transkriptionsstand erfordert einen erneuten Lauf von Schritt 4.

**`source_images`.** Die Liste auf oberster Ebene nennt die lokalen Bilddateien in Seitenreihenfolge. Bei einem Lauf von Schritt 3 muss sie exakt den Dateinamen im Byte-Zustand unter `_meta.source_images` entsprechen. Schritt 5 prueft die aktuellen Dateien gegen diesen Zustand. Schritt 6 verwendet bei gebundener TEI einen verifizierten lokalen Snapshot und kann im Pages-Checkout auf die eingecheckten Dateien unter `docs/images/{object_id}/` zurueckgreifen. Abweichende, fehlende oder zusaetzliche Faksimiles blockieren den Build.

## Quellenregister vor der Transkription

`data/sources/manifest.json` verwendet die Version `0.1` und beschreibt Dokumente, deren Metadaten oder Faksimiles nicht aus lokalen Dateinamen hervorgehen. Ein Dokumenteintrag kann `id`, `prompt_profile`, `metadata` und `pages` tragen. Manifestseiten stehen in Bildreihenfolge und werden ohne Luecke ab 1 nummeriert. Innerhalb eines Dokuments deklarieren entweder alle Seiten `image_url` oder keine. Schritt 2 normalisiert die Adressen nach `metadata.image_urls` im Inventar. `pipeline/fetch_facsimiles.py --from-manifest` materialisiert die Dateien mit einem begrenzten Retry und einem konfigurierbaren Mindestabstand. Das Materialisierungsmanifest bindet jede URL an Dateiname und SHA-256; Schritt 3 verwirft lokale Bytes, deren URL oder Hash nicht mehr zum Inventar passt.

## Vollstaendigkeitsregel fuer Modellantworten

Schritt 3 verlangt genau einen Seiteneintrag pro uebergebenem Bild. Bei einer Verarbeitung in Teilmengen gibt jeder Chunk die ihm zugewiesenen globalen Seitennummern unveraendert zurueck. Fehlende, doppelte, neu nummerierte oder zusaetzliche Modellseiten verletzen den Datenvertrag und erzeugen keine Transkriptionsdatei. Bildordner ohne Manifest werden natuerlich nach den Ziffern im Dateinamen sortiert; Gross- und Kleinschreibung der Bildsuffixe ist unerheblich.

## Manuell oder agentisch erzeugte Transkriptionen

Eine ausserhalb von Schritt 3 erzeugte strukturierte Transkription wird schemakonform direkt nach `data/processed/transcriptions/{object_id}.json` geschrieben; die Pipeline laeuft dann ab Schritt 4. Plaintext, PAGE XML und andere Austauschformate muessen zuvor durch eine projektspezifische Konvertierung in diesen Vertrag ueberfuehrt werden. Schritt 2 inventarisiert solche Dateien, fuehrt diese Umwandlung aber nicht aus. Schritt 3 bleibt der Vision-Provider-Pfad und bricht ohne API-Key mit einer klaren Fehlermeldung ab.

Fuer das Inventar (Schritt 2) koennen strukturierte Transkriptions-JSON zusaetzlich unter `data/sources/text/` liegen; `02_analyze.py` zaehlt ihre Seiten aus dem `pages`-Array (`source_type: transcription`).

## Related

[[00_INDEX]], [[02_DATA]] (Korpusbeschreibung), [[04_TEI_MAPPING]] (TEI-Abbildung), `pipeline/prompts/transcription.md` (Layer 1 erzwingt dieses Schema).
