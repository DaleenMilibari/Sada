# Sada Backend

FastAPI service that runs the agents in [AGENT_SPEC.md](../AGENT_SPEC.md) over a shared database of real SBA posts.

## Setup

```bash
pip install -r backend/requirements-dev.txt   # runtime deps + pytest
cp backend/.env.example backend/.env           # then fill in GEMINI_API_KEY
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz   # real SBA YouTube + X data, no key needed
for f in backend/data/dataset_instagram-scraper_*.json; do python -m backend.instagram_import "$f"; done   # SBA Instagram
uvicorn backend.api:app --reload --port 8000
```

`GEMINI_API_KEY` (preferred, with `OPENAI_API_KEY` as fallback) is used for draft suggestions, optimizer variants, diagnosis narratives, audience themes, topic refinement and comment classification. All of them go through `agents/llm_client.py`, which rotates comma-separated keys and fallback models. Without a key:
- the optimizer still works if you pass `variants` in the draft, and the draft suggestion starts from the strongest recent post's title
- the video diagnosis falls back to evidence-only wording
- topics stay rule-based, comments stay unclassified and audience themes are not generated

Pattern analysis, the publishing playbook, root causes, trending, prediction and anomaly detection are pure statistics and never need a key.

## Layout

| Path | What |
|---|---|
| `api.py` | All routes; shared files are split into `# --- Task N ---` blocks |
| `schemas.py` | Pydantic request/response models (the JSON contracts) |
| `db.py`, `repository.py` | Tables and read helpers. **Use `repository.analysis_records()` for any analysis** |
| `analytics.py` | Dashboard summary (`GET /api/analytics/summary`), cached 60 s |
| `agents/` | One file per agent, plus the platform clients and collectors, `llm_client.py` (OpenAI/Gemini with key and model rotation) and `root_cause.py` (levers behind a post's result) |
| `playbook.py` | Publishing playbook: one decision per topic (platform, account, content type, time) |
| `draft_suggest.py` | First draft for a new post, from the best recent posts on the topic |
| `saudi_context.py` | Saudi writing voice, Riyadh calendar and dialect cues shared by every LLM prompt |
| `instagram_import.py` | Loads an Instagram scraper export into the tables |
| `sba_channels.py` | Verified SBA accounts per platform |
| `topics.py` | The 9-topic taxonomy |
| `auth.py`, `rate_limit.py`, `config.py` | Login, rate limits, env config |
| `db_tools.py` | Export/import the database as a seed file |
| `data/` | Real datasets, MVP fixtures and their parsers |
| `store/` | Local SQLite database and the pattern store (git-ignored) |

## Database

SQLite at `backend/store/sada.db` locally, Postgres on Render (`DATABASE_URL`).

| Table | Contents |
|---|---|
| `channels` | YouTube channels and Instagram/X accounts (`platform`): metadata + latest follower totals |
| `videos` | One row per post: title/caption, `url`, publish time (UTC), duration, `content_type` (short/video/live/image/carousel/text), `topic`, latest views/likes/comments. `NULL` when hidden; Instagram views are always `NULL`; X impressions are stored as views |
| `video_snapshots` | Stats at every refresh: the time series behind velocity, trending, prediction and anomalies |
| `audience_comments` | Comment/reply text, time, likes and the LLM `sentiment` / `intent` labels. No author data |
| `audience_labels` | Blind human labels for a sample of comments, the ground truth for `GET /api/audience/accuracy` |
| `audience_themes` | Saved audience-theme analyses, one per exact comment set, so the same comments never cost a second model call |
| `diagnoses` | Saved LLM wording of a post's diagnosis, kept while its evidence is unchanged |
| `follower_snapshots` | Follower counts over time, for growth |
| `collector_runs` | One row per run: status, counts, quota spent, error |

There are no migrations (`create_all`). **If you see `SchemaOutdated` on startup**, delete `backend/store/sada.db` and re-import the seed.

## Data collection

```bash
python -m backend.agents.data_collector_agent --budget 1000         # all configured platforms
python -m backend.agents.data_collector_agent --platform x          # one platform: youtube | instagram | x
python -m backend.db_tools export backend/data/sba_youtube_seed.json.gz
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
```

A platform without credentials is skipped. Budgets, refresh schedules and per-platform details are in [AGENT_SPEC.md](../AGENT_SPEC.md#1-data-collector-agent). API key setup is in [DEPLOYMENT.md](../DEPLOYMENT.md) sections 1–7. Keep `COLLECTOR_SCHEDULE_ENABLED=false` locally so `--reload` doesn't spend quota.

The shared seed (`sba_youtube_seed.json.gz`) holds the 9 YouTube channels (7,777 videos) and 5 X accounts (7,283 posts), with their snapshots, ~1,170 audience comments, human labels, follower counts, saved diagnoses and saved audience themes. It has no Instagram data: load that from the scraper exports.

### Instagram scraper exports

`data/dataset_instagram-scraper_*.json` are Apify instagram-scraper exports: `sbagovsa` (16 Oct, 100 posts) and `saudia.sa`, `alekhbariya.tv`, `riyadiyatv`, `sbc_channel` (17 Oct, 100 posts each), with their latest comments. Commenter identity fields (`owner`, `ownerUsername`, `ownerProfilePicUrl`) were stripped from the files; the importer never read them.

```bash
python -m backend.instagram_import backend/data/dataset_instagram-scraper_2026-10-17_18-01-36-700.json
```

Posts and comments land in the same tables and shape as the live collector. The scrape time (from the file name) is the snapshot time, so re-running adds nothing and never overwrites newer collector stats. Accounts not in `SBA_INSTAGRAM_ACCOUNTS` are skipped.

## Other datasets (`backend/data/`)

| File | Source | Used by |
|---|---|---|
| `raw/hajj_1445_media_stats.xlsx` → `hajj_1445_platform_totals.json` | **Real** SBA open data: Hajj 1445H reach totals per platform | Behavior agent (`source: real_hajj_1445_sba`) |
| `raw/awj_sada_data.json` → `awj_sada_real.json` | **Real** AWJ \| Sada package: 6 podcast episodes + 5 X posts (see `newData/README_AWJ_Sada.txt`) | Behavior agent (`source: real_awj_sada`), `POST /api/diagnose/awj-sada` |
| `engagement_records.json`, `content_history.json`, `broadcast_mock.json` | **Synthetic** MVP fixtures (`generate_seed_data.py`, deterministic) | Tests, `POST /api/diagnose`, the live-clip endpoints. **Never shown on the dashboard** |

Regenerate them with `python -m backend.data.parse_hajj_1445_real_data`, `python -m backend.data.parse_awj_sada_real_data` and `python -m backend.data.generate_seed_data`.

The Hajj and AWJ sources are far too small to t-test, so they produce plain descriptive comparisons with capped confidence, alongside the per-post patterns.

## API

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
| MVP | `POST /api/diagnose`, `POST /api/diagnose/awj-sada`, `POST /api/broadcast/detect-clips`, `GET /api/broadcast/signal` |

Errors:
- LLM-only endpoints return `503` if no LLM key is set, `502` if the model call fails, and `504` past `GEMINI_DEADLINE_SECONDS`.
- LLM-backed and login routes return `429` when rate limited.
- `/docs` is available only outside production.

The frontend calls the API through `src/lib/api.ts`, with `VITE_API_BASE` as the base URL.

## Running an agent directly

```bash
python -m backend.agents.behavior_analysis_agent
python -m backend.agents.trend_prediction_agent
python -m backend.agents.live_clip_detection_agent
```

The optimizer and diagnosis agents need an input payload, so drive them through the API.

## Tests

```bash
pytest backend/tests -q
```

Each agent has its own test file, and each one asserts that agent's acceptance criteria. Platform APIs (YouTube, Instagram, X), OpenAI and Gemini are faked, so **no test needs a key or the network**. Tests run on a throwaway SQLite database (`backend/tests/conftest.py`). Set `SADA_TEST_DATABASE_URL` to run them against Postgres; CI runs both.

## Notes for reviewers

- `predicted_engagement` (optimizer) is a ranking index: 100 = baseline, with pattern lifts compounded multiplicatively. It is not a forecast to show raw in the UI.
- `Pattern` carries `dimension`, `slice_key`, `lift_pct` and `source` beyond the minimal spec shape, so the optimizer and diagnosis can match patterns without parsing Arabic text. It also carries `account_examples` (the pattern in up to 5 accounts' own raw numbers, e.g. 4,200 → 3,100 impressions) and `accounts_agree` / `accounts_total` (how many of those accounts point the same way).
- Cross-platform comparisons use `performance_index` only. "All platforms" view totals are YouTube views only, so X impressions are never summed with video views.
