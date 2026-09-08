---
title: Anforderungen an Version 0.10.0
status: active
---

# Anforderungen an Version 0.10.0

## Implementierter Korrekturvertrag

Die Version ergänzt die lokale Bearbeitung kanonischer Transkriptionsdateien über Browser und dieselbe lokale API. Eine Textkorrektur bewahrt den Rohtext, setzt den Seitenstand auf `in_review` und erzeugt ein gespeichertes Änderungsereignis. Vorschläge besitzen einen eigenen Speicherort und ändern weder Quelltext noch Abnahme.

Vor Übernahme eines gespeicherten Standes müssen deterministische Qualitätsprüfung, Textbewahrung und das konfigurierte RelaxNG-Schema bestehen. Kanonisches JSON, TEI-Kopien und Browserdaten werden gemeinsam vorbereitet. Konflikte verwerfen keine Nutzereingabe. Vorherige Dateistände ermöglichen Wiederherstellung. Ein erkannter unterbrochener Schreibvorgang sperrt weitere Schreibzugriffe bis zur Wiederherstellung.

Optionale Annotationen können ihren Eingabetext binden. Veraltete Annotationen werden angezeigt und dürfen nicht als aktueller Stand publiziert werden. Ihre Erneuerung ist projektspezifisch. Version 0.10.0 führt keine automatische Entitätenerkennung oder Layoutrekonstruktion ein.

Die Oberfläche zeigt Schreibfähigkeit, aktuellen Text, Rohtext, Änderungsgeschichte und Herkunft. Synthetische Tests prüfen gespeicherte Korrekturen bis zum ausgelieferten TEI. Aufrufprotokolle und wiederverwendbare Teilaufrufe ergänzen den Transkriptionspfad. Neue Providerläufe und eine fachliche Transkriptionsprüfung gehören nicht zum technischen Testnachweis.

## Dokumentationsvertrag

Das README erklärt das Repository, Nachnutzung, Modelle, Aufgaben und Funktionsgrenzen. Die vollständigen Befehle stehen in [SETUP.md](../SETUP.md) und der [Verarbeitungsreferenz](../reference/pipeline.md). Konkrete Forschungskorpora bleiben in den Herkunftsdokumenten; ihre Fakten werden keine Standardkonfiguration.

[AGENTS.md](../AGENTS.md) ist die gemeinsame Aktionsschicht für AI-Harnesses. Harness-spezifische Dateien enthalten ausschließlich den Einstieg. Zusätzliche Verfahren benötigen einen dokumentierten Adapter oder Konverter, dessen Ein- und Ausgabe sowie Provenienz geprüft werden. Die Modellwahl des Harness ist unabhängig von der Verarbeitungskonfiguration.

Die nummerierten Skripte behalten ihre Namen. Qualitätsbewertung des Textes, formale Schemaprüfung und fachliche Abnahme werden getrennt beschrieben. Design ist eine begleitende Konkretisierung der Prüfaufgaben und kein verpflichtender Schritt `5b`.

## Aus dem Video abgeleitete, noch offene Funktionen

Diese Anforderungen sind dokumentiert. Sie sind im Basisfrontend und Basismodell nicht implementiert.

| Anforderung | Nachweis einer künftigen Umsetzung |
|---|---|
| Bildvergrößerung und Sprung zum Quellenbeleg | Kleine Schrift ist prüfbar; ein Metadatenbefund führt zur richtigen Seite oder Region |
| Unabhängige Erstlesung | Modelltext bleibt verborgen, bis die eigene Lesung gespeichert ist |
| Versionsanzeige für Einzelbefunde | Eine unveränderte alte Notiz wird nach Textänderung als prüfpflichtig erkennbar |
| Kontrollierter Vergleich von Modellkontexten | Bildgleiche Läufe mit und ohne Metadaten besitzen getrennte Prompts und unabhängige Referenzen |
| Semantischer Annotationsworkflow | Erwähnungen, Identitäten, Rollen und Beziehungen werden getrennt modelliert und geprüft |
| Herkunft über mehrere Ausführungswege | API-Aufruf, Harness-Aufgabe und deterministische Ableitung sind anhand ihrer tatsächlichen Eingaben nachvollziehbar |

Der vorhandene Editor bindet externe Annotationen an Textstände und speichert Notizänderungen. Er erkennt keine semantischen Widersprüche in unveränderten alten Notizen. Der vorhandene Providerlogger protokolliert keine beliebigen Harness-Aktionen.

Die [Evaluationsreferenz](../reference/evaluation.md) nennt Beobachtungsstellen im Video und die Grenzen der daraus abgeleiteten Aussagen. Ein kontrollierter Modellvergleich, gemessene Kosten und eine Fehlerquote liegen aus dieser Session nicht vor.
