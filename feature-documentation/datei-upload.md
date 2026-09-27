# Datei-Upload über das Web-UI

**Module:** `app/main.py` (Endpunkt `POST /upload`), `app/fileops.py` (`sanitize_upload_filename`, `store_upload`), `app/templates/dashboard.html` (Formular + Rückmeldungen)

## Zweck und Abgrenzung

Das Web-UI erlaubt das Hochladen von Dokumente (Bilder, PDF, TIFF) ohne Datei-Manager oder NAS-Zugriff. Der Upload **endet an der Ablage im Eingangsordner** (`WATCH_DIR`); ab dort folgt der Datei die bestehende Verarbeitungs-Pipeline aus [Watch-Folder](watch-folder.md) und [Format-Erkennung & E-Rechnungs-Bypass](format-erkennung-erechnung.md). Das Web-UI tritt also nicht in die Verarbeitung ein — es schiebt die Datei nur in die Warteschlange, wie eine NAS-Kopie das täte.

Authentifizierung und Größenbegrenzung bleiben ausgeschlossen (LAN-only, PRD §3.3).

## Endpunkt: `POST /upload`

Der Endpunkt `async def upload(request: Request, files: Annotated[list[UploadFile] | None, File()] = None)` nimmt `multipart/form-data` mit einem `files`-Feld entgegen.

Vier Schritte:

1. **Name-Absicherung** via `sanitize_upload_filename()` — der Client-Name kann Pfad-Komponenten oder falsche Zeichen enthalten. Die Funktion entfernt Verzeichnis-Trennzeichen und meldet den eingegrenzten Namen. Ein leerer oder nur aus Punkten bestehender Name (`.`, `..`) wird als „unbrauchbar" zurückgewiesen.

2. **Format-Prüfung** via `detection.is_supported(Path(name))` — nur unterstützte Formate werden akzeptiert. Im Gegensatz zur stillen Übergängnis im Watch-Folder wird ein abgelehntes Format im Dashboard als Rückmeldung angezeigt.

3. **Ablage im Eingangsordner** via `store_upload()` über `loop.run_in_executor(None, …)` — das ist asyncios **Default-Executor**, kein eigener Thread-Pool, und genau der Executor, den auch `Worker._scan_loop` für `scan_dir`/`_intake_file` benutzt (`app/worker.py`). Entkoppelt ist damit nur der serielle **Verarbeitungs-Pool** des Workers von der Aufnahme, nicht die Aufnahme von dessen Executor — auf Geräten mit wenigen Kernen können parallele Uploads den Default-Executor belegen und den Scan-Lauf verzögern. Das ist trotzdem nötig, weil das Schreiben blockiert und den Event-Loop (UI, SSE) nicht aufhalten darf.

4. **Rückmeldung** über Query-Parameter des Redirect-Ziels (s. u. „Rückmeldung").

### Namensabsicherung (`sanitize_upload_filename`)

```python
def sanitize_upload_filename(raw: str) -> str:
    """Reduziert einen client-gelieferten Namen auf einen unmittelbaren Dateinamen."""
    name = raw.strip()
    name = name.replace("\\", "/").rsplit("/", 1)[-1]  # Letzter Bestandteil nach /
    name = name.strip()
    if name == "" or set(name) == {"."}:  # Leer oder nur Punkte?
        return ""
    return name
```

Windows-Clients liefern Backslashes als Pfad-Trenner; beide Trennzeichen werden normalisiert, nur der Dateiname (nach dem letzten `/`) bleibt übrig. Namen wie `.`, `..`, `...` würden das aktuelle/übergeordnete Verzeichnis darstellen — sinnlos und potentiell gefährlich. Sie liefern `""`, das der Aufrufer wie eine nicht unterstützte Endung behandelt.

Kein Ersatzname wird erfunden, da der Nutzer diesen nicht explizit angegeben hat.

### Ablage im Eingangsordner (`store_upload`)

Die Funktion `store_upload(source: BinaryIO, directory: Path, filename: str, *, partial_suffix: str, chunk_size: int = 1 << 20) -> Path` schreibt kollisionsfrei und macht die Datei erst nach Abschluss sichtbar.

**Das Stabilitätsfenster-Problem:**

Der Watch-Folder überwacht neue Dateien mit zwei Strategien (siehe [watch-folder.md](watch-folder.md)):
1. Dateien mit Teil-Suffix (`.tmp`, `.part`, `.crdownload`) gelten nie als fertig.
2. Reguläre Dateien gelten als bereit, wenn ihre Größe über `STABILITY_WINDOW_SECONDS` (Standard 6 s) unverändert bleibt.

Würde der Upload eine Datei direkt unter ihrem Zielnamen schreiben, könnte eine unterbrochene Übertragung vom Stabilitätsfenster als vollständig gewertet werden — das Fenster misst nur die Größenkonstanz der *existierenden* Datei. Ein halbes PDF könnte in die Verarbeitung gehen.

**Die Lösung — Schreiben unter Zwischenpfad + atomares Umbenennen:**

```
1. Schreibe Dateiinhalt unter einem Zwischenpfad mit Suffix (z. B. „scan.pdf.part")
2. Erst nach erfolgreichem Schreiben: os.replace() auf den Zielnamen
   → Der Zielname existiert dann nie unvollständig
   → Der Watch-Folder sieht das Stabilitätsfenster nur für die komplette Datei
```

Details:

- Der Zielpfad wird über `unique_target(directory, filename)` provisorisch bestimmt — Basis für den Zwischenpfad `provisional_target.with_name(provisional_target.name + partial_suffix)`.
- Kollidiert bereits der Zwischenpfad (Leiche eines abgebrochenen früheren Uploads), wird numerisch ausgewichen: `scan.pdf_1.part`, `scan.pdf_2.part`, usw.
- Der Stream wird blockweise geschrieben (Standard 1 MiB `chunk_size`). Fehler lösen ein `try-except` aus, das die Zwischendatei aufräumt (best effort).
- Unmittelbar vor `os.replace()` wird **unter einem Lock** (`_replace_lock`) die Zielnamen-Entscheidung wiederholt. Sonst könnten zwei gleichzeitige Uploads mit demselben Namen beide denselben freien Zielnamen sehen (beide Zieldateien existieren zu Beginn noch nicht) und der zweite `os.replace()` würde das Ergebnis des ersten lautlos überschreiben. Das Schreiben der Zwischendatei bleibt außerhalb des Locks und damit parallel; serialisiert wird nur die kurze Namensentscheidung.

Der Lock schützt nur gegen gleichzeitige Uploads **im eigenen Prozess** (Thread-Pool). Gegen einen externen Schreiber auf demselben Verzeichnis (z. B. eine SMB-Kopie im gleichen Moment) hilft der Lock nicht — dieser Wettlauf steckt unverändert bereits in `unique_target()` und betrifft den gesamten Code.

### Rückmeldung über Query-Parameter

Nach dem Upload wird zum Dashboard (`GET /`) mit Query-Parametern umgeleitet:
- `?upload_ok=N` — Anzahl erfolgreich ablagerter Dateien
- `?upload_format=name1&upload_format=name2` — abgelehnte Dateien (nicht unterstütztes Format)
- `?upload_fehler=name1&upload_fehler=name2` — Fehler beim Speichern

Das Dashboard (Route `GET /`) in `app/main.py` wertet diese Parameter aus und zeigt Erfolgs-, Info- und Fehlermeldungen. Sie stehen im Query-String und bleiben deshalb bei einem einfachen Neuladen der Seite (F5) sichtbar — sie verschwinden erst bei einer Navigation, die die Parameter fallen lässt (z. B. Klick auf eine Kachel oder das Filter-Formular).

**Warum kein Flash-Speicher?**

Flash-Speicher (Session-Daten) bräuchte eine Session-Middleware. Das Projekt hat absichtlich keine Authentifizierung und damit keine Session-Infrastruktur. Query-Parameter sind stateless und ausreichend. Die Rückmeldungen sind transient (einmalig), daher ist Verschlüsselung und CSRF-Schutz nicht nötig.

## Verzögerte Sichtbarkeit

Eine hochgeladene Datei erscheint **nicht sofort** in der Dashboard-Übersicht, obwohl sie schon im Eingangsordner liegt:

1. Der Eingangsordner wird alle `POLL_INTERVAL_SECONDS` (Standard **2 s**) oder bei watchdog-Weckung gescannt.
2. Eine neu sichtbare Datei wird erst als „ready" emittiert, wenn ihre Größe über `STABILITY_WINDOW_SECONDS` (Standard **6 s**) unverändert bleibt.

Daher: ein Upload mit sofortiger Sichtbarkeit könnte **bis zu 2 + 6 = 8 Sekunden** dauern, bis die Datei in der Dashboard-Tabelle erscheint.

Dies ist **Absicht**. Ein Upload vom lokalen PC ist schneller als vom Netzwerk; würde die Sichtbarkeit sofort erfolgen, könnte man nicht sicher sein, ob eine schleppend erscheinende Datei noch hochgeladen wird oder schon vollständig ist.

## Bewusst ausgelassen

- **Authentifizierung** — Betrieb LAN-only, Einzelnutzer (PRD §3.3).
- **Größenbegrenzung** — der Anwender haftet für Speicher und Netzwerk.
- **Vorgezogene Dublettenprüfung** — ein Upload mit demselben Dateinamen startet trotzdem. Die Dublettenerkennung läuft später durch die bestehende Logik (`find_by_hash_active` im Watch-Folder).
- **Kamera-Aufnahme** (Web-API) — der Input ist HTML `<input type="file">`, keine `<input capture>`.
- **Zusammenfassen mehrerer Bilder zu einem Dokument** — jede Datei ist ein Vorgang, wie im Watch-Folder.

## Rückmeldungs-UI

Das Dashboard zeigt nach Upload:

```html
{% if upload_ok %}
<div class="notice">
  {{ upload_ok }} Datei(en) übernommen. Der Vorgang erscheint erst nach einigen Sekunden
  in der Übersicht — der Eingangsordner nimmt eine Datei erst auf, wenn ihre Größe über
  das Stabilitätsfenster unverändert bleibt.
</div>
{% endif %}

{% if upload_format %}
<div class="alert">
  <p>Nicht übernommen:</p>
  <ul>
    {% for name in upload_format %}
    <li>{{ name }} — nicht unterstütztes Format</li>
    {% endfor %}
  </ul>
</div>
{% endif %}

{% if upload_fehler %}
<div class="alert">
  <p>Nicht übernommen:</p>
  <ul>
    {% for name in upload_fehler %}
    <li>{{ name }} — konnte nicht gespeichert werden</li>
    {% endfor %}
  </ul>
</div>
{% endif %}
```

Die Meldungen sind **nicht persistent** im Sinne eines serverseitigen Zustands — sie stecken im Query-String des Redirect-Ziels. Ein Neuladen der Seite zeigt sie deshalb erneut; sie verschwinden erst, wenn eine Navigation die Parameter fallen lässt (Filter-Formular, Klick auf eine Kachel).
