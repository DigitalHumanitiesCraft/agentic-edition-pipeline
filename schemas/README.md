# schemas/

Schema files used by the pipeline for TEI generation and validation.

## Files

| File | Role | License |
|---|---|---|
| `dtabf.json` | Machine-readable **encoding profile**: a JSON abstraction of DTABf structural constraints (allowed parent-child relationships, attributes, self-closing behaviour per element). It is injected into the LLM annotation prompt (step 5) and defines the element inventory the model may use, following the teiCrafter pattern. It is **not** a validation schema, and it does not contain modelling decisions — which source phenomenon maps to which element is defined in `knowledge/04_TEI_MAPPING.md`. | CC-BY 4.0 (part of this template) |
| `tei_all.rng` | Official TEI All RelaxNG schema, the permissive full schema of the TEI guidelines. This is the template's default validation target (`VALIDATION_SCHEMA` in `pipeline/config.py`). | CC BY 4.0, TEI Consortium |
| `basisformat.rng` | Official DTA-Basisformat RelaxNG schema for prints, generated from the DTABf ODD source. Available as a stricter alternative target; see the strictness caveat below. | CC BY-SA 3.0 DE, Deutsches Textarchiv (BBAW) |

Source of `tei_all.rng`: https://tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng.

Source of `basisformat.rng`: https://www.deutschestextarchiv.de/basisformat.rng (schema documentation at https://www.deutschestextarchiv.de/doku/basisformat/schema.html). For manuscript corpora, the manuscript variant is available at https://www.deutschestextarchiv.de/basisformat_ms.rng; download it into this directory and validate against it instead. A Schematron rule set exists at https://www.deutschestextarchiv.de/basisformat.sch.

## How validation runs

The pipeline validates generated TEI at two levels.

**Built-in (step 5, automatic).** `pipeline/05_annotate_tei.py` checks every generated file for XML well-formedness, presence of required TEI elements (`teiHeader`, `fileDesc`, `text`, `body`), and plaintext preservation (word-set similarity between transcription and TEI body). Results go to `results/reports/{object_id}_validation.json`.

**RelaxNG (manual, before publication).** Full conformance is checked against the schema the fork has chosen as its validation target (`VALIDATION_SCHEMA` in `pipeline/config.py`, see below):

```
python pipeline/validate_schema.py                        # all results/tei/*.xml
python pipeline/validate_schema.py --schema schemas/basisformat.rng
```

[Jing](https://relaxng.org/jclark/jing.html) works as well: `jing schemas/tei_all.rng results/tei/*.xml`. Run the RelaxNG check at the step 5 checkpoint on the sample files, and on the full corpus before enabling GitHub Pages.

Note that the deterministic TEI generator produces minimal DTABf-oriented structures; LLM-enriched annotations in particular must be RelaxNG-checked, since post-generation validation is the template's chosen quality mechanism.

## Choosing a validation schema

The validation target is a per-project decision (ADR-005 in `knowledge/decisions.md`). The template defaults to TEI All, because that is the target the generated TEI satisfies without adaptation; a fork that constrains its encoding more tightly points `VALIDATION_SCHEMA` in `pipeline/config.py` somewhere else. This directory can hold any of the following, depending on how strictly your project constrains its encoding.

- **TEI All** (`tei_all.rng`, from the [TEI release](https://tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng)): the permissive full schema, shipped and configured as the default. It accepts almost any valid TEI and therefore does not check project-specific conventions. The deterministic generator's output validates against it out of the box (verified against the fork test-run corpora, 2026-07-18, and pinned by `tests/test_validate_schema.py`).
- **DTA-Basisformat (DTABf)**: the restrictive profile for historical German-language texts (see above; a manuscript variant exists). Strictness caveat: the deterministic generator's header does not pass strict DTABf as shipped — the failures are pre-existing header structures (`title` attributes, `projectDesc`, `revisionDesc`, `facsimile` position), not the body markup. A fork that declares strict DTABf as its target must adapt the header template in `pipeline/05_annotate_tei.py` first.
- **A custom project schema** (your own RNG): use it when your project maintains its own encoding profile.
- **An ODD** (One Document Does it all): the TEI-standard way to define your own profile in a single source, from which the RNG and its documentation are generated, using [Roma](https://roma.tei-c.org/) or `oddbyexample`. Keep the ODD next to the generated RNG in this directory.

Whichever schema you choose, the encoding-profile JSON (`dtabf.json` or its replacement) must describe the **same element set** as the validation schema. If the two diverge, the model generates against one profile while validation checks another, and every run produces spurious errors.

## Using a different schema in a fork

See [SETUP.md, section 6 (Schema adaptation)](../SETUP.md#6-schema-adaptation). In short: put your profile's schema into this directory and point `VALIDATION_SCHEMA` in `pipeline/config.py` at it, adjust or replace `dtabf.json` so the encoding profile matches the new element set, update the modelling decisions in `knowledge/04_TEI_MAPPING.md`, and record the decision in `knowledge/decisions.md`.
