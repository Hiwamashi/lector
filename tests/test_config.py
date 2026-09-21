from app import config
from app.config import Settings, validate_settings


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
        tmp_path, FEATURE_SEVDESK_EXPORT=True, SEVDESK_API_TOKEN=""
    )
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "SEVDESK_API_TOKEN" in problems[0]


def test_validate_settings_sevdesk_export_abgeschaltet_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_SEVDESK_EXPORT=False, SEVDESK_API_TOKEN=""
    )
    assert validate_settings(s) == []


def test_validate_settings_empfaenger_llm_ohne_schluessel_wird_beanstandet(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_RECIPIENT_LLM=True, ANTHROPIC_API_KEY=""
    )
    problems = validate_settings(s)
    assert len(problems) == 1
    assert "ANTHROPIC_API_KEY" in problems[0]


def test_validate_settings_empfaenger_llm_abgeschaltet_bleibt_folgenlos(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path, FEATURE_RECIPIENT_LLM=False, ANTHROPIC_API_KEY=""
    )
    assert validate_settings(s) == []


def test_validate_settings_sammelt_alle_beanstandungen_statt_abzubrechen(tmp_path):
    s = _vollstaendige_documentai_settings(
        tmp_path,
        GCP_PROJECT_ID="",
        RETRY_DELAY_MINUTES=0,
        FEATURE_SEVDESK_EXPORT=True,
        SEVDESK_API_TOKEN="",
    )
    problems = validate_settings(s)
    assert len(problems) == 3
    meldung = "\n".join(problems)
    assert "GCP_PROJECT_ID" in meldung
    assert "RETRY_DELAY_MINUTES" in meldung
    assert "SEVDESK_API_TOKEN" in meldung
