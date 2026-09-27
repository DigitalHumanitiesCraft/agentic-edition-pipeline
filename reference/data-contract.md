# Data contract

One data contract binds step 3 (transcription), step 4 (quality assessment), step 5 (TEI generation) and step 6 (frontend). Every transcription file under `data/processed/transcriptions/{object_id}.json` follows it, whether step 3, a person or an agent produced it. Step 4 passes `metadata` and `pages` unchanged into `data/processed/validated/{object_id}.json` and adds its findings. Step 5 reads the validated file, and step 6 reads the generated TEI. `pipeline/contract.py` holds the field rules in one place. Each of its checks returns a list of violations and reports a malformed shape as a violation, so the calling step decides whether the object fails or the run stops.

## Transcription file

```json
{
  "_meta": {
    "script": "03_transcribe.py",
    "timestamp": "2026-09-27T10:00:00+00:00",
    "pipeline_step": 3,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "prompt_template": "transcription.md",
    "prompt_profile": "correspondence",
    "prompt_layers": [
      "transcription.md",
      "profiles/correspondence.md",
      "inventory:metadata",
      "objects/doc1.md"
    ],
    "prompt_hash": "abc123def456",
    "source_metadata_hash": "123def456abc",
    "raw_transcription_hash": "456abc123def",
    "executed_prompts": [
      {
        "chunk": 1,
        "pages": [1],
        "attempt": 1,
        "prompt_hash": "def456abc123",
        "record": "llm-calls/doc1/0f1e2d3c4b5a69788796a5b4c3d2e1f0.json"
      }
    ],
    "source_images": [
      {
        "page": 1,
        "filename": "doc1_p001.png",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      }
    ],
    "source_images_hash": "789abc123def"
  },
  "object_id": "doc1",
  "source_images": ["doc1_p001.png"],
  "metadata": {
    "title": "Letter to N. N., 22 May 1901",
    "language": "de",
    "date": "1901-05-22",
    "object_type": "correspondence",
    "image_urls": {
      "1": "https://example.org/o:doc1/IMG.1"
    }
  },
  "pages": [
    {
      "page": 1,
      "transcription": "First line\nSecond line\n\nSecond paragraph",
      "transcription_raw": "First line\nSecond line\n\nSecond paragraph",
      "review": {
        "status": "machine_unreviewed",
        "history": []
      },
      "notes": "",
      "page_type": "",
      "foreign_paragraphs": []
    }
  ],
  "confidence": "high",
  "confidence_notes": "",
  "quality_signals": {
    "page_types": ["content"],
    "total_chars": 40,
    "chars_per_page": 40.0,
    "blank_pages": 0,
    "undeclared_empty_pages": 0,
    "gate_pages": 0,
    "foreign_pages": 0,
    "content_pages": 1,
    "needs_review": false
  }
}
```

## Field rules

### Required fields

`_meta`, `object_id` and `pages` stand at the top level. Every page carries `page` (an integer, consecutive from 1), `transcription` (the page text with line breaks as `\n` and paragraph boundaries as a blank line) and `review` with `status` and `history`.

### Object identifiers

`object_id` is a portable file and object name. It starts with a letter or digit and continues with letters, digits, `.`, `_` or `-`. Reserved Windows device names are rejected, and so are identifiers that differ from another object only in letter case. The names `errors` and `catalog` are reserved in any letter case, because `errors.json` and `docs/data/catalog.json` share the directories of the per-object files.

### Text fields

`transcription`, `notes` and the metadata text fields `title`, `signature`, `date`, `language`, `object_type`, `extent` and `repository` must be strings. A character outside the XML 1.0 character range is rejected before the file is stored, because it could not become TEI.

### Text states

Step 3 writes the unchanged first model answer of every page to `transcription_raw` and the same text to `transcription`. The ordered `raw_transcription_hash` in the provenance block binds these raw texts to the model run. Later corrections change only `transcription`. A new model run may replace `transcription_raw` only in a new output file. `--force` in step 3 therefore refuses to overwrite an object once any page carries review history, and a new model run of a reviewed object needs a new object identifier.

### Human review state

`review.status` follows the sequence `machine_unreviewed`, `in_review`, `human_verified`, `accepted`. A model run starts with `machine_unreviewed`. The permitted transitions are these:

- `machine_unreviewed` to `in_review`
- `in_review` to `machine_unreviewed` or `human_verified`
- `human_verified` to `in_review` or `accepted`
- `accepted` to `in_review`

Every entry in `review.history` names the source state, the target state, the human actor and an ISO timestamp with time zone, in chronological order. `human_verified` and `accepted` also bind the complete TEI-relevant page state through `page_state_hash`, which covers text, page type, foreign-paragraph assignment and notes. A later change invalidates that decision and is blocked before step 4. The canonical command is shown below.

```console
uv run python pipeline/update_review.py --object ID --page N --status STATUS --actor REVIEWER
```

The command holds the same repository writer lock as the [local review server](local-review.md) and refuses to write while an interrupted review transaction awaits recovery. A transition recorded with the actor kind `agent`, as the local review server records agent corrections, can reopen or return a page but cannot record `human_verified` or `accepted`. The command line records no actor kind. After a transition, step 4 runs again with `--force`, then steps 5 and 6 run without it.

### Object metadata

`metadata` holds the object metadata that passes unchanged from step 3 to step 6. It comes from the inventory alone, which step 2 builds from the source manifest and local files. Step 3 neither requests nor takes over metadata proposed by the model. The mapping of each field to the TEI header is fixed in the [TEI base mapping](tei-mapping.md). `image_urls` declares remote facsimiles as page number to URL, with string keys consecutive from 1, and a list in page order is accepted as well. Every URL starts with `http://` or `https://`.

### Optional page fields

`notes` holds free text of the transcriber. `page_type` and `foreign_paragraphs` classify the page.

| `page_type` | Meaning | Effect in steps 4 and 5 |
|---|---|---|
| missing or empty | ordinary content page | paragraphs as `<p>` |
| `blank` | declared empty page | only `<pb/>`, no marking note |
| `gate_low_resolution` | image quality insufficient for a diplomatic transcription | `<note type="gate" subtype="low_resolution">`, object status at most `needs_review` |
| `foreign_text` | the whole page belongs to another text or author | text as `<note type="foreign">`, outside the edited body |

On mixed pages `foreign_paragraphs` lists the 0-based indices of paragraphs that are foreign text, and step 5 sets them as `<note type="foreign">` instead of `<p>`. An empty `transcription` without a declared `page_type` produces `<note type="empty">` in step 5, so verification can tell a real blank page from a silent gap.

### Confidence

`confidence` is `high`, `medium`, `low` or empty in the stored file. Step 3 accepts the value from the model answer in any letter case and stores it in lower case. Across chunks the document confidence is the weakest declared chunk value, and the notes of all chunks are kept in `confidence_notes`. A document confidence `low` caps the step-4 status at `needs_review`.

### Quality signals

Step 3 computes `quality_signals`. The block is optional in files produced by a person or an agent. When present, all counters, page types and the boolean `needs_review` must be complete and typed. `needs_review` means an unverified transcription and leads to `needs_review` in step 4.

### Provenance

`_meta` is required from every producing stage. A run of step 3 records provider, model, base template, the optional prompt profile, the prompt layers used, the hash of the fully assembled instruction, the hash of the complete authoritative metadata, the hash of the ordered raw model texts, every executed chunk and retry prompt, and the ordered SHA-256 state of the image files read. The first calls cover every page exactly once, and retry entries repeat the same chunk. Each entry of `executed_prompts` names its private call record in `record`, relative to `data/processed/`, as described in [provider records](provider-records.md). Files produced by hand carry at least `script` and a `timestamp` with time zone. They claim no run of step 3 and use, for example, `pipeline_step: 0`.

### Source images

The top-level `source_images` names the local image files in page order. After a run of step 3 it must match the file names in `_meta.source_images` exactly. Step 5 checks the current files against this byte state. Step 6 uses a verified local snapshot for bound TEI and can fall back to the committed files under `docs/images/{object_id}/` in a Pages checkout. Differing, missing or additional facsimiles block the build.

## Validated file

Step 4 sets its own provenance block in `_meta` and keeps the transcription provenance under `transcription_meta`. The file carries these additional fields:

- `_meta.input_state_hash` binds the complete assessed transcription state, including metadata, pages, raw text, review history, confidence and image binding.
- `_meta.validation_result_hash` binds rule findings, page statistics, the optional judge verdicts and `overall_status`.
- `validation.rules`, `validation.per_page_stats` and `validation.total_characters` hold the deterministic findings.
- `validation.llm_judge` holds one verdict per page when a judge ran, and `validation.llm_judge_unreviewed_pages` counts the pages the judge could not be asked about.
- `overall_status` is `confident`, `needs_review` or `problematic`.
- With a judge, `_meta` also names provider, model, `prompt_template`, `prompt_hash`, `judge_vocabulary_hash` and `executed_prompts`, one entry per text page with `page`, `prompt_hash` and `record`.

`quality_signals`, `confidence`, `confidence_notes` and `source_images` pass through unchanged. `overall_status` never changes the human review state. Rule warnings, the quality signal `needs_review`, image-quality gates, undeclared empty pages, a document confidence `low`, a judge verdict `likely` and a page the judge could not reach cap it at `needs_review`. A judge verdict `uncertain` makes it `problematic`, and so do an answer that arrived but violated the judge contract and more than two rule errors. `compute_overall_status` in `pipeline/04_validate.py` holds the thresholds.

The judge vocabulary follows `pipeline/prompts/validation.md`. Its confidence values are `confident`, `likely` and `uncertain`, and its issue types and perspectives are the enumerations in the prompt's fenced block. `judge_vocabulary_hash` identifies the vocabulary a run accepted. An existing validated file stays current only while its input state hash, provider, model, prompt hash and vocabulary hash match the current run. Otherwise the object fails as stale until step 4 runs with `--force`, so old findings never pass for a changed text or a changed judge.

Step 5 accepts only a formally complete validated file whose hashes and statistics still match metadata, pages, raw text, review history, confidence and image binding. [TEI base mapping](tei-mapping.md) describes the step-5 output and its overwrite guard. Step 6 refuses a TEI file whose step-5 report names another `validation_state_hash` than the derivation recorded in the TEI header, because such a file is left over from a failed regeneration. External TEI without a step-5 report is published.

## Source manifest before transcription

`data/sources/manifest.json` uses version `0.1` and describes documents whose metadata or facsimiles do not follow from local file names. A document entry can carry `id`, `prompt_profile`, `metadata` and `pages`. Manifest pages stand in image order and are numbered from 1 without gaps. Within a document either every page declares `image_url` or none does. Step 2 normalises the addresses to `metadata.image_urls` in the inventory.

Step 2 also marks every inventory document with `transcribable`. Only page images (PDF, image folders, remote or materialised facsimiles) reach step 3. Text, XML, DOCX and transcription-JSON sources are inventoried with `transcribable: false`, and step 3 leaves them out of its selection and names them.

`pipeline/fetch_facsimiles.py --from-manifest` materialises remote pages with bounded retries, a configurable delay and a response size limit. Its manifest binds every URL to file name and SHA-256, and step 3 discards local bytes whose URL or hash no longer matches the inventory.

## Completeness of model answers

Step 3 requires exactly one page entry per supplied image. With chunked processing every chunk returns its assigned global page numbers unchanged. Missing, duplicated, renumbered or additional model pages violate the contract and produce no transcription file. Image folders without a manifest are sorted naturally by the digits in the file name, and the letter case of image suffixes is irrelevant.

## Transcriptions produced outside step 3

A structured transcription produced outside step 3 is written in conformance with this contract directly to `data/processed/transcriptions/{object_id}.json`, and the pipeline then starts at step 4. Plain text, PAGE XML and other exchange formats need a project-specific conversion into this contract first. Step 2 inventories such files but does not convert them. Step 3 remains the image-based provider path. The cloud adapters need their configured API key, and Ollama needs a reachable local service and a compatible model.

For the inventory, structured transcription JSON can also lie under `data/sources/text/`. `02_analyze.py` counts its pages from the `pages` array (`source_type: transcription`).

## Stored corrections

The optional page block `edits` documents every saved text or notes correction with UUID, actor, role, time, reason and the complete before and after values. The sequence must lead without gaps to the current page state. Model answers may not supply these events, review decisions or raw-text fields themselves. The local service sets corrected pages to `in_review`, and the role `agent` establishes no human review. The [local review contract](local-review.md) describes the details.

The static frontend takes over no complete provider answers and no raw transcriptions.

## Other methods and import provenance

External OCR and HTR systems (optical character recognition, handwritten text recognition) and other machine-learning methods enter this contract through an explicit converter. The converter preserves page order, raw text and actual provenance and checks its output before step 4. It must not claim a run of the supplied transcription script or of a model that was not used.

Layout regions, entities and relations need additional contracts. The mere presence of a text field does not carry them. The template contains no universal importer for all exchange formats.

`notes` is editable in the local correction path. An old model note has no automatically updated validity status. Changes become traceable in `edits`, while a semantic check of unchanged notes remains open. [Editorial guidelines](../knowledge/03_CONTEXT.md) and the [local review contract](local-review.md) govern how an edition handles them.

## Related

- [Knowledge index](../knowledge/00_INDEX.md)
- [Data and corpus](../knowledge/02_DATA.md) of the edition
- [TEI base mapping](tei-mapping.md)
- `pipeline/prompts/transcription.md`, whose base layer enforces this contract in the model answer
