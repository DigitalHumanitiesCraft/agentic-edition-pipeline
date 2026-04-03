---
title: Design und Nutzungsanforderungen
description: Epics, User Stories und UI-Komponenten-Mapping. Bruecke zwischen Forschungsfrage und Frontend.
tags: [design, ui, requirements, user-stories]
---

# Design und Nutzungsanforderungen

Dieses Dokument leitet aus der Forschungsfrage, dem Editionstyp und den Annotationstypen die konkreten Nutzungsanforderungen und UI-Elemente der publizierten Edition ab. Claude Code fuellt es vor dem Frontend-Bau aus, der Mensch prueft und korrigiert.

## Eingangsdokumente

Die Anforderungen werden aus drei Quellen abgeleitet:

- [[01_PROJECT]] Forschungsfrage, Editionstyp, Zielgruppe
- [[03_CONTEXT]] Transkriptionskonventionen, Annotationstypen
- [[04_TEI_MAPPING]] TEI-Elemente, Normdaten, Register

## Epics

Epics beschreiben die uebergeordneten Nutzungsziele der Edition. Sie ergeben sich direkt aus der Forschungsfrage und dem Editionstyp.

[TODO: Claude Code leitet Epics aus 01_PROJECT.md ab. Beispiele:]

### Epic 1: [TODO]

**Abgeleitet aus:** [Forschungsfrage / Editionstyp]
**Ziel:** [Was soll die Edition ermoeglichen?]

### Epic 2: [TODO]

**Abgeleitet aus:** [Forschungsfrage / Editionstyp]
**Ziel:** [Was soll die Edition ermoeglichen?]

## User Stories

Jede User Story beschreibt ein konkretes Nutzungsszenario und wird einem Epic zugeordnet. Das Format folgt dem Standard: "Als [Rolle] will ich [Aktion], damit [Nutzen]."

[TODO: Claude Code leitet User Stories aus Epics ab. Beispiele:]

| ID | Epic | User Story | Prioritaet |
|---|---|---|---|
| US-01 | [Epic 1] | Als Forscher will ich ... damit ... | hoch |
| US-02 | [Epic 1] | Als Leser will ich ... damit ... | mittel |
| US-03 | [Epic 2] | Als Forscher will ich ... damit ... | hoch |

## UI-Komponenten-Mapping

Jede User Story wird auf konkrete UI-Elemente abgebildet. Das Mapping bestimmt, welche Komponenten das Frontend enthaelt.

### Standardkomponenten (immer vorhanden)

Diese Komponenten sind Bestandteil jeder Edition, unabhaengig von der Forschungsfrage:

| Komponente | Beschreibung | RIDE-Kriterium |
|---|---|---|
| Katalog | Filterbare Dokumentenliste mit Metadaten | 4.3 Browsen |
| Volltextsuche | Client-seitige Suche ueber alle Dokumente | 4.4 Suche |
| Dokumentenansicht | Seitenweise Textdarstellung | 4.6 Darstellungsqualitaet |
| TEI-Download | XML-Datei pro Dokument herunterladen | 4.9 Schnittstellen, 4.12 Basisdaten |
| Plaintext-Export | Reiner Text ohne Markup | 4.11 Export-Formate |
| Zitierhinweis | Zitierrichtlinie im Footer | 4.8 Identifikation |
| Impressum | Projektinformation, Lizenz, Kontakt | 1.5 Transparenz |

### Forschungsspezifische Komponenten

[TODO: Claude Code leitet aus den User Stories ab, welche zusaetzlichen Komponenten benoetigt werden.]

| Komponente | User Story | Beschreibung | Implementierungshinweis |
|---|---|---|---|
| [TODO] | US-01 | [TODO] | [TODO] |

### Komponentenmatrix nach Editionstyp

Orientierung, welche UI-Elemente fuer welchen Editionstyp typisch sind:

| Komponente | Diplomatisch | Normalisiert | Kritisch |
|---|---|---|---|
| Faksimile-Text-Ansicht | ja (zentral) | optional | optional |
| Zeilengetreue Darstellung | ja | nein | nein |
| Normalisierungsanzeige | nein | ja (Original/Normalisiert umschalten) | nein |
| Variantenapparat | nein | nein | ja (zentral) |
| Textzeugen-Uebersicht | nein | nein | ja |
| Personenregister | wenn annotiert | wenn annotiert | ja |
| Ortsregister | wenn annotiert | wenn annotiert | ja |
| Sachregister | wenn annotiert | wenn annotiert | wenn annotiert |
| Konkordanz | wenn Forschungsfrage es erfordert | wenn Forschungsfrage es erfordert | wenn Forschungsfrage es erfordert |
| Zeitleiste | wenn datierte Dokumente | wenn datierte Dokumente | wenn datierte Dokumente |
| Faksimile-Viewer | ja | optional | optional |

## Wireframes

Textbasierte Wireframes der Hauptansichten. Claude Code erstellt sie basierend auf den ausgewaehlten Komponenten, der Mensch korrigiert.

### Katalogansicht

```
[TODO: Wireframe nach Komponentenauswahl]
```

### Dokumentenansicht

```
[TODO: Wireframe nach Komponentenauswahl]
```

### Registeransicht

```
[TODO: Wireframe nach Komponentenauswahl]
```

## Abnahmekriterien

Jede User Story hat messbare Abnahmekriterien, die vor der Freigabe des Frontends geprueft werden.

| User Story | Abnahmekriterium | Erfuellt |
|---|---|---|
| US-01 | [TODO] | [ ] |
| US-02 | [TODO] | [ ] |
