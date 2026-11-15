# Changelog

Changes to the template, per version. Versions follow the numbering in `pyproject.toml`, which `CITATION.cff`, `codemeta.json` and the README repeat. All versions so far are research previews without a stable release. The journal in `knowledge/journal.md` records the work in detail.

## 0.11.0, research preview

The release date is set when the version is tagged. This is the first version with a Git tag.

### Changed against 0.10.0

- The static viewer renders TEI-derived data through DOM properties instead of HTML strings, which closes attribute injection from TEI content.
- The viewer calls the local review API only when the review server identifies itself.
- The data contract is hardened and the shared pipeline helpers are consolidated. The acquisition steps share selection, error and manifest helpers.
- The judge vocabulary matches its prompt, and step 6 and the review service produce the same frontend output.
- Both spellings of a normalised edition type are read, and the generated inventory table is written in English.
- `aep_eval` binds its markers to the pipeline syntax.
- LF line endings are pinned, so byte comparisons of TEI and JSON hold on Windows checkouts.
- The test suite is rebuilt on shared fixtures with a guard that blocks network access.
- The knowledge base is in English and separates the edition configuration (`knowledge/01_PROJECT.md` to `05_DESIGN.md`), the fixed contracts under `reference/` and the template knowledge under `knowledge/template/`. The template overview defines agent-supported edition workflows and their epistemic infrastructure.
- The journal opens with the open points, and `knowledge/handoff.md` is gone.
- The README states the limits of the research preview and where feedback goes.
- `certifi` is updated to 2026.10.23, which drops the distrusted emSign CA.
- `contract.py` rejects a review history in which an agent records `human_verified` or `accepted`, and an unknown `actor_kind`.
- A non-finite `Retry-After` header no longer aborts the provider retry loop.
- Step 1 imports `pymupdf` instead of the deprecated `fitz`, and the inventory records POSIX paths on every platform.
- `CITATION.cff` names both licences and no longer carries a release date that no tag backed. This changelog is new.

## 0.10.0, research preview

Recorded in the metadata on 2026-09-08 (commit `730d737`) without a Git tag. Added local editing of canonical transcription files through the browser and a local API for agents, with raw text kept, change events, recovery and conflict detection, private provider call records, hash-bound chunk resumption and the shared working contract `AGENTS.md` (ADR-012).

## 0.9.0, pre-release

Recorded in the metadata on 2026-08-31 (commit `9220057`) without a Git tag. Bound sources, prompts, model calls and review states by hashes, introduced the publication gate, the uv lockfile and the quality workflow (ADR-011).
