---
title: Template overview
description: Purpose, reuse, working contract, implemented scope and open requirements of the reusable edition template
tags: [template, project, requirements]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: complete
created: 2026-09-08
updated: 2026-09-30
---

# Template overview

The repository is a reusable template for digital edition workflows run in an AI harness. It connects maintained project knowledge with processing scripts, prompts and data contracts, and an agent uses this context to configure and adapt an edition. The template is a research preview without a stable release. `pyproject.toml` and `CITATION.cff` carry the current version.

## Conceptual basis

### Agent-supported edition workflow

An agent-supported edition workflow is an editorial workflow in which AI agents based on Large Language Models (LLMs) plan work steps, use tools and adapt their approach to intermediate results on the basis of project-specific knowledge and editorial rules. People define the goals and the agents' scope of action and take responsibility for scholarly and technical review.

### Epistemic infrastructure of the edition project

The epistemic infrastructure of the edition project is a working environment jointly shaped by editors, developers and other contributors, in which people work with AI agents to produce, examine and revise scholarly results. It connects sources, research data, documented project knowledge, tools and review procedures. Human responsibilities, provenance, justification, review status and uncertainties remain traceable.

Epistemic infrastructure as a general concept also applies to research environments without AI agents. The definition here specifies its use in an edition project with agent-supported work. It sets a design requirement for that project's working environment. The supplied processing path and correction service implement parts of this requirement, with the implemented scope and open requirements described below. The [evaluation reference](../../reference/evaluation.md) distinguishes formal checks, recognition quality and scholarly acceptance and states the evidence each needs.

## Reuse

The architecture keeps the choice of the harness model independent of the choice of processing methods. The template supplies Python scripts, a native JavaScript frontend and adapters for Gemini, OpenAI, Anthropic and Ollama. Further models, specialised OCR or HTR systems (optical character recognition, handwritten text recognition) and other machine-learning methods need a matching adapter or converter. Technology independence here means the possibility of a justified substitution, while the supplied implementation has concrete technical prerequisites.

The documents `01_PROJECT.md` to `05_DESIGN.md` hold the open settings of an individual edition. Template maintenance and isolated tests keep these placeholders. A fork takes over methods and contracts and makes its own decisions about sources, rights, editorial conventions and models. [[00_INDEX]] explains which records a fork inherits. The historical cases and their provenance are documented in [[lineage]].

## Working contract

[AGENTS.md](../../AGENTS.md) holds the shared working contract, and harness-specific entry files point to it. The numbered scripts describe one supplied processing path. Existing transcriptions and TEI files allow other entry points, and the [processing reference](../../reference/pipeline.md) names their dependencies.

The inspection interface and the edition model take shape with the first sample. Text corrections require dependent outputs to be checked again. Stored changes, formal validation and scholarly acceptance remain separate states.

## Implemented correction contract

Version 0.10.0 added local editing of canonical transcription files through the browser and the same local API for agents. A text correction keeps the raw text, sets the page to `in_review` and creates a stored change event. Proposals have their own storage place and change neither source text nor acceptance.

Before a stored state is taken over, deterministic quality assessment, text preservation and the configured RelaxNG schema must pass. Canonical JSON, TEI and browser data are prepared together. Conflicts discard no user input. Previous file states allow recovery, and a detected interrupted write blocks further writes until recovery. The [local review contract](../../reference/local-review.md) and the [provider records](../../reference/provider-records.md) describe the implemented contracts.

Optional annotations can bind their input text. Stale annotations are shown and block publication. Their renewal is project-specific, and the template introduces no automatic entity recognition or layout reconstruction.

The interface shows write capability, current text, raw text, change history and provenance. Synthetic tests check stored corrections through to the delivered TEI. Call records and reusable chunk calls extend the transcription path. New provider runs and a scholarly review of transcriptions are outside the technical test evidence.

## Documentation contract

The README explains the repository, reuse, models, tasks and functional limits. The complete commands are in [SETUP.md](../../SETUP.md) and the [processing reference](../../reference/pipeline.md). Concrete research corpora stay in the provenance documents, and their facts do not become default configuration.

[AGENTS.md](../../AGENTS.md) is the shared action layer for AI harnesses, and harness-specific files contain only the entry. Additional methods need a documented adapter or converter whose input, output and provenance are checked. The model choice of the harness is independent of the processing configuration.

The numbered scripts keep their names. Text quality assessment, formal schema validation and scholarly acceptance are described separately. Design is an accompanying specification of the inspection tasks, and the pipeline has no mandatory design step.

Knowledge documents are English. [[decisions]] records the division of documents into edition configuration in `knowledge/`, fixed contracts in `reference/` and knowledge about the template in `knowledge/template/`.

## Status and scope

Observations from two local test instances and a [recorded session video](https://youtu.be/krL-xMxTa_c) specified the requirements on metadata provenance, model context and annotation review. The research data and rights decisions of these instances remain outside the template. The [evaluation reference](../../reference/evaluation.md) limits the evidential value of technical tests and of the video observations.

Scholarly acceptance takes place in each edition project. User acceptance of the template extension is still required separately. [[journal]] documents the verified scope, and the public Git state documents the published version.

## Open requirements

These requirements derive from the video analysis. The base frontend and base data model do not implement them.

| Requirement | Evidence of a future implementation |
|---|---|
| Facsimile zoom and jump to the source evidence | Small script stays inspectable, and a metadata finding leads to the correct page or region |
| Independent first reading | The model text stays hidden until the reviewer's own reading is stored |
| Version status of individual findings | An unchanged old note becomes recognisable as needing review after a text change |
| Controlled comparison of model contexts | Runs on identical images with and without metadata have separate prompts and independent references |
| Semantic annotation workflow | Mentions, identities, roles and relations are modelled and checked separately |
| Provenance across execution paths | API call, harness task and deterministic derivation are traceable by their actual inputs |

The existing editor binds external annotations to text states and stores note changes. It detects no semantic contradictions in unchanged old notes. The provider logger records no arbitrary harness actions.

The evaluation reference names the observation points in the video and the limits of the requirements derived from them. A controlled model comparison, measured costs and an error rate are not available from that session.
