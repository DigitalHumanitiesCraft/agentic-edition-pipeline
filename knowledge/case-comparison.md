---
title: Vergleich der drei Editionsfälle
description: Empirischer Vergleich von Hersch/ZBZ, SZD und DoCTA und daraus abgeleitete Anforderungen an die Vorlage
tags: [case-study, comparison, template, requirements]
---

# Vergleich der drei Editionsfälle

## Zweck und Evidenzstand

Hersch/ZBZ, SZD und DoCTA sind die drei offiziellen Editionsfälle der Agentic Edition Pipeline. Der Vergleich untersucht ihre aktuellen Datenwege, Prüfverfahren und Editionsausgaben. Er bestimmt, welche Funktionen in den wiederverwendbaren Kern gehören und welche Regeln im einzelnen Editionsprojekt verbleiben.

Die Untersuchung beruht auf den Repository-Ständen vom 27. August 2026. SZD wurde am Commit `cc45c9345a47` geprüft. DoCTA wurde am Commit `d0a4a5305ce4` geprüft. Für Hersch/ZBZ bildet `c0cc741739c8` den Git-Anker. Ergänzend wurde der umfangreich weiterentwickelte lokale Arbeitsstand gelesen. Aussagen zu dessen neuen Entity- und Kurationsfunktionen gelten deshalb als beobachteter Arbeitsstand ohne reproduzierbaren Commit-Anker.

Der Vergleich ist eine technische und konzeptionelle Prüfung. Er umfasst keine erneute Verarbeitung der drei vollständigen Korpora, keine fachliche Kontrolle der Transkriptionen und keine Nutzerabnahme.

## Offizielle Fälle

| Fall | Aktueller Katalogstand | Quellen und Editionsziel | Beitrag zur Vorlage |
|---|---:|---|---|
| Hersch/ZBZ, `zbz-ocr-tei` | 285 Dokumente und 4.117 Seiten | Publizierte Texte und Digitalisate der Jeanne-Hersch-Ausgabe, kuratierbares TEI nach dem ZBZ-Profil | Getrennte Verarbeitungsströme, menschlich gesetzte Statuswerte, projektspezifische Schemaprüfung und nachvollziehbare Kurationsschritte |
| SZD, `szd-htr-ocr-pipeline` | 2.452 Objekte und 17.132 Seiten in fünf Sammlungen | Heterogener Nachlassbestand mit Handschrift, Typoskript, Druck, Formularen und Tabellen | Materialbezogene Promptprofile, fortschreibbares Page-JSON, kalibrierte Qualitätssignale und konservative Überführung von Transkriptionsmarkern in TEI |
| DoCTA, `DoCTA` | 65 Dokumente und 692 registrierte Seiten | Tiroler Rechnungsbücher, Inventare, Kopialbücher und Gerichtsordnungen aus Transkribus und IIIF | Unveränderliche Transkriptionsläufe, Review-Rueckweg, getrennte Referenzklassen, Entity-Extraktion, arithmetische Prüfungen und regelbasierte TEI-Erzeugung mit Projektgates |

Die Zahlen beschreiben die jeweils beobachteten Repository-Kataloge. Sie sind keine Aussage über den vollständigen physischen Bestand oder den fachlich abgenommenen Editionsumfang.

## Vergleich der Verarbeitung

| Dimension | Hersch/ZBZ | SZD | DoCTA | Folgerung für den gemeinsamen Kern |
|---|---|---|---|---|
| Eingang | Lokale und publizierte Digitalisate, OCR-Ausgaben und Katalogdaten | Remote-Bilder aus GAMS und fünf Sammlungen | Transkribus-Dokumente mit IIIF-Bildern | Ein Quellenregister muss lokale Dateien und entfernte Faksimiles vor der Transkription gemeinsam beschreiben können. |
| Materialsteuerung | Vier Layoutklassen steuern OCR und Layoutanalyse | Neun Promptgruppen steuern die Transkription nach Dokumenttyp | Getrennte Promptmodule für Rechnungsbücher und Inventare | Ein Dokument wählt ein versioniertes Promptprofil. Objektbezogene Sonderregeln bilden eine weitere, explizite Schicht. |
| Arbeitsformat | OCR-Markdown, Layout-JSON und PAGE XML als getrennte Ströme | Page-JSON v0.2 mit optionalen Regionen, dazu PAGE/METS und TEI | Seitenregister mit IIIF, Inhaltsklasse, Prüffeld und unveränderlichen Läufen | Der Kern braucht einen kleinen Seitenvertrag. Layout und weitere Austauschformate bleiben optionale Ströme. |
| Textstände | OCR, Layout, TEI und Entities besitzen eigene Zustände | Maschinelle Rohfassung, bearbeitete Transkription und Bearbeitungsgeschichte bleiben getrennt | Jeder Lauf bleibt unverändert. Automatisch geprüfter und fachlich akzeptierter Text sind eigene Zustände. | Maschinelle Rohfassung und bearbeitbarer Text werden getrennt gespeichert. Der Prüfstatus wird durch menschliche Handlungen verändert. |
| Prüfvokabular | `unverifiziert`, `in_arbeit`, `verifiziert` je Strom | menschlich geprüft, agentisch geprüft und ungeprüft | `unbearbeitet`, `maschinell`, `gesichtet`, `abgenommen` je Seite | Die Vorlage verwendet eine kleine übergreifende Reifefolge und lässt Projekte ihre sichtbaren Bezeichnungen darauf abbilden. |
| Qualitätsprüfung | 25 Referenz-TEIs, Fidelity- und Scope-Zerlegung, Bootstrap-Intervalle | Referenzobjekte aus allen Promptgruppen und korpusspezifisch kalibrierte Prüfsignale | Fester Benchmark, mehrere Wiederholungen je Bedingung und getrennte Referenzklassen | Jede Auswertung nennt Referenzklasse, Normalisierung, Modell, Promptstand und Stichprobe. Universelle Qualitätsgrenzen werden vermieden. |
| TEI-Erzeugung | Regelbasierter Grundbau, seitenweise Verfeinerung und abschließende Schemaprüfung | Regelbasierte Konvertierung mit konservativer Markerabbildung und Rundlaufprüfung | Regelbasierter Builder mit Bildregionen und Arbeitsschritt-Provenienz | Der Basispfad bleibt regelbasiert. Das Projekt wählt sein Schema und implementiert zusätzliche Strukturen als geprüfte Erweiterung. |
| Entitäten | Geschlossene Kandidatenliste, Vorschau vor Freigabe, keine freie ID-Erzeugung durch das Modell | Markerabbildung mit vorsichtiger TEI-Anreicherung | Entity-Kandidaten werden extrahiert und nur bei eindeutiger Textposition in den geregelten Pfad uebernommen | Semantische Anreicherung braucht eine eigene Herkunfts- und Freigaberegel. Sie gehört nicht automatisch in jede Transkription. |
| Publikation | Kanonische Dateien und erzeugter Website-Spiegel sind getrennt | Kurationsansicht über den Arbeitsdaten | Statische Edition mit Quellregister, Viewer, Benchmark sowie Gates gegen `docta.rng` und Projektregeln | Kanonische Daten bleiben außerhalb der Publikationskopie. Der Website-Bestand wird regelbasiert daraus erzeugt. |

## Gemeinsamer Kern

Aus allen drei Fällen ergeben sich folgende verbindliche Anforderungen an die Vorlage.

1. Das Quellenregister erfasst Dokumentidentität, Metadaten, Seitenfolge, Faksimile-Adressen und Promptprofil vor dem ersten Modellaufruf.
2. Die Transkriptionsanweisung entsteht zur Laufzeit aus Basisregeln, Dokumentprofil, Metadatenkontext und einer optionalen Objektregel. Die tatsächlich verwendeten Schichten und ihr gemeinsamer Hash werden protokolliert.
3. Jede Modellseite bewahrt ihre ursprüngliche Ausgabe in `transcription_raw`. `transcription` ist der bearbeitbare Textstand.
4. Jede Seite trägt einen menschlich kontrollierten Prüfstatus. Die gemeinsame Folge lautet `machine_unreviewed`, `in_review`, `human_verified`, `accepted`. Automatische Qualitätsbefunde ändern diesen Status nicht.
5. Jede Bildseite muss genau einer Seite in der Modellantwort entsprechen. Fehlende oder zusätzliche Seiten beenden die Verarbeitung des Dokuments am Vertragsübergang.
6. Die TEI-Erzeugung ist für denselben validierten Eingabestand byte-identisch. Der niedrigste Seitenstatus wird im `revisionDesc` ausgewiesen.
7. Schema und zusätzliche Prüfregeln werden im Editionsprojekt gewählt. Die Vorlage stellt den Auswahl- und Prüfmechanismus bereit.
8. Evaluationen verwenden feste Manifeste. Referenzklasse, Normalisierungsprofil, Stichprobe, Modell und Promptstand gehören zum Ergebnis.

## Projektspezifische Erweiterungen

Die folgenden Funktionen werden in der Vorlage als Erweiterungspunkte dokumentiert. Ihre fachlichen Regeln lassen sich aus keinem der drei Fälle allgemein ableiten.

| Erweiterung | Zuständiges Projektwissen |
|---|---|
| ZBZ-Entity-Liste, GND-Zuordnung und dreistufige Kandidatenentscheidung | Hersch/ZBZ |
| Neun SZD-Promptgruppen, Page-JSON-Regionen, METS/MODS und SZD-Markervokabular | SZD |
| Praxeologische Ereignis- und Beziehungsmodellierung, SiCProD-Verknüpfung und Rechnungslogik | DoCTA |
| Konkretes RelaxNG-Schema, Editionsrichtlinien und Freigaberegeln | jeweiliges Editionsprojekt |

## Umsetzung in der Vorlage

Die Überarbeitung vom 27. August 2026 setzt den gemeinsamen Kern an vier Stellen um.

- `data/sources/manifest.json` dient als früher Einstieg für Katalogdaten, Remote-Faksimiles und Promptprofile. Schritt 2 führt diese Angaben mit lokal gefundenen Dateien zusammen.
- Schritt 3 montiert die vier Promptschichten tatsächlich zur Laufzeit und protokolliert Schichten, Profil und Hash.
- Schritt 3 legt `transcription_raw` und den anfänglichen Prüfstatus an. Schritt 4 reicht beide unverändert weiter.
- Schritt 5 schreibt den zusammengefassten Prüfstatus in den TEI-Header und verwendet den Eingabezeitstempel. Wiederholte Erzeugung aus derselben validierten Datei bleibt damit byte-identisch.

Layoutregionen, Entitätsfreigabe und projektspezifische TEI-Strukturen bleiben Erweiterungen. Ihre Aufnahme in den Kern setzt einen zweiten realen Fall mit demselben Datenbedarf und einen automatisierten Vertragsnachweis voraus.

## Verwandte Dokumente

[[lineage]] ordnet die drei Fälle historisch ein. [[08_DATA_CONTRACT]] definiert den gemeinsamen Seitenvertrag. [[decisions]] dokumentiert die daraus getroffenen Architekturentscheidungen.
