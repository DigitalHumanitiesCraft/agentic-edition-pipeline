# Agentic Edition Pipeline

Forkable template for AI-assisted digital scholarly editions. It connects digitised sources, structured transcription, deterministic TEI generation, formal validation, and a static reading and verification frontend.

**Current state: version 0.9.0, pre-release.** The deterministic path is covered by automated tests and the synthetic offline quickstart. Provider-specific transcription, project-specific scholarly mappings, formal schema selection, and user acceptance remain responsibilities of each edition fork.

Created by [Christopher Pollin](https://github.com/chpollin) ([Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft)). Built with [Claude Code](https://claude.ai/code) using the [Promptotyping](https://doi.org/10.58079/15t4s) methodology.

## What this is

A versioned project template with Python scripts, prompt templates, a knowledge base, and a `CLAUDE.md` that routes agentic work. Projects use it as a repository rather than an installed application or hosted service.

The template generalises the edition workflows developed for the Jeanne Hersch and Stefan Zweig corpora and continued in DoCTA. Together, these three projects form the real research cases of the Agentic Edition Pipeline. The reusable pipeline goes from PDF or image scans to TEI-XML and a static frontend. Schema validation, scholarly review, rights clearance, and acceptance are recorded as separate evidence. [`knowledge/lineage.md`](knowledge/lineage.md) distinguishes these research cases from supporting technical sources and verification artefacts.

## Forking for your own edition project

This repository is designed to be forked once per edition project. You fill in the knowledge documents for your corpus and editorial guidelines, place your source material in `data/sources/`, and Claude Code operates the pipeline from there. The Python scripts and frontend are shared infrastructure you do not normally need to touch.

The research cases listed further below have different historical relationships to the reusable repository. The Hersch and SZD pipelines predate the generalised template and supplied its empirical and technical basis. DoCTA applies the resulting architecture to another corpus in an independently developed repository.

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for the locked Python environment
- [Claude Code](https://claude.ai/code) (Anthropic's agentic coding tool)
- An API key for at least one LLM provider when step 3 should transcribe images. Step 4 has a deterministic mode. Step 5 always runs deterministically.

### Offline quickstart

The repository includes a synthetic two-document corpus that exercises the deterministic path without an API key or network access. It creates an isolated local project under `.aep-quickstart/`, runs steps 4 and 5, validates the generated TEI against the shipped TEI All schema, and builds the static frontend.

```console
uv run python examples/offline-quickstart/run.py
```

The command leaves the template knowledge skeleton and working data unchanged. Recursive replacement through `--force` requires the runner's intact, path-bound ownership marker for every non-empty target, including the canonical `.aep-quickstart/` directory. See [`examples/offline-quickstart/README.md`](examples/offline-quickstart/README.md) for the generated files, preview command, target-safety rules, and verification scope.

### Step-by-step

1. **Fork** this repository on GitHub using **Use this template**, or fork it directly.
2. **Clone** your fork locally.
3. **Install dependencies.**
   ```
   uv sync --extra dev
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

- **Existing structured transcriptions.** Place contract-conformant JSON directly in `data/processed/transcriptions/` and continue at step 4. Plain text, PAGE XML, and other source formats can be inventoried under `data/sources/text/`; a project-specific conversion must first create the JSON defined in `knowledge/08_DATA_CONTRACT.md`.
- **Remote facsimiles.** Declare remote pages in `data/sources/manifest.json`, run step 2, then materialize them with `uv run python pipeline/fetch_facsimiles.py --all --from-manifest` before transcription. The fetch manifest binds each URL to the downloaded bytes. Canonical step-3 output carries a source-image hash, so step 6 publishes a verified local snapshot under `docs/images/`. External TEI without this hash may continue to render its remote URLs directly.
- **Existing TEI, frontend only.** Place TEI files in `data/sources/text/` and copy checked candidates to `results/tei/`. Step 6 can build a local frontend without steps 1–5. The supplied Pages workflow additionally requires the selected RelaxNG schema and `revisionDesc/@status="accepted"`; an external TEI project must map its review state to that gate or adapt and document the publication policy.
- **Different TEI schema.** Replace the schema files in `schemas/` (see `schemas/README.md`) and update `knowledge/04_TEI_MAPPING.md`. Document the decision in `knowledge/decisions.md`.
- **Different LLM provider.** Change `TRANSCRIPTION_PROVIDER` and `TRANSCRIPTION_MODEL` in `.env`. The provider abstraction in `pipeline/llm.py` supports Gemini, OpenAI, Anthropic, and Ollama without code changes.

### Local preview

At any checkpoint, preview the edition in your browser:
```
cd pipeline
uv run python 06_build_frontend.py --serve
```
This starts a local server at `http://localhost:8080` serving the same files that will be published on GitHub Pages.

### Publishing

Enable GitHub Pages with **GitHub Actions** as its source. The workflow at `.github/workflows/pages.yml` installs the locked environment, checks schema conformance and page acceptance, rebuilds the publication data from committed `results/tei/`, and deploys `docs/` on every push to `main`. For TEI that records a source-image hash, commit the verified `docs/images/{doc_id}/` snapshot produced by step 6; bulk source and processed images remain ignored.

## Pipeline overview

```
01 Prepare Sources   Organise source material; PDF → page images (PyMuPDF)
02 Analyze           Corpus inventory and classification
   ── verify inventory ──
03 Transcribe        OCR/HTR via LLM (sample first, then full corpus)
   ── verify transcription quality ──
04 Validate          Deterministic rules + optional LLM judge
   ── review quality summary ──
05 Annotate TEI      Deterministic TEI generation against a project mapping
   ── preview edition, verify TEI ──
5b Design            Requirements engineering (epics, user stories, UI components)
   ── verify design ──
06 Build Frontend    Generate catalog and data for the static verification frontend
   ── verify published edition ──
```

### Step 1 — Prepare sources

**Purpose.** Organise the source material so that downstream steps find one directory of page images per document. Sources arrive in different forms: PDFs are rendered to page images here; image files (JPEG, PNG, TIFF) need no conversion and are placed directly under `data/sources/images/{doc_id}/`, one folder per document. Basic object metadata (title, date, rights information) is recorded alongside; see the metadata note below.

**Input.** `data/sources/pdf/*.pdf` (only PDFs are processed by the script)

**Output.** `data/processed/images/{doc_id}/` — one PNG per page plus `manifest.json` listing page order and provenance.

**Key parameters.** `IMAGE_DPI` (default 150). Use 300 for small print or fine handwriting.

**Skip when.** Source material is already a directory of page images, or when the project enters later with contract-conformant transcription JSON. Image directories under `data/sources/images/` are picked up directly by steps 2 and 3 without conversion.

**Metadata.** Corpus-level metadata (editor, institution, licence) lives in `knowledge/01_PROJECT.md`. Per-object metadata, page URLs, and the selected prompt profile enter through `data/sources/manifest.json`. Step 2 merges the manifest with files discovered locally. The normalised metadata then travels through the transcription contract to the TEI header and frontend catalog.

**Known limits.** The script renders PDF pages fresh at the configured DPI; for image-only scanned PDFs this re-rasterises the embedded scan, which cannot exceed the source resolution.

---

### Step 2 — Analyze

**Purpose.** Build a structured inventory of all documents across `data/sources/` and `data/processed/images/`. The inventory is the single source of truth downstream steps use to know what to process.

**Input.** `data/sources/` including the optional `manifest.json`, plus `data/processed/images/`

**Output.** `data/inventory.json`. With `--update-knowledge`, also updates the `<!-- INVENTAR_START -->…<!-- INVENTAR_END -->` block in `knowledge/02_DATA.md`.

**Key parameters.** `--update-knowledge` (inject summary into knowledge document), `--format markdown` (human-readable output on stdout).

**Source manifest.** The committed manifest uses version `0.1`. Each document may declare `id`, `prompt_profile`, `metadata`, and a consecutively numbered `pages` list. Within one document, every page has an `image_url` or every page refers to local material. This provides an entry point for IIIF and other remote corpora before any transcription exists. Local-only projects can leave the document list empty.

**Known limits.** Language detection is not automated; the `languages` field in the inventory summary is left empty for the human to fill in.

---

### Step 3 — Transcribe

**Purpose.** Send page images to a vision model and obtain diplomatic transcriptions. Handles chunking for documents that exceed the model's image-per-call limit.

**Input.** `data/inventory.json`, images via the shared image-root resolver (`data/sources/images/{doc_id}/` first, then `data/processed/images/{doc_id}/`)

**Output.** `data/processed/transcriptions/{doc_id}.json` in the pipeline data contract format (`knowledge/08_DATA_CONTRACT.md`). Each page carries the editable `transcription`, the immutable initial `transcription_raw`, and a human-controlled `review` state. The document also carries object metadata, confidence notes, quality signals, the executed prompt log, and a hash-bound list of the exact image bytes supplied to the model.

**API key.** This step requires a key for the configured provider and aborts with a clear message when none is set. Transcriptions produced elsewhere enter the pipeline as contract-conformant JSON instead.

**Key parameters.** `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL`, `CHUNK_SIZE` (default 20 images per API call), `BATCH_DELAY` (default 2 s between documents), `--sample N` (pilot run on first N documents).

**Prompt.** `pipeline/prompts/transcription.md` provides the base rules. A document selects `pipeline/prompts/profiles/{prompt_profile}.md` through the source manifest. Step 3 appends its metadata and an optional `pipeline/prompts/objects/{doc_id}.md` override. The exact layer list and combined prompt hash are stored in `_meta`. A declared profile that has no file fails that document instead of silently using generic rules.

**Completeness gate.** The source manifest, local images, inventory, each model chunk, and the assembled response must agree on consecutive page numbers from 1. Step 3 preserves returned page numbers and rejects omissions, duplicates, and additions before writing a transcription file.

**State-aware reuse.** A run without `--force` skips an existing transcription only when its contract, provider, model, assembled prompt, and source-image bytes still match. A stale file stops the object with an instruction to rerun explicitly with `--force`.

**Known limits.** Quality signals in the template are simplified compared to the full seven-signal implementation in szd-htr-ocr-pipeline. The template emits page-type classification and character statistics; marker density, language consistency, and duplicate detection can be adapted from the [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) reference implementation.

---

### Step 4 — Validate

**Purpose.** Score each transcription for quality issues. Phase 1 applies deterministic rules always; Phase 2 sends pages through an LLM judge when a provider is configured.

**Input.** `data/processed/transcriptions/{doc_id}.json`

**Output.** `data/processed/validated/{doc_id}.json` contains the original pages, metadata, transcription provenance, rule results, per-page statistics, optional LLM assessments, and an automatic `overall_status` field (`confident` / `needs_review` / `problematic`). An input-state hash binds these findings to the exact transcription, review history, metadata, confidence fields, and facsimile provenance that step 4 assessed. The automatic status is a triage signal and leaves the human-controlled page review state unchanged. Insufficient image quality, undeclared empty pages, and document confidence `low` cap it at `needs_review`.

**Key parameters.** `VALIDATION_PROVIDER`, `VALIDATION_MODEL` (both empty → deterministic only), `--no-llm` (force deterministic mode regardless of configuration).

**Deterministic rules.** Counts uncertain-reading markers (`[?]`), illegible-passage markers (`[...]`), OCR artefact patterns (punctuation clusters), and double spaces. Severity thresholds are defined in `pipeline/04_validate.py`.

**Prompt.** `pipeline/prompts/validation.md` performs a text-only plausibility assessment. It checks orthographic anomalies, linguistic coherence, transcription markers, and internal structure. It makes no visual or palaeographic claim.

**Human review.** Record page transitions in the canonical transcription file with `uv run python pipeline/update_review.py --object ID --page N --status STATUS --actor REVIEWER`. The permitted sequence is controlled and auditable: a page enters `in_review`, may be returned to `machine_unreviewed`, advances to `human_verified`, and then to `accepted`; accepted pages can be reopened as `in_review`. Re-run steps 4–6 with `--force` after a transition. Automatic validation never changes this state.

**State-aware reuse.** A non-forced run accepts an existing validation only when its input hash and deterministic or model-assisted configuration still match. Changes require an explicit `--force` rerun and cannot silently inherit earlier findings.

**Known limits.** The deterministic rules are tuned for Latin-script handwriting and typography. Corpora in other scripts may require threshold adjustment or additional rules. The LLM judge does not have access to the original images; it evaluates the transcription text only.

---

### Step 5 — Annotate TEI

**Purpose.** Generate predictable and diffable TEI-XML from validated transcriptions. The base renderer is deterministic and makes no provider call.

**Input.** `data/processed/validated/{doc_id}.json`. Step 5 does not bypass the step-4 checkpoint.

**Output.** `data/processed/tei/{doc_id}.xml` and `results/tei/{doc_id}.xml` are synchronized TEI candidates. `results/reports/{doc_id}_validation.json` records well-formedness, required elements, ordered text preservation, and the project-configuration hash. A candidate becomes a published scholarly edition only after the selected RelaxNG check, scholarly review, and user acceptance.

**Key parameters.** `--validate-only` generates and checks without writing TEI. `--sample N` processes a bounded sample.

**Schemas.** `schemas/tei_all.rng` is the runnable default validation target. `schemas/basisformat.rng` provides the stricter DTABf alternative. Roles, validation commands, and schema substitution are documented in [`schemas/README.md`](schemas/README.md).

**Project mapping.** The script reads project metadata from `knowledge/01_PROJECT.md`. `knowledge/04_TEI_MAPPING.md` specifies additional corpus structures and semantic annotations for a project-specific deterministic extension or a separate documented stage. The base renderer does not inject that document into a model prompt.

**Text preservation.** After generation, the script reconstructs transcription markers from the TEI and compares every page as an ordered character sequence after layout-whitespace normalization. Missing pages, reordered text, and lost repetitions block the TEI write. `~~text~~`, `{text}`, `word[?]`, `[...]`, and `[... ~N chars]` map deterministically to `del`, `add`, `unclear`, and `gap`.

**Structure.** Deterministic TEI splits page text on blank lines into `<p>` elements; within a paragraph, line breaks become `<lb/>` unless the edition type in `knowledge/01_PROJECT.md` is normalised. Object dates and repositories become `origDate` and `repository` in the source description. Remote facsimile URLs from `metadata.image_urls` produce a `<facsimile>` block with `graphic url`, referenced from `<pb facs="#facs_N"/>`. Page-level fields from the data contract are honoured: foreign text becomes `<note type="foreign">`, quality-gated pages get `<note type="gate">`, and empty pages without a declared `page_type` are marked `<note type="empty">` for verification.

**Review and reproducibility.** `revisionDesc/@status` records the least mature page review state. Its change entry identifies the timestamp of the validated input state and hashes the transcription instrument, executed prompts, validation state, and project configuration. The same validated JSON and project configuration therefore produce identical TEI bytes.

**Known limits.** The base renderer covers metadata, pages, paragraphs, line breaks, facsimile references, and declared page-state notes. Nested tables, verse, apparatus, semantic entities, and cross-document entity resolution require project-specific implementation and verification.

---

### Step 5b — Design

**Purpose.** Requirements engineering step that derives UI requirements from the research question, edition type, and annotation types before the frontend is built.

**Input.** `knowledge/01_PROJECT.md`, `knowledge/03_CONTEXT.md`, `knowledge/04_TEI_MAPPING.md`

**Output.** `knowledge/05_DESIGN.md` — filled with epics (2–4), user stories (2–3 per epic), UI component mapping, text-based wireframes, and acceptance criteria.

**No script.** This step is a structured reasoning task performed by Claude Code based on the knowledge documents. The human reviews and corrects the output before approving step 6.

---

### Step 6 — Build frontend

**Purpose.** Extract text, metadata, and the human review status from TEI files and generate the JSON data layer for the static frontend in `docs/`. Its facsimile-text view supports inspection. Corrections and status transitions remain explicit operations on the edition data.

**Input.** `results/tei/*.xml`, `knowledge/01_PROJECT.md`, `knowledge/05_DESIGN.md`

**Output.** `docs/data/catalog.json` (project-level index), `docs/data/{doc_id}.json` (per-document data with pages, text, image paths), and `docs/tei/{doc_id}.xml` (downloadable TEI). Local facsimiles are copied atomically to `docs/images/{doc_id}/`. A TEI source-image hash requires those exact bytes; a fresh Pages checkout may verify the committed publication snapshot when ignored source folders are absent. Remote URLs remain direct only for external TEI without a source-image hash. The build removes stale TEI, object data, withdrawn object folders, and obsolete page files. `has_images` reflects what the viewer can actually show.

**Key parameters.** `--force` (regenerate all data files), `--serve` (start local HTTP server on port 8080).

**Known limits.** The default frontend provides a catalog filter, human-review status labels, a read-only facsimile-text view, TEI download, and plaintext export. It has no corpus-wide full-text index, correction editor, annotation editor, or acceptance control. Research-specific components require implementation and verification in the edition fork.

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
│   ├── lineage.md               # Provenance and role of the reference projects
│   ├── case-comparison.md       # Comparison of Hersch/ZBZ, SZD, and DoCTA
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
│   └── prompts/                 # Transcription and validation prompt templates
├── schemas/                     # TEI All and DTABf RelaxNG schemas, see schemas/README.md
├── tests/                       # Pytest checks for the data contract and TEI generation
├── examples/offline-quickstart/ # Synthetic corpus and isolated offline runner
├── docs/                        # Static verification frontend (GitHub Pages root)
├── data/sources/                # Input data (your source material)
│   └── manifest.json            # Optional catalogue, remote pages, prompt profiles
├── data/processed/              # Intermediate results (generated)
└── results/tei/                 # TEI candidates awaiting project gates
```

## Methodology

**Promptotyping** (Pollin 2026a) is a context engineering method for iterative development of research tools through structured LLM interaction. Four phases: Preparation, Exploration, Distillation, Implementation. The `knowledge/` documents are the Promptotyping Documents that steer Claude Code's behaviour.

**Critical Expert in the Loop.** Every processing step produces intermediate results in established formats (JSON, TEI-XML) that can be verified through schema validation, human inspection, and LLM-as-a-Judge. Defined checkpoints require explicit approval before proceeding.

**Epistemic Infrastructure.** The ensemble of mechanisms that make LLM-generated results verifiable, curatable, and documentable. Provenance metadata in every generated file. Architecture Decision Records. Session journal. Quality signals at every pipeline stage.

## Research cases

Three real edition projects carry the research contribution of the Agentic Edition Pipeline.

| Project | Corpus | Contribution | Relationship to this repository |
|---|---|---|---|
| `zbz-ocr-tei` (private research repository) | 285 catalogued documents and 4,117 pages from the Jeanne Hersch edition | End-to-end source processing, stream-level human review, project schema, and verifiable curation | Foundational case that predates the reusable template |
| [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) | 2,452 catalogued objects and 17,132 pages from the Stefan Zweig collection | Corpus-scale HTR, material-specific prompt profiles, calibrated quality signals, and a curation viewer | Foundational case that predates the reusable template |
| [DoCTA](https://github.com/DigitalHumanitiesCraft/DoCTA) | Edition subset of 65 registered documents and 692 pages within an indexed corpus of 115 documents and 12,236 pages from Tyrolean court records | Transkribus and IIIF integration, review return path, entity extraction, arithmetic checks, deterministic TEI, and a project schema | Architectural transfer into an independently developed repository |

`co-ocr-htr` and `teiCrafter` supplied additional implementation patterns for provider abstraction, validation, PAGE XML, TEI editing, and schema handling. They support the reusable core but are not counted among the three primary research cases.

[`knowledge/case-comparison.md`](knowledge/case-comparison.md) compares the three repositories across source entry, prompt routing, working formats, review states, evaluation, TEI generation, and publication. It also records which shared requirements are implemented in this template and which functions remain project-specific.

### Verification artefacts

The offline quickstart and the local Schuchardt letters instance test the reusable software. They provide technical evidence and are not additional research cases.

| Artefact | Evidenced state |
|---|---|
| `examples/offline-quickstart/` | Current deterministic command-line path verified on two synthetic objects |
| local `hsa-letters-pipeline` | Eighteen real letters processed from prepared transcription through TEI, frontend, and evaluation; provider path untested |

## Quality framework

`knowledge/00_INDEX.md` provides a preparation checklist derived from the [IDE criteria for reviewing digital scholarly editions](https://www.i-d-e.de/publikationen/weitereschriften/criteria-version-1-1) (v1.1). It separates structural support supplied by the template from project evidence, formal checks, scholarly review, rights clearance, usability assessment, and user acceptance.

### Evaluation module `aep_eval`

`aep_eval` evaluates existing outputs against references without touching them: character error rate under a declared normalisation profile and TEI conformance against an explicitly named RelaxNG schema. A fixture manifest (`schemas/evaluation-fixture.schema.json`) names hypothesis, reference, scope, reference class, maturity tier, Git anchor and file hashes; the run writes `results.json` (`schemas/evaluation-result.schema.json`) and `report.md`.

```
uv run python -m aep_eval tests/fixtures/evaluation/manifest.json --out results/evaluation
uv run python -m aep_eval MANIFEST --out DIR --strict      # exit 1 when any TEI file is invalid
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
