# CLAUDE.md

This repository is the 0.9 pre-release of a forkable template for AI-assisted digital scholarly editions. Claude Code operates the pipeline, the human is the Critical Expert in the Loop.

**Session start.** Read `knowledge/00_INDEX.md` first. It maps which knowledge documents are relevant for each pipeline step. If `knowledge/01_PROJECT.md` still contains `[TODO]` placeholders, read `SETUP.md` and walk the human through the configuration points before touching any pipeline script.

## Rules (violations are bugs)

- ALWAYS verify that the relevant `knowledge/` documents are filled in before running or modifying a script. Ask if they are empty.
- ALWAYS adapt existing pipeline scripts in `pipeline/`. Write new code only when no existing script covers the source type. Document every adaptation in `knowledge/decisions.md`.
- ALWAYS log date, objective, and result of every session in `knowledge/journal.md`.
- ALWAYS keep transcription JSON on the pipeline data contract (`knowledge/08_DATA_CONTRACT.md`): `pages` at the top level, page text under `transcription`, object metadata under `metadata`, passed through unchanged from step 3 to step 6.
- Steps that call an LLM provider check the API key first and abort with a clear message when it is missing. NEVER work around this with an import mode or a silent fallback; externally produced transcriptions enter the pipeline as contract-conformant JSON in `data/processed/transcriptions/`.
- ALWAYS write provenance metadata into every generated file. JSON files get a `_meta` object. TEI-XML files get a `<revisionDesc>` entry. LLM outputs record provider, model, prompt instrument, executed-prompt hashes, and timestamp. Deterministic outputs record their input-state timestamp and stable hashes of the material configuration.
- NEVER skip a checkpoint. Each pipeline step has a verification checkpoint that requires explicit approval before proceeding.
- NEVER abort on single-object failures. Write the error to `errors.json` in the output directory and continue with the next object.
- Use the three research cases when deriving the shared architecture: Hersch (`zbz-ocr-tei`), SZD (`szd-htr-ocr-pipeline`), and DoCTA. Use `co-ocr-htr` and `teiCrafter` as supporting technical sources where their narrower capabilities apply.

## Project setup

When a new edition project starts, ask these questions one at a time. Wait for each answer before asking the next.

**1. What source material exists?**
Images only (scans) / Text only (transcriptions, plaintext, PAGE-XML) / Both / PDFs

**2. Where is the data?**
Check `data/sources/`. Confirm completeness or ask where to find the remaining data.

**3. How large is the corpus?**
Number of documents, approximate page count, languages.

**4. What edition type?**
Diplomatic (faithful reproduction) / Normalised (with defined normalisations) / Critical (with apparatus and variant listings)

**5. Are there editorial guidelines or a reference edition?**
Transcription rules, encoding handbook, TEI profile (e.g. DTA-Basisformat), institutional requirements.

**6. What is the research question or purpose?**
Why is this being edited? For whom? What should happen with the edited texts?

**7. Where should the edition be published?**
GitHub Pages (default) / Institutional repository / Other

**After all answers:**
1. Fill `knowledge/01_PROJECT.md` with the project information
2. Fill `knowledge/02_DATA.md` with data specifics
3. Fill `knowledge/03_CONTEXT.md` with editorial guidelines
4. Run `pipeline/02_analyze.py` to generate an automated inventory
5. Present the inventory and filled documents for verification

Proceed only after explicit approval.

## Pipeline

Seven steps with verification checkpoints. NEVER skip a checkpoint.

### Step 1 Source preparation

Organise source material into one image directory per document. The script only converts PDFs; image files (JPEG, PNG, TIFF) go directly into `data/sources/images/{doc_id}/` and are picked up by steps 2, 3, and 6 through the shared image-root resolver (`config.resolve_image_dir`: `data/sources/images/` first, then `data/processed/images/`). Record the metadata source in `knowledge/02_DATA.md` and the machine-readable object metadata in `data/sources/manifest.json`.

- **Script** `pipeline/01_extract_images.py` (only when PDFs exist in `data/sources/pdf/`)
- **Reads** `data/sources/pdf/`
- **Writes** `data/processed/images/`
- **Context** `knowledge/02_DATA.md`

### Step 2 Analysis and inventory

- **Script** `pipeline/02_analyze.py`
- **Reads** `data/sources/` including `manifest.json`, `data/processed/images/`
- **Writes** `data/inventory.json`, updates `knowledge/02_DATA.md`
- **Context** `knowledge/01_PROJECT.md`

**CHECKPOINT** Present the inventory. Verify document count, detected source types, completeness. Proceed only after approval.

### Step 3 Transcription

- **Script** `pipeline/03_transcribe.py` (requires an API key for the transcription provider; aborts with a clear message without one)
- **Reads** images via the shared image-root resolver: `data/sources/images/{doc_id}/` first, then `data/processed/images/{doc_id}/`
- **Writes** `data/processed/transcriptions/{object_id}.json` (data contract, `knowledge/08_DATA_CONTRACT.md`)
- **Context** `knowledge/02_DATA.md`, `knowledge/03_CONTEXT.md`
- **Prompt** `pipeline/prompts/transcription.md`

Step 3 assembles the base prompt, the manifest-selected profile under `pipeline/prompts/profiles/`, the document metadata, and an optional object override under `pipeline/prompts/objects/`. A declared profile must exist. The output records all layers and their combined hash. It also preserves the original model text as `transcription_raw` and starts the human review state at `machine_unreviewed`.

Start with a sample (5-10 objects), not the full corpus.

**CHECKPOINT** Present 3-5 transcriptions alongside the original images. Verify quality. If the model or prompt needs adjustment, iterate on the sample. Process the full corpus only after approval.

### Step 4 Validation

- **Script** `pipeline/04_validate.py`
- **Reads** `data/processed/transcriptions/`
- **Writes** `data/processed/validated/{object_id}.json`
- **Context** `knowledge/03_CONTEXT.md`
- **Prompt** `pipeline/prompts/validation.md`

**CHECKPOINT** Present a summary showing how many objects are "confident", "needs review", "problematic". These values are automatic triage signals. Report the separate human review states and never advance them from an automatic result. List triggered quality signals and problematic objects. Proceed only after approval.

### Step 5 TEI annotation

- **Script** `pipeline/05_annotate_tei.py`
- **Reads** `data/processed/validated/`
- **Writes** `data/processed/tei/{object_id}.xml`, `results/tei/{object_id}.xml`
- **Runtime context** `knowledge/01_PROJECT.md`
- **Extension contract** `knowledge/03_CONTEXT.md`, `knowledge/04_TEI_MAPPING.md`
- **Schemas** the project-selected `VALIDATION_SCHEMA` in `pipeline/config.py`; roles and commands in `schemas/README.md`

Start with a sample, then full corpus.

Step 5 is deterministic for the same validated input and the same parsed project configuration. The base renderer covers project metadata, pages, paragraphs, line breaks, transcription markers, facsimile references, declared page-state notes, and the document review status. Ordered page-text preservation is a blocking gate. Semantic entities and corpus-specific structures require an explicit deterministic extension or a separate documented stage. Implement that extension against `knowledge/04_TEI_MAPPING.md` and record the decision.

**CHECKPOINT** Present 2-3 generated TEI files. Verify text preservation, mapping accuracy, provenance, and RelaxNG validation against the configured schema. If adjustment is needed, update `knowledge/04_TEI_MAPPING.md`, adapt the deterministic renderer, and repeat the sample.

### Step 5b Requirements engineering and design

This step has no script. It is a requirements engineering process that derives UI requirements from the research question, edition type, and annotation types.

- **Reads** `knowledge/01_PROJECT.md`, `knowledge/03_CONTEXT.md`, `knowledge/04_TEI_MAPPING.md`
- **Writes** `knowledge/05_DESIGN.md`

Process:
1. Read the research question from `01_PROJECT.md`. What should the edition enable?
2. Read the edition type. Which standard components are typical? (See component matrix in `05_DESIGN.md`.)
3. Read annotation types from `03_CONTEXT.md` and `04_TEI_MAPPING.md`. Which indices and registers follow?
4. Derive 2-4 epics describing the high-level usage goals.
5. Derive 2-3 user stories per epic (format: "As a [role] I want to [action] so that [benefit]").
6. Map each user story to concrete UI components.
7. Create text-based wireframes of the main views.
8. Define acceptance criteria per user story.

**CHECKPOINT** Present epics, user stories, and wireframes from `knowledge/05_DESIGN.md`. Verify that the derived requirements match the research goals. Proceed only after approval.

### Step 6 Frontend

- **Script** `pipeline/06_build_frontend.py`
- **Reads** `results/tei/`, `knowledge/05_DESIGN.md`
- **Writes** `docs/data/`, `docs/tei/`, `docs/images/`
- **Context** `knowledge/01_PROJECT.md`, `knowledge/05_DESIGN.md`

Build the frontend based on the components and wireframes defined in `05_DESIGN.md`. The base template includes a catalog filter, human-review status labels, a read-only document view, TEI download, plaintext export, and an optional page facsimile. Research-specific components, correction controls, and corpus-wide search require explicit implementation and verification.

**CHECKPOINT** Present the frontend locally. Verify the catalog, document view, available facsimiles, exports, review labels, and every component explicitly required in `05_DESIGN.md`.

## Edge cases

**Text only, no images.** Contract-conformant transcription JSON enters under `data/processed/transcriptions/`; steps 1 and 3 are skipped and processing continues at step 4. Plaintext, PAGE XML, and other formats first need a project-specific conversion into the JSON data contract.

**Images and existing transcriptions.** Source files may lie under `data/sources/text/` for inventory. Step 3 is skipped only when a contract-conformant JSON copy exists under `data/processed/transcriptions/`; every other format needs an explicit conversion.

**Existing TEI files.** Steps 1-5 are skipped. TEI files go into `data/sources/text/` and are processed directly by step 6 (frontend). Alternatively, specific transformation tasks can be defined and executed as modifications to the existing TEI files.

**Existing structured transcriptions (JSON).** Files following the data contract (`knowledge/08_DATA_CONTRACT.md`) are placed in `data/processed/transcriptions/{object_id}.json`; the pipeline continues at step 4. For the inventory they may additionally lie in `data/sources/text/`, where step 2 counts their pages from the `pages` array.

**Remote facsimiles.** Declare page records in `data/sources/manifest.json`, run step 2, then run `uv run python pipeline/fetch_facsimiles.py --all --from-manifest`. The utility writes URL- and hash-bound local copies to `data/processed/images/{object_id}/`. Step 5 retains the source URLs in TEI. For canonical step-3 TEI, step 6 publishes the verified local snapshot under `docs/images/{object_id}/`; external TEI without a source hash may render URLs directly. Check licence and access conditions before materializing.

## Script modification protocol

When a pipeline script needs modification because it does not cover a source type:

1. Read the full script
2. Identify the section that needs change
3. Read the corresponding implementation in the reference repository (see capability map below)
4. Implement the change
5. Test on a single object
6. Document in `knowledge/decisions.md` (context, decision, rationale)
7. Document test result in `knowledge/journal.md`

## Reference repositories

The three edition cases carry the empirical comparison. Two supporting repositories provide narrower implementation patterns.

| Repo | Strength | Knowledge |
|---|---|---|
| `zbz-ocr-tei` (private research repository) | Hersch end-to-end source processing, review streams, project schema | Foundational research case |
| [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) | Scaling, prompt grouping, quality signals, viewer | Verification concept, evaluation results |
| [DoCTA](https://github.com/DigitalHumanitiesCraft/DoCTA) | IIIF and Transkribus input, review return path, entities, arithmetic checks, strict project schema | Architectural transfer case |
| [co-ocr-htr](https://github.com/DigitalHumanitiesCraft/co-ocr-htr) | Provider abstraction, validation logic, PAGE-XML | Architecture, overview, reference docs |
| [teiCrafter](https://github.com/DigitalHumanitiesCraft/teiCrafter) | TEI prompt architecture, schema guidance, post-generation validation | 4 knowledge documents |
