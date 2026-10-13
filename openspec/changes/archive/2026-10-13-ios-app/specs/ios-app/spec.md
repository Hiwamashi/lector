# Spec Delta

## Purpose

Beschreibt das Verhalten der iOS-App. Mit ihr gibt man Belege vom iPhone an Lector, per Scan,
Foto oder Teilen-Menü, und verfolgt den Stand der Verarbeitung wie im Dashboard. Dazu gehört
die Entscheidung über angehaltene Vorgänge.

## ADDED Requirements

### Requirement: Die Serveradresse wird bei der Einrichtung eingegeben und gespeichert

Die App MUSS beim ersten Start nach der Adresse des Lector-Dienstes fragen. Bevor sie die
Adresse übernimmt, MUSS sie prüfen, ob dort ein Lector mit einer unterstützten Version der
Schnittstelle antwortet, und den Zugangsmodus ermitteln. Eine bestätigte Adresse MUSS die App
dauerhaft speichern, damit sie nach einem Neustart nicht erneut abgefragt wird. Bei einer
späteren Einrichtung MUSS die zuletzt bestätigte Adresse vorausgefüllt sein. Eine Adresse
ohne verschlüsselte Verbindung MUSS die App ablehnen, außer sie verweist ins lokale Netz.

#### Scenario: Gültige Adresse

- **WHEN** eine Person die Adresse eines erreichbaren Lector-Dienstes eingibt
- **THEN** übernimmt die App die Adresse und fährt mit der Anmeldung fort, im Modus `none`
  direkt mit der Historie

#### Scenario: Adresse ohne Lector

- **WHEN** unter der eingegebenen Adresse kein Lector antwortet
- **THEN** speichert die App die Adresse nicht und meldet, dass dort kein Lector gefunden wurde

#### Scenario: Unverschlüsselte öffentliche Adresse

- **WHEN** eine Adresse mit `http://` außerhalb des lokalen Netzes eingegeben wird
- **THEN** lehnt die App sie mit Hinweis auf die fehlende Verschlüsselung ab

#### Scenario: Neustart der App

- **WHEN** die App nach erfolgreicher Einrichtung beendet und neu gestartet wird
- **THEN** verwendet sie die gespeicherte Adresse, ohne erneut danach zu fragen

### Requirement: Die App meldet sich wie die Weboberfläche an

Im Modus `paperless` MUSS die App eine Anmeldung mit Nutzername, Passwort und einem
optionalen MFA-Code anbieten. Sie MUSS die vier Ablehnungsgründe des Dienstes unterscheidbar
anzeigen: Anmeldung fehlgeschlagen, MFA-Code erforderlich, Paperless nicht erreichbar und
vorübergehend gebremst. Den erhaltenen Zugangsschlüssel MUSS die App ausschließlich im
geschützten Schlüsselspeicher des Geräts aufbewahren, sodass nur die App und ihre
Teilen-Erweiterung ihn lesen können. Passwort und MFA-Code DARF die App NICHT speichern. Im
Modus `none` DARF die App keine Anmeldung verlangen.

#### Scenario: Anmeldung mit MFA

- **WHEN** eine Person Nutzername, Passwort und gültigen MFA-Code eines Paperless-Kontos
  eingibt
- **THEN** ist die App angemeldet und zeigt die Historie

#### Scenario: MFA-Code vergessen

- **WHEN** die Anmeldung ohne MFA-Code mit dem Grund „MFA-Code erforderlich“ abgelehnt wird
- **THEN** fordert die App ausdrücklich zur Eingabe des MFA-Codes auf, und Nutzername und
  Passwort bleiben eingetragen

#### Scenario: Paperless nicht erreichbar

- **WHEN** die Anmeldung mit dem Grund „Paperless nicht erreichbar“ abgelehnt wird
- **THEN** meldet die App diesen Grund und nicht falsche Anmeldedaten

### Requirement: Eine abgelaufene Sitzung führt zurück zur Anmeldung

Antwortet der Dienst auf eine Anfrage mit „nicht angemeldet“, MUSS die App den gespeicherten
Zugangsschlüssel verwerfen und zur Anmeldung wechseln. Die gespeicherte Serveradresse MUSS
dabei erhalten bleiben. Ein Netzwerkfehler oder ein Serverfehler DARF NICHT zum Verwerfen des
Schlüssels führen.

#### Scenario: Sitzung beim Dienst beendet

- **WHEN** die Sitzung der App beim Dienst nicht mehr besteht und die App die Historie lädt
- **THEN** zeigt die App die Anmeldung mit der bisherigen Serveradresse

#### Scenario: Server vorübergehend nicht erreichbar

- **WHEN** der Dienst während der Nutzung nicht erreichbar ist
- **THEN** meldet die App die fehlende Verbindung und bleibt angemeldet

### Requirement: Die Person kann sich abmelden und den Server wechseln

Die App MUSS eine Abmeldung anbieten. Dabei beendet sie die Sitzung beim Dienst, soweit er
erreichbar ist, und verwirft den Zugangsschlüssel auf dem Gerät in jedem Fall. Die App MUSS
außerdem erlauben, eine andere Serveradresse einzurichten. Ein Wechsel des Servers MUSS die
Anmeldung beim bisherigen Server beenden.

#### Scenario: Abmelden ohne Verbindung

- **WHEN** eine Person sich abmeldet, während der Dienst nicht erreichbar ist
- **THEN** ist die App trotzdem abgemeldet, und der Zugangsschlüssel ist vom Gerät entfernt

#### Scenario: Server wechseln

- **WHEN** eine Person eine andere Serveradresse einrichtet
- **THEN** ist die Anmeldung beim bisherigen Server auf dem Gerät beendet, und die App prüft
  die neue Adresse wie bei der Ersteinrichtung

### Requirement: Die Historie zeigt Bestand und Vorgänge wie das Dashboard

Die App MUSS die Zähler je Zustand und die Liste der Vorgänge anzeigen, neueste zuerst. Zu
jedem Vorgang zeigt sie Dateiname, Zustand und Anlagezeitpunkt, bei laufender Verarbeitung
auch den Seitenfortschritt. Sie MUSS nach Zustand, Suchbegriff und Zeitraum filtern können
und ältere Vorgänge nachladen können. Zeitpunkte MUSS die App in der Zeitzone des Geräts
anzeigen. Die Historie MUSS sich manuell aktualisieren lassen.

#### Scenario: Historie öffnen

- **WHEN** eine angemeldete Person die App öffnet
- **THEN** sieht sie die Zähler je Zustand und die neuesten Vorgänge

#### Scenario: Nach Zustand filtern

- **WHEN** eine Person den Filter „gescheitert“ wählt
- **THEN** zeigt die Liste nur gescheiterte Vorgänge, und die Zähler zeigen weiterhin den
  gesamten Bestand

### Requirement: Die Historie aktualisiert sich von selbst, solange die App sichtbar ist

Solange die App im Vordergrund ist, MUSS sie Änderungen an Vorgängen ohne Zutun der Person
anzeigen, auch neu angelegte Vorgänge. Bricht die Verbindung für die Live-Aktualisierung ab,
MUSS die App sie selbstständig wieder aufbauen. Danach MUSS sie den Stand nachladen, damit
keine Änderung verloren geht. Im Hintergrund DARF die App keine Verbindung offen halten.

#### Scenario: Beleg wird verarbeitet

- **WHEN** die Historie geöffnet ist und ein Vorgang von `processing` nach `done` wechselt
- **THEN** zeigt die App den neuen Zustand ohne manuelles Aktualisieren

#### Scenario: Rückkehr aus dem Hintergrund

- **WHEN** die App nach einiger Zeit im Hintergrund wieder in den Vordergrund kommt
- **THEN** lädt sie den aktuellen Stand und nimmt die Live-Aktualisierung wieder auf

### Requirement: Das Detail zeigt den Verlauf und erlaubt Entscheidungen

Die App MUSS zu einem Vorgang seine Angaben und den Verlauf in zeitlicher Reihenfolge
anzeigen. Bei einem angehaltenen Vorgang MUSS sie die festgestellte Seitenzahl und die
Seitenobergrenze nennen und beide Entscheidungen anbieten, Freigeben und Verwerfen. Eine
Entscheidung MUSS die Person vor dem Absenden ausdrücklich bestätigen. Meldet der Dienst,
dass der Vorgang nicht mehr angehalten ist, MUSS die App dies anzeigen und den aktuellen
Stand nachladen.

#### Scenario: Angehaltenen Vorgang freigeben

- **WHEN** eine Person bei einem angehaltenen Vorgang „Freigeben“ wählt und bestätigt
- **THEN** sendet die App die Freigabe und zeigt den aktualisierten Vorgang

#### Scenario: Bereits anderweitig entschieden

- **WHEN** eine Person einen Vorgang verwirft, der inzwischen in der Weboberfläche freigegeben
  wurde
- **THEN** meldet die App, dass der Vorgang nicht mehr angehalten ist, und zeigt den aktuellen
  Stand

### Requirement: Scans und Fotos werden als ein PDF übergeben

Die App MUSS das Scannen von Belegen mit der Kamera anbieten, mit Erkennung der
Dokumentkanten und mehreren Seiten je Beleg. Außerdem MUSS sie die Auswahl von Fotos aus der
Mediathek des Geräts anbieten. Die Seiten eines Scans bzw. die ausgewählten Fotos MUSS die App
auf dem Gerät zu einem einzigen PDF zusammenfassen und als eine Datei übergeben. Ein Bild DARF
NICHT in seinem ursprünglichen Bildformat übergeben werden. Nach der Übergabe MUSS die App die
Annahme bestätigen, ohne auf die Verarbeitung zu warten.

#### Scenario: Dreiseitiger Scan

- **WHEN** eine Person einen Beleg mit drei Seiten scannt und absendet
- **THEN** übergibt die App genau ein PDF mit drei Seiten, und daraus entsteht ein einziger
  Vorgang

#### Scenario: Foto im HEIC-Format

- **WHEN** eine Person ein Foto im HEIC-Format aus der Mediathek wählt und absendet
- **THEN** übergibt die App ein PDF mit diesem Bild und keine HEIC-Datei

### Requirement: Über das Teilen-Menü übergebene Dokumente bleiben unverändert

Die App MUSS im Teilen-Menü des Systems als Ziel erscheinen. PDF-, XML- und TIFF-Dateien
MUSS sie byte-genau unverändert übergeben, damit E-Rechnungen als solche erkannt werden.
Geteilte Bilder in anderen Formaten MUSS sie wie Fotos zu einem PDF umwandeln. Andere
Dateiarten MUSS sie mit Nennung des Dateinamens zurückweisen. Mehrere geteilte Dokumente
MUSS sie als jeweils eigene Datei übergeben. Ist die App noch nicht eingerichtet oder nicht
angemeldet, MUSS das Teilen-Menü darauf hinweisen und DARF nichts übergeben.

#### Scenario: ZUGFeRD-Rechnung aus einer Mail

- **WHEN** eine Person eine ZUGFeRD-PDF aus der Mail-App an Lector teilt
- **THEN** wird die Datei byte-genau unverändert übergeben und von Lector als E-Rechnung
  erkannt

#### Scenario: Nicht angemeldet

- **WHEN** eine Person eine Datei an Lector teilt, ohne in der App angemeldet zu sein
- **THEN** weist das Teilen-Menü darauf hin, dass zuerst die Anmeldung in der App nötig ist,
  und übergibt nichts

#### Scenario: Nicht unterstützte Datei

- **WHEN** eine Person eine Textdatei an Lector teilt
- **THEN** wird sie nicht übergeben, und das Teilen-Menü nennt die Datei als nicht unterstützt

### Requirement: Ohne Verbindung wird nichts zwischengespeichert

Die App MUSS für jede Übergabe eine Verbindung zum Dienst voraussetzen. Scheitert eine
Übergabe, MUSS die App den Fehlschlag melden. Solange die Ansicht geöffnet ist, MUSS sie ein
erneutes Senden des vorbereiteten Dokuments anbieten. Eine Warteschlange, die Übergaben
später selbstständig nachholt, DARF es NICHT geben.

#### Scenario: Upload ohne Netz

- **WHEN** eine Person einen Scan absendet, während keine Verbindung zum Dienst besteht
- **THEN** meldet die App den Fehlschlag und bietet erneutes Senden an

#### Scenario: Kein späteres Nachholen

- **WHEN** eine Übergabe gescheitert ist und die Person die Ansicht schließt
- **THEN** wird das Dokument nicht später automatisch übergeben
