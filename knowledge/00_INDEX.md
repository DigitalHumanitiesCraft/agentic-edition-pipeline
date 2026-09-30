---
title: Knowledge index
description: Navigation, document roles, fork inheritance and reading order of the knowledge base
tags: [index, navigation]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: complete
created: 2026-04-03
updated: 2026-09-30
---

# Knowledge index

The knowledge base holds the decisions of an edition and the records of its work for an AI harness, and [AGENTS.md](../AGENTS.md) holds the shared working contract. Read the documents the current task needs.

While `01_PROJECT.md` to `05_DESIGN.md` still contain `[TODO]` fields, the repository is not yet configured for a concrete edition. Work through [SETUP.md](../SETUP.md) before processing a real corpus. Template maintenance that was explicitly commissioned follows [[overview]], uses isolated synthetic tests and leaves the edition placeholders open.

## Document roles

### Edition configuration

These documents are filled for each fork. The scripts read the field table of `01_PROJECT.md` and write the inventory block of `02_DATA.md`.

| Document | Content | Filled by |
|---|---|---|
| [[01_PROJECT]] | Identity, research question, edition type, language code, publication terms | Edition team |
| [[02_DATA]] | Source types, scope, selection, provenance, generated inventory | Edition team and step 2 |
| [[03_CONTEXT]] | Transcription conventions, permitted model context, reference formation | Edition team |
| [[04_TEI_MAPPING]] | Schema profile, additional structures, annotation rules, registers | Edition team |
| [[05_DESIGN]] | Inspection tasks, component checks, acceptance, criteria self-assessment | Agent and edition team |

### Fixed contracts

These documents under `reference/` describe the behaviour of the supplied code and are the same in every fork.

| Document | Content |
|---|---|
| [Data contract](../reference/data-contract.md) | Transcription and validated JSON of steps 3 to 6, source manifest, completeness rule |
| [TEI base mapping](../reference/tei-mapping.md) | Header and body mapping of step 5, overwrite guard, claims of semantic annotation |
| [Local review contract](../reference/local-review.md) | Local editor, API, recovery, corrections |
| [Provider records](../reference/provider-records.md) | Call records, retries, chunk cache |
| [Processing reference](../reference/pipeline.md) | Commands, inputs and outputs of the scripts |
| [Evaluation reference](../reference/evaluation.md) | Checks, recognition quality, evaluation module |

### Template knowledge

These documents under `knowledge/template/` describe the reusable template and its origin.

| Document | Content |
|---|---|
| [[overview]] | Purpose, conceptual basis, reuse, implemented scope and open requirements of the template |
| [[lineage]] | Edition cases, technical sources, test artefacts and the case comparison behind the shared core |

### Records

| Document | Content |
|---|---|
| [[decisions]] | Architecture decision records (ADR) |
| [[journal]] | Verified results per work session |
| [[handoff]] | Open received items until verified integration |

## Fork inheritance

[[decisions]] and [[journal]] start with the history of the template. A fork keeps these entries as its inherited record and appends its own entries below a heading that names the fork. A fork may keep `knowledge/template/` as reference or delete it. After a deletion, the links from inherited records to [[overview]] and [[lineage]] no longer resolve.

## Reading order by task

The script names carry the numbers of the processing steps. They are independent of the numbers of the configuration documents.

| Task | Script | Documents |
|---|---|---|
| Image preparation | `pipeline/01_extract_images.py`, `pipeline/fetch_facsimiles.py` | [[02_DATA]] |
| Inventory | `pipeline/02_analyze.py` | [[02_DATA]], [data contract](../reference/data-contract.md) |
| Transcription | `pipeline/03_transcribe.py` | [[02_DATA]], [[03_CONTEXT]], [data contract](../reference/data-contract.md), [provider records](../reference/provider-records.md) |
| Quality assessment | `pipeline/04_validate.py` | [[03_CONTEXT]], [data contract](../reference/data-contract.md) |
| TEI generation | `pipeline/05_annotate_tei.py`, `pipeline/validate_schema.py` | [[01_PROJECT]], [[03_CONTEXT]], [[04_TEI_MAPPING]], [TEI base mapping](../reference/tei-mapping.md) |
| Inspection design | none | [[01_PROJECT]], [[03_CONTEXT]], [[04_TEI_MAPPING]], [[05_DESIGN]] |
| Frontend | `pipeline/06_build_frontend.py` | [[01_PROJECT]], [[05_DESIGN]], [data contract](../reference/data-contract.md) |
| Review and correction | `pipeline/update_review.py`, `pipeline/review_server.py` | [[03_CONTEXT]], [local review contract](../reference/local-review.md) |

[SETUP.md](../SETUP.md) describes the setup and alternative entry points. Historical edition cases serve provenance checks, and their metadata, rights and conventions do not pass into a new fork unchecked.

## Terms

German project terms appear where a script, a proper name or a quoted project vocabulary requires them.

The [conceptual basis](template/overview.md#conceptual-basis) defines the agent-supported edition workflow and the epistemic infrastructure of the edition project.

### Edition configuration

The documents `01_PROJECT.md` to `05_DESIGN.md`, which a fork fills with its own decisions.

### Candidate

A TEI file in `results/tei/` that step 5 or an external workflow produced and that has not yet been accepted.

### Review state

The human-controlled state of a page (`machine_unreviewed`, `in_review`, `human_verified`, `accepted`). The automatic `overall_status` of step 4 is separate from it.

### INVENTAR_START and INVENTAR_END

The HTML comment markers in `02_DATA.md` between which step 2 writes the inventory. The German names are part of the script contract and stay unchanged.

### Kurrent

The German cursive handwriting in use from the sixteenth to the twentieth century.
