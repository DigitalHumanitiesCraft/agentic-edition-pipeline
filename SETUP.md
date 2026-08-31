# SETUP.md — Instantiating the Agentic Edition Pipeline

This file guides you through adapting the template for your own edition project. Work through it top to bottom. Each section identifies a configuration point and tells you exactly which file to open and what to fill in. When done, delete or archive this file.

To verify the locked environment and deterministic pipeline before editing the template, run `uv run python examples/offline-quickstart/run.py`. The synthetic example needs no provider key, writes to `.aep-quickstart/`, and leaves the project knowledge and corpus directories unchanged. Its scope, preview command, and fail-closed replacement rules are documented in `examples/offline-quickstart/README.md`.

Prerequisites are Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Install uv before the first command below; the repository then creates and locks its own Python environment.

---

## 1. Fork and clone

1. Click **Use this template** (or fork) on GitHub to create your own copy.
2. Clone your fork locally.
3. Install Python dependencies.

```
uv sync --extra dev
```

4. Copy the environment file and add your API keys.

```
cp .env.example .env
```

Open `.env` in any text editor. At minimum, fill in one provider key for step 3 when the pipeline should transcribe images. Step 4 can run deterministically, and step 5 is always deterministic.

The transcription and optional LLM-validation paths check their key at startup and abort with `no API key configured, this step requires one` instead of producing empty or partial results. There is no key-less transcription mode; transcriptions produced outside step 3 enter the pipeline as contract-conformant JSON (see `knowledge/08_DATA_CONTRACT.md`).

---

## 2. Required configuration

These are the points that every project must touch. Nothing else needs to change to get a working pipeline.

### 2.1 Project identity — `knowledge/01_PROJECT.md`

Fill in the markdown table at the top of the file. The `Projektname` row drives the frontend and project-level catalog title. Each TEI document title comes from object metadata and falls back to its object ID. The remaining fields support the project assessment in `knowledge/00_INDEX.md`.

Fields that affect generated output:

| Field | Where it appears |
|---|---|
| Projektname | Frontend title and project-level catalog |
| Herausgeber / Editor | TEI `titleStmt/editor` |
| Institution | TEI `publicationStmt/publisher` |
| Lizenz | TEI `publicationStmt/availability/licence` |
| Sprachen | Project documentation; each TEI language comes from object metadata |

The research question and edition type determine which UI components `knowledge/05_DESIGN.md` will contain. Fill them in before running step 5b (design).

### 2.2 Corpus description — `knowledge/02_DATA.md`

Describe your source material: what types of documents exist (manuscript, typescript, printed text, mixed), where they are stored, and any known quality issues with the digitisations. The automated inventory block between `<!-- INVENTAR_START -->` and `<!-- INVENTAR_END -->` is filled in by `pipeline/02_analyze.py --update-knowledge`.

Source material placement:

| Source type | Put files in |
|---|---|
| PDF files | `data/sources/pdf/` |
| Image scans (JPEG, PNG, TIFF) | `data/sources/images/{doc_id}/` |
| Existing transcriptions (plain text) | `data/sources/text/` for inventory; convert into the JSON data contract before step 4 |
| Existing PAGE-XML | `data/sources/text/` for inventory; convert into the JSON data contract before step 4 |
| Existing TEI | `data/sources/text/` as source and checked candidates in `results/tei/`; the supplied Pages gate requires schema conformance and `revisionDesc/@status="accepted"` |
| Structured transcription JSON (data contract) | `data/sources/text/` for the inventory; contract-conformant copies in `data/processed/transcriptions/` for steps 4-6 |

With ready-made image scans, step 1 is skipped entirely: all scripts resolve images through one shared root resolution (`data/sources/images/{doc_id}/` first, then `data/processed/images/{doc_id}/`), so supplied scans are consumed directly by steps 2, 3, and 6.

Structured transcription JSON must follow the pipeline data contract in `knowledge/08_DATA_CONTRACT.md` (`_meta`, `object_id`, and `pages` at the top level; page text and review state per page; object metadata under `metadata`). Step 2 counts source JSON pages from the `pages` array but does not convert plain text, PAGE XML, or TEI.

Use `data/sources/manifest.json` when catalogue metadata or page images come from an external system. The committed file is empty. Add one record per document:

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

Run `uv run python pipeline/02_analyze.py`, then `uv run python pipeline/fetch_facsimiles.py --all --from-manifest`. Step 2 merges the declared metadata with locally discovered files and rejects count differences between declared and materialized pages. The fetch utility records URL, filename, and SHA-256 for each page, uses bounded retries for transient server errors, and spaces requests according to `.env`. Step 3 verifies this materialization record before it calls a model.

### 2.3 Transcription conventions — `knowledge/03_CONTEXT.md`

Fill in the transcription convention table. The default conventions (uncertain readings as `[?]`, illegible passages as `[...]`, deletions as `~~text~~`, insertions as `{text}`) are already in the transcription prompt. Override them here if your project uses different markers or has special requirements (e.g. diplomatic conventions for a critical edition, special handling of stamps or marginalia).

Also select which annotation types the TEI should carry, such as persons, places, organisations, dates, and bibliographic references. The selection becomes a requirement for the TEI mapping in step 2.4 and for any project-specific implementation.

### 2.4 TEI element mapping — `knowledge/04_TEI_MAPPING.md`

Fill in the Annotationsregeln section with project-specific, testable rules:

```
- Personal names: <persName ref="GND-URI"> — use GND authority file
- Place names: <placeName ref="Wikidata-URI"> — use Wikidata Q-identifier
- Dates: <date when="YYYY-MM-DD"> — ISO 8601
```

The first body-mapping table records the structures implemented by the base renderer. Add project structures to the second table and implement them in the deterministic renderer or in a separate documented stage. Their presence in the knowledge document does not change the output by itself.

---

## 3. LLM provider selection

Configure in `.env`. The pipeline defaults to Gemini for transcription in step 3. Validation in step 4 may use a separate provider. Step 5 generates TEI deterministically and has no provider setting.

| Provider | Key in .env | Default model |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-opus-4-5` |
| Ollama (local) | `OLLAMA_BASE_URL` | model name in `*_MODEL` |

To activate the LLM judge for validation in step 4, set its provider and model:

```
VALIDATION_PROVIDER=anthropic
VALIDATION_MODEL=claude-haiku-4-5
```

Leaving `VALIDATION_PROVIDER` empty keeps validation deterministic.

---

## 4. Processing parameters

All tunable values live in `.env` and are read by `pipeline/config.py`.

| Variable | Default | When to change |
|---|---|---|
| `BATCH_DELAY` | `2.0` | Reduce for fast APIs, increase if hitting rate limits |
| `CHUNK_SIZE` | `20` | Lower for vision models with small context windows, raise for models that handle more images |
| `IMAGE_DPI` | `150` | Raise to `300` for small print or fine handwriting; lower for large corpus to save disk space |
| `FETCH_DELAY_SECONDS` | `0.5` | Increase when the image host requests a lower request rate |
| `FETCH_MAX_RETRIES` | `3` | Bound retries for HTTP 429, server errors, and temporary connection failures |
| `FETCH_BACKOFF_SECONDS` | `1.0` | Set the initial exponential retry delay |

`IMAGE_DPI` only affects the PDF-to-image extraction in step 1. For ready-made image scans it has no effect; their resolution is fixed by the delivered digitisation and must be ensured at the source. As a minimum for diplomatic transcription, aim for the equivalent of 300 DPI of the original page (for a single octavo page roughly 2500 pixels on the long edge; more for fine print or small handwriting). Double-page book scans at low resolution are generally insufficient for faithful transcription of the running text; expect such pages to be gated as `page_type: gate_low_resolution` (see `knowledge/08_DATA_CONTRACT.md`) rather than transcribed.

---

## 5. Prompt customisation

The transcription and validation prompts in `pipeline/prompts/` are starting points. Every corpus requires adapting the transcription instrument to its source material. Adapt the prompt, run it on a fixed sample, evaluate the output against the originals, and record a new prompt state for every changed instruction. A production run requires a project-specific, evaluated prompt state.

Layer 1 (base rules) changes are typically needed when:

- Your source language or script is not covered by the base rules (e.g. Arabic script, East Asian languages, Kurrent).
- Your edition type requires structural rules the default does not include (e.g. verse numbering, tabular ledger entries).
- A pilot run showed a systematic error that a rule change would prevent.

Project-specific transcription content enters through the runtime layers documented in `pipeline/prompts/transcription.md`. Step 3 now assembles these layers directly. Document any Layer 1 changes in `knowledge/decisions.md` with their rationale.

TEI generation follows a separate contract. Step 5 reads project metadata from `knowledge/01_PROJECT.md` and applies deterministic code. `knowledge/04_TEI_MAPPING.md` specifies project-specific structures and entities that a fork must implement in the renderer or in a separate documented stage. No TEI annotation prompt is assembled at runtime.

Create one profile file at `pipeline/prompts/profiles/{prompt_profile}.md` for every material class selected in the source manifest. Profiles contain only the additional rules for that material. Examples include correspondence, account books, inventories, printed forms, or mixed bundles. A declared profile without a corresponding file fails the document at the prompt boundary.

Per-object prompt overrides for individual documents with special handling go in `pipeline/prompts/objects/{object_id}.md`. Step 3 appends the base rules, profile, metadata context, and object override in that order. `_meta.prompt_layers` and `_meta.prompt_hash` record the assembled instrument.

Operational note for agentic transcription: a vision model can only read an image that exists as a local file. Materialize remote facsimiles first (`pipeline/fetch_facsimiles.py`), then read the saved file; fetching a URL inside an agent tool returns bytes and metadata, not vision input.

---

## 6. Schema adaptation

The pipeline ships with two validation schemas, documented in detail in `schemas/README.md`.

- `schemas/basisformat.rng` — official DTA-Basisformat RelaxNG schema (CC BY-SA 3.0 DE, Deutsches Textarchiv), used for full conformance validation of generated TEI before publication. For manuscript corpora, download the manuscript variant from https://www.deutschestextarchiv.de/basisformat_ms.rng instead.
- `schemas/tei_all.rng` — runnable default target that accepts the base renderer output.

Choosing the validation target is part of setting up a fork (ADR-005). The template defaults to TEI All so its base renderer has an executable gate. DTABf is a stricter supplied alternative for historical German-language texts and requires header adaptation. A project ODD/RNG supplies the final edition-specific contract. The options and their trade-offs are laid out in `schemas/README.md`.

To set or change the target:

1. Put your profile's RelaxNG schema into `schemas/` and point `VALIDATION_SCHEMA` in `pipeline/config.py` at it. Check conformance with `uv run python pipeline/validate_schema.py`.
2. Update `knowledge/04_TEI_MAPPING.md` to match the new profile.
3. Record the decision in `knowledge/decisions.md`.

---

## 7. Frontend configuration

The frontend in `docs/` is a static Vanilla JS application with no JavaScript build system. Its read-only facsimile-text view supports inspection and displays the human review status carried by the TEI.

`pipeline/06_build_frontend.py` reads the project name from `knowledge/01_PROJECT.md` and writes it to `docs/data/catalog.json`. The client applies that value to the browser title and `<h1>`. The script also generates per-object data and synchronizes downloadable TEI into `docs/tei/`. Footer text remains hand-maintained in `docs/index.html`.

To add research-specific UI components (e.g. a timeline, a concordance, a named-entity register), fill in `knowledge/05_DESIGN.md` before running step 6. Claude Code derives the component list from that document and implements only what is specified there.

GitHub Pages: select **GitHub Actions** as the source. `.github/workflows/pages.yml` rebuilds the ignored JSON data layer from committed `results/tei/` and deploys `docs/` on every push to `main`.

---

## 8. Verification checklist before first run

- [ ] `.env` exists with at least one API key for the transcription provider
- [ ] `knowledge/01_PROJECT.md` — project name and institution filled in
- [ ] `knowledge/02_DATA.md` — source type selected and data placed in `data/sources/`
- [ ] `knowledge/03_CONTEXT.md` — transcription conventions confirmed or customised
- [ ] `knowledge/04_TEI_MAPPING.md` — annotation types and mapping rules filled in
- [ ] `knowledge/05_DESIGN.md` — research question has been used to derive at least two epics (or left for Claude Code to derive at step 5b)
- [ ] `data/sources/manifest.json` — external metadata, remote pages, and prompt profiles declared where needed
- [ ] `pipeline/prompts/profiles/` — every selected prompt profile exists and has been evaluated on a fixed sample
- [ ] Pilot test planned: first run `pipeline/02_analyze.py` and verify the inventory before triggering any LLM steps

When all boxes are checked, open Claude Code in this directory. It reads `CLAUDE.md` first and will guide you through the pipeline step by step.
