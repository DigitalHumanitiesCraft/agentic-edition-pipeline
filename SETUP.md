# Set up an edition

This guide lists the decisions and actions that turn a fork into an edition of its own sources. The [processing reference](reference/pipeline.md) holds the commands, and [AGENTS.md](AGENTS.md) holds the rules an agent follows. For a software check without research data, use the [offline quickstart](examples/offline-quickstart/README.md).

## Environment and access

Fork and clone the repository, install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then install the locked environment, which includes the development tools:

```console
uv sync --locked
```

Open the repository in your AI harness. If the harness does not load `AGENTS.md` automatically, direct the agent to it. The harness needs its own access configuration.

For a processing provider, copy `.env.example` to `.env` and fill in the adapter settings described below. In PowerShell:

```powershell
Copy-Item .env.example .env
```

Keep credentials out of Git and public assets. The deterministic steps need no provider key.

## Inherit the template record

`knowledge/decisions.md` and `knowledge/journal.md` start with the template's history. A fork keeps those entries as its inherited record and appends its own decisions and journal entries below a heading that names the fork.

`knowledge/template/` describes the reusable template and its lineage. A fork may keep it as reference or delete it. Deleting it also means removing the references to it from `README.md` and `AGENTS.md`.

## Configure the edition

The numbered knowledge documents record the decisions for this corpus. Writing a requirement there does not implement it. Where the supplied code does not cover it, it needs code and tests.

| File | Decisions |
|---|---|
| [01_PROJECT.md](knowledge/01_PROJECT.md) | Project identity, research question, edition type, responsible editors, publication terms |
| [02_DATA.md](knowledge/02_DATA.md) | Source types, document boundaries, page order, completeness, provenance and rights |
| [03_CONTEXT.md](knowledge/03_CONTEXT.md) | Transcription conventions, model context the edition allows, review procedure, pilot sample |
| [04_TEI_MAPPING.md](knowledge/04_TEI_MAPPING.md) | Chosen schema and every structure beyond the base TEI mapping |
| [05_DESIGN.md](knowledge/05_DESIGN.md) | Inspection tasks and testable interface requirements |

### Project fields

The scripts read only those rows of the field table in `01_PROJECT.md` whose label matches one of the following exactly, ignoring case. A value that is empty or starts with `[TODO` counts as missing, and other rows of the table are not read by any script.

| Label | Also accepted | Effect |
|---|---|---|
| Title | Projektname, Titel | Catalog and frontend title, `Digital Edition` when missing |
| Editor | Herausgeber | TEI `titleStmt/editor` |
| Institution | Publisher | TEI `publisher`. Without it, the TEI states that no publisher is declared |
| Edition type | Editionstyp | A value containing `normalis` selects normalised whitespace comparison, any other value diplomatic |
| Language | Sprache | Language of documents whose metadata declares none, written as the `ident` of TEI `langUsage`, so enter a language code such as `de` |
| License | Licence, Lizenz | TEI licence statement |

Document titles and languages come from the object metadata. A document without a title gets its object ID as TEI title, and without any declared language the TEI carries no `langUsage`.

## Select an input route

| Available input | Placement | Next operation |
|---|---|---|
| PDFs | `data/sources/pdf/` | Extract images, then inventory |
| Page scans | `data/sources/images/{doc_id}/` | Inventory |
| Remote facsimiles | Ordered URLs in `data/sources/manifest.json` | Inventory, then `fetch_facsimiles.py --all --from-manifest` |
| Plain text or PAGE XML | `data/sources/text/` | Write a converter to the transcription JSON contract |
| Transcription JSON under the data contract | `data/processed/transcriptions/` | Quality assessment |
| Existing TEI | Source under `data/sources/text/`, checked candidates in `results/tei/` | Frontend build |

The optional source manifest declares document IDs, prompt profiles, metadata and remote pages where file names do not carry them. Its format is specified in the [data contract](reference/data-contract.md). The inventory marks which documents have page images for transcription. It converts no text formats or TEI. Imported metadata, imported transcriptions and independent reference editions keep separate provenance and declared roles.

## Configure the processing models

The adapter is set in `.env`.

| `TRANSCRIPTION_PROVIDER` | Access | Model |
|---|---|---|
| `gemini` | `GEMINI_API_KEY` | `TRANSCRIPTION_MODEL` |
| `openai` | `OPENAI_API_KEY` | `TRANSCRIPTION_MODEL` |
| `anthropic` | `ANTHROPIC_API_KEY` | `TRANSCRIPTION_MODEL` |
| `ollama` | `OLLAMA_BASE_URL` | An installed model with image input in `TRANSCRIPTION_MODEL` |

The checked-in default model is a starting point. Its suitability for the material needs a project-specific test. The adapter sends the locally materialized image bytes, so a model reached through another route must be checked for whether it actually receives the images.

The optional text-only judge in quality assessment uses `VALIDATION_PROVIDER` and `VALIDATION_MODEL`. An empty provider or `--no-llm` selects deterministic assessment. Base TEI generation has no provider setting.

### Transcription prompt

Step 3 assembles the prompt from these layers, in this order:

1. Base rules in `pipeline/prompts/transcription.md`.
2. The material profile `pipeline/prompts/profiles/{prompt_profile}.md` that the manifest selects, described in the [profile folder](pipeline/prompts/profiles/README.md).
3. The document metadata from the inventory.
4. An optional object instruction in `pipeline/prompts/objects/{object_id}.md`.

A change to any layer is a new prompt state. Check the JSON and TEI mapping of changed conventions as well.

### Pilot before a corpus run

Fix a varied pilot sample in `03_CONTEXT.md` with its expected readings and unresolved cases. Check the inputs and prompts of the pilot documents with `--dry-run`, then run them one by one with `--object`, since `--sample N` takes the first N transcribable documents in inventory order. Inspect the results against the source images. Authorize a corpus-wide provider run only after that inspection. The [evaluation reference](reference/evaluation.md) states what a pilot establishes.

### Processing parameters

`.env` also sets the processing parameters.

| Variable | Default | Purpose | Read by |
|---|---|---|---|
| `BATCH_DELAY` | `2.0` | Seconds step 3 waits after a document that called the provider | `pipeline/config.py` |
| `CHUNK_SIZE` | `20` | Maximum images per transcription call | `pipeline/config.py` |
| `IMAGE_DPI` | `150` | PDF rasterization resolution | `pipeline/config.py` |
| `FETCH_DELAY_SECONDS` | `0.5` | Pause between remote-image requests | `pipeline/fetch_facsimiles.py` |
| `FETCH_MAX_RETRIES` | `3` | Retries after a transient fetch failure | `pipeline/fetch_facsimiles.py` |
| `FETCH_BACKOFF_SECONDS` | `1.0` | Initial delay before a fetch retry | `pipeline/fetch_facsimiles.py` |
| `FETCH_MAX_BYTES` | `268435456` (256 MiB) | Largest accepted image response | `pipeline/fetch_facsimiles.py` |

Adjust them to the service and the sources. A higher rasterization resolution cannot recover detail absent from the digitisation, so check small handwriting, print and double-page scans visually at the resolution the model receives.

## TEI and schema

The generator's fixed base mapping is documented in the [base TEI mapping](reference/tei-mapping.md). Specify every further structure, such as entities, layout or apparatus, in `04_TEI_MAPPING.md` before annotations are generated. The base template resolves no named entities and assigns no authority identifiers.

Choose the validation schema with [schemas/README.md](schemas/README.md). TEI All is shipped and configured. DTABf is not shipped and needs an adapted TEI header. For another schema, place it in `schemas/`, point `VALIDATION_SCHEMA` in `pipeline/config.py` at it, and record the choice in `04_TEI_MAPPING.md` and `knowledge/decisions.md`.

## Review and publish

Define the inspection interface in `05_DESIGN.md` with the first sample and refine it as errors become visible. The frontend builder does not interpret that document, so an agent implements its requirements.

Corrections run through the local editor and human review decisions through `update_review.py`, both described in the [processing reference](reference/pipeline.md#review-states-and-corrections). A human correction becomes an evaluation reference only once its verification method is recorded in `03_CONTEXT.md`.

Before enabling GitHub Pages, clear the source rights, approve the public contents and run the [publication gate](reference/pipeline.md#publication-gate) locally. Then set the Pages source to GitHub Actions in the repository settings. The supplied workflow deploys on every push to `main` that passes the gate, the linter and the tests.
