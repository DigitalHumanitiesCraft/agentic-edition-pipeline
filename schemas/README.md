# schemas/

Schema files for TEI validation and for the evaluation module.

## Files

| File | Role | License |
|---|---|---|
| `tei_all.rng` | TEI All RelaxNG schema of TEI P5 version 4.12.0, the permissive full schema of the TEI Guidelines. It is the template's default validation target (`VALIDATION_SCHEMA` in `pipeline/config.py`). | CC BY and BSD-2 (dual licence stated in the file header), TEI Consortium |
| `evaluation-fixture.schema.json` | JSON Schema of the `aep_eval` fixture manifest, described in [reference/evaluation.md](../reference/evaluation.md). | MIT |
| `evaluation-result.schema.json` | JSON Schema of the `aep_eval` result set. | MIT |

The header of `tei_all.rng` records TEI P5 version 4.12.0, revision 113e933e2. That version is available from the TEI Vault at https://www.tei-c.org/Vault/P5/4.12.0/xml/tei/custom/schema/relaxng/tei_all.rng.

The DTA-Basisformat (DTABf) of the Deutsches Textarchiv (Berlin-Brandenburgische Akademie der Wissenschaften) is not shipped, because its licence (CC BY-SA 3.0 DE) differs from the template's and the generated TEI does not pass it without adaptation. The print schema is at https://www.deutschestextarchiv.de/basisformat.rng and the manuscript variant at https://www.deutschestextarchiv.de/basisformat_ms.rng. Documentation is at https://www.deutschestextarchiv.de/doku/basisformat/schema.html, and a Schematron rule set at https://www.deutschestextarchiv.de/basisformat.sch. A fork that adopts DTABf downloads the variant it needs into this directory.

## How validation runs

Generated TEI is checked at two levels.

Step 5 (`pipeline/05_annotate_tei.py`) checks every generated file for XML well-formedness, for the required TEI elements (`teiHeader`, `fileDesc`, `text`, `body`) and for exact ordered text preservation per page after the declared diplomatic or normalised whitespace treatment. Marker structures are reconstructed before comparison, so omissions, reordered repetitions and lost line or paragraph boundaries block the write. Results go to `results/reports/{object_id}_validation.json`.

RelaxNG conformance against the schema named in `VALIDATION_SCHEMA` is checked automatically in two places. The local review server (`pipeline/review_server.py`) regenerates the TEI of an object on every save and refuses the save when that TEI fails the schema. The Pages workflow runs `pipeline/check_publication.py`, which blocks deployment unless every file in `results/tei/` is valid against the schema and humanly accepted. At any other point, for instance on the sample files at the step 5 checkpoint, the validator runs directly.

```
uv run python pipeline/validate_schema.py                               # all results/tei/*.xml
uv run python pipeline/validate_schema.py --schema schemas/basisformat_ms.rng   # after downloading it
```

[Jing](https://relaxng.org/jclark/jing.html) works as well, for example `jing schemas/tei_all.rng results/tei/*.xml`.

The deterministic TEI generator produces minimal DTABf-oriented structures. Project-specific extensions require the same RelaxNG check before publication.

## Choosing a validation schema

The validation target is a per-project decision (ADR-005 in `knowledge/decisions.md`). The template defaults to TEI All, because the generated TEI satisfies it without adaptation. A fork that constrains its encoding more tightly points `VALIDATION_SCHEMA` in `pipeline/config.py` at another schema in this directory.

- TEI All (`tei_all.rng`) is the permissive full schema, shipped and configured as the default. It accepts almost any valid TEI and therefore does not check project-specific conventions. The deterministic generator's output validates against it out of the box, verified against the fork test-run corpora on 2026-07-18 and pinned by `tests/test_validate_schema.py`.
- The DTA-Basisformat is the restrictive profile for historical German-language texts, with a manuscript variant. The deterministic generator's header does not pass strict DTABf. The failures lie in header structures (`title` attributes, `projectDesc`, `revisionDesc`, `facsimile` position), not in the body markup. A fork that declares strict DTABf as its target adapts the header template in `pipeline/05_annotate_tei.py` first.
- A custom RelaxNG schema suits a project that maintains its own encoding profile.
- An ODD (One Document Does it all) defines a TEI profile in a single source, from which the RelaxNG schema and its documentation are generated with [Roma](https://roma.tei-c.org/) or `oddbyexample`. Keep the ODD next to the generated schema in this directory.

## Using a different schema in a fork

Follow [SETUP.md, TEI and schema](../SETUP.md#tei-and-schema). Put the project schema into this directory, point `VALIDATION_SCHEMA` in `pipeline/config.py` at it, update the modelling decisions in `knowledge/04_TEI_MAPPING.md` and record the decision in `knowledge/decisions.md`.
