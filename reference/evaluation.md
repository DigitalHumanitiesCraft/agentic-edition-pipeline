# Evaluation and evidence

Report the actual scope of each check. A formally valid TEI file can contain a transcription error. A preserved text can contain an incorrect entity assignment. A saved correction records an intervention; its accuracy still needs verification.

## Checks and their claims

| Check | Establishes | Further evidence required |
|---|---|---|
| Inventory and page contract | Declared pages agree with available and processed pages | Whether the source selection is complete |
| Transcription JSON contract | Expected fields and internal consistency | Accuracy against source images |
| Marker round-trip | Ordered text preservation under the declared whitespace policy | Correct reading and editorial interpretation |
| RelaxNG validation | Conformance to the selected structural schema | Suitability of that schema and scholarly correctness |
| Exact mention anchoring | An annotation selects the intended text occurrence | Entity identity, role, relation and authority match |
| Recorded human review | Who declared which review state and when | The declared review procedure and its scope |

The base pipeline does not implement semantic mention anchoring or identity resolution; those checks apply when a project adds such extensions.

## Recognition quality

Use a fixed reference set with documented provenance and review maturity. Describe its selection by material, script, language, page layout and relevant difficulty. A successful demonstration or a first-N sample is not a corpus-wide accuracy estimate.

For independent reading, inspect the image before showing the generated text and record the reading before comparison. The current frontend does not provide a dedicated blind-review mode. A project can follow this procedure with separate views.

State whether recognition received catalogue metadata, earlier transcriptions or object-specific hints. The supplied transcription script includes selected metadata. An image-only versus metadata-assisted comparison requires separate recorded prompt states, the same source bytes and a reference excluded from both calls. Agreement with supplied context alone cannot establish accurate recognition.

Preserve uncertain readings. A user correction is not automatically a gold-standard reference. Model confidence and an LLM judge's plausibility score are not measured error rates. A text-only judge cannot verify the source handwriting.

## Read-only evaluation module

`aep_eval` evaluates existing files without modifying them. It computes character error rate against a reference under a named normalization profile and checks TEI against an explicitly selected RelaxNG schema.

```console
uv run python -m aep_eval tests/fixtures/evaluation/manifest.json --out results/evaluation
uv run python -m aep_eval MANIFEST --out DIR --strict
```

The [fixture manifest schema](../schemas/evaluation-fixture.schema.json) declares hypothesis, reference, scope, reference class, maturity tier, Git anchor and file hashes. Results are written as `results.json` under the [result schema](../schemas/evaluation-result.schema.json) and as `report.md`.

Existing profile identifiers are retained for compatibility:

- `hsa-strict` collapses whitespace while retaining case and punctuation, resolves supported transcription conventions and uses character-weighted aggregation.
- `zbz-fidelity` uses its declared extraction and symmetric normalization, reports a fidelity share of edit distance and aggregates fixture means.

Select a profile for its extraction and comparison rules. These identifiers describe historical implementations and do not prescribe the corpus of a new fork. Results must name the profile; scores from different policies are not directly interchangeable.

Exit codes are 0 for a completed run without reportable errors, 1 for fixture errors and 2 for an unusable manifest. `--strict` also makes TEI invalidity fail the run. [ADR-006](../knowledge/decisions.md) records the evaluation design.

## Provenance and derived findings

A hash identifies an input state. It does not attest to its correctness. Preserve the original observation and record which text version a later assessment concerns. After a correction, earlier notes can contradict the current text and require review.

Model API calls, harness-driven annotation and deterministic scripts need identifiable inputs, operations and outputs. The existing [provider logger](../knowledge/provider-records.md) covers its documented API path. It is not an automatic trace of every agent action.

Document-local entity IDs, textual mentions and resolved entities are different counting units. Report them separately and review identity merges, roles and relationships against their source evidence.

## Evidence from the video

The [video tutorial](https://youtu.be/krL-xMxTa_c) documents development observations that inform the knowledge base. It does not provide a controlled model benchmark or a scholarly acceptance record.

Relevant observations include metadata-assisted reading at 26:38–31:37 and 43:04–49:54, possible reading bias at 40:41–41:26, correction and stale notes at 52:20–57:28, and TEI modelling and entity interpretation at 1:08:03–1:10:35. The supplied transcript ends at 1:14:59, so no claim about later video content is derived from it.

These observations support requirements for explicit input context, version-bound findings and documented annotation choices. They do not establish a hallucination rate, a confirmed model-induced reading error or measured processing costs.
