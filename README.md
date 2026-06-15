# Lector

Lokaler OCR-Veredelungsservice **vor** Paperless-ngx. Lector überwacht einen Eingangsordner,
veredelt eingehende Dokumente (Bilder, PDF, TIFF) per Cloud-OCR (Google Document AI) zu
durchsuchbaren „Sandwich"-PDFs und legt sie in den geteilten `consume`-Ordner für den
automatischen Import in Paperless-ngx. E-Rechnungen (XRechnung, ZUGFeRD/Factur-X) werden
deterministisch erkannt und unverändert durchgereicht.

> Vollständige Anforderungen: [`prd/PRD_Lector.md`](prd/PRD_Lector.md) ·
> Stand der Umsetzung: [`prd/PROGRESS.md`](prd/PROGRESS.md)

## Entwicklung

```bash
# Abhängigkeiten installieren (inkl. Dev-Tools)
uv sync --extra dev

# Tests
uv run pytest                     # alle Tests
uv run pytest tests/test_xy.py    # eine Datei
uv run pytest -k name             # einzelner Test nach Muster

# Linting / Formatierung
uv run ruff check .
uv run ruff format .

# Lokal starten
uv run uvicorn app.main:app --reload --port 8001
```

Konfiguration ausschließlich über Umgebungsvariablen (siehe `app/config.py` und PRD §4.5).
Für lokale Entwicklung kann eine `.env` im Projektwurzelverzeichnis genutzt werden.

### Seitenorientierung

Lector dreht Seiten **nicht** selbst. Eine frühere lokale Auto-Rotate-Heuristik
(`PREPROCESS_AUTOROTATE`) wurde entfernt, weil sie korrekt ausgerichtete Seiten zufällig auf
den Kopf bzw. um 90° drehte: Ihr Maß (Varianz der Zeilensummen) ist für eine Seite und ihre
180°-Drehung identisch, sodass die Entscheidung nur über den Fließkomma-Rundungsfehler fiel.
Die Orientierung übernimmt nun die OCR-Engine (Document AI); die gerenderten Quellseiten sind
ohnehin bereits korrekt ausgerichtet. Es gibt entsprechend kein `PREPROCESS_AUTOROTATE`-Flag
mehr — nur noch `PREPROCESS_DESKEW` (Schieflagenkorrektur) und `PREPROCESS_CONTRAST`.

## Docker

```bash
docker build -t lector .
```

Der Service ist als zusätzlicher Container im bestehenden Paperless-ngx-Compose vorgesehen
(siehe `docker-compose.example.yml`). Wichtig: am Paperless-`webserver`
`PAPERLESS_OCR_MODE: skip` setzen, damit Tesseract den Document-AI-Textlayer nicht überschreibt.

## Google Document AI einrichten (Secrets)

Lector braucht zur OCR einen Google-Cloud-Document-AI-**Processor** und einen
**Service-Account-Schlüssel** (JSON). Document AI ist kostenpflichtig (Abrechnung pro Seite),
bietet aber ein monatliches Gratis-Kontingent. Schritt für Schritt:

1. **Google-Cloud-Projekt anlegen / wählen** in der [Cloud Console](https://console.cloud.google.com).
   Notiere die **Projekt-ID** (nicht den Anzeigenamen) → das ist später `GCP_PROJECT_ID`.
   Stelle sicher, dass für das Projekt die **Abrechnung (Billing)** aktiviert ist.

2. **Document AI API aktivieren:** Console → „APIs & Dienste" → „APIs aktivieren" →
   nach „Cloud Document AI API" suchen → **Aktivieren**.
   (CLI-Alternative: `gcloud services enable documentai.googleapis.com`.)

3. **Processor erstellen:** Console → „Document AI" → „Processors" → „Create Processor".
   - Typ: **Document OCR** (reine Texterkennung — genau was Lector braucht).
   - Region: **EU (Europäische Union)** wählen → entspricht `DOCAI_LOCATION=eu`
     (für Datenschutz/DSGVO; die Region muss zur ENV-Variable passen).
   - Nach dem Anlegen die **Processor-ID** kopieren (lange Hex-/ID-Zeichenfolge in den
     Processor-Details) → das ist `DOCAI_PROCESSOR_ID`.

4. **Service-Account anlegen:** Console → „IAM & Verwaltung" → „Dienstkonten" →
   „Dienstkonto erstellen". Name z. B. `lector-docai`.
   - Rolle zuweisen: **„Document AI API User"** (`roles/documentai.apiUser`).
     Diese Rolle genügt; vergib keine breiteren Rechte.

5. **JSON-Schlüssel erzeugen:** Auf das angelegte Dienstkonto klicken → Reiter „Schlüssel" →
   „Schlüssel hinzufügen" → „Neuen Schlüssel erstellen" → **JSON** → Herunterladen.
   Die heruntergeladene Datei in `lector/secrets/docai-sa.json` ablegen (siehe Schritt 1 unten).
   **Diese Datei ist ein Geheimnis** — niemals in Git committen, nur lesbar mounten (`:ro`).

CLI-Variante für Schritt 4–5 (optional, mit installiertem `gcloud`):

```bash
gcloud iam service-accounts create lector-docai \
    --display-name="Lector Document AI"

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="serviceAccount:lector-docai@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/documentai.apiUser"

gcloud iam service-accounts keys create docai-sa.json \
    --iam-account="lector-docai@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
```

Damit hast du die drei Werte `GCP_PROJECT_ID`, `DOCAI_PROCESSOR_ID`, `DOCAI_LOCATION=eu`
sowie die `docai-sa.json` — alles, was Lector zur OCR benötigt.

## Paperless-Integration: GiroCode & SevDesk-Export

Zusätzlich zum OCR-Veredelungspfad (`scan-in → consume`) bietet Lector ein **entkoppeltes
Zusatz-Feature**, das die Richtung umdreht: Es liest Rechnungen **aus** Paperless, erzeugt
GiroCode-QR-Codes für die Überweisung und exportiert getaggte Belege nach SevDesk — und schreibt
den Status (Zahldaten, Export-Zeitpunkt, „überwiesen") an das Paperless-Dokument zurück. Ein
Hintergrund-Worker gleicht dazu periodisch alle Dokumente des konfigurierten Rechnungs-
Dokumententyps ab; die Bedienung läuft über die Lector-UI unter `/invoices`.

Das Feature ist **standardmäßig deaktiviert** und stört den OCR-Pfad nicht. Es wird erst durch
`FEATURE_PAPERLESS_SYNC=true` (GiroCode) bzw. zusätzlich `FEATURE_SEVDESK_EXPORT=true` (SevDesk)
aktiv. Details: [`feature-documentation/paperless-integration/`](feature-documentation/paperless-integration/README.md).

### Umgebungsvariablen

Alle Variablen sind optional und haben Defaults — ohne `FEATURE_PAPERLESS_SYNC=true` bleiben sie
wirkungslos. Vollständige Vorlage in `.env.example`.

**Paperless-Abgleich (Voraussetzung für GiroCode und SevDesk):**

| ENV | Default | Bedeutung |
|---|---|---|
| `FEATURE_PAPERLESS_SYNC` | `false` | Haupt-Schalter. `true` aktiviert den periodischen Abgleich gegen die Paperless-API und die `/invoices`-UI. Bei `false` ist das gesamte Feature inaktiv. |
| `PAPERLESS_URL` | — | Basis-URL der Paperless-Instanz **ohne** abschließendes `/api` (im Compose-Netz z. B. `http://webserver:8000`). |
| `PAPERLESS_TOKEN` | — | API-Token aus Paperless (Profil → API-Token). Erforderlich für Lese- und Rückschreib-Zugriff. |
| `PAPERLESS_INVOICE_DOCTYPE` | `Rechnung` | Name des Paperless-**Dokumententyps**, der ein Dokument als Rechnung kennzeichnet. Nur solche Dokumente werden abgeglichen. |
| `PAPERLESS_SYNC_INTERVAL_SECONDS` | `300.0` | Intervall (Sekunden) zwischen zwei Abgleich-Läufen des Hintergrund-Workers. |
| `PAPERLESS_AUTO_CREATE_FIELDS` | `true` | Legt fehlende Paperless-Custom-Fields/-Tags (s. u.) beim Start automatisch an. Bei `false` müssen sie manuell in Paperless existieren. |

**GiroCode (EPC069-12-Überweisungs-QR):**

| ENV | Default | Bedeutung |
|---|---|---|
| `GIROCODE_CREDITOR_FROM_CORRESPONDENT` | `true` | Leitet den Gläubigernamen aus dem Paperless-**Korrespondenten** ab, falls er nicht aus dem Beleg (E-Rechnung-XML bzw. OCR-Heuristik) bestimmbar ist. |

**SevDesk-Export:**

| ENV | Default | Bedeutung |
|---|---|---|
| `FEATURE_SEVDESK_EXPORT` | `false` | Schalter für den Beleg-Upload nach SevDesk. Setzt einen aktiven Paperless-Sync voraus. |
| `SEVDESK_API_TOKEN` | — | API-Token deines SevDesk-Kontos. |
| `SEVDESK_BASE_URL` | `https://my.sevdesk.de/api/v1` | API-Endpunkt von SevDesk (i. d. R. unverändert lassen). |
| `SEVDESK_TAG` | `sevdesk` | Paperless-**Tag**, der ein Dokument für den Export vormerkt. Sobald ein Dokument diesen Tag trägt, wird es beim Sync erfasst. |
| `SEVDESK_AUTO_EXPORT` | `false` | `true` = automatischer Upload direkt beim Sync; `false` = nur vormerken, der eigentliche Export wird manuell in der `/invoices`-UI bestätigt. |

**Namen der Paperless-Custom-Fields / -Tags für den Rückschrieb** (anpassen, falls in Paperless
andere Bezeichnungen verwendet werden):

| ENV | Default | Bedeutung |
|---|---|---|
| `CF_GIRO_IBAN` | `Zahlung IBAN` | Custom Field für die erkannte Zahlungs-IBAN. |
| `CF_GIRO_AMOUNT` | `Zahlbetrag` | Custom Field für den Zahlbetrag. |
| `CF_SEVDESK_ID` | `SevDesk-Beleg` | Custom Field für die SevDesk-Beleg-ID nach erfolgtem Export. |
| `CF_EXPORTED_AT` | `SevDesk-Export am` | Custom Field für den Zeitpunkt des SevDesk-Exports. |
| `CF_PAID` | `Überwiesen` | Custom Field für den Bezahlt-Status. |
| `TAG_SEVDESK_DONE` | `sevdesk-exportiert` | Tag, der nach erfolgreichem Export am Dokument gesetzt wird. |
| `TAG_PAID` | `überwiesen` | Tag, der ein als bezahlt markiertes Dokument kennzeichnet. |

## Einbindung in Paperless-ngx auf dem Zettlab NAS

> **Hinweis zu Docker auf ZettaOS:** Der Zettlab NAS bringt eine Docker-Laufzeit mit, die sich
> über die **Docker-/Container-App** der Weboberfläche **oder** per **SSH** auf der Kommandozeile
> bedienen lässt. Die exakten Menübezeichnungen können je nach ZettaOS-Version abweichen — die
> SSH-Variante (`docker` / `docker compose` direkt im Stack-Ordner) ist versionsunabhängig und
> wird hier als verlässlicher Weg gezeigt. SSH aktivierst du in den Systemeinstellungen der NAS.

Lector wird als zusätzlicher Service in **denselben** Compose-Stack aufgenommen, damit er sich den
`consume`-Ordner direkt mit dem Paperless-`webserver` teilen kann.

### 1. Verzeichnisse auf dem NAS anlegen

Lege die Ordner für Lector auf einem freigegebenen Volume an (Pfad an die eigene
Zettlab-Freigabe anpassen, z. B. unter dem Share, in dem auch Paperless liegt):

```bash
# Verzeichnis des bestehenden Paperless-Stacks auf dem NAS
cd Teams/Docker/paperless-ngx-stack
mkdir -p lector/{processed,error,data,secrets} scan-in
```

- `scan-in` – Eingangsordner; hierhin scannt/legt der Scanner oder eine NAS-Freigabe die Dokumente.
- `consume` – existiert bereits aus dem Paperless-Stack und wird mit Lector **geteilt**.
- `lector/secrets` – nimmt die Google-Document-AI-Service-Account-JSON auf (`docai-sa.json`).

Lege außerdem die Service-Account-JSON aus dem Google-Abschnitt dort ab:

```bash
# docai-sa.json vom Rechner auf den NAS kopieren (Pfad/Host anpassen)
scp docai-sa.json sascha@<NAS-IP>:Teams/Docker/paperless-ngx-stack/lector/secrets/docai-sa.json
```

### 2. Lector-Image auf den NAS bringen

Es gibt (noch) kein veröffentlichtes Lector-Image — du baust es aus diesem Repo. Drei Wege,
je nachdem ob der NAS bauen darf und ob du eine Container-Registry nutzt:

**Variante A — direkt auf dem NAS bauen (einfachste, kein Registry-Konto nötig).**
Voraussetzung: SSH-Zugang und `git` auf dem NAS. Da Image und NAS dann dieselbe CPU-Architektur
haben, gibt es keine Plattformprobleme.

```bash
ssh sascha@<NAS-IP>
cd Teams/Docker/paperless-ngx-stack
git clone <repo-url> lector-src          # dieses Repo
docker build -t lector:latest ./lector-src
```

Im Compose dann `image: lector:latest` verwenden. Alternativ direkt aus dem Quellordner bauen
lassen — `build: ./lector-src` statt `image:` (siehe Schritt 3).

**Variante B — lokal bauen, über eine Registry verteilen.**
Auf deinem Rechner für die NAS-Architektur bauen und in eine Registry (Docker Hub / GHCR) pushen,
dann auf dem NAS ziehen. `uname -m` auf dem NAS zeigt die Architektur (`x86_64` → `linux/amd64`,
`aarch64` → `linux/arm64`).

```bash
# lokal — Zielplattform an den NAS anpassen
docker buildx build --platform linux/amd64 -t <user>/lector:latest --push .
# auf dem NAS
docker pull <user>/lector:latest
```

**Variante C — lokal bauen, als Datei kopieren (ohne Registry).**
Image lokal bauen, als Tar exportieren, auf den NAS kopieren und dort laden. Auch hier muss die
Build-Plattform zur NAS-Architektur passen (`--platform` wie in Variante B).

```bash
# lokal
docker build -t lector:latest .
docker save lector:latest | gzip > lector.tar.gz
scp lector.tar.gz sascha@<NAS-IP>:Teams/Docker/paperless-ngx-stack/
# auf dem NAS
gunzip -c lector.tar.gz | docker load
```

Bei B und C im Compose `image: <user>/lector:latest` bzw. `image: lector:latest` eintragen.

### 3. Lector-Service in den Paperless-Compose aufnehmen

Ergänze in der bestehenden `docker-compose.yml` von Paperless (neben `webserver`, `db`, `broker`
usw.) den `lector`-Service. Trage bei `image:` den in Schritt 2 gewählten Namen ein — oder ersetze
die Zeile durch `build: ./lector-src`, wenn der NAS direkt aus dem Quellordner bauen soll. Auf dem
Host wird derselbe `./consume`-Ordner gemountet wie beim `webserver` (dort als
`/usr/src/paperless/consume`), sodass beide Container denselben Ordner teilen:

```yaml
  lector:
    image: lector:latest             # oder: build: ./lector-src
    restart: unless-stopped
    ports:
      - "8001:8001"                    # Web-UI / API (nur LAN)
    volumes:
      - ./scan-in:/scan-in
      - ./consume:/consume             # gleicher Host-Ordner wie beim webserver
      - ./lector/processed:/processed
      - ./lector/error:/error
      - ./lector/data:/data
      - ./lector/secrets:/secrets:ro
    environment:
      OCR_PROVIDER: documentai
      GCP_PROJECT_ID: BITTE_AENDERN
      DOCAI_LOCATION: eu
      DOCAI_PROCESSOR_ID: BITTE_AENDERN
      GOOGLE_APPLICATION_CREDENTIALS: /secrets/docai-sa.json
      TZ: Europe/Berlin
      PUID: 1000
      PGID: 1000
```

> Hinweis: Der `webserver`-Service mountet `./consume:/usr/src/paperless/consume`. Lector mountet
> denselben Host-Ordner `./consume` (intern als `/consume`) — die Container-internen Pfade dürfen
> sich unterscheiden, der **Host-Pfad** muss identisch sein.

Die vollständige Liste der Umgebungsvariablen steht in `docker-compose.example.yml` und `.env.example`.

### 4. Paperless-webserver anpassen

Im `environment`-Block des bestehenden `webserver`-Service `PAPERLESS_OCR_MODE: skip` ergänzen,
damit Tesseract den von Lector eingebetteten Document-AI-Textlayer nicht erneut überschreibt:

```yaml
  webserver:
    environment:
      # ... bestehende Variablen (PAPERLESS_REDIS, PAPERLESS_DBHOST, …) ...
      PAPERLESS_OCR_MODE: skip
```

> Dein Stack setzt bereits `PAPERLESS_OCR_LANGUAGE: deu` und `USERMAP_UID/GID: 1000` — letztere
> passen zu Lectors `PUID/PGID: 1000`, sodass Paperless die von Lector geschriebenen PDFs lesen kann.

### 5. Eigentümerschaft (PUID/PGID)

Auf dem Zettlab NAS prüfen, mit welcher UID/GID Paperless schreibt, und Lector über `PUID`/`PGID`
auf **denselben** Wert setzen (Standard `1000:1000`). Nur so kann Paperless die von Lector nach
`consume` geschriebenen PDFs lesen. UID/GID des aktuellen Benutzers per SSH ermitteln:

```bash
id            # liefert uid=… gid=…
```

### 6. Stack starten

Über die Container-App der NAS neu bereitstellen („Stack aktualisieren/neu erstellen") oder per SSH
im Stack-Ordner. Bei `build:` zusätzlich `--build` mitgeben, damit das Image (neu) gebaut wird:

```bash
cd Teams/Docker/paperless-ngx-stack
docker compose up -d lector              # bzw. `--build` bei build:-Variante
docker compose up -d webserver           # nach Änderung von PAPERLESS_OCR_MODE neu starten
docker compose logs -f lector            # Start prüfen
```

Die Lector-Web-UI ist anschließend im LAN unter `http://<NAS-IP>:8001` erreichbar. Es gibt
**keine** Authentifizierung — der Betrieb ist ausschließlich für das LAN vorgesehen.
