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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(llm_client.MissingApiKeyError):
        llm_client.get_keys()


def test_overloaded_model_is_retried_then_skipped(fake, monkeypatch):
    log, _ = fake
    monkeypatch.setattr(llm_client, "OVERLOAD_BACKOFF_S", 0)

    class Busy(Exception):
        code = 503

    calls = {"n": 0}
    original = llm_client._client_for

    def busy_once(key):
        client = original(key)
        real = client.models.generate_content

        def flaky(model, contents, config):
            calls["n"] += 1
            if calls["n"] == 1:
                raise Busy("503 UNAVAILABLE")
            return real(model, contents, config)

        client.models.generate_content = flaky
        return client

    monkeypatch.setattr(llm_client, "_client_for", busy_once)
    assert llm_client.generate_json("p") == '{"by": "k1/flash"}'  # one short retry, same key/model
    assert llm_client._exhausted == {}  # a spike is not treated as an exhausted quota


def test_timed_out_request_moves_on_to_the_next_key(fake, monkeypatch):
    log, _ = fake
    monkeypatch.setattr(llm_client, "OVERLOAD_BACKOFF_S", 0)
    original = llm_client._client_for

    class ReadTimeout(Exception):  # the shape httpx raises
        pass

    def slow_k1(key):
        client = original(key)
        if key == "k1":
            def hang(model, contents, config):
                log.append((key, model))
                raise ReadTimeout("timed out")
            client.models.generate_content = hang
        return client

    monkeypatch.setattr(llm_client, "_client_for", slow_k1)
    assert llm_client.generate_json("p") == '{"by": "k2/flash"}'
    assert llm_client._exhausted == {}  # a timeout is not an exhausted quota


def test_rotation_stops_at_the_deadline(fake, monkeypatch):
    monkeypatch.setattr(llm_client, "DEADLINE_S", -1)
    with pytest.raises(llm_client.DeadlineExceededError):
        llm_client.generate_json("p")


class OpenAIQuotaError(Exception):
    status_code = 429
    code = "insufficient_quota"  # OpenAI's .code is a string, not the HTTP status


def _fake_openai(monkeypatch, log, exhausted):
    def create(key):
        def _create(model, messages, response_format):
            log.append((key, model))
            if (key, model) in exhausted:
                raise OpenAIQuotaError("429")
            msg = type("M", (), {"content": f'{{"by": "{key}/{model}"}}'})()
            return type("R", (), {"choices": [type("Ch", (), {"message": msg})()]})()
        return _create

    completions = lambda key: type("X", (), {"create": staticmethod(create(key))})()
    monkeypatch.setattr(
        llm_client, "_openai_client_for",
        lambda key: type("O", (), {"chat": type("Chat", (), {"completions": completions(key)})()})(),
    )


def test_openai_first_then_gemini_fallback(fake, monkeypatch):
    log, exhausted = fake
    monkeypatch.setenv("OPENAI_API_KEY", "o1")
    monkeypatch.setenv("OPENAI_MODEL", "mini")
    monkeypatch.delenv("OPENAI_FALLBACK_MODEL", raising=False)
    _fake_openai(monkeypatch, log, exhausted)

    assert llm_client.get_model() == "mini"
    assert llm_client.generate_json("p") == '{"by": "o1/mini"}'

    exhausted.add(("o1", "mini"))
    assert llm_client.generate_json("p") == '{"by": "k1/flash"}'  # OpenAI out of quota: Gemini takes over


def test_openai_only_without_gemini_key(monkeypatch):
    log, exhausted = [], set()
    monkeypatch.setattr(llm_client, "_load_env", lambda: None)
    monkeypatch.setattr(llm_client, "_exhausted", {})
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o1")
    monkeypatch.setenv("OPENAI_MODEL", "mini")
    _fake_openai(monkeypatch, log, exhausted)
    assert llm_client.generate_json("p") == '{"by": "o1/mini"}'
