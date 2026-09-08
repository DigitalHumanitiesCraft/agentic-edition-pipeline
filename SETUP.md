# Set up an edition

Use this guide to configure a fork for its own sources and editorial requirements. Keep it available for later adaptations. An agent should first read [AGENTS.md](AGENTS.md).

For a software-only check, use the [offline quickstart](examples/offline-quickstart/README.md). It leaves the edition placeholders and corpus directories unchanged.

## Environment and access

Create and clone your own copy of the repository. Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then run:

```console
uv sync --locked --extra dev
```

Open the repository in your AI harness and direct it to `AGENTS.md` if that file is not loaded automatically. The harness requires its own access configuration.

When using a processing provider, copy `.env.example` to `.env` with your shell or file manager and configure the chosen adapter. In PowerShell:

```powershell
Copy-Item .env.example .env
```

Gemini, OpenAI and Anthropic need their configured API keys. Ollama uses a reachable local service and a compatible installed model. The deterministic workflow needs no provider key. Keep credentials out of Git and public assets.

## Configure the edition

The configuration files describe decisions for this corpus. New requirements can also need code changes. Writing a rule in Markdown alone does not implement it.

| File | Required decisions |
|---|---|
| [01_PROJECT.md](knowledge/01_PROJECT.md) | Project identity, research question, edition type, responsible editors, publication terms |
| [02_DATA.md](knowledge/02_DATA.md) | Source types, document boundaries, page order, completeness, provenance and rights |
| [03_CONTEXT.md](knowledge/03_CONTEXT.md) | Transcription conventions, allowed model context, review procedure |
| [04_TEI_MAPPING.md](knowledge/04_TEI_MAPPING.md) | Base and additional structures, annotation policy, chosen schema |
| [05_DESIGN.md](knowledge/05_DESIGN.md) | Inspection tasks and testable interface requirements |

In `01_PROJECT.md`, preserve the table labels read by the scripts. `Projektname` supplies the catalog and frontend title. `Herausgeber / Editor`, `Institution` and `Lizenz` populate the TEI header. Document titles and languages come from object metadata. Check missing metadata explicitly; the current renderer has an object-ID title fallback and a German language fallback.

Define the inspection interface with the first sample. Add components only where the edition needs them and verify their implementation against the requirements.

## Select an input route

| Available input | Placement and next operation |
|---|---|
| PDFs | `data/sources/pdf/`; extract images, then inventory |
| Ready page scans | `data/sources/images/{doc_id}/`; inventory directly |
| Remote facsimiles | Declare ordered URLs in `data/sources/manifest.json`; inventory and materialize images |
| Plain text or PAGE XML | Preserve under `data/sources/text/`; implement conversion to the transcription JSON contract |
| Contract-conformant transcription JSON | Checked copies in `data/processed/transcriptions/`; assess quality |
| Existing TEI | Preserve source under `data/sources/text/`; checked candidates in `results/tei/` can enter the frontend build |

The inventory does not convert text formats or TEI. Original sources remain distinguishable from generated results. Imported metadata, imported transcription and independent reference editions need separate provenance and declared roles.

### Optional source manifest

The manifest uses version `0.1`. A document can declare its ID, material-specific prompt profile, metadata and consecutively numbered pages.

```json
{
  "version": "0.1",
  "documents": [
    {
      "id": "doc1",
      "prompt_profile": "correspondence",
      "metadata": {
        "title": "Letter to N. N.",
        "signature": "A 1",
        "date": "1901-05-22",
        "language": "de",
        "object_type": "correspondence"
      },
      "pages": [
        {"page": 1, "image_url": "https://example.org/iiif/doc1/page1/full/max/0/default.jpg"}
      ]
    }
  ]
}
```

Within one document, every page must use the same remote or local source mode. Run the inventory and then `pipeline/fetch_facsimiles.py --all --from-manifest` for remote pages. The fetch record binds URLs to downloaded bytes. Count mismatches stop the affected operation.

The supplied transcription adapter reads locally materialized image bytes. Other harness tools may have different image-input mechanisms; verify that the model actually receives the image.

## Models and transcription instrument

The harness model and processing models are independent. Configure the processing adapter in `.env`:

| Adapter value | Connection | Model selection |
|---|---|---|
| `gemini` | `GEMINI_API_KEY` | `TRANSCRIPTION_MODEL` |
| `openai` | `OPENAI_API_KEY` | `TRANSCRIPTION_MODEL` |
| `anthropic` | `ANTHROPIC_API_KEY` | `TRANSCRIPTION_MODEL` |
| `ollama` | `OLLAMA_BASE_URL` | Compatible installed model in `TRANSCRIPTION_MODEL` |

Set `TRANSCRIPTION_PROVIDER` and an appropriate model identifier. Image transcription requires image support through that adapter. The checked-in default is a configuration starting point. Model suitability requires a project-specific test. Additional engines need an adapter or format converter with provenance and contract tests.

Optional text-only model assessment uses `VALIDATION_PROVIDER` and `VALIDATION_MODEL`. Leaving the provider empty or passing `--no-llm` selects deterministic assessment. Base TEI generation has no provider setting.

The transcription prompt is assembled in this order:

1. Base rules in `pipeline/prompts/transcription.md`.
2. A selected material profile in `pipeline/prompts/profiles/{prompt_profile}.md`.
3. Selected document metadata.
4. An optional object instruction in `pipeline/prompts/objects/{doc_id}.md`.

The executed layers and combined prompt hash are recorded. A declared profile must exist. Changing conventions also requires checking their JSON and TEI mappings.

The supplied script includes selected metadata automatically. An image-only experiment requires a documented adaptation and a new prompt state. Keep prior edition text out of a supposed independent recognition run. Describe outputs as metadata-assisted where appropriate.

Test the instrument on a fixed, varied sample. Record expected readings, unresolved cases and changes to instructions. Inspect the source images before authorizing a corpus-wide provider run. The first `N` documents selected by `--sample N` are not automatically representative.

### Processing parameters

Values are read through `pipeline/config.py` from `.env`.

| Variable | Supplied default | Purpose |
|---|---|---|
| `BATCH_DELAY` | `2.0` | Delay between documents |
| `CHUNK_SIZE` | `20` | Maximum images grouped per transcription call |
| `IMAGE_DPI` | `150` | PDF rasterization resolution |
| `FETCH_DELAY_SECONDS` | `0.5` | Delay between remote-image requests |
| `FETCH_MAX_RETRIES` | `3` | Retry bound for transient fetch failures |
| `FETCH_BACKOFF_SECONDS` | `1.0` | Initial fetch retry delay |

Adjust these to the selected service and sources. A higher rasterization DPI cannot recover detail absent from the original digitisation. Check small handwriting, print and double-page scans visually at the actual model input resolution.

## TEI and schema

The base renderer covers metadata, page structure, paragraphs, line breaks and declared transcription markers. It preserves text in order under its stated whitespace normalization.

Specify additional structures before generating annotations. Decide whether entities are inline or stand-off, how mentions point to the text and how identities and relationships will be verified. Authority-file links require their own evidence. The base template does not resolve named entities or assign GND identifiers.

Choose a schema using [schemas/README.md](schemas/README.md). TEI All is the runnable default. DTABf is a supplied stricter alternative that requires corresponding header and mapping changes. For an edition-specific profile, place the schema in `schemas/`, set `VALIDATION_SCHEMA` in `pipeline/config.py`, update `04_TEI_MAPPING.md` and record the decision.

Run `pipeline/validate_schema.py` for RelaxNG validation. Structural validity does not establish transcription accuracy or scholarly acceptance.

## Inspect, correct and publish

The static frontend reads generated catalog and object JSON from TEI. The builder uses `01_PROJECT.md` for the project name. The agent uses `05_DESIGN.md` to implement additional interface requirements; the builder does not render arbitrary requirements from that document.

Use the [processing reference](reference/pipeline.md) for preview and local editor commands. The optional editor writes version-checked corrections, raw text and history into repository data. A save sets the page to `in_review`. It does not grant acceptance, commit changes or push to GitHub.

Preserve original recognition notes and check whether they still describe the current text. A human correction becomes an evaluation reference only after its verification method and maturity are recorded.

GitHub Pages serves read-only files. The supplied workflow requires schema conformance and accepted TEI, then rebuilds and deploys the static site on a push to `main`. Resolve source rights and approve the public contents before enabling publication. Keep private call records and recovery copies out of the site.

## Check the chosen route before running it

Confirm source completeness, project conventions, input context, schema and the applicable review requirements. Check provider access only for components that need it. Verify inventory and a fixed sample before approving a paid corpus run. Use [evaluation guidance](reference/evaluation.md) to state what each test actually establishes.
