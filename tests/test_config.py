import pytest

from app import config
from app.config import ConfigurationRejectedError, Settings, validate_settings


def _vollstaendige_documentai_settings(tmp_path, **overrides):
    """Baut eine vollständige, gültige Document-AI-Konfiguration; einzelne Angaben
    lassen sich über `overrides` (ENV-Namen als Schlüssel) gezielt überschreiben."""
    creds = tmp_path / "creds.json"
    creds.write_text("{}")
    kwargs = dict(
        _env_file=None,
        OCR_PROVIDER="documentai",
        GCP_PROJECT_ID="mein-projekt",
        DOCAI_PROCESSOR_ID="proc-123",
        DOCAI_LOCATION="eu",
        GOOGLE_APPLICATION_CREDENTIALS=str(creds),
        RETRY_DELAY_MINUTES=15,
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


def test_max_pages_per_document_defaults_to_100():
    assert Settings(_env_file=None).max_pages_per_document == 100


def test_max_pages_per_document_reads_env():
    assert Settings(_env_file=None, MAX_PAGES_PER_DOCUMENT="250").max_pages_per_document == 250


def test_max_pages_per_document_accepts_zero_to_disable():
    assert Settings(_env_file=None, MAX_PAGES_PER_DOCUMENT="0").max_pages_per_document == 0


def test_chunk_cache_retention_defaults_to_7():
    assert Settings(_env_file=None).chunk_cache_retention_days == 7


def test_chunk_cache_retention_reads_env():
    s = Settings(_env_file=None, CHUNK_CACHE_RETENTION_DAYS="30")
    assert s.chunk_cache_retention_days == 30


# --- validate_settings ------------------------------------------------------------


def test_validate_settings_gibt_leere_liste_fuer_vollstaendige_konfiguration(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path)
    assert validate_settings(s) == []


def test_validate_settings_nennt_env_namen_nicht_feldnamen(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, GCP_PROJECT_ID="")
    problems = validate_settings(s)
    meldung = "\n".join(problems)
    assert "GCP_PROJECT_ID" in meldung
    assert "gcp_project_id" not in meldung


def test_validate_settings_beanstandet_unbekannten_ocr_provider(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, OCR_PROVIDER="erfundene-engine")
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "erfundene-engine" in problems[0]
    assert "documentai" in problems[0]


def test_validate_settings_beanstandet_leere_engine_pflichtangaben(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        GCP_PROJECT_ID="",
        DOCAI_PROCESSOR_ID="",
        DOCAI_LOCATION="",
    )
    problems = validate_settings(s)
    meldung = "\n".join(problems)
    assert "GCP_PROJECT_ID" in meldung
    assert "DOCAI_PROCESSOR_ID" in meldung
    assert "DOCAI_LOCATION" in meldung


def test_validate_settings_akzeptiert_provider_in_abweichender_schreibweise(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, OCR_PROVIDER="DocumentAI")
    assert validate_settings(s) == []


def test_validate_settings_meldet_luecke_bei_abweichender_schreibweise_statt_unbekannt(
    tmp_path,
):
    s = _vollstaendige_documentai_settings(tmp_path, OCR_PROVIDER="DocumentAI", GCP_PROJECT_ID="")
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "GCP_PROJECT_ID" in problems[0]
    assert "unbekannten Wert" not in problems[0]


def test_validate_settings_ueberspringt_engine_pflichtangaben_ohne_bedarf(monkeypatch, tmp_path):
    monkeypatch.setitem(config._ENGINE_REQUIRED_FIELDS, "ohne-bedarf", ())
    s = _vollstaendige_documentai_settings(
        tmp_path,
        OCR_PROVIDER="ohne-bedarf",
        GCP_PROJECT_ID="",
        DOCAI_PROCESSOR_ID="",
        DOCAI_LOCATION="",
        GOOGLE_APPLICATION_CREDENTIALS="",
    )
    assert validate_settings(s) == []


def test_validate_settings_beanstandet_leere_credentials_angabe(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, GOOGLE_APPLICATION_CREDENTIALS="")
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "GOOGLE_APPLICATION_CREDENTIALS" in problems[0]
    assert "ist leer" in problems[0]


def test_validate_settings_beanstandet_credentials_pfad_ins_leere(tmp_path):
    fehlend = tmp_path / "nicht-vorhanden.json"
    s = _vollstaendige_documentai_settings(tmp_path, GOOGLE_APPLICATION_CREDENTIALS=str(fehlend))
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "GOOGLE_APPLICATION_CREDENTIALS" in problems[0]
    assert "keine lesbare Datei" in problems[0]
    assert str(fehlend) in problems[0]


def test_validate_settings_akzeptiert_vorhandene_lesbare_credentials_datei(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path)
    assert validate_settings(s) == []


def test_validate_settings_credentials_fehlerfaelle_unterscheiden_sich(tmp_path):
    leer = validate_settings(
        _vollstaendige_documentai_settings(tmp_path, GOOGLE_APPLICATION_CREDENTIALS="")
    )
    pfad_ins_leere = validate_settings(
        _vollstaendige_documentai_settings(
            tmp_path, GOOGLE_APPLICATION_CREDENTIALS=str(tmp_path / "nicht-vorhanden.json")
        )
    )
    assert leer[0] != pfad_ins_leere[0]


def test_validate_settings_retry_delay_null_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_DELAY_MINUTES=0)
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "RETRY_DELAY_MINUTES" in problems[0]


def test_validate_settings_retry_delay_negativ_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_DELAY_MINUTES=-5)
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "RETRY_DELAY_MINUTES" in problems[0]


def test_validate_settings_retry_delay_gueltiger_wert_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_DELAY_MINUTES=1)
    assert validate_settings(s) == []


def test_validate_settings_retry_delay_null_ohne_wiederholversuch_bleibt_folgenlos(tmp_path):
    """RETRY_MAX<=0 heisst 'kein Wiederholversuch' — schedule_retry() (app/pipeline.py:188)
    wird dann nie erreicht, RETRY_DELAY_MINUTES bleibt ohne Wirkung und darf den Start
    nicht grundlos anhalten."""
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_MAX=0, RETRY_DELAY_MINUTES=0)
    assert validate_settings(s) == []


# ---- Fix-Runde: unzuverlaessige_felder darf keine Beanstandung erfinden --------------


def test_validate_settings_ueberspringt_retry_delay_pruefung_bei_unzuverlaessigem_retry_max(
    tmp_path,
):
    """Befund 'Der Fallback kann eine Beanstandung erfinden': Hätte RETRY_MAX selbst einen
    Typfehler, steht der hier gelesene retry_max (im Fallback-Bau der Standardwert `3`)
    nur als Platzhalter da — ob der Anwender tatsächlich retry_max<=0 meinte, ist
    unbekannt. Die Prüfung darf dann keine Forderung an RETRY_DELAY_MINUTES erfinden."""
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_DELAY_MINUTES=0)
    assert validate_settings(s, unzuverlaessige_felder={"retry_max"}) == []


def test_validate_settings_retry_delay_pruefung_greift_trotz_anderer_unzuverlaessiger_felder(
    tmp_path,
):
    """unzuverlaessige_felder wirkt gezielt auf sein Bedingungsfeld: Ein Typfehler an
    einem ANDEREN Feld darf die RETRY_DELAY_MINUTES-Prüfung nicht mit abschalten — sonst
    wäre der Skip ein genereller Schalter statt einer gezielten Ausnahme."""
    s = _vollstaendige_documentai_settings(tmp_path, RETRY_DELAY_MINUTES=0)
    problems = validate_settings(s, unzuverlaessige_felder={"gcp_project_id"})
    assert len(problems) == 1
    assert "RETRY_DELAY_MINUTES" in problems[0]


def test_validate_settings_ueberspringt_paperless_sync_pruefung_bei_unzuverlaessigem_feld(
    tmp_path,
):
    """Zweite Stelle mit demselben Fehlerbild (Nachtrag zur Fix-Runde, app/config.py:362):
    Hätte FEATURE_PAPERLESS_SYNC selbst einen Typfehler, steht der hier gelesene Wert
    (im Fallback-Bau der Standardwert `False`) nur als Platzhalter da — ob der Anwender
    ihn aktivieren wollte, ist unbekannt. Die Prüfung im feature_sevdesk_export-Block
    darf dann keine Aktivierungsforderung erfinden."""
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="tok-123",
        FEATURE_PAPERLESS_SYNC=False,
    )
    assert validate_settings(s, unzuverlaessige_felder={"feature_paperless_sync"}) == []


def test_validate_settings_paperless_sync_pruefung_greift_trotz_anderer_unzuverlaessiger_felder(
    tmp_path,
):
    """Gegenstück: Ein Typfehler an einem ANDEREN Feld darf die
    FEATURE_PAPERLESS_SYNC-Prüfung im feature_sevdesk_export-Block nicht mit abschalten."""
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="tok-123",
        FEATURE_PAPERLESS_SYNC=False,
    )
    problems = validate_settings(s, unzuverlaessige_felder={"gcp_project_id"})
    assert len(problems) == 1
    assert "FEATURE_PAPERLESS_SYNC" in problems[0]


def test_validate_settings_chunk_size_null_verhindert_start_nicht(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, CHUNK_SIZE_PAGES=0)
    assert validate_settings(s) == []


def test_validate_settings_chunk_size_ueber_engine_limit_verhindert_start_nicht(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, CHUNK_SIZE_PAGES=99)
    assert validate_settings(s) == []


def test_validate_settings_negative_aufbewahrungsfrist_verhindert_start_nicht(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, PROCESSED_RETENTION_DAYS=-1)
    assert validate_settings(s) == []


def test_validate_settings_paperless_sync_ohne_angaben_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_PAPERLESS_SYNC=True, PAPERLESS_URL="", PAPERLESS_TOKEN=""
    )
    problems = validate_settings(s)
    meldung = "\n".join(problems)
    assert "PAPERLESS_URL" in meldung
    assert "PAPERLESS_TOKEN" in meldung


def test_validate_settings_paperless_sync_abgeschaltet_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_PAPERLESS_SYNC=False, PAPERLESS_URL="", PAPERLESS_TOKEN=""
    )
    assert validate_settings(s) == []


def test_validate_settings_sevdesk_export_ohne_token_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="",
        FEATURE_PAPERLESS_SYNC=True,
        PAPERLESS_URL="http://paperless.local",
        PAPERLESS_TOKEN="tok-123",
    )
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "SEVDESK_API_TOKEN" in problems[0]


def test_validate_settings_sevdesk_export_ohne_paperless_sync_wird_beanstandet(tmp_path):
    """SevDesk-Token allein genügt nicht: exportierbare Rechnungen entstehen
    ausschließlich im Paperless-Sync (PaperlessSync._sync_invoices/_sync_sevdesk_tag,
    nur erreichbar über sync_once() bei PaperlessSync.enabled). Ohne
    FEATURE_PAPERLESS_SYNC bliebe FEATURE_SEVDESK_EXPORT lautlos wirkungslos, obwohl
    Token und Schalter gesetzt sind."""
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="tok-123",
        FEATURE_PAPERLESS_SYNC=False,
    )
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "FEATURE_PAPERLESS_SYNC" in problems[0]


def test_validate_settings_sevdesk_export_abgeschaltet_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_SEVDESK_EXPORT=False, SEVDESK_API_TOKEN="", FEATURE_PAPERLESS_SYNC=False
    )
    assert validate_settings(s) == []


def test_validate_settings_empfaenger_llm_ohne_schluessel_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_RECIPIENT_LLM=True,
        ANTHROPIC_API_KEY="",
        PAPERLESS_URL="http://paperless.local",
        PAPERLESS_TOKEN="tok-123",
    )
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "ANTHROPIC_API_KEY" in problems[0]


def test_validate_settings_empfaenger_llm_ohne_paperless_wird_beanstandet(tmp_path):
    """PaperlessSync.recipient_llm_enabled (app/paperless_sync.py:130-133) verlangt
    zusätzlich recipient_enabled, also PAPERLESS_URL und PAPERLESS_TOKEN — ausdrücklich
    unabhängig von FEATURE_PAPERLESS_SYNC (app/paperless_sync.py:124-127). Ohne beide
    Angaben wäre FEATURE_RECIPIENT_LLM=true lautlos wirkungslos, obwohl der
    Anthropic-Schlüssel gesetzt ist."""
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_RECIPIENT_LLM=True,
        ANTHROPIC_API_KEY="sk-ant-x",
        PAPERLESS_URL="",
        PAPERLESS_TOKEN="",
    )
    problems = validate_settings(s)
    meldung = "\n".join(problems)
    assert "PAPERLESS_URL" in meldung
    assert "PAPERLESS_TOKEN" in meldung


def test_validate_settings_empfaenger_llm_abgeschaltet_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        FEATURE_RECIPIENT_LLM=False,
        ANTHROPIC_API_KEY="",
        PAPERLESS_URL="",
        PAPERLESS_TOKEN="",
    )
    assert validate_settings(s) == []


def test_validate_settings_sammelt_alle_beanstandungen_statt_abzubrechen(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        GCP_PROJECT_ID="",
        RETRY_DELAY_MINUTES=0,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="",
        FEATURE_PAPERLESS_SYNC=False,
    )
    problems = validate_settings(s)
    assert len(problems) == 4
    meldung = "\n".join(problems)
    assert "GCP_PROJECT_ID" in meldung
    assert "RETRY_DELAY_MINUTES" in meldung
    assert "SEVDESK_API_TOKEN" in meldung
    assert "FEATURE_PAPERLESS_SYNC" in meldung


# ---- Aufgabe 3.1: Ausnahmeklasse für einen abgelehnten Start -------------------------


def test_configuration_rejected_error_ist_gezielt_abfangbar():
    """3.1: Die eigene Ausnahmeklasse lässt sich gezielt abfangen, nicht nur als
    generisches `RuntimeError` — und trägt die Beanstandungen für einen Test, ohne dass
    er das Protokoll abfangen müsste."""
    problems = ["GCP_PROJECT_ID ist leer (Pflicht bei OCR_PROVIDER=documentai)"]

    with pytest.raises(ConfigurationRejectedError) as exc_info:
        raise ConfigurationRejectedError(problems)

    assert exc_info.value.problems == problems
    assert "GCP_PROJECT_ID" in str(exc_info.value)


def test_configuration_rejected_error_ist_ein_runtime_error():
    """Passt sich in die bestehende Fehlerhierarchie ein (`PaperlessError`,
    `SevdeskError`, `RecipientSuggesterError` sind ebenfalls `RuntimeError`)."""
    assert issubclass(ConfigurationRejectedError, RuntimeError)


# ---- Gruppe 1: Zugangsmodus (AUTH_MODE, Sitzungsgeheimnis) ---------------------------


def test_auth_standardwerte():
    s = Settings(_env_file=None)
    assert s.auth_mode == "none"
    assert s.lector_secret_key == ""
    assert s.session_cookie_secure is False


def test_auth_felder_lesen_env():
    s = Settings(
        _env_file=None,
        AUTH_MODE="paperless",
        LECTOR_SECRET_KEY="geheim",
        SESSION_COOKIE_SECURE="true",
    )
    assert s.auth_mode == "paperless"
    assert s.lector_secret_key == "geheim"
    assert s.session_cookie_secure is True


def test_ungueltiger_auth_mode_wird_mit_weiterer_beanstandung_gemeinsam_gemeldet(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)  # keine .env im Arbeitsverzeichnis
    monkeypatch.setenv("AUTH_MODE", "ldap")
    monkeypatch.setenv("OCR_PROVIDER", "documentai")
    monkeypatch.setenv("GCP_PROJECT_ID", "")
    monkeypatch.setenv("DOCAI_PROCESSOR_ID", "proc-123")
    monkeypatch.setenv("DOCAI_LOCATION", "eu")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    config.get_settings.cache_clear()
    try:
        settings, problems = config.get_settings_and_problems()
    finally:
        config.get_settings.cache_clear()

    assert settings is not None
    meldung = "\n".join(problems)
    assert "AUTH_MODE hat einen ungültigen Wert" in meldung
    assert "ldap" in meldung
    assert "GCP_PROJECT_ID" in meldung
    # Keine Folgebeanstandung wegen des auf "none" zurückgefallenen Modus.
    assert "PAPERLESS_URL" not in meldung


def test_validate_settings_paperless_modus_ohne_url_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, AUTH_MODE="paperless", PAPERLESS_URL="")
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "PAPERLESS_URL ist leer" in problems[0]
    assert "AUTH_MODE=paperless" in problems[0]


def test_validate_settings_paperless_modus_url_pflicht_auch_ohne_sync(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, AUTH_MODE="paperless", FEATURE_PAPERLESS_SYNC=False, PAPERLESS_URL=""
    )
    assert any("PAPERLESS_URL" in p for p in validate_settings(s))


def test_validate_settings_paperless_modus_mit_url_ist_gueltig(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, AUTH_MODE="paperless", PAPERLESS_URL="http://paperless.local"
    )
    assert validate_settings(s) == []


def test_validate_settings_auth_modus_none_braucht_keine_paperless_url(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, AUTH_MODE="none", PAPERLESS_URL="")
    assert validate_settings(s) == []


def test_validate_settings_ueberspringt_auth_pruefung_bei_unzuverlaessigem_auth_mode(tmp_path):
    s = _vollstaendige_documentai_settings(tmp_path, AUTH_MODE="paperless", PAPERLESS_URL="")
    assert validate_settings(s, unzuverlaessige_felder={"auth_mode"}) == []


def test_warn_auth_proxy_config_warnt_ohne_forwarded_allow_ips(monkeypatch, caplog):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    s = Settings(_env_file=None, AUTH_MODE="paperless")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    assert any("FORWARDED_ALLOW_IPS" in r.getMessage() for r in caplog.records)
    assert all(r.levelname == "WARNING" for r in caplog.records)


def test_warn_auth_proxy_config_schweigt_mit_forwarded_allow_ips(monkeypatch, caplog):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "172.18.0.0/16")
    s = Settings(_env_file=None, AUTH_MODE="paperless")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    assert caplog.records == []


@pytest.mark.parametrize("wert", ["", "   ", "\t"])
def test_warn_auth_proxy_config_warnt_bei_leerem_forwarded_allow_ips(monkeypatch, caplog, wert):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", wert)
    s = Settings(_env_file=None, AUTH_MODE="paperless")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    assert any("leer" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("wert", ["*", "172.18.0.0/16, *", " * "])
def test_warn_auth_proxy_config_warnt_bei_stern(monkeypatch, caplog, wert):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", wert)
    s = Settings(_env_file=None, AUTH_MODE="paperless")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    meldungen = [r.getMessage() for r in caplog.records]
    assert len(meldungen) == 1
    assert "ERSETZEN" in meldungen[0]


def test_warn_auth_proxy_config_schweigt_bei_stern_im_modus_none(monkeypatch, caplog):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    s = Settings(_env_file=None, AUTH_MODE="none")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    assert caplog.records == []


def test_warn_auth_proxy_config_schweigt_im_modus_none(monkeypatch, caplog):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    s = Settings(_env_file=None, AUTH_MODE="none")
    with caplog.at_level("WARNING", logger="app.config"):
        config.warn_auth_proxy_config(s)
    assert caplog.records == []


def test_load_session_secret_env_gewinnt_und_legt_keine_datei_an(tmp_path):
    s = Settings(
        _env_file=None,
        AUTH_MODE="paperless",
        LECTOR_SECRET_KEY="aus-der-env",
        DB_PATH=str(tmp_path / "lector.db"),
    )
    assert config.load_session_secret(s) == "aus-der-env"
    assert not (tmp_path / "session.key").exists()


def test_load_session_secret_erzeugt_datei_und_verwendet_sie_wieder(tmp_path):
    s = Settings(_env_file=None, AUTH_MODE="paperless", DB_PATH=str(tmp_path / "lector.db"))
    erster = config.load_session_secret(s)
    key_file = tmp_path / "session.key"

    assert erster and len(erster) >= 48
    assert key_file.read_text(encoding="utf-8") == erster
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert config.load_session_secret(s) == erster


def test_load_session_secret_strippt_whitespace_beim_lesen(tmp_path):
    (tmp_path / "session.key").write_text("vorhanden\n", encoding="utf-8")
    s = Settings(_env_file=None, AUTH_MODE="paperless", DB_PATH=str(tmp_path / "lector.db"))
    assert config.load_session_secret(s) == "vorhanden"


def test_load_session_secret_im_modus_none_ohne_datei(tmp_path):
    s = Settings(_env_file=None, AUTH_MODE="none", DB_PATH=str(tmp_path / "lector.db"))
    assert config.load_session_secret(s) is None
    assert list(tmp_path.iterdir()) == []
