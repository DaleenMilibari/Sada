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
    # LLM keys: llm_client re-reads backend/.env on every call, so stop that too. Tests that
    # exercise the LLM path fake generate_json or set their own keys (test_llm_client.py).
    from backend.agents import llm_client

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm_client, "_load_env", lambda: None)
    # Budgets a local backend/.env may tune for real collection - tests assume the defaults.
    monkeypatch.setattr(config, "X_REPLY_BUDGET", 1000)
    monkeypatch.setattr(config, "COLLECTOR_LOOKBACK_DAYS", 180)
