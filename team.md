# Sada — Hackathon Build Plan (team.md)

**3 days · 4 people · work in parallel from hour one.**

Sada is an AI system for SBA's digital media. It tracks engagement across SBA's official channels, predicts what will go viral, finds the best publish times, explains spikes and drops, and shows it all on a live dashboard.

## 📣 Summary for the team: what changed since the MVP

1. **Production-ready platform.** Login (team password), rate limiting, error handling, env-based config, and a deploy setup for Render (backend + Postgres) and Vercel (frontend). The Optimizer now calls the real agent; fake UI (hardcoded notifications, "scheduled" popups, fake uploads) was removed.
2. **Real SBA data, no more synthetic.** A new **Data Collector agent** pulls every video from the last 60 days on **9 official SBA YouTube channels** into a database, and refreshes the stats every 30 minutes. First collection: **2,901 videos, ~49M views**. The seed file `backend/data/sba_youtube_seed.json.gz` gives you the same data locally in one command.
3. **Corrected channel list.** 5 of the original 8 YouTube handles were wrong (non-existent, or tiny unofficial channels). The verified list is in [backend/sba_channels.py](backend/sba_channels.py).
4. **Instagram is collected automatically too**, through Meta's free official API, into the same tables (`platform` = `"instagram"`). The code is built and tested. It goes live once **one teammate does the ≈1 h Meta setup** (see "Instagram setup" below). **Nobody collects anything by hand.**
5. **X and TikTok are not collected.** Their APIs need a paid subscription (X) or an approval that takes weeks (TikTok). In the pitch, they are future work that plugs into the same pipeline.
6. **Docs:**
   - [AGENT_SPEC.md](AGENT_SPEC.md): agent contracts, now including the Data Collector
   - [DEPLOYMENT.md](DEPLOYMENT.md): how to deploy
   - [DATA_COLLECTION.md](DATA_COLLECTION.md): data sources + **how to create every API key**
   - this file: who builds what

**The judges score:**

1. **Behavioral-analysis accuracy**: we must *measure* it, not claim it.
2. **Ease of use**
3. **Speed / latency**
4. **Scalability / reliability**

---

## What already exists (don't rebuild it)

| Piece | Where | Notes |
|---|---|---|
| **Data Collector agent** | [backend/agents/data_collector_agent.py](backend/agents/data_collector_agent.py) | Collects **real data from 9 official SBA YouTube channels** (~10.5M subscribers, see [backend/sba_channels.py](backend/sba_channels.py)) and **SBA Instagram accounts** (`instagram_collector.py`) every 30 min on Render, inside a quota budget. Stores a stats **snapshot per refresh**, so velocity is available. |
| Database | [backend/db.py](backend/db.py) | Tables `channels` (YouTube channels + Instagram accounts), `videos` (YouTube videos + Instagram posts), `video_snapshots`, `collector_runs`. A `platform` column tells them apart. Postgres on Render, SQLite locally. |
| Read helpers | [backend/repository.py](backend/repository.py) | **Use `analysis_records()` for every analysis.** It removes the account-size and post-age confounds and adds Riyadh-time `publish_hour` / `day_of_week`, `engagement_rate` and **`performance_index`**: the post's main metric ÷ its own account's typical value. Views on YouTube; likes + comments on Instagram, whose API has no views. **Compare across platforms only on `performance_index`.** |
| Topic taxonomy | [backend/topics.py](backend/topics.py) | 9 topics (`news`, `sports`, `religious`, …). Rule-based on collection, refined by Gemini. |
| Data API | `GET /api/channels`, `GET /api/videos`, `GET /api/videos/{id}` (with snapshots), `GET /api/collector/status`, `POST /api/collector/run` | All accept `?platform=youtube` or `?platform=instagram` |
| Platform | Login, rate limiting, deploy config, frontend API client | See [DEPLOYMENT.md](DEPLOYMENT.md). |
| MVP agents | Behavior, Optimizer, Diagnosis, Live-clip | They run on **synthetic** seed data today. Tasks 1 and 4 move them onto real data. |

The original agent contracts are in [AGENT_SPEC.md](AGENT_SPEC.md).

**Data source limits.** YouTube and Instagram are collected automatically through their official, free APIs. Instagram exposes no views, reach or shares for accounts we don't own, only likes and comments. X and TikTok are out of scope because their APIs aren't freely available. Say this openly in the pitch: it's a deliberate, honest scoping decision. Details: [DATA_COLLECTION.md](DATA_COLLECTION.md).

---

## Setup (everyone, first 30 minutes)

```bash
git pull
pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env       # add your own GEMINI_API_KEY (DATA_COLLECTION.md section 2); leave SADA_ACCESS_PASSWORD empty
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz   # real SBA data, no API key needed
uvicorn backend.api:app --reload --port 8000
npm install && npm run dev                  # http://localhost:5173
pytest backend/tests -q
```

Only the lead needs a `YOUTUBE_API_KEY`. Everyone else works from the seed file, so we don't burn quota four times. To refresh your data, ask the lead for a new export.

**Keys:** each of you creates your own Gemini key. The YouTube key (lead) and the Meta token (the Instagram-setup owner) are created once, step by step, per [DATA_COLLECTION.md](DATA_COLLECTION.md). **Never commit a key or paste it in the group chat.**

---

## File ownership (this is what makes the 4 tasks independent)

| Task | Owns |
|---|---|
| **1 — Patterns & Optimizer** | `backend/agents/behavior_analysis_agent.py`, `backend/agents/content_optimizer_agent.py`, `src/components/OptimizerView.tsx`, `backend/tests/test_behavior_analysis.py`, `backend/tests/test_content_optimizer.py` |
| **2 — Trends & Viral Prediction** | `backend/agents/trend_prediction_agent.py` (new), `src/components/TrendingPanel.tsx` (new), `src/components/AccuracyCard.tsx` (new), `backend/tests/test_trend_prediction.py` (new) |
| **3 — Live Dashboard & Analytics** | `backend/analytics.py` (new), `src/components/DashboardView.tsx`, `src/App.tsx`, `src/components/Sidebar.tsx`, `backend/tests/test_analytics.py` (new), `vercel.json` (new), `.github/workflows/ci.yml` (new) |
| **Instagram setup** (one person, see below) | `SBA_INSTAGRAM_ACCOUNTS` in `backend/sba_channels.py` (that list only) |
| **4 — Spikes, Drops & Diagnosis** | `backend/agents/anomaly_agent.py` (new), `backend/agents/diagnostic_recommendation_agent.py`, `src/components/BroadcastView.tsx` (becomes the alerts view), `src/components/AlertsPanel.tsx` (new), `backend/tests/test_anomaly.py` (new), `backend/tests/test_diagnostic_recommendation.py` |

**Shared files.** Append only, inside your own `# --- Task N ---` block, and never edit someone else's block:
- `backend/api.py` (your routes)
- `backend/schemas.py` (your response models)
- `src/types/index.ts`

**Locked files.** Ask in the team chat before touching these:
- `backend/db.py`, `backend/repository.py`
- `backend/agents/data_collector_agent.py`, `backend/agents/youtube_client.py`, `backend/agents/instagram_client.py`, `backend/agents/instagram_collector.py`
- `backend/auth.py`, `backend/config.py`
- `src/lib/api.ts`

---

## API contracts (agreed now so frontend and backend can work in parallel)

Frontend work can start on day 1 against these shapes with mocked JSON, then switch to the real endpoint when it lands. **Don't change a shape without telling the team.** `VideoOut` is the existing model in `backend/schemas.py`. It covers YouTube videos *and* Instagram posts: check `platform`, and use `url` for links, never a hand-built YouTube URL.

```text
Task 1  GET  /api/patterns                         -> Pattern[]   (existing shape; add sources "real_youtube_sba" / "real_instagram_sba")
        POST /api/optimize                         -> OptimizationResult (existing shape, additive fields only)

Task 2  GET  /api/trending?hours=24&limit=10       -> TrendingItem[]   (YouTube only: needs view counts)
          TrendingItem = { video: VideoOut, views_per_hour: float, velocity_index: float,
                           viral_score: float (0-1), predicted_views_7d: int | null, reason: str }
        GET  /api/model/accuracy                   -> ModelAccuracy
          ModelAccuracy = { method: str, train_window: str, test_window: str, n_test: int,
                            mape: float, baseline_mape: float, top10_hit_rate: float, computed_at: datetime }

Task 3  GET  /api/analytics/summary?days=30        -> AnalyticsSummary
          AnalyticsSummary = { generated_at, data_as_of (last successful collector run),
            totals:      { posts, views, likes, comments, engagement_rate },        (views: YouTube only)
            by_platform: [{ platform, accounts, posts, followers, likes, comments }],
            by_channel:  [{ platform, entity_key, name_ar, subscriber_count, posts, views (null on Instagram),
                            median_performance_index, engagement_rate }],
            by_content_type: [{ platform, content_type, posts, median_performance_index }],
            by_topic:    [{ topic, label_ar, posts, median_performance_index }],
            best_times:  [{ platform, day_of_week, hour, median_performance_index, n }] }

Task 4  GET  /api/alerts?days=7                    -> Alert[]
          Alert = { alert_id, kind: "spike" | "drop", video: VideoOut,
                    metric: "views" | "interactions", observed: int, expected: int,
                    ratio: float, severity: "high" | "medium", detected_at: datetime }
        POST /api/diagnose/video  { video_id }     -> DiagnosisResult (existing shape)
```

**Embedded components.** Task 3's DashboardView renders these, and their owners build them:
- `<TrendingPanel />` and `<AccuracyCard />` from Task 2
- `<AlertsPanel compact />` from Task 4

Each component fetches its own data and takes no required props. Task 3 can start with a placeholder `<div>` until they land.

---

## Task 1 — Patterns & Optimizer on real data

*Challenge items 2, 3, 5 (predictive content, best time and channel, recommendations)*

**Owner:** _(assign)_

1. **Behavior agent.** Add `analyze_real_data()` that reads `repository.analysis_records()` and reuses the existing `_slice_pattern` statistics (Welch t-test, `MIN_SAMPLES`, `MIN_LIFT`).
   - Score on `performance_index`, not raw counts. Run each platform separately, then once across both for a `platform` dimension ("Reels on Instagram vs. Shorts on YouTube").
   - New dimensions: `content_type`, `publish_hour` bucket and `day_of_week` (Riyadh time), `topic`, and `channel|topic`.
   - Tag patterns `source: "real_youtube_sba"` or `"real_instagram_sba"`. Extend the `dimension` Literal in `schemas.Pattern` inside your block.
   - Keep the synthetic and Hajj patterns, but real ones must come first.
2. **Make `run()` include real patterns.** Then `POST /api/patterns/refresh` rebuilds from the database.
3. **Optimizer.** It recommends **platform + account + content type + publish slot** from real patterns.
   - Add an optional `channel_options: list[str]` (entity keys) to `DraftContent`, additive only.
   - Time windows come from the real best hours, not the 4 hardcoded buckets.
   - Topics come from `backend/topics.py`.
4. **OptimizerView.** Replace the platform buttons with SBA account chips from `GET /api/channels`, grouped by platform. Replace the topic list with the 9 real topics.
5. **Tests.** Real-data patterns appear from a seeded test DB (see `backend/tests/test_data_collector.py` for the fake-YouTube fixtures). A slice under `MIN_SAMPLES` is never surfaced.

**Done when:** the dashboard pattern cards show real SBA patterns with real numbers. For example: "Shorts on @Riyadiyatv after 9pm get 2.1× the channel's usual views (n=84, t=4.2)."

---

## Task 2 — Trends, viral prediction & measured accuracy

*Challenge item 2 plus the **accuracy** criterion*

**Owner:** _(assign)_

1. **`trend_prediction_agent.py`.**
   - **Scope: YouTube only.** Trending and prediction need view counts, which Instagram doesn't expose. Filter on `platform == "youtube"`.
   - **Velocity:** from `video_snapshots`, compute views/hour between the last two snapshots. `velocity_index` = that velocity ÷ the channel's median velocity for videos of the same age bucket.
   - **Viral score:** a 0–1 score from early velocity, channel baseline and content type. Keep it explainable; `reason` says why in Arabic.
   - **Prediction:** `predicted_views_7d` from early views using the channel's typical growth curve, i.e. the median ratio of day-7 views to day-1 views in our snapshot history. Return `null` when history is too short; never guess.
2. **Backtest (the judges' accuracy number).**
   - Hold out the newest ~20% of videos (by publish date).
   - Predict their 7-day views from their first-day data.
   - Report MAPE plus top-10 hit rate: of our predicted top 10, how many were in the actual top 10.
   - Compare against a naive baseline (predict "channel median") so the number means something.
   - Cache the result and recompute at most hourly.
3. **Endpoints:** `GET /api/trending` and `GET /api/model/accuracy`, per the contracts above.
4. **UI.**
   - `TrendingPanel.tsx`: the top videos now, with thumbnail (`https://i.ytimg.com/vi/{id}/mqdefault.jpg`), channel, views/hour, a viral-score bar and a link to YouTube.
   - `AccuracyCard.tsx`: MAPE vs. baseline and the hit rate, plus one sentence explaining the method.
5. **Tests:** synthetic snapshot series with a known growth curve → the prediction is within tolerance; the backtest beats the naive baseline on the fixture.

**Done when:** the dashboard shows what's trending right now across SBA, and a real, reproducible accuracy number beats the baseline.

---

## Task 3 — Live dashboard, analytics & delivery

*Challenge items 1 and 6 plus the **usability, latency and reliability** criteria*

**Owner:** _(assign)_

1. **`backend/analytics.py` + `GET /api/analytics/summary`**, per the contract above. Build it from `repository.analysis_records()`, and read `data_as_of` from `collector_runs`.
   - **Cache in memory for 60 s.** The target is under 100 ms, and that latency is part of the score.
2. **DashboardView.**
   - Replace every hardcoded number (KPI cards, `weeklyData`, `platforms`, the period filter) with the summary.
   - Add:
     - a **YouTube / Instagram / all** platform switch
     - a cross-channel comparison chart
     - a **best-time heatmap** (day × hour of `median_performance_index`), per platform
     - topic and content-type breakdowns
   - Embed `<TrendingPanel/>`, `<AccuracyCard/>` and `<AlertsPanel compact/>`.
   - **Auto-refresh every 60 s.** Show "آخر تحديث للبيانات: قبل X دقيقة" from `data_as_of`.
3. **App shell.**
   - Remove the fake status badges ("بث مباشر متصل", "تزامن الوكلاء نشط") and replace them with a real collector-status pill from `/api/collector/status`.
   - Remove the dead search box.
   - Lazy-load views with `React.lazy` to clear the 619 kB bundle warning.
   - Rename navigation labels to match the new views.
4. **Delivery.**
   - `.github/workflows/ci.yml` runs on every push/PR:
     - pytest on SQLite, then again against a Postgres service container via `SADA_TEST_DATABASE_URL`
     - `npm ci`, `npm run build`
     - add lint once an `eslint.config.js` exists
   - `vercel.json` with security headers.
   - Deploy per [DEPLOYMENT.md](DEPLOYMENT.md) on **day 2**, not day 3.
5. **Load test** (reliability score): `pip install locust`; run 50 users against `/api/analytics/summary` and `/api/trending`. Put p95 latency and the error rate in the pitch.

**Done when:** the production dashboard shows only real numbers, refreshes itself, loads fast, and CI is green.

---

## Task 4 — Spikes, drops & root-cause diagnosis

*Challenge items 4 and 5*

**Owner:** _(assign)_

1. **`anomaly_agent.py` + `GET /api/alerts`.**
   - For each recent post, compare `observed` with `expected` on its platform's main metric: views on YouTube, likes + comments on Instagram. Expected = the account's median for the same content type at the **same age**; snapshots give values at each age.
   - Flag `ratio ≥ 3` as a spike and `ratio ≤ 0.33` as a drop, with high/medium severity.
   - **Also detect sudden velocity changes** between consecutive snapshots: a video that suddenly takes off, or stalls.
2. **Diagnosis on real videos: `POST /api/diagnose/video`.**
   - Retrieve comparable posts from the database (same platform + account + topic + content type, ±14 days).
   - Compare on publish hour, duration, title features (question mark, numbers, emoji, length) and engagement rate.
   - Pass that evidence to the existing Gemini synthesis, and return the existing `DiagnosisResult` shape.
   - **Every factor must cite real comparable posts** (`evidence_url_or_ref` = the post's `url`, YouTube or Instagram).
   - No comparables → `low_confidence: true`. Never invent a reason.
3. **Alerts view.** Turn `BroadcastView.tsx` into "التنبيهات والتشخيص":
   - an alert list (spike = green, drop = red)
   - clicking an alert runs the diagnosis
   - the chat shows the diagnosis with linked evidence
   - Keep the live-clip demo only if it is clearly labeled as a simulation. Otherwise remove it.
   - Also build `AlertsPanel.tsx` (the compact version, for the dashboard).
4. **Tests:** fixture with one clear spike, one clear drop and normal noise → only the two are flagged. A diagnosis with no comparables returns `low_confidence`.

**Done when:** you can click a real SBA video that under-performed and get a specific, evidence-linked explanation that differs from an over-performer's.

---

## Instagram setup (one person, ≈1 hour, day 1 morning)

*Challenge item 1: cross-platform analytics*

**Owner:** _(assign; suggested: the Task 4 owner, whose day-1 morning is the lightest)_

The Instagram collector is **already built and tested**. It only needs credentials and the list of official accounts. Follow [DATA_COLLECTION.md](DATA_COLLECTION.md) section 3, step by step:

1. Create or convert an Instagram **professional** account we control and link it to a Facebook Page (3.1).
2. Create the Meta developer app (3.2).
3. Generate the token, extend it to 60 days, and find our `INSTAGRAM_BUSINESS_ACCOUNT_ID` (3.3).
4. **Verify SBA's official Instagram handles** with the Business Discovery test query, and add them to `SBA_INSTAGRAM_ACCOUNTS` in [backend/sba_channels.py](backend/sba_channels.py). PR: `data: verified Instagram accounts` (3.4).
5. Send `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` **privately to the lead** (3.5). Don't use the group chat, and never commit them.

**Done when:**
- `python -m backend.agents.data_collector_agent --platform instagram` collects posts locally with status `success`
- the verified-accounts PR is merged
- the lead has the credentials on Render

Deadline: **day 1, 18:00**.

---

## Timeline

| | Day 1 | Day 2 | Day 3 |
|---|---|---|---|
| **All** | Setup, Gemini key and seed import (30 min). Instagram setup done by 18:00 (one person) | **Deploy** (Task 3 leads); Instagram data flowing in production; everyone checks their feature on real YouTube + Instagram data | Code freeze **at noon**; bug fixes only, then demo rehearsal |
| **Backend** | Agent + endpoint + tests, working on seed data | Tune on fresh production data; performance | Fixes |
| **Frontend** | UI against mocked JSON from the contracts | Switch to real endpoints; polish; Arabic copy | Fixes |

**Daily sync** at 9:00 and 18:00, 15 minutes: what merged, what's blocked, any contract changes.

---

## Shared rules

- **Branch per task:** `task-1-patterns`, `task-2-trends`, `task-3-dashboard`, `task-4-alerts`. Open small PRs into `main` at least daily. CI must be green before merging.
- **Real numbers only.** If something can't be computed from the data, hide it or label it "تجريبي". A fake number on stage costs more credibility than a missing chart.
- **Never treat missing as zero.** Likes and comments can be `null` (hidden by the account). Instagram views are always `null`.
- **Riyadh time** for anything hour- or day-based. `analysis_records()` already converts it.
- **All HTTP goes through `apiFetch`** in `src/lib/api.ts`. New `/api` routes go on the authenticated `api` router.
- **Every agent output cites evidence:** a number, a sample size, or a link to a real video.
- **Don't spend YouTube quota from laptops.** Use the seed file; production collects on its own.
- **Compare platforms only on `performance_index`.** Raw YouTube views and Instagram likes measure different things.
- **Keys stay private:** never commit them, paste them in the group chat or show them on screen. If one leaks, regenerate it ([DATA_COLLECTION.md](DATA_COLLECTION.md) section 1).
