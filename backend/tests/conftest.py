import os

import pytest

from backend import db


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path):
    """Point the app's engine at a throwaway database so tests never touch backend/store/sada.db.

    Set SADA_TEST_DATABASE_URL (e.g. a local/CI Postgres) to run the suite against that
    instead of SQLite - its tables are dropped and recreated for every test.
    """
    previous = db._engine
    url = os.environ.get("SADA_TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'app.db').as_posix()}"
    engine = db.make_engine(url)
    db.metadata.drop_all(engine)
    db.init_db(engine)
    db.set_engine(engine)
    yield engine
    db.set_engine(previous)
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_real_api_keys(monkeypatch):
    """backend/.env may hold real keys - tests must never reach YouTube/Instagram/X/Gemini for real."""
    from backend import config

    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "")
    monkeypatch.setattr(config, "META_ACCESS_TOKEN", "")
    monkeypatch.setattr(config, "INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    monkeypatch.setattr(config, "INSTAGRAM_ENABLED", False)
    monkeypatch.setattr(config, "X_BEARER_TOKEN", "")
    monkeypatch.setattr(config, "X_ENABLED", False)
