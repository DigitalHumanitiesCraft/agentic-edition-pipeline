# SETUP.md — Instantiating the Agentic Edition Pipeline

This file guides you through adapting the template for your own edition project. Work through it top to bottom. Each section identifies a configuration point and tells you exactly which file to open and what to fill in. When done, delete or archive this file.

To verify the installed dependencies and deterministic pipeline before editing the template, run `python examples/offline-quickstart/run.py`. The synthetic example needs no provider key, writes to `.aep-quickstart/`, and leaves the project knowledge and corpus directories unchanged. Its scope, preview command, and fail-closed replacement rules are documented in `examples/offline-quickstart/README.md`.

---

## 1. Fork and clone

1. Click **Use this template** (or fork) on GitHub to create your own copy.
2. Clone your fork locally.
3. Install Python dependencies.

```
pip install -r requirements.txt
```

4. Copy the environment file and add your API keys.

```
cp .env.example .env
```

Open `.env` in any text editor. At minimum, fill in one provider key for step 3 (transcription). Steps 4 (validation) and 5 (TEI annotation) run without API keys in deterministic mode.

Every step that calls an LLM provider (transcription, LLM validation, LLM annotation) checks its key at startup and aborts with `no API key configured, this step requires one` instead of producing empty or partial results. There is no key-less transcription mode; transcriptions produced outside step 3 enter the pipeline as contract-conformant JSON (see `knowledge/08_DATA_CONTRACT.md`).

---

## 2. Required configuration

These are the points that every project must touch. Nothing else needs to change to get a working pipeline.

### 2.1 Project identity — `knowledge/01_PROJECT.md`

Fill in the markdown table at the top of the file. The `Projektname` row drives the title in the TEI header and the frontend. The remaining fields populate the RIDE self-assessment checklist in `knowledge/00_INDEX.md`.

Fields that affect generated output:

| Field | Where it appears |
|---|---|
| Projektname | TEI `titleStmt/title`, frontend `<h1>` |
| Herausgeber / Editor | TEI `titleStmt/editor` |
| Institution | TEI `publicationStmt/publisher` |
| Lizenz | TEI `publicationStmt/availability/licence` |
| Sprachen | TEI `profileDesc/langUsage`, inventory summary |

The research question and edition type determine which UI components `knowledge/05_DESIGN.md` will contain. Fill them in before running step 5b (design).

### 2.2 Corpus description — `knowledge/02_DATA.md`

Describe your source material: what types of documents exist (manuscript, typescript, printed text, mixed), where they are stored, and any known quality issues with the digitisations. The automated inventory block between `<!-- INVENTAR_START -->` and `<!-- INVENTAR_END -->` is filled in by `pipeline/02_analyze.py --update-knowledge`.

Source material placement:

| Source type | Put files in |
|---|---|
| PDF files | `data/sources/pdf/` |
| Image scans (JPEG, PNG, TIFF) | `data/sources/images/{doc_id}/` |
| Existing transcriptions (plain text) | `data/sources/text/` |
| Existing PAGE-XML or TEI | `data/sources/text/` |
| Structured transcription JSON (data contract) | `data/sources/text/` for the inventory; contract-conformant copies in `data/processed/transcriptions/` for steps 4-6 |

With ready-made image scans, step 1 is skipped entirely: all scripts resolve images through one shared root resolution (`data/sources/images/{doc_id}/` first, then `data/processed/images/{doc_id}/`), so supplied scans are consumed directly by steps 2, 3, and 6.

Structured transcription JSON must follow the pipeline data contract in `knowledge/08_DATA_CONTRACT.md` (`pages` at the top level, page text under `transcription`, object metadata under `metadata`). Step 2 counts their pages from the `pages` array. When the corpus references its facsimiles as remote URLs, declare them in `metadata.image_urls`; `pipeline/fetch_facsimiles.py` can materialize local copies.

### 2.3 Transcription conventions — `knowledge/03_CONTEXT.md`

Fill in the transcription convention table. The default conventions (uncertain readings as `[?]`, illegible passages as `[...]`, deletions as `~~text~~`, insertions as `{text}`) are already in the transcription prompt. Override them here if your project uses different markers or has special requirements (e.g. diplomatic conventions for a critical edition, special handling of stamps or marginalia).

Also select which annotation types the TEI should carry: persons, places, organisations, dates, bibliographic references. The selection here drives the TEI mapping in step 2.4 and the register extraction in step 5.

### 2.4 TEI element mapping — `knowledge/04_TEI_MAPPING.md`

Fill in the Annotationsregeln section with project-specific rules in the format the annotation prompt expects:

```
- Personal names: <persName ref="GND-URI"> — use GND authority file
- Place names: <placeName ref="Wikidata-URI"> — use Wikidata Q-identifier
- Dates: <date when="YYYY-MM-DD"> — ISO 8601
```

The body-mapping table (paragraph, heading, page break, etc.) is pre-filled with sensible defaults. Adjust only where your source structure deviates from the norm (e.g. tabular documents that need `<table>` instead of `<p>`).

---

## 3. LLM provider selection

Configure in `.env`. The pipeline defaults to Gemini for transcription (step 3). You can use different providers for each step.

| Provider | Key in .env | Default model |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-opus-4-5` |
| Ollama (local) | `OLLAMA_BASE_URL` | model name in `*_MODEL` |

To activate the LLM judge for validation (step 4) or LLM enrichment for TEI annotation (step 5), set the corresponding provider and model:

```
VALIDATION_PROVIDER=anthropic
VALIDATION_MODEL=claude-haiku-4-5
ANNOTATION_PROVIDER=anthropic
ANNOTATION_MODEL=claude-opus-4-5
```

Leaving `VALIDATION_PROVIDER` and `ANNOTATION_PROVIDER` empty keeps those steps in deterministic-only mode, which is sufficient for many projects.

---

## 4. Processing parameters

All tunable values live in `.env` and are read by `pipeline/config.py`.

| Variable | Default | When to change |
|---|---|---|
| `BATCH_DELAY` | `2.0` | Reduce for fast APIs, increase if hitting rate limits |
| `CHUNK_SIZE` | `20` | Lower for vision models with small context windows, raise for models that handle more images |
| `IMAGE_DPI` | `150` | Raise to `300` for small print or fine handwriting; lower for large corpus to save disk space |

`IMAGE_DPI` only affects the PDF-to-image extraction in step 1. For ready-made image scans it has no effect; their resolution is fixed by the delivered digitisation and must be ensured at the source. As a minimum for diplomatic transcription, aim for the equivalent of 300 DPI of the original page (for a single octavo page roughly 2500 pixels on the long edge; more for fine print or small handwriting). Double-page book scans at low resolution are generally insufficient for faithful transcription of the running text; expect such pages to be gated as `page_type: gate_low_resolution` (see `knowledge/08_DATA_CONTRACT.md`) rather than transcribed.

---

## 5. Prompt customisation

The three prompt templates in `pipeline/prompts/` (transcription, annotation, validation) and the object-specific layer under `pipeline/prompts/objects/` are starting points, not finished instruments. Every corpus requires adapting them to its source material, and that adaptation is iterative: adapt the prompt, run it on a sample, evaluate the output against the originals at the checkpoint, revise, repeat. Plan several such iterations before a production run over the full corpus is defensible. The template's own test runs deliberately did not perform this tuning; a fork must.

Layer 1 (base rules) changes are typically needed when:

- Your source language or script is not covered by the base rules (e.g. Arabic script, East Asian languages, Kurrent).
- Your edition type requires structural rules the default does not include (e.g. verse numbering, tabular ledger entries).
- A pilot run showed a systematic error that a rule change would prevent.

The project-specific content enters via layers 2 and 3 at runtime from the knowledge documents. Document any Layer 1 changes in `knowledge/decisions.md` with the rationale, so future maintainers understand why the template defaults were overridden.

Per-object prompt overrides (for individual documents with special handling) go in `pipeline/prompts/objects/{object_id}.md`.

Operational note for agentic transcription: a vision model can only read an image that exists as a local file. Materialize remote facsimiles first (`pipeline/fetch_facsimiles.py`), then read the saved file; fetching a URL inside an agent tool returns bytes and metadata, not vision input.

---

## 6. Schema adaptation

The pipeline ships with two schema files, documented in detail in `schemas/README.md`.

- `schemas/dtabf.json` — JSON abstraction of DTABf structural constraints, used as schema guidance for the LLM annotation prompt. Not a validation schema.
- `schemas/basisformat.rng` — official DTA-Basisformat RelaxNG schema (CC BY-SA 3.0 DE, Deutsches Textarchiv), used for full conformance validation of generated TEI before publication. For manuscript corpora, download the manuscript variant from https://www.deutschestextarchiv.de/basisformat_ms.rng instead.

Choosing the validation target is part of setting up a fork (ADR-005): different projects need different schemata, and the template prescribes none. DTABf is the shipped example profile for historical German-language texts; TEI All is the permissive starting point that the deterministic output passes out of the box; a project ODD/RNG is the strict end. The options and their trade-offs, including the header caveat for strict DTABf, are laid out in `schemas/README.md`.

To set or change the target:

1. Put your profile's RelaxNG schema into `schemas/` and point `VALIDATION_SCHEMA` in `pipeline/config.py` at it. Check conformance with `python pipeline/validate_schema.py`.
2. Adjust or replace `schemas/dtabf.json` so the annotation guidance matches the new element set.
3. Update `knowledge/04_TEI_MAPPING.md` to match the new profile.
4. Record the decision in `knowledge/decisions.md`.

---

## 7. Frontend configuration

The frontend in `docs/` is a static Vanilla JS curation frontend with no build step. Its facsimile-text comparison view is where you verify transcription and annotation quality against the original images; the published edition uses the same interface.

The HTML title in `docs/index.html` is set manually. Open the file and edit the `<title>` element and the `<h1>` heading to your project name. The build script `pipeline/06_build_frontend.py` leaves `docs/index.html` unchanged. It generates the data layer in `docs/data/` and copies publication TEI into `docs/tei/`, which makes the viewer's download button work under the same static serving root. The title remains manual because `index.html` is hand-maintained and repeated string replacement would risk overwriting edits to the surrounding markup. The same applies to footer text that differs from the knowledge document.

To add research-specific UI components (e.g. a timeline, a concordance, a named-entity register), fill in `knowledge/05_DESIGN.md` before running step 6. Claude Code derives the component list from that document and implements only what is specified there.

GitHub Pages: enable in your repository settings with source set to deploy from branch `main`, folder `/docs`. The workflow at `.github/workflows/pages.yml` triggers on every push to `main`.

---

## 8. Verification checklist before first run

- [ ] `.env` exists with at least one API key for the transcription provider
- [ ] `knowledge/01_PROJECT.md` — project name and institution filled in
- [ ] `knowledge/02_DATA.md` — source type selected and data placed in `data/sources/`
- [ ] `knowledge/03_CONTEXT.md` — transcription conventions confirmed or customised
- [ ] `knowledge/04_TEI_MAPPING.md` — annotation types and mapping rules filled in
- [ ] `knowledge/05_DESIGN.md` — research question has been used to derive at least two epics (or left for Claude Code to derive at step 5b)
- [ ] Pilot test planned: first run `pipeline/02_analyze.py` and verify the inventory before triggering any LLM steps

When all boxes are checked, open Claude Code in this directory. It reads `CLAUDE.md` first and will guide you through the pipeline step by step.
