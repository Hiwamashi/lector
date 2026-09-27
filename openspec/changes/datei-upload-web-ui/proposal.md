# Proposal

## Why

Dateien gelangen heute ausschließlich über den Eingangsordner (`WATCH_DIR`, im Betrieb die
NAS-Freigabe `scan-in`) in Lector. Wer im LAN vor der Web-UI sitzt, aber kein Share gemountet
hat, kann kein Dokument einspeisen — obwohl die Oberfläche erreichbar ist und den Vorgang
anschließend ohnehin anzeigt. Für den gelegentlichen Einzelfall („ein paar Dateien bei Bedarf")
ist das eine unnötige Hürde.

Das PRD schließt einen manuellen Upload bislang ausdrücklich aus (`prd/PRD_Lector.md`, Zeile 53;
`CLAUDE.md`, Abschnitt „Wichtige Vorgaben & Fallstricke"). Dieser Vorschlag hebt diesen Ausschluss
bewusst auf — begrenzt auf den Betrieb im LAN und ohne die Rolle von Lector als reinen
Veredelungsschritt vor Paperless anzutasten.

## What Changes

- Die Web-UI erhält ein Upload-Formular, über das eine oder mehrere Dateien entgegengenommen
  werden.
- Der Dienst legt jede entgegengenommene Datei **vollständig und unter einem freien Namen** im
  Eingangsordner ab. Damit endet der Upload-Weg; die Aufnahme in die Verarbeitung übernimmt
  unverändert der bestehende Eingangs-Mechanismus.
- Dateien mit nicht unterstützter Endung werden bereits bei der Entgegennahme zurückgewiesen —
  mit sichtbarer Meldung statt stillem Übergehen wie im Eingangsordner.
- Der vom Client gelieferte Dateiname wird auf seinen reinen Namensanteil reduziert, damit er
  nicht aus dem Eingangsordner herausführen kann.
- Keine Änderung an Worker, Verarbeitungspipeline, Datenmodell, Zustandsmaschine oder Historie:
  eine hochgeladene Datei ist ab dem Eingangsordner von einer per SMB kopierten nicht
  unterscheidbar.

Nicht Teil dieses Vorschlags (bewusst ausgeklammert):

- **Keine Authentifizierung.** Der Dienst bleibt wie bisher unauthentifiziert und ausschließlich
  im LAN betrieben. Wer die Oberfläche erreicht, darf hochladen.
- **Keine Erreichbarkeit von außerhalb des LAN**, also kein Reverse Proxy und kein TLS.
- **Keine Kamera-Aufnahme** über das Gerät des Nutzers.
- **Kein Zusammenfassen mehrerer hochgeladener Bilder zu einem mehrseitigen Dokument.** Wie im
  Eingangsordner gilt: eine Datei, ein Vorgang.
- **Keine vorgezogene Doppel-Erkennung.** Ein inhaltsgleicher Doppel-Upload wird wie bisher erst
  bei der Aufnahme verworfen, nicht schon bei der Entgegennahme.

## Capabilities

### New Capabilities

- `datei-upload`: Entgegennahme von Dateien über die Web-UI und deren vollständige, kollisionsfreie
  Ablage im Eingangsordner — einschließlich Format-Zurückweisung und Namens-Absicherung. Der
  Vertrag endet an der Übergabe an den Eingangsordner.

### Modified Capabilities

Keine. `dokumenteneingang` beschreibt, unter welchen Bedingungen eine Datei aus dem Eingangsordner
aufgenommen wird, und ist zur Herkunft der Datei bewusst indifferent. Eine hochgeladene Datei
durchläuft dieselben Anforderungen unverändert (Stabilitätsfenster, Format-Filter, Prüfsummen-
Abgleich, Vorgang im Zustand `pending`), weshalb dort keine Anforderung angepasst werden muss.

## Impact

**Code**

- `app/main.py`: ein neuer Endpunkt zur Entgegennahme; keine Änderung an bestehenden Routen.
- `app/templates/dashboard.html`: Upload-Formular; `app/static/app.css` für dessen Darstellung.
- `app/fileops.py`: `unique_target()` wird für die Namensvergabe wiederverwendet — voraussichtlich
  unverändert.
- Unberührt: `app/worker.py`, `app/watcher.py`, `app/pipeline.py`, `app/detection.py`,
  `app/repository.py`, `app/models.py`, `app/db.py`.

**Abhängigkeiten**

Keine neuen. `python-multipart` ist bereits in `pyproject.toml` enthalten (wird für die
bestehenden `Form(...)`-Routen benötigt).

**Konfiguration**

Kein neuer Pflichtparameter. Der Upload schreibt in das bereits konfigurierte `WATCH_DIR` und
nutzt die bestehenden `PARTIAL_SUFFIXES` für die Zwischenablage.

**Betrieb**

Keine Änderung am Compose-Stack: `WATCH_DIR` ist bereits als Volume eingebunden und beschreibbar,
der Start prüft das bereits (`_check_writable_paths`).

**Dokumentation**

- `prd/PRD_Lector.md` und `CLAUDE.md`: der Ausschluss „kein manueller Datei-Upload" muss durch den
  neuen, eingegrenzten Stand ersetzt werden.
- `feature-documentation/`: eine neue Datei für das Feature.
- `prd/PROGRESS.md`: Fortschritt nachziehen.
