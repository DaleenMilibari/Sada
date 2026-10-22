"""Check candidate Instagram handles against Business Discovery (DEPLOYMENT.md, section 3.4).

Needs META_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID in backend/.env.
Costs one Graph API call per handle.

    python -m backend.instagram_verify sbagovsa some_other_handle
    python -m backend.instagram_verify --registry     # re-check SBA_INSTAGRAM_ACCOUNTS

A handle that returns data is a real business/creator account we can collect.
That alone does not prove it is SBA's *official* account: also apply the
checks in DEPLOYMENT.md section 3.4 before adding it to sba_channels.py.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from backend import config
from backend.agents.instagram_client import (
    InstagramAccountNotFound,
    InstagramApiError,
    InstagramAuthError,
    InstagramClient,
    InstagramRateLimited,
    parse_timestamp,
)


def check_handles(client: InstagramClient, usernames: list[str]) -> list[dict[str, Any]]:
    """One result per handle: {"username", "ok", ...profile fields or "error"}.

    Stops early (re-raising) only for problems that affect every handle:
    an expired token or a rate limit.
    """
    results: list[dict[str, Any]] = []
    for username in usernames:
        try:
            account, media, _ = client.media_page(username)
        except (InstagramAuthError, InstagramRateLimited):
            raise
        except InstagramAccountNotFound:
            results.append({"username": username, "ok": False, "error": "not found, or not a business/creator account"})
            continue
        except InstagramApiError as e:
            results.append({"username": username, "ok": False, "error": str(e)})
            continue
        latest = max((t for t in (parse_timestamp(m.get("timestamp")) for m in media) if t), default=None)
        results.append(
            {
                "username": account.get("username", username),
                "ok": True,
                "name": account.get("name"),
                "followers_count": account.get("followers_count"),
                "media_count": account.get("media_count"),
                "latest_post": latest.date().isoformat() if latest else None,
            }
        )
    return results


def _format(result: dict[str, Any]) -> str:
    if not result["ok"]:
        return f"  FAIL  @{result['username']}: {result['error']}"
    followers = result["followers_count"]
    followers_text = f"{followers:,}" if isinstance(followers, int) else "?"
    return (
        f"  OK    @{result['username']}  |  {result['name']}  |  {followers_text} followers"
        f"  |  {result['media_count']} posts  |  latest post {result['latest_post'] or 'n/a'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Instagram handles via Business Discovery.")
    parser.add_argument("usernames", nargs="*", help="Instagram handles, without the @")
    parser.add_argument("--registry", action="store_true", help="check every handle in SBA_INSTAGRAM_ACCOUNTS")
    args = parser.parse_args(argv)

    usernames = [u.lstrip("@") for u in args.usernames]
    if args.registry:
        from backend.sba_channels import SBA_INSTAGRAM_ACCOUNTS

        usernames += [a["username"] for a in SBA_INSTAGRAM_ACCOUNTS]
    if not usernames:
        parser.error("give at least one handle, or --registry")

    if not config.INSTAGRAM_ENABLED:
        print("META_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID must both be set in backend/.env (DEPLOYMENT.md section 3).")
        return 2

    client = InstagramClient(config.META_ACCESS_TOKEN, config.INSTAGRAM_BUSINESS_ACCOUNT_ID, config.META_GRAPH_API_VERSION)
    try:
        results = check_handles(client, usernames)
    except (InstagramAuthError, InstagramRateLimited) as e:
        print(f"Stopped: {e}")
        return 2

    print(f"Checked {len(results)} handle(s):")
    for result in results:
        print(_format(result))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
