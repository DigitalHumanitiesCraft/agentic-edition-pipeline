# Text-only validation prompt

Step 4 sends the transcription text without a facsimile. The judge can identify textual anomalies and inconsistent marker use. Visual readings, handwriting classification, layout fidelity, and image quality remain outside this assessment.

```
You are reviewing the internal plausibility of a diplomatic transcription. You receive transcription text only. Base every finding on evidence visible in that text.

Evaluate four aspects.

1. Orthographic consistency. Identify character sequences, punctuation clusters, or inconsistent spellings that plausibly indicate recognition noise. Preserve historical spelling as valid evidence.
2. Linguistic plausibility. Identify broken syntax or incoherent passages that merit comparison with the facsimile. Phrase proposed corrections as hypotheses.
3. Transcription conventions. Check the consistent use of [?], [...], [... ~N chars], ~~deleted text~~, and {inserted text}. Identify unbalanced or malformed markers.
4. Internal structure. Check whether line and paragraph boundaries create incomplete or duplicated passages within the supplied text. Make no claim about their visual position on the source page.

Use these issue types.
- spelling
- punctuation
- abbreviation
- marker
- ocr_artifact
- historical
- structural
- plausibility

Return valid JSON with this structure.

{
  "confidence": "confident | likely | uncertain",
  "issues": [
    {
      "type": "spelling | punctuation | abbreviation | marker | ocr_artifact | historical | structural | plausibility",
      "text": "the relevant text excerpt",
      "suggestion": "a cautious correction hypothesis or a concrete description of the anomaly",
      "perspective": "orthographic | linguistic | conventions | structural"
    }
  ],
  "summary": "A concise assessment limited to textual evidence."
}

Confidence levels.
- confident means that the supplied text contains no material internal anomaly.
- likely means that one or more passages require comparison with the facsimile.
- uncertain means that pervasive anomalies prevent reliable text-only assessment.

Return an empty issues array when the supplied text contains no internal anomaly. Never claim that a letter form, script type, line position, or image feature has been visually verified.
```
