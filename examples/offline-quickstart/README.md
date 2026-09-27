# Offline quickstart

The example runs the deterministic path from transcription JSON to the static edition on two synthetic documents. It needs no API key, makes no network request and writes only into a separate workspace.

From the repository root, run:

```console
uv run python examples/offline-quickstart/run.py
```

The runner creates `.aep-quickstart/` and copies the pipeline, schemas, references, evaluation module, viewer, operator documents and synthetic evaluation fixtures into it. It copies the template's `knowledge/` and overlays the filled example documents `01_PROJECT.md` to `05_DESIGN.md`, then places the example transcriptions under `data/processed/transcriptions/`. API credentials and research corpora are never copied, and every provider variable is cleared for the child processes.

In the workspace it runs, through their command-line interfaces:

1. Deterministic quality assessment (`04_validate.py --all --no-llm --force`).
2. TEI generation (`05_annotate_tei.py --all --force`).
3. RelaxNG validation against the shipped TEI All schema.
4. The frontend build (`06_build_frontend.py`).
5. `aep_eval` on the synthetic fixture manifest, writing to `results/evaluation/`.

A failing build step stops the run. The schema and evaluation steps always run, and their exit statuses become checks in `quickstart-report.json`, which also records the object IDs, the schema target, the evaluation manifest, the cleared provider settings and the ownership marker. The run fails when any check fails.

## Target and ownership

`--target PATH` selects another workspace. Inside the repository only the default `.aep-quickstart/` is allowed, and paths through symbolic links or Windows reparse points are refused. An existing target must be empty unless `--force` is given:

```console
uv run python examples/offline-quickstart/run.py --force
```

The runner records ownership in `.aep-offline-quickstart-owner.json`. With `--force`, recursive replacement requires an intact marker bound to the target's exact path, including for the default target. Non-empty unmarked targets and manipulated markers are rejected without deleting their contents. `--clean` removes the workspace under the same checks and leaves unmarked or manipulated targets untouched:

```console
uv run python examples/offline-quickstart/run.py --clean
```

## Preview

The run ends by printing a preview command for its workspace. For the default target it is equivalent to:

```console
uv run python -m http.server 8080 --bind 127.0.0.1 --directory .aep-quickstart/docs
```

Open http://127.0.0.1:8080/ in a browser.

## Scope

The example demonstrates the deterministic path and its declared technical checks. It provides no scholarly validation or acceptance of an edition. An agent can read the copied instructions alongside the generated results. The workspace has no Git history and no publication workflow, so a real edition starts from a fork as described in [SETUP.md](../../SETUP.md).
