# Agentic Edition Pipeline

> Research preview, version 0.10.0. The template is under active development and has no stable release yet.

A forkable repository template for digital edition workflows operated with an AI harness, the working environment in which an agent reads the repository, runs tools and changes files. The template combines a knowledge base for the edition's decisions with Python scripts, prompts and data contracts for image transcription, quality assessment, TEI-XML generation, local correction and static publication.

The deterministic workflow and the local correction service have automated tests. Transcription quality, project-specific annotations and scholarly acceptance need evidence from the individual edition, as described in the [evaluation reference](reference/evaluation.md).

## Quickstart

With Python 3.11+ and [uv](https://docs.astral.sh/uv/) installed, build a synthetic edition without an API key, network access or research data:

```console
uv run python examples/offline-quickstart/run.py
```

The [quickstart guide](examples/offline-quickstart/README.md) explains the isolated workspace, the preview command and what the run verifies.

For a real edition, fork the [repository](https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline) and follow [SETUP.md](SETUP.md). The [video tutorial](https://youtu.be/krL-xMxTa_c) *Agentic Edition Pipeline mit GPT-6 Astra | Live-Demo* records an earlier development session with adaptation and review on historical documents. The documentation here describes the current state.

## Workflow components

Each component can be used on its own when the inputs match. The script numbers name the supplied processing path.

| Task | Supplied component | Input |
|---|---|---|
| Prepare page images | PDF rasterization or remote-image download | Ordered source pages |
| Inventory the corpus | Source and metadata inventory | Declared document boundaries |
| Transcribe | Image-based OCR/HTR through a Large Language Model (LLM) provider | Inventory, page images and a tested prompt |
| Assess text quality | Rules and an optional text-only LLM judge | Transcription JSON under the data contract |
| Generate base TEI | Deterministic mapping with a text-preservation check | Current quality assessment and project fields |
| Inspect and correct | Static viewer and a local write service | Generated edition data |
| Publish | Publication gate and static site build on GitHub Pages | Rights clearance and human acceptance |

Existing transcription JSON enters at quality assessment and existing checked TEI at the frontend build. Other formats need a converter. The [processing reference](reference/pipeline.md) lists commands, options and outputs.

## Models and methods

The model that runs the AI harness and the models the processing scripts call are configured independently. The supplied adapters connect Gemini, OpenAI, Anthropic and Ollama, and other LLMs, specialist OCR/HTR engines or machine-learning methods enter through an adapter or format converter that satisfies the same data and provenance contracts. Base TEI generation calls no model. Named entities, authority links and document-specific layout need an explicitly implemented extension.

The frontend shows facsimiles beside the text, review states, provenance and TEI downloads. GitHub Pages serves it read-only. Corrections go through the local service, which writes version-checked changes into the repository files and leaves committing, pushing and acceptance to the responsible people.

## Documentation

- [Setup for an edition](SETUP.md)
- [Agent working contract](AGENTS.md) and [knowledge index](knowledge/00_INDEX.md)
- [Processing reference](reference/pipeline.md) and [evaluation reference](reference/evaluation.md)
- [Data contract](reference/data-contract.md), [base TEI mapping](reference/tei-mapping.md), [local corrections](reference/local-review.md) and [provider records](reference/provider-records.md)
- [Schema selection](schemas/README.md) and [template overview](knowledge/template/overview.md)

## Licence and citation

Code is licensed under the [MIT License](LICENSE). Documentation and knowledge documents are licensed under CC BY 4.0. Third-party research data keeps its own rights.

Created by [Christopher Pollin](https://github.com/chpollin), [Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft). Cite the repository with [CITATION.cff](CITATION.cff).
