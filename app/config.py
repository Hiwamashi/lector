"""Zentrale Konfiguration — ausschließlich über Umgebungsvariablen (siehe PRD §4.5)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OCR-Engine
    ocr_provider: str = Field(default="documentai", alias="OCR_PROVIDER")
    gcp_project_id: str = Field(default="", alias="GCP_PROJECT_ID")
    docai_location: str = Field(default="eu", alias="DOCAI_LOCATION")
    docai_processor_id: str = Field(default="", alias="DOCAI_PROCESSOR_ID")
    google_application_credentials: str = Field(
        default="", alias="GOOGLE_APPLICATION_CREDENTIALS"
    )

    # Ordnerpfade
    watch_dir: Path = Field(default=Path("/scan-in"), alias="WATCH_DIR")
    consume_dir: Path = Field(default=Path("/consume"), alias="CONSUME_DIR")
    processed_dir: Path = Field(default=Path("/processed"), alias="PROCESSED_DIR")
    error_dir: Path = Field(default=Path("/error"), alias="ERROR_DIR")
    db_path: Path = Field(default=Path("/data/lector.db"), alias="DB_PATH")

    # Lifecycle / Retry / Retention
    processed_retention_days: int = Field(default=30, alias="PROCESSED_RETENTION_DAYS")
    retry_delay_minutes: int = Field(default=15, alias="RETRY_DELAY_MINUTES")
    retry_max: int = Field(default=3, alias="RETRY_MAX")
    chunk_size_pages: int = Field(default=15, alias="CHUNK_SIZE_PAGES")
    # Obergrenze je Dokument, geprüft VOR dem ersten OCR-Aufruf. Jede Seite kostet bei
    # Document AI Geld; ein irrtümlich eingelegter Massenscan soll anhalten statt
    # durchzulaufen. 0 oder kleiner schaltet die Prüfung ab.
    max_pages_per_document: int = Field(default=100, alias="MAX_PAGES_PER_DOCUMENT")
    # Verfallsfrist bewahrter OCR-Teilergebnisse. Lang genug für jede Retry-Kette,
    # kurz genug, dass Reste eines abgestürzten Laufs nicht liegen bleiben.
    # 0 oder kleiner schaltet nur das Verfallen ab, nicht das Aufräumen abgeschlossener
    # Vorgänge — deren Einträge werden immer entfernt.
    chunk_cache_retention_days: int = Field(default=7, alias="CHUNK_CACHE_RETENTION_DAYS")

    # Vorverarbeitung (Orientierung übernimmt Document AI, kein lokales Auto-Rotate)
    preprocess_deskew: bool = Field(default=True, alias="PREPROCESS_DESKEW")
    preprocess_contrast: bool = Field(default=True, alias="PREPROCESS_CONTRAST")

    # Watch-Folder-Vollständigkeitsprüfung
    poll_interval_seconds: float = Field(default=2.0, alias="POLL_INTERVAL_SECONDS")
    stability_window_seconds: float = Field(default=6.0, alias="STABILITY_WINDOW_SECONDS")
    partial_suffixes: str = Field(default=".tmp,.part,.crdownload", alias="PARTIAL_SUFFIXES")

    # Throttling gegen Document-AI-Quota
    docai_max_pages_per_minute: int = Field(default=120, alias="DOCAI_MAX_PAGES_PER_MINUTE")

    # Ausgabe-Eigentümerschaft (geteilter consume-Ordner mit Paperless)
    puid: int = Field(default=1000, alias="PUID")
    pgid: int = Field(default=1000, alias="PGID")

    # Sonstiges
    tz: str = Field(default="Europe/Berlin", alias="TZ")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8001, alias="PORT")

    # ---- Paperless-Integration (entkoppeltes Feature-Set: GiroCode + SevDesk) ----
    # Schaltet den periodischen Abgleich gegen die Paperless-API frei.
    feature_paperless_sync: bool = Field(default=False, alias="FEATURE_PAPERLESS_SYNC")
    paperless_url: str = Field(default="", alias="PAPERLESS_URL")
    paperless_token: str = Field(default="", alias="PAPERLESS_TOKEN")
    # Öffentliche, im Browser erreichbare Paperless-URL für den "In Paperless öffnen"-Link.
    # Im Compose-Stack ist PAPERLESS_URL die container-interne Adresse (http://webserver:8000),
    # die im Browser nicht auflösbar ist — daher hier die externe URL setzen.
    # Leer = Fallback auf paperless_url.
    paperless_public_url: str = Field(default="", alias="PAPERLESS_PUBLIC_URL")
    # Name des Paperless-Dokumententyps, der Rechnungen kennzeichnet.
    paperless_invoice_doctype: str = Field(default="Rechnung", alias="PAPERLESS_INVOICE_DOCTYPE")
    paperless_sync_interval_seconds: float = Field(
        default=300.0, alias="PAPERLESS_SYNC_INTERVAL_SECONDS"
    )
    # Wenn Custom Fields / Tags in Paperless fehlen, legt Lector sie automatisch an.
    paperless_auto_create_fields: bool = Field(
        default=True, alias="PAPERLESS_AUTO_CREATE_FIELDS"
    )

    # GiroCode: Gläubigername aus dem Paperless-Korrespondenten ableiten, falls nicht im Beleg.
    girocode_creditor_from_correspondent: bool = Field(
        default=True, alias="GIROCODE_CREDITOR_FROM_CORRESPONDENT"
    )

    # SevDesk-Export
    feature_sevdesk_export: bool = Field(default=False, alias="FEATURE_SEVDESK_EXPORT")
    sevdesk_api_token: str = Field(default="", alias="SEVDESK_API_TOKEN")
    sevdesk_base_url: str = Field(default="https://my.sevdesk.de/api/v1", alias="SEVDESK_BASE_URL")
    # Paperless-Tag, der den Export nach SevDesk auslöst.
    sevdesk_tag: str = Field(default="sevdesk", alias="SEVDESK_TAG")
    # true = automatischer Export beim Sync, false = nur Vormerken (manuelle Bestätigung im UI).
    sevdesk_auto_export: bool = Field(default=False, alias="SEVDESK_AUTO_EXPORT")

    # Namen der Paperless-Custom-Fields / -Tags für den Rückschrieb.
    cf_giro_iban: str = Field(default="Zahlung IBAN", alias="CF_GIRO_IBAN")
    cf_giro_amount: str = Field(default="Zahlbetrag", alias="CF_GIRO_AMOUNT")
    cf_sevdesk_id: str = Field(default="SevDesk-Beleg", alias="CF_SEVDESK_ID")
    cf_exported_at: str = Field(default="SevDesk-Export am", alias="CF_EXPORTED_AT")
    cf_paid: str = Field(default="Überwiesen", alias="CF_PAID")
    tag_sevdesk_done: str = Field(default="sevdesk-exportiert", alias="TAG_SEVDESK_DONE")
    tag_paid: str = Field(default="überwiesen", alias="TAG_PAID")

    # ---- Empfänger-Zuordnung (Paperless-Custom-Field "Empfänger", Typ select) ----
    # Name des kuratierten select-Custom-Fields in Paperless. Wird NICHT automatisch
    # angelegt — die Auswahloptionen (Familienmitglieder) pflegst du in Paperless.
    cf_recipient: str = Field(default="Empfänger", alias="CF_RECIPIENT")
    # KI-gestützter Empfänger-Vorschlag (reaktiviert die paperless-gpt-Anthropic-Anbindung).
    feature_recipient_llm: bool = Field(default=False, alias="FEATURE_RECIPIENT_LLM")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    recipient_llm_model: str = Field(default="claude-sonnet-4-6", alias="RECIPIENT_LLM_MODEL")
    # true = Vorschlag ab der Konfidenz-Schwelle direkt ins Paperless-Feld schreiben.
    recipient_llm_auto_apply: bool = Field(default=True, alias="RECIPIENT_LLM_AUTO_APPLY")
    # Mindest-Konfidenz (0..1) für das automatische Setzen; darunter nur vorschlagen.
    recipient_llm_min_confidence: float = Field(
        default=0.75, alias="RECIPIENT_LLM_MIN_CONFIDENCE"
    )
    # Obergrenze, wie viele Dokumente ein einzelner Batch-Lauf maximal verarbeitet.
    recipient_batch_max: int = Field(default=1000, alias="RECIPIENT_BATCH_MAX")

    @property
    def partial_suffix_list(self) -> list[str]:
        return [s.strip().lower() for s in self.partial_suffixes.split(",") if s.strip()]

    def ensure_dirs(self) -> None:
        for d in (self.watch_dir, self.consume_dir, self.processed_dir, self.error_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Zulässige Werte für OCR_PROVIDER und ihr Pflichtbedarf je Engine (Feldnamen, nicht Alias).
# Bewusst hier statt in app/ocr/__init__.py: app/ocr/__init__.py importiert Settings aus
# diesem Modul (from ..config import Settings), ein Import in Gegenrichtung würde einen
# Zyklus erzeugen. Damit der Bedarf trotzdem an genau einer Stelle steht, lebt er hier;
# eine zweite Engine ergänzt nur diesen Dict-Eintrag.
_ENGINE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "documentai": (
        "gcp_project_id",
        "docai_processor_id",
        "docai_location",
        "google_application_credentials",
    ),
}


def _env_name(field_name: str) -> str:
    """Liest den ENV-Namen (Alias) zu einem Feld aus dem Modell, statt ihn zu wiederholen."""
    alias = Settings.model_fields[field_name].alias
    return alias if alias is not None else field_name


# Kehrrichtung zu _env_name(): vom ENV-Namen (Alias), wie ihn eine pydantic-ValidationError
# in error["loc"][0] nennt, zurück zum Feldnamen der Klasse — nur darüber lässt sich der
# zugehörige Standardwert aus Settings.model_fields auflösen.
_ALIAS_TO_FIELD_NAME: dict[str, str] = {
    (field.alias or name): name for name, field in Settings.model_fields.items()
}


def _type_error_to_problem(error: dict) -> str:
    """Übersetzt einen einzelnen Eintrag aus `ValidationError.errors()` in eine
    Beanstandung in derselben Form wie `validate_settings()` — mit dem ENV-Namen, unter
    dem der Anwender die Angabe setzt. `error["loc"]` ist bei diesem Modell immer ein
    Ein-Element-Tupel, weil `Settings` flach ist (keine verschachtelten Unter-Modelle) und
    pydantic-settings darin bereits den Alias einträgt, nicht den Feldnamen."""
    alias = str(error["loc"][0])
    return f"{alias} hat einen ungültigen Wert ({error['input']!r}): {error['msg']}"


def get_settings_and_problems() -> tuple[Settings | None, list[str]]:
    """Baut die Konfiguration und sammelt ALLE Beanstandungen in einem Durchgang — auch
    dann, wenn `get_settings()` bereits an einem Typfehler scheitert (z. B.
    `RETRY_MAX=abc`). Ohne diese Funktion würde ein Typfehler eine gleichzeitig leere
    Pflichtangabe verdecken: `Settings()` scheitert mit `pydantic.ValidationError`, bevor
    `validate_settings()` überhaupt ein Objekt zum Prüfen hat, und der Anwender sähe die
    leere Pflichtangabe erst nach einem zweiten Neustart. Siehe das Requirement „Die
    Startprüfung nennt alle Beanstandungen in einem Durchgang"
    (openspec/changes/startvalidierung-und-healthcheck/specs/verarbeitungs-lebenszyklus/spec.md).

    Zwei Stufen:
    1. `get_settings()` normal versuchen. Gelingt es, laufen die inhaltlichen Prüfungen
       über `validate_settings()` wie bisher — Verhalten für den Erfolgsfall unverändert.
    2. Scheitert Stufe 1, wird jeder Fehler aus `err.errors()` zu einer Beanstandung
       (`_type_error_to_problem`). Die betroffenen Felder werden danach als
       Konstruktor-Argumente auf ihren Standardwert gesetzt — ein Konstruktor-Argument hat
       in pydantic-settings Vorrang vor der Umgebung (geprüft: `Settings(_env_file=None,
       RETRY_MAX=3)` mit `RETRY_MAX=abc` in `os.environ` liefert `retry_max == 3`, alle
       übrigen Felder lesen weiter normal aus der Umgebung) — und `Settings` ein zweites
       Mal gebaut. Gelingt das, laufen die inhaltlichen Prüfungen zusätzlich auf diesem
       Objekt, ihre Beanstandungen werden angehängt.

       Rand (Maskierungsrichtung): Ein Feature-Schalter mit Typfehler (z. B.
       `FEATURE_PAPERLESS_SYNC=vielleicht`) fällt in diesem zweiten Bau auf seinen
       Standardwert (`False`) zurück; die davon abhängigen Prüfungen in
       `validate_settings()` greifen dann nicht, obwohl der Anwender den Schalter
       eigentlich aktivieren wollte. Das führt nicht in die Irre, weil der Typfehler
       selbst gemeldet wird (der Schalter steht als Beanstandung in der Meldung) und der
       nächste Start nach dessen Behebung den Rest zeigt — es ist aber bewusst kein
       Versuch, den *gemeinten* Wert zu erraten.

       Gegenrichtung (Erfindungsrichtung), behoben statt nur dokumentiert: Der
       Standardwert eines Felds mit Typfehler kann umgekehrt auch eine Prüfung
       *aktivieren*, die beim tatsächlich gemeinten Wert gar nicht gälte — `RETRY_MAX`
       fällt z. B. auf `3` (> 0) zurück, unabhängig davon, ob der Anwender `0` meinte.
       Deshalb übergibt diese Funktion die Namen aller Felder mit Typfehler als
       `unzuverlaessige_felder` an `validate_settings()`; dort überspringt sich die
       einzige Prüfung, deren Bedingung an einem solchen Feld hängt
       (`retry_max`/`retry_delay_minutes`), statt eine Beanstandung zu erfinden.

    Scheitert auch der zweite Bau (bei den aktuellen Feldern nicht beobachtet — jedes Feld
    trägt einen zum eigenen Typ passenden Standardwert, und es gibt keine
    modellübergreifenden Validatoren, die einen für sich genommen gültigen Standardwert
    nachträglich verwerfen könnten), bleibt es bei den Typfehlern allein. Der erste
    Rückgabewert ist dann `None` — es gibt kein gültiges `Settings`-Objekt, der Aufrufer
    darf es folglich nicht verwenden und muss anhand der (dann garantiert nicht leeren)
    Beanstandungsliste den Start ablehnen, bevor er `settings` anfasst.
    """
    try:
        settings = get_settings()
    except ValidationError as exc:
        errors = exc.errors()
        type_problems = [_type_error_to_problem(e) for e in errors]
        overrides: dict[str, object] = {}
        unreliable_fields: set[str] = set()
        for error in errors:
            alias = str(error["loc"][0])
            field_name = _ALIAS_TO_FIELD_NAME.get(alias)
            if field_name is not None:
                overrides[alias] = Settings.model_fields[field_name].default
                unreliable_fields.add(field_name)
        try:
            fallback = Settings(**overrides)
        except ValidationError:
            return None, type_problems
        return fallback, type_problems + validate_settings(fallback, unreliable_fields)
    return settings, validate_settings(settings)


def _is_readable_file(path: Path) -> bool:
    """Einziger I/O-Zugriff dieser Prüfung: Vorhandensein und Lesbarkeit, kein Parsen."""
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


class ConfigurationRejectedError(RuntimeError):
    """Wird beim Start geworfen, wenn `validate_settings` oder die Schreibprobe in
    `lifespan` (app/main.py) Beanstandungen findet. Trägt die gesammelten Beanstandungen
    zusätzlich als `problems`, damit ein Test sie prüfen kann, ohne das Protokoll
    abzufangen — die Ausnahme selbst ist der maßgebliche Träger der Information, das
    `log.error` davor (design.md D3) dient nur der Lesbarkeit in `docker logs`."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        block = "\n".join(f"  {p}" for p in problems)
        super().__init__(f"Konfiguration unvollständig — der Dienst startet nicht:\n{block}")


def validate_settings(
    settings: Settings, unzuverlaessige_felder: set[str] | None = None
) -> list[str]:
    """Prüft ein bereits aufgebautes Settings-Objekt auf Angaben, die sonst erst beim
    ersten Dokument als Google-API-Fehler auffallen würden (fehlende Engine-Angaben,
    unlesbare Credentials-Datei, ein zu kurzes Retry-Intervall, ein gesetzter
    Feature-Schalter ohne die dazugehörigen Angaben).

    Gibt die Liste aller Beanstandungen zurück (leere Liste = gültige Konfiguration).
    Wirft selbst nicht und bricht nicht bei der ersten Beanstandung ab — sie werden
    gesammelt, damit der Aufrufer sie in einem Durchgang meldet.

    `unzuverlaessige_felder` nennt Feldnamen (nicht ENV-Namen), deren Wert in `settings`
    NICHT der vom Anwender gemeinte ist, weil das Feld selbst schon bei der Konstruktion
    einen Typfehler hatte und deshalb im übergebenen Objekt auf seinem Standardwert liegt
    (siehe `get_settings_and_problems()` in diesem Modul, das dieses Argument beim
    Fallback-Bau füllt). Eine Prüfung, deren BEDINGUNG an einem solchen Feld hängt, darf
    daraus keine abgeleitete Beanstandung erzeugen — wir wissen schlicht nicht, ob die
    Bedingung zuträfe: `RETRY_MAX=drei` (Typfehler, gemeint war z.B. `0`) zusammen mit
    `RETRY_DELAY_MINUTES=0` fiele ohne diese Ausnahme auf den Standardwert `retry_max=3`
    zurück, und die Prüfung unten würde `RETRY_DELAY_MINUTES muss mindestens 1 sein`
    erfinden — eine Beanstandung an etwas, das beim eigentlich gemeinten `retry_max<=0`
    gar nicht gälte. Der Standardfall (kein Typfehler) übergibt `None`/eine leere Menge
    und bleibt dadurch unverändert."""
    unreliable = unzuverlaessige_felder or set()
    problems: list[str] = []

    provider = settings.ocr_provider
    # Case-insensitiv, konsistent zu get_adapter() (app/ocr/__init__.py:10), das den
    # Provider ebenfalls über .lower() auflöst — sonst würde eine Schreibweise, die zur
    # Laufzeit anstandslos die Engine auflöst, hier als unbekannt zurückgewiesen.
    normalized_provider = provider.lower()
    if normalized_provider not in _ENGINE_REQUIRED_FIELDS:
        zulaessig = ", ".join(sorted(_ENGINE_REQUIRED_FIELDS))
        problems.append(
            f"{_env_name('ocr_provider')} hat einen unbekannten Wert {provider!r} "
            f"(zulässig: {zulaessig})"
        )
    else:
        for field_name in _ENGINE_REQUIRED_FIELDS[normalized_provider]:
            value = getattr(settings, field_name)
            if field_name == "google_application_credentials":
                if not value:
                    problems.append(
                        f"{_env_name(field_name)} ist leer (Pflicht bei OCR_PROVIDER={provider})"
                    )
                elif not _is_readable_file(Path(value)):
                    problems.append(
                        f"{_env_name(field_name)} zeigt auf keine lesbare Datei: {value}"
                    )
            elif not value:
                problems.append(
                    f"{_env_name(field_name)} ist leer (Pflicht bei OCR_PROVIDER={provider})"
                )

    # Nur relevant, wenn überhaupt wiederholt wird — bei RETRY_MAX<=0 wird
    # schedule_retry() (app/pipeline.py:188) nie erreicht, und der Wert bliebe folgenlos.
    # Die Bedingung hängt an retry_max — hatte RETRY_MAX selbst einen Typfehler, steht der
    # hier gelesene Wert nur als Standard da (siehe unzuverlaessige_felder oben) und die
    # Prüfung überspringt sich, statt eine Beanstandung zu erfinden, die beim tatsächlich
    # gemeinten Wert gar nicht gälte.
    if (
        "retry_max" not in unreliable
        and settings.retry_max > 0
        and settings.retry_delay_minutes < 1
    ):
        problems.append(
            f"{_env_name('retry_delay_minutes')} muss mindestens 1 sein, "
            f"ist {settings.retry_delay_minutes}"
        )

    if settings.feature_paperless_sync:
        schalter = _env_name("feature_paperless_sync")
        if not settings.paperless_url:
            problems.append(f"{_env_name('paperless_url')} ist leer (Pflicht bei {schalter}=true)")
        if not settings.paperless_token:
            problems.append(
                f"{_env_name('paperless_token')} ist leer (Pflicht bei {schalter}=true)"
            )

    if settings.feature_sevdesk_export:
        schalter = _env_name("feature_sevdesk_export")
        if not settings.sevdesk_api_token:
            problems.append(
                f"{_env_name('sevdesk_api_token')} ist leer (Pflicht bei {schalter}=true)"
            )
        # Exportierbare Rechnungen entstehen ausschließlich im Paperless-Sync
        # (PaperlessSync._sync_invoices/_sync_sevdesk_tag, nur erreichbar über
        # sync_once() bei PaperlessSync.enabled) — ohne FEATURE_PAPERLESS_SYNC bleibt der
        # Export dauerhaft ohne Rechnung, also lautlos wirkungslos.
        if not settings.feature_paperless_sync:
            problems.append(
                f"{_env_name('feature_paperless_sync')} ist nicht aktiv (Pflicht bei "
                f"{schalter}=true — exportierbare Rechnungen entstehen ausschließlich im "
                "Paperless-Sync)"
            )

    if settings.feature_recipient_llm:
        schalter = _env_name("feature_recipient_llm")
        if not settings.anthropic_api_key:
            problems.append(
                f"{_env_name('anthropic_api_key')} ist leer (Pflicht bei {schalter}=true)"
            )
        # PaperlessSync.recipient_llm_enabled (app/paperless_sync.py:130-133) verlangt
        # zusätzlich recipient_enabled, also PAPERLESS_URL und PAPERLESS_TOKEN —
        # ausdrücklich unabhängig von FEATURE_PAPERLESS_SYNC.
        if not settings.paperless_url:
            problems.append(f"{_env_name('paperless_url')} ist leer (Pflicht bei {schalter}=true)")
        if not settings.paperless_token:
            problems.append(
                f"{_env_name('paperless_token')} ist leer (Pflicht bei {schalter}=true)"
            )

    return problems
