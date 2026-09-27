# Evaluation and evidence

Every check establishes a bounded claim, and reports name that claim. A formally valid TEI file can contain a transcription error, a preserved text can carry a wrong entity assignment, and a saved correction records an intervention whose accuracy still needs verification.

## Checks and their claims

| Check | Establishes | Further evidence required |
|---|---|---|
| Inventory and page contract | Declared pages agree with available and processed pages | Whether the source selection is complete |
| Transcription JSON contract | Expected fields and internal consistency | Accuracy against source images |
| Marker round-trip | Ordered text preservation under the declared whitespace policy | Correct reading and editorial interpretation |
| RelaxNG validation | Conformance to the selected structural schema | Suitability of that schema and scholarly correctness |
| Exact mention anchoring | An annotation selects the intended text occurrence | Entity identity, role, relation and authority match |
| Recorded human review | Who declared which review state and when | The declared review procedure and its scope |

The base pipeline implements neither semantic mention anchoring nor identity resolution. Those checks apply once a project adds such extensions.

## Recognition quality

Use a fixed reference set with documented provenance and review maturity. Describe its selection by material, script, language, page layout and relevant difficulty. A successful demonstration or the first N documents that `--sample N` selects give no corpus-wide accuracy estimate.

For independent reading, inspect the image before showing the generated text and record the reading before comparison. The current frontend has no dedicated blind-review mode, so a project follows this procedure with separate views.

State whether recognition received catalogue metadata, earlier transcriptions or object-specific instructions. The supplied transcription script adds each document's inventory metadata to the prompt, so its results are metadata-assisted. An image-only comparison needs a documented adaptation, separately recorded prompt states, the same source bytes and a reference excluded from both calls. Agreement with supplied context alone does not establish accurate recognition.

Model confidence and an LLM judge's plausibility verdict are not measured error rates, and automatic quality labels grant no acceptance. A text-only judge cannot verify the source handwriting. Preserve uncertain readings.

## Corrections and acceptance

A save in the local editor records one intervention with actor, reason and before and after values, and sets the page to `in_review`. It verifies no other passage, grants no acceptance and neither commits nor pushes. `human_verified` and `accepted` are separate human decisions recorded with `update_review.py`. A corrected text becomes a gold-standard reference only after its verification method and maturity are recorded.

## Read-only evaluation module

`aep_eval` evaluates existing files without modifying them. It computes the character error rate against a reference under a named normalization profile and checks TEI against an explicitly selected RelaxNG schema.

```console
uv run python -m aep_eval tests/fixtures/evaluation/manifest.json --out results/evaluation
uv run python -m aep_eval MANIFEST --out DIR --strict --fail-fast
```

The [fixture manifest schema](../schemas/evaluation-fixture.schema.json) declares hypothesis, reference, scope, reference class, maturity tier, Git anchor and file hashes. Results are written as `results.json` under the [result schema](../schemas/evaluation-result.schema.json) and as `report.md`.

The existing profile identifiers are kept for compatibility:

- `hsa-strict` collapses whitespace while keeping case and punctuation, resolves supported transcription conventions and aggregates weighted by characters.
- `zbz-fidelity` uses its declared extraction and symmetric normalization, reports a fidelity share of the edit distance and aggregates fixture means.

Select a profile for its extraction and comparison rules. The identifiers name historical implementations and prescribe nothing about the corpus of a new fork. Results name their profile, and scores under different profiles are not interchangeable.

The exit code is 0 for a completed run without reportable errors, 1 for fixture errors and 2 for an unusable manifest. `--strict` also fails the run on invalid TEI, and `--fail-fast` stops at the first fixture error. [ADR-006](../knowledge/decisions.md) records the evaluation design.

## Provenance and derived findings

A hash identifies an input state and attests nothing about its correctness. Preserve the original observation and record which text version a later assessment concerns. After a correction, earlier notes can contradict the current text and need review.

Model API calls, harness-driven annotation and deterministic scripts need identifiable inputs, operations and outputs. The [provider records](provider-records.md) cover the calls of steps 3 and 4 and are no trace of other agent actions.

Document-local entity IDs, textual mentions and resolved entities are different counting units. Report them separately and review identity merges, roles and relationships against their source evidence.

## Evidence from the video

The [video tutorial](https://youtu.be/krL-xMxTa_c) documents development observations that inform the knowledge base. It is neither a controlled model benchmark nor a record of scholarly acceptance.

Relevant observations are metadata-assisted reading at 26:38–31:37 and 43:04–49:54, possible reading bias at 40:41–41:26, correction and stale notes at 52:20–57:28, and TEI modelling and entity interpretation at 1:08:03–1:10:35. The supplied transcript ends at 1:14:59, and no claim about later video content is derived from it.

These observations support requirements for explicit input context, version-bound findings and documented annotation choices. They establish no hallucination rate, no confirmed model-induced reading error and no measured processing costs.
