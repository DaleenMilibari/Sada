# Sada — Next Steps (Frontend Integration)

[team.md](team.md)'s four agents are built and tested in [backend/](backend/) (see [backend/README.md](backend/README.md)), but the React frontend still renders 100% hardcoded mock data — none of the three views call the backend yet. This file splits that integration work into 4 independent tasks, one per agent/view pairing. As with team.md, each task can be built by one person without waiting on the others.

---

## How to Run This Project

Two independent processes, two terminals.

**Backend** (from the repo root):

```bash
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env      # fill in GEMINI_API_KEY - needed for Task 2 & 3 tasks below
python -m backend.agents.behavior_analysis_agent   # populates backend/store/pattern_store.json once
uvicorn backend.api:app --reload --port 8000
```

**Frontend** (from the repo root, in a second terminal):

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. The API is now live at `http://localhost:8000` — see `backend/README.md` for the full endpoint list.

**Backend tests** (no server needed): `pytest backend/tests -v`

---

## Shared prerequisite — enable CORS (do this first, blocks all 4 tasks)

`backend/api.py` has no CORS policy yet. The Vite dev server (`localhost:5173`) calling the API (`localhost:8000`) will be blocked by the browser until this is added. Whoever picks up Task A first should add:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

to `backend/api.py`, right after `app = FastAPI(...)`.

---

## Task A — Wire Dashboard to the Pattern Store (Task 1)

**File:** [src/components/DashboardView.tsx](src/components/DashboardView.tsx)

- Replace the hardcoded `patternsList` array with a `fetch("http://localhost:8000/api/patterns")` on mount, typed against `Pattern` in `backend/schemas.py` (`pattern_id`, `pattern`, `supporting_metric`, `confidence`, `affected_content_types`, `dimension`, `slice_key`, `lift_pct`).
- Wire the existing "تحديث" (refresh) button to `POST /api/patterns/refresh` instead of the fake `setTimeout`.
- The category filter pills (`فيديو`/`توقيت`/`محلي`) currently filter on a made-up `category` field — remap them to filter on the real `dimension` value (`content_type` / `timing` / `topic_platform`) instead.
- The top metric cards and the platform-breakdown chart (`weeklyData`, `platforms`) aren't produced by any of the 4 agents — leave them mocked for now; wiring them is a separate future analytics task, not part of team.md's scope.
- **Done when:** the pattern cards on load match whatever `GET /api/patterns` currently returns (5 patterns against the seed data), and clicking refresh visibly re-fetches.

## Task B — Wire Optimizer to the Content Optimizer Agent (Task 2)

**File:** [src/components/OptimizerView.tsx](src/components/OptimizerView.tsx)

- Replace `handleOptimize`'s fake 3-step `setTimeout` chain with a real `POST /api/optimize` call, body = `DraftContent` (`content_type`, `topic`, `platform_options` from the selected platform buttons, `original_text` = the textarea content). Omit `variants` so the backend generates them via Gemini — this requires `GEMINI_API_KEY` to be set (see setup above); surface the `503` response as a toast if it's missing, don't fail silently.
- Replace the hardcoded `OPTIMIZED_CONTENT` / `ORIGINAL_CONTENT` / `ALT_CONTENT` / `HASHTAGS` with the response's `recommended_variant` (winner card) and `ranked_alternatives` (the other cards).
- The winner card's rationale line ("صيغة سؤال تفاعلي...") should come from `evidence[].pattern` in the response instead of being static text.
- The timing capsule ("التوقيت المقترح للنشر") should show `recommended_time` from the response.
- **Done when:** typing a real draft and clicking "تحسين واختبار المتغيرات" shows agent-generated variants and a winner that changes based on the input, not always the same 3 strings.

## Task C — Wire Broadcast Monitor to the Live Clip Detection Agent (Task 4)

**File:** [src/components/BroadcastView.tsx](src/components/BroadcastView.tsx)

- Replace the hardcoded `TIMELINE` array with a `POST /api/broadcast/detect-clips` call on mount (no body → uses the seeded mock broadcast in `backend/data/broadcast_mock.json`).
- The response is a ranked list of `{ clip_opportunity: { start_time, end_time, segment_label, spike_magnitude, confidence } }`. Use the top-ranked one to drive the "تنبيه لقطة فيروسية مكتشفة" alert box (currently hardcoded to "12:04" / "45%" / "الدعم السكني").
- The bar chart currently renders from `TIMELINE`'s coarse hourly buckets — the real signal is sampled every 10s over 1200s (`backend/data/broadcast_mock.json`); either down-sample it client-side to a similar number of bars, or widen the chart's x-axis.
- **Done when:** the alert box and the highlighted bar(s) reflect the actual spike(s) the agent detects (2, in the current seed data), not the fixed 12:04 example.

## Task D — Wire Diagnostic Chat to the RAG Agent (Task 3)

**File:** [src/components/BroadcastView.tsx](src/components/BroadcastView.tsx) (chat section)

This one needs a small scope decision before coding: team.md's Task 3 is triggered by *selecting a specific published item*, not by open-ended free-text chat. The current UI is a free-text chat box, which doesn't map 1:1 onto `POST /api/diagnose`'s input (`PublishedItemMetrics` — a specific `content_id`, platform, metrics, etc.).

Recommended approach:
- Add a lightweight "select content to diagnose" affordance (e.g. a dropdown of a few mock published items, or reuse the existing `SUGGESTIONS` prompts as pre-wired triggers, each mapped to one hardcoded `PublishedItemMetrics` payload).
- On selection, call `POST /api/diagnose` and render `diagnosis` as the agent's message text, `contributing_factors[]` as the bulleted cards (replacing the 3 hardcoded ones in `AGENT_RESPONSE`), and `recommendations[]` under them. Populate the message's `sources` from each factor's `evidence_source_title`.
- Requires `GEMINI_API_KEY`; handle the `503` the same way as Task B.
- Leave genuinely free-text questions (e.g. "ما الكلمات الأكثر تداولاً؟") out of scope — they don't map to any of the 4 backend agents today.
- **Done when:** selecting a mock published item produces a diagnosis in the chat that's grounded in that item's real numbers (verify by picking both an over- and under-performing mock item and confirming the explanations genuinely differ).

---

## Shared rules for all 4 tasks

- Don't invent new response fields — match `backend/schemas.py` exactly; if the UI needs something the backend doesn't return, that's a sign to extend the schema (flag it) rather than fake it client-side.
- Keep the loading-state UX each view already has (spinners, step indicators) — just point it at real request latency instead of a fixed `setTimeout`.
- If `GEMINI_API_KEY` isn't set, Tasks B and D must show a clear error state, not a silent failure or fabricated content.
