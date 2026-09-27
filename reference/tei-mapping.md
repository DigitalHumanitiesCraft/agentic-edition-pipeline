# TEI base mapping

Step 5 (`pipeline/05_annotate_tei.py`) generates TEI deterministically from the validated file of the [data contract](data-contract.md) and the project fields of `knowledge/01_PROJECT.md`. No model runs in this step. The mapping below is fixed in the code of every fork. An edition records its schema choice, additional structures and annotation rules in its [TEI mapping decisions](../knowledge/04_TEI_MAPPING.md).

## Header

The header carries only declared values. A field without a value leaves its element out, except where the table names a replacement.

| Source | TEI element | Rule |
|---|---|---|
| `metadata.title` | `titleStmt/title` | `object_id` when the title is missing or empty |
| Editor in `01_PROJECT.md` | `titleStmt/editor` | omitted when missing |
| Institution in `01_PROJECT.md` | `publicationStmt/publisher` | without it `publicationStmt` holds `<p>No publisher is declared in knowledge/01_PROJECT.md.</p>` |
| License in `01_PROJECT.md` | `publicationStmt/availability/licence` | after a publisher only, otherwise a second `<p>Licence: …</p>` |
| `metadata.repository` | `msIdentifier/repository` | omitted when missing |
| `metadata.signature` | `msIdentifier/idno[@type='shelfmark']` | omitted when missing |
| `object_id` | `msIdentifier/idno[@type='object-id']` | always |
| `metadata.date` | `history/origin/origDate` | `@when` only for a semantically valid `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, free datings stay escaped element text |
| `metadata.language`, else Language in `01_PROJECT.md` | `profileDesc/langUsage/language[@ident]` | the value becomes `@ident` and element text, `profileDesc` is omitted when neither declares a language |
| least mature page review state | `revisionDesc/@status` and `change/@status` | order `machine_unreviewed`, `in_review`, `human_verified`, `accepted` |
| step-4 timestamp and provenance | `revisionDesc/change` | `@when` is the timestamp of the validated input, the text names transcription provenance, `validation_state_hash` and `project_config_hash` |
| `metadata.image_urls` | `facsimile/graphic[@url]` | one `graphic` with `xml:id="facs_N"` per declared page |

`validation_state_hash` hashes the validated file and `project_config_hash` the project fields read from `01_PROJECT.md`. The step-5 report carries the same two values. Identical validated input and project configuration produce identical TEI bytes.

## Body

| Source | TEI element | Rule |
|---|---|---|
| paragraph | `<p>` | a blank line separates paragraphs |
| page | `<pb/>` | `@n` is the page number, `@facs` points to `#facs_N` for a remote image or to `../images/{object_id}/{filename}` for a local one |
| line break | `<lb/>` | kept unless the Edition type in `01_PROJECT.md` contains `normalis` or `normaliz` in any letter case, in which case lines of a paragraph are joined with a space |
| `page_type: foreign_text` | `<note type="foreign">` | one note per paragraph |
| `page_type: gate_low_resolution` | `<note type="gate" subtype="low_resolution">` | the page notes or a fixed reason as text, a structure-only transcription follows |
| empty page without `page_type` | `<note type="empty">` | a declared `blank` page gets only `<pb/>` |
| `foreign_paragraphs` | `<note type="foreign">` | 0-based paragraph index on a mixed page |
| `~~text~~` | `<del>text</del>` | marker reconstructed exactly in the round trip |
| `{text}` | `<add>text</add>` | marker reconstructed exactly in the round trip |
| `word[?]` | `<unclear>word</unclear>` | a `[?]` without a preceding word stays literal text |
| `[...]`, `[... ~N chars]` | `<gap reason="illegible"/>` | the estimate becomes `@quantity` with `@unit="character"` |

`pipeline/markers.py` defines the marker syntax once for the prompt, step 4 and step 5. Further structures are specified in the edition's TEI mapping decisions and then implemented in the deterministic renderer or in a separate, documented stage. An entry in a Markdown table alone changes no output.

## Stored corrections

The base path maps `pages[].edits` to `revisionDesc/change[@type='transcription-correction']`. `@when` names the time, `@subtype` the declared role (`human` or `agent`), `@who` points to a `respStmt` in `titleStmt` with the name of the actor, and `@target` points to the affected page break. The reason of the change is the element text. Before and after values stay in the canonical JSON. Unsaved proposals produce no TEI events. A new derivation and a scholarly release keep separate meanings.

## Output, checks and overwrite guard

Step 5 writes the TEI to `results/tei/{object_id}.xml` and its report to `results/reports/{object_id}_validation.json`. No second working copy exists. Schema validation, step 6, the local review server and the publication check read `results/tei/`.

Before a write, every generated file must be well-formed, contain `teiHeader`, `fileDesc`, `text` and `body`, and reproduce every page's ordered text after the markers are reconstructed and layout whitespace is normalised. Missing pages, reordered text and lost repetitions block the write. `--validate-only` generates and checks without writing TEI.

The report records `validation_state_hash`, `project_config_hash` and, in `_meta.tei_sha256`, the SHA-256 of the TEI bytes step 5 last wrote. An existing TEI file with exactly the generated bytes is skipped. An existing file whose bytes differ from the recorded digest, or one without a recorded digest, was edited or enriched elsewhere, and step 5 replaces it only with `--force`. A regular re-run after a text change therefore needs no `--force` in step 5. RelaxNG validation against `VALIDATION_SCHEMA` is a separate check (`pipeline/validate_schema.py`, [schema documentation](../schemas/README.md)).

## Claims of semantic annotation

A semantic annotation makes distinct claims, and each needs its own evidence.

| Claim | Required evidence |
|---|---|
| Mention | exact text and the correct location |
| Entity identity | justified merging of different name forms |
| Role | attested function in the document context |
| Relation | traceable connection between the entities involved |
| Authority link | matching external record and documented disambiguation |

Several designations of a work can refer to the same entity. Document-local IDs allow no statement about the number of distinct persons or works in the corpus. A formally valid anchor confirms neither identity nor role. A format example such as `<persName ref="GND-URI">` presupposes a checked identity and an attested authority link in the Gemeinsame Normdatei (GND). It is no instruction to assign identifiers automatically. Date normalisation and work identification need their own rules.

Tables, columns and typographic groups can carry relations between persons, works and functions. Where the edition needs them, these layout relations are recorded before a lossy linearisation. The base renderer does not reconstruct them.

## Maturity of a TEI file

A generated TEI document is a candidate. Well-formedness, RelaxNG conformance and text preservation are technical checks. Only a state that was reviewed accordingly and explicitly confirmed counts as scholarly accepted, and the Pages workflow requires `revisionDesc/@status="accepted"`. Naming a file or folder `final` confirms no maturity.

After text corrections, text anchors and dependent findings are checked again. The [local review contract](local-review.md) describes how the correction path protects enriched TEI.
