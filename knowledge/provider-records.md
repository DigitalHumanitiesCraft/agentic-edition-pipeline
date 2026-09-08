---
title: Modellaufrufe und Wiederaufnahme
status: active
---

# Modellaufrufe und Wiederaufnahme

Schritt 3 schreibt pro tatsächlich begonnenem Chunk- oder JSON-Retry-Aufruf eine eigene Datei unter `data/processed/llm-calls/{id}/`. Das Protokoll enthält Provider, angefordertes Modell, Temperatur, vollständigen ausgeführten Prompt, Bilddateinamen mit Hash, Seitenbereich, Beginn und Ende. Eine empfangene JSON-Antwort bleibt vollständig erhalten. Damit bleiben vom Provider gelieferte Angaben wie tatsächliche Modellversion, Verbrauch und Abschlussgrund nachprüfbar. Das extrahierte Antworttextfeld und bei Fehlern die bereinigte Fehlermeldung sind getrennt vorhanden. Zugangsdaten, HTTP-Header und eingebettete Bildbytes werden nicht protokolliert. Konfigurierte Schlüsselwerte werden auch aus Antwortinhalten entfernt.

Die Aufzeichnungen erfassen den logischen Provideraufruf. Interne HTTP-Retries bei Rate Limits und Timeouts besitzen weiterhin keine einzelnen vollständigen Aufzeichnungen. Nicht empfangene oder nicht als JSON lesbare Antworten können nicht als Provider-JSON gespeichert werden. Die dokumentierte Modellversion hängt von den tatsächlich gelieferten Feldern ab.

Erfolgreiche, vertragskonforme Chunks liegen zusätzlich unter `data/processed/chunk-cache/{id}/`. Ihre Identität umfasst den vollständigen Prompt, alle autoritativen Objektmetadaten, Provider und Modell, Temperatur, Bildbytes, Seitenbereich und eine Cache-Vertragsversion. Der gespeicherte Inhalt besitzt einen eigenen SHA-256. Vor Wiederverwendung werden Identität, Integrität und Seitenvertrag geprüft. Ein abgebrochener Dokumentlauf kann dadurch seine fertigen Teilmengen weiterverwenden. Ein unlesbarer oder widersprüchlicher Cache blockiert das Objekt. `--force` führt frische Aufrufe aus; die bestehende Sperre für Transkriptionen mit Review-Historie bleibt bestehen.

Die Protokolle werden durch den lokalen Editor und GitHub Pages nicht ausgeliefert. Die lokale Herkunftsanzeige nennt die Aufrufreferenzen. Vor einer Weitergabe solcher Dateien sind Text- und Metadatenrechte sowie ihre möglichen vertraulichen Inhalte zu prüfen. Die synthetischen Regressionstests prüfen Wiederaufnahme, Prompt- und Bildänderungen, vollständige Antwortprotokolle und Schlüsselbereinigung ohne Netzwerkzugriff. Eine erneute Prüfung realer Provider wurde für 0.10.0 nicht durchgeführt.

## Ausführungswege und Aussagegrenzen

Das Modell im Harness und das Modell eines API-Aufrufs sind unabhängig zu benennen. Eine durch den Agenten direkt erstellte Annotation benötigt ein eigenes Aufgabenprotokoll mit Eingabestand, Anweisung, Ergebnis und ausgeführten Prüfungen. Der bestehende Providerlogger erfasst solche Harness-Aktionen nicht automatisch.

Eine deterministische Ableitung wird durch Codezustand, Konfiguration, Eingabe und Ergebnis nachvollziehbar. Ein Hash belegt die Identität des jeweiligen Stands. Eine fachliche Richtigkeit folgt daraus nicht.

Verbrauchszahlen werden nur berichtet, wenn sie tatsächlich vorliegen. Eine Kostenangabe benötigt zusätzlich das verwendete Preismodell und den Abrechnungsbezug. Schätzungen aus einem Gespräch sind kein Kostenbeleg. Fehlende tatsächliche Modellversionen bleiben als fehlend gekennzeichnet.

Eine zukünftige gemeinsame Herkunftsdarstellung könnte diese Ausführungswege verbinden. Ein automatischer PROV-Export und eine vollständige Aufzeichnung aller Harness-Aktionen sind derzeit nicht implementiert.
