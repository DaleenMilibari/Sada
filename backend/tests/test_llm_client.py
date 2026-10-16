import pytest

from backend.agents import llm_client


class QuotaError(Exception):
    code = 429


class FakeModels:
    def __init__(self, key, log, exhausted):
        self.key, self.log, self.exhausted = key, log, exhausted

    def generate_content(self, model, contents, config):
        self.log.append((self.key, model))
        if (self.key, model) in self.exhausted:
            raise QuotaError("429 RESOURCE_EXHAUSTED")
        return type("R", (), {"text": f'{{"by": "{self.key}/{model}"}}'})()


@pytest.fixture()
def fake(monkeypatch):
    log, exhausted = [], set()
    monkeypatch.setenv("GEMINI_API_KEY", "k1, k2")
    monkeypatch.setenv("GEMINI_MODEL", "flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "lite")
    monkeypatch.setattr(llm_client, "_load_env", lambda: None)
    monkeypatch.setattr(llm_client, "_exhausted", {})
    monkeypatch.setattr(llm_client, "_client_for", lambda key: type("C", (), {"models": FakeModels(key, log, exhausted)})())
    return log, exhausted


def test_rotates_to_next_key_then_fallback_model(fake):
    log, exhausted = fake
    assert llm_client.generate_json("p") == '{"by": "k1/flash"}'

    exhausted.add(("k1", "flash"))
    assert llm_client.generate_json("p") == '{"by": "k2/flash"}'
    log.clear()
    assert llm_client.generate_json("p") == '{"by": "k2/flash"}'
    assert log == [("k2", "flash")]  # the exhausted key is skipped, not retried every call

    exhausted.add(("k2", "flash"))
    assert llm_client.generate_json("p") == '{"by": "k1/lite"}'


def test_all_exhausted_raises_clear_error(fake):
    _, exhausted = fake
    exhausted.update({("k1", "flash"), ("k2", "flash"), ("k1", "lite"), ("k2", "lite")})
    with pytest.raises(llm_client.QuotaExhaustedError):
        llm_client.generate_json("p")


def test_missing_key(monkeypatch):
    monkeypatch.setattr(llm_client, "_load_env", lambda: None)
    monkeypatch.setenv("GEMINI_API_KEY", " ")
    with pytest.raises(llm_client.MissingApiKeyError):
        llm_client.get_keys()
