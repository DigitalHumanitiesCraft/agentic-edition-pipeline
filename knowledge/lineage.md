---
title: Herkunft und reale Fallbeiträge
description: Verhältnis der drei Editionsfälle zur wiederverwendbaren Pipeline und zu ihren technischen Prüfartefakten
tags: [lineage, integration, template, case-study]
---

# Herkunft und reale Fallbeiträge

## Gegenstand

Die Agentic Edition Pipeline ist eine wiederverwendbare Projektvorlage für digitale wissenschaftliche Editionen. Sie verbindet ausführbare Verarbeitungsschritte, einen gemeinsamen Datenvertrag, Projektwissen, Prüfpunkte, Schema-Validierung und eine statische Publikationsoberfläche. Jedes Editionsprojekt ergänzt eigene Quellen, Editionsregeln, ein TEI-Profil, den Forschungszweck und die fachlichen Abnahmeentscheidungen.

Die drei realen Editionsfälle sind die Hersch-Pipeline, SZD-HTR und DoCTA. Hersch und SZD-HTR entstanden vor dem allgemeinen Repository. Aus ihnen wurden Erfahrungen, Verarbeitungsschritte und Prüfverfahren in die Vorlage überführt. DoCTA wendet die daraus entwickelte Architektur in einem eigenständigen Repository auf einen weiteren Quellenbestand an.

## Drei reale Editionsfälle

| Fall | Repository | Beitrag | Verhältnis zur Vorlage |
|---|---|---|
| Hersch | `zbz-ocr-tei` | Durchgängige Verarbeitung von PDF-Digitalisaten bis zu geprüften TEI-Dateien, projektspezifisches Schema und überprüfbare Kurationsschritte | Grundlegender Fall, der vor der wiederverwendbaren Vorlage entstand |
| SZD | `szd-htr-ocr-pipeline` | Verarbeitung eines großen und heterogenen Bestands, materialbezogene Promptgruppen, Qualitätssignale und Korrekturoberfläche | Grundlegender Fall, der vor der wiederverwendbaren Vorlage entstand |
| DoCTA | `DoCTA` | Übertragung der Architektur auf Tiroler Gerichtsakten mit Transkribus-Quellen, getrennten Referenzständen und Prüfkandidaten, regelbasierter TEI-Erzeugung und statischer Edition | Eigenständige Anwendung der verallgemeinerten Architektur |

Diese drei Fälle bilden die empirische Grundlage des Vorhabens. Hersch und SZD zeigen, aus welchen realen Editionsproblemen die allgemeine Pipeline entwickelt wurde. DoCTA zeigt ihre Übertragung auf einen neuen Bestand. Die unterschiedliche Entstehungsgeschichte bleibt für Aussagen über Wiederverwendung und technische Abstammung relevant.

[[case-comparison]] untersucht die drei aktuellen Repository-Stände entlang derselben technischen und editorischen Dimensionen. Das Dokument leitet daraus den gemeinsamen Kern der Vorlage und die Grenzen projektspezifischer Erweiterungen ab.

## Technische Quellen

Zwei weitere Projekte lieferten einzelne technische Muster für den wiederverwendbaren Kern.

| Repository | Übernommener Beitrag |
|---|---|
| `co-ocr-htr` | Abstraktion externer Modelldienste, kombinierte Validierung und PAGE-XML-Verarbeitung |
| `teiCrafter` | TEI-Bearbeitung, Schemaführung, semantische Annotation und bearbeitbare Projektprofile |

Sie gehören zur technischen Herkunft. Die drei primären Forschungsfälle bleiben Hersch, SZD und DoCTA.

## Technische Prüfartefakte

### Künstliches Kurzbeispiel

`examples/offline-quickstart/` erzeugt ein isoliertes lokales Projekt aus der aktuellen Vorlage. Es prüft die regelbasierte Validierung, TEI-Erzeugung, Schema-Validierung und den Aufbau der Oberfläche an zwei künstlichen Objekten. Der Test umfasst den ausführbaren Programmweg und seine Sicherheitsgrenzen. Externe Modelldienste, Faksimiles und fachliche Editionsqualität liegen außerhalb seines Prüfumfangs.

### Schuchardt-Prüfinstanz

Das lokale Repository `hsa-letters-pipeline` wurde aus dem Vorlagenstand `7328482` erzeugt. Es verarbeitete 18 Briefe aus dem Hugo Schuchardt Archiv von vorbereiteten Transkriptionen über Validierung und TEI-Erzeugung bis zu Oberfläche und Auswertung. Alle 18 TEI-Dateien waren im Instanzstand `a28dee27` gegen TEI All valide. Die automatische Transkription über einen externen Modelldienst wurde wegen eines ungültigen Zugangs nicht ausgeführt. Der Lauf erzeugte 16 Befunde zur Vorlage, deren blockierender Anteil später in die Vorlage übernommen wurde.

Die Schuchardt-Instanz belegt einen technischen Lauf an realem Material. Sie ist kein vierter zentraler Editionsfall dieser Forschungslinie. Das Repository ist lokal und unveröffentlicht. Seine geerbte Dokumentation beschreibt den älteren Vorlagenstand.

## Ebenen der Wiederverwendung

| Ebene | Bedeutung |
|---|---|
| Grundlegender Editionsfall | Ein früheres Projekt liefert Erfahrungen, Code und überprüfte Verfahren für die Verallgemeinerung |
| Direkte Projektinstanz | Ein Repository wird aus einem benannten Vorlagenstand erzeugt |
| Architektonische Übertragung | Ein eigenständig entwickeltes Repository übernimmt ausgewählte Abläufe und Prüfverträge |
| Technisches Prüfartefakt | Ein begrenzter Lauf prüft Funktionen des wiederverwendbaren Kerns |
| Konzeptioneller Vorläufer | Ein Forschungs- oder Schreibprojekt entwickelt Begriffe und methodische Rahmung |

DoCTA ist eine architektonische Übertragung. Eine gemeinsame Git-Abstammung von der Vorlage ist nicht belegt, und DoCTA übernimmt deren Dateivertrag nicht wörtlich. Wiederverwendbare Bestandteile aus DoCTA gelangen erst nach einer ausdrücklichen Zuordnung ihrer Ein- und Ausgaben sowie ihrer Herkunfts- und Prüfregeln in den Kern.

## Konzeptioneller Vorläufer

`amplified-edition-pipeline` ist ein Forschungs- und Paper-Repository vom Februar 2026. Dort entstanden die Rahmung der asymmetrischen Verstärkung, die Rolle des Critical Expert in the Loop, Promptotyping und die Prüfung entlang einer Editionspipeline. Eine aktuelle Software-Abstammung zur Vorlage besteht nicht. Die fortgeführten Begriffe sind in der gepflegten Methodik und der aktuellen Editopia-Publikationslinie verankert.

## Synchronisationsvertrag

- Jede direkte Projektinstanz dokumentiert den verwendeten Vorlagenstand und ihren aktuellen eigenen Stand.
- Allgemeine Korrekturen gelangen mit einem reproduzierbaren Fehlerfall und einer automatisierten Gegenprüfung in die Vorlage.
- Projektdaten, Rechteentscheidungen, Editionsregeln und fachliche Urteile verbleiben im jeweiligen Editionsprojekt.
- Architektonische Übertragungen dokumentieren die Zuordnung ihrer Verträge, bevor Code oder Aussagen in den wiederverwendbaren Kern übernommen werden.
- Aktualisierungen zwischen Vorlage und Projektinstanz erfolgen als ausdrückliche Integration. Eine automatische Synchronisation besteht nicht.

## Aktuelle Evidenzgrenze

Hersch und SZD belegen die fachliche und technische Ausgangsbasis der Verallgemeinerung. DoCTA belegt die Anwendung der Architektur in einem eigenständigen Projekt. Das künstliche Kurzbeispiel prüft den aktuellen regelbasierten Kern. Die Schuchardt-Instanz belegt einen Lauf an realem Material ab vorbereiteter Transkription. Ein vollständiger, durch einen externen Modelldienst gestützter Korpuslauf auf dem aktuellen Vorlagenstand mit fachlicher Prüfung und Nutzerabnahme ist noch nicht abgeschlossen.
