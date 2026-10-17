# 🎙️ Sada (صدى) - AI Audience Engagement Platform

Sada is a multi-agent AI platform for the **Saudi Broadcasting Authority (SBA)**. It collects real engagement data from SBA's official YouTube, Instagram and X accounts. It finds which content, timing and channel work best, predicts what will trend, flags spikes and drops and explains them, and shows what the audience says about SBA. Everything appears on a live Arabic (RTL) dashboard.

**The judges score:** behavioral-analysis accuracy (we *measure* it: `GET /api/model/accuracy`), ease of use, speed/latency, and scalability/reliability.

| Doc | For |
|---|---|
| **README.md** (this file) | Overview, setup, status, team rules |
| [AGENT_SPEC.md](AGENT_SPEC.md) | Agent specifications and JSON contracts |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Data sources, **how to create every API key**, deploying to Render + Vercel, configuration |
| [backend/README.md](backend/README.md) | Backend internals, database, datasets, endpoints, tests |

---

## 🤖 The Agents

All agents share one database and one pattern store.

1. **🛰️ Data Collector:** every 30 minutes, collects posts and a stats time series from SBA's official YouTube, X and Instagram accounts, plus audience comments and follower counts. It uses official APIs only, within a fixed quota and cost budget.
2. **📊 Behavior Analysis:** finds statistically significant engagement patterns by content type, publish time, topic, account and platform. Every pattern cites its sample size and test statistic.
3. **🚀 Content Optimizer:** generates caption variants with Gemini, scores them against the patterns, and recommends a variant, SBA account and publish slot.
4. **📈 Trend & Viral Prediction:** ranks what's trending now, gives each video a viral score, predicts its day-7 views, and backtests its own accuracy against a naive baseline.
5. **🚨 Anomaly Detection:** flags posts that spike or drop compared with their peers at the same age.
6. **🩺 Diagnostic & Recommendation:** explains why a post over- or under-performed, using comparable real posts, with an evidence link for every factor.
7. **💬 Audience Analysis:** classifies YouTube comments and X replies by sentiment and intent (praise, criticism, request, question, reaction) and tracks follower growth. It reports aggregates only and stores no author data.
8. **🎬 Live Clip Detection:** detects engagement spikes in a broadcast signal and maps them to segments. Backend only, and runs on a simulated signal.

---

## 📦 Data Sources

| Source | Type | Status |
|---|---|---|
| 9 official SBA YouTube channels | **Real**, YouTube Data API v3, every 30 min | ✅ 7,777 videos / ~95M views over 180 days |
| 5 official SBA X accounts | **Real**, X API v2, pay-per-use with a hard budget | ✅ 7,283 posts in the seed; live wherever `X_BEARER_TOKEN` is set |
| Official SBA Instagram accounts | **Real**, Meta Graph API Business Discovery | 🟡 Code ready; goes live after the Meta setup ([DEPLOYMENT.md](DEPLOYMENT.md) §3) |
| Audience comments (YouTube + X) | **Real**, same run, no author data | ✅ |
| SBA Hajj 1445H media statistics | **Real**, SBA open data (season totals) | ✅ |
| AWJ \| Sada podcast dataset | **Real**, curated | ✅ |
| TikTok | Not collected: the API needs a weeks-long approval | Future work |

The dashboard and the pattern store show **real data only**. The old synthetic seed files are kept only as fixtures for the MVP endpoints and tests.

---

## 🛠️ Tech Stack

* **Frontend:** React (TypeScript) + Vite, Tailwind CSS, Recharts, Lucide icons. RTL, light "enterprise" theme with royal-green accents
* **Backend:** FastAPI (Python 3.11), Google Gemini, YouTube Data API v3, Instagram Graph API, X API v2
* **Database:** PostgreSQL in production, SQLite locally (SQLAlchemy)
* **Security:** team-password login with signed tokens, per-IP rate limiting
* **Hosting:** Vercel (frontend) + Render (API + Postgres). CI on GitHub Actions

---

## 🚀 Local Development

```bash
# Backend (terminal 1)
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env                                    # add your own GEMINI_API_KEY (DEPLOYMENT.md §2)
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz # real SBA data, no key needed
uvicorn backend.api:app --reload --port 8000

# Frontend (terminal 2)
npm install
npm run dev
```

Open `http://localhost:5173/`. Login is skipped locally while `SADA_ACCESS_PASSWORD` is empty. Run the tests with `pytest backend/tests -q`.

Only the lead holds `YOUTUBE_API_KEY` and `X_BEARER_TOKEN`. Everyone else works from the seed file, so we don't spend quota or money four times. To refresh your data, ask the lead for a new export.

---

## 📍 Status

**Done:** all four hackathon tasks (patterns & optimizer on real data, trends & measured accuracy, live dashboard & CI, spikes/drops & diagnosis), X collection, and audience analysis.

**Open:**
1. **Instagram go-live.** The collector is built and tested; it needs credentials and verified handles. One person follows [DEPLOYMENT.md](DEPLOYMENT.md) §3 (≈1 hour): create the Meta app and token, verify each SBA handle with the Business Discovery query, add it to `SBA_INSTAGRAM_ACCOUNTS` in [backend/sba_channels.py](backend/sba_channels.py), and send the token **privately** to the lead.
2. **X in production:** fill `X_BEARER_TOKEN` on Render once the X account has credit.
3. **Load test:** run 50 users against `/api/analytics/summary` and `/api/trending`, and put p95 latency and the error rate in the pitch.

**After the hackathon:**
- Per-user accounts instead of the shared password.
- Move the collector to a Render Cron Job and rate limits to Redis, so the API can scale past one instance.
- Schema migrations (Alembic) instead of `create_all`.
- TikTok, if Research API access is approved; otherwise TikTok Studio exports from SBA's social team.
- A Meta system-user token, so Instagram access doesn't expire after 60 days.
- Upgrade Postgres off the free plan (it expires after 30 days).
- A real live-broadcast signal for the Live Clip agent.

---

## 👥 Working on Sada

**Who owns what** (each area also owns its `backend/tests/test_*.py`):

| Area | Files |
|---|---|
| Patterns & Optimizer | `backend/agents/behavior_analysis_agent.py`, `content_optimizer_agent.py`, `src/components/OptimizerView.tsx` |
| Trends & Prediction | `backend/agents/trend_prediction_agent.py`, `src/components/TrendingPanel.tsx`, `AccuracyCard.tsx` |
| Dashboard & Delivery | `backend/analytics.py`, `src/components/DashboardView.tsx`, `src/App.tsx`, `Sidebar.tsx`, `vercel.json`, `.github/workflows/ci.yml` |
| Alerts & Diagnosis | `backend/agents/anomaly_agent.py`, `diagnostic_recommendation_agent.py`, `src/components/BroadcastView.tsx` (Alerts view), `AlertsPanel.tsx` |
| Audience | `backend/agents/audience_agent.py`, `src/components/AudienceView.tsx` |

**Shared files:** append only, inside your own `# --- Task N ---` block: `backend/api.py`, `backend/schemas.py`, `src/types/index.ts`.

**Locked files:** ask the team before touching `backend/db.py`, `backend/repository.py`, `backend/auth.py`, `backend/config.py`, `src/lib/api.ts`, `backend/agents/data_collector_agent.py`, or the platform clients and collectors (`youtube_client.py`, `instagram_*.py`, `x_*.py`, `audience_collector.py`).

**Rules:**
- **Small commits straight to `main`.** Keep CI green (pytest on SQLite + Postgres, frontend build).
- **API shapes are additive only.** Tell the team before changing one. `VideoOut` covers YouTube, X and Instagram: check `platform`, and use `url` for links.
- **Real numbers only.** If something can't be computed from the data, hide it or label it "تجريبي".
- **Never treat missing as zero.** Hidden likes, Instagram views and unclassified comments stay `null`.
- **Riyadh time** for anything hour- or day-based (`analysis_records()` already converts it).
- **Compare platforms only on `performance_index`.** YouTube views, X impressions and Instagram likes measure different things.
- **All HTTP goes through `apiFetch`** in `src/lib/api.ts`. New `/api` routes go on the authenticated `api` router.
- **Every agent output cites evidence:** a number, a sample size, or a link to a real post.
- **Don't spend quota or money from laptops.** Use the seed file; X is billed per post read.
- **No personal data.** Never store or show commenter names, handles or ids.
- **Keys stay private:** never commit them, paste them in chat or show them on screen. If one leaks, regenerate it ([DEPLOYMENT.md](DEPLOYMENT.md) §1).
