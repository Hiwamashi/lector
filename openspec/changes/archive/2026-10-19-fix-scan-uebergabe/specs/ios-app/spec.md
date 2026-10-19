# Spec Delta

## MODIFIED Requirements

### Requirement: Scans und Fotos werden als ein PDF übergeben

Die App MUSS das Scannen von Belegen mit der Kamera anbieten, mit Erkennung der
Dokumentkanten und mehreren Seiten je Beleg. Außerdem MUSS sie die Auswahl von Fotos aus der
Mediathek des Geräts anbieten. Die Seiten eines Scans bzw. die ausgewählten Fotos MUSS die App
auf dem Gerät zu einem einzigen PDF zusammenfassen und als eine Datei übergeben. Ein Bild DARF
NICHT in seinem ursprünglichen Bildformat übergeben werden. Nach der Übergabe MUSS die App die
Annahme bestätigen, ohne auf die Verarbeitung zu warten. Die Übergabe MUSS unmittelbar nach dem
Speichern im Scanner beginnen, ohne weiteres Zutun der Person, und auf dieselbe Weise gelingen
wie die Übergabe ausgewählter Fotos.

#### Scenario: Dreiseitiger Scan

- **WHEN** eine Person einen Beleg mit drei Seiten scannt und absendet
- **THEN** übergibt die App genau ein PDF mit drei Seiten, und daraus entsteht ein einziger
  Vorgang

#### Scenario: Übergabe direkt nach dem Scannen

- **WHEN** eine Person im Scanner auf „Speichern“ tippt und eine Verbindung zum Dienst besteht
- **THEN** schließt sich der Scanner, die Übergabe-Ansicht zeigt den Fortschritt, der Dienst
  erhält das PDF, und die App bestätigt die Annahme

#### Scenario: Foto im HEIC-Format

- **WHEN** eine Person ein Foto im HEIC-Format aus der Mediathek wählt und absendet
- **THEN** übergibt die App ein PDF mit diesem Bild und keine HEIC-Datei

### Requirement: Ohne Verbindung wird nichts zwischengespeichert

Die App MUSS für jede Übergabe eine Verbindung zum Dienst voraussetzen. Scheitert eine
Übergabe, MUSS die App den Fehlschlag melden. Solange die Ansicht geöffnet ist, MUSS das
vorbereitete Dokument erhalten bleiben und die App ein erneutes Senden dieses Dokuments
anbieten. Erst das Schließen der Ansicht durch die Person DARF das vorbereitete Dokument
verwerfen. Ist das vorbereitete Dokument dennoch nicht mehr vorhanden, MUSS die App das als
eigenen Fehler benennen und DARF ihn NICHT als allgemeinen Sendefehler ausgeben. Eine
Warteschlange, die Übergaben später selbstständig nachholt, DARF es NICHT geben.

#### Scenario: Upload ohne Netz

- **WHEN** eine Person einen Scan absendet, während keine Verbindung zum Dienst besteht
- **THEN** meldet die App den Fehlschlag und bietet erneutes Senden an

#### Scenario: Erneutes Senden nach einem Fehlschlag

- **WHEN** eine Übergabe gescheitert ist, die Ansicht geöffnet bleibt und die Verbindung wieder
  besteht
- **THEN** sendet „Erneut senden“ dasselbe vorbereitete PDF, und der Dienst erhält es

#### Scenario: Vorbereitetes Dokument fehlt

- **WHEN** das vorbereitete PDF beim Senden nicht mehr gelesen werden kann
- **THEN** meldet die App, dass das Dokument nicht mehr vorliegt und neu erfasst werden muss,
  und nicht „Senden fehlgeschlagen.“

#### Scenario: Kein späteres Nachholen

- **WHEN** eine Übergabe gescheitert ist und die Person die Ansicht schließt
- **THEN** wird das Dokument nicht später automatisch übergeben
