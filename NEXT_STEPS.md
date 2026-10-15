# Sada — Next Steps

> **The current plan is in [team.md](team.md).** This file records what has been completed and what is deliberately left for after the hackathon.

## ✅ Done

- **Frontend ↔ backend integration** (the old Tasks A–D):
  - Dashboard patterns, Optimizer, Broadcast clip detection and the AWJ diagnosis all call the real API through `src/lib/api.ts`.
  - CORS is configured from `CORS_ORIGINS`.
- **Production hardening:**
  - team-password login with signed, expiring tokens
  - per-IP rate limiting on Gemini and login routes
  - clean 502/503 errors
  - `/health`, pinned dependencies, startup config validation
  - Render + Vercel deploy config ([DEPLOYMENT.md](DEPLOYMENT.md))
- **Real data:**
  - Data Collector agent for 9 official SBA YouTube channels, with a Postgres/SQLite database and stats snapshots
  - Instagram collector (Meta Graph API), storing into the same tables, tested
  - seed export for the team
  - see [AGENT_SPEC.md](AGENT_SPEC.md) Task 5

## 🔄 In progress (hackathon, see team.md)

1. Patterns & Optimizer on real data
2. Trends, viral prediction & measured accuracy
3. Live dashboard, analytics & delivery
4. Spikes, drops & root-cause diagnosis
5. Instagram go-live: Meta setup + verified SBA accounts ([DATA_COLLECTION.md](DATA_COLLECTION.md) section 3). The collector code is done.

## 🗂️ After the hackathon

- Per-user accounts (replace the shared password).
- Move the collector to a Render Cron Job and rate limits to Redis, so the API can scale past one instance.
- Schema migrations (Alembic) instead of `create_all`.
- X / TikTok collectors, if paid or approved API access is obtained. Alternatively, ask SBA's social team for X Analytics / TikTok Studio exports.
- A Meta system-user token, so Instagram access doesn't expire after 60 days.
- Upgrade Postgres off the free plan (it expires after 30 days).
