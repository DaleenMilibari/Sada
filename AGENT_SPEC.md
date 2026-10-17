# Sada — Agent Specification

Each agent lives in its own file under `backend/agents/` and returns structured JSON (Pydantic models in `backend/schemas.py`). Field names and JSON shapes here are the contract the backend implements.

Every agent is specified with the same Agentic AI fields: Goal, Input, Trigger, Tools, Data/Context, Reasoning task, Decision, Action/Output, Memory/state, Evidence, Failure/fallback. No agent is a single LLM prompt. Each one visibly chooses between options, uses evidence, and produces a structured decision.

> **Numbering.** Code comments say "Task N" after the build task that created the code: Tasks 1–4 of the original MVP (Behavior, Optimizer, Diagnosis, Live clip), Task 5 (Data Collector), and Tasks 1–4 of the hackathon plan (Patterns & Optimizer, Trends, Dashboard, Alerts & Diagnosis; the plan itself is in git history as `team.md`). The sections below are ordered by agent instead.

---

## 1. Data Collector Agent

**Files:** `backend/agents/data_collector_agent.py` (orchestration), `youtube_client.py`, `instagram_client.py` + `instagram_collector.py`, `x_client.py` + `x_collector.py`, `audience_collector.py`; registry in `backend/sba_channels.py`; tables in `backend/db.py`.

- **Goal:** Keep a fresh, real per-post dataset for SBA's official accounts, with a stats time series, audience comments and follower counts, so every other agent runs on real data.
- **Input:** The account registry (`backend/sba_channels.py`: 9 verified YouTube channels, `SBA_INSTAGRAM_ACCOUNTS`, `SBA_X_ACCOUNTS`) plus what is already stored.
- **Trigger:** In-process scheduler every 30 min (production), `POST /api/collector/run`, or the CLI `python -m backend.agents.data_collector_agent [--platform all|youtube|instagram|x] [--budget N]`.
- **Available tools:**
  - YouTube Data API v3: `channels.list`, `playlistItems.list`, `videos.list`, `commentThreads.list`, 1 quota unit each.
  - Instagram Graph API Business Discovery: public profile and posts of business accounts, about 200 calls/hour.
  - X API v2 (pay-per-use, ≈$0.005 per post or reply read).
  - Gemini, for topic classification.
- **Data/context:** Tables `channels`, `videos`, `video_snapshots`, `audience_comments`, `follower_snapshots`, `collector_runs` (Postgres in production, SQLite locally).
- **Reasoning task:** Spend a fixed quota and money budget where it matters most.
- **Decision:**
  - Which channels to page, and when discovery has caught up: 50 consecutive known uploads, or the lookback cutoff.
  - Which YouTube videos are due a stats refresh, by age: under 2 days every 30 min, under 7 days every 2 h, under 30 days daily, older weekly.
  - Which posts to read comments/replies for (the most-viewed recent ones).
  - Which topics to refine with the LLM.
- **Action/output:**
  - Upserted channel and post rows (`platform` = `youtube` / `instagram` / `x`).
  - One `video_snapshots` row per refreshed post, and `follower_snapshots` rows (YouTube every 6 h, Instagram every run, X daily).
  - `audience_comments` rows: text, time and likes only.
  - A `collector_runs` row with status, counts and quota spent.
- **Memory/state:** The database. Runs are incremental, and backfill progress is derived from what's stored.
- **Evidence:** Every stored number is exactly what the API returned at `captured_at`. Hidden metrics stay `NULL`, never 0.
- **Failure/fallback:**
  - Transient errors are retried with backoff.
  - Quota exhaustion ends the run as `partial`; the next run resumes.
  - A failing platform (expired token, rate limit, exhausted X budget) fails only its own step, and the run is marked `partial`.
  - Only one run at a time. A platform without credentials is skipped.
  - No Gemini key → topics stay rule-based.

**Content type:** `short` (≤60s, or ≤180s tagged #shorts; the API has no Shorts flag), `video`, `live`, `image`, `carousel`, `text` (X).
**Topics:** `news`, `sports`, `religious`, `national_event`, `economy`, `talk_show`, `documentary`, `entertainment`, `other` (`backend/topics.py`).

**Per platform:**
- **YouTube:** views, likes, comments; refreshed on the age schedule above.
- **Instagram:** likes (`NULL` when hidden) and comments, but **no views, reach or shares** for accounts we don't own. Reels map to `short`. Once an account is backfilled, runs re-read only the last 7 days.
- **X:** each post is read **once**. New posts (`since_id`) are read for every account first; the remaining budget then backfills toward the cutoff one page at a time, always for the account with the shortest history, so a small budget evens the accounts out. The user timeline only reaches an account's ~3,200 latest tweets (under two weeks for a busy news account), so the backfill continues through full-archive search (`/2/tweets/search/all`) from the oldest stored post. Impressions are stored as `view_count`, replies as `comment_count`. Reposts and replies are excluded. `X_TOTAL_POST_BUDGET` and `X_REPLY_BUDGET` are hard stops across all runs.
- **Audience:** YouTube top comments for the most-viewed videos published 1–7 days ago, and X replies to the most-seen posts from the last ~7 days. **No author name, handle or id is stored.**

**Analysis input for other agents:** `backend/repository.analysis_records()`. One record per post, with Riyadh-time `publish_hour` / `day_of_week`, `engagement_rate`, and **`performance_index`**: the post's main metric (views on YouTube, impressions on X, likes + comments on Instagram) ÷ its own account + content type's median. Posts too young to compare are excluded. X posts use their age when measured, since they are never re-read.

**Acceptance criteria (met):** the first run backfills 60 days for all 9 YouTube channels (2,901 videos, 131 quota units); the next run is incremental (19 units). Extending the window to 180 days backfilled all 9 channels to 7,777 videos in one run (324 units). Quota exhaustion, concurrent runs, expired tokens, rate limits and the X budget are all tested against simulated APIs.

---

## 2. Behavior Analysis Agent

**File:** `backend/agents/behavior_analysis_agent.py`

- **Goal:** Detect engagement patterns across content types, topics, timing, accounts and platforms, and maintain the shared pattern store the other agents read.
- **Input:** `repository.analysis_records()`, plus the real Hajj 1445H totals and the AWJ | Sada dataset.
- **Trigger:** Startup, `POST /api/patterns/refresh`, or the CLI.
- **Available tools:** Aggregation over the records; Welch's t-test.
- **Data/context:** Real SBA posts only. The synthetic MVP seed is no longer published.
- **Reasoning task:** Find which attributes correlate with a higher or lower `performance_index`, and separate real effects from noise.
- **Decision:** A slice is surfaced only with `n ≥ MIN_SAMPLES` (10), a lift of at least `MIN_LIFT` (20%) and `t ≥ MIN_T_STAT` (2.5). Dimensions: content type, publish-hour bucket and day of week, topic, `channel|topic`, and a cross-platform comparison.
- **Action/output:** `Pattern[]`: `{pattern, supporting_metric, confidence, affected_content_types}` plus `pattern_id`, `dimension`, `slice_key`, `lift_pct` and `source` (`real_youtube_sba`, `real_instagram_sba`, `real_x_sba`, `real_sba`, `real_hajj_1445_sba`, `real_awj_sada`).
- **Memory/state:** `backend/store/pattern_store.json`. Each run **replaces** the store atomically, so a pattern that stops being significant disappears and readers never see a half-written file. `pattern_id` includes the source, so the same slice on two platforms is two patterns.
- **Evidence:** Each pattern cites its sample size, lift and t statistic.
- **Failure/fallback:** Too little data for a slice → no pattern for it. The Hajj and AWJ sources are too small to t-test, so they get plain descriptive comparisons with capped confidence. No database → no real patterns, never fabricated ones.

---

## 3. Content & Publishing Optimizer Agent

**File:** `backend/agents/content_optimizer_agent.py`

- **Goal:** Evaluate a draft before publishing and recommend the best variant, SBA account, content type and publish slot.
- **Input:** `DraftContent`: caption/headline options, content type, topic, optional `channel_options` (entity keys).
- **Trigger:** `POST /api/optimize` from the Optimizer view.
- **Available tools:** The pattern store; a scoring function; Gemini to generate 2–4 variants when none are supplied.
- **Reasoning task:** Score each variant × account × slot against the real patterns, comparing candidates with each other rather than in isolation. A pattern measured on one platform (`real_youtube_sba`, `real_x_sba`, `real_instagram_sba`) only scores candidates for that platform.
- **Decision:** The winning variant, account and time window. Time windows come from the real best hours.
- **Action/output:** `{recommended_variant, predicted_engagement, recommended_platform, recommended_time, ranked_alternatives[], evidence[]}`. `predicted_engagement` is a ranking index (100 = baseline), not a forecast.
- **Memory/state:** Stateless per call.
- **Evidence:** Every recommendation points to the pattern(s) it relied on.
- **Failure/fallback:** No relevant pattern → say so, and fall back to the highest-confidence general pattern (preferring one from the recommended platform), flagged as lower confidence. Gemini unavailable → the original text is scored on its own and the evidence says so; with no original text either, the API answers 503/502/504.
- **Limits:** at most 8 variants, 6 platforms and 30 accounts per request.

---

## 4. Trend & Viral Prediction Agent

**File:** `backend/agents/trend_prediction_agent.py`

- **Goal:** Say what is trending across SBA right now, how likely each video is to go viral and how many views it will have at day 7, and measure how accurate that prediction is.
- **Input:** YouTube posts and their `video_snapshots`. YouTube only, because prediction needs view counts.
- **Trigger:** `GET /api/trending`, `GET /api/model/accuracy`, or the CLI.
- **Available tools:** Plain statistics (medians, interpolation). No LLM, so every number is reproducible.
- **Reasoning task:**
  - Velocity = views/hour between the last two snapshots. `velocity_index` = velocity ÷ the channel's median velocity at the same age.
  - Viral score (0–1) = 0.60 momentum + 0.25 reach so far + 0.15 content-type track record.
  - Day-7 prediction = current views ÷ the typical share of day-7 views at this age, from finished videos' growth curves.
- **Decision:** Which videos rank as trending, their score, and whether there is enough history to predict at all.
- **Action/output:** `TrendingItem[]` = `{video, views_per_hour, velocity_index, viral_score, predicted_views_7d, reason}`; `ModelAccuracy` = `{method, train_window, test_window, n_test, mape, baseline_mape, top10_hit_rate, computed_at}`.
- **Memory/state:** In-process caches: trending for 60 s, the growth model and the backtest for an hour.
- **Evidence:** Each `reason` quotes the measured velocity and the baseline it is compared with. Accuracy is a temporal backtest on the newest ~20% of videos against a naive "channel median" baseline.
- **Failure/fallback:** Too little history → `predicted_views_7d` is `null` and accuracy reports `insufficient_history`. Never guessed.

---

## 5. Anomaly Detection Agent (spikes & drops)

**File:** `backend/agents/anomaly_agent.py`

- **Goal:** Flag posts that perform far above or below what is normal for them.
- **Input:** Posts and snapshots for the last `days` (default 7).
- **Trigger:** `GET /api/alerts` (cached 60 s).
- **Available tools:** Peer comparison and snapshot interpolation.
- **Reasoning task:**
  - **Level:** the post's main metric vs. peers (same platform + account + content type) **at the same age**. Posts ≥7 days old are compared on current values ("plateau").
  - **Velocity:** metric per hour between the latest two snapshots vs. the interval before them, to catch a post that suddenly takes off or stalls.
- **Decision:** `ratio ≥ 3` → spike, `ratio ≤ 0.33` → drop. `≥ 6` or `≤ 0.15` is high severity.
- **Action/output:** `Alert[]` = `{alert_id, kind, video, metric, observed, expected, ratio, severity, detected_at}`.
- **Memory/state:** Stateless apart from the cache.
- **Evidence:** `observed`, `expected` and the ratio.
- **Failure/fallback:** Fewer than 5 peers, posts younger than 6 h, or a tiny expected value → no alert.

---

## 6. Diagnostic & Recommendation Agent

**File:** `backend/agents/diagnostic_recommendation_agent.py`

- **Goal:** Explain why a post over- or under-performed, grounded in comparable real posts, and recommend what to do.
- **Input:** A `video_id` (`POST /api/diagnose/video`). The MVP endpoints `POST /api/diagnose` and `POST /api/diagnose/awj-sada` remain.
- **Trigger:** Clicking an alert or a post in the Alerts view.
- **Available tools:** Retrieval of comparable posts from the database (same platform + account + topic + content type, ±14 days; widened to account + content type when the topic has too few); the pattern store; Gemini for the narrative.
- **Reasoning task:** Compare the post with its comparables on publish hour, duration, title features (question mark, numbers, emoji, length) and engagement rate, instead of restating the metrics as prose.
- **Decision:** Which factors best explain the outcome, ranked by how well the evidence supports them.
- **Action/output:** `DiagnosisResult` = `{diagnosis, contributing_factors[{reason, supporting_metric, evidence_source_title, evidence_url_or_ref, confidence}], recommendations[], low_confidence}`.
- **Memory/state:** Stateless per call.
- **Evidence:** Every factor links to real comparable posts (`evidence_url_or_ref` = the post's `url`).
- **Failure/fallback:** No comparables → `low_confidence: true`. Never an invented reason. No Gemini key, a model error or a malformed reply (all three endpoints) → evidence-only wording built from the same factors.

---

## 7. Audience Analysis Agent

**File:** `backend/agents/audience_agent.py`

- **Goal:** Turn public comments (YouTube) and replies (X) into an aggregate picture of the audience: sentiment, what people praise, criticize, ask or request, which posts drive discussion, and follower growth per account.
- **Input:** `audience_comments` and `follower_snapshots`, joined to posts and channels.
- **Trigger:** The collector run (classification) and `GET /api/audience/summary?days=&platform=`.
- **Available tools:** Gemini classifies comments in batches of 50; everything else is deterministic aggregation.
- **Reasoning task:** Label each comment's sentiment (`positive` / `negative` / `neutral`) and intent (`praise`, `criticism`, `request`, `question`, `reaction` (to the news itself, not to SBA), `other`).
- **Decision:** Which intents and posts to surface, and whether a sample is large enough to report shares.
- **Action/output:** `AudienceSummary`: per-channel sentiment, intents with example comments, most-discussed posts, follower growth.
- **Memory/state:** Labels are stored on `audience_comments` (`sentiment`, `intent`, `classified_at`).
- **Evidence:** Every share comes with its sample size. Every intent lists real example comments linked to their post.
- **Failure/fallback:** Without a Gemini key, or once every key is out of quota, the run stops classifying and the rest wait for the next run; the summary shows `classified < comments`. Unclassified or invalid labels are **never counted as neutral**. Fewer than 10 classified comments → shares are `null`.
- **Privacy:** No author data exists in the database. Output is aggregate only (PDPL).

---

## 8. Live Clip Detection Agent

**File:** `backend/agents/live_clip_detection_agent.py`

- **Goal:** Find engagement spikes during a live broadcast and flag them as social-clip opportunities.
- **Input:** A timestamped engagement signal aligned to broadcast segments. **Currently a simulated signal** (`backend/data/broadcast_mock.json`); there is no live feed.
- **Trigger:** `POST /api/broadcast/detect-clips`, `GET /api/broadcast/signal`. Not shown in the UI.
- **Reasoning task:** Separate a real spike from normal fluctuation using a rolling baseline, and tie it to the segment it happened in.
- **Action/output:** `ClipOpportunity[]` = `{start_time, end_time, segment_label, spike_magnitude, confidence}`, ranked.
- **Evidence:** Deviation from the baseline plus the aligned segment.
- **Failure/fallback:** A noisy or flat signal, or a zero baseline → no clips. A posted signal is sorted by time first and capped at 20,000 points.

---

## Shared rules

- Use the exact field names and JSON shapes defined in `backend/schemas.py`. Changes are additive only.
- Every agent returns structured JSON the frontend consumes directly; no free-form prose blobs.
- Every recommendation or diagnosis traces back to a specific number, sample size or real post.
- Missing is never zero: hidden likes, Instagram views and unclassified comments stay `null`.
- Compare platforms only on `performance_index`.
- Every Gemini call has a per-request timeout and an overall deadline (`GEMINI_TIMEOUT_SECONDS`, `GEMINI_DEADLINE_SECONDS`), so no API request hangs on the model.
