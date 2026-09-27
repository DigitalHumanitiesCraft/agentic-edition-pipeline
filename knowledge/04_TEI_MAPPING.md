---
title: TEI mapping decisions
description: Schema profile, additional structures, annotation rules and registers of the edition
tags: [tei, mapping, schema, edition-configuration]
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

# TEI mapping decisions

Step 5 produces the fixed base mapping of header, body, markers and stored corrections described in the [TEI base mapping](../reference/tei-mapping.md). The decisions below extend it for this edition. A decision recorded here changes no output until the renderer or a separate, documented stage implements it with tests.

## TEI profile

[TODO: Choose the project profile, ODD or RelaxNG schema, set `VALIDATION_SCHEMA` in `pipeline/config.py` and justify the choice in [[decisions]].]

`schemas/tei_all.rng` is the runnable default of the template. The DTA base format (DTABf) of the Deutsches Textarchiv is not shipped, and adopting it requires an adapted header. The [schema documentation](../schemas/README.md) names its sources and the known header deviations.

## Additional structures

[TODO: Structures of the edition beyond the base mapping, each with its evidence and rule.]

| Project structure | TEI element | Evidence and rule |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

## Project-specific annotation rules

[TODO: Semantic annotations of the edition and their attested rules. Step 5 does not read this section. The edition implements the rules deterministically or as its own documented and tested extension stage.]

The claims an annotation makes and the evidence each needs are listed in the [TEI base mapping](../reference/tei-mapping.md#claims-of-semantic-annotation).

## Modelling decisions before annotation

[TODO: Confirm inline or stand-off model, permitted categories, references and checking rules.]

Inline markup marks a passage in the text body. Stand-off markup keeps the annotation separate and binds it to text passages through explicit references. The choice depends on overlaps, editing and the required outputs. An agent's proposal becomes a project profile only after documented scholarly confirmation.

## Registers

[TODO: Which registers should the edition contain? The base frontend aggregates no semantic registers. The edition implements the data projection and interface against the confirmed annotations.]

- [ ] Person register (from `persName`)
- [ ] Place register (from `placeName`)
- [ ] Subject register
- [ ] List of works (from `bibl`)
