---
title: Editionsrichtlinien
description: Transkriptionskonventionen, Normalisierungen, Annotationstypen
tags: [context, guidelines, transcription]
---

# Editionsrichtlinien

## Transkriptionskonventionen

[TODO: Welche Regeln gelten fuer die Transkription?]

| Aspekt | Konvention |
|---|---|
| Zeilenumbrueche | [beibehalten / normalisieren] |
| Abkuerzungen | [aufloesen / beibehalten / kennzeichnen] |
| Unsichere Lesungen | `[?]` nach dem Wort (Standard) |
| Unleserliches | `[...]` mit optionaler Zeichenzahl (Standard) |
| Durchstreichungen | `~~text~~` (Standard) |
| Einfuegungen | `{text}` (Standard) |
| Orthographie | [beibehalten / normalisieren] |
| Interpunktion | [beibehalten / normalisieren] |
| Grossschreibung | [beibehalten / normalisieren] |

## Normalisierungen

[TODO: Nur relevant wenn Editionstyp = normalisiert. Welche Normalisierungen werden angewandt?]

## Sprachen und Schrifttypen

[TODO: Welche Schrifttypen kommen vor?]

- [ ] Handschrift (lateinisch)
- [ ] Kurrentschrift
- [ ] Druckschrift (Antiqua)
- [ ] Fraktur
- [ ] Mischformen

## Besonderheiten

[TODO: Spezifische Konventionen fuer dieses Korpus, z.B. Umgang mit Stempeln, Marginalien, eingeklebten Elementen]

## Annotationstypen

Welche Entitaeten und Strukturen sollen im TEI ausgezeichnet werden?

- [ ] Personen (`persName`)
- [ ] Orte (`placeName`)
- [ ] Organisationen (`orgName`)
- [ ] Daten (`date`)
- [ ] Bibliographische Referenzen (`bibl`)
- [ ] Sonstiges: [TODO]

## Normdaten

[TODO: Sollen Entitaeten mit Normdaten verknuepft werden?]

- [ ] GND (Gemeinsame Normdatei)
- [ ] Wikidata
- [ ] VIAF
- [ ] Geonames
- [ ] Keine Normdaten
- [ ] Sonstiges: [TODO]

## Vorbild oder Referenzedition

[TODO: Gibt es eine bestehende Edition als Vorbild? Ein Kodierungshandbuch? Institutionelle Vorgaben?]

## Zulässiger Modellkontext

[TODO: Vor einem Lauf festlegen, welche Informationen das Modell zusätzlich zum Bild erhalten darf.]

Mögliche Informationsquellen sind Katalogmetadaten, frühere Transkriptionen und objektspezifische Hinweise. Schritt 3 fügt ausgewählte Metadaten bereits automatisch zum Prompt hinzu. Die Ausgabe ist damit gegebenenfalls metadatenunterstützt. Eine ausschließlich bildbasierte Versuchsbedingung benötigt eine dokumentierte Anpassung des ausgeführten Prompts.

Die genaue Promptfassung und ihre Eingaben sind für die Bewertung maßgeblich. Übereinstimmung mit einer mitgelieferten Signatur belegt für sich keine korrekte Bildlesung. Ein Einfluss des Kontexts ist durch einen kontrollierten Vergleich zu untersuchen; aus einem einzelnen passenden oder widersprüchlichen Wert folgt kein Kausalnachweis.

## Quellenvergleich und Referenzbildung

[TODO: Verantwortliche, Seitenumfang und Verfahren der fachlichen Prüfung festlegen.]

Für eine unabhängige Erstlesung wird das Bild vor dem Modelltext betrachtet und die Lesung vor dem Vergleich festgehalten. Eine eigene Blindprüfungsfunktion ist im Basisfrontend noch nicht vorhanden.

Eine gespeicherte Nutzerkorrektur dokumentiert einen Eingriff. Für ihre Verwendung als Evaluationsreferenz müssen Prüfung und Reife des Referenztexts feststehen. Unaufgelöste Lesungen bleiben gekennzeichnet.

Modellkonfidenz und automatische Plausibilitätsbewertung sind Einschätzungen des jeweiligen Verfahrens. Sie sind keine gemessenen Fehlerraten. Frühere Notizen werden nach Textänderungen auf ihren Geltungsbereich geprüft. Herkunft und Grenzen der Videobeobachtungen stehen in der [Evaluationsreferenz](../reference/evaluation.md).
