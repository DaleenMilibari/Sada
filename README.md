# 🎙️ Sada (صدى) - AI Audience Engagement Platform

Sada is a multi-agent AI platform for the **Saudi Broadcasting Authority (SBA)**. It collects real engagement data from SBA's official YouTube, Instagram and X accounts. It finds which content, timing and channel work best, predicts what will trend, flags spikes and drops and explains them, shows what the audience says about SBA, and spots clip-worthy moments in a live broadcast. Everything appears on a live Arabic (RTL) dashboard.

**The judges score:** behavioral-analysis accuracy (we *measure* it: `GET /api/model/accuracy`), ease of use, speed/latency, and scalability/reliability.

| Doc | For |
|---|---|
| **README.md** (this file) | Overview, setup, backend reference (layout, database, datasets, API, tests), status, team rules |
| [AGENT_SPEC.md](AGENT_SPEC.md) | Agent specifications and JSON contracts |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Data sources, **how to create every API key**, deploying to Render + Vercel, configuration |
| [rag/README.md](rag/README.md) | AWJ podcast RAG knowledge base (Chroma Cloud): transcript chunking and loading scripts, separate from the backend |

---

## 🤖 The Agents

Seven agents share one database and one pattern store. Each one's full spec is in [AGENT_SPEC.md](AGENT_SPEC.md).

| # | Agent | What it does | Where it shows |
|---|---|---|---|
| 1 | **🛰️ Data Collector** | Every 30 minutes, collects posts and a stats time series from SBA's official YouTube, X and Instagram accounts, plus audience comments and follower counts. Official APIs only, within a fixed quota and cost budget. | Status pill in the top bar |
| 2 | **📊 Behavior Analysis** | Finds statistically significant engagement patterns by content type, publish time, topic, account and platform. Every pattern cites its sample size and test statistic. | Dashboard |
| 3 | **🚀 Content Optimizer** | Suggests a first draft from SBA's best recent posts on the topic, writes caption variants in a Saudi media voice that knows the Riyadh and Hijri calendar (Ramadan, Eid, Hajj, national days), scores them against the patterns, and recommends a variant, account and publish slot. A **publishing playbook** gives one complete decision per topic. | Optimizer, Dashboard |
| 4 | **📈 Trend & Viral Prediction** | Ranks what's trending now, gives each video a viral score, predicts its day-7 views, and backtests its own accuracy against a naive baseline. | Dashboard |
| 5 | **🚨 Alerts & Diagnosis** | Flags posts that spike or drop compared with their peers at the same age, then explains a clicked alert: the root causes a team controls (posting in a burst, crowding, a weak time slot, a weak format), measured on the account's own history, plus a comparison with similar real posts. Every factor has an evidence link. | التنبيهات والتشخيص |
| 6 | **💬 Audience Analysis** | Classifies YouTube, Instagram and X comments by sentiment and intent (praise, criticism, request, question, reaction) with Saudi dialect cues, groups them into themes, measures its own accuracy against blind human labels, and tracks follower growth. Aggregates only, no author data. | تحليل الجمهور |
| 7 | **🎬 Live Clip Detection** | Detects engagement spikes during a broadcast and maps them to segments as clip opportunities. **Runs on a simulated signal** until the YouTube live feed is connected, and the page says so. | لقطات البث المباشر |

---

## 📦 Data Sources

| Source | Type | Status |
|---|---|---|
| 9 official SBA YouTube channels | **Real**, YouTube Data API v3, every 30 min | ✅ 7,777 videos / ~95M views over 180 days |
| 5 official SBA X accounts | **Real**, X API v2, pay-per-use with a hard budget | ✅ 7,283 posts in the seed; live wherever `X_BEARER_TOKEN` is set |
| 5 official SBA Instagram accounts | **Real**, scraper export loaded with `python -m backend.instagram_import`; live Graph API collector ready | ✅ 500 posts (100 per account) and ~1,400 comments from the scrapes of 16–17 Oct. Live collection starts after the Meta setup ([DEPLOYMENT.md](DEPLOYMENT.md) §3) |
| Audience comments (YouTube, X, Instagram) | **Real**, no author data | ✅ |
| SBA Hajj 1445H media statistics | **Real**, SBA open data (season totals) | ✅ |
| AWJ \| Sada podcast dataset | **Real**, curated (`newData/`, see `README_AWJ_Sada.txt`) | ✅ |
| Live broadcast signal | Simulated (`backend/data/broadcast_mock.json`) | Real YouTube live feed is future work |
| TikTok | Not collected: the API needs a weeks-long approval | Future work |

The dashboard and the pattern store show **real data only**. The synthetic files are kept as fixtures for the MVP endpoints and tests, and the live-clips page, which labels its signal as simulated.

---

## 🛠️ Tech Stack

* **Frontend:** React (TypeScript) + Vite, Tailwind CSS, Recharts, Lucide icons. RTL, light "enterprise" theme with royal-green accents
* **Backend:** FastAPI (Python 3.11), Google Gemini, with OpenAI as fallback (when `OPENAI_API_KEY` is set), YouTube Data API v3, Instagram Graph API, X API v2
* **Database:** PostgreSQL in production, SQLite locally (SQLAlchemy)
* **Security:** team-password login with signed tokens, per-IP rate limiting
* **Hosting:** Vercel (frontend) + Render (API + Postgres). CI on GitHub Actions

---

## 🚀 Local Development

```bash
# Backend (terminal 1)
pip install -r backend/requirements-dev.txt                             # runtime deps + pytest
cp backend/.env.example backend/.env                                    # add your own GEMINI_API_KEY (DEPLOYMENT.md §2)
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz # real SBA YouTube + X data, no key needed
for f in backend/data/dataset_instagram-scraper_*.json; do python -m backend.instagram_import "$f"; done   # SBA Instagram posts + comments
uvicorn backend.api:app --reload --port 8000

# Frontend (terminal 2)
npm install
npm run dev
```

Open `http://localhost:5173/`. Login is skipped locally while `SADA_ACCESS_PASSWORD` is empty. Run the tests with `pytest backend/tests -q`.

Only the lead holds `YOUTUBE_API_KEY` and `X_BEARER_TOKEN`. Everyone else works from the seed file, so we don't spend quota or money four times. To refresh your data, ask the lead for a new export.

**LLM key.** `GEMINI_API_KEY` (preferred, with `OPENAI_API_KEY` as fallback) is used for draft suggestions, optimizer variants, diagnosis wording, audience themes, topic refinement and comment classification. All of them go through `backend/agents/llm_client.py`, which rotates comma-separated keys and fallback models. Without a key:
- the optimizer still works if you pass `variants` in the draft, and the draft suggestion starts from the strongest recent post's title
- the diagnosis falls back to evidence-only wording
- topics stay rule-based, comments stay unclassified and audience themes are not generated

Pattern analysis, the playbook, root causes, trending, prediction, spike/drop detection and live-clip detection are pure statistics and never need a key.

---

## 🧩 Backend Reference

### Layout (`backend/`)

| Path | What |
|---|---|
| `api.py` | All routes; shared files are split into `# --- Task N ---` blocks |
| `schemas.py` | Pydantic request/response models (the JSON contracts) |
| `db.py`, `repository.py` | Tables and read helpers. **Use `repository.analysis_records()` for any analysis** |
| `analytics.py` | Dashboard summary (`GET /api/analytics/summary`), cached 60 s |
| `agents/` | One file per agent, plus helpers: the platform clients and collectors, `llm_client.py` (Gemini/OpenAI with key and model rotation) and `root_cause.py` (the levers behind a post's result, used by Alerts & Diagnosis) |
| `playbook.py` | Publishing playbook: one decision per topic (platform, account, content type, time) |
| `draft_suggest.py` | First draft for a new post, from the best recent posts on the topic |
| `saudi_context.py` | Shared by every LLM prompt: Saudi writing voice per tone, Riyadh date with the approximate Hijri date, Friday prayer, the current season (Ramadan, Eid, Hajj), upcoming national and Hijri occasions with how to mark them, and Saudi dialect cues for reading comments |
| `instagram_import.py` | Loads an Instagram scraper export into the tables |
| `sba_channels.py` | Verified SBA accounts per platform |
| `topics.py` | The 9-topic taxonomy |
| `auth.py`, `rate_limit.py`, `config.py` | Login, rate limits, env config |
| `db_tools.py` | Export/import the database as a seed file |
| `data/` | Real datasets, MVP fixtures and their parsers |
| `store/` | Local SQLite database and the pattern store (git-ignored) |

### Database

SQLite at `backend/store/sada.db` locally, Postgres on Render (`DATABASE_URL`).

| Table | Contents |
|---|---|
| `channels` | YouTube channels and Instagram/X accounts (`platform`): metadata + latest follower totals |
| `videos` | One row per post: title/caption, `url`, publish time (UTC), duration, `content_type` (short/video/live/image/carousel/text), `topic`, latest views/likes/comments. `NULL` when hidden; Instagram views are always `NULL`; X impressions are stored as views |
| `video_snapshots` | Stats at every refresh: the time series behind velocity, trending, prediction and alerts |
| `audience_comments` | Comment/reply text, time, likes and the LLM `sentiment` / `intent` labels. No author data |
| `audience_labels` | Blind human labels for a sample of comments, the ground truth for `GET /api/audience/accuracy` |
| `audience_themes` | Saved audience-theme analyses, one per exact comment set, so the same comments never cost a second model call |
| `diagnoses` | Saved LLM wording of a post's diagnosis, kept while its evidence is unchanged |
| `follower_snapshots` | Follower counts over time, for growth |
| `collector_runs` | One row per run: status, counts, quota spent, error |

There are no migrations (`create_all`). **If you see `SchemaOutdated` on startup**, delete `backend/store/sada.db` and re-import the seed.

### Data collection

```bash
python -m backend.agents.data_collector_agent --budget 1000         # all configured platforms
python -m backend.agents.data_collector_agent --platform x          # one platform: youtube | instagram | x
python -m backend.db_tools export backend/data/sba_youtube_seed.json.gz
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
```

A platform without credentials is skipped. Budgets, refresh schedules and per-platform details are in [AGENT_SPEC.md](AGENT_SPEC.md#1-data-collector-agent); key setup is in [DEPLOYMENT.md](DEPLOYMENT.md) sections 1–7. Keep `COLLECTOR_SCHEDULE_ENABLED=false` locally so `--reload` doesn't spend quota.

The shared seed (`sba_youtube_seed.json.gz`) holds the 9 YouTube channels (7,777 videos) and 5 X accounts (7,283 posts), with their snapshots, ~1,170 audience comments, human labels, follower counts, saved diagnoses and saved audience themes. It has no Instagram data: load that from the scraper exports.

**Instagram scraper exports.** `backend/data/dataset_instagram-scraper_*.json` are Apify instagram-scraper exports: `sbagovsa` (16 Oct, 100 posts) and `saudia.sa`, `alekhbariya.tv`, `riyadiyatv`, `sbc_channel` (17 Oct, 100 posts each), with their latest comments. Commenter identity fields (`owner`, `ownerUsername`, `ownerProfilePicUrl`) were stripped from the files; the importer never read them. Posts and comments land in the same tables and shape as the live collector. The scrape time (from the file name) is the snapshot time, so re-running adds nothing and never overwrites newer collector stats. Accounts not in `SBA_INSTAGRAM_ACCOUNTS` are skipped.

### Other datasets (`backend/data/`)

| File | Source | Used by |
|---|---|---|
| `raw/hajj_1445_media_stats.xlsx` → `hajj_1445_platform_totals.json` | **Real** SBA open data: Hajj 1445H reach totals per platform | Behavior agent (`source: real_hajj_1445_sba`) |
| `raw/awj_sada_data.json` → `awj_sada_real.json` | **Real** AWJ \| Sada package: 6 podcast episodes + 5 X posts (see `newData/README_AWJ_Sada.txt`) | Behavior agent (`source: real_awj_sada`), `POST /api/diagnose/awj-sada` |
| `engagement_records.json`, `content_history.json`, `broadcast_mock.json` | **Synthetic** MVP fixtures (`generate_seed_data.py`, deterministic) | Tests, `POST /api/diagnose`, the live-clip endpoints and page (labelled simulated). **Never shown on the dashboard** |

Regenerate them with `python -m backend.data.parse_hajj_1445_real_data`, `python -m backend.data.parse_awj_sada_real_data` and `python -m backend.data.generate_seed_data`. The Hajj and AWJ sources are far too small to t-test, so they produce plain descriptive comparisons with capped confidence, alongside the per-post patterns.

### API

Public:
- `GET  /health` - liveness probe
- `GET  /api/auth/status`, `POST /api/auth/login` - login (`{password}` → bearer token)

Authenticated (`Authorization: Bearer <token>` when `SADA_ACCESS_PASSWORD` is set). Endpoints that take `platform` accept `youtube`, `instagram` or `x`:

| Area | Endpoints |
|---|---|
| Data | `GET /api/channels`, `GET /api/videos` (filters `platform`, `channel`, `content_type`, `topic`, `days`, `sort`, `limit`, `offset`), `GET /api/videos/{video_id}` (with snapshots) |
| Collector | `GET /api/collector/status`, `POST /api/collector/run` |
| Patterns | `GET /api/patterns`, `POST /api/patterns/refresh` (rebuilds from the database) |
| Optimizer | `POST /api/optimize` (body `DraftContent`), `POST /api/draft/suggest` (`{topic, content_type, channel_options, tone}`), `GET /api/playbook?days=60` |
| Trends | `GET /api/trending?hours=24&limit=10`, `GET /api/model/accuracy` |
| Dashboard | `GET /api/analytics/summary?days=30&platform=` |
| Alerts & diagnosis | `GET /api/alerts?days=7`, `POST /api/diagnose/video` (`{video_id}`) |
| Audience | `GET /api/audience/summary?days=30&platform=`, `GET /api/audience/themes?days=30&platform=`, `GET /api/audience/accuracy`, `GET /api/audience/review/next?limit=1`, `POST /api/audience/review` (`{comment_id, sentiment, intent}`) |
| Live clips | `GET /api/broadcast/signal`, `POST /api/broadcast/detect-clips` (optional body: a signal to analyse instead of the simulated one) |
| MVP | `POST /api/diagnose`, `POST /api/diagnose/awj-sada` |

Errors:
- LLM-only endpoints return `503` if no LLM key is set, `502` if the model call fails, and `504` past `GEMINI_DEADLINE_SECONDS`.
- LLM-backed and login routes return `429` when rate limited.
- `/docs` is available only outside production.

The frontend calls the API through `src/lib/api.ts`, with `VITE_API_BASE` as the base URL.

### Running an agent directly

```bash
python -m backend.agents.behavior_analysis_agent
python -m backend.agents.trend_prediction_agent
python -m backend.agents.live_clip_detection_agent
```

The optimizer and Alerts & Diagnosis need an input (a draft, a post), so drive them through the API.

### Tests

```bash
pytest backend/tests -q
```

Each agent has its own test files, and each one asserts that agent's acceptance criteria. Platform APIs (YouTube, Instagram, X), OpenAI and Gemini are faked, so **no test needs a key or the network**. Tests run on a throwaway SQLite database (`backend/tests/conftest.py`). Set `SADA_TEST_DATABASE_URL` to run them against Postgres; CI runs both.

### Notes for reviewers

- `predicted_engagement` (optimizer) is a ranking index: 100 = baseline, with pattern lifts compounded multiplicatively. It is not a forecast to show raw in the UI.
- `Pattern` carries `dimension`, `slice_key`, `lift_pct` and `source` beyond the minimal spec shape, so the optimizer and diagnosis can match patterns without parsing Arabic text. It also carries `account_examples` (the pattern in up to 5 accounts' own raw numbers, e.g. 4,200 → 3,100 impressions) and `accounts_agree` / `accounts_total` (how many of those accounts point the same way).
- Cross-platform comparisons use `performance_index` only. "All platforms" view totals are YouTube views only, so X impressions are never summed with video views.
- Hijri dates in `saudi_context.py` come from the arithmetic Hijri calendar, within a day of Umm al-Qura, so prompts always present them as approximate.

---

## 📍 Status

**Done:** all four hackathon tasks (patterns & optimizer on real data, trends & measured accuracy, live dashboard & CI, spikes/drops & diagnosis), X collection, audience analysis (with themes and a measured accuracy), Instagram data for 5 accounts from scraper exports, the publishing playbook, draft suggestions, root-cause diagnosis, a Saudi context that follows the Hijri calendar (Ramadan, Eid, Hajj), and the live-clips page.

**Open:**
1. **Live Instagram collection.** The data is in from scraper exports; the live collector is built and tested but needs credentials. One person follows [DEPLOYMENT.md](DEPLOYMENT.md) §3 (≈1 hour): create the Meta app and token, check each handle in `SBA_INSTAGRAM_ACCOUNTS` ([backend/sba_channels.py](backend/sba_channels.py)) with the Business Discovery query, and send the token **privately** to the lead.
2. **X in production:** fill `X_BEARER_TOKEN` on Render once the X account has credit.
3. **Load test:** run 50 users against `/api/analytics/summary` and `/api/trending`, and put p95 latency and the error rate in the pitch.

**After the hackathon:**
- A real live signal for the Live Clip agent: live-chat messages per minute and concurrent viewers from SBA's YouTube live streams (Al Riyadiya has 72 in the database). Check first that the live-chat API works with our key and what it costs in quota.
- Per-user accounts instead of the shared password.
- Move the collector to a Render Cron Job and rate limits to Redis, so the API can scale past one instance.
- Schema migrations (Alembic) instead of `create_all`.
- TikTok, if Research API access is approved; otherwise TikTok Studio exports from SBA's social team.
- A Meta system-user token, so Instagram access doesn't expire after 60 days.
- Upgrade Postgres off the free plan (it expires after 30 days).

---

## 👥 Working on Sada

**Who owns what** (each area also owns its `backend/tests/test_*.py`):

| Area | Files |
|---|---|
| Patterns & Optimizer | `backend/agents/behavior_analysis_agent.py`, `content_optimizer_agent.py`, `backend/draft_suggest.py`, `backend/playbook.py`, `backend/saudi_context.py`, `src/components/OptimizerView.tsx`, `PatternStore.tsx`, `PublishingPlaybook.tsx` |
| Trends & Prediction | `backend/agents/trend_prediction_agent.py`, `src/components/TrendingPanel.tsx`, `AccuracyCard.tsx` |
| Dashboard & Delivery | `backend/analytics.py`, `src/components/DashboardView.tsx`, `ContextBar.tsx`, `src/App.tsx`, `Sidebar.tsx`, `vercel.json`, `.github/workflows/ci.yml` |
| Alerts & Diagnosis | `backend/agents/alerts_diagnosis_agent.py`, `root_cause.py`, `src/components/BroadcastView.tsx` (Alerts view), `AlertsPanel.tsx` |
| Live clips | `backend/agents/live_clip_detection_agent.py`, `src/components/LiveClipsView.tsx` |
| Audience | `backend/agents/audience_agent.py`, `src/components/AudienceView.tsx`, `AudienceInsights.tsx` |

**Shared files:** append only, inside your own `# --- Task N ---` block: `backend/api.py`, `backend/schemas.py`, `src/types/index.ts`.

**Locked files:** ask the team before touching `backend/db.py`, `backend/repository.py`, `backend/auth.py`, `backend/config.py`, `src/lib/api.ts`, `backend/agents/data_collector_agent.py`, `backend/agents/llm_client.py`, `backend/instagram_import.py`, or the platform clients and collectors (`youtube_client.py`, `instagram_*.py`, `x_*.py`, `audience_collector.py`).

**Rules:**
- **Small commits straight to `main`.** Keep CI green (pytest on SQLite + Postgres, frontend build).
- **API shapes are additive only.** Tell the team before changing one. `VideoOut` covers YouTube, X and Instagram: check `platform`, and use `url` for links.
- **Real numbers only.** If something can't be computed from the data, hide it or label it "تجريبي" / "محاكاة".
- **Never treat missing as zero.** Hidden likes, Instagram views and unclassified comments stay `null`.
- **Riyadh time** for anything hour- or day-based (`analysis_records()` already converts it).
- **Compare platforms only on `performance_index`.** YouTube views, X impressions and Instagram likes measure different things.
- **All HTTP goes through `apiFetch`** in `src/lib/api.ts`. New `/api` routes go on the authenticated `api` router.
- **Every agent output cites evidence:** a number, a sample size, or a link to a real post.
- **Every LLM prompt that writes for SBA or reads its audience uses `backend/saudi_context.py`.**
- **Don't spend quota or money from laptops.** Use the seed file; X is billed per post read.
- **No personal data.** Never store or show commenter names, handles or ids.
- **Keys stay private:** never commit them, paste them in chat or show them on screen. If one leaks, regenerate it ([DEPLOYMENT.md](DEPLOYMENT.md) §1).
