# Processing reference

This reference describes the supplied scripts. Run commands from the repository root with the locked environment. [SETUP.md](../SETUP.md) defines project decisions and [AGENTS.md](../AGENTS.md) defines authorization and review requirements.

The base path is image preparation → inventory → transcription → quality assessment → deterministic TEI → frontend. Existing contract-conformant transcriptions enter at quality assessment. Checked external TEI can enter at the frontend. These routes have different verification scopes.

## Image preparation and inventory

```console
uv run python pipeline/01_extract_images.py --all
uv run python pipeline/02_analyze.py
```

Extraction rasterizes PDFs from `data/sources/pdf/` with PyMuPDF and writes page images under `data/processed/images/{id}/`. `IMAGE_DPI` controls rasterization. It cannot reconstruct missing source detail. Ready scans under `data/sources/images/{id}/` take precedence through the shared image resolver and skip extraction.

Inventory combines local files and optional `data/sources/manifest.json` records. It writes `data/inventory.json`; `--update-knowledge` explicitly updates the inventory block in `knowledge/02_DATA.md`. `--format markdown` selects readable output. The inventory command scans the declared corpus; it has no `--object` selector. Language detection is not automatic.

For manifest-declared remote pages:

```console
uv run python pipeline/fetch_facsimiles.py --all --from-manifest
```

The fetch record binds each URL to saved image bytes. Declared and materialized page counts must match. Inspect the inventory and page order before transcription.

## Image transcription

```console
uv run python pipeline/03_transcribe.py --all --sample 2
```

Step 3 reads inventory and local images and writes `data/processed/transcriptions/{id}.json`. The [data contract](../knowledge/08_DATA_CONTRACT.md) specifies pages, metadata, raw text, editable text, notes and review state.

Configure `TRANSCRIPTION_PROVIDER` and `TRANSCRIPTION_MODEL`. The cloud adapters require their credentials; Ollama needs its local service and a compatible vision model. `CHUNK_SIZE` bounds images per call and `BATCH_DELAY` spaces document processing.

The prompt combines base rules, selected material profile, selected object metadata and optional object instructions. A missing declared profile fails the document. The output records executed layers, prompt hash and exact image hashes. Each response chunk and the assembled document must preserve consecutive page numbers without missing or additional pages.

A non-forced run reuses output only when its contract and recorded input identity still match. Changed prompts, provider, model or image bytes require an explicit rerun. `--force` requests fresh calls; review-history guards still protect corrected transcriptions. Successful chunks can be reused after interruptions under the full cache identity described in [provider records](../knowledge/provider-records.md).

`--sample N` selects the first N documents. Select and record a suitable varied pilot separately. Model confidence, page classification and character statistics are aids to review and do not establish accuracy.

## Text quality assessment

```console
uv run python pipeline/04_validate.py --all --no-llm
```

Step 4 reads transcription JSON and writes `data/processed/validated/{id}.json`. Rules flag uncertain or illegible markers, suspicious character patterns and whitespace issues. Thresholds in the script may need adjustment for a different script or material.

The optional judge uses `VALIDATION_PROVIDER`, `VALIDATION_MODEL` and `pipeline/prompts/validation.md`. It sees transcription text without the source images. Its output is a plausibility assessment.

The automatic `overall_status` is `confident`, `needs_review` or `problematic`. It leaves human-controlled page review states unchanged. Image-quality gates, undeclared empty pages and low document confidence cap the automatic result at `needs_review`.

Findings are bound to the assessed input state and configuration. Changed inputs require an explicit `--force` assessment and cannot inherit old findings silently.

## Base TEI generation

```console
uv run python pipeline/05_annotate_tei.py --all
uv run python pipeline/validate_schema.py
```

Despite its historical filename, step 5 generates base TEI deterministically. It makes no provider call and requires current step-4 output.

It writes synchronized candidates to `data/processed/tei/{id}.xml` and `results/tei/{id}.xml`, plus `results/reports/{id}_validation.json`. `--validate-only` checks generated candidates without writing TEI. `--sample N` bounds the selected documents.

The renderer reads project fields from `knowledge/01_PROJECT.md`. The mapping document specifies requirements for extensions and is not injected into a model call. The base covers metadata, pages, paragraphs, diplomatic line breaks, facsimile references and declared page-state notes.

Transcription markers map to `del`, `add`, `unclear` and `gap`. Reconstructing them from the generated TEI must reproduce every page's ordered text after layout-whitespace normalization. Missing pages, reordered text and lost repetitions block output.

Dates and repository metadata enter the source description. Facsimile references bind pages to images. `revisionDesc/@status` records the least mature page review state; provenance and correction events identify the derivation. Identical validated input and project configuration produce identical TEI bytes.

The configured RelaxNG target is a separate check. [Schema documentation](../schemas/README.md) explains TEI All, DTABf and project profiles. Tables, verse, critical apparatus, entity annotations and cross-document identity resolution require implemented extensions.

## Review states and corrections

A responsible reviewer can record a state transition:

```console
uv run python pipeline/update_review.py --object ID --page N --status STATUS --actor REVIEWER
```

Pages enter `in_review`, can return to `machine_unreviewed`, advance to `human_verified` and then `accepted`, or reopen as `in_review`. Follow the permitted transition order and rerun dependent stages with `--force` after a change. An automated assessment cannot grant these human decisions.

For local correction after building the edition:

```console
uv run python pipeline/review_server.py --port 8080
```

Open [the local editor](http://127.0.0.1:8080/). It offers current and raw text, reasons, history and separate proposals. A save prepares the canonical JSON, deterministic checks, configured schema validation and derived viewer files before replacement. Conflicts preserve the browser draft. Recovery snapshots protect interrupted writes. Already enriched TEI is refused by the base correction path.

Read the [local correction contract](../knowledge/local-review.md) before using the API or recovery command. A correction reopens review and does not commit, push or accept the result.

## Frontend and publication

```console
uv run python pipeline/06_build_frontend.py --serve
```

The builder reads `results/tei/*.xml` and project metadata. `--force` regenerates existing data; `--serve` previews the static files on port 8080. Do not run the preview and editor on the same occupied port.

Output includes `docs/data/catalog.json`, per-document JSON, downloadable TEI under `docs/tei/` and verified local image snapshots under `docs/images/`. Obsolete object data, TEI and images are removed from this generated publication set.

TEI carrying a source-image hash requires those exact bytes. A clean publication checkout can use its committed verified snapshot when ignored source folders are absent. External TEI without image hashes can retain direct remote image URLs.

The supplied viewer has catalog filtering, page views, review labels, provenance and downloads. Corpus-wide search, annotation editors and additional research views need implementation. `knowledge/05_DESIGN.md` guides that work; it is not interpreted automatically by the builder.

The Pages workflow rebuilds the site from committed candidates and requires schema conformance and `revisionDesc/@status="accepted"`. Source rights and human publication authorization remain required. An external-TEI project must explicitly map its review policy to this gate or document an adaptation. Public assets must exclude private logs, credentials and recovery files.
