---
title: Design und Nutzungsanforderungen
description: Prüfaufgaben, vorhandene Komponenten und projektspezifische Abnahmekriterien
tags: [design, ui, requirements]
---

# Design und Nutzungsanforderungen

Dieses Dokument konkretisiert die Prüf- und Nutzungsaufgaben einer Edition. Agent und Editionsteam bearbeiten es am ersten Beispiel und bei neu beobachteten Fehlern. Der Frontend-Builder liest diese Anforderungen nicht automatisch; zusätzliche Funktionen erfordern Code und Tests.

## Grundlagen

[[01_PROJECT]] beschreibt Forschungsfrage, Editionstyp und Zielgruppe. [[03_CONTEXT]] legt Editionskonventionen und Prüfverfahren fest. [[04_TEI_MAPPING]] bestimmt die darzustellenden Strukturen und Annotationen.

## Aufgaben der Nutzenden

Jede gewählte Aufgabe benötigt ein beobachtbares Abnahmekriterium. Umfangreiche Projekte können verwandte Aufgaben gruppieren. Eine feste Anzahl an Epics oder User Stories ist nicht erforderlich.

| Aufgabe | Benötigte Information oder Handlung | Abnahmekriterium |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

## Vorhandene Komponenten

Der Fork prüft die Inhalte und Eignung dieser technisch vorhandenen Funktionen an seinen eigenen Quellen.

| Komponente | Vorhandener Umfang |
|---|---|
| Katalog | Filterbare Dokumentenliste mit Metadaten |
| Dokumentenansicht | Seitenweiser Text mit optionalem Faksimile |
| Review-Status | Getrennte Darstellung von Seitenstand und zusammengefasstem Dokumentstand |
| TEI-Herkunft | Aus TEI abgeleitete Herkunft und gespeicherte Korrekturereignisse |
| Downloads | TEI pro Dokument und Plaintext-Export |
| Lokaler Korrektureditor | Aktueller Text, Rohtext, Versionsprüfung, Änderungsgrund und Verlauf |
| Vorschläge | Getrennte Ablage und ausdrückliche Übernahme in den Korrekturweg |

[[local-review]] definiert den lokalen Schreibweg. GitHub Pages liefert die statische Leseansicht. Ein Speichervorgang führt weder Commit noch Push oder fachliche Freigabe aus.

## Anforderungen aus der Videoprüfung

Die folgenden Funktionen sind noch umzusetzen, wenn der Fork sie benötigt. [[specification]] führt ihren Status für das Template.

| Prüfaufgabe | Anforderung | Prüffall |
|---|---|---|
| Schwierige Lesung beurteilen | Vergrößern und Verschieben des Faksimiles | Kleine Schrift bleibt lesbar und auf die richtige Seite bezogen |
| Eigene Lesung unbeeinflusst festhalten | Bildansicht vor Freigabe des Modelltextes | Erstlesung wird vor dem Vergleich gespeichert |
| Metadaten begründen | Feldherkunft und Sprung zum Quellenbeleg | Sprachangabe führt zu der tatsächlich mehrsprachigen Passage |
| Frühere Notizen einordnen | Befund mit Eingabeversion und aktuellem Geltungsstatus | Alte Ziffernlesung wird nach einer Textkorrektur als prüfpflichtig gezeigt |
| Entitäten prüfen | Erwähnung, Entität, Rolle und Normdatenbeleg getrennt anzeigen | Zwei Schreibweisen werden erst nach Prüfung derselben Identität zugeordnet |

Eine gespeicherte Korrektur muss über Objekt, Seite und Änderungsgeschichte überprüfbar sein. Das Basisfrontend zeigt diese Daten bereits teilweise; eine zusätzliche direkte Anzeige des kanonischen Dateipfads und ein Metadaten-Belegsprung benötigen eigene Implementierung.

## Weitere projektspezifische Komponenten

[TODO: Komponenten aus den gewählten Forschungs- und Prüfaufgaben ableiten.]

| Komponente | Voraussetzung | Abnahmekriterium |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

Ein kritischer Apparat setzt modellierte Textzeugen und Varianten voraus. Register benötigen geprüfte Entitätsdaten und eine eigene Datenprojektion. Eine korpusweite Volltextsuche benötigt einen Suchindex. Ein Zitierhinweis benötigt stabile Identifikatoren und die Zitierregel des Projekts.

## Ansichten

[TODO: Die tatsächlich benötigten Ansichten knapp skizzieren. Textbasierte Wireframes nur verwenden, wenn sie die Anordnung oder Interaktion klären.]

## Abnahme

[TODO: Die ausgewählten Aufgaben an benannten Dokumenten prüfen. Ergebnis, Datenstand und verbleibende fachliche Unsicherheit festhalten.]

Technische Funktion, Lesbarkeit, Zugänglichkeit und fachliche Prüfung benötigen jeweils passende Belege. Eine vorhandene Komponente bestätigt noch keine gelungene Nutzung am konkreten Korpus.
