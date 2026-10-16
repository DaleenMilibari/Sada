# Sada — Next Steps

What's done, what's open, and what's deliberately left for after the hackathon. Day-to-day team info is in [team.md](team.md).

## ✅ Done

- **Platform:** team-password login with signed tokens, per-IP rate limiting, clean 502/503 errors, `/health`, startup config validation, Render + Vercel deploy config ([DEPLOYMENT.md](DEPLOYMENT.md)), and CI on SQLite + Postgres.
- **Real data:**
  - Data Collector for 9 official SBA YouTube channels, with snapshots every 30 min (2,901 videos in the first backfill)
  - X collector for 4 verified SBA accounts, with hard cost budgets
  - Instagram collector (built and tested)
  - Audience comments (YouTube + X) and follower snapshots, with no author data
  - Seed export for the team
- **Agents on real data:**
  - Pattern store built from real data only, and rebuilt on refresh
  - Optimizer recommends an SBA account and publish slot
  - Trending, viral score, day-7 prediction and a backtested accuracy number
  - Spike/drop alerts with evidence-linked diagnosis
  - Audience sentiment, intent and follower growth
- **Frontend:** live analytics dashboard (platform switch, best-time heatmap, trending, accuracy, alerts), Optimizer, Alerts and Audience views, all on the real API.

## 🔄 Open

1. **Instagram go-live:** Meta setup + verified SBA handles ([team.md](team.md#instagram-go-live-one-person-1-hour)).
2. **X in production:** add `X_BEARER_TOKEN` on Render (it isn't in `render.yaml` yet).
3. **Load test:** run 50 users against `/api/analytics/summary` and `/api/trending`, and put p95 latency and the error rate in the pitch.

## 🗂️ After the hackathon

- Per-user accounts (replace the shared password).
- Move the collector to a Render Cron Job and rate limits to Redis, so the API can scale past one instance.
- Schema migrations (Alembic) instead of `create_all`.
- TikTok, if Research API access is approved. Otherwise ask SBA's social team for TikTok Studio exports.
- A Meta system-user token, so Instagram access doesn't expire after 60 days.
- Upgrade Postgres off the free plan (it expires after 30 days).
- A real live-broadcast signal for the Live Clip agent, which runs on a simulated signal today.
