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

## Gespeicherte Korrekturen

Der Basispfad bildet `pages[].edits` als `revisionDesc/change[@type='transcription-correction']` ab. `@when` nennt den Zeitpunkt, `@subtype` die angegebene Rolle und `@who` verweist auf ein `respStmt` mit dem Bearbeiternamen. `@target` verweist auf die betroffene Seite. Der Änderungsgrund steht im Elementtext. Vorher-/Nachher-Werte bleiben im kanonischen JSON. Ungespeicherte Vorschläge erzeugen keine TEI-Ereignisse. Eine neue Ableitung und eine fachliche Freigabe behalten getrennte Bedeutungen.

## Projektspezifische Annotationsregeln

[TODO: Projektspezifische semantische Annotationen und ihre belegten Regeln definieren. Schritt 5 konsumiert diesen Abschnitt nicht automatisch. Der Fork implementiert die Regeln deterministisch oder als eigene dokumentierte und geprüfte Erweiterungsstufe.]

Ein Formatbeispiel wie `<persName ref="GND-URI">` setzt eine geprüfte Identität und einen belegten Normdatenbezug voraus. Das Beispiel ist keine Anweisung zur automatischen Vergabe von Identifikatoren. Datumsnormalisierung und Werkidentifikation benötigen eigene Regeln.

## Register

[TODO: Welche Register soll die Edition enthalten? Das Basisfrontend aggregiert derzeit keine semantischen Register. Der Fork implementiert die Datenprojektion und Oberfläche gegen die bestätigten Annotationen.]

- [ ] Personenregister (aus `persName`)
- [ ] Ortsregister (aus `placeName`)
- [ ] Sachregister
- [ ] Werkverzeichnis (aus `bibl`)

## Modellierungsentscheidungen vor der Annotation

[TODO: Inline- oder Stand-off-Modell, erlaubte Kategorien, Referenzen und Prüfregeln bestätigen.]

Inline-Auszeichnung markiert eine Stelle im Textkörper. Stand-off-Auszeichnung führt die Annotation getrennt und bindet sie über explizite Verweise an Textstellen. Die Wahl richtet sich nach Überlappungen, Bearbeitung und den benötigten Ausgaben. Eine Agentenentscheidung erhält erst nach dokumentierter fachlicher Bestätigung den Status eines Projektprofils.

Bei semantischen Annotationen sind unterschiedliche Aussagen zu prüfen:

| Aussage | Erforderlicher Beleg |
|---|---|
| Erwähnung | Exakter Text und die richtige Fundstelle |
| Entitätsidentität | Begründete Zusammenführung unterschiedlicher Namensformen |
| Rolle | Belegte Funktion im jeweiligen Dokumentkontext |
| Beziehung | Nachvollziehbare Verbindung zwischen den beteiligten Entitäten |
| Normdatenlink | Passender externer Datensatz und dokumentierte Disambiguierung |

Mehrere Bezeichnungen eines Werks können dieselbe Entität meinen. Dokumentlokale IDs erlauben keine Aussage über die Zahl verschiedener Personen oder Werke im Gesamtkorpus. Ein formal gültiger Anker bestätigt weder Identität noch Rolle.

Tabellen, Spalten und typografische Gruppen können Beziehungen zwischen Personen, Werken und Funktionen tragen. Diese Layoutbeziehungen sind vor einer verlustbehafteten Linearisierung zu erfassen, wenn sie für das Editionsziel benötigt werden. Der Basisrenderer rekonstruiert sie nicht.

## Reife einer TEI-Datei

Ein erzeugtes TEI-Dokument ist zunächst ein Kandidat. Wohlgeformtheit, RelaxNG-Konformität und Textbewahrung sind technische Prüfungen. Als fachlich abgenommen gilt nur der entsprechend geprüfte und ausdrücklich bestätigte Stand. Die Benennung einer Datei oder eines Ordners als `final` bestätigt diese Reife nicht.

Nach Textkorrekturen müssen Textanker und abhängige Befunde erneut geprüft werden. [[local-review]] beschreibt den Schutz angereicherter TEI im bestehenden Korrekturweg.
