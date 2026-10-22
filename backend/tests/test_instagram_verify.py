import httpx
import pytest

from backend import instagram_verify
from backend.agents.instagram_client import InstagramAuthError, InstagramClient


def _client(handler) -> InstagramClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return InstagramClient("token", "123", "v23.0", http=http, max_retries=0, backoff_seconds=0)


def _handler(request: httpx.Request) -> httpx.Response:
    fields = request.url.params["fields"]
    if "username(good)" in fields:
        return httpx.Response(
            200,
            json={
                "business_discovery": {
                    "id": "1",
                    "username": "good",
                    "name": "Good Channel",
                    "followers_count": 1200000,
                    "media_count": 40,
                    "media": {"data": [{"id": "a", "timestamp": "2026-10-14T18:30:00+0000"}]},
                }
            },
        )
    return httpx.Response(400, json={"error": {"code": 110, "message": "Invalid user id"}})


def test_check_handles_reports_each_handle_separately():
    results = instagram_verify.check_handles(_client(_handler), ["good", "wrong_handle"])

    assert results[0]["ok"] is True
    assert results[0]["followers_count"] == 1200000
    assert results[0]["latest_post"] == "2026-10-14"
    assert results[1]["ok"] is False
    assert "not found" in results[1]["error"]


def test_expired_token_stops_the_whole_check():
    def expired(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 190, "message": "expired"}})

    with pytest.raises(InstagramAuthError):
        instagram_verify.check_handles(_client(expired), ["good", "other"])


def test_main_refuses_to_run_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr(instagram_verify.config, "INSTAGRAM_ENABLED", False)
    assert instagram_verify.main(["good"]) == 2
    assert "META_ACCESS_TOKEN" in capsys.readouterr().out
