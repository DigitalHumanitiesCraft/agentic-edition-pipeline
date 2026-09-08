# Agentic Edition Pipeline

> **Research Preview (v0.10.0)**
>
> This project is under active development and is not yet a stable release.

A forkable repository template for digital edition workflows with an AI harness. It combines reusable project knowledge and processing tools for transcription, TEI-XML generation and review interfaces, with adaptable models and methods.

The supplied deterministic workflow and local correction service have automated tests. Transcription quality, project-specific annotations and scholarly acceptance require evidence from the individual edition.

## What it is

The repository provides Python scripts, prompts, data contracts and a knowledge base. An AI harness is the working environment in which an agent can read those files, use tools and modify the project. Its agent uses the repository context to adapt and operate an edition workflow.

The knowledge documents record source descriptions, editorial conventions, modelling decisions and verification requirements. They make project choices available across sessions and tools. Adding a requirement to a document still requires implementation and testing where the supplied code does not support it.

## Use it for your own edition

Create your own copy of the [repository](https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline), open it in your AI harness and ask the agent to read [AGENTS.md](AGENTS.md). Define your sources, editorial requirements and processing methods using [SETUP.md](SETUP.md).

The [video tutorial](https://youtu.be/krL-xMxTa_c), *Agentic Edition Pipeline mit GPT-6 Astra | Live-Demo*, demonstrates adaptation and review on historical documents. It records a development session; current capabilities are documented here.

To try the deterministic workflow without an API key or research data, install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then run:

```console
uv run python examples/offline-quickstart/run.py
```

This creates an isolated synthetic edition. See the [quickstart guide](examples/offline-quickstart/README.md) for previewing it and the exact verification scope.

## Models and methods

The model in the AI harness and the models used for document processing are independent choices. The supplied processing adapters support Gemini, OpenAI, Anthropic and Ollama. Choose a compatible model and configure access for each task.

Other frontier models, local models, specialist OCR/HTR systems and machine-learning methods can be integrated through adapters or format converters. They must satisfy the relevant input, output and provenance contracts. The architecture supports these substitutions; the repository does not include every integration.

The current implementation uses Python and native JavaScript. Base TEI generation is deterministic. Named entities, authority links and document-specific layout structures need an explicitly implemented extension.

## Workflow components

Use the components that match your inputs. The script numbers describe the supplied processing path.

| Task | Supplied component | Dependency |
|---|---|---|
| Prepare page images | PDF extraction or remote-image download | Ordered source pages |
| Inventory the corpus | Source and metadata inventory | Declared document boundaries |
| Transcribe | Image-based OCR/HTR | Checked inventory, images and evaluated prompt |
| Assess text quality | Rules and optional text-only model assessment | Contract-conformant transcription JSON |
| Generate base TEI | Deterministic mapping and text-preservation checks | Current quality assessment and project configuration |
| Inspect and correct | Static viewer and optional local write service | Generated edition data |
| Publish | Schema and review-state gates, static site build | Rights clearance and human acceptance |

Existing transcription JSON can enter at quality assessment. Existing checked TEI can enter at the frontend build. Other input formats require conversion. Review-interface requirements should be defined with the first sample and refined as errors become visible.

A correction changes the transcription state and requires dependent outputs to be regenerated or rechecked. [Processing reference](reference/pipeline.md) documents commands, dependencies and limits.

## Capabilities and limits

The frontend displays facsimiles beside text, review states, provenance and TEI downloads. The optional local service writes version-checked corrections into repository files, preserves raw text and records changes and proposals. It does not commit or push them.

GitHub Pages serves the read-only edition. Repository writes require the local service. Actor labels in that service are self-declared within a trusted local session; it is not a multi-user authentication system.

Formal XML validity, text preservation, transcription accuracy and scholarly acceptance are separate checks. Model confidence and automatic quality labels do not grant acceptance. Layout reconstruction, entity resolution, image-first blind review and project annotation editors require further implementation.

## Documentation

- [Setup and entry points](SETUP.md)
- [Agent working contract](AGENTS.md) and [knowledge index](knowledge/00_INDEX.md)
- [Processing reference](reference/pipeline.md) and [evaluation reference](reference/evaluation.md)
- [Data contract](knowledge/08_DATA_CONTRACT.md), [local corrections](knowledge/local-review.md) and [provider records](knowledge/provider-records.md)
- [Schema selection](schemas/README.md) and [current requirements](knowledge/specification.md)

## Licence and citation

Code is licensed under the [MIT License](LICENSE). Documentation and knowledge documents are licensed under CC BY 4.0. Third-party research data retains its own rights.

Created by [Christopher Pollin](https://github.com/chpollin), [Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft). Use [CITATION.cff](CITATION.cff) to cite the repository.
