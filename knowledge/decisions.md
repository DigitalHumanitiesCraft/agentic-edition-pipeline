---
title: Decisions
description: Architecture decision records of the template and of the edition built from it
tags: [decisions, architecture]
project:
  name: agentic-edition-pipeline
  repository: https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline
method:
  name: Promptotyping
  url: https://lisa.gerda-henkel-stiftung.de/digitale_geschichte_pollin
status: active
created: 2026-04-03
updated: 2026-09-27
---

# Decisions

Architecture and design decisions are recorded here as architecture decision records (ADR). The agent adds a record when a pipeline script changes or a design decision is taken. A fork keeps the template's records and appends its own below a heading that names the fork, as [[00_INDEX]] describes.

## Format

```
### ADR-NNN Title (YYYY-MM-DD)

#### Context
What is the starting situation?

#### Decision
What was decided?

#### Rationale
Why?

#### Alternatives
What was rejected, and why?
```

## Template decisions

### ADR-001 Bilingual documentation (2026-07-17)

Superseded by ADR-014.

#### Context

The template carried documentation in two languages. README and SETUP were English, so that the forkable repository stayed accessible to an international audience. The knowledge documents in `knowledge/` were German, because they continued the Promptotyping knowledge base of the German-language source projects.

#### Decision

The documentation stays bilingual. README and SETUP are maintained in English, the knowledge documents in `knowledge/` in German. No unification on one language.

#### Rationale

The two languages served two different readerships. The English README and SETUP address fork users, the German `knowledge/` addresses the agent and the German-speaking edition team that fills the knowledge base. A unification would serve one of the two readerships worse.

#### Alternatives

A complete switch to English was rejected, because the knowledge base connected conceptually to the German-language source projects and the edition team worked in German. A complete switch to German was rejected, because it would restrict the international forkability of the template.

### ADR-002 One data contract, API-key gate instead of an import mode (2026-07-18)

#### Context

The two fork test runs found three key variants for the same page text (`transcription` in the prompt and in steps 4 and 5, `text` in the quality signals, nested `pages` in step 3) and silent metadata loss in step 4. A declared path for transcriptions produced without a provider key was missing as well.

#### Decision

One single data contract, today the [data contract](../reference/data-contract.md), with `pages` at the top level, page text under `transcription` and object metadata under `metadata`, passed unchanged from step 3 to step 6. Every stage with a provider call checks the API key at start and stops with a clear message. Step 3 has no import mode, and externally produced transcriptions are written in conformance with the contract directly to `data/processed/transcriptions/`.

#### Rationale

Steps 4 and 5 already expected the flat contract, so adapting step 3 was the smallest intervention. An import mode would create a second entrance with its own validation logic, while the documented contract delivers the same capability without code. Running on silently without a key produced empty results without an error message in the test runs.

#### Alternatives

An `--import` flag for step 3 was rejected as a second code path for the same contract. Reloading the metadata in step 5 from `transcriptions/` was rejected, because passing them through in step 4 keeps the contract continuous.

### ADR-003 Central image-root resolution and remote facsimiles (2026-07-18)

#### Context

Image path resolution was duplicated per script and inconsistent. Step 6 checked only `data/processed/images/`, step 3 preferred it, and existing facsimiles under `data/sources/images/` stayed invisible in the frontend. The SZD (Stefan Zweig Digital) test run also brought corpora with exclusively remotely referenced facsimiles.

#### Decision

One resolver function, `config.resolve_image_dir` (first `data/sources/images/`, then `data/processed/images/`), used by all scripts. Step 6 copies local facsimiles to `docs/images/{object_id}/` and binds `has_images` to what can actually be displayed. Remote facsimiles are a declared case with `metadata.image_urls` in the data contract, `<facsimile>` with `graphic url` in the deterministic TEI, direct URL display in the frontend and materialisation through `pipeline/fetch_facsimiles.py`.

#### Rationale

A single resolution removes the class of path ambiguities that both test runs found independently. The static frontend can serve only below `docs/`, so step 6 copies the files.

#### Alternatives

Symbolic links instead of a copy were rejected as not portable to Windows and GitHub Pages. Remote-only display without a fetch utility was rejected, because vision transcription and verification need local files.

### ADR-004 Convention names journal.md and decisions.md (2026-07-18)

#### Context

The Promptotyping convention expects `journal.md` and `decisions.md`, while the template kept both numbered (`07_JOURNAL.md`, `06_DECISIONS.md`). Users who knew the convention searched for the convention names or created duplicates.

#### Decision

Renaming to `journal.md` and `decisions.md`. The reading order comes from the table in [[00_INDEX]].

#### Rationale

One name per role, and the convention is the older and broader source of truth.

#### Alternatives

Declaring the numbered names as a deliberate deviation was rejected, because it only documents the conflict instead of removing it.

### ADR-005 The validation target is a project decision (2026-07-18)

#### Context

The strict check by Research Mission Control showed that the deterministically generated TEI failed the DTABf RelaxNG schema (DTA base format of the Deutsches Textarchiv) on pre-existing header structures (`title` attributes, `projectDesc`, `revisionDesc`, `facsimile` position). The new note types caused no error. The template implicitly claimed DTABf as validation target without meeting it. All four TEI files of the ZBZ (Zentralbibliothek Zürich) test run validated against TEI All without errors (checked 2026-07-18).

#### Decision

The template configures TEI All as runnable technical default target. Every fork confirms this target or replaces it with DTABf, its own RelaxNG schema or a schema generated from ODD. `VALIDATION_SCHEMA` in `pipeline/config.py` is the shared configuration point, and `pipeline/validate_schema.py` checks against it. The DTABf files stayed in the template as a worked example profile with a documented header caveat for the strict case.

Since 2026-09-27 the template no longer ships a DTABf schema, and `schemas/README.md` names its sources and licence.

#### Rationale

The two original options, documenting TEI All as fixed target or pulling the header strictly to DTABf, would each have served one class of projects worse. Configurability solves both cases and makes the claimed target explicit and checkable.

#### Alternatives

Pulling the header strictly to DTABf was rejected as the sole solution, because it binds all forks to a profile not all of them need. TEI All as the only declared target was rejected, because it loses strictness for projects that maintain a profile.

### ADR-006 Evaluation module aep_eval with declared CER profiles (2026-08-22)

#### Context

The inventory by Research Mission Control (pilot Agentic Edition Evaluation, task T-024) found three incompatible ways of computing the character error rate (CER) around the template. The Schuchardt fork measured against the published edition with whitespace normalisation, zbz-ocr-tei measured against manual reference TEI with symmetric normalisation and a fidelity and scope decomposition, and SZD-HTR used its own protocol normalisation. The template itself had no evaluation. The TEI check was schema-specific and had no shared result format. The operator authorised the local implementation of a first slice (operator points OP-003 and OP-004 of Mission Control).

#### Decision

A standalone package `aep_eval` (CLI `uv run python -m aep_eval MANIFEST --out DIR`) reads a fixture manifest checked against a JSON Schema (hypothesis, reference, scope, reference class, maturity level, Git anchor, hashes), computes CER under declared profiles and checks TEI against an explicitly named RelaxNG schema. Results are schema-checked JSON and Markdown. Version 0.1 carries two profiles. `hsa-strict` ports `tools/evaluate_cer.py` of the fork and aggregates weighted by characters. `zbz-fidelity` ports `extract_text_for_comparison`, `normalize_for_comparison` and `classify_edit_operations` from zbz-ocr-tei and aggregates as the mean over fixtures. Every result carries profile, reference class and maturity level (observed function, formal validation, model-judged, human-reviewed, operator-accepted) as required fields. The regression anchors are Schuchardt 0.0598 over eighteen letters with 18 of 18 valid against `tei_all.rng`, and Hersch `end_to_end_fidelity.mean` 0.020804 over 25 reference documents as a technical oracle with documented provenance (the source file was generated on an unclean worktree). Inputs stay read-only, and source texts and facsimiles are not copied into the template. Two runtime dependencies are added, jsonschema and rapidfuzz.

#### Rationale

Without a declared normalisation profile, CER values are not comparable between projects, and the profile as a required field makes the incomparability visible. The ports reproduce the frozen figures of the source projects exactly and can therefore be audited against the originals. The maturity level separates technical conformance from scholarly validation, which stays with the operator. rapidfuzz is needed because the fidelity decomposition needs the opcodes of the minimal alignment, and a Python backtrace does not carry documents with several hundred thousand characters.

#### Alternatives

A universal normalisation profile was rejected, because none reproduces both source contracts. Evaluation as pipeline step 07 was rejected for version 0.1, because it makes sense only after the contract is confirmed and with structure and entity evaluators (Mission Control plan M10). Pure Python Levenshtein without a dependency was rejected because of run time and memory on the Hersch documents.

### ADR-007 Isolated offline quickstart with a synthetic corpus (2026-08-26)

#### Context

The template contained an offline path proven inside the tests, but no directly executable example for fork users. A run in the repository root would mix the deliberately unfilled knowledge skeleton and the working data of the template with example data.

#### Decision

`examples/offline-quickstart/` carries two synthetic transcription files that conform to the contract, filled example knowledge and a runner. The runner creates a separate local project folder, copies the real pipeline and frontend files there and runs step 4 without a model, step 5, the explicit RelaxNG check against TEI All and step 6 through their public CLIs. It clears all provider and API-key variables before the child processes. An ownership sentinel binds each target to its absolute path. Recursive replacement also requires an unchanged sentinel at the canonical default target, and empty targets can be filled for the first time. Paths through symbolic links or Windows reparse points are rejected before their resolution. A machine-readable final report documents object set, checks, schema, sentinel and offline configuration.

#### Rationale

The run checks the actual command-line path in fresh processes. The template skeleton, existing corpus data and provider configurations stay untouched. The fail-closed target check prevents `--force` from deleting foreign directory contents. Synthetic texts avoid dependencies on image rights, external services and production data not yet accepted.

#### Alternatives

Prebuilt TEI and frontend outputs were rejected, because they do not check the processing chain. Copying the fixtures into `data/processed/` of the template repository was rejected, because example and user data would then share the same working state.

### ADR-008 Publication metadata and TEI download in the static serving root (2026-08-26)

#### Context

The data contract promised the mapping of object data to `origDate`, but the deterministic TEI generation left out `date` and `repository`, so the frontend catalogue lost the date values. The download button pointed to `results/tei/`, although the local server and GitHub Pages serve only `docs/`.

#### Decision

Step 5 writes `metadata.date` as `history/origin/origDate` and `metadata.repository` as `msIdentifier/repository`. Semantically valid calendar values get `origDate/@when`, and free datings stay as safely escaped text without a normalising attribute. Step 6 synchronises the successfully processed canonical TEI files as an exact XML mirror to `docs/tei/{object_id}.xml`, and the client uses this relative path for the download.

#### Rationale

The metadata stay visible along the existing contract and provide the static filter basis. All published assets lie under the same static serving root and work locally and in the GitHub Actions deployment. The exact mirror prevents stale download files after a failed or reduced corpus run.

#### Alternatives

Removing the download button was rejected, because TEI export is a promised standard function. A relative access to `results/tei/` was rejected, because this folder lies outside the published root.

### ADR-009 Lineage categories and the deterministic TEI boundary (2026-08-27)

#### Context

README and knowledge base mixed four source projects, planned forks, the meanwhile completed Schuchardt run and independent project pipelines. The documentation also still promised an optional LLM annotation path in step 5, although the code has worked exclusively deterministically since the operator decision of 24 August 2026.

#### Decision

[[lineage]] distinguishes real edition cases, technical sources, test artefacts, direct project instances, architectural transfers and conceptual precursors. Hersch, SZD and DoCTA (Doing Court in the Tyrolean Alps) are the three real edition cases. Hersch and SZD form the empirical and technical starting point of the generalisation, and DoCTA applies the architecture in an independent project. The offline quickstart and the local fork with letters from the Hugo Schuchardt Archiv (HSA) are technical test artefacts. Step 5 stays a deterministic base path. Semantic annotation and complex structures are implemented as a project-specific deterministic extension or as a separate, documented stage. Dead provider configuration and the unused annotation prompt are removed.

#### Rationale

The categories make research contribution, provenance, code descent and evidential scope checkable. The documentation then describes the executed code path and prevents a knowledge entry from being read as an already implemented transformation.

#### Alternatives

Calling DoCTA a literal fork was rejected, because no shared Git descent and no takeover of the template file contract is documented. The old LLM annotation path was rejected, because it had no code reader and produced false run-time and provenance assumptions.

### ADR-010 Shared core from Hersch/ZBZ, SZD and DoCTA (2026-08-27)

#### Context

The comparison of the three official edition cases found recurring requirements that the template had only documented or mapped only after transcription. SZD and DoCTA steer different materials with their own prompt modules. All three projects separate machine results from human-reviewed text states. ZBZ and DoCTA keep status values as controlled working states. All three obtain facsimiles from external repositories. The template could load remote images only from an existing transcription or TEI file and did not assemble the described prompt layers 2 to 4 in executed code.

#### Decision

`data/sources/manifest.json` becomes the early contract for document metadata, remote pages and prompt profiles, and step 2 merges it with local sources. Step 3 assembles base rules, profile, metadata and object rule and records layers and hash. Every generated page gets an immutable `transcription_raw`, an editable text and the human-controlled state `machine_unreviewed`. The state sequence also includes `in_review`, `human_verified` and `accepted`. Automatic quality values stay separate from it. The model answer must contain exactly one page per image. Step 5 writes the least mature page state into `revisionDesc` and produces byte-identical TEI from the same validated input.

#### Rationale

These functions occur in all three cases under different names and solve the same contract problems. The shared core establishes provenance, completeness and maturity of a text state before project-specific annotation or publication begins. The early manifest input removes the circularity by which remote images could be loaded only from a transcription result.

#### Alternatives

Automatic derivation of a prompt profile from free document-type labels was rejected, because it produces unclear and hardly reproducible assignments. An automatic change of the human review state through quality signals was rejected, because technical plausibility proves no scholarly control. Layout regions, entity models and project-specific marker vocabularies stay extensions, because their contracts differ considerably between the three cases.

### ADR-011 Version 0.9 and state-bound trust boundaries (2026-08-27)

#### Context

The template already carried the label 1.0, although provider-specific and project-specific runs, scholarly review and user acceptance of the current core were outstanding. The examination of the three edition cases and of the Schuchardt run also showed that mere file existence, page counts and character counts bound earlier results insufficiently to their sources.

#### Decision

The repository stays at version `0.9.0` and marks itself as a pre-release. Step 1 binds renderings to PDF hash and resolution. The remote fetch binds URL, file name and image hash. Step 3 binds model, assembled instruction, executed chunk prompts and image bytes. Step 4 binds input and validation findings with separate state hashes. Step 5 accepts only the complete step-4 contract and produces TEI deterministically. Step 6 checks facsimile bytes, publishes atomically and removes withdrawn or stale assets. The Pages workflow checks RelaxNG and the state `accepted` before the build. Python dependencies are installed reproducibly with uv and `uv.lock`, and Ruff, format check and pytest form the technical gate.

#### Rationale

Every completion statement then points to a named and checked state. Technical validation, observed function, scholarly review and user acceptance stay distinguishable. Version 1.0 requires explicit user acceptance and at least one current provider-specific and project-specific run.

#### Alternatives

An immediate label 1.0 was rejected because of the outstanding acceptance. Continued existence skips were rejected, because changed sources and instructions would otherwise make old results appear current.

### ADR-012 Version 0.10 with a local correction contract (2026-09-08)

#### Context

Two local demo instances specified how browser corrections return into transcription data and TEI. They also showed the importance of unchanged model text, separate proposals and the binding of later annotations to their input text. A demo test wrongly assumed an unchanged real user state, so the new regressions use exclusively synthetic data.

#### Decision

An optional loopback service connects the browser and authorised local agents with the same versioned storage path. Every correction documents before and after values and sets the page to `in_review`. Before the takeover, the existing deterministic stages, text preservation and the configured RelaxNG schema run. Snapshots, transaction markers and a process lock secure the write path. Proposals stay separate. TEI events name actor and page, and complete private correction data are not copied into the static output. Deviating, already enriched TEI requires the project-specific workflow. Optional annotations get a checkable text binding, and stale bindings block publication.

#### Rationale

The return path must keep all published representations of a text state consistent. A valid schema alone confirms neither a reading nor a scholarly acceptance. Self-declared actor names suffice for a traceable local session but establish no multi-user authentication.

#### Scope

Version `0.10.0` stays a pre-release. Private call records and hash-bound chunk resumption extend step 3. Layout analysis, new NER methods (named-entity recognition) and authority linking stay outside this commission. The edition settings 01 to 05 remain as templates, while `project.md`, `specification.md` and the linked contracts steer template maintenance (today [[overview]] and the contracts under `reference/`). `AGENTS.md` adds the shared action layer.

#### Verification

Offline regressions check stored corrections, protection of raw texts, source bytes, conflicts, recovery, preservation of annotations and model call records. The browser check covered separate proposals, explicit adoption, input preservation and the static reading view. Real demo corpora were not changed. User acceptance, a renewed provider check and publication remain open.

### ADR-013 Harness-neutral working contract and project-independent entry (2026-09-08)

#### Context

README and setup mixed the general template with its historical edition cases and tied its operation to one harness. The video analysis showed additional ambiguities about model context, metadata takeover, scholarly acceptance and the scope of semantic annotation.

#### Decision

`AGENTS.md` holds the shared working contract, and `CLAUDE.md` points to it as a tool-specific entry. README and software description explain the reusable template, the AI harness and the independent choice of processing models. Additional technologies require explicit adapters or converters. Provenance cases stay in [[lineage]]. `SETUP.md` and `reference/` carry setup, commands and evaluation limits.

#### Processing

The numbered scripts keep their interfaces. Alternative entry points and dependencies are documented. Quality assessment, RelaxNG validation and scholarly acceptance are separate operations. Design specifies the inspection tasks with the first sample and with new findings. Fixed sets of epics or user stories are dropped.

#### Write-back

[[02_DATA]] and [[03_CONTEXT]] govern input roles, metadata context and reference formation. [[04_TEI_MAPPING]] distinguishes mentions, identities, roles and relations. The local review contract and the provider records limit the evidential scope of stored changes and calls. `specification.md`, today [[overview]], marks the functions derived from the video that are not yet implemented.

#### Technical consequence

The offline quickstart takes over the working contract and its references together with the synthetic examples and the existing evaluator. Link checks secure this navigation in the repository and in the generated example. Edition settings, real demo data and existing local changes stay preserved. Version `0.10.0` stays a pre-release.

### ADR-014 English knowledge language (2026-09-27)

Supersedes ADR-001.

#### Context

ADR-001 kept the knowledge documents German for a German-speaking edition team. The operator decided on 24 August 2026 that the template becomes English throughout, and the standing rule for knowledge folders requires English. The knowledge base still mixed German configuration documents with English contracts, and step 2 wrote a German inventory table.

#### Decision

Every Markdown file in `knowledge/` and the contracts in `reference/` are English. The template's decision records and journal entries are translated faithfully and keep their dates and content. German words remain only as proper names of institutions and archives, as script contract (the `INVENTAR_START` and `INVENTAR_END` markers, the German table labels still accepted in `01_PROJECT.md`), as quoted vocabulary of a historical case, or as a term defined in the glossary of [[00_INDEX]]. Step 2 writes the inventory table in English.

#### Rationale

The decision implements the operator decision of 24 August 2026. One language keeps the configuration documents consistent with README, SETUP and the contracts they point to, which were already English.

#### Alternatives

Keeping the bilingual split of ADR-001 was rejected, because it left the configuration documents German while every contract they point to was English.

### ADR-015 Document roles and fork inheritance (2026-09-27)

#### Context

`knowledge/` held three kinds of documents side by side. The numbered documents configure an edition, `08_DATA_CONTRACT.md`, `local-review.md` and `provider-records.md` describe fixed behaviour of the code, and `project.md`, `specification.md`, `lineage.md` and `case-comparison.md` describe the template itself. The fixed base mapping of step 5 stood inside the edition's `04_TEI_MAPPING.md`, and `05_DESIGN.md` repeated the open requirements of `specification.md`. A fork could not tell which documents it fills, which it must not change and which it may drop.

#### Decision

- Edition configuration stays in `knowledge/` as `01_PROJECT.md` to `05_DESIGN.md`. These documents hold placeholders and point to the fixed guidance.
- Fixed, fork-invariant contracts live in `reference/` as `data-contract.md`, `tei-mapping.md`, `local-review.md` and `provider-records.md`, next to `pipeline.md` and `evaluation.md`. They use Markdown links.
- Knowledge about the template lives in `knowledge/template/` as `overview.md` (from `project.md` and `specification.md`, with the one open-requirements table) and `lineage.md` (from `lineage.md` and `case-comparison.md`).
- `00_INDEX.md`, `decisions.md`, `journal.md` and `handoff.md` stay at the root of `knowledge/`. The criteria self-assessment moves from the index into `05_DESIGN.md`.
- A fork keeps the template's decision records and journal entries as its inherited record and appends its own below a heading naming the fork. It may keep `knowledge/template/` as reference or delete it.

#### Rationale

The roles differ in who changes a document and when. Edition configuration changes per fork, contracts change only with the code, and template knowledge changes only in template maintenance. Separate places make these update cycles visible in the path, so an agent can route a question by file location. Keeping the inherited records lets a fork trace why the code behaves as it does.

#### Alternatives

Keeping the contracts in the numbered sequence of `knowledge/` (as `08_DATA_CONTRACT.md` stood) was rejected, because the sequence otherwise lists the documents a fork fills. Starting a fork with empty records was rejected, because the fork would then lose the reasons behind the code it inherits.

### ADR-016 The field table of 01_PROJECT.md is a machine-read contract (2026-09-27)

#### Context

Step 5 and step 6 each read `01_PROJECT.md` with their own parser. Step 5 matched table labels by substring and fell back to the first heading as title, so rows such as `Langzeitarchivierung` or `Sprachen des Korpus` could fill the language and `[TODO]` placeholders reached the TEI header. SETUP named labels (`Herausgeber / Editor`, `Lizenz`) that the template table did not contain, so editor and licence of a filled template never reached the TEI.

#### Decision

One parser, `project_info` in `pipeline/config.py`, reads only Markdown table rows. A label counts when it equals `Title`, `Editor`, `Institution`, `Edition type`, `Language` or `License` after case folding and trimming, and the German labels `Projektname`, `Titel`, `Herausgeber`, `Editionstyp`, `Sprache`, `Lizenz` and the variants `Publisher` and `Licence` are accepted for existing editions. An empty value or one starting with `[TODO` counts as missing, and the first filled row of a field wins. The unfilled template yields no values. The Language value becomes `langUsage/language/@ident`, so the field asks for a BCP 47 language code. The Edition type decides the line-break rule of step 5. Step 5, step 6 and the local review server use the same parser.

#### Rationale

Exact labels make the table a contract that tests can pin (`tests/test_config.py`) and that an edition team can fill without side effects from headings or neighbouring rows. Treating placeholders as missing keeps invented values out of the TEI header.

#### Alternatives

The substring matching with heading fallback was replaced, because it read unrelated rows and headings. Validation of the language code was not added in this change and remains an open operator decision.

### ADR-017 The judge vocabulary follows its prompt and is part of the judge identity (2026-09-27)

#### Context

Step 4 accepted issue types and perspectives that differed from those `pipeline/prompts/validation.md` asks the judge to use. An answer that followed the prompt therefore violated the accepted vocabulary and counted as `uncertain`, which made the object `problematic`. A stored validation stayed current as long as provider, model and prompt hash matched, even when the accepted vocabulary had changed.

#### Decision

The enumerations in the fenced block of `pipeline/prompts/validation.md` are canonical. `JUDGE_ISSUE_TYPES` and `JUDGE_PERSPECTIVES` in `pipeline/04_validate.py` equal them, and a test compares both. `_meta.judge_vocabulary_hash` records the vocabulary a run accepted, and a stored validation with another vocabulary hash is stale until step 4 runs with `--force`. Every judge call leaves a call record like a transcription call, and its entry in `executed_prompts` names the record.

#### Rationale

The judge can only be held to the vocabulary it is asked for. Binding the vocabulary into the identity of a judged output prevents verdicts accepted under other rules from passing for current ones, in the same way the prompt hash already did for the prompt text.

#### Alternatives

Keeping a separate code vocabulary and mapping prompt terms onto it was rejected, because two vocabularies would drift apart again without a test binding them.

### ADR-018 The evaluator reads markers differently from the pipeline on purpose (2026-09-27)

#### Context

`aep_eval` resolves the transcription markers of a hypothesis before it computes CER. `pipeline/markers.py` defines the marker syntax, and its `resolve_markers` removes struck text and matches only the pipeline's illegibility syntax. The evaluator kept its own copies of the patterns, which could drift from the pipeline.

#### Decision

`aep_eval/profiles.py` copies the four marker patterns verbatim from `pipeline/markers.py`, so the evaluator stays importable without `pipeline/`, and `tests/test_aep_eval_cer.py` fails when the copies differ. Two readings differ deliberately. The evaluator keeps struck text, because both reference extractions keep the content of `<del>`, which step 5 writes for `~~text~~`. It also removes illegibility notes with the wider pattern `ILLEGIBLE_ANY_NOTE`, which covers free-text notes such as `[... Arabic script, ~1 word]`.

#### Rationale

Dropping struck text from the hypothesis alone would count every deletion as a recognition error against references that keep it. The wider illegibility pattern belongs to the `hsa-strict` source evaluator, and narrowing it moves the Schuchardt regression anchor of ADR-006.

#### Alternatives

Importing `resolve_markers` from the pipeline was rejected, because it would change the ported profiles and their frozen figures and would make the evaluator depend on the pipeline package.

### ADR-019 Single TEI output of step 5 and its overwrite guard (2026-09-27)

#### Context

Step 5 wrote each TEI file twice, to `data/processed/tei/` and `results/tei/`, and filled missing header values with invented defaults (language `de`, publisher `agentic-edition-pipeline`). An existing TEI file enriched by hand or by a project workflow could be overwritten by a regular run.

#### Decision

Step 5 writes only `results/tei/{object_id}.xml`, the candidate that schema validation, step 6, the local review server and the publication check read. Its report `results/reports/{object_id}_validation.json` records in `_meta.tei_sha256` the digest of the TEI bytes step 5 last wrote. An existing file with other bytes, or without a recorded digest, is replaced only with `--force`. The header carries only declared values. Without a language in document metadata or `01_PROJECT.md`, `langUsage` is omitted, and without a declared institution `publicationStmt` states in a paragraph that no publisher is declared. Step 6 refuses TEI whose step-5 report names another derivation. The [TEI base mapping](../reference/tei-mapping.md) holds the details.

#### Rationale

One copy removes the question which of two files is canonical. The recorded digest distinguishes a file step 5 wrote from one edited elsewhere without comparing content heuristically. Invented header values would pass schema validation and misstate the edition's language and publisher.

#### Alternatives

Keeping the working copy was rejected, because no reader needed it. Refusing every existing file without `--force` was rejected, because a regular re-run after a text change should replace the file step 5 itself wrote.
