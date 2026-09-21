from app.config import Settings


def test_max_pages_per_document_defaults_to_100():
    assert Settings(_env_file=None).max_pages_per_document == 100


def test_max_pages_per_document_reads_env():
    assert Settings(_env_file=None, MAX_PAGES_PER_DOCUMENT="250").max_pages_per_document == 250


def test_max_pages_per_document_accepts_zero_to_disable():
    assert Settings(_env_file=None, MAX_PAGES_PER_DOCUMENT="0").max_pages_per_document == 0
