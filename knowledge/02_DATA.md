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

Mindestanforderung fuer diplomatische Transkription: Aufloesung entsprechend etwa 300 DPI der Originalseite. Doppelseiten-Buchscans mit kleinem Satz reichen dafuer in der Regel nicht; solche Seiten werden in Schritt 3 als `page_type: gate_low_resolution` gegated statt transkribiert (siehe [[08_DATA_CONTRACT]]). Bei vorgelieferten Bildscans ist die Aufloesung an der Quelle sicherzustellen, `IMAGE_DPI` wirkt nur auf die PDF-Extraktion in Schritt 1.

## Automatisches Inventar

<!-- INVENTAR_START -->
(wird von `pipeline/02_analyze.py` generiert)
<!-- INVENTAR_END -->
