---
title: Editorial guidelines
description: Transcription conventions, normalisations, annotation types, permitted model context and reference formation of the edition
tags: [context, guidelines, transcription, edition-configuration]
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

# Editorial guidelines

The editorial guidelines state the rules that transcription, quality assessment and review apply to this corpus. The transcription markers themselves have a fixed syntax, defined in `pipeline/markers.py` and mapped to TEI as the [TEI base mapping](../reference/tei-mapping.md) describes. The edition decides whether and how it uses them.

## Transcription conventions

[TODO: Which rules apply to the transcription?]

| Aspect | Convention |
|---|---|
| Line breaks | [keep / normalise] |
| Abbreviations | [expand / keep / mark] |
| Uncertain readings | `word[?]`, fixed marker syntax |
| Illegible passages | `[...]` or `[... ~N chars]`, fixed marker syntax |
| Strikethrough | `~~text~~`, fixed marker syntax |
| Insertions | `{text}`, fixed marker syntax |
| Orthography | [keep / normalise] |
| Punctuation | [keep / normalise] |
| Capitalisation | [keep / normalise] |

## Normalisations

[TODO: Only for a normalised edition type. Which normalisations apply?]

## Scripts

[TODO: Which scripts occur?]

- [ ] Handwriting in Latin script
- [ ] Kurrent
- [ ] Printed Antiqua
- [ ] Fraktur
- [ ] Mixed forms

## Special cases

[TODO: Corpus-specific conventions, for example for stamps, marginalia or pasted-in elements.]

## Annotation types

[TODO: Which entities and structures should be marked up in TEI?]

- [ ] Persons (`persName`)
- [ ] Places (`placeName`)
- [ ] Organisations (`orgName`)
- [ ] Dates (`date`)
- [ ] Bibliographic references (`bibl`)
- [ ] Other ([TODO])

## Authority data

[TODO: Should entities be linked to authority data?]

- [ ] GND (Gemeinsame Normdatei)
- [ ] Wikidata
- [ ] VIAF (Virtual International Authority File)
- [ ] GeoNames
- [ ] No authority data
- [ ] Other ([TODO])

## Model or reference edition

[TODO: Is there an existing edition to follow, an encoding manual or institutional guidance?]

## Permitted model context

[TODO: Decide before a run which information the model may receive in addition to the image.]

Possible sources are catalogue metadata, earlier transcriptions and object-specific hints. Step 3 already adds the title, signature, date, language, object type and extent from the inventory to the prompt, so its output can be metadata-assisted. An experimental condition based on the image alone needs a documented adaptation of the executed prompt.

The exact prompt and its inputs govern the assessment. Agreement with a supplied shelfmark does not by itself prove a correct reading of the image. The influence of context needs a controlled comparison, and a single matching or contradicting value establishes no causal effect.

## Source comparison and reference formation

[TODO: Responsible roles, page scope and procedure of the scholarly review.]

For an independent first reading, the reviewer looks at the image before the model text and records the reading before the comparison. The base frontend offers no dedicated blind-review mode.

A stored user correction documents an intervention. Its use as an evaluation reference requires that review and maturity of the reference text are settled. Unresolved readings stay marked.

Model confidence and the automatic plausibility assessment are estimates of the respective procedure and no measured error rates. Earlier notes are checked for their scope after text changes. The [evaluation reference](../reference/evaluation.md) states the origin and limits of the video observations.
