import pytest
from fastapi.testclient import TestClient

from backend import auth, config
from backend.agents import llm_client
from backend.api import app
from backend.rate_limit import llm_limiter, login_limiter

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_PASSWORD", PASSWORD)
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    llm_limiter.reset()
    login_limiter.reset()
    with TestClient(app) as c:
        yield c


def _login(client) -> dict:
    res = client.post("/api/auth/login", json={"password": PASSWORD})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_health_is_public(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_api_routes_require_token(client):
    assert client.get("/api/patterns").status_code == 401
    assert client.get("/api/patterns", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_wrong_password_rejected(client):
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401


def test_login_then_access(client):
    headers = _login(client)
    res = client.get("/api/patterns", headers=headers)
    assert res.status_code == 200
    # Startup builds the store when empty, so a fresh deploy always has patterns.
    assert len(res.json()) > 0


def test_tampered_and_expired_tokens_rejected(client, monkeypatch):
    token, _ = auth.issue_token()
    payload, sig = token.split(".")
    assert auth.verify_token(f"{payload}.{sig[:-2]}xx") is None

    monkeypatch.setattr(config, "TOKEN_TTL_HOURS", -1)
    expired, _ = auth.issue_token()
    assert auth.verify_token(expired) is None


def test_login_is_rate_limited(client):
    statuses = [client.post("/api/auth/login", json={"password": "nope"}).status_code for _ in range(8)]
    assert 429 in statuses


def test_llm_routes_rate_limited_and_map_missing_key_to_503(client, monkeypatch):
    def no_key(*_args):
        raise llm_client.MissingApiKeyError("no key")

    monkeypatch.setattr("backend.agents.content_optimizer_agent.run", no_key)
    headers = _login(client)
    draft = {"content_type": "video", "topic": "national_event", "platform_options": ["x"]}

    statuses = [
        client.post("/api/optimize", json=draft, headers=headers).status_code
        for _ in range(config.LLM_RATE_LIMIT_PER_MINUTE + 2)
    ]
    assert statuses[0] == 503
    assert statuses[-1] == 429


def test_llm_unexpected_error_returns_502(client, monkeypatch):
    def boom(*_args):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr("backend.agents.content_optimizer_agent.run", boom)
    headers = _login(client)
    draft = {"content_type": "video", "topic": "national_event"}
    res = client.post("/api/optimize", json=draft, headers=headers)
    assert res.status_code == 502
    assert "exploded" not in res.text


def test_spoofed_forwarded_for_does_not_change_client_key(monkeypatch):
    from starlette.requests import Request

    monkeypatch.setattr(config, "TRUSTED_PROXY_HOPS", 1)
    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 203.0.113.9")],
        "client": ("10.0.0.1", 1234),
    }
    assert auth.client_ip(Request(scope)) == "203.0.113.9"
