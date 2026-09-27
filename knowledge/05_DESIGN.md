---
title: Design and usage requirements
description: Inspection and usage tasks, verified components, acceptance and criteria self-assessment of the edition
tags: [design, ui, requirements, edition-configuration]
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

# Design and usage requirements

The edition's inspection and usage tasks take shape with the first sample and grow with newly observed errors. The frontend builder does not read this document, so an additional function needs code and tests.

## Foundations

[[01_PROJECT]] states research question, edition type and audience. [[03_CONTEXT]] sets editorial conventions and review procedures. [[04_TEI_MAPPING]] determines the structures and annotations to display.

## Tasks of the users

Every chosen task needs an observable acceptance criterion. Larger projects can group related tasks.

| Task | Required information or action | Acceptance criterion |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

## Supplied components

[TODO: Check each supplied component against the edition's own sources and record the result.]

| Component | Supplied scope | Checked for this edition |
|---|---|---|
| Catalogue | Filterable document list with metadata | [TODO] |
| Document view | Page-wise text with optional facsimile | [TODO] |
| Review state | Separate display of page state and aggregated document state | [TODO] |
| TEI provenance | Provenance and stored correction events derived from TEI | [TODO] |
| Downloads | TEI per document and plain-text export | [TODO] |
| Local correction editor | Current text, raw text, version check, reason for change and history | [TODO] |
| Proposals | Separate storage and explicit adoption into the correction path | [TODO] |

The [local review contract](../reference/local-review.md) defines the local write path. GitHub Pages delivers the static reading view. A save performs no commit, push or scholarly release.

The supplied viewer has no facsimile zoom, no blind first-reading mode, no jump from a metadata value to its source evidence, no version status of individual findings and no separate display of mention, entity, role and authority evidence. A task that needs one of these functions adds its implementation and a test. A stored correction must be verifiable through object, page and change history, and the viewer shows these data in part. A direct display of the canonical file path needs its own implementation.

## Further project-specific components

[TODO: Derive components from the chosen research and inspection tasks.]

| Component | Prerequisite | Acceptance criterion |
|---|---|---|
| [TODO] | [TODO] | [TODO] |

A critical apparatus presupposes modelled witnesses and variants. Registers need checked entity data and their own data projection. A corpus-wide full-text search needs a search index. A citation hint needs stable identifiers and the citation rule of the project.

## Views

[TODO: Sketch the views actually needed. Use text wireframes only where they clarify arrangement or interaction.]

## Acceptance

[TODO: Check the chosen tasks on named documents. Record result, data state and remaining scholarly uncertainty.]

Technical function, legibility, accessibility and scholarly review each need suitable evidence. A supplied component does not yet confirm successful use on the concrete corpus.

## Criteria for digital editions

The self-assessment follows the [criteria for reviewing scholarly digital editions, version 1.1](https://www.i-d-e.de/publikationen/weitereschriften/criteria-version-1-1) of the Institut für Dokumentologie und Editorik (IDE), which also underlie its review journal RIDE (A Review Journal for Digital Editions and Resources). The template supplies functions but no fulfilled criterion. The edition documents each criterion with its corpus, its chosen schema, its rights statements, its interface and its scholarly acceptance.

| Criteria area | Supplied support | Required evidence of the edition |
|---|---|---|
| Bibliographic identification | TEI header with document title, editor, institution, shelfmark and object ID | Completeness and scholarly correctness of the metadata |
| Data modelling | Deterministic TEI and configurable RelaxNG validation with TEI All as technical default | Edition-specific profile, mapping and passed formal validation |
| Infrastructure and browsing | Static catalogue and document view with filter | Usability, accessibility and suitability for the audience |
| Interfaces and export | TEI download and plain-text export | Persistent addresses, citation rules and archiving path |
| Rights and transparency | Configurable licence field and open project documentation | Rights clearance for texts, images and metadata, imprint and contact |

- [ ] 2.1 Selection, see [[02_DATA]] (selection criteria)
- [ ] 2.3 Content, see [[02_DATA]] (inventory) and [[01_PROJECT]] (scope)
- [ ] 3.1 Documentation, see [[03_CONTEXT]] (editorial guidelines)
- [ ] 3.2 Scholarly aims, see [[01_PROJECT]] (research question)
- [ ] 3.3 Mission, see [[01_PROJECT]] (edition type, audience)
- [ ] 3.4 Method, see [[03_CONTEXT]] (editorial approach)
- [ ] 3.5 Representation of documents, see [[03_CONTEXT]] and [[04_TEI_MAPPING]]
- [ ] 3.6 Textual criticism and indexing, see [[04_TEI_MAPPING]]
- [ ] 4.5 Indices, see [[04_TEI_MAPPING]], this document and the project-specific implementation
- [ ] 4.7 Metadata and linking, see [[04_TEI_MAPPING]] (authority data)
- [ ] 4.8 Identification and citation, see [[01_PROJECT]] (persistent identifiers)
- [ ] 4.9, 4.11 and 4.12 Interfaces and exports, checked on the downloads of the built frontend
- [ ] 4.13 Rights and licences, rights clearance for all published parts
- [ ] 4.15 Documentation, project guide, responsibilities and contact checked
- [ ] 4.16 Long-term use, see [[01_PROJECT]] (long-term archiving)
