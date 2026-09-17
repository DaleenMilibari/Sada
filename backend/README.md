# Sada Backend - Agent Intelligence (team.md Tasks 1-4)

Implements the four agents specified in [team.md](../team.md). There was no
pre-existing backend or `backend-buildout-prompt.md` in this repo, so the
data schemas, seed datasets and API contracts here were designed from
scratch, following team.md's documented field names/JSON shapes exactly.

## Setup

```bash
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in ANTHROPIC_API_KEY
```

`ANTHROPIC_API_KEY` is only required for:
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

- `POST /api/patterns/refresh` - re-run Task 1 over the seed dataset, upserts the store
- `GET  /api/patterns` - read the current pattern store
- `POST /api/optimize` - Task 2, body = `DraftContent`
- `POST /api/diagnose` - Task 3, body = `PublishedItemMetrics`
- `POST /api/broadcast/detect-clips` - Task 4, body = optional signal override, else uses the seeded mock broadcast

LLM-dependent endpoints return `503` with a clear message if
`ANTHROPIC_API_KEY` isn't set, rather than failing silently.

## Tests

```bash
pytest backend/tests -v
```

Each test file asserts its task's acceptance criterion from team.md
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
- Pattern objects carry a few fields beyond team.md's minimal shape
  (`dimension`, `slice_key`, `lift_pct`) so Tasks 2/3 can match a pattern to
  a draft/item programmatically instead of regexing the Arabic pattern text.
  The fields team.md documents (`pattern`, `supporting_metric`,
  `confidence`, `affected_content_types`) are unchanged.
- Frontend rewiring (making `src/components/*View.tsx` call this API
  instead of their hardcoded mock data) is a follow-up, not part of this
  pass.
