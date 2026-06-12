# Agentic Edition Pipeline — Wissensdokument

Stand 2026-04-03. Dieses Dokument konsolidiert das gesamte Projektwissen für Claude Code. Es dient als Einstiegspunkt, um das Repository-Template `agentic-edition-pipeline` aufzubauen, zu befüllen und funktionsfähig zu machen.

---

## 1. Was ist das Projekt?

Ein forkbares GitHub-Repository-Template für LLM-gestützte digitale Editionen. Der Weg geht vom Digitalisat (PDF, Bild) bis zum validen TEI-XML und einem publizierten Frontend auf GitHub Pages. Claude Code ist der primäre Operator, der Mensch ist *Critical Expert in the Loop*.

Das Template ist die Generalisierung von vier bestehenden Projekten, die alle mit der Promptotyping-Methodik und Claude Code entwickelt wurden. Es ist kein GUI-Tool, kein Framework, kein SaaS-Produkt. Es ist ein Projektordner mit vorgefertigten Python-Skripten, Prompt-Templates, einer Wissensbasis und einer CLAUDE.md, die Claude Code sagt, was zu tun ist.

**Repository-Name.** `agentic-edition-pipeline`

**Beschreibung (GitHub).** Forkable template for AI-assisted digital scholarly editions. From digitised source to TEI-XML and published frontend. Promptotyping methodology, Claude Code as operator, human as Critical Expert in the Loop.

**Lizenz.** CC-BY 4.0

**Organisation.** DigitalHumanitiesCraft

---

## 2. Herkunft und Quellprojekte

Das Template destilliert Wissen und Code aus vier GitHub-Repositories, die alle funktionsfähig sind und reale Editionsprojekte umsetzen. Claude Code soll diese Repos als Referenzimplementierungen behandeln, nicht als Abhängigkeiten. Code wird adaptiert, nicht importiert.

### 2.1 zbz-ocr-tei

- **Repository.** https://github.com/chpollin/zbz-ocr-tei
- **Gegenstand.** LLM-gestützte OCR und TEI-Auszeichnung für die Schriften von Jeanne Hersch (Zentralbibliothek Zürich)
- **Korpus.** 286 PDF-Dokumente, 4152 Seiten, Sprachen Deutsch/Französisch/Englisch, gedruckte Texte
- **Pipeline.** PDF → OCR → Layoutanalyse → Entitätserkennung → TEI-XML (DTA-Basisformat)
- **TEI-Schema.** DTA-Basisformat (DTABf)
- **Besonderheiten.** Mehrere aufeinander aufbauende Pipelines, Multi-Agenten-System für Code-Generierung, Frontend mit Kuratierungsfunktionen, Evaluation gegen Ground Truth geplant
- **Relevanz für Template.** Vollständigstes End-to-End-Beispiel, zeigt den gesamten Weg vom PDF bis zur publizierten Edition. Epistemische Infrastruktur als Konzept. Zwischenformate und Validierungsroutinen an jeder Stufe.
- **Ordnerstruktur.** `knowledge/` (Wissensdokumente), `data/` (Quelldaten), `pipeline/` (Python-Skripte), `docs/` (GitHub Pages Frontend), `schemas/`, `results/`
- **Akademischer Kontext.** Eingereicht als Beitrag "Agentenbasierte Editionsworkflows und epistemische Infrastrukturen" (Pollin/Kreyenbühl), siehe Abschnitt 7

### 2.2 szd-htr-ocr-pipeline

- **Repository.** https://github.com/chpollin/szd-htr-ocr-pipeline
- **Gegenstand.** VLM-basierte HTR/OCR für den Nachlass Stefan Zweig (Literaturarchiv Salzburg)
- **Korpus.** 2.107 digitalisierte Objekte, 18.719 Faksimile-Scans (~23 GB), 4 Sammlungen (Lebensdokumente, Werke, Aufsatzablage, Korrespondenzen)
- **Pipeline.** JPEG (von GAMS) → Kontextauflösung via TEI-Metadaten → VLM-Transkription (Gemini 3.1 Flash Lite) → Quality Signals → Verifikation (Cross-Model-Consensus)
- **Besonderheiten.**
  - 4-Layer-Prompt-System mit automatischer Prompt-Gruppenzuweisung (9 Kategorien, von Handschrift über Typoskript bis Zeitungsausschnitt)
  - Automatisches Chunking für große Objekte (>20 Bilder)
  - 7 automatische Quality Signals (Seitentyp-Klassifikation, Marker-Dichte, Duplikaterkennung, Sprachkonsistenz)
  - Cross-Model-Consensus (Flash Lite + Flash + Claude als Judge)
  - Live Viewer mit Faksimile-Vergleich, Qualitätssignalen und Suche
- **Relevanz für Template.** Größtes Korpus, zeigt Skalierung. Prompt-Gruppierung nach Dokumenttyp ist ein generalisierbares Muster. Quality Signals als automatische Vorfilterung. Gesamtes Projekt wurde mit Promptotyping und Claude Code realisiert (Opus 4.6), Projektleiter als Projektmanager und Domänenexperte, nicht als Softwareentwickler.
- **Ordnerstruktur.** `knowledge/`, `data/`, `pipeline/`, `results/`, `docs/`, `schemas/`, `CLAUDE.md`

### 2.3 co-ocr-htr

- **Repository.** https://github.com/DigitalHumanitiesCraft/co-ocr-htr
- **Gegenstand.** Browser-basierte Expert-in-the-Loop-Workbench für OCR/HTR-Verifikation, Validierung und Korrektur
- **Technologie.** Vollständig clientseitig, Vanilla JavaScript, kein Backend, kein npm, EventTarget-basiertes State Management
- **Besonderheiten.**
  - Multi-Provider-LLM-Integration (Gemini, OpenAI, Anthropic, DeepSeek-OCR via Ollama)
  - Hybride Validierung (deterministische Regeln + LLM-as-Judge mit 4 Perspektiven, paläographisch, sprachlich, strukturell, domänenspezifisch)
  - Kategorielle Konfidenz (sicher / prüfenswert / problematisch) statt numerischer Scores
  - PAGE-XML Import/Export, METS-XML Support, IIIF Support
  - Batch Processing mit Abort Control
  - Validation Fallback (lokale Transkription + Cloud-Validierung)
  - 276 Unit Tests
  - PWA-fähig
- **Relevanz für Template.** Die Provider-Abstraktion (llm.js), die Validierungslogik, die PAGE-XML/METS-Parser und das UI-Pattern (Bild-Text-Gegenüberstellung) sind direkt übernehmbar. Das kategorielle Konfidenzmodell ist ein konzeptueller Beitrag, der in die Validierungsstufe des Templates einfließt.
- **Ordnerstruktur.** `knowledge/` (umfangreiche Wissensbasis), `docs/` (Anwendung), `data/` (Samples), `CLAUDE.md`
- **Mitwirkende.** Robert Klugseder (ÖAW) hat Fork mit erweiterten Features (IndexedDB, Mistral OCR, Prompt Profiles, Postprocessing Pipeline)

### 2.4 teiCrafter

- **Repository.** https://github.com/DigitalHumanitiesCraft/teiCrafter
- **Gegenstand.** LLM-gestützte TEI-XML-Annotation für Digital Humanities
- **Technologie.** Browser-basiert, Vanilla ES6 Modules, kein Build, kein Framework, null npm-Abhängigkeiten
- **Besonderheiten.**
  - 5-Schritt-Workflow (Import, Mapping, Transform, Validate, Export)
  - 6 LLM-Provider (Gemini, OpenAI, Anthropic, DeepSeek, Qwen, Ollama)
  - Three-Layer-Prompt-Architektur (Base Rules + Source Context + User-Defined Mapping)
  - ODD-basierte Schema-Guidance (DTABf JSON Schema Profile)
  - 4-Level-Validierung (Well-Formedness, Plaintext Preservation, Schema Conformance, Review Completeness)
  - Confidence Visualization (drei Stufen mit Dual-Channel-Encoding)
  - Multi-Format Import (Plaintext, Markdown, XML, DOCX)
- **Positionierung im Workflow.** Image → coOCR/HTR → teiCrafter → ediarum/GAMS/Publication
- **Relevanz für Template.** Die Three-Layer-Prompt-Architektur für TEI-Annotation, die Schema-Guidance und die Validierungsstufen sind direkt generalisierbar. Die Erkenntnis, dass Post-Generation-Validierung besser funktioniert als Constrained Decoding (Schall/de Melo, RANLP 2025), bestimmt die Architektur der Annotationsstufe.
- **Ordnerstruktur.** `knowledge/` (4 Dokumente, OVERVIEW/ARCHITECTURE/REFERENCE/DEVELOPMENT), `docs/`, `data/`, `schemas/`, `CLAUDE.md`
- **Forschungskontext.** Explizit referenziert in Pollin et al. 2025 (ZfdG). Expert-LLM Agreement bei 64–68% (IUI 2025) bestätigt Notwendigkeit menschlicher Verifikation.

---

## 3. Methodik

### 3.1 Promptotyping

Promptotyping ist eine Context-Engineering-Methode zur iterativen Entwicklung von Forschungswerkzeugen durch gezielte Interaktion mit LLMs. Vier Phasen.

1. **Preparation.** Quellenanalyse, Kontextualisierung, Zieldefinition. Ergebnis sind die Wissensdokumente im `knowledge/`-Ordner.
2. **Exploration.** Iteratives Testen von Modellkonfigurationen und Prompt-Strategien. Vergleich verschiedener Ansätze an einem repräsentativen Sample.
3. **Distillation.** Konsolidierung der Erkenntnisse in strukturierte Dokumentation. Die Promptotyping Documents (DATA.md, CONTEXT.md, TEI_MAPPING.md) sind das Ergebnis.
4. **Implementation.** Umsetzung in funktionierenden Code. Claude Code generiert Code basierend auf den Promptotyping Documents.

Referenz: Pollin 2026a (L.I.S.A. Wissenschaftsportal Gerda Henkel Stiftung).

### 3.2 Critical Expert in the Loop

Der Mensch ist nicht Qualitätskontrolleur am Ende, sondern integraler Bestandteil des Prozesses. Jede Verarbeitungsstufe erzeugt Zwischenergebnisse in etablierten Formaten (JSON, PAGE-XML, TEI-XML), die auf mehreren Wegen prüfbar sind (Schema-Validierung, Tests, menschliche Inspektion, LLM-as-a-Judge). Der Mensch entscheidet an definierten Übergabepunkten, ob die nächste Stufe starten darf.

### 3.3 Epistemische Infrastruktur

Agentenbasierte Workflows bringen eine Kategorie von Entscheidungen in editorische Prozesse ein, die weder vollständig determiniert noch ohne Weiteres reproduzierbar sind. Die epistemische Infrastruktur ist das Ensemble aus Mechanismen, Arbeitsschritten und Werkzeugen, das die Ergebnisse LLM-gestützter Verarbeitungsschritte verifizierbar, kuratierbar und dokumentierbar macht. Im Template manifestiert sie sich als `knowledge/`-Ordner (Wissensdokumente als Kontextsteuerung für Agents), Validierungsroutinen (an jeder Stufe), Zwischenformate (JSON, PAGE-XML, TEI als prüfbare Artefakte), Provenance-Metadaten (welches Modell, welcher Prompt, welcher Zeitstempel), Entscheidungslog (`DECISIONS.md`) und Entwicklungsjournal (`JOURNAL.md`).

### 3.4 Asymmetrische Amplifikation

Frontier-LLMs automatisieren Forschungsarbeit nicht, sondern amplifizieren sie disruptiv. Der produktive Einsatz setzt Expertise voraus und verstärkt bestehende Kompetenz- und Infrastrukturvorteile. Das Template ist dafür konzipiert, von Domänenexpert*innen eingesetzt zu werden, nicht als Ersatz für editorische Kompetenz.

---

## 4. Template-Architektur

### 4.1 Designprinzipien

**Konfiguration vor Code.** Claude Code passt Wissensdokumente und Prompt-Templates an, nicht die Python-Skripte selbst. Nur wenn die bestehenden Skripte einen Quellentyp nicht abdecken, wird neuer Code geschrieben.

**Kontext-Budget.** Die CLAUDE.md definiert, welche Dokumente für welchen Arbeitsschritt gelesen werden. Nicht alles auf einmal.

**Idempotenz.** Jedes Pipeline-Skript kann mehrfach ausgeführt werden ohne Datenverlust.

**Provenance.** Jede erzeugte Datei enthält Metadaten (Modell, Modellversion, Prompt-Hash, Zeitstempel).

**Progressive Disclosure.** Minimale Konfiguration zum Start (Wissensdokumente ausfüllen, Daten in `data/sources/` legen). Fortgeschrittene Anpassungen möglich, aber nicht erforderlich.

### 4.2 Repository-Struktur

```
agentic-edition-pipeline/
│
├── CLAUDE.md                    # Einstiegspunkt für Claude Code
├── README.md                    # Projektbeschreibung
├── LICENSE                      # CC-BY 4.0
├── .env.example                 # API-Key-Template
├── .gitignore
├── requirements.txt
│
├── knowledge/                   # Promptotyping-Wissensbasis
│   ├── 00_INDEX.md              # Navigation, Lesehinweise, Dokumentenmatrix
│   ├── 01_PROJECT.md            # Projektziel, Scope, Institution, Zeitrahmen
│   ├── 02_DATA.md               # Quellenanalyse, Korpusbeschreibung, Formate
│   ├── 03_CONTEXT.md            # Editorische Richtlinien, Konventionen
│   ├── 04_TEI_MAPPING.md        # Quellstruktur → TEI-Element-Mapping
│   ├── 05_DECISIONS.md          # Entscheidungslog (ADR-Format)
│   └── 06_JOURNAL.md            # Entwicklungsjournal (pro Session)
│
├── data/
│   ├── sources/                 # Eingangsdaten (vom Menschen bereitgestellt)
│   └── processed/               # Pipeline-Ergebnisse (von Skripten erzeugt)
│
├── pipeline/                    # Python-Skripte
│   ├── config.py                # .env lesen, Pfade, Grundkonfiguration
│   ├── 01_extract_images.py     # PDF → Einzelseiten
│   ├── 02_analyze.py            # Inventar, Klassifikation
│   ├── 03_transcribe.py         # OCR/HTR via LLM-API
│   ├── 04_validate.py           # Hybride Validierung
│   ├── 05_annotate_tei.py       # Plaintext → TEI-XML
│   ├── 06_build_frontend.py     # TEI → Static Site
│   ├── llm.py                   # Provider-Abstraktion (Gemini, OpenAI, Anthropic, Ollama)
│   └── prompts/                 # Prompt-Templates
│       ├── transcription.md
│       ├── validation.md
│       └── annotation.md
│
├── results/                     # Finale Ergebnisse
│   ├── tei/
│   └── reports/
│
├── docs/                        # GitHub Pages
│   ├── index.html
│   ├── css/
│   └── js/
│
├── schemas/                     # TEI-Schemata
│   └── dtabf.json
│
└── .github/
    └── workflows/
        └── pages.yml
```

### 4.3 Workflow

```
1. Repository forken
2. knowledge/ Dokumente ausfüllen (01_PROJECT.md bis 04_TEI_MAPPING.md)
3. Daten in data/sources/ legen (PDFs, Bilder, oder PAGE-XML)
4. .env mit API-Keys anlegen
5. Claude Code starten → liest CLAUDE.md
6. Pipeline Schritt für Schritt ausführen:
   01_extract_images.py  → data/processed/images/
   02_analyze.py         → data/inventory.json, knowledge/02_DATA.md aktualisiert
   ---- Mensch prüft Inventar und Datenanalyse ----
   03_transcribe.py      → data/processed/transcriptions/
   ---- Mensch prüft Stichprobe ----
   04_validate.py        → data/processed/validated/
   ---- Mensch prüft Quality Signals ----
   05_annotate_tei.py    → data/processed/tei/ und results/tei/
   ---- Mensch validiert TEI-Stichprobe ----
   06_build_frontend.py  → docs/
   ---- Mensch prüft Frontend ----
7. GitHub Pages aktivieren
8. Iteration bei Bedarf
```

---

## 5. Gelöste Teilprobleme (Capability Map)

Diese Tabelle zeigt, welches der vier Quellprojekte welche Fähigkeit implementiert hat. Claude Code soll bei der Implementierung des Templates die jeweils ausgereifteste Lösung als Referenz verwenden.

### 5.1 Bilderkennung und Textextraktion

| Fähigkeit | Beste Referenz | Implementierung |
|---|---|---|
| Multi-Provider OCR/HTR | co-ocr-htr | `llm.js`, unterstützt Gemini, OpenAI, Anthropic, DeepSeek-OCR, Ollama |
| Prompt-Gruppierung nach Dokumenttyp | szd-htr-ocr-pipeline | 9 Kategorien, automatische Zuweisung via TEI-Metadaten |
| Chunking großer Objekte | szd-htr-ocr-pipeline | Automatisch bei >20 Bildern |
| Lokale OCR (ohne Cloud) | co-ocr-htr | DeepSeek-OCR via Ollama |
| PDF → Einzelseiten | zbz-ocr-tei | PyMuPDF |

### 5.2 Validierung und Qualitätssicherung

| Fähigkeit | Beste Referenz | Implementierung |
|---|---|---|
| Hybride Validierung (Regeln + LLM) | co-ocr-htr | Deterministische Regeln + LLM-Judge mit 4 Perspektiven |
| Kategorielle Konfidenz | co-ocr-htr | sicher / prüfenswert / problematisch |
| Quality Signals | szd-htr-ocr-pipeline | 7 automatische Signale |
| Cross-Model-Consensus | szd-htr-ocr-pipeline | Flash Lite + Flash + Claude als Judge |
| TEI-Schema-Validierung | teiCrafter | DOMParser + DTABf JSON Schema Profile |
| Plaintext Preservation Check | teiCrafter | Word Similarity, 95% Threshold |
| Validation Fallback | co-ocr-htr | Lokale Transkription + Cloud-Validierung |

### 5.3 TEI-Transformation und Annotation

| Fähigkeit | Beste Referenz | Implementierung |
|---|---|---|
| Three-Layer-Prompt-Architektur | teiCrafter | Base Rules + Source Context + User-Defined Mapping |
| ODD-basierte Schema-Guidance | teiCrafter | DTABf JSON Schema Profile (30+ Elemente) |
| DTA-Basisformat-Erzeugung | zbz-ocr-tei | Vollständige Pipeline |
| Bookkeeping-Ontology-TEI | Schliemann (in Chats) | Tabellarische Struktur mit bk:entry, bk:money |
| Multi-Format-Import | teiCrafter | Plaintext, Markdown, XML, DOCX |

### 5.4 Layout und Dokumentstruktur

| Fähigkeit | Beste Referenz | Implementierung |
|---|---|---|
| Automatische Dokumenttyp-Erkennung | co-ocr-htr | lines-Modus vs. grid-Modus |
| PAGE-XML Parsing | co-ocr-htr | `page-xml.js` |
| METS-XML Parsing | co-ocr-htr | `mets-xml.js` |
| IIIF Support | co-ocr-htr | Internet Archive, Bodleian, etc. |

### 5.5 Frontend und Publikation

| Fähigkeit | Beste Referenz | Implementierung |
|---|---|---|
| Live Viewer mit Faksimile-Vergleich | szd-htr-ocr-pipeline | Katalog, Suche, Qualitätssignale |
| Stepper-Navigation | teiCrafter | 5-Schritt-Workflow |
| GitHub Pages Deployment | szd-htr-ocr-pipeline | Statische Site |
| Export-Formate | co-ocr-htr | TXT, JSON, MD, PAGE-XML, TEI-XML, ZIP |

---

## 6. Architekturentscheidungen für das Template

### 6.1 Warum kein `agents/`-Ordner

In der Konzeptionsphase wurde ein `agents/`-Ordner mit separaten CLAUDE.md-Dateien pro Sub-Agent erwogen. Das wurde verworfen, weil Claude Code in der Praxis sequentiell durch eine einzige CLAUDE.md arbeitet. Separate Agent-Definitionen erzeugen Komplexität ohne operativen Nutzen. Die Pipeline-Reihenfolge und die Übergabepunkte für menschliche Verifikation werden in der Root-CLAUDE.md beschrieben.

### 6.2 Warum kein YAML-Konfigurationssystem

Die Projektkonfiguration lebt in `knowledge/`-Dokumenten. Claude Code liest sie dort. Eine separate YAML-Datei erzeugt eine zweite Quelle der Wahrheit. Die einzige maschinenlesbare Konfiguration sind API-Keys in `.env`.

### 6.3 Warum eine einzige `llm.py`

Die bestehenden Repos lösen Multi-Provider-Support mit einer einzigen Datei und Branching nach Provider-Typ. Für ein Template, das geforkt und modifiziert wird, ist das praktischer als eine Abstraktionsschicht mit separaten Provider-Dateien.

### 6.4 Warum Vanilla JavaScript im Frontend

Alle vier Quellprojekte verwenden Vanilla JS ohne Framework. Das reduziert Abhängigkeiten, maximiert Langlebigkeit und ermöglicht Claude Code die direkte Modifikation ohne Build-Prozess.

### 6.5 Warum `knowledge/` statt Wiki oder externes Dokumentationssystem

Die Wissensdokumente sind der Kontext für Claude Code. Sie müssen im selben Repository liegen wie der Code, damit Claude Code sie lesen kann. Sie sind Obsidian-kompatibel, also auch für Menschen als vernetzte Wissensbasis nutzbar.

---

## 7. Akademischer Kontext

### 7.1 Eingereichte Publikation

**Titel.** Agentenbasierte Editionsworkflows und epistemische Infrastrukturen. Ein Experiment zur digitalen Edition der Schriften von Jeanne Hersch

**Autoren.** Christopher Pollin (Digital Humanities Craft), Elias Kreyenbühl (Zentralbibliothek Zürich)

**Kernaussagen.**
- Agentenbasierte End-to-End-Pipeline vom PDF bis zum validen TEI (DTA-Basisformat) als bewusst zugespitztes Experiment
- Solche Workflows setzen eine epistemische Infrastruktur voraus
- AI Agents bilden einen neuen Layer im Technologie-Stack digitaler Editionen
- Die editorische Arbeit verlagert sich auf Verifikation und Kuratierung
- Agentenbasierte Systeme amplifizieren die Expertise der Einsetzenden
- Bestehende Asymmetrien werden verschärft (AI Literacy + Zugang zu Frontier-Modellen als Voraussetzung)

**Referenzen.**
- Pollin et al. 2025, ZfdG (Generative AI in Digital Scholarly Editions)
- Pollin 2026a, L.I.S.A. (Promptotyping)
- Sahle 2016 (What is a Scholarly Digital Edition?)
- Sapkota et al. 2025, Information Fusion (AI Agents vs. Agentic AI)
- Strutz/Scholger 2026, DHd (LLM-Assisted Metadata Extraction)

### 7.2 Forschungslandschaft

Aus dem teiCrafter Knowledge Base (Stand 2026):
- Kein integriertes System existiert, das LLM-assisted TEI Generation, ODD-guided Schema Validation und Human-in-the-Loop Review in einer Browser-basierten Umgebung kombiniert
- Kein Benchmark für LLM-generated TEI-XML Quality ist publiziert
- Expert-LLM Agreement bei domänenspezifischen Tasks erreicht nur 64–68% (IUI 2025)
- Post-Generation Validation übertrifft Constrained Decoding (Schall/de Melo, RANLP 2025)

---

## 8. Auftrag an Claude Code

Wenn du dieses Dokument als Claude Code liest, ist dein Auftrag wie folgt.

### 8.1 Repository aufsetzen

1. Erstelle die Ordnerstruktur gemäß Abschnitt 4.2
2. Erstelle die `CLAUDE.md` als Root-Einstiegspunkt mit Verweis auf dieses Wissensdokument, die Pipeline-Reihenfolge (Abschnitt 4.3) und die Übergabepunkte für menschliche Verifikation
3. Erstelle die `knowledge/`-Templates mit Leitfragen und Platzhaltern, basierend auf den Mustern der vier Quellprojekte
4. Erstelle die `README.md` mit Projektbeschreibung, Quickstart und Verweis auf die Methodik

### 8.2 Pipeline-Skripte

1. Implementiere `config.py` (liest `.env`, definiert Pfade, Grundkonfiguration)
2. Implementiere `llm.py` als einheitliche Provider-Abstraktion. Referenzimplementierung ist `llm.js` aus co-ocr-htr (adaptiert für Python) und die Provider-Logik aus szd-htr-ocr-pipeline
3. Implementiere die Pipeline-Skripte 01–06. Jedes Skript folgt diesem Muster:
   - Liest Input aus `data/sources/` oder `data/processed/`
   - Liest Konfiguration aus `knowledge/`-Dokumenten (wo nötig)
   - Schreibt Output in `data/processed/` oder `results/`
   - Schreibt strukturiertes Log (JSON) mit Provenance-Metadaten
   - Ist idempotent (überschreibt nur mit `--force`)
4. Orientiere dich an den konkreten Implementierungen der Quellprojekte. Für OCR/Transkription ist szd-htr-ocr-pipeline die ausgereifteste Referenz. Für Validierung ist die Kombination aus co-ocr-htr (hybride Validierung) und szd-htr-ocr-pipeline (Quality Signals) das Ziel. Für TEI-Annotation ist teiCrafter (Three-Layer-Prompt) die Referenz. Für Frontend ist szd-htr-ocr-pipeline (Viewer mit Katalog, Suche, Qualitätssignale) die Referenz.

### 8.3 Prompt-Templates

1. Erstelle `prompts/transcription.md` basierend auf dem 4-Layer-Prompt-System der szd-htr-ocr-pipeline, generalisiert für verschiedene Quellentypen
2. Erstelle `prompts/validation.md` basierend auf dem 4-Perspektiven-Judge aus co-ocr-htr
3. Erstelle `prompts/annotation.md` basierend auf der Three-Layer-Architektur aus teiCrafter

### 8.4 Frontend

1. Erstelle eine minimale Static Site in `docs/` mit Katalog-Ansicht, Faksimile-Text-Gegenüberstellung und Suchfunktion
2. Referenzimplementierung ist der Live Viewer der szd-htr-ocr-pipeline
3. Vanilla HTML/CSS/JS, kein Framework, kein Build-Prozess
4. GitHub Pages Workflow in `.github/workflows/pages.yml`

### 8.5 Qualitätskriterien

- Jedes Skript muss ohne Modifikation auf einem neuen Editionsprojekt lauffähig sein, wenn die `knowledge/`-Dokumente ausgefüllt und die Daten bereitgestellt sind
- Die Provider-Abstraktion muss Gemini, OpenAI, Anthropic und Ollama unterstützen
- Das Frontend muss auf GitHub Pages funktionieren
- Alle erzeugten TEI-Dateien müssen gegen das DTABf-Schema validieren
- Provenance-Metadaten müssen in jeder erzeugten Datei vorhanden sein

---

## 9. Glossar

| Begriff | Definition |
|---|---|
| Promptotyping | Context-Engineering-Methode mit vier Phasen (Preparation, Exploration, Distillation, Implementation) |
| Critical Expert in the Loop | Mensch als konstitutiver Bestandteil des Prozesses, nicht als Endkontrolle |
| Epistemische Infrastruktur | Mechanismen, Arbeitsschritte und Werkzeuge zur Verifikation, Kuratierung und Dokumentation von LLM-Ergebnissen |
| Asymmetrische Amplifikation | These, dass Frontier-LLMs bestehende Kompetenz- und Infrastrukturvorteile verstärken |
| Kategorielle Konfidenz | Dreistufiges Bewertungsschema (sicher / prüfenswert / problematisch) statt numerischer Scores |
| Quality Signals | Automatische Indikatoren für potenzielle Probleme in Pipeline-Ergebnissen |
| DTA-Basisformat (DTABf) | TEI-Profil des Deutschen Textarchivs, weit verbreiteter Standard für historische Texte |
| CSAP | Context Stream Agent Protocol, Methode für Multi-Agenten-Wissenstransfer |
| Agentic | Prozesscharakter von AI-Agent-basierten Workflows (vs. "agent-based" als technische Architektur) |