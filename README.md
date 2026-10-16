# 🎙️ Sada (صدى) - AI Audience Engagement Platform

Sada is a multi-agent AI platform for the **Saudi Broadcasting Authority (SBA)**. It tracks audience engagement across SBA's official channels, predicts which content will spread, recommends the best time and channel to publish, explains why content spiked or dropped, and shows it all on a live dashboard.

---

## 🤖 The Multi-Agent Architecture

All agents share one database and one pattern store:

1. **🛰️ Data Collector Agent:** collects real data every 30 minutes, through official APIs, from **9 official SBA YouTube channels** (~10.5M subscribers), **SBA's Instagram accounts** and **SBA's X accounts**. It keeps a stats time series for every post, within a fixed API quota budget.
2. **📊 Behavior Analysis Agent:** finds statistically significant engagement patterns by content type, topic, publish time and channel. Every pattern cites its sample size and test statistic.
3. **🚀 Content Optimizer Agent:** generates caption variants with Gemini, scores them against the patterns, and recommends the winning version, channel and publish time.
4. **🩺 Diagnostic & Recommendation Agent:** explains why a post over- or under-performed, grounded in comparable past content, with an evidence link for every factor.
5. **🎬 Live Clip Detection Agent:** detects engagement spikes during a broadcast and maps them to the segment that caused them.

Field contracts for each agent are in [AGENT_SPEC.md](AGENT_SPEC.md).

---

## 📦 Data Sources

| Source | Type | Status |
|---|---|---|
| 9 official SBA YouTube channels | **Real**, collected automatically every 30 min | ✅ Live: 2,901 videos / ~49M views in the first 60-day backfill |
| Official SBA Instagram accounts | **Real**, collected automatically via Meta's Graph API | 🟡 Code ready; goes live after the Meta setup in [DATA_COLLECTION.md](DATA_COLLECTION.md) |
| Official SBA X accounts | **Real**, via X API v2 (pay-per-use, hard-capped budget) | 🟡 Code ready; goes live once `X_BEARER_TOKEN` is set ([DATA_COLLECTION.md](DATA_COLLECTION.md) §5) |
| TikTok | Not collected: API needs approval | Future work |
| SBA Hajj 1445H media statistics | **Real**, SBA open data (season totals) | ✅ |
| AWJ \| Sada podcast dataset | **Real**, curated | ✅ |
| Engagement records, broadcast signal | Synthetic seed data (MVP) | Being replaced by real data |

---

## 🎨 UI/UX Design Philosophy

Designed using an upscale **Enterprise Light Mode** interface to reflect an official, high-stature institutional and corporate branding environment.
* Full **Right-to-Left (RTL)** layout support for native regional content.
* Crisp, professional palette incorporating elegant **Royal Green** accents alongside neutral corporate slates for optimal technical readability.

---

## 🛠️ Tech Stack

* **Frontend:** React.js (TypeScript) + Vite, Tailwind CSS, Recharts, Lucide icons
* **Backend:** FastAPI (Python), Google Gemini, YouTube Data API v3, Instagram Graph API
* **Database:** PostgreSQL in production, SQLite locally (SQLAlchemy)
* **Security:** team-password login with signed tokens, per-IP rate limiting
* **Hosting:** Vercel (frontend) + Render (API + Postgres). See [DEPLOYMENT.md](DEPLOYMENT.md)

---

## 🚀 Local Development Setup

```bash
# Backend (terminal 1)
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env                                    # add GEMINI_API_KEY
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz # real SBA data, no key needed
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
| [team.md](team.md) | **Start here:** current plan, task split, API contracts, timeline |
| [AGENT_SPEC.md](AGENT_SPEC.md) | Agent specifications and JSON contracts |
| [DATA_COLLECTION.md](DATA_COLLECTION.md) | Data sources and **how to create every API key** (Gemini, YouTube, Meta/Instagram) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying to Render + Vercel, configuration reference |
| [backend/README.md](backend/README.md) | Backend internals, datasets, endpoints |
