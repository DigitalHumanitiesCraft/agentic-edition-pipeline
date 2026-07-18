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
