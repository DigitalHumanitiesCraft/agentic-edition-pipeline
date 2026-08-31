---
title: TEI-Mapping
description: Zuordnung von Quellstrukturen zu TEI-Elementen, Schema-Profil
tags: [tei, mapping, schema, dtabf]
---

# TEI-Mapping

## TEI-Profil

Der Fork legt sein Validierungsziel in `pipeline/config.py` fest. `schemas/tei_all.rng` ist das lauffähige Ausgangsprofil des Templates. `schemas/basisformat.rng` ist das mitgelieferte strengere DTA-Basisformat-Schema; seine Nutzung erfordert einen angepassten Header.

[TODO: Projektprofil, ODD oder RelaxNG-Schema festlegen und die Auswahl in [[decisions]] begründen.]

## Header-Mapping

Zuordnung von Projektmetadaten zu TEI-Header-Elementen. Quellen sind die Knowledge-Dokumente und die Dokumentmetadaten.

| Metadatenfeld | TEI-Element | Quelle |
|---|---|---|
| Dokumenttitel | `titleStmt/title` | Dokumentmetadaten `title`, Fallback `object_id` |
| Herausgeber | `titleStmt/editor` | [[01_PROJECT]] |
| Verlag/Institution | `publicationStmt/publisher` | [[01_PROJECT]] |
| Lizenz | `publicationStmt/availability/licence` | [[01_PROJECT]] |
| Signatur | `msIdentifier/idno[@type='shelfmark']` | Dokumentmetadaten `signature` |
| Objekt-ID | `msIdentifier/idno[@type='object-id']` | `object_id` |
| Repository | `msIdentifier/repository` | Dokumentmetadaten |
| Sprache | `profileDesc/langUsage/language` | Dokumentmetadaten `language`, Fallback `de` |
| Datum | `history/origin/origDate` | Dokumentmetadaten |

## Body-Mapping

Der deterministische Basispfad bildet die folgenden Strukturen ab.

| Quellelement | TEI-Element | Regeln |
|---|---|---|
| Absatz | `<p>` | Doppelzeilenumbruch trennt Absaetze |
| Seitenumbruch | `<pb/>` | Pro Faksimile-Bild, mit `@n` und `@facs` |
| Zeilenumbruch | `<lb/>` | Nur bei diplomatischer Transkription |
| Fremdtextseite | `<note type="foreign">` | Nur bei entsprechendem `page_type` |
| Gesperrte Seite | `<note type="gate" subtype="low_resolution">` | Nur bei entsprechendem `page_type` |
| Leere Seite | `<note type="empty">` | Leerer Text ohne deklarierten Seitentyp |
| Geloeschter Text `~~text~~` | `<del>text</del>` | Marker wird beim Rundlauf exakt rekonstruiert |
| Einfuegung `{text}` | `<add>text</add>` | Marker wird beim Rundlauf exakt rekonstruiert |
| Unsichere Lesung `word[?]` | `<unclear>word</unclear>` | Marker wird beim Rundlauf exakt rekonstruiert |
| Unleserliche Stelle `[...]` | `<gap reason="illegible"/>` | Optionaler Umfang aus `[... ~N chars]` |
| Fremdabsatz | `<note type="foreign">` | 0-basierter Index in `foreign_paragraphs` |

Weitere Strukturen werden hier spezifiziert und anschließend im deterministischen Renderer oder in einer getrennten Stufe implementiert. Ein Eintrag in dieser Tabelle allein verändert keine Ausgabe.

| Projektstruktur | TEI-Element | Beleg und Regel |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

## Annotationsregeln

[TODO: Projektspezifische semantische Annotationen und ihre belegten Regeln definieren. Schritt 5 konsumiert diesen Abschnitt nicht automatisch. Der Fork implementiert die Regeln deterministisch oder als eigene dokumentierte und geprüfte Erweiterungsstufe.]

Beispielformat:

```
- Personennamen mit <persName ref="GND-URI"> auszeichnen
- Ortsnamen mit <placeName ref="Wikidata-URI"> auszeichnen
- Datumsangaben mit <date when="YYYY-MM-DD"> auszeichnen
- Werktitel mit <bibl> auszeichnen
```

## Register

[TODO: Welche Register soll die Edition enthalten? Das Basisfrontend aggregiert derzeit keine semantischen Register. Der Fork implementiert die Datenprojektion und Oberfläche gegen die bestätigten Annotationen.]

- [ ] Personenregister (aus `persName`)
- [ ] Ortsregister (aus `placeName`)
- [ ] Sachregister
- [ ] Werkverzeichnis (aus `bibl`)
