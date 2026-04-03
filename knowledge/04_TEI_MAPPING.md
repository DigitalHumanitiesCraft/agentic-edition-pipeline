---
title: TEI-Mapping
description: Zuordnung von Quellstrukturen zu TEI-Elementen, Schema-Profil
tags: [tei, mapping, schema, dtabf]
---

# TEI-Mapping

## TEI-Profil

DTA-Basisformat (DTABf). Schema in `schemas/dtabf.json`. Anpassbar bei Bedarf.

[TODO: Abweichendes Profil? Eigenes ODD?]

## Header-Mapping

Zuordnung von Projektmetadaten zu TEI-Header-Elementen. Quellen sind die Knowledge-Dokumente und die Dokumentmetadaten.

| Metadatenfeld | TEI-Element | Quelle |
|---|---|---|
| Titel | `titleStmt/title` | [[01_PROJECT]] |
| Herausgeber | `titleStmt/editor` | [[01_PROJECT]] |
| Verlag/Institution | `publicationStmt/publisher` | [[01_PROJECT]] |
| Lizenz | `publicationStmt/availability/licence` | [[01_PROJECT]] |
| Signatur | `msIdentifier/idno` | Dokumentmetadaten |
| Repository | `msIdentifier/repository` | Dokumentmetadaten |
| Sprache | `profileDesc/langUsage/language` | [[02_DATA]] |
| Datum | `history/origin/origDate` | Dokumentmetadaten |

## Body-Mapping

Zuordnung von Quellelementen zu TEI-Body-Elementen.

| Quellelement | TEI-Element | Regeln |
|---|---|---|
| Absatz | `<p>` | Doppelzeilenumbruch trennt Absaetze |
| Ueberschrift | `<head>` | Erkennung via Layout-Analyse oder Prompt |
| Seitenumbruch | `<pb/>` | Pro Faksimile-Bild, mit `@n` und `@facs` |
| Zeilenumbruch | `<lb/>` | Nur bei diplomatischer Transkription |
| Tabelle | `<table><row><cell>` | Struktur aus Prompt-Output |
| Marginalie | `<note type="marginalia">` | Position aus Layout-Analyse |
| Kopfzeile | `<fw type="header">` | Wiederkehrend am Seitenanfang |
| Fusszeile | `<fw type="footer">` | Wiederkehrend am Seitenende |
| Fussnote | `<note place="foot">` | [TODO: Konventionen fuer Fussnoten] |

## Annotationsregeln

[TODO: Projektspezifische Mapping-Regeln fuer Layer 3 des Annotationsprompts (`pipeline/prompts/annotation.md`). Diese Regeln steuern, wie Claude Code TEI-Annotationen erzeugt.]

Beispielformat:

```
- Personennamen mit <persName ref="GND-URI"> auszeichnen
- Ortsnamen mit <placeName ref="Wikidata-URI"> auszeichnen
- Datumsangaben mit <date when="YYYY-MM-DD"> auszeichnen
- Werktitel mit <bibl> auszeichnen
```

## Register

[TODO: Welche Register soll die Edition enthalten? Register werden aus TEI-Annotationen aggregiert und im Frontend angezeigt.]

- [ ] Personenregister (aus `persName`)
- [ ] Ortsregister (aus `placeName`)
- [ ] Sachregister
- [ ] Werkverzeichnis (aus `bibl`)
