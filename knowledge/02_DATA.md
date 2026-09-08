---
title: Daten und Korpus
description: Quellentypen, Korpusumfang, Inventar, Auswahlkriterien
tags: [data, corpus, inventory]
---

# Daten und Korpus

## Quellentyp

- [ ] Nur Bilder (Digitalisate, Scans)
- [ ] Nur Text (bestehende Transkriptionen, Plaintext, PAGE-XML)
- [ ] Bilder und Text (Digitalisate mit zugehoerigen Transkriptionen)
- [ ] PDFs (die in Bilder zerlegt werden muessen)

## Speicherort

[TODO: Wo liegen die Daten? Pfad zu `data/sources/`]

Externe Katalogdaten, Remote-Faksimiles und die Auswahl des Transkriptionsprofils werden vor dem ersten Modelllauf in `data/sources/manifest.json` deklariert. Schritt 2 fuehrt diese Angaben mit lokal gefundenen Dateien zusammen. Lokale Korpora ohne zusaetzliche Angaben lassen die Dokumentliste im Manifest leer.

## Korpusumfang

| Feld | Wert |
|---|---|
| Dokumente | [TODO] |
| Seiten (geschaetzt) | [TODO] |
| Sprachen | [TODO] |
| Zeitraum | [TODO] |

## Auswahlkriterien

[TODO: Nach welchen Kriterien wurden die Quellen ausgewaehlt? Vollstaendig, repraesentativ, exemplarisch? Was ist nicht enthalten und warum?]

## Dokumenttypen

[TODO: Welche Dokumenttypen kommen vor? Handschrift, Typoskript, Druck, Formular, Tabelle, Zeitungsausschnitt, Korrespondenz, etc. Diese Information beeinflusst die Prompt-Gruppierung in Schritt 3.]

Jeder wiederholt auftretende Materialtyp erhaelt ein eigenes, evaluiertes Promptprofil unter `pipeline/prompts/profiles/`. Das Quellenmanifest weist Dokumente mit `prompt_profile` einem solchen Profil zu. Einzelne Ausnahmen werden als Objektregel unter `pipeline/prompts/objects/{object_id}.md` dokumentiert.

## Qualitaet der Digitalisate

[TODO: Aufloesung, Farbtiefe, Qualitaetsprobleme (verblasst, beschnitten, durchscheinend)?]

Die Eignung wird am tatsächlich übergebenen Bild geprüft, insbesondere bei kleiner Schrift und Doppelseiten. Eine nominelle DPI-Angabe allein bestätigt keine Lesbarkeit. `IMAGE_DPI` wirkt nur auf die PDF-Rasterisierung und kann fehlende Quelldetails nicht wiederherstellen. Der Transkriptionsvertrag erlaubt `page_type: gate_low_resolution` für unzureichende Bilder; die Zuverlässigkeit dieser Modellklassifikation ist am Korpus zu prüfen.

## Automatisches Inventar

<!-- INVENTAR_START -->
(wird von `pipeline/02_analyze.py` generiert)
<!-- INVENTAR_END -->

## Herkunft und Eingaberollen

[TODO: Für jede Quellenart Herkunft, Zugriff, Rechte, Auswahl und Verarbeitung festhalten.]

Katalogmetadaten können aus einer vorhandenen TEI-Datei stammen, während der Text neu aus Bildern erzeugt wird. Beide Herkunftswege sind einzeln zu dokumentieren. Eine bestehende Transkription kann als Eingabe oder als Vergleichsreferenz dienen. Ihre Rolle bestimmt, ob ein unabhängiger Erkennungsvergleich möglich ist.

Das Manifest nimmt Objektmetadaten und Seitenfolgen auf. Detaillierte feldbezogene Herkunft und Quellenbelege sind im Projekt gesondert zu dokumentieren; das Template erzeugt sie nicht automatisch.

## Auswahl eines Prüfbestands

[TODO: Benannte Dokumente und Seiten mit Auswahlgrund, Materialtyp, Sprache, Layout und relevanten Schwierigkeiten festlegen.]

Ein erster Lauf mit `--sample N` verarbeitet die ersten N Dokumente. Die Auswahl belegt keine Repräsentativität. Ein Prüfbestand soll die behauptete Anwendung abdecken und seine ausgeschlossenen Fälle nennen. Maßgeblich ist die [Evaluationsreferenz](../reference/evaluation.md).

Die Übernahme einer technischen Methode überträgt keine Nutzungsrechte an Texten, Bildern oder Katalogdaten.
