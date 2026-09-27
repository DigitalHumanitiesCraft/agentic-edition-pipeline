---
title: Project
description: Identity, research question, edition type, audience and publication terms of the edition
tags: [project, metadata, edition-configuration]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: stub
created: 2026-04-03
updated: 2026-09-27
---

# Project

The field table is read by the scripts. Step 5 writes its values into the TEI header following the [TEI base mapping](../reference/tei-mapping.md), and step 6 and the local review server take the edition title from it. A row counts only when its label equals one of the labels below, and a value starting with `[TODO` counts as missing. Keep the labels unchanged. The scripts also accept the German labels `Projektname`, `Titel`, `Herausgeber`, `Editionstyp`, `Sprache` and `Lizenz` and the variants `Publisher` and `Licence`, and the first filled row of a field wins.

| Field | Value | Read by the scripts as |
|---|---|---|
| Title | [TODO] | catalogue and frontend title of the edition |
| Editor | [TODO] | `titleStmt/editor` |
| Institution | [TODO] | `publicationStmt/publisher` |
| Edition type | [TODO] | line-break rule of the body, see Edition type below |
| Language | [TODO] | BCP 47 language code of the edition text, `langUsage/language/@ident` for documents without their own language |
| License | [TODO] | `publicationStmt/availability/licence` |
| Project period | [TODO] | documentation only |
| Contact | [TODO] | documentation only |
| Repository URL | [TODO] | documentation only |

## Edition type

[TODO: Enter one of the following values in the Edition type row.]

- Diplomatic transcription reproduces the source character by character and keeps its line breaks as `<lb/>`.
- Normalised transcription applies the normalisations defined in [[03_CONTEXT]] and joins the lines of a paragraph.
- Critical edition adds apparatus and variants, which need their own modelling in [[04_TEI_MAPPING]].

Step 5 joins lines only when the value contains `normalis` or `normaliz` in any letter case. Every other value, including an empty one, keeps the line breaks.

## Language

[TODO: Enter a language tag following BCP 47, the language-tag standard of the Internet Engineering Task Force, such as `de`, `en`, `la` or `de-AT` in the Language row. The scripts do not check the code.]

Document metadata with its own `language` value takes precedence. When neither declares a language, the TEI header has no `langUsage`.

## Languages of the corpus

[TODO: Languages and scripts of the corpus, with their approximate share where known.]

## Research question

[TODO: Why is the material edited, for whom, and what should happen with the edited texts? The answers determine the inspection and usage tasks in [[05_DESIGN]].]

## Audience

[TODO: Researchers of a particular field, students or an interested public. The audience shapes interface decisions.]

## Publication target

- [ ] GitHub Pages (default)
- [ ] Institutional repository such as GAMS (Geisteswissenschaftliches Asset Management System) or TextGrid
- [ ] Other platform ([TODO])
- [ ] Not yet decided

## Licence

[TODO: CC BY 4.0 is the default for texts and data. Record any deviating licence and restrictions from image rights.]

## Citation

[TODO: How should the edition be cited? Give the citation pattern with editors as a role, title of the edition, institution, year, URL and DOI.]

## Persistent identifiers

[TODO: DOI, URN, Handle or not yet decided.]

## Long-term archiving

[TODO: Planned institutional archiving, repository, or GitHub only.]
