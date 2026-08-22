# Agentic Edition Pipeline

Forkable template for AI-assisted digital scholarly editions. From digitised source to TEI-XML and a published curation frontend on GitHub Pages, where the edition is inspected, verified, and presented.

Created by [Christopher Pollin](https://github.com/chpollin) ([Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft)). Built with [Claude Code](https://claude.ai/code) using the [Promptotyping](https://doi.org/10.58079/15t4s) methodology.

## What this is

A project folder with pre-built Python scripts, prompt templates, a knowledge base, and a `CLAUDE.md` that tells Claude Code what to do. Not a GUI tool, not a framework, not a SaaS product.

The template generalises four production-grade edition projects into a reusable pipeline that goes from PDF/image scans to valid TEI-XML (DTA-Basisformat) and a published static curation frontend, where the facsimile-text comparison supports verification of the machine-generated edition.

## Forking for your own edition project

This repository is designed to be forked once per edition project. You fill in the knowledge documents for your corpus and editorial guidelines, place your source material in `data/sources/`, and Claude Code operates the pipeline from there. The Python scripts and frontend are shared infrastructure you do not normally need to touch.

The reference projects listed further below are the production repositories this template distils from. They predate the generalised template and were built directly, not forked from it. Use them as orientation for what an instantiated edition project looks like.

### Prerequisites

- Python 3.10+
- [Claude Code](https://claude.ai/code) (Anthropic's agentic coding tool)
- An API key for at least one LLM provider (Gemini, OpenAI, Anthropic, or a local Ollama instance). Steps 4 (validation) and 5 (TEI annotation) run without API keys in deterministic mode.

### Step-by-step

1. **Fork** this repository on GitHub using **Use this template**, or fork it directly.
2. **Clone** your fork locally.
3. **Install dependencies.**
   ```
   pip install -r requirements.txt
   ```
4. **Set up API keys** by copying `.env.example` to `.env` and filling in at least one provider key.
   ```
   cp .env.example .env
   ```
5. **Work through `SETUP.md`.** It identifies every configuration point: project identity, corpus description, transcription conventions, TEI mapping, provider selection, and processing parameters. Each point maps to a specific file and section.
6. **Start Claude Code** in the project directory. It reads `CLAUDE.md` and walks you through the pipeline step by step, asking one question at a time before running anything.

Each pipeline step has a human verification checkpoint. Nothing proceeds without your explicit approval.

### Adapting parts of the pipeline

You do not have to use the full pipeline. Common partial reuse patterns from the reference projects:

- **Existing transcriptions, no OCR needed.** Place plain text files in `data/sources/text/`. Skip steps 1 and 3. The pipeline starts at step 2 (inventory), proceeds to step 4 (validation of existing transcriptions), and continues to TEI annotation. Structured transcription JSON goes directly into `data/processed/transcriptions/` in the pipeline data contract format (`knowledge/08_DATA_CONTRACT.md`); step 2 counts JSON pages from the `pages` array.
- **Remote facsimiles.** When images are referenced as URLs instead of local files, declare them in `metadata.image_urls` of the transcription JSON. Step 5 writes them as `<facsimile>` with `graphic url`, the frontend renders the URLs directly, and `pipeline/fetch_facsimiles.py` materializes local copies when vision-based transcription or verification needs the files on disk.
- **Existing TEI, frontend only.** Place TEI files in `data/sources/text/` and copy them to `results/tei/`. Skip steps 1–5. Run only step 6 (frontend build).
- **Different TEI schema.** Replace the schema files in `schemas/` (see `schemas/README.md`) and update `knowledge/04_TEI_MAPPING.md`. Document the decision in `knowledge/decisions.md`.
- **Different LLM provider.** Change `TRANSCRIPTION_PROVIDER` and `TRANSCRIPTION_MODEL` in `.env`. The provider abstraction in `pipeline/llm.py` supports Gemini, OpenAI, Anthropic, and Ollama without code changes.

### Local preview

At any checkpoint, preview the edition in your browser:
```
cd pipeline
python 06_build_frontend.py --serve
```
This starts a local server at `http://localhost:8080` serving the same files that will be published on GitHub Pages.

### Publishing

Enable GitHub Pages in your repository settings (source: deploy from branch, branch: main, folder: /docs). The workflow at `.github/workflows/pages.yml` handles deployment automatically on every push to main.

## Pipeline overview

```
01 Prepare Sources   Organise source material; PDF → page images (PyMuPDF)
02 Analyze           Corpus inventory and classification
   ── verify inventory ──
03 Transcribe        OCR/HTR via LLM (sample first, then full corpus)
   ── verify transcription quality ──
04 Validate          Deterministic rules + optional LLM judge
   ── review quality summary ──
05 Annotate TEI      Deterministic TEI generation + optional LLM annotation
   ── preview edition, verify TEI ──
5b Design            Requirements engineering (epics, user stories, UI components)
   ── verify design ──
06 Build Frontend    Generate catalog and data for the static curation frontend
   ── verify published edition ──
```

### Step 1 — Prepare sources

**Purpose.** Organise the source material so that downstream steps find one directory of page images per document. Sources arrive in different forms: PDFs are rendered to page images here; image files (JPEG, PNG, TIFF) need no conversion and are placed directly under `data/sources/images/{doc_id}/`, one folder per document. Basic object metadata (title, date, rights information) is recorded alongside; see the metadata note below.

**Input.** `data/sources/pdf/*.pdf` (only PDFs are processed by the script)

**Output.** `data/processed/images/{doc_id}/` — one PNG per page plus `manifest.json` listing page order and provenance.

**Key parameters.** `IMAGE_DPI` (default 150). Use 300 for small print or fine handwriting.

**Skip when.** Source material is already images or plain text. Image directories under `data/sources/images/` are picked up directly by steps 2 and 3 without any conversion.

**Metadata.** Corpus-level metadata (editor, institution, licence) lives in `knowledge/01_PROJECT.md` and flows into the TEI header from there. Per-object metadata (title, language, date, object type, remote image URLs) lives in the `metadata` object of the transcription JSON (`knowledge/08_DATA_CONTRACT.md`) and is passed through unchanged to the TEI header and the frontend catalog. Record where it comes from in `knowledge/02_DATA.md`.

**Known limits.** The script renders PDF pages fresh at the configured DPI; for image-only scanned PDFs this re-rasterises the embedded scan, which cannot exceed the source resolution.

---

### Step 2 — Analyze

**Purpose.** Build a structured inventory of all documents across `data/sources/` and `data/processed/images/`. The inventory is the single source of truth downstream steps use to know what to process.

**Input.** `data/sources/` (all subdirectories), `data/processed/images/`

**Output.** `data/inventory.json`. With `--update-knowledge`, also updates the `<!-- INVENTAR_START -->…<!-- INVENTAR_END -->` block in `knowledge/02_DATA.md`.

**Key parameters.** `--update-knowledge` (inject summary into knowledge document), `--format markdown` (human-readable output on stdout).

**Known limits.** Language detection is not automated; the `languages` field in the inventory summary is left empty for the human to fill in.

---

### Step 3 — Transcribe

**Purpose.** Send page images to a vision model and obtain diplomatic transcriptions. Handles chunking for documents that exceed the model's image-per-call limit.

**Input.** `data/inventory.json`, images via the shared image-root resolver (`data/sources/images/{doc_id}/` first, then `data/processed/images/{doc_id}/`)

**Output.** `data/processed/transcriptions/{doc_id}.json` in the pipeline data contract format (`knowledge/08_DATA_CONTRACT.md`): `pages` at the top level with per-page `transcription`, object metadata under `metadata`, confidence level, and quality signals.

**API key.** This step requires a key for the configured provider and aborts with a clear message when none is set. Transcriptions produced elsewhere enter the pipeline as contract-conformant JSON instead.

**Key parameters.** `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL`, `CHUNK_SIZE` (default 20 images per API call), `BATCH_DELAY` (default 2 s between documents), `--sample N` (pilot run on first N documents).

**Prompt.** `pipeline/prompts/transcription.md` — four-layer architecture. Layer 1 is the base diplomatic transcription rule set. Layers 2–4 inject document-type instructions, document metadata, and optional per-object overrides at runtime. See the prompt file for the full layer description.

**Known limits.** Quality signals in the template are simplified compared to the full seven-signal implementation in szd-htr-ocr-pipeline. The template emits page-type classification and character statistics; marker density, language consistency, and duplicate detection can be adapted from the [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) reference implementation.

---

### Step 4 — Validate

**Purpose.** Score each transcription for quality issues. Phase 1 applies deterministic rules always; Phase 2 sends pages through an LLM judge when a provider is configured.

**Input.** `data/processed/transcriptions/{doc_id}.json`

**Output.** `data/processed/validated/{doc_id}.json` — original transcription (`pages` and `metadata` passed through unchanged) plus rule results, per-page statistics, optional LLM assessments, and an `overall_status` field (`confident` / `needs_review` / `problematic`). The `needs_review` quality signal from step 3 means "unverified transcription" and maps to `needs_review`, not `problematic`; pages gated for insufficient image quality cap the status at `needs_review`.

**Key parameters.** `VALIDATION_PROVIDER`, `VALIDATION_MODEL` (both empty → deterministic only), `--no-llm` (force deterministic mode regardless of configuration).

**Deterministic rules.** Counts uncertain-reading markers (`[?]`), illegible-passage markers (`[...]`), OCR artefact patterns (punctuation clusters), and double spaces. Severity thresholds are defined in `pipeline/04_validate.py`.

**Prompt.** `pipeline/prompts/validation.md` — evaluates from palaeographic, linguistic, structural, and plausibility perspectives. Returns confidence level (`confident` / `likely` / `uncertain`) and typed issue list.

**Known limits.** The deterministic rules are tuned for Latin-script handwriting and typography. Corpora in other scripts may require threshold adjustment or additional rules. The LLM judge does not have access to the original images; it evaluates the transcription text only.

---

### Step 5 — Annotate TEI

**Purpose.** Generate TEI-XML from validated transcriptions. Deterministic mode builds well-formed TEI using string templates. An optional LLM enrichment pass adds named-entity and semantic markup.

**Input.** `data/processed/validated/{doc_id}.json` (preferred) or `data/processed/transcriptions/{doc_id}.json`

**Output.** `data/processed/tei/{doc_id}.xml` (working copy), `results/tei/{doc_id}.xml` (publication copy), `results/reports/{doc_id}_validation.json` (well-formedness and plaintext-similarity check).

**Key parameters.** `ANNOTATION_PROVIDER`, `ANNOTATION_MODEL` (both empty → deterministic only), `--no-llm`, `--validate-only` (generate and check but do not write TEI), `--sample N`.

**Schemas.** `schemas/dtabf.json` provides machine-readable DTABf structural guidance for the annotation prompt; `schemas/basisformat.rng` is the official DTABf RelaxNG schema for full conformance validation before publication. Roles, validation commands, and how to substitute a different TEI profile are documented in [`schemas/README.md`](schemas/README.md).

**Prompt.** `pipeline/prompts/annotation.md` — three-layer architecture. Layer 1 defines base TEI rules (well-formedness, plaintext preservation, confidence and responsibility attributes). Layer 2 injects project context from `knowledge/01_PROJECT.md`. Layer 3 loads the mapping rules from `knowledge/04_TEI_MAPPING.md`.

**Plaintext preservation.** After generation, the script computes word-set similarity between the source transcription and the generated TEI body. Similarity below 0.95 triggers a warning; below 0.80 is flagged as low. This check catches annotation errors where the model altered the text content.

**Structure.** Deterministic TEI splits page text on blank lines into `<p>` elements; within a paragraph, line breaks become `<lb/>` unless the edition type in `knowledge/01_PROJECT.md` is normalised. Remote facsimile URLs from `metadata.image_urls` produce a `<facsimile>` block with `graphic url`, referenced from `<pb facs="#facs_N"/>`. Page-level fields from the data contract are honoured: foreign text becomes `<note type="foreign">`, quality-gated pages get `<note type="gate">`, and empty pages without a declared `page_type` are marked `<note type="empty">` for verification.

**Known limits.** Complex layouts (nested tables, verse, apparatus) require LLM enrichment and project-specific mapping rules. The LLM enrichment pass does not yet support cross-document entity resolution; each document is annotated independently.

---

### Step 5b — Design

**Purpose.** Requirements engineering step that derives UI requirements from the research question, edition type, and annotation types before the frontend is built.

**Input.** `knowledge/01_PROJECT.md`, `knowledge/03_CONTEXT.md`, `knowledge/04_TEI_MAPPING.md`

**Output.** `knowledge/05_DESIGN.md` — filled with epics (2–4), user stories (2–3 per epic), UI component mapping, text-based wireframes, and acceptance criteria.

**No script.** This step is a structured reasoning task performed by Claude Code based on the knowledge documents. The human reviews and corrects the output before approving step 6.

---

### Step 6 — Build frontend

**Purpose.** Extract text and metadata from TEI files and generate the JSON data layer for the static curation frontend in `docs/`. The frontend is not a mere display viewer; the facsimile-text comparison view is where the Critical Expert in the Loop inspects and verifies transcription and annotation quality against the original images, before and after publication.

**Input.** `results/tei/*.xml`, `knowledge/01_PROJECT.md`, `knowledge/05_DESIGN.md`

**Output.** `docs/data/catalog.json` (project-level index), `docs/data/{doc_id}.json` (per-document data with pages, text, image paths). Local facsimiles resolved via the shared image root are copied to `docs/images/{doc_id}/` so the static site can serve them; remote facsimile URLs from the TEI `<facsimile>` block are rendered directly. `has_images` reflects what the viewer can actually show. The frontend HTML/CSS/JS in `docs/` is static and pre-existing; this step fills `docs/data/` and `docs/images/`.

**Key parameters.** `--force` (regenerate all data files), `--serve` (start local HTTP server on port 8080).

**Known limits.** The default frontend in `docs/` provides catalog, full-text search, and the facsimile-text curation view. Research-specific components (concordance, timeline, named-entity registers) require additional JavaScript; they are implemented by Claude Code when specified in `knowledge/05_DESIGN.md` but are not part of the base template.

## Repository structure

```
agentic-edition-pipeline/
├── CLAUDE.md                    # Operational protocol for Claude Code
├── knowledge/                   # Promptotyping knowledge base (Obsidian-compatible)
│   ├── 00_INDEX.md              # Navigation, RIDE self-assessment checklist
│   ├── 01_PROJECT.md            # Project metadata, research question
│   ├── 02_DATA.md               # Corpus description, source types, inventory
│   ├── 03_CONTEXT.md            # Editorial guidelines, transcription conventions
│   ├── 04_TEI_MAPPING.md        # Source structure → TEI element mapping
│   ├── 05_DESIGN.md             # Epics, user stories, UI components, wireframes
│   ├── 08_DATA_CONTRACT.md      # Pipeline data contract (transcription JSON schema)
│   ├── decisions.md             # Architecture Decision Records
│   └── journal.md               # Development journal
├── pipeline/                    # Python scripts (6 steps + infrastructure)
│   ├── config.py                # Paths, API config, image-root resolver, shared utilities
│   ├── llm.py                   # Multi-provider LLM (Gemini, OpenAI, Anthropic, Ollama)
│   ├── 01_extract_images.py     # Source preparation: PDF → page images
│   ├── 02_analyze.py            # Corpus inventory
│   ├── 03_transcribe.py         # OCR/HTR with chunking and quality signals
│   ├── 04_validate.py           # Hybrid validation (rules + LLM judge)
│   ├── 05_annotate_tei.py       # TEI-XML generation with validation
│   ├── 06_build_frontend.py     # TEI → static site data + local server
│   ├── fetch_facsimiles.py      # Utility: materialize remote facsimile URLs locally
│   └── prompts/                 # Prompt templates (transcription, validation, annotation)
├── schemas/                     # DTABf encoding profile (JSON) + official RelaxNG, see schemas/README.md
├── tests/                       # Pytest checks for the data contract and TEI generation
├── docs/                        # Static curation frontend (GitHub Pages root)
├── data/sources/                # Input data (your source material)
├── data/processed/              # Intermediate results (generated)
└── results/tei/                 # Final TEI-XML files
```

## Methodology

**Promptotyping** (Pollin 2026a) is a context engineering method for iterative development of research tools through structured LLM interaction. Four phases: Preparation, Exploration, Distillation, Implementation. The `knowledge/` documents are the Promptotyping Documents that steer Claude Code's behaviour.

**Critical Expert in the Loop.** Every processing step produces intermediate results in established formats (JSON, TEI-XML) that can be verified through schema validation, human inspection, and LLM-as-a-Judge. Defined checkpoints require explicit approval before proceeding.

**Epistemic Infrastructure.** The ensemble of mechanisms that make LLM-generated results verifiable, curatable, and documentable. Provenance metadata in every generated file. Architecture Decision Records. Session journal. Quality signals at every pipeline stage.

## Reference projects

This template distils knowledge and code from four production-grade repositories. Each has a `knowledge/` folder with synthesized project knowledge.

| Repository | Corpus | Strength |
|---|---|---|
| [zbz-ocr-tei](https://github.com/chpollin/zbz-ocr-tei) | 286 docs, 4152 pages (Jeanne Hersch) | End-to-end PDF→TEI, epistemic infrastructure |
| [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) | 2107 objects, 18719 scans (Stefan Zweig) | Prompt grouping, quality signals, live viewer |
| [co-ocr-htr](https://github.com/DigitalHumanitiesCraft/co-ocr-htr) | Browser-based workbench | Multi-provider LLM, hybrid validation, PAGE-XML |
| [teiCrafter](https://github.com/DigitalHumanitiesCraft/teiCrafter) | Browser-based annotation | TEI prompt architecture, schema guidance |

### Planned production forks

The first edition projects to be built as forks of this generalised template are planned but not yet run. They will serve as the first real-world validation of the template and feed the resulting learnings back into its structure.

| Planned fork | Corpus | Status |
|---|---|---|
| zbz-ocr-tei | Jeanne Hersch writings (Zentralbibliothek Zürich) | Placeholder — test run pending |
| SZD | Stefan Zweig papers (Literaturarchiv Salzburg) | Placeholder — test run pending |

Both entries are placeholders until the first fork test run is complete. The links and instantiation details will be added once the runs have taken place.

## Quality framework

Every forked edition structurally addresses the [IDE criteria for reviewing digital scholarly editions](https://www.i-d-e.de/publikationen/weitereschriften/criteria-version-1-1) (v1.1), [tools](https://www.i-d-e.de/publikationen/weitereschriften/criteria-tools-version-1) (v1), and [text collections](https://www.i-d-e.de/publikationen/weitereschriften/criteria-text-collections-version-1-0) (v1.0). See `knowledge/00_INDEX.md` for the RIDE self-assessment checklist.

### Evaluation module `aep_eval`

`aep_eval` evaluates existing outputs against references without touching them: character error rate under a declared normalisation profile and TEI conformance against an explicitly named RelaxNG schema. A fixture manifest (`schemas/evaluation-fixture.schema.json`) names hypothesis, reference, scope, reference class, maturity tier, Git anchor and file hashes; the run writes `results.json` (`schemas/evaluation-result.schema.json`) and `report.md`.

```
python -m aep_eval tests/fixtures/evaluation/manifest.json --out results/evaluation
python -m aep_eval MANIFEST --out DIR --strict      # exit 1 when any TEI file is invalid
```

Profiles in v0.1: `hsa-strict` (whitespace collapsed, case and punctuation kept, edition reference without editorial notes, transcription conventions resolved; aggregate char-weighted) and `zbz-fidelity` (zbz-ocr-tei extraction and symmetric normalisation, fidelity share of the edit distance; aggregate fixture mean). There is no universal profile; every result names the profile it was computed under. Exit codes: 0 clean, 1 fixture errors, 2 unusable manifest. Design decision: `knowledge/decisions.md`, ADR-006.

## Citation

```bibtex
@software{pollin_agentic_edition_2026,
  author = {Pollin, Christopher},
  title = {Agentic Edition Pipeline},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline},
  note = {Forkable template for AI-assisted digital scholarly editions}
}
```

## Licence

Code is licensed under the MIT License (see [LICENSE](LICENSE)). Documentation and knowledge documents are licensed under Creative Commons Attribution 4.0 International (CC BY 4.0). Third-party research data is excluded from these terms; rights remain with their respective holders.

## Author

**Christopher Pollin** — [Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft)

Research context: Pollin, Christopher / Kreyenbühl, Elias: "Agentenbasierte Editionsworkflows und epistemische Infrastrukturen. Ein Experiment zur digitalen Edition der Schriften von Jeanne Hersch." 2026.
