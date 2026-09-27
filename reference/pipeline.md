# Processing reference

Run every command from the repository root in the locked environment. The rules that files must satisfy live in the [data contract](data-contract.md), the [base TEI mapping](tei-mapping.md), the [local correction contract](local-review.md) and the [provider records](provider-records.md). Project decisions belong in [SETUP.md](../SETUP.md) and agent rules in [AGENTS.md](../AGENTS.md).

The supplied path runs image preparation, inventory, transcription, quality assessment, base TEI generation and the frontend build in this order. Existing transcription JSON enters at quality assessment and checked external TEI at the frontend build.

## Object selection and error records

Steps 1, 3, 4 and 5 and `fetch_facsimiles.py` take `--object ID` or `--all`. With `--all`, `--sample N` (N ≥ 1) keeps the first N candidates in the step's processing order. An unknown ID, an empty selection or `--sample` without `--all` exits 1 before any work.

These steps and step 6 write `errors.json` on every run, and an empty list clears an earlier failure. A run with a failed item prints each failure on stderr and exits 1.

| Command | `errors.json` in |
|---|---|
| `01_extract_images.py` | `data/processed/images/` |
| `fetch_facsimiles.py` | `data/processed/images/` |
| `03_transcribe.py` | `data/processed/transcriptions/` |
| `04_validate.py` | `data/processed/validated/` |
| `05_annotate_tei.py` | `results/reports/` |
| `06_build_frontend.py` | `results/frontend/` |

Step 2 writes no error file and exits 1 when a source declaration is invalid.

## Image preparation

```console
uv run python pipeline/01_extract_images.py --all
uv run python pipeline/01_extract_images.py --object ID --dpi 300 --force
```

Step 1 rasterizes `data/sources/pdf/{id}.pdf` with PyMuPDF into `data/processed/images/{id}/`, one PNG per page plus a `manifest.json` that records the PDF hash, the resolution and the hash of every page image. `--dpi` overrides `IMAGE_DPI`. A document whose manifest still matches is skipped unless `--force` is given. Scans under `data/sources/images/{id}/` need no extraction, and the shared image resolver prefers them over extracted images.

## Inventory

```console
uv run python pipeline/02_analyze.py
uv run python pipeline/02_analyze.py --update-knowledge --format markdown
```

Step 2 scans `data/sources/`, merges the optional `data/sources/manifest.json` and adds materialized images from `data/processed/images/`. It writes `data/inventory.json`, whose records carry a `transcribable` flag that is true only for documents with page images. `--update-knowledge` replaces the block between the `INVENTAR_START` and `INVENTAR_END` markers in `knowledge/02_DATA.md` with an English table whose Step 3 column shows which documents step 3 reads. `--format markdown` prints that table instead of the JSON. The step always scans the whole corpus and detects no languages.

## Remote facsimiles

```console
uv run python pipeline/fetch_facsimiles.py --all --from-manifest
uv run python pipeline/fetch_facsimiles.py --all --from-transcriptions
uv run python pipeline/fetch_facsimiles.py --object ID --force
```

The utility downloads remote page images into `data/processed/images/{id}/` with a `manifest.json` that binds every URL to its file name and SHA-256. The source of the URLs depends on the mode:

- `--from-manifest` reads `metadata.image_urls` from `data/inventory.json`, after step 2 and before step 3.
- `--from-transcriptions` reads `metadata.image_urls` from `data/processed/transcriptions/*.json`.
- Without either flag it reads `<graphic url>` from `results/tei/*.xml`, for imported or generated TEI before step 6.

A page whose file, URL and hash still match is skipped unless `--force` is given. The `FETCH_*` variables in [SETUP.md](../SETUP.md#processing-parameters) set pacing, retries and the response size cap. A response above `FETCH_MAX_BYTES` and bytes that do not decode as JPEG, PNG or TIFF fail the page. Check the licence of the image provider before materializing.

## Image transcription

```console
uv run python pipeline/03_transcribe.py --all --sample 2 --dry-run
uv run python pipeline/03_transcribe.py --object ID
uv run python pipeline/03_transcribe.py --all --chunk-size 10 --delay 5
```

Step 3 reads `data/inventory.json` and the page images of transcribable documents. Under `--all` it names and skips documents flagged `transcribable: false`, and `--sample` counts only transcribable documents. `--object` with such a document exits 1. The step writes `data/processed/transcriptions/{id}.json`, one call record per provider call under `data/processed/llm-calls/{id}/` and verified chunks under `data/processed/chunk-cache/{id}/`.

It requires `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_MODEL` and the adapter's credential, and a missing setting stops the run before any call. `--dry-run` calls no provider and needs no key. It lists each document as `CURRENT` (existing output kept), `PENDING` (would call the provider) or with the upper-cased name of the stage that would fail, and exits 1 if any document would fail.

`--chunk-size` (default `CHUNK_SIZE`) bounds the images per call. `--delay` (default `BATCH_DELAY`) pauses after a document that called the provider. `--force` requests fresh calls for existing output. An existing output that no longer matches its recorded inputs fails with stage `stale` until `--force` is given, and output with review history is never replaced.

The prompt layers are listed in [SETUP.md](../SETUP.md#transcription-prompt). A declared profile without its file fails the document, and the profile key `README` is refused. An unparseable answer gets one retry with a JSON hint. A truncated answer fails the document with stage `truncated` and no second call, because a repeat would hit the same output limit.

## Text quality assessment

```console
uv run python pipeline/04_validate.py --all --no-llm
uv run python pipeline/04_validate.py --all --sample 2
uv run python pipeline/04_validate.py --object ID --force
```

Step 4 reads `data/processed/transcriptions/{id}.json` and writes `data/processed/validated/{id}.json`. The deterministic rules always run. The judge runs when `VALIDATION_PROVIDER` is set and `--no-llm` is absent. It reads the page text without the images, uses `pipeline/prompts/validation.md`, and every judge call leaves a record under `data/processed/llm-calls/{id}/`.

An existing output is kept while its input state, judge configuration and judge vocabulary still match, as the [data contract](data-contract.md#validated-file) specifies. A stale or unreadable output fails the object until `--force` reassesses it. A `problematic` status is a finding and does not fail the run.

## Base TEI generation

```console
uv run python pipeline/05_annotate_tei.py --all
uv run python pipeline/05_annotate_tei.py --object ID --validate-only
uv run python pipeline/validate_schema.py
```

Step 5 calls no model. It reads current step-4 output, the project fields of `knowledge/01_PROJECT.md` and the bound source images, and writes `results/tei/{id}.xml` and `results/reports/{id}_validation.json`. `--validate-only` writes the report without TEI.

An existing TEI file that step 5 did not write itself, because it was edited or enriched elsewhere, is refused unless `--force` is given. The [base TEI mapping](tei-mapping.md#output-checks-and-overwrite-guard) specifies this guard and the header and body mapping. After a text correction only step 4 needs `--force`.

`validate_schema.py` checks `results/tei/*.xml`, or the files given as arguments, against `VALIDATION_SCHEMA` or `--schema PATH`. It exits 0 when every file is valid, 1 when a file is invalid or none is found, and 2 when the schema is missing or unusable. The [schema documentation](../schemas/README.md) explains the choice of schema.

## Review states and corrections

```console
uv run python pipeline/update_review.py --object ID --page N --status STATUS --actor REVIEWER --note "reason"
```

`update_review.py` records one page transition in the canonical transcription JSON, with `--note` as an optional comment. It refuses to write while an interrupted review transaction awaits recovery. The permitted transitions, the writer lock and the limits for agent actors are defined in the [data contract](data-contract.md#human-review-state). Afterwards, rerun step 4 with `--force`, then steps 5 and 6.

```console
uv run python pipeline/review_server.py --port 8080
uv run python pipeline/review_server.py --recover
```

The review server needs a built frontend and binds only 127.0.0.1, with the editor at http://127.0.0.1:8080/. A save stages steps 4 to 6 and the schema check before it replaces any file. A stale version returns HTTP 409, a save that changes nothing returns HTTP 400, and TEI that differs from the base generator's output is refused. The server offers no endpoint for human decisions. `--recover` restores the snapshot of an interrupted transaction and exits.

## Frontend build

```console
uv run python pipeline/06_build_frontend.py
uv run python pipeline/06_build_frontend.py --serve
```

Step 6 reads `results/tei/*.xml`, their step-5 reports and the project title. It writes `docs/data/catalog.json`, `docs/data/{id}.json`, `docs/tei/{id}.xml` and verified image snapshots under `docs/images/{id}/`, and removes obsolete files from that set. Every run rebuilds all objects. A TEI file whose step-5 report names another derivation is left over from a failed regeneration and is refused. External TEI without a report is published.

`--serve` previews `docs/` at http://127.0.0.1:8080/ after a successful build. The preview and the review server both default to port 8080, so run one at a time or give the review server another `--port`.

## Publication gate

```console
uv run python pipeline/check_publication.py
```

The gate exits 0 only when no review transaction awaits recovery, every file in `results/tei/` is valid against `VALIDATION_SCHEMA`, optional annotations are bound to the current transcription and every `revisionDesc/@status` is `accepted`. The Pages workflow runs this gate, the linter and the tests, then step 6, and deploys `docs/` on a push to `main`. A project with external TEI maps its review policy to this gate or documents an adaptation.

## Evaluation

`aep_eval` computes character error rates and schema conformance for declared fixtures without modifying them. The [evaluation reference](evaluation.md) documents its commands.
