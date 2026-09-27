---
title: Lineage and case comparison
description: Relation of the three edition cases, technical sources and test artefacts to the reusable template, and the comparison from which its shared core was derived
tags: [lineage, case-study, comparison, template]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: complete
created: 2026-08-31
updated: 2026-09-27
---

# Lineage and case comparison

The Agentic Edition Pipeline is a reusable project template for digital scholarly editions. It connects executable processing steps, a shared data contract, project knowledge, checkpoints, schema validation and a static publication interface. Each edition project adds its own sources, editorial rules, TEI profile, research purpose and scholarly acceptance decisions. The template grew out of three edition cases, and a comparison of their repositories determined which of their features form its shared core.

## Three edition cases

The three real edition cases are Hersch, the edition project of the Zentralbibliothek Zürich (ZBZ), SZD (Stefan Zweig Digital) and DoCTA (Doing Court in the Tyrolean Alps). Hersch and SZD existed before the general repository, and their experience, processing steps and review procedures were carried over into the template. DoCTA applies the resulting architecture to a further source collection in an independent repository.

| Case | Repository | Contribution | Relation to the template |
|---|---|---|---|
| Hersch/ZBZ | `zbz-ocr-tei` | Continuous processing from PDF scans to reviewed TEI files, a project-specific schema and verifiable curation steps | Founding case that predates the reusable template |
| SZD | `szd-htr-ocr-pipeline` | Processing of a large and heterogeneous holding, material-specific prompt groups, quality signals and a correction interface | Founding case that predates the reusable template |
| DoCTA | `DoCTA` | Transfer of the architecture to Tyrolean court records with Transkribus sources, separate reference states and review candidates, rule-based TEI generation and a static edition | Independent application of the generalised architecture |

These three cases form the empirical basis of the project. Hersch and SZD show from which real editorial problems the general pipeline was developed, and DoCTA shows its transfer to a new holding. The different origins stay relevant for statements about reuse and technical descent.

## Technical sources

Two further projects supplied individual technical patterns for the reusable core.

| Repository | Contribution taken over |
|---|---|
| `co-ocr-htr` | Abstraction of external model services, combined validation and PAGE XML processing |
| `teiCrafter` | TEI editing, schema guidance, semantic annotation and editable project profiles |

They belong to the technical provenance. The three primary research cases remain Hersch, SZD and DoCTA.

## Technical test artefacts

### Synthetic offline example

`examples/offline-quickstart/` creates an isolated local project from the current template. It checks rule-based validation, TEI generation, schema validation, the frontend build and the evaluation module on two synthetic objects. The test covers the executable command path and its safety boundaries. External model services, facsimiles and scholarly edition quality are outside its scope.

### Schuchardt test instance

The local repository `hsa-letters-pipeline` was created from template commit `7328482`. It processed 18 letters from the Hugo Schuchardt Archiv (HSA) from prepared transcriptions through validation and TEI generation to interface and evaluation. All 18 TEI files were valid against TEI All at instance commit `a28dee27`. Automatic transcription through an external model service was not run because of invalid credentials. The run produced 16 findings about the template, and the blocking ones were later taken into the template.

The Schuchardt instance documents a technical run on real material. It is no fourth central edition case of this research line. The repository is local and unpublished, and its inherited documentation describes the older template state.

### Video demonstrations of September 2026

The local letter and PDF instances worked on in the [session video](https://youtu.be/krL-xMxTa_c) are additional technical test cases. The letter demonstration combines imported archival metadata with its own image transcription run and is distinct from the older instance with 18 letters. The PDF demonstration adds separately produced semantic annotations.

Requirements on corrections, input context and review were derived from these instances. Their data and project-specific functions do not enter the template automatically. The [evaluation reference](../../reference/evaluation.md) names the observed points and the limits of their evidence. The video demonstrations establish neither a controlled model benchmark nor the scholarly acceptance of the current template.

## Levels of reuse

| Level | Meaning |
|---|---|
| Founding edition case | An earlier project supplies experience, code and verified procedures for the generalisation |
| Direct project instance | A repository is created from a named template state |
| Architectural transfer | An independently developed repository takes over selected workflows and review contracts |
| Technical test artefact | A bounded run checks functions of the reusable core |
| Conceptual precursor | A research or writing project develops concepts and methodological framing |

DoCTA is an architectural transfer. A shared Git descent from the template is not documented, and DoCTA does not take over the template's file contract literally. Reusable parts of DoCTA enter the core only after an explicit mapping of their inputs and outputs and of their provenance and review rules.

## Conceptual precursor

`amplified-edition-pipeline` is a research and paper repository from February 2026. It developed the framing of asymmetric amplification, the role of the Critical Expert in the Loop, Promptotyping and the review along an edition pipeline. No current software descent to the template exists. The continued concepts are anchored in the maintained methodology and the current Editopia publication line.

## Synchronisation contract

- Every direct project instance documents the template state it used and its own current state.
- General corrections enter the template with a reproducible failure case and an automated check.
- Project data, rights decisions, editorial rules and scholarly judgements stay in the edition project.
- Architectural transfers document the mapping of their contracts before code or statements enter the reusable core.
- Updates between template and project instance happen as explicit integration. No automatic synchronisation exists.

## Evidence boundary

Hersch and SZD document the scholarly and technical starting point of the generalisation. DoCTA documents the application of the architecture in an independent project. The synthetic offline example checks the current rule-based core. The Schuchardt instance documents a run on real material starting from prepared transcriptions. A complete corpus run on the current template state supported by an external model service, with scholarly review and user acceptance, has not been completed.

## Comparison of the three cases

The comparison examines the data paths, review procedures and edition outputs of the three cases and determines which functions belong in the reusable core and which rules stay in the individual edition project. It is a technical and conceptual examination. It includes no reprocessing of the three complete corpora, no scholarly check of the transcriptions and no user acceptance.

The comparison rests on the repository states of 27 August 2026. SZD was examined at commit `cc45c9345a47` and DoCTA at commit `d0a4a5305ce4`, the commit that adds the project schema `docta.rng` named below. For Hersch/ZBZ, `c0cc741739c8` is the Git anchor. The substantially extended local working state was read in addition, so statements about its new entity and curation functions count as an observed working state without a reproducible commit anchor.

### Catalogue snapshot of 27 August 2026

The figures describe the repository catalogues observed at the states named above. They make no statement about the complete physical holding or the scholarly accepted edition scope, and the source repositories hold the current figures.

| Case | Catalogue at the examined state | Sources and edition goal |
|---|---:|---|
| Hersch/ZBZ | 285 documents, 4,117 pages | Published texts and scans of the Hersch edition, curatable TEI following the ZBZ profile |
| SZD | 2,452 objects, 17,132 pages in five collections | Heterogeneous literary estate with handwriting, typescript, print, forms and tables |
| DoCTA | 65 documents, 692 registered pages | Tyrolean account books, inventories, copybooks and court ordinances from Transkribus and IIIF |

### Contributions to the template

| Case | Contribution |
|---|---|
| Hersch/ZBZ | Separate processing streams, status values set by humans, project-specific schema validation and traceable curation steps |
| SZD | Material-specific prompt profiles, continuable page JSON, calibrated quality signals and conservative conversion of transcription markers into TEI |
| DoCTA | Immutable transcription runs, a review return path, separate reference classes, entity extraction, arithmetic checks and rule-based TEI generation with project gates |

### Processing compared

| Dimension | Hersch/ZBZ | SZD | DoCTA | Consequence for the shared core |
|---|---|---|---|---|
| Input | Local and published scans, outputs of optical character recognition (OCR) and catalogue data | Remote images from GAMS (Geisteswissenschaftliches Asset Management System) in five collections | Transkribus documents with IIIF images | A source register describes local files and remote facsimiles together before transcription. |
| Material control | Four layout classes steer OCR and layout analysis | Nine prompt groups steer transcription by document type | Separate prompt modules for account books and inventories | A document selects a versioned prompt profile. Object-specific rules form a further explicit layer. |
| Working format | OCR Markdown, layout JSON and PAGE XML as separate streams | Page JSON v0.2 with optional regions, plus PAGE/METS and TEI | Page register with IIIF, content class, review field and immutable runs | The core needs a small page contract. Layout and further exchange formats stay optional streams. |
| Text states | OCR, layout, TEI and entities have their own states | Raw machine output, edited transcription and edit history stay separate | Every run stays unchanged, and automatically checked and scholarly accepted text are separate states | Raw machine output and editable text are stored separately. Human actions change the review state. |
| Review vocabulary | `unverifiziert`, `in_arbeit`, `verifiziert` per stream | human reviewed, agent reviewed and unreviewed | `unbearbeitet`, `maschinell`, `gesichtet`, `abgenommen` per page | The template uses a small shared maturity sequence onto which projects map their visible labels. |
| Quality assessment | Reference TEI files, fidelity and scope decomposition, bootstrap intervals | Reference objects from all prompt groups and corpus-calibrated signals | Fixed benchmark, repeated runs per condition and separate reference classes | Every evaluation names reference class, normalisation, model, prompt state and sample. Universal quality thresholds are avoided. |
| TEI generation | Rule-based base structure, page-wise refinement and a final schema check | Rule-based conversion with conservative marker mapping and round-trip check | Rule-based builder with image regions and processing-step provenance | The base path stays rule-based. The project chooses its schema and implements further structures as a checked extension. |
| Entities | Closed candidate list, preview before release, no free ID generation by the model | Marker mapping with cautious TEI enrichment | Entity candidates are extracted and enter the governed path only with an unambiguous text position | Semantic enrichment needs its own provenance and release rule and does not belong automatically in every transcription. |
| Publication | Canonical files and generated website mirror are separate | Curation view over the working data | Static edition with source register, viewer, benchmark and gates against `docta.rng` and project rules | Canonical data stay outside the publication copy, and the website set is generated from them by rule. |

The review vocabularies are quoted in the projects' own German labels.

### Shared core

All three cases lead to these binding requirements on the template.

1. The source register records document identity, metadata, page order, facsimile addresses and prompt profile before the first model call.
2. The transcription instruction is assembled at run time from base rules, document profile, metadata context and an optional object rule. The layers actually used and their joint hash are recorded.
3. Every model page keeps its original output in `transcription_raw`, and `transcription` is the editable text state.
4. Every page carries a human-controlled review state. The shared sequence is `machine_unreviewed`, `in_review`, `human_verified`, `accepted`, and automatic quality findings do not change it.
5. Every image page corresponds to exactly one page in the model answer. Missing or additional pages end the processing of the document at the contract boundary.
6. TEI generation is byte-identical for the same validated input state, and the least mature page state is stated in `revisionDesc`.
7. Schema and additional checks are chosen in the edition project, and the template supplies the selection and checking mechanism.
8. Evaluations use fixed manifests. Reference class, normalisation profile, sample, model and prompt state belong to the result.

### Project-specific extensions

The template documents these functions as extension points, because none of the three cases allows their editorial rules to be derived in general.

| Extension | Responsible project knowledge |
|---|---|
| ZBZ entity list, GND assignment and three-stage candidate decision | Hersch/ZBZ |
| Nine SZD prompt groups, page JSON regions, METS/MODS and the SZD marker vocabulary | SZD |
| Praxeological event and relation modelling, SiCProD linking (a prosopographical database of the Tyrolean court) and accounting logic | DoCTA |
| Concrete RelaxNG schema, editorial guidelines and release rules | each edition project |

### Implementation in the template

The revision of 27 August 2026 implemented the shared core in four places.

- `data/sources/manifest.json` is the early entry for catalogue data, remote facsimiles and prompt profiles, and step 2 merges these declarations with locally found files.
- Step 3 assembles the four prompt layers at run time and records layers, profile and hash.
- Step 3 creates `transcription_raw` and the initial review state, and step 4 passes both on unchanged.
- Step 5 writes the aggregated review state into the TEI header and uses the input timestamp, so repeated generation from the same validated file stays byte-identical.

Layout regions, entity release and project-specific TEI structures remain extensions. Their inclusion in the core requires a second real case with the same data need and an automated contract check. [Data contract](../../reference/data-contract.md) defines the shared page contract, and [[decisions]] documents the architecture decisions derived from the comparison.
