# Sada — Team Guide

Sada is an AI system for SBA's digital media. It tracks engagement across SBA's official channels, predicts what will trend, finds the best publish times, explains spikes and drops, analyzes what the audience says, and shows it all on a live dashboard.

**The judges score:**

1. **Behavioral-analysis accuracy**: we *measure* it (`GET /api/model/accuracy`), we don't claim it.
2. **Ease of use**
3. **Speed / latency**
4. **Scalability / reliability**

---

## Where we are

All four hackathon tasks are merged into `main`, along with X collection and audience analysis.

| Area | Status |
|---|---|
| **Data Collector**: 9 YouTube channels, 4 X accounts, audience comments, follower counts | ✅ Live on YouTube; X wherever `X_BEARER_TOKEN` is set |
| **Instagram** | 🟡 Collector built and tested; waiting on the Meta setup + verified handles (see below) |
| **Task 1 — Patterns & Optimizer** on real data | ✅ Pattern store is real data only; Optimizer recommends account + slot |
| **Task 2 — Trends, viral prediction & measured accuracy** | ✅ `TrendingPanel`, `AccuracyCard` |
| **Task 3 — Live dashboard, analytics & delivery** | ✅ Analytics summary, platform switch, heatmap, CI, `vercel.json` |
| **Task 4 — Spikes, drops & diagnosis** | ✅ Alerts view (التنبيهات والتشخيص), `AlertsPanel` |
| **Audience analysis**: sentiment, intent, follower growth | ✅ تحليل الجمهور view |

Open work and the post-hackathon backlog are in [NEXT_STEPS.md](NEXT_STEPS.md). Agent contracts are in [AGENT_SPEC.md](AGENT_SPEC.md), and the endpoint list is in [backend/README.md](backend/README.md#api).

---

## Setup (new laptop, 30 minutes)

```bash
git pull
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env       # add your own GEMINI_API_KEY (DATA_COLLECTION.md section 2); leave SADA_ACCESS_PASSWORD empty
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz   # real SBA data, no API key needed
uvicorn backend.api:app --reload --port 8000
npm install && npm run dev                  # http://localhost:5173
pytest backend/tests -q
```

Only the lead holds `YOUTUBE_API_KEY` and `X_BEARER_TOKEN`. Everyone else works from the seed file, so we don't spend quota or money four times. To refresh your data, ask the lead for a new export.

**Keys:** each of you creates your own Gemini key. The YouTube key, X token and Meta token are created once, per [DATA_COLLECTION.md](DATA_COLLECTION.md). **Never commit a key or paste it in the group chat.**

---

## Instagram go-live (one person, ≈1 hour)

The Instagram collector is **already built and tested**. It only needs credentials and the list of official accounts. Follow [DATA_COLLECTION.md](DATA_COLLECTION.md) section 3:

1. Create or convert an Instagram **professional** account we control and link it to a Facebook Page (3.1).
2. Create the Meta developer app (3.2).
3. Generate the token, extend it to 60 days, and find our `INSTAGRAM_BUSINESS_ACCOUNT_ID` (3.3).
4. **Verify SBA's official Instagram handles** with the Business Discovery test query, and add them to `SBA_INSTAGRAM_ACCOUNTS` in [backend/sba_channels.py](backend/sba_channels.py). Only `saudiyatv` is listed today. PR: `data: verified Instagram accounts` (3.4).
5. Send `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` **privately to the lead** (3.5).

**Done when** `python -m backend.agents.data_collector_agent --platform instagram` collects posts with status `success`, the PR is merged, and the lead has the credentials on Render.

---

## Who owns what

| Area | Files |
|---|---|
| **Patterns & Optimizer** | `backend/agents/behavior_analysis_agent.py`, `backend/agents/content_optimizer_agent.py`, `src/components/OptimizerView.tsx` |
| **Trends & Prediction** | `backend/agents/trend_prediction_agent.py`, `src/components/TrendingPanel.tsx`, `src/components/AccuracyCard.tsx` |
| **Dashboard & Delivery** | `backend/analytics.py`, `src/components/DashboardView.tsx`, `src/App.tsx`, `src/components/Sidebar.tsx`, `vercel.json`, `.github/workflows/ci.yml` |
| **Alerts & Diagnosis** | `backend/agents/anomaly_agent.py`, `backend/agents/diagnostic_recommendation_agent.py`, `src/components/BroadcastView.tsx` (Alerts view), `src/components/AlertsPanel.tsx` |
| **Audience** | `backend/agents/audience_agent.py`, `src/components/AudienceView.tsx` |

Each area also owns its `backend/tests/test_*.py`.

**Shared files.** Append only, inside your own `# --- Task N ---` block, and never edit someone else's block:
- `backend/api.py` (your routes)
- `backend/schemas.py` (your response models)
- `src/types/index.ts`

**Locked files.** Ask in the team chat before touching these:
- `backend/db.py`, `backend/repository.py`
- `backend/agents/data_collector_agent.py` and the platform clients/collectors: `youtube_client.py`, `instagram_client.py`, `instagram_collector.py`, `x_client.py`, `x_collector.py`, `audience_collector.py`
- `backend/auth.py`, `backend/config.py`
- `src/lib/api.ts`

**API shapes.** Don't change a response shape without telling the team; changes are additive only. `VideoOut` covers YouTube videos, X posts and Instagram posts: check `platform`, and use `url` for links, never a hand-built URL.

---

## Shared rules

- **Branch per change**, small PRs into `main` at least daily. CI (pytest on SQLite + Postgres, frontend build) must be green before merging.
- **Real numbers only.** If something can't be computed from the data, hide it or label it "تجريبي". A fake number on stage costs more credibility than a missing chart.
- **Never treat missing as zero.** Likes and comments can be `null` (hidden by the account). Instagram views are always `null`. Unclassified comments are not neutral.
- **Riyadh time** for anything hour- or day-based. `analysis_records()` already converts it.
- **Compare platforms only on `performance_index`.** YouTube views, X impressions and Instagram likes measure different things.
- **All HTTP goes through `apiFetch`** in `src/lib/api.ts`. New `/api` routes go on the authenticated `api` router.
- **Every agent output cites evidence:** a number, a sample size, or a link to a real post.
- **Don't spend quota or money from laptops.** Use the seed file; production collects on its own. X is billed per post read.
- **No personal data.** Audience analysis is aggregate only; never store or show commenter names, handles or ids.
- **Keys stay private:** never commit them, paste them in the group chat or show them on screen. If one leaks, regenerate it ([DATA_COLLECTION.md](DATA_COLLECTION.md) section 1).
