# Sada — Agent Development Tasks (Team.md)

This file splits the remaining **agent intelligence** work into 4 independent tasks. Each task can be built by one person in their own file, against the stub contracts already wired into the backend (see `backend-buildout-prompt.md`). No task requires another task's code to exist first — each agent reads from the shared seed/mock data and returns its own structured JSON.

Every agent below is specified using the project's required Agentic AI fields (Goal, Input, Trigger, Tools, Data/Context, Reasoning task, Decision, Action/Output, Memory/state, Evidence, Failure/fallback) — do not simplify an agent down to a single LLM prompt; each should visibly choose between options, use evidence, and produce a structured decision.

---

## Task 1 — Behavior Analysis Agent

**Owner:** _(assign)_
**File:** `agents/behavior_analysis_agent.py`

- **Goal:** Detect engagement patterns, trends, and drop-off across content types, topics, formats, and timing, and maintain a continuously updated "pattern store" the other agents read from.
- **Input:** Historical engagement/interaction records (platform, content type, topic, format, publish time, views/likes/shares/watch-time, drop-off points).
- **Trigger:** Scheduled/batch run (e.g., on new data ingestion) or on-demand call from the dashboard.
- **Available tools:** Query/aggregation functions over the engagement dataset; (optional) simple statistical or trend-detection functions.
- **Data/context:** The seeded engagement dataset from the backend; no external APIs required for MVP.
- **Reasoning task:** Identify which content attributes (format, topic, timing, platform) correlate with higher/lower engagement; detect meaningful trend shifts, not noise.
- **Decision:** Which patterns are significant enough to surface (e.g., "video content on Platform X between 8–10pm outperforms by N%").
- **Action/output:** A structured pattern list: `{pattern, supporting_metric, confidence, affected_content_types}[]`, written to the shared pattern store the other two agents can read.
- **Memory/state:** The pattern store itself (can be a JSON file, table, or in-memory cache for MVP) — must persist between runs so it's "continuously updated," not recomputed from scratch each demo.
- **Evidence:** Each pattern must cite the underlying metric(s) it's derived from (numbers, not vibes).
- **Failure/fallback:** If insufficient data for a given slice, return no pattern for it rather than a low-confidence guess; never fabricate a trend.

**Acceptance criteria:** Given the seeded dataset, running this agent produces at least 3–5 distinct, evidence-backed patterns, and re-running it after new mock data is added updates the pattern store rather than duplicating it.

---

## Task 2 — Content & Publishing Optimizer Agent

**Owner:** _(assign)_
**File:** `agents/content_optimizer_agent.py`

- **Goal:** Evaluate a draft/candidate piece of content before publishing and recommend the best platform, timing, and content variant.
- **Input:** A draft content item (headline/caption/thumbnail options, content type, intended topic) plus the pattern store from Task 1.
- **Trigger:** Called when a media team member submits a draft for evaluation via the dashboard.
- **Available tools:** Read access to the pattern store (Task 1's output); a scoring/ranking function; optionally an LLM call to generate 2–4 headline/caption variants if none are supplied.
- **Data/context:** The draft content, the pattern store, and historical performance of similar past content.
- **Reasoning task:** Compare the draft (and its variants) against known engagement patterns to predict relative performance; compare candidate publishing times/platforms against each other, not in isolation.
- **Decision:** Which variant to recommend, and the best platform + time window to publish it.
- **Action/output:** `{recommended_variant, predicted_engagement, recommended_platform, recommended_time, ranked_alternatives[], evidence[]}` — evidence should reference specific patterns from Task 1's store.
- **Memory/state:** Stateless per call is fine for MVP (reads pattern store, doesn't need its own persistent memory).
- **Evidence:** Every recommendation must point to the specific pattern(s) it relied on (from Task 1), not a generic LLM justification.
- **Failure/fallback:** If the pattern store has no relevant pattern for this content type, say so explicitly and fall back to the highest-confidence general pattern available, flagged as lower-confidence.

**Acceptance criteria:** Given a mock draft, the agent returns a ranked list of variants/platform/time combinations with at least one evidence citation per recommendation, not just a single unexplained answer.

---

## Task 3 — Diagnostic & Recommendation Agent (RAG-grounded)

**Owner:** _(assign)_
**File:** `agents/diagnostic_recommendation_agent.py`

- **Goal:** Explain why a published piece of content over- or under-performed, grounded in historical evidence, and produce actionable recommendations.
- **Input:** A published content item's actual performance metrics, plus its metadata (topic, format, platform, time).
- **Trigger:** Called when a user selects a published item on the dashboard and asks "why did this perform this way," or automatically for items that significantly beat/missed predicted engagement from Task 2.
- **Available tools:** A retrieval function over historical content/performance records (RAG — can be a simple vector search over Chroma/local embeddings, or a well-scoped keyword/metadata filter for MVP if a full vector DB is overkill); read access to the pattern store from Task 1.
- **Data/context:** Historical SBA-style content/performance records (seeded/mock), the item being diagnosed, and Task 1's pattern store.
- **Reasoning task:** Retrieve genuinely comparable past content (similar topic/format/platform), compare the item's actual performance to that baseline and to Task 1's patterns, and identify the most likely contributing factor(s) — do not just restate the metrics back as prose.
- **Decision:** Which factor(s) most plausibly explain the outcome, ranked by how well-supported they are by retrieved evidence.
- **Action/output:** `{diagnosis, contributing_factors[], each_with: {reason, supporting_metric, evidence_source_title, evidence_url_or_ref, confidence}, recommendations[]}`.
- **Memory/state:** Stateless per call for MVP; relies on the retrieval index being built once at startup from the seed data.
- **Evidence:** This is the agent where the evidence requirement matters most — every claim needs a source title + reference, kept compact per the UI's evidence format (recommendation → short reason → metric → evidence link), not a wall of retrieved text.
- **Failure/fallback:** If retrieval finds no comparable past content, say the diagnosis is low-confidence due to lack of comparable history, rather than inventing a plausible-sounding explanation.

**Acceptance criteria:** Given a mock underperforming and a mock overperforming item, the agent returns different, specific, evidence-cited explanations for each — not interchangeable generic text.

---

## Task 4 — Live Clip Detection Agent

**Owner:** _(assign)_
**File:** `agents/live_clip_detection_agent.py`

- **Goal:** Identify real-time engagement spikes during a live broadcast that correspond to specific broadcast moments, and flag them as social-clip opportunities.
- **Input:** A stream (or, for MVP, a mock time-series) of engagement/interaction signal during a live broadcast, timestamped and aligned to broadcast moments/segments.
- **Trigger:** Continuous/periodic check during a simulated live broadcast window, or a "run on this mock broadcast" button in the demo.
- **Available tools:** Spike/anomaly detection over the time series; a lookup mapping timestamps to broadcast segment metadata (e.g., segment title/topic) if available.
- **Data/context:** The mock live engagement time series plus segment metadata; can reuse the pattern store from Task 1 for context (e.g., is this spike unusually large relative to normal engagement for this content type).
- **Reasoning task:** Distinguish a genuine spike worth clipping from normal fluctuation, and identify the moment/segment the spike is tied to (not just "engagement went up at 14:32" but "up during the segment about X").
- **Decision:** Which moments cross the threshold for a recommended clip, and how to rank multiple candidates if several spikes occur.
- **Action/output:** `{clip_opportunity: {start_time, end_time, segment_label, spike_magnitude, confidence}}[]`, ranked by confidence/magnitude.
- **Memory/state:** Needs to track a rolling baseline of "normal" engagement during the broadcast to detect deviation — this can be simple (rolling average/stddev), doesn't need to be sophisticated for MVP.
- **Evidence:** Each flagged clip should report the magnitude of deviation from baseline as its evidence, plus the segment it aligns to.
- **Failure/fallback:** If the engagement signal is too noisy/flat to detect a confident spike, return no clip opportunities rather than forcing a low-confidence flag.

**Acceptance criteria:** Fed a mock time series with 1–2 obvious spikes and some noise, the agent flags the real spikes (with correct segment alignment) and does not flag the noise.

---

## Shared rules for all 4 tasks

- Use the exact field names and JSON shapes already defined by the backend stubs — do not rename fields for your own file.
- Every agent returns structured JSON the frontend can consume directly; no free-form prose blobs.
- Every recommendation/diagnosis must be traceable to a specific number or retrieved source — this is what makes Sada credible against the evaluation criteria, not "an AI dashboard."
- If you need data your teammate's agent produces (e.g., Task 2 needs Task 1's pattern store), code against the **documented shape** in this file, not against their actual in-progress code — that's what keeps the four tasks independent.
- Flag any place where you had to guess a field/shape instead of finding it in the backend stub, so it can be reconciled before integration.