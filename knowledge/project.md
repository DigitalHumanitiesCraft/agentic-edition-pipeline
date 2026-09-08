---
title: Auftrag der Agentic Edition Pipeline
status: active
---

# Auftrag der Agentic Edition Pipeline

Das Repository ist eine nachnutzbare Vorlage für digitale Editionsworkflows in einem AI-Harness. Es verbindet gepflegtes Projektwissen mit Verarbeitungsskripten, Prompts und Datenverträgen. Der Agent verwendet diesen Kontext zur Einrichtung und Anpassung einer Edition.

## Wiederverwendung

Die Architektur lässt die Modellwahl im Harness und die Wahl der Verarbeitungsverfahren unabhängig voneinander zu. Mitgeliefert sind Python-Skripte, ein natives JavaScript-Frontend und Adapter für Gemini, OpenAI, Anthropic und Ollama. Weitere Modelle, spezialisierte OCR-/HTR-Systeme und andere ML-Verfahren benötigen eine passende Schnittstelle oder Konvertierung. Technologieunabhängigkeit bezeichnet hier die Möglichkeit zur begründeten Substitution. Die vorhandene Implementierung hat konkrete technische Voraussetzungen.

Die Dateien 01 bis 05 enthalten offene Angaben für einzelne Editionsprojekte. Wartung und isolierte Tests erhalten diese Platzhalter. Ein neuer Fork übernimmt Methoden und Verträge und trifft seine eigenen Entscheidungen über Quellen, Rechte, Editionskonventionen und Modelle. Historische Fälle und ihre Herkunft bleiben in [[lineage]] und [[case-comparison]] dokumentiert.

## Arbeitsvertrag

[AGENTS.md](../AGENTS.md) enthält den gemeinsamen Arbeitsvertrag. Harness-spezifische Einstiegsdateien verweisen darauf. Die nummerierten Skripte beschreiben einen vorhandenen Verarbeitungspfad. Bereits verfügbare Transkriptionen und TEI-Dateien erlauben andere Einstiege. Die [Verarbeitungsreferenz](../reference/pipeline.md) nennt deren Abhängigkeiten.

Prüfoberfläche und Editionsmodell werden bereits am ersten Beispiel konkretisiert. Textkorrekturen erfordern die erneute Prüfung abhängiger Ausgaben. Gespeicherte Änderungen, formale Validierung und fachliche Abnahme bleiben getrennte Zustände.

## Stand und Geltungsumfang

Version 0.10.0 ergänzt den lokalen Korrekturworkflow. Beobachtungen aus zwei lokalen Prüfinstanzen und dem [Video](https://youtu.be/krL-xMxTa_c) konkretisieren die Anforderungen an Metadatenherkunft, Modellkontext und Annotationsprüfung. Die Forschungsdaten und Rechteentscheidungen der Instanzen bleiben außerhalb des Templates.

Anforderungen und noch offene Erweiterungen stehen in [[specification]]. [[local-review]] und [[provider-records]] beschreiben die implementierten Verträge. [Evaluation](../reference/evaluation.md) begrenzt die Aussagekraft technischer Tests und der Videobeobachtungen.

Die Vorlage ist eine Research Preview und keine stabile Version. Die fachliche Abnahme erfolgt im jeweiligen Editionsprojekt. Die Nutzerabnahme der Template-Erweiterung bleibt gesondert erforderlich. Das Entwicklungsjournal dokumentiert den geprüften Umfang; der öffentliche Git-Stand belegt die tatsächlich veröffentlichte Fassung.
