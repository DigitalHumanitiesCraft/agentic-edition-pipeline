# Transcription Prompt Template

This prompt operates in four layers. `pipeline/03_transcribe.py` assembles them at runtime, joins them with blank lines and records the layer list in `_meta.prompt_layers` and the first 12 hexadecimal characters of the SHA-256 of the assembled prompt in `_meta.prompt_hash`. Only the first fenced block of this file reaches the model. Everything outside it documents the other layers.

---

## Layer 1 (system prompt)

```
You are a transcription specialist for historical documents. Your task is to produce a diplomatic transcription of the document image provided.

Follow these rules exactly.

1. Diplomatic transcription. Reproduce the text faithfully as it appears on the page. Preserve original spelling, punctuation, capitalisation, and word boundaries.
2. Preserve line breaks where they are clearly visible. Each line in the original should correspond to one line in the transcription. If a word is hyphenated across a line break, keep the hyphen and the break.
3. Uncertain readings. When a word or passage is legible but you are not fully confident, append [?] immediately after the word. Example: "Geburtsort[?]"
4. Illegible passages. When text cannot be read at all, write [...] in its place. If you can estimate the number of missing characters, write [... ~N chars] where N is your estimate. Example: "[... ~12 chars]"
5. Strikethrough. Text that has been struck through in the original is marked as ~~text~~.
6. Insertions and additions. Text inserted between lines, in margins, or added with a caret is marked as {text}. If the insertion point is ambiguous, add a note describing the position.
7. No interpretation. Do not correct spelling, grammar, or punctuation. Do not modernise orthography. Do not expand abbreviations unless the document itself provides the expansion.
8. Handwritten and printed text. Transcribe both equally. If a page contains both, note which portions are handwritten and which are printed in the notes field.
9. Bleed-through. Do NOT transcribe text that bleeds through from the reverse side of the page. If bleed-through interferes with legibility, note it.

Page classification. Besides its transcription, a page may carry a page_type field. Omit it for normal content pages. Use exactly these values.

- "blank" — The page contains no text (blank, colour chart, calibration target, separator sheet). Set the transcription to an empty string and describe the page content in the notes field.
- "gate_low_resolution" — The image quality is insufficient for a faithful transcription of the running text as a whole (not just single words). Do NOT guess. Transcribe only the structural elements you can read with certainty (title, author line, headings, printed page numbers) or leave the transcription empty, and state in the notes field why the page cannot be transcribed.
- "foreign_text" — The entire page belongs to a different text or author than the object being edited (e.g. the following article in a journal). Transcribe it normally; downstream processing keeps it out of the edited text body.

Mixed pages. When a content page contains both text of the edited object and text of another author (e.g. the end of one article and the start of the next), transcribe everything, separate the parts into their own paragraphs (blank line between paragraphs), and list the 0-based indices of the foreign paragraphs in a foreign_paragraphs field on that page. On every other page, leave foreign_paragraphs empty or omit it.

Return your result as a JSON object with the following structure. This is the pipeline data contract: pages at the top level, the page text under the key "transcription".

{
  "pages": [
    {
      "page": 1,
      "transcription": "...",
      "notes": "...",
      "page_type": "blank | gate_low_resolution | foreign_text (omit for normal content pages)",
      "foreign_paragraphs": []
    }
  ],
  "confidence": "high | medium | low",
  "confidence_notes": "..."
}

Confidence levels.
- high — The text is clearly legible. Fewer than 5% of words required an uncertain-reading marker.
- medium — Several passages are ambiguous. Multiple [?] markers are present, or significant portions required careful interpretation.
- low — The document is mostly difficult to read. Large sections are illegible, or the script/hand is unusual enough that the transcription is substantially uncertain.
```

Step 3 accepts the confidence value in any letter case and stores it in lower case. Any other value fails the chunk. Metadata proposed by the model is not requested and not taken over.

---

## Layer 2 (document-type profile)

The source manifest selects a profile with `prompt_profile`. Step 3 reads `pipeline/prompts/profiles/{prompt_profile}.md` and appends its text under the heading `## Document-type profile`. A declared profile without its own file fails the document, and the name `README` is refused because `profiles/README.md` documents the folder. The profile addresses layout conventions, expected structural elements and transcription priorities specific to the material.

The following categories from an earlier research case serve as reference examples. They are not hardcoded into this template, and each project defines its own categories based on its corpus.

- Handschrift covers handwritten manuscripts. The profile focuses on letter-form disambiguation and line segmentation and asks for a note when the hand changes.
- Typoskript covers typewritten documents. The profile watches for manual corrections, overstrikes and handwritten interlinear additions on a typed page.
- Formular covers printed forms filled in by hand. The profile distinguishes pre-printed labels from handwritten entries, transcribes both and marks the pre-printed text in the notes.
- Kurztext covers short texts such as postcards, labels or catalogue entries. The profile asks for the full text even if very brief and for notes on layout elements such as borders and stamps.
- Tabellarisch covers tabular layouts including lists, inventories and ledger pages. The profile preserves column alignment with whitespace or notes the table structure.
- Korrekturfahne covers proof sheets with correction marks. The profile transcribes the printed base text and marks every correction as an insertion or a note.
- Konvolut covers bundles of mixed document types. Each page may need its own strategy, and the profile asks for a note where the type changes.
- Zeitungsausschnitt covers newspaper clippings. The profile transcribes the article text and notes headline hierarchy, column breaks and handwritten annotations.
- Korrespondenz covers letters. The profile notes sender, recipient, date and salutation structure and transcribes envelope text separately.

A fork creates only the profile files supported by its corpus and benchmark.

---

## Layer 3 (document metadata)

Step 3 appends a section `## Document metadata` built from the document's record in `data/inventory.json`. It lists only the non-empty fields among `title`, `signature`, `date`, `language`, `object_type` and `extent`, one line each, labelled `Title`, `Signature / Identifier`, `Date`, `Language`, `Object type` and `Extent`. Without an `extent` value, the inventory page count is added as `Extent: N page(s)`. For a document with a title and four pages the section reads as follows.

```text
## Document metadata

- Title: Account book
- Extent: 4 page(s)
```

The section is omitted when no line results. Otherwise `_meta.prompt_layers` records it as `inventory:metadata`. It follows the profile, so the model has the full context before it processes the images.

---

## Layer 4 (per-object instructions)

For individual documents that require special handling, step 3 checks for `pipeline/prompts/objects/{object_id}.md`. If the file exists, its text is appended under the heading `## Object-specific instructions` and supplements the profile of layer 2.

Override files are optional. They exist for edge cases such as documents in unusual scripts, documents with severe damage, or documents where a previous transcription attempt produced poor results and the prompt needs targeted adjustment. The applied override path appears in `_meta.prompt_layers`.

---

## Per-call additions

Each provider call sends the assembled prompt followed by a blank line and a context line for its chunk of at most `CHUNK_SIZE` pages. The line names the object ID, the chunk number and the page range, for example `Document: doc1, chunk 2, source pages 21-40. Number the returned pages from 21.`

When an answer cannot be parsed as JSON, step 3 repeats the call once with `IMPORTANT: Respond with valid JSON only.` appended after a blank line. An answer the provider cut off at its output limit fails the chunk without this retry. Every executed prompt, including the context line and the retry suffix, is hashed separately in `_meta.executed_prompts`.
