# 🎙️ Sada (صدى) - AI Audience Engagement Platform

Sada is a multi-agent AI platform for the **Saudi Broadcasting Authority (SBA)**. It collects real engagement data from SBA's official YouTube, Instagram and X accounts. It finds which content, timing and channel work best, predicts what will trend, flags spikes and drops and explains them, and shows what the audience says about SBA. Everything appears on a live Arabic (RTL) dashboard.

---

## 🤖 The Agents

All agents share one database and one pattern store. Field contracts are in [AGENT_SPEC.md](AGENT_SPEC.md).

1. **🛰️ Data Collector:** every 30 minutes, collects posts and a stats time series from **9 official SBA YouTube channels** (~10.5M subscribers), SBA's Instagram accounts and SBA's X accounts. It also collects audience comments and follower counts. All of it goes through official APIs, within a fixed quota and cost budget.
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
| 9 official SBA YouTube channels | **Real**, collected every 30 min (YouTube Data API v3) | ✅ Live: 2,901 videos / ~49M views in the first 60-day backfill |
| Official SBA X accounts (4 verified) | **Real**, X API v2, pay-per-use with a hard budget | ✅ Collector built; runs wherever `X_BEARER_TOKEN` is set |
| Official SBA Instagram accounts | **Real**, Meta Graph API Business Discovery | 🟡 Code ready; goes live after the Meta setup in [DATA_COLLECTION.md](DATA_COLLECTION.md) §3 |
| Audience comments (YouTube + X) | **Real**, collected in the same run, no author data | ✅ |
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
* **Hosting:** Vercel (frontend) + Render (API + Postgres). CI on GitHub Actions. See [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 🚀 Local Development

```bash
# Backend (terminal 1)
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env                                    # add GEMINI_API_KEY
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz # real SBA YouTube data, no key needed
uvicorn backend.api:app --reload --port 8000

# Frontend (terminal 2)
npm install
npm run dev
```

Open `http://localhost:5173/`. Login is skipped locally while `SADA_ACCESS_PASSWORD` is empty.

Run the tests with `pytest backend/tests -q`.

---

## 📚 Documentation

| File | For |
|---|---|
| [team.md](team.md) | **Start here:** how the team works, file ownership, API reference, rules |
| [AGENT_SPEC.md](AGENT_SPEC.md) | Agent specifications and JSON contracts |
| [DATA_COLLECTION.md](DATA_COLLECTION.md) | Data sources and **how to create every API key** (Gemini, YouTube, Meta, X) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying to Render + Vercel, configuration reference |
| [backend/README.md](backend/README.md) | Backend internals, datasets, endpoints, tests |
| [NEXT_STEPS.md](NEXT_STEPS.md) | What's done and what's left |
