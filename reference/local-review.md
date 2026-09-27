# Local review contract

The local service starts from a configured edition with the command below and binds only to `127.0.0.1`.

```console
uv run python pipeline/review_server.py --port 8080
```

GitHub Pages remains a static reading view. A session token and Host and Origin checks limit write access to the local session, and cross-site requests are refused. Every response carries a Content Security Policy header that blocks foreign scripts and, with `frame-ancestors 'none'`, embedding in another page. The service is no authenticated multi-user system.

## API

`GET /api/session` returns write capability and the session token. `GET /api/documents/{object_id}` returns pages, a file version, stored proposals and the state of known dependencies. `POST /api/documents/{object_id}/pages/{n}` expects the strings `version`, `transcription`, `notes`, `actor` and `note`, plus an optional `actor_kind`. `actor_kind` is the string `human` or `agent`, and an omitted value counts as `human` for compatibility. The service offers no endpoint for scholarly release.

POST requests use `Content-Type: application/json` and the header `X-Review-Token` with the value from `GET /api/session`. Agents declare `actor_kind: "agent"`. Before a save they read the current document version and compare their planned change with the existing text. Tokens belong in no file, log or public URL.

| Response | Cause |
|---|---|
| 409 | the version hash is stale, and the client must compare again, because replacing only the hash would bypass the conflict protection |
| 400 | invalid or unexpected fields, an empty actor or reason, a save identical to the current page state (`No change to save`), an oversized field, or a pending interrupted transaction |
| 413 | an empty body or one above the request size limit |
| 415 | another content type or chunked transfer |
| 403 | a foreign host or origin, a cross-site request or an invalid token |

`transcription` and `notes` are each limited to `MAX_TEXT_CHARS` characters (200 000 in `pipeline/review_server.py`), the reason and the actor name to shorter limits in the same module. A page with `foreign_paragraphs` is refused, because paragraph-index annotations need the project annotation workflow.

Proposals go with the same fields to `/api/documents/{object_id}/proposals/{n}`. They stay under `data/review-proposals/{object_id}/`, separate from the canonical text. Their base version makes later staleness visible. A proposal file that cannot be read is reported with its error in the document response, and the remaining proposals stay available. A proposal enters the text only through an explicit correction save.

## Processing a save

A save runs steps 4 and 5 without a model call on a staged copy, checks the result against the configured `VALIDATION_SCHEMA` and prepares the viewer files with the same record and catalog builders step 6 uses. A review save and a later step-6 run therefore write identical bytes to `docs/data/`. Prepared files replace the published ones only after every check has passed. A save refuses TEI in `results/tei/` that differs from what the base generator produces for the current validated file, so enriched TEI keeps its markup and goes through the project annotation workflow.

ZIP snapshots under `results/review-backups/` and a transaction marker secure recovery. A failed write rolls back through the same hash-checked path as the recovery command. While the marker exists after an interrupted process, the service refuses edits and does not serve generated assets. Recovery runs with the command below.

```console
uv run python pipeline/review_server.py --recover
```

Recovery checks the snapshot hash recorded in the marker, restores the previous files, removes only the output files the snapshot lists as previously absent and then removes the marker. It restores only paths under `data/processed/`, `results/tei/`, `results/reports/`, `docs/data/` and `docs/tei/`. Without a pending transaction the command reports this and exits with status 1.

An operating-system lock limits the server, the recovery command and `pipeline/update_review.py` to one writing process per repository. It is released when the process ends. `update_review.py` also refuses to write while a transaction is pending, because recovery would restore the snapshot and silently drop the transition. Direct file editing by other tools must not happen during a save.

## Browser interface

The browser keeps the draft after HTTP 409 and after failed saves. An unsaved draft warns before the page is left. Proposals can be loaded into the input field first, and adopting one still requires an explicit save. Page state and aggregated document state are shown separately, so a single edited page can stand beside pages that remain unreviewed.

GitHub Pages shows the provenance and correction events derived from TEI. Raw transcription, complete before and after values, session token and proposals are available only through the local service. A save starts no commit, push or scholarly release.

## Data of an intervention

`pages[].edits` contains `id`, `actor`, `actor_kind`, a `timestamp` with time zone, `note` and complete `before` and `after` values for `transcription` and `notes`. The event sequence must match the current text. `transcription_raw` and the initial model provenance stay unchanged. A save sets the page to `in_review` through the review transition of the [data contract](data-contract.md). TEI takes over the stored events with actor and page reference in `revisionDesc`, as the [TEI base mapping](tei-mapping.md) describes. Unconfirmed proposals produce no change there. Page releases (`human_verified`, `accepted`) remain an explicit human decision recorded with `update_review.py`.

## Dependencies

Optional project-specific annotations under `data/annotations/{object_id}.json` bind the transcription state through `_meta.transcription_sha256`. The hash covers UTF-8 JSON with sorted keys, unescaped Unicode characters and compact separators. Missing, unreadable or deviating bindings need review. The service renews no annotations. After a text change they remain visible as stale, and the publication check blocks them.

Review reports must name their input. After a change, an earlier finding makes no statement about the new state. A newly saved correction confirms no other passage and not the whole page. Recovery files and complete call records are never served publicly.

## Notes and reference status after a correction

The editor can change text and notes together and records both before and after values. An unchanged older note can still describe a reading that has since been replaced. The application does not detect such contradictions automatically.

A save is therefore the moment to check the page notes against the current text. Original model observations stay traceable in the call record and, after later changes, in the event sequence. A save confirms only the stored intervention. Using the corrected text as an independent evaluation reference requires the review procedure an edition documents in its [editorial guidelines](../knowledge/03_CONTEXT.md).
