from app.config import Settings


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
