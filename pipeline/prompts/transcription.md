# Transcription Prompt Template

This prompt operates in four layers. `pipeline/03_transcribe.py` assembles them at runtime and records the layer list and combined prompt hash in the transcription metadata.

---

## Layer 1 — System Prompt

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

Mixed pages. When a content page contains both text of the edited object and text of another author (e.g. the end of one article and the start of the next), transcribe everything, separate the parts into their own paragraphs (blank line between paragraphs), and list the 0-based indices of the foreign paragraphs in a foreign_paragraphs field on that page.

Return your result as a JSON object with the following structure. This is the pipeline data contract: pages at the top level, the page text under the key "transcription" (see knowledge/08_DATA_CONTRACT.md).

{
  "pages": [
    {
      "page": 1,
      "transcription": "...",
      "notes": "...",
      "page_type": "blank | gate_low_resolution | foreign_text (omit for normal content pages)",
      "foreign_paragraphs": [2]
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

---

## Layer 2 — Document-Type Instructions

The source manifest selects a profile with `prompt_profile`. Step 3 loads `pipeline/prompts/profiles/{prompt_profile}.md` and appends it to the base prompt. The profile addresses layout conventions, expected structural elements, and transcription priorities specific to the material.

The following categories from the szd-htr pipeline serve as reference examples. They are not hardcoded into this template. Each project defines its own categories based on its corpus.

- **Handschrift** — Handwritten manuscripts. Focus on letter-form disambiguation and line segmentation. Note changes in hand if multiple writers are present.
- **Typoskript** — Typewritten documents. Watch for manual corrections, overstrikes, and interlinear additions made by hand on a typed page.
- **Formular** — Printed forms filled in by hand. Distinguish pre-printed labels from handwritten entries. Transcribe both, marking pre-printed text in notes.
- **Kurztext** — Short texts such as postcards, labels, or catalogue entries. Transcribe the full text even if very brief. Note layout elements (borders, stamps).
- **Tabellarisch** — Tabular layouts including lists, inventories, and ledger pages. Preserve column alignment using whitespace or note the table structure.
- **Korrekturfahne** — Proof sheets with correction marks. Transcribe the base printed text and mark all correction annotations as insertions or notes.
- **Konvolut** — Bundles containing mixed document types. Each page may require a different transcription strategy. Note type changes between pages.
- **Zeitungsausschnitt** — Newspaper clippings. Transcribe the article text. Note headline hierarchy, column breaks, and any handwritten annotations on the clipping.
- **Korrespondenz** — Letters and correspondence. Note sender, recipient, date, and salutation structure. Transcribe envelope text separately if present.

The categories above are design references. A fork creates only the profile files supported by its corpus and benchmark.

---

## Layer 3 — Document Context

Step 3 appends the available document metadata from `data/inventory.json` at runtime.

```
This document has the following metadata.
- Title: {title}
- Signature / Identifier: {signature}
- Date: {date}
- Language: {language}
- Object type: {object_type}
- Extent: {extent}
```

The context block is appended after the document-type instructions so the model has full information before processing the image.

---

## Layer 4 — Per-Object Overrides

For individual documents that require special handling, step 3 checks for an override file at `pipeline/prompts/objects/{object_id}.md`. If the file exists, its contents supplement the document-type instructions from Layer 2.

Override files are optional. They exist for edge cases such as documents in unusual scripts, documents with severe damage, or documents where a previous transcription attempt produced poor results and the prompt needs targeted adjustment.

The applied override path appears in `_meta.prompt_layers`. The combined `_meta.prompt_hash` binds the model output to the exact assembled prompt.
