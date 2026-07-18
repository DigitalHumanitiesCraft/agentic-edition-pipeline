---
title: Wissensindex
description: Navigation und Lesereihenfolge fuer alle Knowledge-Dokumente
tags: [index, navigation]
---

# Wissensindex

Einstiegspunkt fuer Claude Code und Menschen. Dieses Verzeichnis ist die Promptotyping-Wissensbasis des Editionsprojekts. Claude Code liest zuerst dieses Dokument, dann die fuer den aktuellen Arbeitsschritt relevanten Dokumente.

Wenn die Dokumente 01–04 noch ungefuellte `[TODO]`-Felder enthalten, ist das Repository noch nicht fuer ein konkretes Editionsprojekt instantiiert. In diesem Fall `SETUP.md` im Projektstamm lesen und mit dem Menschen gemeinsam die Konfigurationspunkte abarbeiten, bevor Pipeline-Skripte ausgefuehrt werden.

## Dokumente

Die Lesereihenfolge ergibt sich aus dieser Tabelle und der Schritt-Tabelle darunter, nicht aus Dateipraefixen. `decisions.md` und `journal.md` tragen die Konventionsnamen der Promptotyping-Dokumente.

| Dokument | Inhalt | Wer fuellt aus | Wann relevant |
|---|---|---|---|
| [[01_PROJECT]] | Projektdaten, Forschungsfrage, Editionstyp | Mensch | Projektstart, Frontend |
| [[02_DATA]] | Quellentypen, Korpusumfang, Inventar | Mensch + Skript | Analyse, Transkription |
| [[03_CONTEXT]] | Editionsrichtlinien, Transkriptionskonventionen | Mensch | Transkription, Validierung |
| [[04_TEI_MAPPING]] | Quellstruktur zu TEI-Element-Zuordnung | Mensch | TEI-Annotation |
| [[05_DESIGN]] | Epics, User Stories, UI-Komponenten, Wireframes | Claude Code + Mensch | Frontend-Design |
| [[08_DATA_CONTRACT]] | Datenvertrag der Transkriptions-JSON (Schritt 3 bis 6) | Template (fix) | Transkription bis Frontend |
| [[decisions]] | Architekturentscheidungen (ADR-Format) | Claude Code | Fortlaufend |
| [[journal]] | Entwicklungsjournal pro Session | Claude Code | Fortlaufend |

## Lesereihenfolge nach Pipeline-Schritt

| Schritt | Dokumente |
|---|---|
| 01 Bildextraktion | [[02_DATA]] |
| 02 Analyse | [[01_PROJECT]], [[02_DATA]] |
| 03 Transkription | [[02_DATA]], [[03_CONTEXT]], [[08_DATA_CONTRACT]] |
| 04 Validierung | [[03_CONTEXT]], [[08_DATA_CONTRACT]] |
| 05 TEI-Annotation | [[03_CONTEXT]], [[04_TEI_MAPPING]], [[08_DATA_CONTRACT]] |
| 05b Design | [[01_PROJECT]], [[03_CONTEXT]], [[04_TEI_MAPPING]], [[05_DESIGN]] |
| 06 Frontend | [[01_PROJECT]], [[05_DESIGN]], [[08_DATA_CONTRACT]] |

## RIDE-Kriterien-Status

Selbstbewertung gegen die [IDE-Kriterien fuer digitale Editionen v1.1](https://www.i-d-e.de/publikationen/weitereschriften/criteria-version-1-1).

### Automatisch durch Template erfuellt

- [x] 1.2 Bibliographische Identifikation (teiHeader/fileDesc)
- [x] 1.5 Transparenz (knowledge/ offen im Repo, README, Lizenz)
- [x] 3.7 Datenmodellierung (TEI DTABf, schemas/dtabf.json)
- [x] 4.1 Technische Infrastruktur (Vanilla JS, GitHub Pages)
- [x] 4.2 Interface und Usability (Katalog, Faksimile-Text-Ansicht)
- [x] 4.3 Browsen (Katalog mit Inhaltsverzeichnis)
- [x] 4.4 Suche (Client-seitige Volltextsuche)
- [x] 4.5 Indizes (Personen-/Ortsregister aus TEI-Annotationen)
- [x] 4.9 Technische Schnittstellen (TEI-XML Download)
- [x] 4.11 Export-Formate (TEI-XML + Plaintext)
- [x] 4.12 Zugang zu Basisdaten (TEI-XML in results/tei/)
- [x] 4.13 Rechte und Lizenzen (CC-BY 4.0, konfigurierbar)
- [x] 4.15 Dokumentation (knowledge/-System, README)

### Vom Menschen auszufuellen

- [ ] 2.1 Auswahl → [[02_DATA]] (Auswahlkriterien)
- [ ] 2.3 Inhalt → [[02_DATA]] (Inventar), [[01_PROJECT]] (Umfang)
- [ ] 3.1 Dokumentation → [[03_CONTEXT]] (Editionsrichtlinien)
- [ ] 3.2 Wissenschaftliche Ziele → [[01_PROJECT]] (Forschungsfrage)
- [ ] 3.3 Mission → [[01_PROJECT]] (Editionstyp, Zielgruppe)
- [ ] 3.4 Methode → [[03_CONTEXT]] (Editorische Schule)
- [ ] 3.5 Repraesentation von Dokumenten → [[03_CONTEXT]], [[04_TEI_MAPPING]]
- [ ] 3.6 Textkritik und Indizierung → [[04_TEI_MAPPING]]
- [ ] 4.7 Metadaten und Verlinkung → [[04_TEI_MAPPING]] (Normdaten)
- [ ] 4.8 Identifikation und Zitation → [[01_PROJECT]] (Persistente Identifier)
- [ ] 4.16 Langzeitnutzung → [[01_PROJECT]] (Archivierung)
