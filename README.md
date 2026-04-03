# Agentic Edition Pipeline

Forkable template for AI-assisted digital scholarly editions. From digitised source to TEI-XML and published frontend on GitHub Pages.

Created by [Christopher Pollin](https://github.com/chpollin) ([Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft)). Built with [Claude Code](https://claude.ai/code) using the [Promptotyping](https://doi.org/10.58079/15t4s) methodology.

## What this is

A project folder with pre-built Python scripts, prompt templates, a knowledge base, and a `CLAUDE.md` that tells Claude Code what to do. Not a GUI tool, not a framework, not a SaaS product.

The template generalises four production-grade edition projects into a reusable pipeline that goes from PDF/image scans to valid TEI-XML (DTA-Basisformat) and a published static frontend.

## How to use

### Prerequisites

- Python 3.10+
- [Claude Code](https://claude.ai/code) (Anthropic's agentic coding tool)
- An API key for at least one LLM provider (Gemini, OpenAI, Anthropic, or a local Ollama instance)

### Step-by-step

1. **Fork** this repository on GitHub
2. **Clone** your fork locally
3. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```
4. **Set up API keys** by copying `.env.example` to `.env` and adding your keys
   ```
   cp .env.example .env
   ```
5. **Place your source material** in `data/sources/`
   - PDFs go into `data/sources/pdf/`
   - Images go into `data/sources/images/`
   - Existing transcriptions go into `data/sources/text/`
6. **Start Claude Code** in the project directory. It reads `CLAUDE.md` and asks a series of questions about your edition project (data types, edition type, research question, editorial guidelines). Based on your answers, it fills in the knowledge documents and runs the pipeline step by step.

Each pipeline step has a verification checkpoint where you review the results before proceeding. Steps 4 (validation) and 5 (TEI annotation) work in deterministic mode without API keys. LLM-based features are optional enhancements.

### Local preview

At any checkpoint, preview the edition in your browser:
```
cd pipeline
python 06_build_frontend.py --serve
```
This starts a local server at `http://localhost:8080` serving the same files that will be published on GitHub Pages.

### Publishing

Enable GitHub Pages in your repository settings (source: deploy from branch, branch: main, folder: /docs). The included workflow at `.github/workflows/pages.yml` handles deployment automatically on push to main.

## Pipeline overview

```
01 Extract Images    PDF → page images (PyMuPDF)
02 Analyze           Corpus inventory and classification
   ── verify inventory ──
03 Transcribe        OCR/HTR via LLM (sample first, then full corpus)
   ── verify transcription quality ──
04 Validate          Deterministic rules + optional LLM judge
   ── review quality summary ──
05 Annotate TEI      Deterministic TEI generation + optional LLM annotation
   ── preview edition, verify TEI ──
5b Design            Requirements engineering (epics, user stories, UI components)
   ── verify design ──
06 Build Frontend    Generate catalog and viewer data for static site
   ── verify published edition ──
```

## Repository structure

```
agentic-edition-pipeline/
├── CLAUDE.md                    # Operational protocol for Claude Code
├── knowledge/                   # Promptotyping knowledge base (Obsidian-compatible)
│   ├── 00_INDEX.md              # Navigation, RIDE self-assessment checklist
│   ├── 01_PROJECT.md            # Project metadata, research question
│   ├── 02_DATA.md               # Corpus description, source types, inventory
│   ├── 03_CONTEXT.md            # Editorial guidelines, transcription conventions
│   ├── 04_TEI_MAPPING.md        # Source structure → TEI element mapping
│   ├── 05_DESIGN.md             # Epics, user stories, UI components, wireframes
│   ├── 06_DECISIONS.md          # Architecture Decision Records
│   └── 07_JOURNAL.md            # Development journal
├── pipeline/                    # Python scripts (6 steps + infrastructure)
│   ├── config.py                # Paths, API config, shared utilities
│   ├── llm.py                   # Multi-provider LLM (Gemini, OpenAI, Anthropic, Ollama)
│   ├── 01_extract_images.py     # PDF → page images
│   ├── 02_analyze.py            # Corpus inventory
│   ├── 03_transcribe.py         # OCR/HTR with chunking and quality signals
│   ├── 04_validate.py           # Hybrid validation (rules + LLM judge)
│   ├── 05_annotate_tei.py       # TEI-XML generation with validation
│   ├── 06_build_frontend.py     # TEI → static site data + local server
│   └── prompts/                 # Prompt templates (transcription, validation, annotation)
├── schemas/dtabf.json           # DTA-Basisformat JSON Schema (57 elements)
├── docs/                        # Static frontend (GitHub Pages root)
├── data/sources/                # Input data (your source material)
├── data/processed/              # Intermediate results (generated)
└── results/tei/                 # Final TEI-XML files
```

## Methodology

**Promptotyping** (Pollin 2026a) is a context engineering method for iterative development of research tools through structured LLM interaction. Four phases: Preparation, Exploration, Distillation, Implementation. The `knowledge/` documents are the Promptotyping Documents that steer Claude Code's behaviour.

**Critical Expert in the Loop.** Every processing step produces intermediate results in established formats (JSON, TEI-XML) that can be verified through schema validation, human inspection, and LLM-as-a-Judge. Defined checkpoints require explicit approval before proceeding.

**Epistemic Infrastructure.** The ensemble of mechanisms that make LLM-generated results verifiable, curatable, and documentable. Provenance metadata in every generated file. Architecture Decision Records. Session journal. Quality signals at every pipeline stage.

## Reference projects

This template distils knowledge and code from four production-grade repositories. Each has a `knowledge/` folder with synthesized project knowledge.

| Repository | Corpus | Strength |
|---|---|---|
| [zbz-ocr-tei](https://github.com/chpollin/zbz-ocr-tei) | 286 docs, 4152 pages (Jeanne Hersch) | End-to-end PDF→TEI, epistemic infrastructure |
| [szd-htr-ocr-pipeline](https://github.com/chpollin/szd-htr-ocr-pipeline) | 2107 objects, 18719 scans (Stefan Zweig) | Prompt grouping, quality signals, live viewer |
| [co-ocr-htr](https://github.com/DigitalHumanitiesCraft/co-ocr-htr) | Browser-based workbench | Multi-provider LLM, hybrid validation, PAGE-XML |
| [teiCrafter](https://github.com/DigitalHumanitiesCraft/teiCrafter) | Browser-based annotation | TEI prompt architecture, schema guidance |

## Quality framework

Every forked edition structurally addresses the [IDE criteria for reviewing digital scholarly editions](https://www.i-d-e.de/publikationen/weitereschriften/criteria-version-1-1) (v1.1), [tools](https://www.i-d-e.de/publikationen/weitereschriften/criteria-tools-version-1) (v1), and [text collections](https://www.i-d-e.de/publikationen/weitereschriften/criteria-text-collections-version-1-0) (v1.0). See `knowledge/00_INDEX.md` for the RIDE self-assessment checklist.

## Citation

```bibtex
@software{pollin_agentic_edition_2026,
  author = {Pollin, Christopher},
  title = {Agentic Edition Pipeline},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/DigitalHumanitiesCraft/agentic-edition-pipeline},
  note = {Forkable template for AI-assisted digital scholarly editions}
}
```

## License

CC-BY 4.0. See [LICENSE](LICENSE).

## Author

**Christopher Pollin** — [Digital Humanities Craft](https://github.com/DigitalHumanitiesCraft)

Research context: Pollin, Christopher / Kreyenbühl, Elias: "Agentenbasierte Editionsworkflows und epistemische Infrastrukturen. Ein Experiment zur digitalen Edition der Schriften von Jeanne Hersch." 2026.
