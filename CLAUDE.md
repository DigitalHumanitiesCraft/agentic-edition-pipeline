# CLAUDE.md

This repository is a forkable template for AI-assisted digital scholarly editions. Claude Code operates the pipeline, the human is the Critical Expert in the Loop.

Read `knowledge/00_INDEX.md` first. It maps which knowledge documents are relevant for each pipeline step.

## Rules (violations are bugs)

- ALWAYS verify that the relevant `knowledge/` documents are filled in before running or modifying a script. Ask if they are empty.
- ALWAYS adapt existing pipeline scripts in `pipeline/`. Write new code only when no existing script covers the source type. Document every adaptation in `knowledge/06_DECISIONS.md`.
- ALWAYS log date, objective, and result of every session in `knowledge/07_JOURNAL.md`.
- ALWAYS write provenance metadata into every generated file. JSON files get a `_meta` object. TEI-XML files get a `<revisionDesc>` entry. Include model name, prompt template, and timestamp.
- NEVER skip a checkpoint. Each pipeline step has a verification checkpoint that requires explicit approval before proceeding.
- NEVER abort on single-object failures. Write the error to `errors.json` in the output directory and continue with the next object.
- Use the four reference repositories when implementation details are needed. Each has a `knowledge/` folder with synthesized project knowledge that provides context for the code.

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

### Step 1 Image extraction

Only when PDFs exist in `data/sources/pdf/`.

- **Script** `pipeline/01_extract_images.py`
- **Reads** `data/sources/pdf/`
- **Writes** `data/processed/images/`
- **Context** `knowledge/02_DATA.md`

### Step 2 Analysis and inventory

- **Script** `pipeline/02_analyze.py`
- **Reads** `data/sources/`, `data/processed/images/`
- **Writes** `data/inventory.json`, updates `knowledge/02_DATA.md`
- **Context** `knowledge/01_PROJECT.md`

**CHECKPOINT** Present the inventory. Verify document count, detected source types, completeness. Proceed only after approval.

### Step 3 Transcription

- **Script** `pipeline/03_transcribe.py`
- **Reads** images from `data/processed/images/` or `data/sources/images/`
- **Writes** `data/processed/transcriptions/{object_id}.json`
- **Context** `knowledge/02_DATA.md`, `knowledge/03_CONTEXT.md`
- **Prompt** `pipeline/prompts/transcription.md`

Start with a sample (5-10 objects), not the full corpus.

**CHECKPOINT** Present 3-5 transcriptions alongside the original images. Verify quality. If the model or prompt needs adjustment, iterate on the sample. Process the full corpus only after approval.

### Step 4 Validation

- **Script** `pipeline/04_validate.py`
- **Reads** `data/processed/transcriptions/`
- **Writes** `data/processed/validated/{object_id}.json`
- **Context** `knowledge/03_CONTEXT.md`
- **Prompt** `pipeline/prompts/validation.md`

**CHECKPOINT** Present a summary showing how many objects are "confident", "needs review", "problematic". List triggered quality signals and problematic objects. Proceed only after approval.

### Step 5 TEI annotation

- **Script** `pipeline/05_annotate_tei.py`
- **Reads** `data/processed/validated/`
- **Writes** `data/processed/tei/{object_id}.xml`, `results/tei/{object_id}.xml`
- **Context** `knowledge/03_CONTEXT.md`, `knowledge/04_TEI_MAPPING.md`
- **Prompt** `pipeline/prompts/annotation.md`
- **Schema** `schemas/dtabf.json`

Start with a sample, then full corpus.

**CHECKPOINT** Present 2-3 generated TEI files. Verify annotation correctness, mapping accuracy, schema validation. If adjustment is needed, update `knowledge/04_TEI_MAPPING.md` and the prompt, then repeat the sample.

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
- **Writes** `docs/`
- **Context** `knowledge/01_PROJECT.md`, `knowledge/05_DESIGN.md`

Build the frontend based on the components and wireframes defined in `05_DESIGN.md`. Standard components (catalog, search, document view, TEI download, plaintext export) are always included. Research-specific components (concordance, timeline, specialised registers) are only implemented when defined in the user stories.

**CHECKPOINT** Present the frontend (locally or on GitHub Pages). Verify against the acceptance criteria from `05_DESIGN.md`. Check catalog, facsimile-text view, search, and all user-story-specific features.

## Edge cases

**Text only, no images.** Steps 1 and 3 are skipped. The pipeline starts at step 2 (analysis), followed by step 4 (validation of existing transcriptions) and step 5 (TEI annotation). The frontend shows annotated text without a facsimile viewer.

**Images and existing transcriptions.** Existing transcriptions go into `data/sources/text/`. Step 3 is optional. The decision whether to use existing transcriptions or re-transcribe is made at the step 2 checkpoint.

**Existing TEI files.** Steps 1-5 are skipped. TEI files go into `data/sources/text/` and are processed directly by step 6 (frontend). Alternatively, specific transformation tasks can be defined and executed as modifications to the existing TEI files.

## Script modification protocol

When a pipeline script needs modification because it does not cover a source type:

1. Read the full script
2. Identify the section that needs change
3. Read the corresponding implementation in the reference repository (see capability map below)
4. Implement the change
5. Test on a single object
6. Document in `knowledge/06_DECISIONS.md` (context, decision, rationale)
7. Document test result in `knowledge/07_JOURNAL.md`

## Reference repositories

Each repository has a `knowledge/` folder with synthesized and distilled project knowledge that provides implementation context.

| Repo | Strength | Knowledge |
|---|---|---|
| [zbz-ocr-tei](https://github.com/chpollin/zbz-ocr-tei) | End-to-end PDF to TEI, epistemic infrastructure | 21 knowledge documents |
| [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) | Scaling, prompt grouping, quality signals, viewer | Verification concept, evaluation results |
| [co-ocr-htr](https://github.com/DigitalHumanitiesCraft/co-ocr-htr) | Provider abstraction, validation logic, PAGE-XML | Architecture, overview, reference docs |
| [teiCrafter](https://github.com/DigitalHumanitiesCraft/teiCrafter) | TEI prompt architecture, schema guidance, post-generation validation | 4 knowledge documents |
