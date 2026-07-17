# schemas/

Schema files used by the pipeline for TEI generation and validation.

## Files

| File | Role | License |
|---|---|---|
| `dtabf.json` | Machine-readable **encoding profile**: a JSON abstraction of DTABf structural constraints (allowed parent-child relationships, attributes, self-closing behaviour per element). It is injected into the LLM annotation prompt (step 5) and defines the element inventory the model may use, following the teiCrafter pattern. It is **not** a validation schema, and it does not contain modelling decisions — which source phenomenon maps to which element is defined in `knowledge/04_TEI_MAPPING.md`. | CC-BY 4.0 (part of this template) |
| `basisformat.rng` | Official DTA-Basisformat RelaxNG schema for prints, generated from the DTABf ODD source. Used for full schema validation of generated TEI-XML. | CC BY-SA 3.0 DE, Deutsches Textarchiv (BBAW) |

Source of `basisformat.rng`: https://www.deutschestextarchiv.de/basisformat.rng (schema documentation at https://www.deutschestextarchiv.de/doku/basisformat/schema.html). For manuscript corpora, the manuscript variant is available at https://www.deutschestextarchiv.de/basisformat_ms.rng; download it into this directory and validate against it instead. A Schematron rule set exists at https://www.deutschestextarchiv.de/basisformat.sch.

## How validation runs

The pipeline validates generated TEI at two levels.

**Built-in (step 5, automatic).** `pipeline/05_annotate_tei.py` checks every generated file for XML well-formedness, presence of required TEI elements (`teiHeader`, `fileDesc`, `text`, `body`), and plaintext preservation (word-set similarity between transcription and TEI body). Results go to `results/reports/{object_id}_validation.json`.

**RelaxNG (manual, before publication).** Full DTABf conformance is checked against `basisformat.rng`. Run it with lxml:

```
python -c "
from lxml import etree
rng = etree.RelaxNG(etree.parse('schemas/basisformat.rng'))
doc = etree.parse('results/tei/OBJECT_ID.xml')
print('valid' if rng.validate(doc) else rng.error_log)
"
```

or with [Jing](https://relaxng.org/jclark/jing.html): `jing schemas/basisformat.rng results/tei/*.xml`. Run the RelaxNG check at the step 5 checkpoint on the sample files, and on the full corpus before enabling GitHub Pages.

Note that the deterministic TEI generator produces minimal DTABf-oriented structures; LLM-enriched annotations in particular must be RelaxNG-checked, since post-generation validation is the template's chosen quality mechanism.

## Choosing a validation schema

This directory can hold any of the following, depending on how strictly your project constrains its encoding.

- **TEI All** (`tei_all.rng`, from the [TEI release](https://tei-c.org/release/xml/tei/custom/schema/relaxng/tei_all.rng)): the permissive full schema. Good for getting started; it accepts almost any valid TEI and therefore does not check project-specific conventions.
- **DTA-Basisformat (DTABf)**: the restrictive profile for historical German-language texts, and the default of this template (see above; a manuscript variant exists).
- **A custom project schema** (your own RNG): use it when your project maintains its own encoding profile.
- **An ODD** (One Document Does it all): the TEI-standard way to define your own profile in a single source, from which the RNG and its documentation are generated, using [Roma](https://roma.tei-c.org/) or `oddbyexample`. Keep the ODD next to the generated RNG in this directory.

Whichever schema you choose, the encoding-profile JSON (`dtabf.json` or its replacement) must describe the **same element set** as the validation schema. If the two diverge, the model generates against one profile while validation checks another, and every run produces spurious errors.

## Using a different schema in a fork

See [SETUP.md, section 6 (Schema adaptation)](../SETUP.md#6-schema-adaptation). In short: replace the RNG with your profile's schema, adjust or replace `dtabf.json` so the encoding profile matches the new element set, update the modelling decisions in `knowledge/04_TEI_MAPPING.md`, and record the decision in `knowledge/06_DECISIONS.md`.
