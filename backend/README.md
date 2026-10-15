# Sada Backend - Agent Intelligence (AGENT_SPEC.md Tasks 1-5)

Implements the agents specified in [AGENT_SPEC.md](../AGENT_SPEC.md): the
original four MVP agents (Tasks 1-4) plus the Data Collector agent (Task 5),
which gathers real SBA YouTube data into the database. There was no
pre-existing backend or `backend-buildout-prompt.md` in this repo, so the
data schemas, seed datasets and API contracts here were designed from
scratch, following AGENT_SPEC.md's documented field names/JSON shapes exactly.

## Setup

```bash
pip install -r backend/requirements-dev.txt   # runtime deps + pytest
cp backend/.env.example backend/.env   # then fill in GEMINI_API_KEY
```

`GEMINI_API_KEY` is only required for:
- Task 2's variant-generation step (skipped if you pass `variants` explicitly in the draft)
- Task 3's diagnosis narrative synthesis

Task 1 (behavior analysis) and Task 4 (live clip detection) are pure
statistics and never need an API key.

## Regenerating seed data

```bash
python -m backend.data.generate_seed_data
```

Writes `backend/data/engagement_records.json`, `content_history.json` and
`broadcast_mock.json`. The generator is seeded (deterministic) and bakes in
known correlations (video content_type outperforms, a weekday-afternoon
engagement dip, a national_event+platform-x spike, a deliberately sparse
"science" topic) so the agents have real signal to recover instead of noise.

## Real data: SBA Hajj 1445H media statistics

`backend/data/raw/hajj_1445_media_stats.xlsx` is a real open-data export
from SBA (season-level media reach totals per platform for Hajj season
1445H). It's a totals table, not per-post records like
`engagement_records.json` - each platform reports a different subset of
metrics (e.g. YouTube has no reported engagement figure, Meta has no
reported views figure).

```bash
python -m backend.data.parse_hajj_1445_real_data
```

Parses the raw sheet into `backend/data/hajj_1445_platform_totals.json`
(numbers only, null for anything a platform doesn't report). Task 1
(`behavior_analysis_agent.analyze_real_hajj_platforms`) turns this into its
own `platform_reach_real` patterns - each platform's share of a metric vs.
an equal split across the platforms that actually report it, and
engagement-rate comparisons scoped to platforms reporting the same
numerator/denominator pair. These run alongside (not instead of) the
synthetic per-post patterns, tagged `"source": "real_hajj_1445_sba"` vs.
`"source": "synthetic_seed_engagement_records"` on each `Pattern`, since the
two sources answer different questions: per-post patterns say what kind of
content works, the real totals say which platform carried Hajj season
reach.

## Real data: AWJ | Sada podcast/X dataset

`backend/data/raw/awj_sada_data.json` is a copy of the verified AWJ | Sada
data package (see `newData/README_AWJ_Sada.txt` in the repo root for its
collection scope and data-quality policy) - 6 real podcast episodes (3 from
رهان, 3 from SO) plus 5 publicly recovered X posts. No fabricated metrics
or reply text.

```bash
python -m backend.data.parse_awj_sada_real_data
```

Parses the raw episodes/X posts into `backend/data/awj_sada_real.json`,
aggregated by podcast (avg YouTube views/likes) and by X post relationship
(official `@Medhalpodcast` account vs. related amplification from other
accounts). Like the Hajj data above, this is far too few records (6
episodes, 5 posts) for Task 1's Welch-t-test pipeline, so
`behavior_analysis_agent.analyze_real_awj_sada` reports plain descriptive
comparisons instead (no significance test, confidence capped at 0.75),
tagged `"source": "real_awj_sada"` / `"dimension": "awj_sada_real"` in the
pattern store, alongside the synthetic and Hajj patterns rather than
replacing them.

## Real data: SBA YouTube channels + Instagram accounts (Data Collector agent)

`backend/agents/data_collector_agent.py` collects every upload from the last
`COLLECTOR_LOOKBACK_DAYS` (default 60) on the 9 official SBA YouTube channels
in `backend/sba_channels.py`, into the database in `backend/db.py` (SQLite
locally, Postgres on Render):

| Table | Contents |
|---|---|
| `channels` | YouTube channels and Instagram accounts (`platform`): metadata + subscriber/follower totals |
| `videos` | One row per YouTube video or Instagram post: title/caption, `url`, publish time (UTC), duration, `content_type` (short/video/live/image/carousel), `topic` (`backend/topics.py`), latest views/likes/comments (`NULL` when hidden; Instagram views are always `NULL`) |
| `video_snapshots` | Stats at every refresh - the time series behind velocity, trending and spike/drop detection |
| `collector_runs` | One row per run: status, counts, quota spent, error |

Each run spends at most `COLLECTOR_QUOTA_PER_RUN` YouTube units: new uploads
first, then stats refreshes prioritised by age (videos <2 days old every 30 min,
<7 days every 2 h, <30 days daily, older weekly). Topics are keyword/channel
rules on ingest, refined by Gemini for up to `COLLECTOR_LLM_CLASSIFY_PER_RUN`
videos per run. Shorts are detected heuristically (the API doesn't flag them):
<=60s, or <=180s and tagged `#shorts`.

Instagram (`instagram_collector.py`) reads the accounts in `SBA_INSTAGRAM_ACCOUNTS` through the Graph
API's Business Discovery. It needs `META_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID`
(setup: [DATA_COLLECTION.md](../DATA_COLLECTION.md) section 3) and is skipped without them.

```bash
python -m backend.agents.data_collector_agent --budget 1000        # collect all configured platforms
python -m backend.agents.data_collector_agent --platform instagram # one platform only
python -m backend.db_tools export backend/data/sba_youtube_seed.json.gz
python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz
```

For analysis, use `repository.analysis_records()`. It normalizes each post's main metric
(views on YouTube, likes + comments on Instagram) per account + content type into
`performance_index`, drops posts too young to compare, and converts times to Riyadh.

**Local database out of date?** If you see `SchemaOutdated` on startup, delete
`backend/store/sada.db` and re-import the seed.

## Running an agent directly

```bash
python -m backend.agents.behavior_analysis_agent
python -m backend.agents.live_clip_detection_agent
```

Tasks 2 and 3 are library functions (`content_optimizer_agent.run(draft)`,
`diagnostic_recommendation_agent.run(item)`) rather than scripts, since they
need an input payload - see `backend/schemas.py` for the shapes, or drive
them through the API below.

## Running the API

```bash
uvicorn backend.api:app --reload
```

Public:
- `GET  /health` - liveness probe
- `GET  /api/auth/status`, `POST /api/auth/login` - login (`{password}` -> bearer token)

Authenticated (`Authorization: Bearer <token>` when `SADA_ACCESS_PASSWORD` is set):
- `POST /api/patterns/refresh` - re-run Task 1, upserts the store
- `GET  /api/patterns` - read the current pattern store
- `POST /api/optimize` - Task 2, body = `DraftContent`
- `POST /api/diagnose` - Task 3, body = `PublishedItemMetrics`
- `POST /api/diagnose/awj-sada` - Task 3 on the real AWJ dataset
- `POST /api/broadcast/detect-clips`, `GET /api/broadcast/signal` - Task 4
- `GET  /api/channels` - tracked SBA channels with subscriber counts
- `GET  /api/videos` - collected videos; filters `channel`, `content_type`, `topic`, `days`, `sort`, `limit`, `offset`
- `GET  /api/videos/{video_id}` - one video with its stats snapshots
- `GET  /api/collector/status`, `POST /api/collector/run` - Task 5 runs and quota use

Error handling:
- LLM-dependent endpoints return `503` if `GEMINI_API_KEY` isn't set, `502` if the model call fails.
- Gemini and login routes return `429` when rate limited.
- `/docs` is available only outside production.

## Tests

```bash
pytest backend/tests -v
```

Each test file asserts its task's acceptance criterion from AGENT_SPEC.md
directly (pattern count and re-run stability for Task 1, ranked
variants with evidence for Task 2, distinct evidence-cited diagnoses for
over/under-performers for Task 3, correct spike detection vs. noise for
Task 4). None of the tests require an API key - the LLM calls in Tasks 2
and 3 are isolated behind `_generate_variants_via_llm` /
`_synthesize_via_llm`, and the tests exercise the deterministic
scoring/retrieval/evidence logic around them directly.

## Notes / things a reviewer should know

- `predicted_engagement` (Task 2) is an internal index, not a percentage -
  100 represents the dataset-wide baseline, and it compounds pattern lifts
  multiplicatively. It's meant for *ranking* candidates against each other,
  not as a literal forecast number to surface unstyled in a UI.
- Pattern objects carry a few fields beyond AGENT_SPEC.md's minimal shape
  (`dimension`, `slice_key`, `lift_pct`) so Tasks 2/3 can match a pattern to
  a draft/item programmatically instead of regexing the Arabic pattern text.
  The fields AGENT_SPEC.md documents (`pattern`, `supporting_metric`,
  `confidence`, `affected_content_types`) are unchanged.
- The frontend calls this API through `src/lib/api.ts`, using `VITE_API_BASE` as the base URL.
- Tests run on a throwaway SQLite database (`backend/tests/conftest.py`). Set
  `SADA_TEST_DATABASE_URL` to run the whole suite against Postgres instead.
