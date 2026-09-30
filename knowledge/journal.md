---
title: Journal
description: Record of every work session with date, goal, verified result and open points
tags: [journal, sessions]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: active
created: 2026-04-03
updated: 2026-09-30
---

# Journal

The agent appends one entry per work session with date, goal, verified result and open points. A fork keeps the template's entries and appends its own below a heading that names the fork, as [[00_INDEX]] describes.

## Format

```
### YYYY-MM-DD Session title

#### Goal
What should be achieved?

#### Result
What was achieved and verified?

#### Problems
What did not work?

#### Next steps
What remains open?
```

## Template sessions

### 2026-07-18 Repair run after the fork test runs

#### Goal

Fix all template bugs documented in the ZBZ and SZD test runs and unify the documentation.

#### Result

The data contract of the transcription JSON was fixed (today the [data contract](../reference/data-contract.md)) and enforced in steps 3 to 6 and in the prompt. Further changes were metadata pass-through in step 4, an API-key gate with a clear stop message in steps 3, 4 and 5, central image-root resolution in `config.py` with a facsimile copy to `docs/images/`, remote facsimiles as a declared case (`metadata.image_urls`, `<facsimile>` with `graphic url`, `fetch_facsimiles.py`), page gates (`page_type`), foreign-text separation and `<lb/>` for the diplomatic edition type in step 5, whitespace normalisation and `pb` attribute parsing in step 6, `.json` as a source type with page counting in step 2, a softened status model (`needs_review` instead of `problematic`), the renaming to `journal.md` and `decisions.md`, and test coverage under `tests/` (pytest, all green). The decisions are ADR-002 to ADR-004.

#### Problems

The old `pb` regular expression in step 6 lost the `facs` attribute when `n` preceded `facs`. Attribute-wise parsing replaced it.

#### Next steps

Set up the first production fork with corpus-specific iterated prompts (SETUP.md section 5). Implement the LLM annotation pass in step 5 once a fork needs it.

### 2026-07-18 Verification finding of Research Mission Control, strict DTABf check

#### Goal

Recheck the repair run (test rerun, Git anchors) and the open question whether the new note types (`gate`, `foreign`, `empty`) conform strictly to DTABf.

#### Result

The test rerun passed 14 of 14, and commits and renamings were confirmed. The RelaxNG check of a generated TEI against `schemas/basisformat.rng` failed, but on pre-existing header structures (`title` attributes, `projectDesc`, `revisionDesc` and `facsimile` at this position are not accepted by the strict base format). The new note types caused no error. The deterministic TEI was therefore never strictly DTABf-valid. It is well-formed TEI oriented towards the base format.

#### Problems

None new. The finding sharpens the separation between encoding profile and validation laid out in `schemas/README.md`.

#### Next steps

Decide whether the deterministic mode declares TEI All as validation target (documentation change) or pulls the header to strict base-format conformance (code change). Until then the wording "oriented towards" applies.

### 2026-07-18 Configurable validation target (ADR-005)

#### Goal

Implement the open decision on the validation target. The operator decided that the schema must be selectable per project.

#### Result

`VALIDATION_SCHEMA` in `pipeline/config.py` became the only configuration point, and `pipeline/validate_schema.py` a runnable checker with a clear message for a missing schema, a file report and an exit code. Three new tests were added (17 of 17 green). All four ZBZ test-run TEI files proved TEI All-valid, and the DTABf failure reproduced exactly at the header structures of the previous finding. `schemas/README.md` and SETUP.md section 6 were switched to the project decision, with DTABf as example profile with a header caveat. ADR-005 records the decision.

#### Problems

None.

#### Next steps

Set up the first production fork, set the validation target explicitly there and pull the header to the profile where needed.

### 2026-08-22 Evaluation module aep_eval v0.1 (Research Mission Control, task T-026)

#### Goal

First executable slice of the evaluation contract of Research Mission Control (pilot Agentic Edition Evaluation). It comprises a fixture manifest with JSON Schema, CER under the profiles `hsa-strict` and `zbz-fidelity`, parametrised RelaxNG checking, a shared result schema, JSON and Markdown reports, synthetic tests, and real regressions against Schuchardt and Hersch in read-only mode.

#### Result

The package `aep_eval/` (profiles, cer, tei_check, manifest, results, runner, CLI), `schemas/evaluation-fixture.schema.json` and `schemas/evaluation-result.schema.json`, 39 new tests in `tests/test_aep_eval_*.py` with fixtures under `tests/fixtures/evaluation/` (whole suite 56 green), a README section, ADR-006, and `jsonschema` and `rapidfuzz` in `requirements.txt`. The Schuchardt regression (18 letters, fork `a28dee27`) gave `hsa-strict` character-weighted 0.059821 against the frozen 0.0598, with every object identical in reference length and distance to `results/reports/cer.json`, and 18 of 18 valid against `tei_all.rng`. The Hersch regression (25 reference documents, zbz-ocr-tei `c0cc7417`) gave a `zbz-fidelity` fixture mean of 0.020804 against the published 0.020804, with fidelity, full and scope per document within 5e-7 of the published values and a consistent decomposition throughout. Manifests and run reports lie outside the repository in the Mission Control workspace, and the fixture repositories stayed unchanged.

#### Problems

None in the module. It stays open that the Hersch source file `cer_statistics.json` was generated on an unclean worktree (provenance noted in the manifest). The TEI extraction mirrors the source algorithms on `xml.etree`, so the figures stay auditable (see the module docstring).

#### Next steps

Independent review by Research Mission Control (task T-027), then structure and entity evaluators on the same contract (M10) and the integration as a pipeline step.

### 2026-08-24 Hardening round after the fork findings (round 1)

#### Goal

Close the sixteen template findings of the Schuchardt production run (`reports/report-2026-08-22` in the Mission Control repository), starting with the five blocking ones. Beforehand, three independent review agents analysed the whole repository (architecture and documentation-code drift, findings and fork delta, walkthrough of the fork path on a fresh clone).

#### Result

Round 1 was committed as `511228c`, the suite grew from 56 to 93 tests, and Ruff was clean under a new `pyproject.toml`. The API key moved from a query parameter into a header, with `redact_secrets` on every error string. Steps 3 to 6 exit with code 1 on processing errors, while scholarly findings stay exit 0. The inventory accepts every image format (`list_page_images`, a fork patch). `schemas/tei_all.rng` was shipped and set as the default validation target that the template's own output passes. The central marker list `pipeline/markers.py` stops convention markers from counting as OCR artefacts. The run-time contract check `pipeline/contract.py` runs before every write in step 3. `merge_chunks` keeps metadata and carries `confidence` as the most conservative vocabulary word. Judge transport errors got their own state (`llm_judge_unreviewed_pages`) instead of `problematic`. Step 5 lost its dead LLM path and its false provenance, and `aep_eval` moved to a Python 3.10 floor and a repository-internal contract reference. Four operator decisions of 24 August 2026 were recorded. The documented LLM annotation pass in step 5 is dropped and described as an extension point. Publication teaches a branch deploy from `/docs` with a versioned data layer. A synthetic example corpus with an offline quickstart enters the template. The template becomes English throughout.

#### Problems

The planned round 2 (fifteen packages) was not executed, and the working tree stayed clean at `511228c`. Still open from round 1 were these points. `ANNOTATION_PROVIDER` and `ANNOTATION_MODEL` in `config.py` and `.env.example` and `pipeline/prompts/annotation.md` had no code reader. `08_DATA_CONTRACT.md` did not yet describe the merge semantics of `confidence` and the field `llm_judge_unreviewed_pages`. `requirements.txt` duplicated the dependencies of `pyproject.toml`. README, SETUP and CLAUDE.md carried the known documentation-code drifts (Pages contradiction, dead promises of search, registers and download).

#### Next steps

Round 2 comprises fifteen packages:

- TEI header (`origDate`, `repository`) and removal of fallbacks in step 6
- real registers (`annotations` field)
- marker-to-TEI mapping (`del`, `add`, `unclear`, `gap`)
- real facsimile resolution for `pb/@facs`
- object status in the catalogue
- TEI download under `docs/tei/`
- `.gitignore` rework for the branch deploy
- a shared project-table parser including the missing table rows
- prompt layers 2 to 4
- `--from-manifest` and `apply_external_transcription`
- robustness of step 6 (serve, TEI without `pb`, `@n` assignment)
- remaining findings of step 2
- removal of dead configuration
- example corpus with quickstart
- an `aep_eval` example manifest

Then follow the English documentation round with ADR-007 and following and, as final verification, the fresh-clone walkthrough of the documented fork path.

### 2026-08-26 Synthetic example corpus and offline quickstart

#### Goal

Provide the decided offline quickstart as an isolated, directly executable example fork without provider access, external research data or change to the template skeleton.

#### Result

`examples/offline-quickstart/` contains two synthetic transcription objects, fully filled example knowledge, its own guide and a runner. The runner creates a separate project folder and runs the real CLIs for deterministic validation, TEI generation, explicit RelaxNG checking against TEI All and the frontend build. All provider and API-key variables are cleared, and the integration test additionally blocks socket access of the runner and pipeline processes. A path-bound ownership sentinel limits `--force` for every non-empty target, including the canonical default target, to contents the runner demonstrably owns. Paths through symbolic links and Windows reparse points are rejected before resolution. Targeted tests cover foreign directories, unmarked contents, valid ownership, the default target, sentinel manipulation, the order of the reparse check and empty targets. Step 5 takes date and repository into the TEI header, and only semantically valid calendar values get `origDate/@when`. Step 6 keeps `docs/tei/` as an exact mirror of successfully processed TEI files, where the corrected download link reaches the assets over HTTP. The end-to-end test compares metadata and pages with the fixtures, requires a text similarity of 1.0, checks exact frontend texts, catalogue values and the static search basis and filter logic, and fetches the download assets through a local HTTP server. README, SETUP, action layer and data contract were updated, and ADR-007 and ADR-008 document the decisions.

#### Problems

The quickstart checks technical pipeline properties on synthetic text. Facsimiles, provider runs and scholarly edition review lie outside its scope.

#### Next steps

Work on the remaining round-2 packages, especially marker mapping, registers, facsimile resolution and object status. Then run the English documentation round and the fresh-clone walkthrough of the documented fork path.

### 2026-08-27 Lineage and the deterministic TEI boundary

#### Goal

Clarify purpose and derivation line of the template against the three real edition cases and align the documentation with the executed code path of step 5.

#### Result

`knowledge/lineage.md` (today [[lineage]]) names Hersch, SZD and DoCTA as the three real edition cases. Hersch and SZD form the starting point of the generalisation, and DoCTA is the independent application of the architecture. The offline quickstart and the local HSA letters fork are separate technical test artefacts. README and knowledge index represent these levels. README, SETUP, action layer, schema documentation and TEI mapping describe step 5 as a deterministic base path. The unused variables `ANNOTATION_PROVIDER` and `ANNOTATION_MODEL` and `pipeline/prompts/annotation.md` were removed. The Promptotyping handoff exists with an empty, active inbox. The full suite passes with 119 tests, one data-dependent test is skipped, and Ruff reports no findings.

#### Problems

The HSA letters fork still carries the inherited documentation of template state `7328482` and has no upstream mechanism. DoCTA uses an independent data and knowledge contract, and its existing foreign working state stayed untouched.

#### Next steps

Define a small machine-readable template anchor and an explicit upgrade protocol for future project instances. Document a provider-supported run on a current instance as tried only when transcription, scholarly review and acceptance exist for the named corpus.

### 2026-08-27 Comparison of the three edition cases and adoption of the shared core

#### Goal

Compare Hersch/ZBZ, SZD and DoCTA as official cases at their current repository state and take the shared requirements into the template.

#### Result

`knowledge/case-comparison.md` (today part of [[lineage]]) compares source access, material control, working formats, text states, review procedures, TEI generation, entities and publication. The comparison uses SZD `cc45c9345a47`, DoCTA `d0a4a5305ce4` and ZBZ `c0cc741739c8`, with a marked addition from the local working state. (Corrected on 2026-09-27. This entry first named DoCTA `2233beffb588`, the preceding DoCTA commit of the same day, which does not yet contain the project schema `docta.rng` the comparison cites. The comparison document itself named `d0a4a5305ce4`.) `data/sources/manifest.json` is the early entry for remote pages, object metadata and prompt profiles, and step 2 merges it with local sources. Step 3 assembles the four prompt layers, records their hash, requires exactly one answer page per image and creates raw text and human review state. Step 4 preserves the transcription provenance. Step 5 transfers the least mature page state into the TEI header and produces byte-identical text from the same input. The facsimile fetcher skips existing pages before the HTTP call, uses an identifying user agent and writes downloads atomically. README, SETUP, prompt documentation, data contract, knowledge index and lineage were updated. ADR-010 documents the architecture decision. The full suite passes with 127 tests and one expected data-dependent skip. Ruff and `git diff --check` report no findings. The temporary SZD audit clone was removed after the check.

#### Problems

The three project repositories were read and stayed unchanged. The ZBZ working state contained numerous uncommitted extensions, and the corresponding statements are limited in the comparison as observed working state. No corpus was reprocessed and no scholarly transcription review took place.

#### Next steps

Layout regions and semantic release stay project-specific extensions. Their inclusion in the shared core requires a second documented use case with a matching contract.

### 2026-08-27 Version 0.9 consolidation and trust boundaries

#### Goal

Consolidate the insights from Hersch/ZBZ, SZD, DoCTA and the technical test runs in the shared template, mark the state as pre-release 0.9 and secure data, review and publication boundaries executably.

#### Result

Version, citation and CodeMeta stand at `0.9.0`. uv and `uv.lock` form the only installation source, and Ruff, format check, pytest, pre-commit and both GitHub Actions workflows use the same locked state. The source contract binds portable object IDs that are unique also without regard to letter case, page order, authoritative metadata, remote URLs and exact facsimile bytes. The ID check applies before the first write in PDF extraction, remote materialisation and all following collection boundaries. Step 3 records raw text, prompt layers, executed calls and image state. Hashes secure the raw model texts and the identity of the prompt profile used. A new model run may overwrite neither an unreadable existing state nor existing human review history. Step 4 keeps confidence values and binds input and findings with separate hashes. The human review history has controlled, chronological transitions, and `human_verified` and `accepted` bind the complete TEI-relevant page state. Step 5 accepts only the complete validated state, maps markers deterministically to TEI and checks the ordered text round trip. Step 6 verifies and publishes facsimiles atomically, uses committed snapshots in a fresh Pages checkout and removes withdrawn or stale publication files. The knowledge base names Hersch/ZBZ, SZD and DoCTA as the three official cases and limits technical test examples to their actual evidence. The unused annotation instruction, the duplicate `requirements.txt` and the unused `schemas/dtabf.json` were removed. The offline quickstart can remove its own marked working folder safely. Its executed run passed for two objects with exact text round trip, TEI All validation and frontend build, and the temporary output folder was removed afterwards. The full technical run passes with 218 tests, and one Windows test for symbolic directories is skipped as expected. Ruff, format check, lock check and `git diff --check` are clean.

#### Problems

The current state contains no provider-supported corpus run on version 0.9. Scholarly review of the three corpora, rights clearance and user acceptance lie outside this technical consolidation.

#### Next steps

Version 1.0 receives its reliable status after a current provider-specific and project-specific run, scholarly review and explicit user acceptance.

### 2026-09-08 Local correction workflow for version 0.10.0

#### Commission and scope

The commissioned template extension was implemented on `codex/edition-0.10-review` from the unchanged base commit `9220057`. The two local demo repositories and their real research data stayed unchanged. Layout analysis, new NER methods and additional evaluators were not implemented.

#### Implementation

`review_server.py` provides a local storage path protected against foreign browser origins. Browser and authorised agents use the same API with a version hash. Text and note corrections get a traceable event sequence, and the raw model text and initial provenance stay preserved. Separate proposals do not change the edition. The storage path validates and regenerates JSON, TEI and browser data before the joint takeover. Process lock, snapshots and transaction markers secure conflicts, write errors and recovery. The base editor refuses to overwrite deviating or enriched TEI. Optional annotations carry a text binding, and stale bindings block publication. Private call records and verified chunk caches extend step 3. Successful chunk calls are reused after an interrupted run as long as instruction and input data match.

#### Knowledge base

`AGENTS.md` adds the shared action layer. `project.md` and `specification.md` (today [[overview]]) separate template maintenance from the setup of an edition. `local-review.md` and `provider-records.md` (today the [local review contract](../reference/local-review.md) and the [provider records](../reference/provider-records.md)) specify storage and call contracts. Index, TEI mapping, data contract, design, README and CLAUDE were updated. Version, citation, CodeMeta and lock metadata stand at `0.10.0`. The quality action now includes Ubuntu and Windows, and no remote CI run was started.

#### Verification

The full local suite passes with 242 tests and one skip. Ruff, format check and `git diff --check` are clean. The isolated offline quickstart produced two synthetic documents with a passed text round trip, RelaxNG check and frontend build. Browser checks confirmed separate proposals, explicit adoption, actor role, the distinction between page and document state, and the preservation of a draft after HTTP 409 and aborted navigation. An HTTP download was byte-identical to the canonical TEI. The static view offers no write controls. An additional synthetic test checks the unchanged raw model texts and the facsimile binding, and differing published image bytes are rejected.

#### Limits

No paid provider calls, no scholarly review of real transcriptions and no user acceptance took place. The local service is no multi-user system, and declared actor roles are not authenticated. A takeover into the demo repositories, commit, push and publication were not performed. The local synthetic preview ran at `http://127.0.0.1:8871/#viewer/example-letter-001`.

### 2026-09-08 Project-independent documentation and write-back of the video analysis

#### Commission and starting state

The discussed README and knowledge refactoring was implemented on the existing, uncommitted state of `codex/edition-0.10-review`. The existing 0.10 implementation stays preserved. The basis was the supplied video transcript up to 1:14:59, the previously read local demo artefacts and the current template code.

#### Result

The README explains reuse, AI harness, independent processing models and the limits of additional integrations. Research corpora and method theory left the entry, and their provenance documentation stays accessible. Commands and evaluation rules are reachable under `reference/`. `AGENTS.md` replaces the duplicated operating contract, and `CLAUDE.md` contains the entry to it. SETUP and index follow tasks and dependencies. The CLI comparison corrected missing required selectors in example commands and a non-existent inventory parameter.

#### Knowledge gained

Input roles and metadata-assisted recognition stand in [[02_DATA]] and [[03_CONTEXT]]. [[04_TEI_MAPPING]] separated text anchors, identities and relations from formal validity (today in the [TEI base mapping](../reference/tei-mapping.md)). The local review contract takes old notes after text corrections into account. The provider records describe the separate provenance requirements of API calls, harness tasks and deterministic derivations. `specification.md` (today [[overview]]) and [[05_DESIGN]] mark zoom, blind review, metadata evidence and semantic extensions as open functions. The video proved no causal influence of individual metadata, no measured model error rates and no actual processing costs.

#### Technical check

The full local suite passes with 243 tests and one skip. The offline integration test checks the copied working contract and resolvable local documentation links in addition to the existing processing. The quickstart also takes over the referenced synthetic examples and the evaluator, but no credentials or research holdings. The commands were compared with the actual CLI options.

#### Limits

The work extends the documentation and the isolated example scope. New OCR models, layout reconstruction, NER and additional frontend review modes were not implemented. No paid provider calls, changes to demo corpora, independent subagent review or scholarly acceptance took place. Commit, push, GitHub About and publication stay unchanged. User acceptance of the local pre-release is outstanding.

### 2026-09-08 Research preview label

At the user's explicit request, the README title is directly followed by the note "Research Preview (v0.10.0)" with the explanation that no stable version exists yet. The previous version statement in the introduction was merged into it. Code, version number and publication state stay unchanged.

### 2026-09-08 Knowledge consolidation and authorised repository completion

#### Commission

The user explicitly commissioned the consolidation of the relevant knowledge and commit and push of the existing template state. The previous implementation and documentation state belongs to this completion. The real demo corpora stay unchanged.

#### Knowledge consolidation

In the personal vault, project overview, Promptotyping case study, provenance modelling, software architecture, AI harness and verification boundary were specified. They hold transferable insights and dated source evidence. Executable contracts, technical test figures and open functions stay here in the repository. No new knowledge files were needed for this addition. The public entry explains the research preview status and separates the harness model from the processing methods integrated through adapters.

#### Renewed verification

The full local suite passes with 243 tests and one expected Windows symbolic-link skip. Ruff checks the code without findings, and all 83 Python files match the formatting. `git diff --check` is clean. This check repeats the synthetic software evidence and is no independent subagent review, new provider evaluation or scholarly acceptance.

#### Publication evidence

Commit `730d7376aa0b589ae5d40307ec12d89b3a094458` was pushed to `main` and `codex/edition-0.10-review`. The public README matches the local file. GitHub About describes the research preview with AI harness, project knowledge and adaptable processing tools. The [quality run on main](https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline/actions/runs/34225398462) passed on Ubuntu and Windows. The vault additions are secured in the vault commit `08d5222` and link the concrete template commit as implementation evidence.

#### Publication boundary

The template contains no released research TEI, so the locally executed publication check blocks with `no TEI candidates found`. The [Pages run](https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline/actions/runs/34225398554) ends at `Configure Pages`, because no Pages site is configured for the template. No edition was published. The publication of code and documentation on GitHub is separate from this. A later edition publication needs the Pages setup and a schema-valid, humanly accepted corpus, and the existing protective checks stay unchanged.

#### Open scholarly and functional work

The extensions named in `specification.md` (today [[overview]]) and the user acceptance remain open. A real edition fork needs its own rights decisions, source review, model evaluation and scholarly release. Git state, knowledge index, requirements, this journal and the empty inbox [[handoff]] suffice as entry for later work, and no additional handoff snapshot was created.

### 2026-09-08 Time limit of the HTTP integration test

The renewed [Ubuntu run after the journal commit](https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline/actions/runs/34225795140) showed a sporadic timeout in `test_http_security_and_version_conflict`. The test client waited ten seconds for a save with complete TEI check and regeneration, and the server log showed HTTP 200 after about twelve seconds. The previous cross-platform run and the Windows job passed with the same production code.

The HTTP test helper therefore uses a bounded wait of 60 seconds and closes its connection on errors as well. All status, security and version-conflict assertions stay. The test defines no ten-second latency requirement for an edition build. Production code and editorial protective checks stay unchanged. The affected test was repeated successfully locally, and the full suite runs again with the fix in GitHub Actions.

### 2026-09-27 Code refactor and restructured knowledge base

#### Goal

Harden the data contract and the shared pipeline helpers, align documentation with the code, and separate edition configuration, fixed contracts and template knowledge in the documentation.

#### Result

The commits of the day changed the code. The facts below were checked against the code of the working tree.

- `.gitattributes` pins LF line endings, so byte comparisons of TEI and JSON hold on Windows checkouts (`e327071`).
- The viewer renders all data through the element builder in `docs/js/dom.js`, and a Content Security Policy (CSP) meta tag blocks inline script. Before, `esc()` did not escape quotes, so `pb/@n` or `graphic/@url` from imported TEI could run script (`2fbe9c1`).
- `aep_eval` copies the marker syntax of `pipeline/markers.py`, and a test holds the copies equal. It keeps struck text and the wider illegibility pattern on purpose (ADR-018). `schemas/basisformat.rng` was removed, the quickstart report derives its checks from exit statuses and runs the evaluator, and CI adds Python 3.13 (`3db88cc`).
- Contract checks report malformed shapes instead of raising, reject characters outside XML 1.0 in transcription, notes and metadata text fields, and reserve the object IDs `errors` and `catalog`. One parser reads the field table of `01_PROJECT.md` by exact labels (ADR-016). The provider layer retries 429, 5xx, timeouts and connection errors with bounded backoff that honours `Retry-After` and raises a distinct error for truncated answers (`bb9cd65`).
- Step 3 always merges chunks, keeps the weakest declared confidence in lower case, takes over no model-proposed metadata, rejects `--sample 0`, stops a truncated answer without a second call and paces only after provider calls. Step 2 marks documents without page images `transcribable: false`, and step 3 skips them. The fetcher caps the response size and records images that would expand to excessive sizes when decoded (decompression bombs) as failures (`0a4b29a`).
- Step 4 accepts the judge vocabulary of its prompt, records every judge call and treats outputs judged under another vocabulary as stale (ADR-017). Step 5 writes only `results/tei/`, declares no invented language or publisher and refuses to overwrite TEI whose bytes differ from its recorded digest without `--force` (ADR-019). Step 6 and the local review server share one record and catalog builder, step 6 writes `errors.json` to `results/frontend/` and refuses TEI whose step-5 report names another derivation. The review server rejects no-op saves, caps text fields and sends a CSP header, and `update_review.py` takes the writer lock and refuses during a pending transaction (`ff3ef12`).
- Step 2 writes the inventory table in English (`d01d574`).

The knowledge base was restructured and translated. Every document in `knowledge/` is English (ADR-014). `01_PROJECT.md` to `05_DESIGN.md` hold only the edition configuration, and the criteria self-assessment moved from the index into `05_DESIGN.md`. The data contract, the local review contract and the provider records moved to `reference/`, and the fixed base mapping of step 5 left `04_TEI_MAPPING.md` for `reference/tei-mapping.md`. `project.md` and `specification.md` became [[overview]], and `lineage.md` and `case-comparison.md` became [[lineage]] (ADR-015). The moved documents were updated to the code, and the decision records and journal entries lost their bold field labels. The comparison anchor of DoCTA in the entry of 27 August 2026 was corrected to `d0a4a5305ce4`. Docstrings in `pipeline/` point to the new paths, and the example knowledge of the offline quickstart declares its language as `en`. The link check of `tests/test_offline_quickstart.py` covers the new reference files and the inherited knowledge documents, including their wikilinks.

The test suite was rebuilt on shared builders and fixtures in `tests/conftest.py`. An autouse guard blanks the provider keys and blocks connections to non-loopback addresses, so a test that forgets to stub a provider fails instead of making a paid call. Tests pin `schemas/tei_all.rng` instead of the fork-configurable schema, the parallel-save test no longer depends on a slow build, directory links are tested as Windows junctions, and the frontend is checked by rendering it under Node instead of grepping `app.js`. Step 1 gained tests with PDFs generated in memory. The closing pass let step 5 read both spellings `normalis` and `normaliz` as a normalised edition type, removed the unused German `detail` string from the annotation dependency record and removed the stale document path from the transcription prompt.

#### Verification

At the end of the session `uv run ruff check .`, `uv run ruff format --check .` and `uv lock --check` were clean and `uv run pytest -q` passed with 497 tests and no skip in about 19 seconds, against 243 passed and one skip in about 150 seconds at the start. The compiled RelaxNG schema is cached per process, which removed most of the former runtime. The offline quickstart ran end to end inside the suite. A separate check resolved every Markdown link, anchor and wikilink in `knowledge/` and the four new reference files. The viewer fix was checked in headless Chrome with hostile TEI values, and the review server was exercised with real HTTP saves against a quickstart workspace.

#### Open points

- The Pages job cannot verify annotation bindings. `data/annotations/` is committed while `data/processed/**` is ignored, so in a Pages checkout the canonical transcription is missing, the binding counts as unreadable and the publication check blocks every edition with annotations. How annotations bind in the Pages job is an operator decision.
- The Language value of `01_PROJECT.md` and the `language` of document metadata become `langUsage/language/@ident` unchecked. Whether the scripts validate BCP 47 codes is an operator decision.
- Existing forks meet three one-time consequences. The changed transcription prompt makes earlier step-3 outputs stale, so a rerun needs `--force`. Step 5 refuses to replace TEI written before the recorded digest existed until one `--force` run. Processed image manifests without a SHA-256 per page must be regenerated.
- `update_review.py` cannot tell whether a person or an agent runs it, so the rule that agents never record `human_verified` or `accepted` stays a behavioural rule on the command line.

### 2026-09-30 Integrate the editorial workflow definitions

#### Goal

Integrate the definitions of the agent-supported edition workflow and the epistemic infrastructure of the edition project agreed with the operator.

#### Result

The English definitions are maintained in the [conceptual basis](template/overview.md#conceptual-basis). The README and [[00_INDEX]] link there. The project-specific use of epistemic infrastructure is distinguished from the general concept, which also applies without AI agents, and its design requirements are distinguished from the supplied implementation.

The existing operator-document link test passed. The new section anchors, the documentation diff and the prose style were checked. No code or processing configuration changed.
