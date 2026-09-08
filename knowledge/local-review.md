---
title: Lokaler Korrekturvertrag
status: active
---

# Lokaler Korrekturvertrag

Der lokale Dienst wird aus einer eingerichteten Edition mit `uv run python pipeline/review_server.py --port 8080` gestartet. Er bindet ausschließlich an `127.0.0.1`. GitHub Pages bleibt eine statische Leseansicht. Ein API-Token, Host- und Origin-Prüfungen begrenzen Schreibzugriffe auf die lokale Sitzung. Der Dienst ist kein authentifiziertes Mehrbenutzersystem.

`GET /api/session` liefert Schreibfähigkeit und Sitzungstoken. `GET /api/documents/{id}` liefert Seiten, eine Dateiversion und den Zustand bekannter Abhängigkeiten. `POST /api/documents/{id}/pages/{n}` erwartet `version`, `transcription`, `notes`, `actor`, `actor_kind` und `note`. `actor_kind` ist `human` oder `agent`; ausgelassene Angaben verwenden aus Kompatibilitätsgründen `human`. Ein veralteter Versionshash ergibt HTTP 409. Leere Änderungsgründe sind unzulässig. Der Dienst bietet keinen Endpunkt für fachliche Freigaben.

Vorschläge werden mit denselben Feldern an `/api/documents/{id}/proposals/{n}` übergeben. Sie bleiben unter `data/review-proposals/{id}/` getrennt vom kanonischen Text. Ihre Basisversion macht spätere Veraltung sichtbar. Eine Übernahme erfolgt durch einen ausdrücklichen Korrektursave.

POST-Anfragen verwenden `Content-Type: application/json` und den Header `X-Review-Token` mit dem Wert aus `GET /api/session`. Agenten geben `actor_kind: "agent"` an. Vor einem Save lesen sie die aktuelle Dokumentversion und vergleichen ihre geplante Änderung mit dem vorhandenen Text. HTTP 409 erfordert einen erneuten Vergleich; das bloße Ersetzen des Versionshashes würde den Konfliktschutz umgehen. Token gehören nicht in Dateien, Logs oder öffentliche URLs.

Die Verarbeitung verwendet die vorhandenen Stufen 4 und 5 sowie die gemeinsame Frontend-Erzeugung. Sie erfolgt ohne Modellaufruf. Das konfigurierte `VALIDATION_SCHEMA` bleibt verbindlich. Vorbereitete Dateien werden erst nach erfolgreicher Prüfung übernommen. ZIP-Snapshots und ein Transaktionsmarker sichern die Wiederherstellung. Bei einem unterbrochenen Vorgang ist der Snapshot vor weiteren Saves wiederherzustellen. Direkte parallele Dateiedits außerhalb des Dienstes bleiben ein zu vermeidender Konfliktweg.

Der Wiederherstellungsbefehl lautet `uv run python pipeline/review_server.py --recover`. Er prüft den im Marker hinterlegten Snapshot-Hash, restauriert die vorherigen Dateien und entfernt ausschließlich die im Snapshot als zuvor fehlend verzeichneten Ausgabedateien. Erst danach wird die Sperre entfernt. Während einer offenen Transaktion nach einem Prozessabbruch werden statische Ausgaben nicht ausgeliefert. Eine Betriebssystemsperre begrenzt Server und Wiederherstellungs-CLI auf einen schreibenden Prozess pro Repository. Sie wird beim Prozessende freigegeben. Direkte Dateibearbeitung durch andere Werkzeuge muss während eines Saves weiterhin unterbleiben.

Die Browseroberfläche bewahrt den Entwurf bei HTTP 409 und bei fehlgeschlagenen Saves. Ein ungespeicherter Entwurf warnt vor dem Verlassen der Seite. Vorschläge lassen sich zuerst in das Eingabefeld laden; die Übernahme erfordert weiterhin das ausdrücklich betätigte Speichern. Seitenstatus und zusammengefasster Dokumentstatus werden getrennt ausgewiesen. Eine einzelne bearbeitete Seite kann neben weiterhin ungeprüften Seiten stehen.

GitHub Pages zeigt die aus TEI abgeleitete Herkunft und Korrekturereignisse. Rohtranskription, vollständige Vorher-/Nachher-Werte, Sitzungstoken und Vorschläge stehen ausschließlich über den lokalen Dienst bereit. Der Speichervorgang startet weder Commit noch Push oder fachliche Freigabe.

## Prüfungen beim Speichern

Ein ausdrücklich ausgelöster Korrektursave umfasst die erneute deterministische Prüfung und Ableitung der Stufen 4 bis 6. Er benötigt keine Modellaufrufe. Die fachlichen Checkpoints für die Ersteinrichtung und Verarbeitung eines Korpus bleiben bestehen. Seitenfreigaben erfolgen weiterhin ausschließlich nach einer ausdrücklichen menschlichen Entscheidung.

## Daten eines Eingriffs

`pages[].edits` enthält `id`, `actor`, `actor_kind`, zeitzonenbezogenen `timestamp`, `note` und vollständige `before`-/`after`-Werte für `transcription` und `notes`. Die Ereignisfolge muss zum aktuellen Text passen. `transcription_raw` und initiale Modellprovenienz bleiben unverändert. TEI übernimmt die gespeicherten Ereignisse mit Akteur und Seitenbezug in `revisionDesc`. Unbestätigte Vorschläge erzeugen dort keine Änderung.

## Abhängigkeiten

Optionale projektspezifische Annotationen unter `data/annotations/{id}.json` binden den Transkriptionsstand über `_meta.transcription_sha256`. Der Hash bezieht sich auf UTF-8-JSON mit sortierten Schlüsseln, unveränderten Unicode-Zeichen und kompakten Trennzeichen. Fehlende, unlesbare oder abweichende Bindungen sind prüfpflichtig. Der Dienst erneuert keine Annotationen. Bei einer Textänderung bleiben sie als veraltet sichtbar; eine bereits semantisch angereicherte TEI wird vom Basis-Korrekturworkflow abgewiesen, um ihre Auszeichnung nicht zu verlieren.

Prüfberichte müssen ihre Eingabe benennen. Nach Änderungen ist ein früherer Befund keine Aussage über den neuen Stand. Eine neu gespeicherte Korrektur bestätigt keine andere Stelle oder die ganze Seite. Wiederherstellungsdateien und vollständige Modellprotokolle werden nicht öffentlich ausgeliefert.

## Notizen und Referenzstatus nach einer Korrektur

Der Editor kann Text und Notizen gemeinsam ändern und protokolliert beide Vorher-/Nachher-Werte. Eine unveränderte ältere Notiz kann dennoch eine inzwischen ersetzte Lesung beschreiben. Die Anwendung erkennt solche inhaltlichen Widersprüche derzeit nicht automatisch.

Beim Speichern sind deshalb auch die zugehörigen Notizen auf ihren Bezug zum aktuellen Text zu prüfen. Ursprüngliche Modellbeobachtungen bleiben im Aufrufprotokoll und bei späteren Änderungen in der Ereignisfolge nachvollziehbar. Ein zusätzlicher versionsbezogener Status einzelner Befunde ist eine offene Anforderung in [[specification]].

Ein Save bestätigt ausschließlich den gespeicherten Eingriff. Die Verwendung des korrigierten Texts als unabhängige Evaluationsreferenz erfordert das in [[03_CONTEXT]] dokumentierte Prüfverfahren.
