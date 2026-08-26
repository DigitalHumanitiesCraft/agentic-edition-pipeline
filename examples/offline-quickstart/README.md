# Offline quickstart

This example exercises the deterministic path from contract-conformant transcription JSON to the static edition. It uses two synthetic documents, requires no API key, makes no network request, and writes only to a separate local workspace.

From the repository root, run:

```console
python examples/offline-quickstart/run.py
```

The command creates `.aep-quickstart/`, runs deterministic validation, generates TEI, validates it against the shipped TEI All RelaxNG schema, and builds the frontend data and downloadable TEI assets. It fails if the target already exists. Rebuild the canonical target explicitly with:

```console
python examples/offline-quickstart/run.py --force
```

An existing target is accepted when it is empty. The runner records ownership in `.aep-offline-quickstart-owner.json`. With `--force`, recursive replacement requires an intact marker bound to the target's exact path, including for the canonical `.aep-quickstart/` target. Non-empty unmarked targets, manipulated markers, and paths traversing symbolic links or Windows reparse points are rejected without deleting their contents.

Preview the generated edition with the command printed at the end of the run. The default is:

```console
python -m http.server 8080 --directory .aep-quickstart/docs
```

Open `http://localhost:8080/` in a browser. The generated `quickstart-report.json` records the object IDs, completed checks, explicit schema target, offline provider configuration, and ownership marker. The runner clears every supported API-key and provider variable before it starts the pipeline processes.

The example proves the runnable deterministic path and its declared technical checks. It does not provide scholarly validation or acceptance of an edition.
