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
    "prompt_hash": "abc123def456"
  },
  "object_id": "doc1",
  "source_images": ["doc1_p001.png"],
  "metadata": {
    "title": "Brief an N. N. vom 22. Mai 1901",
    "language": "de",
    "date": "1901-05-22",
    "object_type": "Korrespondenz",
    "image_urls": {
      "1": "https://example.org/o:doc1/IMG.1",
      "2": "https://example.org/o:doc1/IMG.2"
    }
  },
  "pages": [
    {
      "page": 1,
      "transcription": "Erste Zeile\nZweite Zeile\n\nZweiter Absatz",
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
    "gate_pages": 0,
    "foreign_pages": 0,
    "content_pages": 1,
    "needs_review": false
  }
}
```

## Feldregeln

**Pflichtfelder.** `object_id`, `pages` auf oberster Ebene. Jede Seite traegt `page` (Seitennummer, ganzzahlig, ab 1) und `transcription` (der Seitentext, Zeilenumbrueche als `\n`, Absatzgrenzen als Leerzeile).

**`metadata`.** Objektmetadaten, die von Schritt 3 bis Schritt 6 unveraendert durchgereicht werden. `title` wird zum TEI `titleStmt/title`, `language` (ISO-Code) zu `langUsage/language`, `date` zu `history/origin/origDate` und `repository` zu `msIdentifier/repository`. Kalenderwerte in den Formen `YYYY`, `YYYY-MM` und `YYYY-MM-DD` erhalten nach semantischer Pruefung ein gleichlautendes `origDate/@when`. Freie Datierungen bleiben XML-escaped als Elementtext ohne normalisierendes Attribut erhalten. `image_urls` deklariert Remote-Faksimiles als Objekt Seitennummer-zu-URL (JSON-Schluessel sind Strings); eine positionsgleiche Liste wird ebenfalls akzeptiert. Schritt 3 uebernimmt Metadaten aus der Modellantwort, soweit vorhanden; fehlende Felder ergaenzt der Operator vor Schritt 5, sonst faellt der TEI-Header auf die `object_id` und `de` zurueck.

**Seitenfelder optional.** `notes` (Freitext des Transkribierenden), `page_type` und `foreign_paragraphs`:

| `page_type` | Bedeutung | Wirkung in Schritt 4 und 5 |
|---|---|---|
| fehlt oder leer | normale Inhaltsseite | Absaetze als `<p>` |
| `blank` | deklarierte Leerseite | nur `<pb/>`, keine Markierungsnote |
| `gate_low_resolution` | Bildqualitaet reicht fuer diplomatische Transkription nicht | `<note type="gate" subtype="low_resolution">`, Objektstatus hoechstens `needs_review` |
| `foreign_text` | ganze Seite gehoert einem anderen Text/Verfasser | Text als `<note type="foreign">`, nicht im edierten Body |

`foreign_paragraphs` listet auf gemischten Seiten die 0-basierten Absatzindizes, die Fremdtext sind; Schritt 5 setzt diese Absaetze als `<note type="foreign">` statt `<p>`. Eine leere `transcription` ohne deklarierten `page_type` erzeugt in Schritt 5 eine `<note type="empty">`, damit die Verifikation eine echte Leerseite von einer stillen Luecke unterscheiden kann.

**`quality_signals`.** Von Schritt 3 berechnet; bei manuell oder agentisch erzeugten Dateien optional. `needs_review` bedeutet "unverifizierte Transkription" und fuehrt in Schritt 4 zu `needs_review`, nie allein zu `problematic`.

**`_meta`.** Provenienzblock, bei jeder erzeugenden Stufe Pflicht (CLAUDE.md-Regel). Manuell erzeugte Dateien tragen mindestens `script` (wer oder was erzeugt hat) und `timestamp`.

## Manuell oder agentisch erzeugte Transkriptionen

Eine ausserhalb von Schritt 3 erzeugte Transkription (bestehende HTR-Ausgabe, agentische Vision-Transkription) wird schemakonform direkt nach `data/processed/transcriptions/{object_id}.json` geschrieben; die Pipeline laeuft dann ab Schritt 4 unveraendert. Es gibt bewusst keinen Import-Modus in Schritt 3: die Stufe ruft immer einen Vision-Provider und bricht ohne API-Key mit einer klaren Fehlermeldung ab.

Fuer das Inventar (Schritt 2) koennen strukturierte Transkriptions-JSON zusaetzlich unter `data/sources/text/` liegen; `02_analyze.py` zaehlt ihre Seiten aus dem `pages`-Array (`source_type: transcription`).

## Related

[[00_INDEX]], [[02_DATA]] (Korpusbeschreibung), [[04_TEI_MAPPING]] (TEI-Abbildung), `pipeline/prompts/transcription.md` (Layer 1 erzwingt dieses Schema).
