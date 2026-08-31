# Transcription prompt profiles

Create one Markdown file per material class selected by `prompt_profile` in `data/sources/manifest.json`. The filename is the profile key. A document using `"prompt_profile": "correspondence"` therefore requires `correspondence.md` in this directory.

A profile contains only instructions that supplement the base rules in `../transcription.md`. It should describe the expected layout, source-specific phenomena, and transcription priorities. Changes that can alter output receive a new documented prompt state and are evaluated on the same fixed sample before a corpus run.
