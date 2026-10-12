# Abnahme — Manuelle Prüfung gegen die echte Instanz

Diese Checkliste dient der manuellen Abnahme der iOS-App gegen eine echte Lector-Instanz im TestFlight-Build auf einem echten iPhone. Jeder Punkt wird gegen die live laufende Instanz (nicht Emulator/Simulator) durchlaufen.

**Testgerät:** iPhone (nicht iPad, da nur Hochformat unterstützt)  
**Build:** TestFlight-Build  
**Serveradresse:** Live-Produktivinstanz (z. B. `https://lector.nerd-wg.eu`)  
**Netzwerk:** echte Verbindung (nicht Simulator/Mock)

---

## 1. Einrichtung und Anmeldung

- [ ] **App startet und zeigt Einrichtungsformular**  
  Erwartung: Nach dem ersten Start erscheint ein Feld zur Eingabe der Serveradresse.

- [ ] **Produktivadresse eingeben, `/api/info` prüft die Version**  
  Eingabe: `lector.nerd-wg.eu`  
  Erwartung: App prüft `GET /api/info`, zeigt kurz „Verbindung wird geprüft", speichert die Adresse.

- [ ] **Anmeldung mit MFA-Code**  
  Eingabe: Gültiges Paperless-Konto mit aktiviertem MFA  
  Erwartung: App zeigt Felder für Nutzername, Passwort und MFA-Code. Nach Eingabe aller Daten wird die App angemeldet.

- [ ] **Nach Abmelden → Anmeldung bleibt möglich, Adresse erhalten**  
  Ablauf: Anmelden → Menü Abmelden → App zeigt Anmeldeformular  
  Erwartung: Serveradresse ist noch vorausgefüllt, Nutzername und Passwort sind geleert.

---

## 2. Live-Aktualisierung und Historie

- [ ] **Live-Aktualisierung durch den Reverse Proxy**  
  Ablauf: Scan hochladen vom iPhone, während die Historie auf der App offen ist  
  Erwartung: Neuer Vorgang erscheint **sofort** in der Liste (nicht erst nach Neustart oder manuellem Refresh). Der Proxy darf den SSE-Stream `/events` nicht puffern.

- [ ] **Zustandswechsel von `processing` zu `done` ist sichtbar**  
  Ablauf: Mehrere Seiten scanen und beobachten  
  Erwartung: Bei jeder Seitenverarbeitung wechselt der Seitenfortschritt (z. B. „1 / 3" → „2 / 3" → „3 / 3"), am Ende wechselt der Zustand von `processing` zu `done`.

---

## 3. Scan eines mehrseitigen Belegs

- [ ] **Mehrseitiger Scan (mindestens 3 Seiten)**  
  Ablauf: Menü + → Beleg scannen → 3 Seiten scannen → Speichern → „An Lector übergeben"  
  Erwartung: Ein einzelner Vorgang entsteht mit der richtigen Seitenzahl (z. B. `total_pages: 3`).

- [ ] **Scan ist durchsuchbar**  
  Ablauf: Scan mit erkennbarem Text (z. B. Betrag, Datum) hochladen → Nach Verarbeitung → Detail öffnen  
  Erwartung: Text ist in der PDF sichtbar und durchsuchbar (mit Strg+F im Browser auffindbar). Kein `OCR_MODE: skip` auf dem Paperless-Container; Dokumentation einhalten.

- [ ] **Begradigung ist unauffällig**  
  Ablauf: Scan absichtlich schief aufnehmen (ca. 15° Neigung) → Speichern → Verarbeitung beobachten  
  Erwartung: Das finale Scan-PDF ist gerade, ohne Qualitätsverlust. Die doppelte Begradigung (VisionKit im Scanner + Lector-Deskew) sollte nicht zu Verzerrungen führen.

---

## 4. Fotoauswahl

- [ ] **HEIC-Foto wird akzeptiert und konvertiert**  
  Ablauf: Aus Mediathek ein modernes iPhone-Foto (HEIC-Format) auswählen → Hochladen  
  Erwartung: Datei wird als PDF hochgeladen, nicht als HEIC. Der Vorgang verarbeitet korrekt.

- [ ] **Mehrere Fotos → Ein PDF mit mehreren Seiten**  
  Ablauf: 2–3 verschiedene Fotos auswählen → Hochladen  
  Erwartung: Ein einzelner Vorgang mit der Seitenanzahl der ausgewählten Fotos (z. B. `total_pages: 3`).

---

## 5. Flugmodus und Offline-Szenarien

- [ ] **Upload ohne Netz → Fehler mit „Erneut senden"**  
  Ablauf: Flugmodus einschalten → Scan hochladen → Upload-Fehler  
  Erwartung: Button „Erneut senden" wird angezeigt, Datei bleibt in der Upload-Ansicht.

- [ ] **„Erneut senden" funktioniert nach Flugmodus-Aus**  
  Ablauf: Nach Fehler (Flugmodus) → Flugmodus ausschalten (Netzwerk zurück) → „Erneut senden"  
  Erwartung: Upload erfolgreich. **Kein automatisches Nachholen** (die App wartet, bis die Person „Erneut senden" tippt).

- [ ] **Kein Nachholen nach App-Neustart**  
  Ablauf: Upload fehlgeschlagen → App beenden (nicht nur in den Hintergrund) → App neu starten  
  Erwartung: Die Upload-Ansicht ist leer. Keine Warteschlange. Die gescheiterte Datei ist weg.

---

## 6. E-Rechnung aus Mail

- [ ] **ZUGFeRD-PDF aus Mail teilen**  
  Ablauf: Mail-App → ZUGFeRD-rechnung.pdf → Teilen → Lector  
  Erwartung: Datei wird byte-genau unverändert hochgeladen. In der Historia wird der Vorgang mit `status: skipped_erechnung` und `doc_type: erechnung_pdf` angezeigt (nicht `done`).

- [ ] **E-Rechnung wird nicht nach `consume` kopiert**  
  Überprüfung: Dateisystem prüfen oder Lector-Log  
  Erwartung: Das Original geht zu `processed`, **nicht** zu `consume`. Paperless sieht die E-Rechnung nie (kein Duplikat in der Weboberfläche).

---

## 7. Teilen-Menü mit mehreren Dateitypen

- [ ] **Mehrere Dateien gleichzeitig teilen (PDF, XML, TIFF, Bild)**  
  Ablauf: Dateien-App oder Mail → PDF + XML + Bild auswählen (max. 20) → Lector teilen  
  Erwartung: Jede Datei wird einzeln hochgeladen, Ergebnisse werden einzeln angezeigt.

- [ ] **TIFF wird byte-genau hochgeladen**  
  Ablauf: Mehrseitiges TIFF (z. B. von Scanner) teilen  
  Erwartung: TIFF wird unverändert übergeben (nicht zu PDF konvertiert).

- [ ] **Textdatei wird abgewiesen**  
  Ablauf: `.txt`-Datei teilen  
  Erwartung: Hinweis „Datei ‚Beispiel.txt' wird nicht unterstützt", keine Hochladung.

- [ ] **Dateinamen mit Punkten funktionieren**  
  Ablauf: Datei wie `Rechnung 12.03.2025.pdf` oder `Beleg v2.1.pdf` teilen  
  Erwartung: Dateiname wird korrekt übergeben und im Server gespeichert.

---

## 8. Teilen vor der Anmeldung

- [ ] **Teilen-Menü zeigt Hinweis, wenn nicht angemeldet**  
  Ablauf: App installieren → Noch nicht konfiguriert → Datei teilen  
  Erwartung: Hinweis „Bitte zuerst in der Lector-App anmelden" (oder ähnlich), keine Hochladung.

- [ ] **Nach Anmeldung funktioniert Teilen sofort**  
  Ablauf: App konfigurieren und anmelden → Datei teilen (ohne App-Neustart)  
  Erwartung: Teilen funktioniert sofort, kein Neustart erforderlich.

---

## 9. Speicherlimit der Extension

- [ ] **Großes PDF > 100 MB wird erkannt**  
  Ablauf: PDF > 100 MB teilen  
  Erwartung: Extension zeigt Hinweis wie „Datei zu groß für die Extension" (nicht Crash, sondern klare Fehlermeldung).

---

## 10. Angehaltener Vorgang und Freigabe

- [ ] **Angehaltener Vorgang wird in der Historia angezeigt**  
  Ablauf: Scan mit Seitenzahl > Grenzwert hochladen → Status `blocked` beobachten  
  Erwartung: Vorgang zeigt `status: blocked`, Seitenzahl und Grenzwert sind sichtbar.

- [ ] **Detail öffnen und Freigabe bestätigen**  
  Ablauf: Detail-Ansicht → Button „Freigeben" → Bestätigungs-Alert → Bestätigen  
  Erwartung: Vorgang wird freigegeben, Status wechselt zu `done` (oder `failed` mit dem Fehler).

- [ ] **409-Szenario: Anderweitig entschieden**  
  Ablauf: Vorgang in der App als `blocked` zeigen → In Weboberfläche (gleichzeitig) freigeben → In App „Freigeben" versuchen  
  Erwartung: App zeigt Hinweis „Dieser Vorgang wurde inzwischen anders entschieden", lädt das Detail neu.

---

## Bewertung

**Platz für Datum, Build-Nummer und Gesamtergebnis:**

```
Datum:              _______________
Build-Nummer:       _______________
Gerät/iOS-Version:  _______________
Tester:             _______________

Gesamtergebnis:
  [ ] Bestanden (alle Punkte erfolgreich)
  [ ] Mit Vorbehalt (kleine Mängel, dokumentiert)
  [ ] Nicht bestanden (kritische Ausfälle)

Besonderheiten / Erkannte Mängel:
_________________________________________
_________________________________________
_________________________________________
```

---

## Hinweise zum Testen

- **Reverse Proxy:** Der SSE-Stream `/events` muss durch den Proxy fließen ohne Pufferung. Nginx-Beispiel: `proxy_buffering off;`. Siehe `feature-documentation/web-zugang.md` Abschnitt „SSE-Pufferung".
- **Testflight vs. Release:** Der TestFlight-Build kann Unterschiede zu einer Release-Version haben. Im Zweifelsfall nochmals testen, bevor auf den App Store geht.
- **Paperless-Integration:** Stellen Sie sicher, dass `PAPERLESS_OCR_MODE: skip` auf dem Webserver-Service gesetzt ist (sonst überschreibt Tesseract den Textlayer).
- **Zeitzone:** Uhrzeiten sollten in der Geräte-Zeitzone angezeigt werden. Verifizieren Sie durch Änderung der Systemzeit.
