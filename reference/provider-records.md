# Provider records and resumption

Every provider call of step 3 and step 4 leaves a private call record under `data/processed/llm-calls/{object_id}/`. Step 3 writes one record per chunk call and per JSON retry that was actually started. Step 4 writes one record per page it sends to the judge. The entries of `_meta.executed_prompts` name their record in `record`, relative to `data/processed/`, as the [data contract](data-contract.md) specifies.

A record contains provider, requested model, temperature, the complete executed prompt, page range or page, the image file names with their hashes for step 3, start and end time, and the extracted answer text. A received JSON answer of the provider stays complete in `responses`, so values the provider supplied, such as the actual model version, usage and finish reason, remain verifiable. After a failure the redacted error message is recorded separately. Credentials, HTTP headers and embedded image bytes are not recorded, and configured key values are removed from answer contents as well. Step 4 fails an object when a judge record could not be written, because its provenance would be lost.

## Retries and truncated answers

`pipeline/llm.py` retries HTTP 429, server errors (5xx), timeouts and connection errors with bounded exponential backoff. A numeric `Retry-After` header lengthens the wait up to a fixed upper bound. Any other HTTP error stops at once. These transport retries belong to one logical call and have no separate records. An answer the provider cut off at its output-token limit raises a distinct error instead of reaching the JSON parser. Step 3 then stops the document with the stage `truncated` and makes no JSON retry, because a second call would be cut off at the same limit. An answer that arrived complete but could not be parsed gets one JSON retry in step 3. An answer that was not received or not readable as JSON cannot be stored as provider JSON. The documented model version depends on the fields the provider actually delivered.

## Chunk cache

Successful chunks that satisfy the contract are also stored under `data/processed/chunk-cache/{object_id}/`. Their identity covers the complete prompt, all authoritative object metadata, provider and model, temperature, image bytes, object, chunk and start page, and a cache contract version. The stored content has its own SHA-256. Identity, integrity and page contract are checked before reuse, so an interrupted document run can reuse its finished chunks. An unreadable or contradictory cache entry blocks the object instead of triggering a paid call. `--force` requests fresh calls, and the lock against transcriptions with review history stays in force.

Neither the local editor nor GitHub Pages serves call records. The local provenance view names the call references. Before such files are passed on, text and metadata rights and possible confidential content need checking. Synthetic regression tests check resumption, prompt and image changes, complete answer records and key redaction without network access.

## Execution paths and limits of their evidence

The model of the harness and the model of an API call are named independently. An annotation an agent writes directly in the harness needs its own task record with input state, instruction, result and the checks performed. The provider logger does not capture such harness actions.

A deterministic derivation is traceable through code state, configuration, input and result. A hash proves the identity of a state and says nothing about scholarly correctness.

Usage figures are reported only when the provider actually supplied them. A cost statement also needs the price model and the billing reference, and an estimate from a conversation is no evidence of cost. A missing actual model version stays marked as missing.

A joint provenance view could connect these execution paths in the future. An automatic PROV export (the W3C provenance data model) and a complete record of all harness actions are not implemented.
